import { useMemo, useState, useRef, useEffect } from "react";
import { Info, Clock, Activity, Target, ShieldCheck, Server, PanelRight } from "lucide-react";
import { type StageView, type PipelineJobDetail, STAGES, humanizeToken, formatDuration } from "../utils/console";

export interface PipelineCanvasProps {
  stages: StageView[];
  detail: PipelineJobDetail | null;
  selectedStageIndex: number;
  onSelectStage: (index: number | null) => void;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
  isDiagOpen: boolean;
  onToggleDiag: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatMs(ms: number) {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

// ── Component ────────────────────────────────────────────────────────────────

export default function PipelineCanvas({
  stages,
  detail,
  selectedStageIndex,
  onSelectStage,
  selectedSpanId,
  onSelectSpan,
  isDiagOpen,
  onToggleDiag,
}: PipelineCanvasProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Time math ──────────────────────────────────────────────────────────────
  // We compute global pipeline bounds based on all stages
  const { totalDuration, pipelineStart } = useMemo(() => {
    if (!stages.length) return { totalDuration: 0, pipelineStart: 0 };
    const start = Math.min(...stages.map(s => s.startMs));
    const end   = Math.max(...stages.map(s => s.endMs));
    return {
      totalDuration: Math.max(end - start, 1), 
      pipelineStart: start,
    };
  }, [stages]);

  const overallStatus = detail?.status || "standby";

  // ── Tooltip positioning ───────────────────────────────────────────────────
  const tooltipStyle = useMemo(() => {
    const margin = 20;
    const tooltipWidth = 220;
    const tooltipHeight = 160;
    let x = mousePos.x + 15;
    let y = mousePos.y + 15;

    if (x + tooltipWidth > window.innerWidth - margin) x = mousePos.x - tooltipWidth - 15;
    if (y + tooltipHeight > window.innerHeight - margin) y = mousePos.y - tooltipHeight - 15;

    return { left: x, top: y };
  }, [mousePos]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <section className="pipeline-panel">
      {/* Header */}
      <div className="pipeline-header-bar">
        <div>
          <p className="panel-kicker">Pipeline Execution</p>
          <p style={{ fontSize: 12, fontWeight: 500, color: "var(--text-dim)", marginTop: 3 }}>Trace Timeline</p>
        </div>
        <div className="pipeline-meta-strip">
          <span className={`pipeline-status-${overallStatus === "completed" ? "ok" : overallStatus === "failed" ? "err" : "live"}`}>
            {humanizeToken(overallStatus, "standby")}
          </span>
          {detail && (
            <>
              <span>trace_{detail.job_id.slice(0, 8)}</span>
              <span>{formatDuration(totalDuration)}</span>
            </>
          )}
          <button 
            type="button"
            className={`diag-toggle-btn ${isDiagOpen ? "active" : ""}`}
            onClick={onToggleDiag}
            title="Toggle Technical Diagnostics"
          >
            <PanelRight size={14} />
          </button>
        </div>
      </div>

      <div className="pipeline-body" ref={containerRef}>
        <div className="pipeline-timeline-inner">
          {/* Axis Row */}
          <div className="trace-col-layout trace-axis-row">
            <div /> <div /> <div /> <div /> <div />
            <div style={{ height: 20 }}>
              <div className="trace-axis-tick" style={{ left: "0%" }}>0ms</div>
              <div className="trace-axis-tick" style={{ left: "25%" }}>{formatDuration(totalDuration * 0.25)}</div>
              <div className="trace-axis-tick" style={{ left: "50%" }}>{formatDuration(totalDuration * 0.5)}</div>
              <div className="trace-axis-tick" style={{ left: "75%" }}>{formatDuration(totalDuration * 0.75)}</div>
              <div className="trace-axis-tick" style={{ left: "100%" }}>{formatDuration(totalDuration)}</div>
            </div>
          </div>

          {/* Headings */}
          <div className="trace-col-layout trace-table-head">
            <div>Stage</div>
            <div>Start</div>
            <div>End</div>
            <div>Dur.</div>
            <div>Conf.</div>
            <div>Timeline</div>
          </div>

          {/* Stages */}
          <div style={{ position: "relative" }}>
            {stages.map((stage, idx) => {
              const isSelected = selectedStageIndex === idx;
              const isDimmed = selectedStageIndex !== -1 && !isSelected;
              const st = stage.startMs;
              const en = stage.endMs;

              // Absolute math for offset and width
              const offsetPct = ((st - pipelineStart) / totalDuration) * 100;
              const widthPct  = Math.max(((en - st) / totalDuration) * 100, 0.5);

              // Connector line from previous stage end to this stage start
              let connector = null;
              if (idx > 0) {
                const prev = stages[idx-1];
                const prevEnd = prev.endMs;
                const prevX = ((prevEnd - pipelineStart) / totalDuration) * 100;
                const thisX = offsetPct;

                // Basic vertical + horizontal step connector
                // Vertical part: current row center up to previous row center
                // Horizontal part: prev end to current start
                connector = (
                  <div
                    className="trace-stage-connector"
                    style={{
                      left: `${Math.min(prevX, thisX)}%`,
                      width: `${Math.abs(thisX - prevX)}%`,
                      top: "-14px", // half of row height (28px) 
                      height: "14px",
                    }}
                  >
                    <div className="trace-stage-connector-arrow" />
                  </div>
                );
              }

              return (
                <button
                  key={stage.key}
                  type="button"
                  className={`span-row trace-col-layout ${isSelected ? "is-selected" : ""} ${isDimmed ? "is-dimmed" : ""}`}
                  onClick={() => onSelectStage(isSelected ? null : idx)}
                  onMouseMove={(e) => {
                    setMousePos({ x: e.clientX, y: e.clientY });
                    setHoveredIdx(idx);
                  }}
                  onMouseLeave={() => setHoveredIdx(null)}
                >
                  {/* Stage Name */}
                  <div className="span-name">
                    {idx === selectedStageIndex ? (
                      <Activity size={12} className="pipeline-status-live" />
                    ) : (
                      <Server size={12} style={{ color: "var(--text-faint)" }} />
                    )}
                    {stage.label}
                  </div>

                  {/* Timing fields */}
                  <div className="span-field">{formatDuration(st - pipelineStart)}</div>
                  <div className="span-field">{formatDuration(en - pipelineStart)}</div>
                  <div className="span-field hi">{formatDuration(en - st)}</div>
                  <div className="span-field">{Math.round((stage.confidence || 0.9) * 100)}%</div>

                  {/* Timeline Axis */}
                  <div className="span-timeline-cell">
                    {connector}
                    <div className="span-grid-guides">
                      <div /><div /><div /><div />
                    </div>
                    <div
                      className="span-bar"
                      style={{
                        left: `${offsetPct}%`,
                        width: `${widthPct}%`,
                        backgroundColor: stage.color,
                        boxShadow: isSelected ? `0 0 8px ${stage.color}` : "none",
                      }}
                    />
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Hover Tooltip */}
      {hoveredIdx !== null && stages[hoveredIdx] && (
        <div className="span-tooltip" style={tooltipStyle}>
          <div className="span-tooltip-header">{stages[hoveredIdx].label}</div>
          <div className="span-tooltip-row">
            <span>Service</span>
            <span>{stages[hoveredIdx].service || "orchestrator"}</span>
          </div>
          <div className="span-tooltip-row">
            <span>Duration</span>
            <span>{formatDuration(stages[hoveredIdx].endMs - stages[hoveredIdx].startMs)}</span>
          </div>
          <div className="span-tooltip-row">
            <span>Confidence</span>
            <span>{Math.round((stages[hoveredIdx].confidence || 0) * 100)}%</span>
          </div>
          <div className="span-tooltip-row">
            <span>Status</span>
            <span style={{ color: stages[hoveredIdx].status === "failed" ? "var(--err)" : "var(--ok)" }}>
              {stages[hoveredIdx].status}
            </span>
          </div>
          <div className="span-tooltip-trace">
            span: {detail?.job_id?.slice(0, 12)}_stage_{stages[hoveredIdx].key}
          </div>
        </div>
      )}
    </section>
  );
}
