import { Gauge, TerminalSquare } from "lucide-react";
import type {
  HealthResponse,
  OpsMetrics,
  PipelineJobDetail,
  PipelineJobSummary,
} from "../types/api";
import { type StageView, humanizeToken } from "../utils/console";

export interface DiagnosticsPanelProps {
  health: HealthResponse | null;
  ops: OpsMetrics | null;
  detail: PipelineJobDetail | null;
  selectedJob: PipelineJobSummary | null;
  stages: StageView[];
}

export default function DiagnosticsPanel({ health, ops, detail, selectedJob, stages }: DiagnosticsPanelProps) {
  const activeStage = stages.find((stage) => stage.status === "running") ?? stages.find((stage) => stage.status !== "pending") ?? stages[0];
  const rows = [
    { label: "Service", value: detail?.service ?? "orchestrator" },
    { label: "Anomaly", value: detail?.anomaly_type ?? selectedJob?.anomaly_type ?? "Awaiting classification" },
    { label: "Patch", value: detail?.patch_type ?? selectedJob?.patch_type ?? "Unassigned" },
    { label: "Risk", value: detail?.risk_score !== undefined ? detail.risk_score.toFixed(2) : "--" },
    { label: "MTTD", value: detail?.mttd_seconds !== undefined ? `${detail.mttd_seconds.toFixed(3)}s` : `${ops?.mttdSeconds?.toFixed(3) ?? "--"}s` },
    { label: "MTTR", value: detail?.mttr_seconds !== undefined ? `${detail.mttr_seconds.toFixed(2)}s` : `${ops?.mttrSeconds?.toFixed(2) ?? "--"}s` },
    { label: "Dedup", value: ops !== undefined ? `${Math.round(ops?.dedupRatio ?? 0)}%` : "--" },
    { label: "Environment", value: health?.environment ?? "local" },
  ];

  return (
    <section className="diagnostics-section">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">DIAGNOSTICS</p>
          <h2>Control surfaces</h2>
        </div>
        <Gauge size={16} />
      </div>

      <div className="diagnostics-focus">
        <div>
          <span>Dominant stage</span>
          <strong style={{ color: activeStage.color }}>{activeStage.label}</strong>
        </div>
        <div>
          <span>Runtime status</span>
          <strong>{humanizeToken(detail?.status, "standby")}</strong>
        </div>
      </div>

      <dl className="diagnostics-list">
        {rows.map((row) => (
          <div key={row.label} className="diagnostics-row">
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>

      <div className="diagnostics-footer">
        <div>
          <TerminalSquare size={15} />
          <span>{detail?.root_cause ?? "Root cause narrative pending live diagnosis."}</span>
        </div>
      </div>
    </section>
  );
}
