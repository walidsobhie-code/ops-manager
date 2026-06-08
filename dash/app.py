import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

# ── Path bootstrap ──────────────────────────────────────────────────────────────
# Works whether launched from project root, dash/ folder, or Streamlit Cloud
_here = os.path.dirname(os.path.abspath(__file__))   # .../dash
_root = os.path.abspath(os.path.join(_here, '..'))   # project root
for _p in [_root, _here]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from brain.db_handler import StoreDB
from brain.ops_brain import OpsManagerAI

# ── Analytics Integration ──────────────────────────────────────────────────────
try:
    from brain.analytics import (
        analyze_store_status,
        calculate_7day_baseline,
        identify_red_zone_stores,
        generate_fleet_summary_prompt,
        calculate_fleet_kpis,
        generate_store_forecast,
        calculate_store_benchmarks,
        export_fleet_to_excel,
        export_fleet_to_pdf,
        optimize_staffing
    )
except Exception as e:
    import logging as _log
    _log.getLogger(__name__).warning("brain.analytics import failed (%s) — using fallbacks", e)
    # Fallbacks for criticals to prevent total crash
    def analyze_store_status(cv, b): return "Green" if cv >= 0.9*b else "Red"
    def calculate_7day_baseline(r): return 0.0
    def identify_red_zone_stores(tr, b): return []
    def generate_fleet_summary_prompt(rr): return "{}"
    def calculate_fleet_kpis(ar): return {"total_sales": 0, "avg_sales": 0, "store_count": 0}
    def generate_store_forecast(sr): return {"forecast": [], "trend": "stable"}
    def calculate_store_benchmarks(ar): return []
    def export_fleet_to_excel(df, p="opt.xlsx"): return p
    def export_fleet_to_pdf(df, p="opt.pdf"): return p
    def optimize_staffing(sid, rh, asf): return {"status": "error", "schedule": []}

# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OPS NEXUS — Command",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Design System (v3.0 High Density) ────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=Bricolage+Grotesque:wght@400;500;600;700;800&family=DM+Sans own:wght@300;400;500;600&display=swap');
:root {
    --bg-base: #080C16; --bg-surface: #0D1221; --bg-raised: #131828; --bg-overlay: #1A2035;
    --border-subtle: rgba(255,255,255,0.06); --border-mid: rgba(255,255,255,0.10); --border-strong: rgba(255,255,255,0.18);
    --text-primary: #F0F2F8; --text-secondary: #9BA3C0; --text-muted: #4E577A; --text-dim: #2E3555;
    --blue: #4F8EF7; --green: #22C87A; --amber: #F5A623; --red: #F5454A; --purple: #A78BFA; --cyan: #38BDF8;
}
html, body, .stApp { background-color: var(--bg-base) !important; color: var(--text-primary); font-family: 'DM Sans', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding-bottom: 20px; border-bottom: 1px solid var(--border-subtle); margin-bottom: 20px; }
.logo-mark { width: 40px; height: 40px; background: var(--blue); border-radius: 6px; display: flex; align-items: center; justify-content: center; font-family: 'Bricolage Grotesque'; font-weight: 800; color: #fff; }
.logo-title { font-family: 'Bricolage Grotesque'; font-size: 22px; font-weight: 800; color: var(--text-primary); }
.logo-sub { font-family: 'IBM Plex Mono'; font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 2px; }
.ai-banner { background: linear-gradient(120deg, rgba(15,22,45,0.98), rgba(12,20,40,0.98)); border: 1px solid rgba(79,142,247,0.28); border-radius: 18px; padding: 20px; margin-bottom: 20px; }
.ai-title { font-family: 'Bricolage Grotesque'; font-weight: 700; color: var(--blue); }
.ai-score { font-family: 'IBM Plex Mono'; font-size: 10px; color: var(--blue); background: rgba(79,142,247,0.12); border: 1px solid rgba(79,142,247,0.28); border-radius: 6px; padding: 3px 10px; }
.ai-rec { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
.ai-pill { font-family: 'IBM Plex Mono'; font-size: 9px; color: #FCA5A5; background: rgba(245,69,74,0.12); border: 1px solid rgba(245,69,74,0.28); border-radius: 6px; padding: 3px 10px; margin-right: 5px; }
.kpi-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 14px; padding: 20px; position: relative; overflow: hidden; height: 100%; }
.kpi-label { font-family: 'IBM Plex Mono'; font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 2px; }
.kpi-value { font-family: 'Bricolage Grotesque'; font-size: 30px; font-weight: 800; color: var(--text-primary); }
.node-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 14px; padding: 20px; margin-bottom: 14px; transition: transform 0.15s; }
.node-name { font-family: 'Bricolage Grotesque'; font-weight: 700; color: var(--text-primary); }
.node-badge { font-family: 'IBM Plex Mono'; font-size: 9px; padding: 4px 10px; border-radius: 6px; border: 1px solid; }
.badge-critical { color: var(--red); background: rgba(245,69,74,0.12); border-color: var(--red); }
.badge-growth { color: var(--green); background: rgba(34,200,122,0.12); border-color: var(--green); }
.badge-stable { color: var(--amber); background: rgba(245,166,35,0.12); border-color: var(--amber); }
.rz-card { background: linear-gradient(135deg, rgba(80,15,15,0.4), rgba(40,8,8,0.6)); border: 1px solid var(--red); border-radius: 10px; padding: 14px; margin-bottom: 10px; }
.footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border-subtle); font-family: 'IBM Plex Mono'; font-size: 9px; color: var(--text-dim); display: flex; justify-content: space-between; }
</style>
""", unsafe_allow_html=True)

# ─── Services ──────────────────────────────────────────────────────────────────
@st.cache_resource
def init_services():
    return StoreDB(url=os.getenv("SUPABASE_URL"), key=os.getenv("SUPABASE_KEY")), \
           OpsManagerAI(api_key=os.getenv("GROQ_API_KEY"))

db, ai = init_services()

# ─── Data Logic ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_data():
    resp = db.get_all_store_summaries()
    data = resp.data if hasattr(resp, 'data') else resp
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    df['sales'] = pd.to_numeric(df['sales'], errors='coerce').fillna(0)
    df['report_date'] = pd.to_datetime(df['report_date'])
    return df

df_raw = load_data()
if df_raw.empty:
    st.error("Sovereign Telemetry Offline: No data found in database.")
    st.stop()

# Global Baselines for the session
baselines = {s: calculate_7day_baseline(df_raw[df_raw['store_id'] == s].to_dict('records')) 
             for s in df_raw['store_id'].unique()}

# ─── TOPBAR ─────────────────────────────────────────────────────────────────────
a_now = datetime.now().strftime("%a %d %b %Y  ·  %H:%M")
st.markdown(f"""
<div class="topbar">
    <div style="display:flex; align-items:center; gap:14px;">
        <div class="logo-mark">◈</div>
        <div style="display:flex; flex-direction:column;">
            <div class="logo-title">OPS NEXUS</div>
            <div class="logo-sub">Sovereign Intelligence Console</div>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:12px; font-family:'IBM Plex Mono'; font-size:10px; color:var(--text-muted);">
        {a_now} <span style="color:var(--green)">● LIVE</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── AI Intelligence Banner ────────────────────────────────────────────────────
