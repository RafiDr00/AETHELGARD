# Aethelgard Frontend — Premium Engineering Control Panel

A **visually stunning, technically sophisticated** DevOps control interface for the Aethelgard autonomous incident response platform.

> An engineering control system built to impress senior frontend engineers and UI/UX designers.

**Built with**: React 18 • TypeScript • Vite • TailwindCSS • Framer Motion • TanStack Query • React Three Fiber • Zustand

---

## 🎯 Design Philosophy

Every pixel, animation, and interaction is **intentional and premium-grade**.

The interface communicates:
- **Precision**: Accurate metrics, responsive feedback, clear states
- **Speed**: 120ms micro-interactions, 240ms normal transitions, 400ms panel animations
- **Technical Power**: Depth layers, glow effects, 3D visualizations, glassmorphism
- **System Intelligence**: Ambient animations, reactive elements, real-time data integration

**Inspired by**: Stripe • Linear • Vercel • Raycast • Datadog • Apple Developer Tools

---

## 📖 Documentation

**→ Read [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md) for complete design system documentation**

Key topics:
- Color palette and design tokens
- 4px grid spacing system
- Motion timing hierarchy
- Component library specs
- Animation best practices
- Design rules & checklist

---

## 🚀 Quick Start

**Prerequisites**: Node.js 18+, Aethelgard backend running on `http://localhost:8000`

```bash
cd frontend
npm install
npm run dev        # ➜ http://localhost:3000
```

Open `http://localhost:3000` in your browser.

---

## npm Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Start Vite dev server on port 3000 (proxies API to localhost:8000) |
| `npm run build` | TypeScript compilation + production bundle in `dist/` |
| `npm run preview` | Serve the production build locally |

---

## ✅ Quality Standards

This frontend is held to premium standards:

- **0 Runtime Errors** – TypeScript strict, full type safety
- **0 Console Warnings** – Clean, professional dev experience
- **Consistent Animations** – All motion uses design system timings
- **Accessible** – WCAG compliant, keyboard navigation, focus states
- **Responsive** – Adapts smoothly to all screen sizes
- **Performant** – Lazy loading, code splitting, optimized bundle
- **Handcrafted** – Not AI-generated, intentional design decisions

---

## 🎨 Component Library

All components follow the design system:

Feature-based modular structure under `src/`:

```
src/
├── types/
│   └── api.ts                # TypeScript types mirroring all Pydantic API models
│
├── services/
│   └── api/
│       ├── client.ts         # Base fetch wrapper (apiFetch, apiPost, wsUrl)
│       ├── health.ts         # /health, /ready
│       ├── metrics.ts        # /metrics, /api/metrics, /metrics/history
│       └── pipeline.ts       # /pipeline/jobs, /pipeline/run, timeline, spans
│
├── hooks/
│   ├── useHealth.ts          # useHealth() — 5s polling
│   ├── useMetrics.ts         # useOpsMetrics(), usePlatformMetrics(), useMetricsHistory()
│   └── usePipeline.ts        # usePipelineJobs(), useJobDetail(), useJobTimeline(), useJobSpans()
│
├── lib/
│   └── utils.ts              # cn(), formatSeconds(), statusColor()
│
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx      # Full-page shell with sidebar
│   │   ├── Sidebar.tsx       # Navigation sidebar
│   │   └── PageHeader.tsx    # Reusable page title/subtitle/badge/action
│   └── ui/
│       ├── Badge.tsx         # Status badges (success/danger/warning/info)
│       ├── Card.tsx          # Surface card with optional title/action
│       ├── MetricCard.tsx    # KPI stat card
│       ├── LoadingSpinner.tsx
│       └── EmptyState.tsx
│
├── features/
│   ├── pipeline/
│   │   ├── PipelineGraph.tsx    # Detection→Diagnosis→Remediation→Validation→Deployment
│   │   ├── SpanVisualizer.tsx   # Gantt-style span bars (similar to Jaeger/Datadog APM)
│   │   ├── AgentActivityPanel.tsx # Five agents with live status
│   │   ├── PatchDiffViewer.tsx  # GitHub-style diff renderer
│   │   ├── JobList.tsx          # Scrollable pipeline job list
│   │   └── TriggerPanel.tsx     # Trigger new pipeline job (requires API key)
│   ├── incidents/
│   │   └── IncidentTimeline.tsx # Chronological anomaly events
│   ├── metrics/
│   │   ├── MttrChart.tsx        # MTTD/MTTR line chart
│   │   ├── ResolutionBarChart.tsx # Resolution status distribution
│   │   └── RiskScoreChart.tsx   # Risk score area chart
│   └── system/
│       └── SystemHealthPanel.tsx # API/Agents/Knowledge/Runtime health cards
│
└── pages/
    ├── Dashboard.tsx   # Overview grid: KPIs, pipeline graph, agent activity, metrics
    ├── Incidents.tsx   # Full incident timeline
    ├── Pipeline.tsx    # Deep pipeline view: graph + spans + diff + trigger
    ├── Metrics.tsx     # Metrics charts + raw remediation table
    └── System.tsx      # System health + platform configuration
```

---

## Data Sources

All data is polled every 5 seconds via TanStack Query:

| Endpoint | Hook | Used In |
|----------|------|---------|
| `GET /health` | `useHealth()` | Dashboard, System |
| `GET /metrics` | `usePlatformMetrics()` | System |
| `GET /api/metrics` | `useOpsMetrics()` | Dashboard, Pipeline, Metrics |
| `GET /metrics/history?limit=N` | `useMetricsHistory()` | Incidents, Metrics, Dashboard |
| `GET /pipeline/jobs` | `usePipelineJobs()` | Dashboard, Pipeline |
| `GET /pipeline/jobs/{id}` | `useJobDetail()` | Pipeline |
| `GET /api/remediation/{id}/timeline` | `useJobTimeline()` | Dashboard, Pipeline |
| `GET /api/pipeline/{id}/spans` | `useJobSpans()` | Dashboard, Pipeline |

Completed jobs (status `completed` / `failed`) stop polling automatically.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_BASE_URL` | `""` (same origin) | Override the API base URL |

In dev mode, all API paths (`/health`, `/metrics`, `/pipeline`, `/api`) are proxied to `http://localhost:8000` by the Vite dev server config.

For a standalone deployment pointing at a remote API:

```bash
VITE_API_BASE_URL=https://api.example.com npm run build
```

---

## Triggering a Pipeline

1. Navigate to **Pipeline** in the sidebar
2. Select a scenario from the dropdown in the **Trigger Pipeline** panel
3. Enter your API key (set via `AETHELGARD_API_KEY` environment variable)
4. Click **Trigger Pipeline** — the panel returns a job ID immediately (202 Accepted)
5. Select the new job from the list to watch the execution graph update live

The API key is stored in memory only and cleared on page reload. Enter it once per session via the session start screen.

---

## Design

- **Dark mode** forced by default (`class="dark"` on `<html>`)
- **Palette**: slate-950 background, brand cyan (`#06b6d4`) accent, status green/red/amber
- **Typography**: JetBrains Mono / Fira Code monospace throughout (reinforces DevOps/SRE aesthetic)
- **Minimal animations**: only CSS transitions and a slow pulse for running states
- **Layout**: fixed sidebar + scrollable main area; responsive grid from 1→2→3→4 columns
