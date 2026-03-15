/**
 * system.ts — Canonical type definitions for the Aethelgard console.
 *
 * These types mirror the Pydantic models exposed by the FastAPI backend
 * and are the single source of truth for all frontend type usage.
 *
 * NOTE: Do NOT extend or diverge from backend models without updating api.py.
 */

// ─── Stage / Pipeline ────────────────────────────────────────────────────────

export type StageKey =
  | "detection"
  | "diagnosis"
  | "remediation"
  | "validation"
  | "deployment";

export type Severity = "info" | "warning" | "error" | "success";

export type RuntimeStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "rolled_back"
  | "deduplicated";

export type TimelineStageStatus =
  | "success"
  | "failed"
  | "rolled_back"
  | "deduplicated"
  | "pending"
  | "running";

// ─── API Response Shapes ─────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
  agents_active: number;
  environment: string;
  rag_backend: string | null;
}

export interface OpsMetrics {
  activePipelines: number;
  dedupRatio: number;
  failedHealth: number;
  avgLatency: number;
  mttdSeconds: number;
  mttrSeconds: number;
  autonomousResolutionRate: number;
}

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

export interface TimelineStage {
  stage: string;
  status: TimelineStageStatus;
  timestamp: string;
  details?: string;
}

export interface TimelineResponse {
  job_id: string;
  status: string;
  timeline: TimelineStage[];
}

export interface SpanAttributes {
  service_name?: string;
  anomaly_type?: string;
  patch_type?: string;
  risk_score?: number;
  validation_latency?: number;
}

export interface Span {
  id?: string;
  span_id?: string;
  name: string;
  duration: number;
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

// ─── UI / View Models ─────────────────────────────────────────────────────────

export interface StageMeta {
  key: StageKey;
  label: string;
  color: string;
  short: string;
  /** Lucide icon component — typed loosely to avoid importing lucide here. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon: any;
  fallbackDurationMs: number;
}

export interface StageView extends StageMeta {
  spanId: string;
  status: RuntimeStatus;
  durationMs: number;
  confidence: number;
  /** Offset from pipeline start in milliseconds (used for timeline math). */
  startMs: number;
  /** Absolute end offset in milliseconds (used for timeline math). */
  endMs: number;
  timestamp: string;
  service: string;
  message: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  severity: Severity;
  stage: StageKey;
  service: string;
  message: string;
  /** Links this log to a distributed trace. */
  traceId?: string;
  /** Links this log to a specific pipeline span for correlation. */
  spanId?: string;
}

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
