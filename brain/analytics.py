1|1|"""
2|2|brain/analytics.py
3|3|──────────────────
4|4|Pure-Python analytics helpers for OPS NEXUS dashboard.
5|5|No external dependencies beyond the stdlib — all heavy lifting
6|6|(Supabase, Groq, Streamlit) lives in the callers.
7|7|
8|8|Public API
9|9|----------
10|10|analyze_store_status(current_value, baseline)            -> str  "Green" | "Yellow" | "Red"
11|11|calculate_7day_baseline(store_reports)                   -> float
12|12|identify_red_zone_stores(today_reports, baselines)       -> list[dict]
13|13|generate_fleet_summary_prompt(recent_reports)            -> str
14|14|calculate_fleet_kpis(all_reports)                        -> dict
15|15|"""
16|16|
17|17|from __future__ import annotations
18|18|
19|19|import logging
20|20|from datetime import datetime, timedelta
21|21|from typing import Any, Dict, List, Optional
22|22|
23|23|logger = logging.getLogger(__name__)
24|24|
25|25|
26|26|# ─────────────────────────────────────────────────────────────────────────────
27|27|# 1. analyze_store_status
28|28|# ─────────────────────────────────────────────────────────────────────────────
29|29|def analyze_store_status(current_value: float, baseline: float) -> str:
30|30|    """
31|31|    Compare today's sales against the 7-day rolling baseline and return a
32|32|    traffic-light status string.
33|33|
34|34|    Thresholds
35|35|    ----------
36|36|    Green  : current >= 90 % of baseline  (on target or above)
37|37|    Yellow : 70 % <= current < 90 %       (mild underperformance)
38|38|    Red    : current < 70 % of baseline   (significant drop)
39|39|
40|40|    If baseline is 0 (new store / no history), returns "Green" to avoid
41|41|    false alarms.
42|42|    """
43|43|    if baseline <= 0:
44|44|        return "Green"
45|45|
46|46|    ratio = current_value / baseline
47|47|
48|48|    if ratio >= 0.90:
49|49|        return "Green"
50|50|    elif ratio >= 0.70:
51|51|        return "Yellow"
52|52|    else:
53|53|        return "Red"
54|54|
55|55|
56|56|# ─────────────────────────────────────────────────────────────────────────────
57|57|# 2. calculate_7day_baseline
58|58|# ─────────────────────────────────────────────────────────────────────────────
59|59|def calculate_7day_baseline(store_reports: List[Dict[str, Any]]) -> float:
60|60|    """
61|61|    Calculate a rolling 7-day average sales baseline for a single store.
62|62|
63|63|    Parameters
64|64|    ----------
65|65|    store_reports : list of report dicts, each containing at minimum:
66|66|        - 'report_date'  : str (ISO "YYYY-MM-DD") or datetime / date object
67|67|        - 'sales'        : numeric or str-numeric
68|68|
69|69|    Returns
70|70|    ------
71|71|    float  — average daily sales over the most recent 7 calendar days
72|72|             that have at least one report; 0.0 if no valid data.
73|73|    """
74|74|    if not store_reports:
75|75|        return 0.0
76|76|
77|77|    # Normalise dates and sales
78|78|    parsed: List[tuple[datetime, float]] = []
79|79|    for r in store_reports:
80|80|        try:
81|81|            raw_date = r.get("report_date")
82|82|            if isinstance(raw_date, str):
83|83|                raw_date = datetime.fromisoformat(raw_date.split("T")[0])
84|84|            elif hasattr(raw_date, "date"):          # datetime / pandas Timestamp
85|85|                raw_date = raw_date                  # already datetime-like
86|86|            sales = float(r.get("sales") or 0)
87|87|            parsed.append((raw_date, sales))
88|88|        except (TypeError, ValueError):
89|89|            continue
90|90|
91|91|    if not parsed:
92|92|        return 0.0
93|93|
94|94|    # Find the most recent date in the dataset
95|95|    most_recent = max(d for d, _ in parsed)
96|96|    cutoff      = most_recent - timedelta(days=6)   # last 7 days inclusive
97|97|
98|98|    recent_sales = [s for d, s in parsed if d >= cutoff and s > 0]
99|99|
100|100|    if not recent_sales:
101|101|        # Fall back to all-time average if last 7 days are empty
102|102|        all_sales = [s for _, s in parsed if s > 0]
103|103|        return round(sum(all_sales) / len(all_sales), 2) if all_sales else 0.0
104|104|
105|105|    return round(sum(recent_sales) / len(recent_sales), 2)
106|106|
107|107|
108|108|# ─────────────────────────────────────────────────────────────────────────────
109|109|# 3. identify_red_zone_stores
110|110|# ─────────────────────────────────────────────────────────────────────────────
111|111|def identify_red_zone_stores(
112|112|    today_reports: List[Dict[str, Any]],
113|113|    baselines: Dict[str, float],
114|114|    threshold_pct: float = 30.0,
115|115|) -> List[Dict[str, Any]]:
116|116|    """
117|117|    Identify stores whose current sales are below their baseline by at least
118|118|    `threshold_pct` percent.
119|119|
120|120|    Parameters
121|121|    ----------
122|122|    today_reports   : list of today's report dicts (store_id, sales, …)
123|123|    baselines       : dict  {store_id: baseline_float}
124|124|    threshold_pct   : drop % that triggers red-zone (default 30 %)
125|125|
126|126|    Returns
127|127|    ------
128|128|    list of dicts, each containing:
129|129|        store_id       : str
130|130|        current_value  : float
131|131|        baseline       : float
132|132|        drop_pct       : float  (positive number, e.g. 35.2)
133|133|    Sorted by drop_pct descending (worst first).
134|134|    """
135|135|    red_zone: List[Dict[str, Any]] = []
136|136|
137|137|    for report in today_reports:
138|138|        store_id = report.get("store_id")
139|139|        if not store_id:
140|140|            continue
141|141|
142|142|        current = float(report.get("sales") or 0)
143|143|        baseline = baselines.get(store_id, 0.0)
144|144|
145|145|        # Skip stores with no baseline history — can't assess performance
146|146|        if baseline <= 0:
147|147|            continue
148|148|
149|149|        drop_pct = (baseline - current) / baseline * 100
150|150|
151|151|        if drop_pct >= threshold_pct:
152|152|            red_zone.append({
153|153|                "store_id":      store_id,
154|154|                "current_value": round(current, 2),
155|155|                "baseline":      round(baseline, 2),
156|156|                "drop_pct":      round(drop_pct, 1),
157|157|            })
158|158|
159|159|    red_zone.sort(key=lambda x: x["drop_pct"], reverse=True)
160|160|    return red_zone
161|161|
162|162|
163|163|# ─────────────────────────────────────────────────────────────────────────────
164|164|# 4. generate_fleet_summary_prompt
165|165|# ─────────────────────────────────────────────────────────────────────────────
166|166|def generate_fleet_summary_prompt(recent_reports: List[Dict[str, Any]]) -> str:
167|167|    """
168|168|    Build a structured prompt for the Groq AI fleet intelligence banner.
169|169|
170|170|    The prompt instructs the model to return a strict JSON object with:
171|171|        fleet_health_score         : int   0-100
172|172|        strategic_recommendation   : str   one-sentence executive action item
173|173|        critical_alerts            : list[str]   up to 3 short alert strings
174|174|        top_performer              : str   store_id
175|175|        at_risk_stores             : list[str]   store_ids
176|176|
177|177|    Parameters
178|178|    ----------
179|179|    recent_reports : list of the latest report dicts for each store
180|180|    """
181|181|    if not recent_reports:
182|182|        return (
183|183|            'Return this exact JSON: {"fleet_health_score": 0, '
184|184|            '"strategic_recommendation": "No data available.", '
185|185|            '"critical_alerts": [], "top_performer": "", "at_risk_stores": []}'
186|186|        )
187|187|
188|188|    # Build a compact text summary of each store's status
189|189|    store_lines: List[str] = []
190|190|    for r in recent_reports:
191|191|        store_id  = r.get("store_id", "Unknown")
192|192|        sales     = r.get("sales", 0)
193|193|        inventory = r.get("inventory_status", "unknown")
194|194|        staffing  = r.get("staffing", "unknown")
195|195|        analysis  = r.get("analysis", "")
196|196|        store_lines.append(
197|197|            f"  • {store_id}: sales=${sales}, inventory={inventory}, "
198|198|            f"staffing={staffing}, AI note={analysis}"
199|199|        )
200|200|
201|201|    stores_block = "\\n".join(store_lines)
202|202|    report_date  = recent_reports[0].get("report_date", "today")
203|203|
204|204|    prompt = f"""You are the AI operations brain for a multi-store retail fleet.
205|205|Analyse the latest daily report data below and return a JSON object — nothing else.
206|206|
207|207|REPORT DATE: {report_date}
208|208|STORES ({len(recent_reports)} total):
209|209|{stores_block}
210|210|
211|211|Return ONLY valid JSON matching this exact schema (no markdown, no preamble):
212|212|{{
213|213|  "fleet_health_score": <integer 0-100, where 100 = all stores exceeding targets>,
214|214|  "strategic_recommendation": "<one clear, actionable sentence for the ops manager>",
215|215|  "critical_alerts": ["<alert 1>", "<alert 2>"],
216|216|  "top_performer": "<store_id of best performing store>",
217|217|  "at_risk_stores": ["<store_id>", ...]
218|218|}}
219|219|
220|220|Scoring guide:
221|221|- 90-100 : All stores ≥ target, no inventory or staffing issues
222|222|- 70-89  : Minor shortfalls in 1-2 stores
223|223|- 50-69  : Multiple stores underperforming or staffing gaps
224|224|- 30-49  : Significant revenue decline across fleet
225|225|- 0-29   : Critical — multiple stores in crisis
226|226|"""
227|227|    return prompt
228|228|
229|229|
230|230|# ─────────────────────────────────────────────────────────────────────────────
231|231|# 5. calculate_fleet_kpis
232|232|# ─────────────────────────────────────────────────────────────────────────────
233|233|def calculate_fleet_kpis(all_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
234|234|    """
235|235|    Calculate top-level fleet KPIs from the full report dataset.
236|236|
237|237|    Parameters
238|238|    ----------
239|239|    all_reports : list of all report dicts in the current date window
240|240|
241|241|    Returns
242|242|    -------
243|243|    dict with keys:
244|244|        total_sales   : float
245|245|        avg_sales     : float
246|246|        store_count   : int
247|247|        report_count  : int
248|248|        top_store     : str   (store_id with highest cumulative sales)
249|249|        top_sales     : float
250|250|    """
251|251|    if not all_reports:
252|252|        return {
253|253|            "total_sales":  0.0,
254|254|            "avg_sales":    0.0,
255|255|            "store_count":  0,
256|256|            "report_count": 0,
257|257|            "top_store":    "—",
258|258|            "top_sales":    0.0,
259|259|        }
260|260|
261|261|    store_totals: Dict[str, float] = {}
262|262|    for r in all_reports:
263|263|        sid   = r.get("store_id", "Unknown")
264|264|        sales = float(r.get("sales") or 0)
265|265|        store_totals[sid] = store_totals.get(sid, 0.0) + sales
266|266|
267|267|    total_sales  = sum(store_totals.values())
268|268|    store_count  = len(store_totals)
269|269|    avg_sales    = round(total_sales / store_count, 2) if store_count else 0.0
270|270|    top_store    = max(store_totals, key=store_totals.get) if store_totals else "—"
271|271|    top_sales    = store_totals.get(top_store, 0.0)
272|272|
273|273|    return {
274|274|        "total_sales":  round(total_sales, 2),
275|275|        "avg_sales":    avg_sales,
276|276|        "store_count":  store_count,
277|277|        "report_count": len(all_reports),
278|278|        "top_store":    top_store,
279|279|        "top_sales":    round(top_sales, 2),
280|280|    }
281|281|
282|282|# ─────────────────────────────────────────────────────────────────────────────
283|283|# 6. generate_store_forecast (Prophet)
284|284|# ─────────────────────────────────────────────────────────────────────────────
285|285|def generate_store_forecast(store_reports, periods: int = 7):
286|286|    """
287|287|    Predict future sales using Facebook Prophet.
288|288|    """
289|289|    # Import inside function to avoid global dependency issues during non-UI runs
290|290|    from prophet import Prophet
291|291|    import pandas as pd
292|292|    
293|293|    if not store_reports:
294|294|        return {"forecast": [], "trend": "stable"}
295|295|
296|296|    # Prepare dataframe for Prophet
297|297|    data = []
298|298|    for r in store_reports:
299|299|        date = r.get("report_date")
300|300|        if isinstance(date, str):
301|301|            date = date.split("T")[0]
302|302|        data.append({"ds": date, "y": float(r.get("sales") or 0)})
303|303|    
304|304|    df_prophet = pd.DataFrame(data)
305|305|    if len(df_prophet) < 2:
306|306|        return {"forecast": [], "trend": "insufficient_data"}
307|307|
308|308|    model = Prophet(daily_seasonality=True, yearly_seasonality=False, weekly_seasonality=True)
309|309|    model.fit(df_prophet)
310|310|    
311|311|    future = model.make_future_dataframe(periods=periods)
312|312|    forecast = model.predict(future)
313|313|    
314|314|    # Return last N points
315|315|    result = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(periods).to_dict('records')
316|316|    
317|317|    # Simple trend detection
318|318|    trend = "increasing" if result[-1]['yhat'] > result[0]['yhat'] else "decreasing"
319|319|    
320|320|    return {"forecast": result, "trend": trend}
321|321|
322|322|
323|323|# ─────────────────────────────────────────────────────────────────────────────
324|324|# 7. calculate_store_benchmarks (Z-Score)
325|325|# ─────────────────────────────────────────────────────────────────────────────
326|326|def calculate_store_benchmarks(all_reports):
327|327|    """
328|328|    Perform store-to-store benchmarking using Z-scores to find outliers.
329|329|    """
330|330|    from scipy import stats
331|331|    
332|332|    if not all_reports:
333|333|        return []
334|334|
335|335|    # Aggregate latest sales per store
336|336|    latest_sales = {}
337|337|    for r in all_reports:
338|338|        sid = r.get("store_id")
339|339|        latest_sales[sid] = float(r.get("sales") or 0)
340|340|    
341|341|    sales_values = list(latest_sales.values())
342|342|    if len(sales_values) < 2:
343|343|        return []
344|344|
345|345|    z_scores = stats.zscore(sales_values)
346|346|    
347|347|    benchmarks = []
348|348|    for i, (sid, val) in enumerate(latest_sales.items()):
349|349|        z = z_scores[i]
350|350|        significance = "Neutral"
351|351|        if z > 1.5: significance = "High Outlier (Positive)"
352|352|        elif z < -1.5: significance = "Critical Underperformer"
353|353|        
354|354|        benchmarks.append({
355|355|            "store_id": sid,
356|356|            "sales": val,
357|357|            "z_score": round(z, 2),
358|358|            "significance": significance
359|359|        })
360|360|    
361|361|    # Sort by Z-score (Worst performers first)
362|362|    benchmarks.sort(key=lambda x: x['z_score'])
363|363|    return benchmarks
364|364|
365|
366|# ─────────────────────────────────────────────────────────────────────────────
367|# 8. export_to_excel
368|# ─────────────────────────────────────────────────────────────────────────────
369|import openpyxl
370|from openpyxl.styles import Font, PatternFill
371|
372|def export_fleet_to_excel(df, output_path="fleet_report.xlsx"):
373|    """
374|    Exports current fleet dataframe to a formatted Excel file.
375|    """
376|    df.to_excel(output_path, index=False, sheet_name="Ops Report")
377|    wb = openpyxl.load_workbook(output_path)
378|    ws = wb.active
379|    
380|    # Header styling
381|    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
382|    header_font = Font(color="FFFFFF", bold=True)
383|    
384|    for cell in ws[1]:
385|        cell.fill = header_fill
386|        cell.font = header_font
387|        
388|    wb.save(output_path)
389|    return output_path
390|
391|
392|# ─────────────────────────────────────────────────────────────────────────────
393|# 9. export_to_pdf
394|# ─────────────────────────────────────────────────────────────────────────────
395|from weasyprint import HTML
396|
397|def export_fleet_to_pdf(df, output_path="fleet_report.pdf"):
398|    """
399|    Converts a simple HTML summary table to PDF.
400|    """
401|    html_content = f"""
402|    <html>
403|    <style>
404|        body {{ font-family: Arial, sans-serif; color: #333; }}
405|        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
406|        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
407|        th {{ background-color: #f2f2f2; }}
408|        h1 {{ color: #1f4e78; }}
409|    </style>
410|    <body>
411|        <h1>Sovereign Ops Fleet Report</h1>
412|        <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
413|        {df.to_html(index=False)}
414|    </body>
415|    </html>
416|    """
417|    HTML(string=html_content).write_pdf(output_path)
418|    return output_path
419|

# ─────────────────────────────────────────────────────────────────────────────
# 10. optimize_staffing (OR-Tools)
# ─────────────────────────────────────────────────────────────────────────────
from ortools.sat.python import cp_model

def optimize_staffing(store_id: str, required_hours: int, available_staff: List[Dict[str, Any]]):
    """
    Simple constraint solver to allocate shifts given available staff and total hour requirements.
    available_staff: list of { "name": str, "max_hours": int, "pref_shift": "morning"|"evening" }
    """
    model = cp_model.CpModel()
    
    # Variables: x[staff_id] = hours assigned to that staff
    staff_vars = {}
    for i, s in enumerate(available_staff):
        staff_vars[i] = model.NewIntVar(0, s.get("max_hours", 8), f"staff_{i}")
    
    # Constraint: Total hours must equal required_hours
    model.Add(sum(staff_vars.values()) == required_hours)
    
    solver = cp_model.CpSolver()
    status = solver.Solve()
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule = []
        for i, s in enumerate(available_staff):
            schedule.append({
                "name": s.get("name", f"Staff {i}"),
                "assigned_hours": solver.Value(staff_vars[i])
            })
        return {"status": "success", "schedule": schedule}
    
    return {"status": "infeasible", "schedule": []}
