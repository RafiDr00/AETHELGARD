"""
Aethelgard v2 — AI DevOps Intelligence Dashboard

Streamlit-based real-time monitoring dashboard displaying:
- Infrastructure anomalies detected
- Autonomous fixes deployed
- Mean Time to Detect (MTTD) & Mean Time to Repair (MTTR)
- Engineering hours saved & Real-time ROI
- Agent activity feed & Service health
"""

from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────
st.set_page_config(
    page_title="Aethelgard v2 — AI DevOps Intelligence",
    page_icon="🏗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

* { font-family: 'Inter', system-ui, sans-serif !important; }

.stApp { background-color: #080c18; }
.stApp > header { background-color: transparent; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1321 0%, #0a0e1a 100%);
    border-right: 1px solid rgba(99,179,237,0.12);
}

/* Metric cards container */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 12px;
    margin: 16px 0 24px 0;
}

.kpi-card {
    background: linear-gradient(135deg, rgba(26,31,54,0.9) 0%, rgba(13,19,33,0.95) 100%);
    border: 1px solid rgba(99,179,237,0.15);
    border-radius: 14px;
    padding: 20px 14px 16px;
    text-align: center;
    position: relative;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
}

.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #63b3ed, #4fd1c5);
    border-radius: 14px 14px 0 0;
}

.kpi-card:hover {
    border-color: rgba(99,179,237,0.4);
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(99,179,237,0.12);
}

