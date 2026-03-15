import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { Search } from "lucide-react";
import {
  type LogEntry,
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

// ─── SSE payload shape ────────────────────────────────────────────────────────

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

// ─── Constants ────────────────────────────────────────────────────────────────

const LOG_CAP          = 300;
const INITIAL_BACKOFF  = 1_000;
const MAX_BACKOFF      = 30_000;
const FLUSH_INTERVAL   = 100;

// Severity display config
const SEV_CONFIG: Record<Severity, { token: string; tokenCls: string }> = {
  info:    { token: "INF", tokenCls: "sev-token-info"    },
  warning: { token: "WRN", tokenCls: "sev-token-warning" },
  error:   { token: "ERR", tokenCls: "sev-token-error"   },
  success: { token: "OK ", tokenCls: "sev-token-success" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function normalizeSeverity(value?: string): Severity {
  if (value === "warning" || value === "error" || value === "success") return value;
  return "info";
}

function parseStreamLog(raw: string): LogEntry | null {
  let parsed: StreamLogPayload;
  try { parsed = JSON.parse(raw) as StreamLogPayload; }
  catch { return null; }
  const stage     = normalizeStageKey(parsed.stage) ?? "detection";
  const timestamp = formatTimestamp(parsed.timestamp);
  return {
    id:        parsed.id ?? `${timestamp}-${stage}-${Math.random().toString(36).slice(2, 8)}`,
    timestamp,
    severity:  normalizeSeverity(parsed.severity),
    stage:     stage as StageKey,
    service:   parsed.service ?? "orchestrator",
    message:   parsed.message ?? "stream event",
    traceId:   parsed.trace_id,
    spanId:    parsed.span_id ?? `span-${stage}`,
  };
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function LogConsole({
  logs,
  selectedStageIndex,
  onSelectStage: _onSelectStage,
  onSelectSpan,
  selectedSpanId,
}: LogConsoleProps) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [streamLogs, setStreamLogs] = useState<LogEntry[]>([]);
  const [search, setSearch]         = useState("");
  const [sevFilter, setSevFilter]   = useState<Severity | null>(null);
  const [focusedIdx, setFocusedIdx] = useState<number>(-1);
  const [pinned, setPinned]         = useState(true);

  // ── Refs ───────────────────────────────────────────────────────────────────
  const pendingRef  = useRef<LogEntry[]>([]);
  const sourceRef   = useRef<EventSource | null>(null);
  const bodyRef     = useRef<HTMLDivElement>(null);
  const searchRef   = useRef<HTMLInputElement>(null);
  const rowRefs     = useRef<(HTMLButtonElement | null)[]>([]);

  // ── SSE with reconnect backoff ─────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    let backoff   = INITIAL_BACKOFF;
    let retryTo: ReturnType<typeof setTimeout> | null = null;
    let flushIv: ReturnType<typeof setInterval> | null = null;

    function connect() {
      if (cancelled) return;
      if (sourceRef.current) { sourceRef.current.close(); sourceRef.current = null; }

      const src = new EventSource("/api/v1/log-stream");
      sourceRef.current = src;

      src.onopen    = () => { backoff = INITIAL_BACKOFF; };
      src.onmessage = (e: MessageEvent) => {
        const next = parseStreamLog(e.data as string);
        if (next) pendingRef.current.push(next);
      };
      src.onerror   = () => {
        src.close();
        if (sourceRef.current === src) sourceRef.current = null;
        if (!cancelled) {
          retryTo = setTimeout(() => { backoff = Math.min(backoff * 2, MAX_BACKOFF); connect(); }, backoff);
        }
      };
    }

    flushIv = setInterval(() => {
      if (!pendingRef.current.length) return;
      const batch = pendingRef.current.splice(0);
      setStreamLogs((prev) => {
        const next = [...prev, ...batch];
        return next.length > LOG_CAP ? next.slice(-LOG_CAP) : next;
      });
    }, FLUSH_INTERVAL);

    connect();

    return () => {
      cancelled = true;
      if (retryTo) clearTimeout(retryTo);
      if (flushIv) clearInterval(flushIv);
      if (sourceRef.current) { sourceRef.current.close(); sourceRef.current = null; }
      pendingRef.current = [];
    };
  }, []);

  // ── Autoscroll ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !pinned) return;
    el.scrollTop = el.scrollHeight;
  }, [streamLogs, logs, pinned]);

  const handleScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setPinned(atBottom);
  }, []);

  const resumeScroll = useCallback(() => {
    setPinned(true);
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  // ── Filtered display ───────────────────────────────────────────────────────
  const displayedLogs = useMemo(() => {
    let src = streamLogs.length === 0 ? logs : streamLogs;

    // Span correlation filter
    if (selectedSpanId) {
      src = src.filter((l) => l.spanId === selectedSpanId);
    }

    // Severity filter
    if (sevFilter) {
      src = src.filter((l) => l.severity === sevFilter);
    }

    // Text search — matches service or message
    const q = search.trim().toLowerCase();
    if (q) {
      // Support query syntax: "severity:error", "stage:diagnosis"
      const sevMatch   = q.match(/^severity:(\w+)/);
      const stageMatch = q.match(/^stage:(\w+)/);
      if (sevMatch) {
        const s = normalizeSeverity(sevMatch[1]);
        src = src.filter((l) => l.severity === s);
      } else if (stageMatch) {
        const stageKey = normalizeStageKey(stageMatch[1]);
        src = stageKey ? src.filter((l) => l.stage === stageKey) : src;
      } else {
        src = src.filter(
          (l) =>
            l.message.toLowerCase().includes(q) ||
            l.service.toLowerCase().includes(q) ||
            l.stage.toLowerCase().includes(q)
        );
      }
    }

    return src;
  }, [logs, streamLogs, selectedSpanId, sevFilter, search]);

  // ── Keyboard navigation ────────────────────────────────────────────────────
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const len = displayedLogs.length;
    if (!len) return;

    if (e.key === "j" || e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIdx((i) => {
        const next = Math.min(i + 1, len - 1);
        rowRefs.current[next]?.scrollIntoView({ block: "nearest" });
        return next;
      });
    } else if (e.key === "k" || e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIdx((i) => {
        const next = Math.max(i - 1, 0);
        rowRefs.current[next]?.scrollIntoView({ block: "nearest" });
        return next;
      });
    } else if (e.key === "g") {
      e.preventDefault();
      resumeScroll();
      setFocusedIdx(len - 1);
    } else if (e.key === "Enter" && focusedIdx >= 0) {
      const log = displayedLogs[focusedIdx];
      if (log) onSelectSpan(log.spanId ?? null);
    } else if (e.key === "Escape") {
      onSelectSpan(null);
      setSevFilter(null);
      setSearch("");
      setFocusedIdx(-1);
    }
  }, [displayedLogs, focusedIdx, onSelectSpan, resumeScroll]);

  // Global Ctrl+F → focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────────
  const SEVS: Severity[] = ["info", "warning", "error", "success"];

  return (
    <section
      className="log-panel"
      onKeyDown={handleKeyDown}
      tabIndex={0}
      style={{ outline: "none" }}
    >
      {/* Header */}
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Terminal Log Stream</p>
          <h2>Correlated execution feed</h2>
        </div>
        <span className="panel-value">{String(displayedLogs.length).padStart(3, "0")}</span>
      </div>

      {/* Filter / search controls */}
      <div className="log-controls">
        {/* Severity toggles */}
        {SEVS.map((sev) => (
          <button
            key={sev}
            type="button"
            className={`log-filter-btn ${sevFilter === sev ? "active" : ""}`}
            onClick={() => setSevFilter((prev) => (prev === sev ? null : sev))}
          >
            {SEV_CONFIG[sev].token}
          </button>
        ))}

        {/* Search input */}
        <div className="log-search-wrap">
          <Search size={11} className="log-search-icon" />
          <input
            ref={searchRef}
            className="log-search-input"
            placeholder="search · severity:error · stage:diagnosis"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            spellCheck={false}
          />
        </div>
      </div>

      {/* Column header */}
      <div className="log-header">
        <span>timestamp</span>
        <span>sev</span>
        <span>stage</span>
        <span>service</span>
        <span>message</span>
      </div>

      {/* Log rows */}
      <div
        className="log-body"
        ref={bodyRef}
        onScroll={handleScroll}
      >
        {displayedLogs.map((log, idx) => {
          const stageIdx  = STAGES.findIndex((s) => s.key === log.stage);
          const isActive  = selectedStageIndex === stageIdx;
          const isFocused = focusedIdx === idx;
          const sevCfg    = SEV_CONFIG[log.severity];
          const stageColor = STAGES[stageIdx]?.color ?? "var(--text-faint)";

          return (
            <button
              key={log.id}
              ref={(el) => { rowRefs.current[idx] = el; }}
              type="button"
              className={[
                "log-row",
                `sev-${log.severity}`,
                isActive  ? "is-active"  : "",
                isFocused ? "is-focused" : "",
              ].join(" ")}
              onClick={() => {
                setFocusedIdx(idx);
                onSelectSpan(log.spanId ?? null);
              }}
            >
              {/* Timestamp */}
              <span style={{ color: "var(--text-faint)" }}>{log.timestamp}</span>

              {/* Severity glyph */}
              <span className={`log-sev ${sevCfg.tokenCls}`}>{sevCfg.token}</span>

              {/* Stage */}
              <span className="log-stage" style={{ color: stageColor }}>{log.stage}</span>

              {/* Service */}
              <span style={{ color: "var(--text-dim)" }}>{log.service}</span>

              {/* Message */}
              <span className="log-msg">{log.message}</span>
            </button>
          );
        })}

        {displayedLogs.length === 0 && (
          <div style={{
            padding: "24px 16px",
            textAlign: "center",
            color: "var(--text-faint)",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
          }}>
            {search || sevFilter ? "No logs match current filter." : "Awaiting log stream…"}
          </div>
        )}
      </div>

      {/* Keyboard hints + autoscroll resume */}
      <div className="log-kbd-hints">
        <span className="log-kbd-hint">
          <kbd>j</kbd><kbd>k</kbd> navigate
        </span>
        <span className="log-kbd-hint">
          <kbd>g</kbd> bottom
        </span>
        <span className="log-kbd-hint">
          <kbd>↵</kbd> correlate
        </span>
        <span className="log-kbd-hint">
          <kbd>Esc</kbd> clear
        </span>
        <span className="log-kbd-hint">
          <kbd>⌘F</kbd> search
        </span>

        {!pinned && (
          <button
            type="button"
            className="log-resume-pill"
            onClick={resumeScroll}
          >
            ↓ resume
          </button>
        )}
      </div>
    </section>
  );
}
