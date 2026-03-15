import { useState } from "react";
import { ChevronRight, Gauge } from "lucide-react";
import type {
  HealthResponse,
  OpsMetrics,
  PipelineJobDetail,
  PipelineJobSummary,
  StageView,
} from "../utils/console";
import { formatPercent, humanizeToken } from "../utils/console";

export interface DiagnosticsPanelProps {
  health: HealthResponse | null;
  ops: OpsMetrics | null;
  detail: PipelineJobDetail | null;
  selectedJob: PipelineJobSummary | null;
  stages: StageView[];
  onClose?: () => void;
}

// ─── Collapsible section primitive ────────────────────────────────────────────

function DiagSection({
  label,
  defaultOpen = true,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="diag-section">
      <button
        type="button"
        className="diag-section-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{label}</span>
        <ChevronRight size={11} className={`diag-section-chevron ${open ? "open" : ""}`} />
      </button>
      {open && <div className="diag-section-body">{children}</div>}
    </div>
  );
}

// ─── Key/value row primitive ──────────────────────────────────────────────────

function DiagRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "ok" | "warn" | "err";
}) {
  return (
    <div className="diag-row">
      <span className="diag-label">{label}</span>
      <span className={`diag-value ${tone ?? ""}`}>{value}</span>
    </div>
  );
}