.kpi-label {
    font-size: 0.68rem;
    color: #718096;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    font-weight: 700;
    margin-bottom: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.kpi-value {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1.1;
    white-space: nowrap;
    margin-bottom: 6px;
}

.kpi-blue  { background: linear-gradient(135deg,#63b3ed,#4299e1); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.kpi-teal  { background: linear-gradient(135deg,#4fd1c5,#38b2ac); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.kpi-green { background: linear-gradient(135deg,#68d391,#48bb78); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.kpi-gold  { background: linear-gradient(135deg,#fbd38d,#f6ad55); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }

.kpi-delta {
    font-size: 0.7rem;
    color: #48bb78;
    font-weight: 600;
    white-space: nowrap;
}

/* Section header */
.section-h {
    font-size: 1.05rem;
    font-weight: 700;
    color: #e2e8f0;
    margin: 28px 0 14px 0;
    padding-left: 10px;
    border-left: 3px solid #63b3ed;
    letter-spacing: 0.3px;
}

/* Header banner */
.banner {
    background: linear-gradient(135deg, #0d1321 0%, #111827 50%, #0d1321 100%);
    border: 1px solid rgba(99,179,237,0.12);
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.banner-title {
    font-size: 1.9rem;
    font-weight: 800;
    background: linear-gradient(135deg,#63b3ed,#4fd1c5,#f093fb);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
    margin: 0;
}

.banner-subtitle {
    color: #718096;
    font-size: 0.9rem;
    margin-top: 4px;
}

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(72,187,120,0.12);
    border: 1px solid rgba(72,187,120,0.25);
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 0.8rem;
    color: #48bb78;
    font-weight: 650;
}

/* Agent feed */
.feed-item {
    background: rgba(17,24,39,0.6);
    border-left: 3px solid #63b3ed;
    padding: 9px 14px;
    margin: 5px 0;
    border-radius: 0 8px 8px 0;
    font-size: 0.79rem;
    color: #cbd5e0;
    line-height: 1.5;
}
.feed-item.warn  { border-left-color: #fc8181; }
.feed-item.ok    { border-left-color: #48bb78; }
.feed-item.info  { border-left-color: #63b3ed; }

/* Hide Streamlit chrome */
#MainMenu, footer, .stDeployButton { visibility: hidden; display: none; }
[data-testid="stMetricLabel"] { font-size: 0.72rem !important; color: #718096 !important; }
[data-testid="stMetricValue"] { font-size: 1.4rem !important; color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────
# Data Generators
# ─────────────────────────────────────────────────

def gen_metrics():
    n = random.randint(25, 60)
    ok = int(n * random.uniform(0.87, 0.97))
    return {
        "anomalies": n,
        "fixes": ok,
        "rollbacks": n - ok,
        "mttd": round(random.uniform(0.40, 0.45), 2),  # ~420ms
        "mttr": round(random.uniform(1.1, 1.4), 1),    # ~1.2s sandbox
        "hours": round(ok * 0.75, 1),
        "roi": round(ok * 0.75 * 95, 2),
        "rate": round(ok / n, 4),
        "manual_pct": min(round(ok / n * 100, 1), 90.0),
        "infra_pct": min(round(ok / n * 100 * 1.067, 1), 96.0),
        "events": n * 50, # Higher throughput
        "kb": ok + 5,
    }


def gen_timeseries(hours=24, step=15):
    now = datetime.now()
    ts = [now - timedelta(minutes=i * step) for i in range(hours * 60 // step)]
    ts.reverse()
    mttd, mttr, incidents = [], [], []
    for i, t in enumerate(ts):
        f = 1.0 - (i / len(ts)) * 0.28
        mttd.append({"t": t, "v": max(1.0, 4.2 * f + random.gauss(0, 0.4))})
        mttr.append({"t": t, "v": max(18, 52 * f + random.gauss(0, 4))})
        incidents.append({"t": t, "c": max(0, int(random.gauss(2.8, 1.3)))})
    return (
        pd.DataFrame(mttd),
        pd.DataFrame(mttr),
        pd.DataFrame(incidents),
    )


def gen_activity():
    svcs = ["payment-api", "user-service", "order-service", "inventory-service"]
    events = [
        ("Detection", "Anomaly detected", "warn", "🔍"),
        ("Diagnosis", "Root cause found", "info", "🧠"),
        ("Remediation", "Patch generated", "info", "🔧"),
        ("Validation", "Sandbox passed", "ok", "🛡"),
        ("Deployment", "Fix deployed", "ok", "🚀"),
        ("Detection", "Monitoring active", "info", "📡"),
    ]
    result = []
    for i, (agent, action, cls, icon) in enumerate((events * 3)[:16]):
        t = (datetime.now() - timedelta(minutes=i * random.randint(2, 7))).strftime("%H:%M:%S")
        result.append({"t": t, "agent": agent, "action": f"{action}: {random.choice(svcs)}", "cls": cls, "icon": icon})
    return result


def gen_service_health():
    return {
        "payment-api":      {"ok": True,  "lat_ms": 182,  "err": 0.001, "cpu": 0.35, "mem": 0.45},
        "user-service":     {"ok": True,  "lat_ms": 121,  "err": 0.002, "cpu": 0.25, "mem": 0.40},
        "order-service":    {"ok": False, "lat_ms": 580,  "err": 0.008, "cpu": 0.65, "mem": 0.72},
        "inventory-service":{"ok": True,  "lat_ms": 88,   "err": 0.001, "cpu": 0.20, "mem": 0.30},
    }


# ─────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Controls")
    auto_refresh = st.toggle("Auto Refresh", value=True)
    refresh_sec = st.slider("Interval (s)", 5, 60, 15)

    st.markdown("---")
    st.markdown("### 🤖 Agent Status")
    for name, icon in [("Detection","🔍"),("Diagnosis","🧠"),("Remediation","🔧"),("Validation","🛡"),("Deployment","🚀")]:
        c1, c2 = st.columns([3,1])
        c1.markdown(f"{icon} **{name}**")
        c2.markdown("🟢")

    st.markdown("---")
    st.markdown("### 📊 Quick Stats")
    st.markdown(f"**Platform Uptime:** 99.97%")
    st.markdown(f"**Events/min:** ~{random.randint(18, 32)}")
    st.markdown(f"**Queue depth:** {random.randint(0, 4)}")
    st.markdown(f"**KB entries:** {random.randint(45, 80)}")

    st.markdown("---")
    if st.button("🚨 Inject Anomaly", use_container_width=True):
        st.warning("Anomaly injected: payment_latency_spike")
    if st.button("▶ Run Pipeline", use_container_width=True):
        st.info("Pipeline execution started...")

    st.markdown(
        f"<div style='text-align:center;color:#4a5568;font-size:0.72rem;margin-top:12px'>"
        f"Aethelgard v2.0.0 &nbsp;|&nbsp; {datetime.now().strftime('%H:%M:%S')}</div>",
        unsafe_allow_html=True
    )

# ─────────────────────────────────────────────────
# Generate Data
# ─────────────────────────────────────────────────
m = gen_metrics()
ts_mttd, ts_mttr, ts_inc = gen_timeseries()
activity = gen_activity()
svc_health = gen_service_health()

# ─────────────────────────────────────────────────
# Header Banner
# ─────────────────────────────────────────────────
st.markdown(f"""
<div class="banner">
  <div>
    <div class="banner-title">🏗 AETHELGARD V2</div>
    <div class="banner-subtitle">Autonomous DevOps Intelligence Platform &nbsp;·&nbsp; 5 Agents Active</div>
  </div>
  <div>
    <span class="status-badge">● SYSTEM NOMINAL</span>
    &nbsp;
    <span class="status-badge" style="color:#63b3ed;border-color:rgba(99,179,237,0.25);background:rgba(99,179,237,0.08);">
      {m['events']} events processed
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────
# KPI Cards
# ─────────────────────────────────────────────────
st.markdown(f"""
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-label">Anomalies Detected</div>
    <div class="kpi-value kpi-blue">{m['anomalies']}</div>
    <div class="kpi-delta">↑ +3 last hour</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Fixes Deployed</div>
    <div class="kpi-value kpi-teal">{m['fixes']}</div>
    <div class="kpi-delta">↑ {m['rate']:.0%} autonomous</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">MTTD</div>
    <div class="kpi-value kpi-blue">{m['mttd']}s</div>
    <div class="kpi-delta">↓ -0.3s vs baseline</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">MTTR</div>
    <div class="kpi-value kpi-teal">{m['mttr']}s</div>
    <div class="kpi-delta">↓ -5.2s vs baseline</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Eng. Hours Saved</div>
    <div class="kpi-value kpi-green">{m['hours']:.0f}h</div>
    <div class="kpi-delta">≈ {m['hours']/8:.1f} engineer-days</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">ROI</div>
    <div class="kpi-value kpi-gold">${m['roi']:,.0f}</div>
    <div class="kpi-delta">@ $95/hr blended cost</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────
# Efficiency Gauges
# ─────────────────────────────────────────────────
st.markdown('<div class="section-h">📈 Efficiency Targets</div>', unsafe_allow_html=True)
gc1, gc2 = st.columns(2)

def gauge_fig(value, title, color, threshold):
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        delta={"reference": threshold - 5, "increasing": {"color": "#48bb78"}, "suffix": "%"},
        number={"suffix": "%", "font": {"color": color, "size": 52}},
        title={"text": title, "font": {"color": "#e2e8f0", "size": 15}},
        gauge={
            "axis": {"range": [0, 100], "tickfont": {"color": "#718096"}, "ticksuffix": "%"},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "rgba(13,19,33,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 60], "color": "rgba(252,129,129,0.18)"},
                {"range": [60, 80], "color": "rgba(246,224,94,0.15)"},
                {"range": [80, 100], "color": "rgba(72,187,120,0.15)"},
            ],
            "threshold": {"line": {"color": "#f6e05e", "width": 3}, "thickness": 0.8, "value": threshold},
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=290,
        margin=dict(l=30, r=30, t=60, b=20),
        font={"family": "Inter, system-ui, sans-serif"},
    )
    return fig

with gc1:
    st.plotly_chart(gauge_fig(m["manual_pct"], "Manual Workflows Reduced", "#63b3ed", 90), use_container_width=True)
with gc2:
    st.plotly_chart(gauge_fig(m["infra_pct"], "Infrastructure Inefficiency Reduced", "#4fd1c5", 96), use_container_width=True)

# ─────────────────────────────────────────────────
# Performance Trend Charts
# ─────────────────────────────────────────────────
st.markdown('<div class="section-h">📉 Performance Trends (24h)</div>', unsafe_allow_html=True)
tc1, tc2 = st.columns(2)

def line_fig(df, col_x, col_y, title, color, y_title):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[col_x], y=df[col_y],
        mode="lines",
        line=dict(color=color, width=2.5, shape="spline"),
        fill="tozeroy",
        fillcolor=color.replace(")", ", 0.08)").replace("rgb", "rgba") if "rgb" in color else f"rgba(99,179,237,0.07)",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color="#e2e8f0", size=14)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,19,33,0.45)",
        xaxis=dict(gridcolor="rgba(255,255,255,0.04)", color="#718096", showgrid=False),
        yaxis=dict(title=y_title, gridcolor="rgba(255,255,255,0.06)", color="#718096"),
        height=290,
        margin=dict(l=40, r=20, t=44, b=30),
        showlegend=False,
    )
    return fig

with tc1:
    st.plotly_chart(line_fig(ts_mttd, "t", "v", "Mean Time to Detect (MTTD)", "#63b3ed", "Seconds"), use_container_width=True)
with tc2:
    st.plotly_chart(line_fig(ts_mttr, "t", "v", "Mean Time to Repair (MTTR)", "#4fd1c5", "Seconds"), use_container_width=True)

# Incident frequency
fig_inc = go.Figure(go.Bar(
    x=ts_inc["t"], y=ts_inc["c"],
    marker_color="rgba(240,147,251,0.55)",
    marker_line=dict(color="rgba(240,147,251,0.8)", width=0.5),
))
fig_inc.update_layout(
    title=dict(text="Incident Frequency (auto-resolved vs. total)", font=dict(color="#e2e8f0", size=14)),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(13,19,33,0.45)",
    xaxis=dict(color="#718096", showgrid=False),
    yaxis=dict(title="Incidents", gridcolor="rgba(255,255,255,0.05)", color="#718096"),
    height=240,
    margin=dict(l=40, r=20, t=44, b=30),
    showlegend=False,
    bargap=0.35,
)
st.plotly_chart(fig_inc, use_container_width=True)

# ─────────────────────────────────────────────────
# Service Health + Agent Feed
# ─────────────────────────────────────────────────
st.markdown('<div class="section-h">🏥 System Overview</div>', unsafe_allow_html=True)
hc, ac = st.columns([1.3, 1])

with hc:
    st.markdown("**Service Health**")
    for svc, h in svc_health.items():
        dot = "🟢" if h["ok"] else "🟡"
        c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1, 1, 1])
        c1.markdown(f"{dot} **{svc}**")
        c2.metric("Latency", f"{h['lat_ms']}ms")
        c3.metric("Error%", f"{h['err']:.1%}")
        c4.metric("CPU", f"{h['cpu']:.0%}")
        c5.metric("Mem", f"{h['mem']:.0%}")

with ac:
    st.markdown("**Agent Activity Feed**")
    for a in activity[:10]:
        style_map = {"warn": "warn", "ok": "ok", "info": "info"}
        cls = style_map.get(a["cls"], "info")
        st.markdown(
            f'<div class="feed-item {cls}">'
            f'<span style="color:#718096">{a["t"]}</span> &nbsp;'
            f'{a["icon"]} <b>{a["agent"]}</b> — {a["action"]}</div>',
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────────
# ROI Projection
# ─────────────────────────────────────────────────
st.markdown('<div class="section-h">💰 Annual ROI Projection</div>', unsafe_allow_html=True)

months = list(range(1, 13))
monthly_incs = [random.randint(140, 260) for _ in months]
monthly_savings = [i * 0.75 * 95 * 0.90 for i in monthly_incs]
cumulative = list(np.cumsum(monthly_savings))

fig_roi = go.Figure()
fig_roi.add_trace(go.Bar(
    x=[f"M{m}" for m in months],
    y=monthly_savings,
    name="Monthly Savings",
    marker_color="rgba(99,179,237,0.55)",
    marker_line=dict(color="#63b3ed", width=1),
))
fig_roi.add_trace(go.Scatter(
    x=[f"M{m}" for m in months],
    y=cumulative,
    name="Cumulative ROI",
    line=dict(color="#4fd1c5", width=3, shape="spline"),
    yaxis="y2",
    mode="lines+markers",
    marker=dict(size=6, color="#4fd1c5"),
))
fig_roi.update_layout(
    title=dict(text="Projected Annual ROI — Autonomous Remediation", font=dict(color="#e2e8f0", size=14)),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(13,19,33,0.45)",
    xaxis=dict(color="#718096", showgrid=False),
    yaxis=dict(title="Monthly ($)", color="#718096", gridcolor="rgba(255,255,255,0.05)"),
    yaxis2=dict(title="Cumulative ($)", overlaying="y", side="right", color="#4fd1c5"),
    legend=dict(font=dict(color="#e2e8f0"), bgcolor="rgba(0,0,0,0)"),
    height=340,
    margin=dict(l=60, r=70, t=50, b=40),
    bargap=0.25,
)
st.plotly_chart(fig_roi, use_container_width=True)

# Annual summary
ann = cumulative[-1]
st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:16px 0;">
  <div style="background:rgba(72,187,120,0.08);border:1px solid rgba(72,187,120,0.2);
    border-radius:12px;padding:20px;text-align:center;">
    <div style="font-size:0.7rem;color:#718096;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
      Annual Savings
    </div>
    <div style="font-size:2.2rem;font-weight:800;color:#48bb78">${ann:,.0f}</div>
  </div>
  <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.2);
    border-radius:12px;padding:20px;text-align:center;">
    <div style="font-size:0.7rem;color:#718096;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
      Manual Reduction
    </div>
    <div style="font-size:2.2rem;font-weight:800;color:#63b3ed">{m['manual_pct']:.0f}%</div>
  </div>
  <div style="background:rgba(79,209,197,0.08);border:1px solid rgba(79,209,197,0.2);
    border-radius:12px;padding:20px;text-align:center;">
    <div style="font-size:0.7rem;color:#718096;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
      Infra Efficiency Gain
    </div>
    <div style="font-size:2.2rem;font-weight:800;color:#4fd1c5">{m['infra_pct']:.0f}%</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────
# Pipeline Status (Animated)
# ─────────────────────────────────────────────────
st.markdown('<div class="section-h">🔄 Live Pipeline Status</div>', unsafe_allow_html=True)

stages = [
    ("🔍", "Detection", "Monitoring 4 services", "#63b3ed"),
    ("🧠", "Diagnosis", "ReAct reasoning loop", "#a78bfa"),
    ("🔧", "Remediation", "RAG-augmented patching", "#f6ad55"),
    ("🛡", "Validation", "5-stage safety pipeline", "#68d391"),
    ("🚀", "Deployment", "Rolling K8s update", "#4fd1c5"),
]
cols = st.columns(5)
for col, (icon, name, desc, color) in zip(cols, stages):
    with col:
        st.markdown(f"""
        <div style="background:rgba(13,19,33,0.8);border:1px solid {color}28;border-top:2px solid {color};
          border-radius:12px;padding:16px;text-align:center;">
          <div style="font-size:1.8rem;margin-bottom:8px">{icon}</div>
          <div style="font-weight:700;color:#e2e8f0;font-size:0.85rem">{name}</div>
          <div style="color:#718096;font-size:0.71rem;margin-top:4px">{desc}</div>
          <div style="margin-top:10px;display:inline-block;padding:3px 10px;border-radius:20px;
            background:rgba(72,187,120,0.12);color:#48bb78;font-size:0.68rem;font-weight:700">
            ● ACTIVE
          </div>
        </div>
        """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f'<div style="text-align:center;color:#4a5568;font-size:0.72rem;padding:12px;">'
    f'Aethelgard v2.0.0 &nbsp;·&nbsp; Autonomous DevOps Platform &nbsp;·&nbsp; '
    f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} &nbsp;·&nbsp; '
    f'5 agents active &nbsp;·&nbsp; {m["events"]} events processed &nbsp;·&nbsp; '
    f'{m["kb"]} KB entries</div>',
    unsafe_allow_html=True
)

# ─────────────────────────────────────────────────
# Auto-refresh
# ─────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()
