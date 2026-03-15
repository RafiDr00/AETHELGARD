import {
  Activity,
  CheckCircle2,
  Cpu,
  Radar,
  ShieldCheck,
} from "lucide-react";
import { create } from "zustand";

// ─── API types (mirrors Pydantic models in api.py) ──────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
  agents_active: number;
  environment: string;
  rag_backend: string | null;
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

export interface OpsMetrics {
  activePipelines: number;
  dedupRatio: number;
  failedHealth: number;
  pipelineLatencyMs: number;
  throughputEps: number;
  sandboxDurationSeconds: number;
  autonomousResolutionRate: number;
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

export type TimelineStageStatus = "success" | "failed" | "rolled_back" | "deduplicated" | "pending" | "running";

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

export type StageKey = "detection" | "diagnosis" | "remediation" | "validation" | "deployment";
export type Severity = "info" | "warning" | "error" | "success";
export type RuntimeStatus = "pending" | "running" | "success" | "failed" | "rolled_back" | "deduplicated";

export interface StageMeta {
  key: StageKey;
  label: string;
  color: string;
  short: string;
  icon: typeof Radar;
  fallbackDurationMs: number;
}

export interface StageView extends StageMeta {
  spanId: string;
  status: RuntimeStatus;
  durationMs: number;
  confidence: number;
  startMs: number;
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
  traceId?: string;
  spanId?: string;
}

export const STAGES: StageMeta[] = [
  { key: "detection", label: "Detection", color: "var(--stage-detection)", short: "DET", icon: Radar, fallbackDurationMs: 280 },
  { key: "diagnosis", label: "Diagnosis", color: "var(--stage-diagnosis)", short: "DGN", icon: Cpu, fallbackDurationMs: 540 },
  { key: "remediation", label: "Remediation", color: "var(--stage-remediation)", short: "RMD", icon: Activity, fallbackDurationMs: 460 },
  { key: "validation", label: "Validation", color: "var(--stage-validation)", short: "VAL", icon: ShieldCheck, fallbackDurationMs: 320 },
  { key: "deployment", label: "Deployment", color: "var(--stage-deployment)", short: "DPL", icon: CheckCircle2, fallbackDurationMs: 180 },
];

export const STATUS_COPY: Record<RuntimeStatus, string> = {
  pending: "Queued",
  running: "Live",
  success: "Stable",
  failed: "Failed",
  rolled_back: "Rolled back",
  deduplicated: "Deduplicated",
};

export const SEVERITY_GLYPH: Record<Severity, string> = {
  info: "I",
  warning: "W",
  error: "E",
  success: "S",
};

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function formatDuration(ms?: number) {
  if (!ms || Number.isNaN(ms)) {
    return "--";
  }

  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
  }

  return `${Math.round(ms)} ms`;
}

export function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }

  return `${Math.round(value * 100)}%`;
}

export function formatTimestamp(value?: string) {
  if (!value) {
    return "--:--:--";
  }

  if (/^\d{2}:\d{2}:\d{2}$/.test(value)) {
    return value;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }

  return date.toLocaleTimeString([], { hour12: false });
}

export function formatRelativeUpdate(date: Date | null) {
  if (!date) {
    return "Awaiting sync";
  }

  return `Updated ${date.toLocaleTimeString([], { hour12: false })}`;
}

export function humanizeToken(value?: string | null, fallback = "--") {
  if (!value) {
    return fallback;
  }

  return value.replace(/_/g, " ");
}

export function normalizeStageKey(value?: string | null): StageKey | null {
  if (!value) {
    return null;
  }

  const normalized = value.toLowerCase().replace(/^agent\./, "");

  if (normalized === "awaiting_approval") {
    return "deployment";
  }

  if (STAGES.some((stage) => stage.key === normalized)) {
    return normalized as StageKey;
  }

  return null;
}

export function mapTimelineStatus(stage?: TimelineStage): RuntimeStatus | null {
  if (!stage) {
    return null;
  }

  switch (stage.status) {
    case "success":
      return "success";
    case "failed":
      return "failed";
    case "rolled_back":
      return "rolled_back";
    case "deduplicated":
      return "deduplicated";
    case "running":
      return "running";
    default:
      return "pending";
  }
}

export function mapSpanStatus(status?: string): RuntimeStatus | null {
  switch (status) {
    case "success":
      return "success";
    case "failed":
      return "failed";
    case "rolled_back":
      return "rolled_back";
    default:
      return status === "running" ? "running" : null;
  }
}

export function computeConfidence(status: RuntimeStatus, riskScore?: number, stageIndex = 0) {
  const baseByStatus: Record<RuntimeStatus, number> = {
    pending: 0.18,
    running: 0.74,
    success: 0.93,
    failed: 0.26,
    rolled_back: 0.34,
    deduplicated: 0.61,
  };

  const riskModifier = riskScore !== undefined ? clamp((1 - riskScore) * 0.08, -0.05, 0.08) : 0;
  const stageModifier = (2 - stageIndex) * 0.01;

  return clamp(baseByStatus[status] + riskModifier + stageModifier, 0.05, 0.99);
}

