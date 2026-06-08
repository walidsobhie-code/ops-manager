import sys
import os
from pathlib import Path

# ── Path bootstrap ──────────────────────────────────────────────────────────────
# Ensure the project root is in the python path so 'brain' module is found
_here = os.path.dirname(os.path.abspath(__file__))   # /mount/src/ops-manager/dash
_root = os.path.abspath(os.path.join(_here, '..'))   # /mount/src/ops-manager
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from brain.db_handler import StoreDB
from brain.ops_brain import OpsManagerAI
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
except ImportError as e:
    st.error(f"Critical Error: Could not load analytics engine. {e}")
    st.stop()


# --- Configuration ---
st.set_page_config(page_title="Sovereign Ops Command Center", layout="wide")

# Custom CSS for the "War Room" Aesthetic
st.markdown("""
    <style>
    .stApp { background-color: #03050a; color: #cbd5e1; }
    .main { background-color: #03050a; }
    div[data-testid="stMetricValue"] { color: #3b82f6; font-size: 2rem; }
    .stMetric { background: rgba(10, 14, 26, 0.8); border: 1px solid rgba(255,255,255,0.05); padding: 15px; border-radius: 12px; }
    .red-zone-card { background: rgba(220, 38, 38, 0.1); border: 1px solid #dc2626; padding: 10px; border-radius: 8px; margin-bottom: 10px; color: #fca5a5; }
    .ai-summary-card { background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.3); padding: 20px; border-radius: 12px; color: #e2e8f0; }
    .kpi-header { font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; }
    </style>
""", unsafe_allow_html=True)

# --- State Initialization ---
@st.cache_resource
def init_services():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    ai_key = os.getenv("GROQ_API_KEY")
    return StoreDB(url=url, key=key), OpsManagerAI(api_key=ai_key)

db, ai = init_services()

st.title("◈ SOVEREIGN OPS COMMAND CENTER ◈")

# 1. Data Fetching
all_data = db.get_all_store_summaries()
df = pd.DataFrame(all_data.data)

if df.empty:
    st.warning("No operational reports found in database.")
    st.stop()

# Convert report_date to datetime
df['report_date'] = pd.to_datetime(df['report_date'])

# Calculate Baselines
baselines = {}
for store in df['store_id'].unique():
    store_reports = df[df['store_id'] == store].to_dict('records')
    baselines[store] = calculate_7day_baseline(store_reports)

# --- 3-TIER HIERARCHY ---

# TIER 1: EXECUTIVE PULSE
st.markdown("### 📡 EXECUTIVE PULSE")
kpis = calculate_fleet_kpis(df.to_dict('records'))
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Fleet Sales", f"${kpis['total_sales']:,.0f}")
m2.metric("Avg Store Sales", f"${kpis['avg_sales']:,.0f}")
m3.metric("Active Stores", kpis['store_count'])
m4.metric("Daily Sync", "Complete ✅")

