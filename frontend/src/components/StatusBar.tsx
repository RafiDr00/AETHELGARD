import type {
  HealthResponse,
  OpsMetrics,
  PipelineJobDetail,
  PipelineJobSummary,
} from "../types/api";
import { formatRelativeUpdate, humanizeToken } from "../utils/console";

interface MetricChipProps {
  label: string;
  value: string;
  tone: "info" | "success" | "warning" | "error";
}

function MetricChip({ label, value, tone }: MetricChipProps) {
  return (
    <div className={`metric-chip tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export interface StatusBarProps {
  health: HealthResponse | null;
  ops: OpsMetrics | null;
  selectedJob: PipelineJobSummary | null;
  detail: PipelineJobDetail | null;
  updatedAt: Date | null;
  live: boolean;
}

export default function StatusBar({ health, ops, selectedJob, detail, updatedAt, live }: StatusBarProps) {
  const healthTone = health?.status === "healthy" ? "success" : "warning";
  const incidentTone = detail?.status === "failed" ? "error" : detail?.status === "completed" ? "success" : "info";

  return (
    <div className="statusbar-grid">
      <div className="statusbar-titleblock">
        <div>
          <p className="statusbar-kicker">AETHELGARD / INCIDENT RESPONSE CONSOLE</p>
          <h1>Engineering mission control</h1>
        </div>
        <p className="statusbar-subtitle">Trace-driven response orchestration with dense terminal telemetry.</p>
      </div>

      <div className="statusbar-strip">
        <MetricChip label="Fabric" value={live ? "Live" : "Degraded"} tone={live ? "success" : "warning"} />
        <MetricChip label="Health" value={health?.status ?? "Unknown"} tone={healthTone} />
        <MetricChip label="Pipelines" value={`${ops?.activePipelines ?? 0}`} tone="info" />
        <MetricChip label="Autonomy" value={ops ? `${Math.round(ops.autonomousResolutionRate)}%` : "--"} tone="info" />
        <MetricChip label="Incident" value={humanizeToken(selectedJob?.scenario, "Standby")} tone={incidentTone} />
      </div>

      <div className="statusbar-meta">
        <span>{formatRelativeUpdate(updatedAt)}</span>
        <span>{health?.environment ?? "local"}</span>
        <span>{selectedJob?.job_id ?? "no-job-selected"}</span>
      </div>
    </div>
  );
}
