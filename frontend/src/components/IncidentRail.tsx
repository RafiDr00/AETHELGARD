import { useMemo, useState } from "react";
import { Info, AlertTriangle, CheckCircle, Activity, Server, Hash } from "lucide-react";
import { type PipelineJobSummary, STAGES, humanizeToken } from "../utils/console";

export interface IncidentRailProps {
  jobs: PipelineJobSummary[];
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getSeverity(anomalyType?: string, status?: string) {
  if (status === "completed") return "ok";
  const type = (anomalyType || "").toLowerCase();
  if (type.includes("critical") || type.includes("exhaust")) return "critical";
  if (type.includes("high") || type.includes("fail")) return "error";
  if (type.includes("unstable") || type.includes("warn")) return "warning";
  return "info";
}

function getAlertSource(scenario?: string) {
  const s = (scenario || "").toLowerCase();
  if (s.includes("prom") || s.includes("alert")) return "prometheus:alert";
  if (s.includes("k8s") || s.includes("oom")) return "k8s:oom-kill";
  if (s.includes("api") || s.includes("latency")) return "api:gateway";
  if (s.includes("db") || s.includes("stat")) return "pg_stat:monitor";
  return "aethelgard:detector";
}

function getAffectedServices(scenario?: string, anomalyType?: string): string[] {
  const text = `${scenario} ${anomalyType}`.toLowerCase();
  const found = new Set<string>();
  if (text.includes("api") || text.includes("gateway")) found.add("api-gateway");
  if (text.includes("index") || text.includes("search")) found.add("search-svc");
  if (text.includes("order")) found.add("order-svc");
  if (text.includes("db") || text.includes("postgres") || text.includes("data")) found.add("postgres");
  if (text.includes("auth")) found.add("auth-svc");
  if (found.size === 0) found.add("orchestrator");
  return Array.from(found);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function IncidentRail({
  jobs,
  selectedJobId,
  onSelect,
}: IncidentRailProps) {
  // ── Render system status if no incidents ─────────────────────────────────
  if (jobs.length === 0) {
    return (
      <section className="rail-section">
        <div className="panel-header">
          <div className="rail-label">
            <p className="panel-kicker">Incident Feed</p>
            <h2>System Standby</h2>
          </div>
          <span className="panel-value rail-label">IDLE</span>
        </div>

        <div className="rail-empty">
          <Activity size={32} strokeWidth={1.5} style={{ color: "var(--ok)", opacity: 0.6 }} />
          <div>
            <p style={{ fontWeight: 500, color: "var(--text)", marginBottom: 4 }}>Armed and Ready</p>
            <p style={{ fontSize: 11, color: "var(--text-faint)", lineHeight: 1.4 }}>
              Observability agents are monitoring telemetry streams. No active anomalies detected.
            </p>
          </div>

          <div style={{ marginTop: 24, width: "100%", padding: "0 16px" }}>
            <div className="diag-row" style={{ border: 0 }}>
              <span className="diag-label">Agents</span>
              <span className="diag-value">05 ACTIVE</span>
            </div>
            <div className="diag-row" style={{ border: 0 }}>
              <span className="diag-label">Stream</span>
              <span className="diag-value ok">LATENCY 4ms</span>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="rail-section">
      <div className="panel-header">
        <div className="rail-label">
          <p className="panel-kicker">Incident Feed</p>
          <h2>Execution queue</h2>
        </div>
        <span className="panel-value rail-label">{String(jobs.length).padStart(2, "0")}</span>
      </div>

      <div className="rail-list">
        {jobs.map((job) => {
          const sev = getSeverity(job.anomaly_type, job.status);
          const source = getAlertSource(job.scenario);
          const services = getAffectedServices(job.scenario, job.anomaly_type);
          const isSelected = selectedJobId === job.job_id;

          return (
            <button
              key={job.job_id}
              className={`rail-item ${isSelected ? "selected" : ""}`}
              onClick={() => onSelect(job.job_id)}
            >
              <div className="rail-item-topline">
                <span className={`sev-badge sev-${sev}`}>{sev}</span>
                <span className="rail-duration">
                  {job.duration_seconds ? `${Math.round(job.duration_seconds)}s` : "live"}
                </span>
              </div>

              <p className="rail-scenario">{job.scenario || "Unknown Incident"}</p>

              <div className="rail-services">
                {services.map((svc) => (
                  <span key={svc} className="rail-service-chip">{svc}</span>
                ))}
              </div>

              <div className="rail-meta">
                <Server size={10} style={{ color: "var(--text-faint)" }} />
                <span>{source}</span>
              </div>

              <div className={`job-status job-${job.status}`}>
                {humanizeToken(job.status, "standby")}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