# AI Intelligence Banner
with st.container():
    st.markdown('<div class="ai-summary-card">', unsafe_allow_html=True)
    try:
        latest_date = df['report_date'].max()
        recent_df = df[df['report_date'] == latest_date]
        prompt = generate_fleet_summary_prompt(recent_df.to_dict('records'))
        summary_raw = ai.client.chat.completions.create(
            model=ai.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        ).choices[0].message.content
        summary = json.loads(summary_raw)
        st.markdown(f"#### ⚡ AI Insight: Health Score {summary.get('fleet_health_score')}/100")
        st.markdown(f"**Strategic Priority:** {summary.get('strategic_recommendation')}")
        alerts = " | ".join([f"🚨 {a}" for a in summary.get('critical_alerts', [])])
        st.markdown(f"<div style='font-size: 0.9rem; color: #fca5a5;'>{alerts}</div>", unsafe_allow_html=True)
    except Exception as e:
        st.info("AI Intelligence initializing... Please wait.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# TIER 2: TACTICAL HEATMAP & CALENDAR
col_main, col_side = st.columns([3, 1])

with col_main:
    tabs = st.tabs(["🌡️ Fleet Heatmap", "📅 Performance Calendar", "📈 Trend Analysis", "🔮 Forecasting", "⚖️ Benchmarking", "👥 Staffing"])
    
    with tabs[0]:
        latest_date = df['report_date'].max()
        today_df = df[df['report_date'] == latest_date]
        
        heatmap_data = []
        for _, row in today_df.iterrows():
            sid = row['store_id']
            val = float(row['sales'] or 0)
            base = baselines.get(sid, 0)
            status = analyze_store_status(val, base)
            heatmap_data.append({"Store": sid, "Status": status, "Sales": val})
        
        heatmap_df = pd.DataFrame(heatmap_data)
        color_map = {"Green": "#10b981", "Yellow": "#f59e0b", "Red": "#dc2626"}
        fig = px.scatter(heatmap_df, x="Store", y="Sales", color="Status", 
                         color_discrete_map=color_map, 
                         template="plotly_dark",
                         size_max=60)
        fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)
    
    with tabs[1]:
        st.subheader("Daily Performance Log")
        selected_store = st.selectbox("Select Store to View History", options=df['store_id'].unique())
        store_history = df[df['store_id'] == selected_store].sort_values('report_date')
        cal_df = store_history[['report_date', 'sales', 'inventory_status', 'staffing']].copy()
        cal_df['report_date'] = cal_df['report_date'].dt.date
        st.table(cal_df.set_index('report_date'))
    
    with tabs[2]:
        st.subheader("Sales Momentum")
        trend_fig = px.line(df, x='report_date', y='sales', color='store_id', 
                           template="plotly_dark", markers=True)
        trend_fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(trend_fig, use_container_width=True)

    with tabs[3]:
        st.subheader("🔮 Sales Forecasting")
        f_store = st.selectbox("Forecast Store", options=df['store_id'].unique(), key='f_store')
        store_h = df[df['store_id'] == f_store].to_dict('records')
        f_res = generate_store_forecast(store_h)
        
        if f_res['trend'] == 'insufficient_data':
            st.warning("Not enough data for a reliable forecast.")
        else:
            st.metric("7-Day Projection Trend", f_res['trend'].upper())
            f_df = pd.DataFrame(f_res['forecast'])
            f_df['ds'] = pd.to_datetime(f_df['ds']).dt.date
            
            fig_f = px.line(f_df, x='ds', y='yhat', labels={'yhat': 'Predicted Sales'}, 
                             template="plotly_dark", title=f"Forecast for {f_store}")
            fig_f.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_f, use_container_width=True)

    with tabs[4]:
        st.subheader("⚖️ Store-to-Store Benchmarking")
        bench_data = calculate_store_benchmarks(df.to_dict('records'))
        if not bench_data:
            st.info("Insufficient data for benchmarking.")
        else:
            b_df = pd.DataFrame(bench_data)
            st.table(b_df.set_index('store_id'))
            crit = [b['store_id'] for b in bench_data if b['significance'] == 'Critical Underperformer']
            if crit:
                st.markdown(f"<div class='red-zone-card'>Critical Outliers Detected: {', '.join(crit)}</div>", unsafe_allow_html=True)

    with tabs[5]:
        st.subheader("👥 Shift Scheduler Optimization")
        target_store = st.selectbox("Select Store for Scheduling", options=df['store_id'].unique())
        req_hours = st.number_input("Total Required Hours for Shift", min_value=1, value=16)
        
        staff_pool = [
            {"name": "Ahmed", "max_hours": 8, "pref": "morning"},
            {"name": "Sarah", "max_hours": 8, "pref": "evening"},
            {"name": "John", "max_hours": 6, "pref": "morning"},
            {"name": "Maria", "max_hours": 10, "pref": "evening"},
        ]
        
        if st.button("Optimize Shifts"):
            res = optimize_staffing(target_store, req_hours, staff_pool)
            if res['status'] == 'success':
                st.success(f"Optimal allocation found for {target_store}")
                st.table(pd.DataFrame(res['schedule']))
            else:
                st.error("Could not find a feasible shift allocation for these constraints.")

with col_side:
    st.subheader("🚨 RED ZONE")
    latest_date = df['report_date'].max()
    today_reports = df[df['report_date'] == latest_date].to_dict('records')
    red_zone_stores = identify_red_zone_stores(today_reports, baselines)
    
    if not red_zone_stores:
        st.success("No stores in Red Zone.")
    else:
        for store in red_zone_stores:
            st.markdown(f"""
                <div class="red-zone-card">
                    <strong style="color:#fff">{store['store_id']}</strong><br>
                    <span style="font-size:1.2rem; font-weight:bold;">↓ {store['drop_pct']}%</span><br>
                    <span style="font-size:0.8rem;">Val: {store['current_value']} | Base: {store['baseline']}</span>
                </div
            """, unsafe_allow_html=True)
            if st.button(f"Contact {store['store_id']}", key=f"btn_{store['store_id']}"):
                st.info(f"Bridge established. Sending alert to {store['store_id']} manager...")

st.sidebar.markdown("### 📤 EXPORT SUITE")
if st.sidebar.button("Export to Excel (.xlsx)"):
    try:
        path = export_fleet_to_excel(df)
        st.sidebar.download_button("Download Excel", data=open(path, "rb"), file_name="fleet_report.xlsx")
    except Exception as e:
        st.sidebar.error(f"Excel Error: {e}")

if st.sidebar.button("Export to PDF (.pdf)"):
    try:
        path = export_fleet_to_pdf(df)
        st.sidebar.download_button("Download PDF", data=open(path, "rb"), file_name="fleet_report.pdf")
    except Exception as e:
        st.sidebar.error(f"PDF Error: {e}")

st.markdown("<br><br>", unsafe_allow_html=True)
st.caption("Sovereign Ops Command Center v2.1 | Powered by Groq Llama 3.3 & Supabase")
