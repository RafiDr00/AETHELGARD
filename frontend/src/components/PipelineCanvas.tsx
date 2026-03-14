import type { PipelineJobDetail } from "../types/api";
import {
  type StageView,
  clamp,
  formatDuration,
  formatPercent,
  humanizeToken,
} from "../utils/console";

export interface PipelineCanvasProps {
  stages: StageView[];
  detail: PipelineJobDetail | null;
  selectedStageIndex: number;
  onSelectStage: (index: number) => void;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
}

export default function PipelineCanvas({ stages, detail, selectedStageIndex, onSelectStage, selectedSpanId, onSelectSpan }: PipelineCanvasProps) {
  const pipelineStart = Math.min(...stages.map(s => s.startMs));
  const pipelineEnd = Math.max(...stages.map(s => s.endMs));
  const totalDuration = Math.max(pipelineEnd - pipelineStart, 1);
  const tickCount = 5;
  const tickStep = totalDuration / tickCount;
  const axisTicks = Array.from({ length: tickCount + 1 }, (_, index) => ({
    label: formatDuration(Math.round(index * tickStep)),
    pos: (index / tickCount) * 100,
  }));

  const orderedStages = [...stages].sort((a, b) => a.startMs - b.startMs);

  return (
    <section className="pipeline-panel flex flex-col h-full bg-slate-900/40 rounded-lg border border-slate-800 p-4">
      <div className="panel-header pipeline-header mb-6 relative">
        <div className="flex flex-row justify-between items-end w-full">
          <div>
            <p className="panel-kicker text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1">PIPELINE EXECUTION</p>
            <h2 className="text-xl font-medium text-slate-100">Trace Timeline</h2>
          </div>
          <div className="pipeline-summary-strip flex gap-4 text-sm text-slate-400 font-mono">
            <span>{humanizeToken(detail?.status, "standby")}</span>
            <span>{formatDuration((detail?.duration_seconds ?? 0) * 1000)}</span>
            <span>{detail?.service ?? "orchestrator"}</span>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* TRACE TABLE HEADER */}
        <div className="grid grid-cols-[140px_80px_80px_80px_90px_1fr] gap-4 pb-2 border-b border-slate-700/50 text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2 font-mono px-2">
          <div>Stage Name</div>
          <div>Start</div>
          <div>End</div>
          <div>Duration</div>
          <div>Confidence</div>
          <div className="pl-2 border-l border-slate-700/50">Timeline</div>
        </div>

        {/* TIMELINE AXIS */}
        <div className="grid grid-cols-[140px_80px_80px_80px_90px_1fr] gap-4 items-center px-2 py-1 mb-1 text-[10px] text-slate-500 font-mono">
          <div />
          <div />
          <div />
          <div />
          <div />
          <div className="relative pl-2 border-l border-transparent h-4">
            {axisTicks.map((tick, i) => (
              <span
                key={i}
                className="absolute transform -translate-x-1/2 whitespace-nowrap first:translate-x-0 last:translate-x-[-100%]"
                style={{ left: `${tick.pos}%` }}
              >
                {tick.label}
              </span>
            ))}
          </div>
        </div>

        {/* TRACE TABLE BODY */}
        <div className="flex flex-col gap-[2px] relative mt-1">
          {orderedStages.map((stage, index) => {
            const originalIndex = stages.findIndex(s => s.key === stage.key);
            const widthPercentage = ((stage.endMs - stage.startMs) / totalDuration) * 100;
            const leftPercentage = ((stage.startMs - pipelineStart) / totalDuration) * 100;
            const width = clamp(widthPercentage, 0.5, 100);
            const left = clamp(leftPercentage, 0, 99.5);

            const Icon = stage.icon;
            const isRunning = stage.status === "running";
            const isFailed = stage.status === "failed" || stage.status === "rolled_back";
            const stageSpanId = `span-${stage.key}`;
            const isSpanHighlighted = selectedSpanId !== null && selectedSpanId === stageSpanId;
            const hasSpanSelection = selectedSpanId !== null;
            const isDimmed = hasSpanSelection && !isSpanHighlighted;

            const rowBg = selectedStageIndex === originalIndex ? "bg-slate-800/80 ring-1 ring-slate-700" : "hover:bg-slate-800/40";
            const barPulseClass = isRunning ? "trace-running" : "";

            return (
              <button
                key={stage.key}
                type="button"
                onClick={() => {
                  onSelectStage(originalIndex);
                  onSelectSpan(isSpanHighlighted ? null : stageSpanId);
                }}
                className={`grid grid-cols-[140px_80px_80px_80px_90px_1fr] gap-4 items-center w-full py-2 px-2 rounded transition-colors text-left text-sm relative group ${rowBg}`}
              >
                <div className="flex items-center gap-2 font-medium overflow-hidden whitespace-nowrap text-ellipsis" style={{ color: stage.color }}>
                  <Icon size={14} className="shrink-0" />
                  {stage.label}
                </div>

                <div className="text-slate-400 font-mono text-xs whitespace-nowrap font-medium">
                  {formatDuration(stage.startMs)}
                </div>
                <div className="text-slate-400 font-mono text-xs whitespace-nowrap font-medium">
                  {formatDuration(stage.endMs)}
                </div>
                <div className="text-slate-300 font-mono text-xs">
                  {formatDuration(stage.durationMs)}
                </div>
                <div className="text-slate-300 font-mono text-xs">
                  {formatPercent(stage.confidence)}
                </div>

                {/* Timeline Horizontal Bar */}
                <div className="relative h-6 w-full flex items-center border-l border-slate-700/50 pl-2">
                  {/* Vertical Connector (except for last element) */}
                  {index < orderedStages.length - 1 && (
                    <div className="absolute left-[-1px] top-6 bottom-[-24px] w-[1px] bg-slate-600/30 z-0" />
                  )}

                  {/* Grid Lines Context */}
                  <div className="pointer-events-none absolute inset-0 w-full h-full opacity-10 flex border-l border-transparent">
                    <div className="border-r border-slate-500 w-1/4 h-full" />
                    <div className="border-r border-slate-500 w-1/4 h-full" />
                    <div className="border-r border-slate-500 w-1/4 h-full" />
                    <div className="border-r border-slate-500 w-1/4 h-full" />
                  </div>

                  {/* The execution block (utilizes transform for perf) */}
                  <div
                    className="absolute inset-y-0 flex items-center w-full"
                    style={{ transform: `translateX(${left}%)` }}
                  >
                    <div
                      className={`h-2.5 rounded-sm transition-colors duration-300 ${barPulseClass}`}
                      title={`${stage.label}\n${formatDuration(stage.startMs)} \u2192 ${formatDuration(stage.endMs)}\n${stage.durationMs}ms\nconfidence ${formatPercent(stage.confidence)}`}
                      style={{
                        width: `${width}%`,
                        background: isFailed ? "var(--state-error, #ef4444)" : stage.color,
                        boxShadow: isSpanHighlighted
                          ? `0 0 0 1px color-mix(in srgb, ${stage.color} 85%, white), 0 0 16px color-mix(in srgb, ${stage.color} 55%, transparent)`
                          : isRunning
                            ? `0 0 10px ${stage.color}, 0 0 20px ${stage.color}`
                            : "none",
                        opacity: isDimmed ? 0.35 : stage.status === "pending" ? 0.25 : 1
                      }}
                    />
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