export function buildStageViews(
  job: PipelineJobSummary | null,
  detail: PipelineJobDetail | null,
  spans: Span[],
  timeline: TimelineStage[],
): StageView[] {
  const spansByStage = new Map<StageKey, Span>();
  spans.forEach((span) => {
    const key = normalizeStageKey(span.name);
    if (key) {
      spansByStage.set(key, span);
    }
  });

  const timelineByStage = new Map<StageKey, TimelineStage>();
  timeline.forEach((item) => {
    const key = normalizeStageKey(item.stage);
    if (key) {
      timelineByStage.set(key, item);
    }
  });

  const provisional = STAGES.map((stage, index) => {
    const span = spansByStage.get(stage.key);
    const timelineStage = timelineByStage.get(stage.key);
    const jobFailureStage = normalizeStageKey(detail?.failure_stage ?? job?.failure_stage ?? null);

    let status: RuntimeStatus = "pending";
    if (timelineStage) {
      status = mapTimelineStatus(timelineStage) ?? status;
    }
    if (span?.status) {
      status = mapSpanStatus(span.status) ?? status;
    }
    if (jobFailureStage === stage.key) {
      status = "failed";
    }
    if (detail?.status === "awaiting_approval" && stage.key === "deployment") {
      status = "pending";
    }

    return {
      ...stage,
      spanId: span?.span_id ?? span?.id ?? `span-${stage.key}`,
      status,
      durationMs: span?.duration ?? stage.fallbackDurationMs,
      confidence: computeConfidence(status, detail?.risk_score, index),
      startMs: 0,
      endMs: 0,
      timestamp: formatTimestamp(timelineStage?.timestamp ?? span?.timestamp),
      service: span?.attributes?.service_name ?? detail?.service ?? "orchestrator",
      message: span?.details ?? timelineStage?.details ?? `${stage.label.toLowerCase()} stage awaiting live telemetry`,
    } satisfies StageView;
  });

  if (!provisional.some((stage) => stage.status === "running") && detail?.status === "running") {
    const runningIndex = provisional.findIndex((stage) => stage.status === "pending");
    if (runningIndex >= 0) {
      provisional[runningIndex] = {
        ...provisional[runningIndex],
        status: "running",
        confidence: computeConfidence("running", detail.risk_score, runningIndex),
      };
    }
  }

  if (!provisional.some((stage) => stage.status !== "pending") && detail?.status === "completed") {
    provisional.forEach((stage, index) => {
      provisional[index] = {
        ...stage,
        status: "success",
        confidence: computeConfidence("success", detail.risk_score, index),
      };
    });
  }

  let cursor = 0;
  return provisional.map((stage) => {
    const next = {
      ...stage,
      startMs: cursor,
      endMs: cursor + stage.durationMs,
    };
    cursor += stage.durationMs;
    return next;
  });
}

export function buildLogEntries(
  job: PipelineJobSummary | null,
  detail: PipelineJobDetail | null,
  stages: StageView[],
): LogEntry[] {
  const base: LogEntry[] = stages.map((stage) => {
    let severity: Severity = "info";
    if (stage.status === "success") severity = "success";
    if (stage.status === "failed" || stage.status === "rolled_back") severity = "error";
    if (stage.status === "deduplicated") severity = "warning";

    return {
      id: `${job?.job_id ?? "standby"}-${stage.key}`,
      timestamp: stage.timestamp,
      severity,
      stage: stage.key,
      service: stage.service,
      message: stage.message,
      traceId: job?.job_id ?? undefined,
      spanId: stage.spanId,
    };
  });

  const head: LogEntry = {
    id: `${job?.job_id ?? "standby"}-start`,
    timestamp: stages[0]?.timestamp ?? "--:--:--",
    severity: detail?.status === "failed" ? "warning" : "info",
    stage: "detection",
    service: "orchestrator",
    message: job ? `pipeline started for ${humanizeToken(job.scenario)}` : "console standby; awaiting incident trigger",
    traceId: job?.job_id ?? undefined,
    spanId: "span-detection",
  };

  const tail: LogEntry = {
    id: `${job?.job_id ?? "standby"}-tail`,
    timestamp: stages[stages.length - 1]?.timestamp ?? "--:--:--",
    severity: detail?.status === "failed" ? "error" : detail?.status === "completed" ? "success" : "info",
    stage: normalizeStageKey(detail?.failure_stage ?? null) ?? "deployment",
    service: detail?.service ?? "orchestrator",
    message: detail?.status === "failed"
      ? detail.failure_reason ?? "pipeline halted on stage failure"
      : detail?.status === "completed"
        ? `pipeline ${detail.deployed ? "deployment committed" : "completed without deployment"}`
        : detail?.status === "awaiting_approval"
          ? "deployment awaiting manual approval"
          : "execution trace streaming",
    traceId: job?.job_id ?? undefined,
    spanId: `span-${normalizeStageKey(detail?.failure_stage ?? null) ?? "deployment"}`,
  };

  return [head, ...base, tail];
}

export async function fetchJson<T>(path: string) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

// ─── UI State ────────────────────────────────────────────────────────────────

interface UiState {
  sidebarExpanded: boolean;
  toggleSidebar: () => void;
  setSidebarExpanded: (v: boolean) => void;
  selectedJobId: string | null;
  setSelectedJobId: (id: string | null) => void;
  stageReplayIndex: number | null;
  setStageReplayIndex: (idx: number | null) => void;
  activePanel: string | null;
  setActivePanel: (id: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarExpanded: true,
  toggleSidebar: () => set((s) => ({ sidebarExpanded: !s.sidebarExpanded })),
  setSidebarExpanded: (v) => set({ sidebarExpanded: v }),
  selectedJobId: null,
  setSelectedJobId: (id) => set({ selectedJobId: id }),
  stageReplayIndex: null,
  setStageReplayIndex: (idx) => set({ stageReplayIndex: idx }),
  activePanel: null,
  setActivePanel: (id) => set({ activePanel: id }),
}));
