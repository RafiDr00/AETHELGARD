import { ChevronRight, Radar } from "lucide-react";
import type { PipelineJobSummary } from "../utils/console";
import { formatDuration, humanizeToken } from "../utils/console";

export interface IncidentRailProps {
  jobs: PipelineJobSummary[];
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

export default function IncidentRail({ jobs, selectedJobId, onSelect }: IncidentRailProps) {
  return (
    <section className="rail-section">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">INCIDENT FEED</p>
          <h2>Execution queue</h2>
        </div>
        <span className="panel-value">{jobs.length.toString().padStart(2, "0")}</span>
      </div>

      <div className="rail-list">
        {jobs.length === 0 ? (
          <div className="rail-empty">
            <Radar size={18} />
            <span>No active incidents. Console remains armed.</span>
          </div>
        ) : (
          jobs.map((job) => {
            const selected = selectedJobId === job.job_id;
            return (
              <button
                key={job.job_id}
                type="button"
                className={`rail-item ${selected ? "selected" : ""}`}
                onClick={() => onSelect(job.job_id)}
              >
                <div className="rail-item-topline">
                  <span className={`job-status job-${job.status}`}>{job.status}</span>
                  <span className="rail-duration">{formatDuration((job.duration_seconds ?? 0) * 1000)}</span>
                </div>
                <div className="rail-scenario">{humanizeToken(job.scenario)}</div>
                <div className="rail-meta">
                  <span>{job.anomaly_type ?? "unknown anomaly"}</span>
                  <ChevronRight size={14} />
                  <span>{job.patch_type ?? "pending patch"}</span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
