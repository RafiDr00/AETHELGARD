import { useEffect, useMemo, useRef, useState } from "react";

import {
  type LogEntry,
  SEVERITY_GLYPH,
  STAGES,
  type Severity,
  type StageKey,
  normalizeStageKey,
  formatTimestamp,
} from "../utils/console";

export interface LogConsoleProps {
  logs: LogEntry[];
  selectedStageIndex: number;
  onSelectStage: (index: number) => void;
  onSelectSpan: (spanId: string | null) => void;
  selectedSpanId: string | null;
}

interface StreamLogPayload {
  id?: string;
  timestamp?: string;
  severity?: string;
  stage?: string;
  service?: string;
  message?: string;
  trace_id?: string;
  span_id?: string;
}

function normalizeSeverity(value?: string): Severity {
  if (value === "warning" || value === "error" || value === "success") {
    return value;
  }

  return "info";
}

function parseStreamLog(raw: string): LogEntry | null {
  let parsed: StreamLogPayload;

  try {
    parsed = JSON.parse(raw) as StreamLogPayload;
  } catch {
    return null;
  }

  const stage = normalizeStageKey(parsed.stage) ?? "detection";
  const timestamp = formatTimestamp(parsed.timestamp);

  return {
    id: parsed.id ?? `${timestamp}-${stage}-${Math.random().toString(36).slice(2, 8)}`,
    timestamp,
    severity: normalizeSeverity(parsed.severity),
    stage: stage as StageKey,
    service: parsed.service ?? "orchestrator",
    message: parsed.message ?? "stream event",
    traceId: parsed.trace_id,
    spanId: parsed.span_id ?? `span-${stage}`,
  };
}

export default function LogConsole({ logs, selectedStageIndex, onSelectStage, onSelectSpan, selectedSpanId }: LogConsoleProps) {
  const [streamLogs, setStreamLogs] = useState<LogEntry[]>([]);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const seenIdsRef = useRef<Map<string, number>>(new Map());
  const pendingLogsRef = useRef<LogEntry[]>([]);
  const flushIntervalRef = useRef<number | null>(null);
  const shouldStickToBottomRef = useRef(true);

  const isNearBottom = (element: HTMLDivElement) => {
    return element.scrollHeight - element.scrollTop - element.clientHeight < 20;
  };

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed) {
        return;
      }

      if (sourceRef.current) {
        return;
      }

      const source = new EventSource("/api/v1/log-stream");
      sourceRef.current = source;

      source.onmessage = (event) => {
        const next = parseStreamLog(event.data);
        if (!next) return;

        const now = Date.now();

        // Prevent duplicate logs in the sliding window
        if (seenIdsRef.current.has(next.id)) return;

        seenIdsRef.current.set(next.id, now);
        pendingLogsRef.current.push(next);
      };

      // Sliding window cleanup via flush interval later
      source.onerror = () => {
        source.close();
        sourceRef.current = null;

        if (disposed) {
          return;
        }

        if (reconnectTimeoutRef.current !== null) {
          window.clearTimeout(reconnectTimeoutRef.current);
        }

        reconnectTimeoutRef.current = window.setTimeout(() => {
          reconnectTimeoutRef.current = null;
          connect();
        }, 3000);
      };
    };

    connect();

    flushIntervalRef.current = window.setInterval(() => {
      const now = Date.now();

      // Periodic sliding window cleanup of seenIds
      if (seenIdsRef.current.size > 5000) {
        for (const [id, seenAt] of seenIdsRef.current.entries()) {
          if (now - seenAt > 30000) {
            seenIdsRef.current.delete(id);
          }
        }
      }

      if (pendingLogsRef.current.length === 0) return;

      const batch = pendingLogsRef.current.splice(0, pendingLogsRef.current.length);
      setStreamLogs((previous) => {
        const updated = [...previous, ...batch];
        // Enforce max log history length
        if (updated.length > 800) {
          return updated.slice(-800);
        }
        return updated;
      });
    }, 150);

    return () => {
      disposed = true;

      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }

      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (flushIntervalRef.current !== null) {
        window.clearInterval(flushIntervalRef.current);
        flushIntervalRef.current = null;
      }

      pendingLogsRef.current = [];
    };
  }, []);

  const displayedLogs = useMemo(() => {
    let source = streamLogs.length === 0 ? logs : streamLogs;
    if (selectedSpanId) {
      source = source.filter(log => log.spanId === selectedSpanId);
    }
    return source;
  }, [logs, streamLogs, selectedSpanId]);

  useEffect(() => {
    const body = bodyRef.current;
    if (!body) {
      return;
    }

    if (shouldStickToBottomRef.current) {
      body.scrollTop = body.scrollHeight;
    }
  }, [displayedLogs]);

  const handleBodyScroll = () => {
    const body = bodyRef.current;
    if (!body) {
      return;
    }
    shouldStickToBottomRef.current = isNearBottom(body);
  };

  return (
    <section className="log-panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">TERMINAL LOG STREAM</p>
          <h2>Correlated execution feed</h2>
        </div>
        <span className="panel-value">{displayedLogs.length.toString().padStart(2, "0")}</span>
      </div>

      <div className="log-header">
        <span>timestamp</span>
        <span>sev</span>
        <span>stage</span>
        <span>service</span>
        <span>message</span>
      </div>

      <div className="log-body" ref={bodyRef} onScroll={handleBodyScroll}>
        {displayedLogs.map((log) => {
          const stageIndex = STAGES.findIndex((stage) => stage.key === log.stage);
          const selected = selectedStageIndex === stageIndex;

          return (
            <button
              key={log.id}
              type="button"
              className={`log-row ${selected ? "selected" : ""} severity-${log.severity}`}
              onClick={() => {
                const nextSpanId = log.spanId ?? null;
                onSelectStage(stageIndex);
                onSelectSpan(selectedSpanId === nextSpanId ? null : nextSpanId);
              }}
            >
              <span>{log.timestamp}</span>
              <span>{SEVERITY_GLYPH[log.severity]}</span>
              <span className="log-stage" style={{ color: STAGES[stageIndex]?.color }}>{log.stage}</span>
              <span>{log.service}</span>
              <span>{log.message}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