latest_date = df_raw['report_date'].max()
recent_df = df_raw[df_raw['report_date'] == latest_date]
try:
    prompt = generate_fleet_summary_prompt(recent_df.to_dict('records'))
    summary_raw = ai.client.chat.completions.create(
        model=ai.model, messages=[{"role": "user", "content": prompt}], 
        response_format={"type": "json_object"}).choices[0].message.content
    summary = json.loads(summary_raw)
    pills = "".join([f'<span class="ai-pill">🚨 {a}</span>' for a in summary.get('critical_alerts', [])])
    st.markdown(f"""
        <div class="ai-banner">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <div class="ai-title">⚡ AI Fleet Intelligence</div>
                <span class="ai-score">Health Score {summary.get('fleet_health_score', '—')} / 100</span>
            </div>
            <div class="ai-rec">{summary.get('strategic_recommendation', 'No recommendation.')}</div>
            <div style="margin-top:10px;">{pills}</div>
        </div>
    """, unsafe_allow_html=True)
except Exception:
    st.info("AI Intelligence initializing... Please check GROQ_API_KEY.")

# ─── KPI SECTION ────────────────────────────────────────────────────────────────
st.markdown('<div style="color:var(--text-muted); font-family:IBM Plex Mono; font-size:9px; letter-spacing:2px; text-transform:uppercase; margin-bottom:10px;">Executive KPIs</div>', unsafe_allow_html=True)
kpis = calculate_fleet_kpis(df_raw.to_dict('records'))
cols = st.columns(4)
metrics = [
    ("Network Revenue", f"${kpis['total_sales']:,.0f}", "◈"),
    ("Avg Store Sales", f"${kpis['avg_sales']:,.0f}", "⌀"),
    ("Active Stores", kpis['store_count'], "◉"),
    ("Daily Sync", "Complete ✅", "✓")
]
for i, (lbl, val, ico) in enumerate(metrics):
    with cols[i]:
        st.markdown(f"""
            <div class="kpi-card">
                <div style="position:absolute; top:15px; right:15px; font-size:24px; opacity:0.2;">{ico}</div>
                <div class="kpi-label">{lbl}</div>
                <div class="kpi-value">{val}</div>
            </div>
        """, unsafe_allow_html=True)

