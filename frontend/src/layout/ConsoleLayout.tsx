import { useEffect, useMemo, useState } from "react";
import type {
  HealthResponse,
  OpsMetrics,
  PipelineJobDetail,
  PipelineJobsResponse,
  PipelineJobSummary,
  Span,
  SpansResponse,
  TimelineResponse,
  TimelineStage,
} from "../utils/console";

import { buildLogEntries, buildStageViews, fetchJson, useUiStore } from "../utils/console";

import IncidentRail from "../components/IncidentRail";
import PipelineCanvas from "../components/PipelineCanvas";
import DiagnosticsPanel from "../components/DiagnosticsPanel";
import LogConsole from "../components/LogConsole";

export default function ConsoleLayout() {
  // ── Zustand — one selector per value to avoid the getSnapshot object-equality
  //    infinite-loop: returning a new {} on every call defeats useSyncExternalStore.
  const selectedJobId      = useUiStore((s) => s.selectedJobId);
  const setSelectedJobId   = useUiStore((s) => s.setSelectedJobId);
  const stageReplayIndex   = useUiStore((s) => s.stageReplayIndex);
  const setStageReplayIndex = useUiStore((s) => s.setStageReplayIndex);

  const [health, setHealth]   = useState<HealthResponse | null>(null);
  const [ops, setOps]         = useState<OpsMetrics | null>(null);
  const [jobs, setJobs]       = useState<PipelineJobSummary[]>([]);
  const [detail, setDetail]   = useState<PipelineJobDetail | null>(null);
  const [spans, setSpans]     = useState<Span[]>([]);
  const [timeline, setTimeline] = useState<TimelineStage[]>([]);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [isDiagOpen, setIsDiagOpen] = useState(false);

  // ── Shell data: health + ops metrics + job list (5s polling) ────────────────
  useEffect(() => {
    let cancelled = false;

    const loadShell = async () => {
      const [healthResult, opsResult, jobsResult] = await Promise.allSettled([
        fetchJson<HealthResponse>("/health"),
        fetchJson<OpsMetrics>("/api/v1/metrics/ops"),
        fetchJson<PipelineJobsResponse>("/api/v1/pipeline/jobs?limit=12"),
      ]);

      if (cancelled) return;

      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (opsResult.status   === "fulfilled") setOps(opsResult.value);
      if (jobsResult.status  === "fulfilled") setJobs(jobsResult.value.jobs);
    };

    void loadShell();
    const id = window.setInterval(() => { void loadShell(); }, 5000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  // ── Auto-select the first / running job when job list changes ───────────────
  useEffect(() => {
    if (jobs.length === 0) return;
    const stillExists = selectedJobId && jobs.some((j) => j.job_id === selectedJobId);
    if (stillExists) return;
    const preferred = jobs.find((j) => j.status === "running") ?? jobs[0];
    setSelectedJobId(preferred.job_id);
  }, [jobs, selectedJobId, setSelectedJobId]);

  // ── Reset span / stage selection when selected job changes ──────────────────
  useEffect(() => {
    setStageReplayIndex(null);
    setSelectedSpanId(null);
  }, [selectedJobId, setStageReplayIndex]);

  // ── Per-job detail, spans, timeline (2.5s when running, 5s otherwise) ───────
  useEffect(() => {
    if (!selectedJobId) {
      setDetail(null);
      setSpans([]);
      setTimeline([]);
      return;
    }

    let cancelled = false;

    const loadDetail = async () => {
      const [detailResult, spansResult, timelineResult] = await Promise.allSettled([
        fetchJson<PipelineJobDetail>(`/api/v1/pipeline/jobs/${selectedJobId}`),
        fetchJson<SpansResponse>(`/api/v1/pipeline/${selectedJobId}/spans`),
        fetchJson<TimelineResponse>(`/api/v1/remediation/${selectedJobId}/timeline`),
      ]);

      if (cancelled) return;

      if (detailResult.status  === "fulfilled") setDetail(detailResult.value);
      if (spansResult.status   === "fulfilled") setSpans(spansResult.value.spans);
      if (timelineResult.status === "fulfilled") setTimeline(timelineResult.value.timeline);
    };

    void loadDetail();
    const id = window.setInterval(
      () => { void loadDetail(); },
      detail?.status === "running" ? 2500 : 5000,
    );

    return () => { cancelled = true; window.clearInterval(id); };
  }, [detail?.status, selectedJobId]);

  // ── Derived view models ──────────────────────────────────────────────────────
  const selectedJob = useMemo(
    () => jobs.find((j) => j.job_id === selectedJobId) ?? null,
    [jobs, selectedJobId],
  );

  const stageViews = useMemo(
    () => buildStageViews(selectedJob, detail, spans, timeline),
    [detail, selectedJob, spans, timeline],
  );

  const activeStageIndex = useMemo(() => {
    if (stageReplayIndex !== null && stageReplayIndex >= 0 && stageReplayIndex < stageViews.length) {
      return stageReplayIndex;
    }
    const runningIdx = stageViews.findIndex((s) => s.status === "running");
    if (runningIdx >= 0) return runningIdx;
    return Math.max(stageViews.findIndex((s) => s.status !== "pending"), 0);
  }, [stageReplayIndex, stageViews]);

  const logs = useMemo(
    () => buildLogEntries(selectedJob, detail, stageViews),
    [detail, selectedJob, stageViews],
  );

  // ── Layout ───────────────────────────────────────────────────────────────────
  return (
    <div className="console-shell">
      <div className="console-frame">
        <aside className="console-rail">
          <IncidentRail
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelect={setSelectedJobId}
          />
        </aside>

        <main className="console-center">
          <PipelineCanvas
            stages={stageViews}
            detail={detail}
            selectedStageIndex={activeStageIndex}
            onSelectStage={setStageReplayIndex}
            selectedSpanId={selectedSpanId}
            onSelectSpan={setSelectedSpanId}
            isDiagOpen={isDiagOpen}
            onToggleDiag={() => setIsDiagOpen(!isDiagOpen)}
          />
          <LogConsole
            logs={logs}
            selectedStageIndex={activeStageIndex}
            onSelectStage={setStageReplayIndex}
            onSelectSpan={setSelectedSpanId}
            selectedSpanId={selectedSpanId}
          />
        </main>

        <aside className={`console-diagnostics ${isDiagOpen ? "open" : ""}`}>
          <DiagnosticsPanel
            health={health}
            ops={ops}
            detail={detail}
            selectedJob={selectedJob}
            stages={stageViews}
            onClose={() => setIsDiagOpen(false)}
          />
        </aside>
      </div>
    </div>
  );
}
