// ─────────────────────────────────────────────────────────────────────────────
// Aethelgard API — TypeScript type definitions
// Mirrors the Pydantic models in api.py exactly.
// ─────────────────────────────────────────────────────────────────────────────

// ── /health ──────────────────────────────────────────────────────────────────
export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
  agents_active: number;
  environment: string;
  rag_backend: string | null;
}

// ── /api/v1/metrics (PlatformMetrics from core/models.py) ──────────────────────────────────────
export interface PlatformMetrics {
  timestamp: string;
  total_anomalies_detected: number;
  total_fixes_deployed: number;
  total_rollbacks: number;
  avg_mttd_seconds: number;
  avg_mttr_seconds: number;
  engineering_hours_saved: number;
  roi_dollars: number;
  autonomous_resolution_rate: number;
  manual_workflows_reduced_pct: number;
  infrastructure_inefficiency_reduced_pct: number;
  active_agents: number;
  events_processed: number;
  knowledge_base_entries: number;
}

// ── /api/v1/metrics/ops (OperationsMetricsResponse) ───────────────────────────────────────
export interface OpsMetrics {
  activePipelines: number;
  dedupRatio: number;
  failedHealth: number;
  avgLatency: number;
  mttdSeconds: number;
  mttrSeconds: number;
  autonomousResolutionRate: number;
}

// ── /api/v1/pipeline/jobs ───────────────────────────────────────────────────
export interface PipelineJobSummary {
  job_id: string;
  scenario: string;
  status: "pending" | "running" | "completed" | "failed";
  duration_seconds?: number;
  anomaly_type?: string;
  patch_type?: string;
  remediation_status?: string;
  failure_stage?: string;
  failure_reason?: string;
}

export interface PipelineJobsResponse {
  count: number;
  jobs: PipelineJobSummary[];
}

// ── /api/v1/pipeline/jobs/{id} (PipelineJobStatus) ─────────────────────────
export interface PipelineJobDetail {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed" | "awaiting_approval";
  scenario: string;
  duration_seconds?: number;
  error?: string;
  anomaly_detected?: boolean;
  service?: string;
  anomaly_type?: string;
  root_cause?: string;
  patch_type?: string;
  remediation_status?: string;
  failure_stage?: string;
  failure_reason?: string;
  risk_score?: number;
  deployed?: boolean;
  mttd_seconds?: number;
  mttr_seconds?: number;
}

// ── /api/v1/remediation/{id}/timeline ────────────────────────────────────────
export type TimelineStageStatus = "success" | "failed" | "rolled_back" | "deduplicated" | "pending" | "running";

export interface TimelineStage {
  stage: string;
  status: TimelineStageStatus;
  timestamp: string;   // HH:MM:SS
  details?: string;
}

export interface TimelineResponse {
  job_id: string;
  status: string;
  timeline: TimelineStage[];
}

// ── /api/v1/pipeline/{id}/spans ──────────────────────────────────────────────
export interface SpanAttributes {
  service_name?: string;
  anomaly_type?: string;
  patch_type?: string;
  risk_score?: number;
  validation_latency?: number;
}

export interface Span {
  name: string;
  duration: number;    // milliseconds
  status?: string;
  timestamp?: string;
  details?: string;
  attributes?: SpanAttributes;
}

export interface SpansResponse {
  job_id: string;
  trace_name?: string;
  status?: string;
  spans: Span[];
}

// ── /api/v1/metrics/history ─────────────────────────────────────────────────
export interface RemediationRecord {
  id: string;
  anomaly_type: string;
  service: string;
  severity: string;
  root_cause: string;
  patch_type: string;
  remediation_status: string;
  failure_stage: string | null;
  failure_reason: string | null;
  risk_score: number;
  was_successful: boolean;
  mttd_seconds: number;
  mttr_seconds: number;
  completed_at: string;
}

export interface MetricsHistoryResponse {
  count: number;
  records: RemediationRecord[];
}

// ── /api/v1/pipeline/run (POST) ──────────────────────────────────────────────
export interface PipelineRunRequest {
  scenario: string;
}

export interface PipelineJobAccepted {
  job_id: string;
  status: string;
  scenario: string;
  message: string;
  poll_url: string;
}