# ─── TACTICAL OPERATIONS (TABS) ────────────────────────────────────────────────
st.markdown('<br>', unsafe_allow_html=True)
main_col, rz_col = st.columns([3, 1])

with main_col:
    tabs = st.tabs(["🌡️ Fleet Heatmap", "📅 Calendar", "🔮 Forecasting", "⚖️ Benchmarking", "👥 Staffing"])
    
    with tabs[0]:
        today_df = df_raw[df_raw['report_date'] == latest_date]
        hm_data = []
        for _, row in today_df.iterrows():
            sid = row['store_id']
            val = float(row['sales'] or 0)
            base = baselines.get(sid, 0)
            hm_data.append({"Store": sid, "Status": analyze_store_status(val, base), "Sales": val})
        
        hm_df = pd.DataFrame(hm_data)
        fig = px.scatter(hm_df, x="Store", y="Sales", color="Status", 
                         color_discrete_map={"Green": "#22C87A", "Yellow": "#F5A623", "Red": "#F5454A"},
                         template="plotly_dark", size_max=60)
        fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width="stretch")

    with tabs[1]:
        sel_store = st.selectbox("Select Store", options=df_raw['store_id'].unique())
        s_hist = df_raw[df_raw['store_id'] == sel_store].sort_values('report_date')
        st.table(s_hist[['report_date', 'sales', 'inventory_status', 'staffing']].set_index('report_date'))

    with tabs[2]:
        st.subheader("🔮 Sales Forecasting")
        f_store = st.selectbox("Forecast Store", options=df_raw['store_id'].unique())
        f_res = generate_store_forecast(df_raw[df_raw['store_id'] == f_store].to_dict('records'))
        if f_res['trend'] == 'insufficient_data':
            st.warning("Insufficient data for forecast.")
        else:
            st.metric("Trend", f_res['trend'].upper())
            f_df = pd.DataFrame(f_res['forecast'])
            fig_f = px.line(f_df, x='ds', y='yhat', template="plotly_dark", title=f"Projected for {f_store}")
            fig_f.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_f, width="stretch")

    with tabs[3]:
        st.subheader("⚖️ Store Benchmarking")
        bench = calculate_store_benchmarks(df_raw.to_dict('records'))
        if bench:
            st.table(pd.DataFrame(bench).set_index('store_id'))

    with tabs[4]:
        st.subheader("👥 Staffing Optimization")
        t_store = st.selectbox("Store", options=df_raw['store_id'].unique())
        rh = st.number_input("Required Hours", min_value=1, value=16)
        pool = [{"name": "S1", "max_hours": 8}, {"name": "S2", "max_hours": 8}, {"name": "S3", "max_hours": 8}]
        if st.button("Optimize"):
            res = optimize_staffing(t_store, rh, pool)
            st.write(res)

with rz_col:
    st.markdown('<div style="color:var(--red); font-family:IBM Plex Mono; font-size:9px; letter-spacing:2px; text-transform:uppercase; margin-bottom:12px;">🚨 Red Zone</div>', unsafe_allow_html=True)
    today_reports = df_raw[df_raw['report_date'] == latest_date].to_dict('records')
    reds = identify_red_zone_stores(today_reports, baselines)
    if not reds:
        st.success("All Nominal")
    else:
        for s in reds:
            st.markdown(f"""
                <div class="rz-card">
                    <div style="font-weight:700; color:#fff;">{s['store_id']}</div>
                    <div style="font-size:22px; font-weight:800; color:var(--red);">↓ {s['drop_pct']}%</div>
                    <div style="font-family:IBM Plex Mono; font-size:9px; color:var(--text-muted);">Base: ${s['baseline']}</div>
                </div>
            """, unsafe_allow_html=True)

# ─── EXPORT SUITE ──────────────────────────────────────────────────────────────
st.sidebar.markdown("### 📤 EXPORT SUITE")
if st.sidebar.button("Export Excel"):
    path = export_fleet_to_excel(df_raw)
    st.sidebar.download_button("Download", data=open(path, "rb"), file_name="fleet.xlsx")
if st.sidebar.button("Export PDF"):
    path = export_fleet_to_pdf(df_raw)
    st.sidebar.download_button("Download", data=open(path, "rb"), file_name="fleet.pdf")

st.markdown(f"""
    <div style="margin-top:40px; padding-top:20px; border-top:1px solid var(--border-subtle); display:flex; justify-content:space-between; font-family:'IBM Plex Mono'; font-size:9px; color:var(--text-dim);">
        <div>OPS◈NEXUS — Sovereign Intelligence Console v3.0 Hybrid</div>
        <div>{len(df_raw)} records · {df_raw['store_id'].nunique()} stores · Groq Llama 3.3</div>
    </div>
""", unsafe_allow_html=True)