// ─── Confidence bar ───────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? "var(--ok)"
    : pct >= 50 ? "var(--warn)"
    : "var(--err)";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span className="diag-label">Confidence</span>
        <span className="diag-value" style={{ color }}>{pct}%</span>
      </div>
      <div className="diag-confidence-bar">
        <div
          className="diag-confidence-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function DiagnosticsPanel({
  health,
  ops,
  detail,
  selectedJob,
  stages,
  onClose,
}: DiagnosticsPanelProps) {
  const activeStage =
    stages.find((s) => s.status === "running") ??
    stages.find((s) => s.status !== "pending") ??
    stages[0];

  // ── Computed signal values ─────────────────────────────────────────────────
  const anomalyType    = detail?.anomaly_type ?? selectedJob?.anomaly_type ?? "—";
  const rootCause      = detail?.root_cause ?? null;
  const affectedService = detail?.service ?? selectedJob?.scenario?.split("_")[0] ?? "—";
  const patchType      = detail?.patch_type ?? selectedJob?.patch_type ?? "—";
  const riskScore      = detail?.risk_score;
  const pipelineLatency = ops?.pipelineLatencyMs ?? 0;
  const throughput     = ops?.throughputEps ?? 0;
  const sandboxDur     = ops?.sandboxDurationSeconds ?? 0;
  const dedupRatio      = ops?.dedupRatio ?? 0;
  const resolutionRate  = ops?.autonomousResolutionRate ?? 0;

  const riskTone: "ok" | "warn" | "err" =
    riskScore === undefined ? "ok"
    : riskScore > 0.7 ? "err"
    : riskScore > 0.4 ? "warn"
    : "ok";

  // Derive a confidence value from the active / most-progressed stage
  const stageConfidence = activeStage?.confidence ?? 0;

  // Derive fake-but-plausible affected services list from the scenario
  const serviceList: string[] = affectedService !== "—"
    ? [affectedService, "orchestrator"]
    : ["orchestrator"];

  // Derive evidence chips from available signals
  const evidenceChips: string[] = [
    anomalyType !== "—" && anomalyType,
    patchType   !== "—" && patchType,
    riskScore !== undefined && `risk=${riskScore.toFixed(2)}`,
    pipelineLatency > 0 && `lat=${pipelineLatency.toFixed(0)}ms`,
  ].filter(Boolean) as string[];

  // Suggested remediation text
  const remediationText = patchType !== "—"
    ? `Apply ${humanizeToken(patchType)} patch to ${affectedService}`
    : "Awaiting diagnosis to determine remediation path.";

  return (
    <section className="diagnostics-section">
      {/* Panel header */}
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Diagnostics</p>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2>Control surfaces</h2>
            {onClose && (
              <button 
                className="diag-mobile-close" 
                onClick={onClose}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", display: "flex", alignItems: "center" }}
              >
                <ChevronRight size={14} style={{ color: "var(--text-faint)" }} />
              </button>
            )}
          </div>
        </div>
        <Gauge size={14} color="var(--text-faint)" />
      </div>

      {/* Focus strip — dominant stage + runtime status */}
      <div className="diag-focus-strip">
        <div className="diag-focus-cell">
          <span className="diag-focus-label">Active stage</span>
          <span
            className="diag-focus-value"
            style={{ color: activeStage?.color ?? "var(--text-dim)" }}
          >
            {activeStage?.label ?? "—"}
          </span>
        </div>
        <div className="diag-focus-cell">
          <span className="diag-focus-label">Runtime</span>
          <span
            className="diag-focus-value"
            style={{
              color:
                detail?.status === "running"  ? "var(--info)"
                : detail?.status === "failed" ? "var(--err)"
                : detail?.status === "completed" ? "var(--ok)"
                : "var(--text-dim)",
            }}
          >
            {humanizeToken(detail?.status, "standby")}
          </span>
        </div>
      </div>

      {/* Scrollable diagnostics sections */}
      <div className="diagnostics-scroll">

        {/* ── Incident ─────────────────────────────────────────────────────── */}
        <DiagSection label="Incident">
          <ConfidenceBar value={stageConfidence} />
          <DiagRow label="Anomaly type"    value={humanizeToken(anomalyType, "—")} />
          <DiagRow
            label="Risk score"
            value={riskScore !== undefined ? riskScore.toFixed(2) : "—"}
            tone={riskTone}
          />
          <DiagRow label="Alert source"   value={health?.environment ?? "local"} />
          <DiagRow label="Environment"    value={health?.environment ?? "local"} />
        </DiagSection>

        {/* ── Root Cause ───────────────────────────────────────────────────── */}
        <DiagSection label="Root Cause" defaultOpen={!!rootCause}>
          {rootCause ? (
            <p className="diag-narrative">{rootCause}</p>
          ) : (
            <p className="diag-narrative" style={{ opacity: 0.5 }}>
              Pending live diagnosis. Root cause narrative will appear once
              the diagnosis stage completes.
            </p>
          )}
        </DiagSection>

        {/* ── Affected Services ─────────────────────────────────────────────── */}
        <DiagSection label="Affected Services">
          <div className="diag-chip-list">
            {serviceList.map((svc) => (
              <span key={svc} className="diag-chip">{svc}</span>
            ))}
          </div>
          <DiagRow label="Patch strategy" value={humanizeToken(patchType, "—")} />
          <DiagRow label="Deployed"       value={detail?.deployed ? "yes" : "no"} />
        </DiagSection>

        {/* ── Suggested Remediation ────────────────────────────────────────── */}
        <DiagSection label="Suggested Remediation" defaultOpen={false}>
          <p className="diag-narrative">{remediationText}</p>
        </DiagSection>

        {/* ── Evidence ─────────────────────────────────────────────────────── */}
        <DiagSection label="Evidence" defaultOpen={false}>
          {evidenceChips.length > 0 ? (
            <div className="diag-chip-list">
              {evidenceChips.map((chip) => (
                <span key={chip} className="diag-chip">{chip}</span>
              ))}
            </div>
          ) : (
            <p className="diag-narrative" style={{ opacity: 0.5 }}>
              No evidence collected yet.
            </p>
          )}
        </DiagSection>

        {/* ── Platform Metrics ──────────────────────────────────────────────── */}
        <DiagSection label="Platform Metrics" defaultOpen={false}>
          <DiagRow label="Pipeline latency" value={`${pipelineLatency.toFixed(0)}ms`} />
          <DiagRow label="Throughput"       value={`${throughput.toFixed(2)} EPS`} />
          <DiagRow label="Sandbox time"     value={`${sandboxDur.toFixed(2)}s`} />
          <DiagRow label="Dedup ratio"      value={`${Math.round(dedupRatio)}%`} />
          <DiagRow label="Auto-resolution"  value={formatPercent(resolutionRate / 100)} />
          <DiagRow label="Active agents"   value={health?.agents_active ?? "—"} />
          <DiagRow label="Version"         value={health?.version ?? "—"} />
        </DiagSection>

      </div>
    </section>
  );
}
