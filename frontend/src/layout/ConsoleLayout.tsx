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

import StatusBar from "../components/StatusBar";
import IncidentRail from "../components/IncidentRail";
import PipelineCanvas from "../components/PipelineCanvas";
import DiagnosticsPanel from "../components/DiagnosticsPanel";
import LogConsole from "../components/LogConsole";

export default function ConsoleLayout() {
  const {
    selectedJobId,
    setSelectedJobId,
    stageReplayIndex,
    setStageReplayIndex,
  } = useUiStore((state) => ({
    selectedJobId: state.selectedJobId,
    setSelectedJobId: state.setSelectedJobId,
    stageReplayIndex: state.stageReplayIndex,
    setStageReplayIndex: state.setStageReplayIndex,
  }));

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ops, setOps] = useState<OpsMetrics | null>(null);
  const [jobs, setJobs] = useState<PipelineJobSummary[]>([]);
  const [detail, setDetail] = useState<PipelineJobDetail | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [timeline, setTimeline] = useState<TimelineStage[]>([]);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [live, setLive] = useState(true);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadShell = async () => {
      const [healthResult, opsResult, jobsResult] = await Promise.allSettled([
        fetchJson<HealthResponse>("/health"),
        fetchJson<OpsMetrics>("/api/v1/metrics/ops"),
        fetchJson<PipelineJobsResponse>("/api/v1/pipeline/jobs?limit=12"),
      ]);

      if (cancelled) {
        return;
      }

      const hasSuccess = [healthResult, opsResult, jobsResult].some((result) => result.status === "fulfilled");
      setLive(hasSuccess);

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      }

      if (opsResult.status === "fulfilled") {
        setOps(opsResult.value);
      }

      if (jobsResult.status === "fulfilled") {
        setJobs(jobsResult.value.jobs);
      }

      if (hasSuccess) {
        setUpdatedAt(new Date());
      }
    };

    void loadShell();
    const intervalId = window.setInterval(() => {
      void loadShell();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (jobs.length === 0) {
      return;
    }

    const currentSelectionStillExists = selectedJobId && jobs.some((job) => job.job_id === selectedJobId);
    if (currentSelectionStillExists) {
      return;
    }

    const preferredJob = jobs.find((job) => job.status === "running") ?? jobs[0];
    setSelectedJobId(preferredJob.job_id);
  }, [jobs, selectedJobId, setSelectedJobId]);

  useEffect(() => {
    setStageReplayIndex(null);
    setSelectedSpanId(null);
  }, [selectedJobId, setStageReplayIndex]);

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

      if (cancelled) {
        return;
      }

      if (detailResult.status === "fulfilled") {
        setDetail(detailResult.value);
      }

      if (spansResult.status === "fulfilled") {
        setSpans(spansResult.value.spans);
      }

      if (timelineResult.status === "fulfilled") {
        setTimeline(timelineResult.value.timeline);
      }

      if (
        detailResult.status === "fulfilled" ||
        spansResult.status === "fulfilled" ||
        timelineResult.status === "fulfilled"
      ) {
        setUpdatedAt(new Date());
      }
    };

    void loadDetail();
    const intervalId = window.setInterval(() => {
      void loadDetail();
    }, detail?.status === "running" ? 2500 : 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [detail?.status, selectedJobId]);

  const selectedJob = useMemo(
    () => jobs.find((job) => job.job_id === selectedJobId) ?? null,
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

    return stageViews.findIndex((stage) => stage.status === "running") >= 0
      ? stageViews.findIndex((stage) => stage.status === "running")
      : Math.max(stageViews.findIndex((stage) => stage.status !== "pending"), 0);
  }, [stageReplayIndex, stageViews]);

  const logs = useMemo(() => buildLogEntries(selectedJob, detail, stageViews), [detail, selectedJob, stageViews]);

  return (
    <div className="console-shell">
      <div className="console-frame">
        <div className="console-statusbar">
          <StatusBar
            health={health}
            ops={ops}
            selectedJob={selectedJob}
            detail={detail}
            updatedAt={updatedAt}
            live={live}
          />
        </div>
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
          />
          <LogConsole
            logs={logs}
            selectedStageIndex={activeStageIndex}
            onSelectStage={setStageReplayIndex}
            onSelectSpan={setSelectedSpanId}
            selectedSpanId={selectedSpanId}
          />
        </main>
        <aside className="console-diagnostics">
          <DiagnosticsPanel
            health={health}
            ops={ops}
            detail={detail}
            selectedJob={selectedJob}
            stages={stageViews}
          />
        </aside>
      </div>
    </div>
  );
}
