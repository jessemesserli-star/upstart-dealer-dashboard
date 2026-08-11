"""Implementation Pipeline Summary — live Streamlit dashboard.

Reads the "Implementation Claude" sheet via a Google service account and renders the same
metrics as the weekly Slides deck (shared logic in metrics.py). Always-on: anyone with the
app URL sees current numbers without depending on anyone's laptop.

Setup: see README.md (share the sheet with the service-account email as Viewer, put the SA
JSON in st.secrets["gcp_service_account"]).
"""
import datetime
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build

import metrics

# ---- palette (matches the deck) ----
TEAL_D = "#0C6B60"; TEAL = "#0E8A7B"; MUTED = "#888780"; GRAY = "#5F5E5A"
UPRED = "#C0392B"; DOWNGREEN = "#2E7D46"
SEG = {"Setup in Progress": ("#F5E0A3", "#6B5A16"), "Launch Ready": ("#5DCAA5", "#FFFFFF"),
       "Launch Scheduled": ("#0F6E56", "#FFFFFF"), "Blocked": ("#E79684", "#FFFFFF")}

st.set_page_config(page_title="Implementation Pipeline Summary", layout="wide")

# ---- data access (service account) ----
@st.cache_resource
def _service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

@st.cache_data(ttl=600)  # cache 10 min so the app isn't hammering the API per view
def read_range(a1):
    res = _service().spreadsheets().values().get(
        spreadsheetId=metrics.SPREADSHEET_ID, range=a1,
        valueRenderOption="UNFORMATTED_VALUE", dateTimeRenderOption="FORMATTED_STRING").execute()
    return res.get("values", [])

# ---- small render helpers ----
def delta_line(cur, prev, unit="", lower_is_better=True, label="previous week"):
    if prev is None or cur is None:
        return "&nbsp;"
    pv = round(prev)  # display the comparator rounded to match the headline value
    if round(cur) == pv:
        return f"<span style='color:{MUTED}'>no change {label}: {pv}{unit}</span>"
    up = cur > prev
    good = (not up) if lower_is_better else up
    color = DOWNGREEN if good else UPRED
    arrow = "▲" if up else "▼"
    return f"<span style='color:{color}'>{arrow} {'up' if up else 'down'} {label}: {pv}{unit}</span>"

def kpi(label, value, sub_html):
    st.markdown(
        f"""<div style="background:#F1EFE8;border-radius:10px;padding:12px;text-align:center;height:118px;
             display:flex;flex-direction:column;justify-content:center;">
          <div style="font-size:12px;font-weight:600;color:{TEAL_D};text-transform:uppercase;line-height:1.2;">{label}</div>
          <div style="font-size:34px;font-weight:700;color:{TEAL};margin:2px 0;">{value}</div>
          <div style="font-size:11px;">{sub_html}</div>
        </div>""", unsafe_allow_html=True)

def pct(x): return "—" if x is None else f"{round(x)}%"
def num(x): return "—" if x is None else (str(int(x)) if float(x).is_integer() else f"{x:.1f}")

# ---- build ----
try:
    m = metrics.compute(read_range)
except Exception as e:
    st.error(f"Could not load data from the sheet. Check the service-account access / secrets.\n\n{e}")
    st.stop()

d = m["today"]
st.markdown(f"<h2 style='color:{TEAL_D};margin-bottom:0;'>Implementation Pipeline Summary "
            f"&mdash; {d.strftime('%A, %B %-d')}</h2>", unsafe_allow_html=True)
st.caption(f"Live from the Implementation Claude sheet · refreshed {datetime.datetime.now():%b %-d, %-I:%M %p}")
if st.button("↻ Refresh data"):
    st.cache_data.clear(); st.rerun()

# ---- KPI row ----
prev = m["prev"] or {}
c = st.columns(5)
cur, prv = m["fwk_cur"], m["fwk_prev"]
with c[0]:
    kpi("Total RTs in Pipeline", m["total"], delta_line(m["total"], prev.get("total"), lower_is_better=False))
with c[1]:
    kpi("Blocked RTs", m["blocked"], delta_line(m["blocked"], prev.get("blocked"), lower_is_better=True))
with c[2]:
    kpi("Med Days Launch Ready (4 wk)", num(cur["median"]),
        delta_line(cur["median"], prv["median"], lower_is_better=True, label="prior 4 wks"))
with c[3]:
    kpi("Launch Ready &gt;30 Days (4 wk)", pct(cur["over30"]),
        delta_line(cur["over30"], prv["over30"], unit="%", lower_is_better=True, label="prior 4 wks"))
with c[4]:
    kpi("Setup Issues (4 wk)", pct(cur["issues"]),
        delta_line(cur["issues"], prv["issues"], unit="%", lower_is_better=True, label="prior 4 wks"))

st.write("")
left, right = st.columns([1, 1])

# ---- left: Pipeline by Age stacked bar ----
with left:
    st.markdown(f"<div style='background:{TEAL_D};color:#E6F6F2;text-align:center;font-weight:600;"
                f"padding:6px;border-radius:8px;text-transform:uppercase;'>Pipeline by Age</div>", unsafe_allow_html=True)
    order = ["0-14", "15-29", "30+"]; labels = {"0-14": "0 – 14 days", "15-29": "15 – 29 days", "30+": "30+ days"}
    fig = go.Figure()
    for stt in metrics.STATUS_ORDER:
        fill, txt = SEG[stt]
        vals = [m["buckets"][b]["counts"][stt] for b in order]
        fig.add_bar(y=[labels[b] for b in order], x=vals, orientation="h", name=stt,
                    marker_color=fill, text=[v if v > 0 else "" for v in vals],
                    textposition="inside", insidetextanchor="middle",
                    textfont=dict(color=txt, size=13))
    fig.update_layout(barmode="stack", height=260, margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.18, x=0, font=dict(size=11)),
                      xaxis=dict(visible=False), yaxis=dict(autorange="reversed", tickfont=dict(size=12, color=TEAL_D)),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    # bucket totals + week-over-week as annotations at bar ends
    pkeys = {"0-14": "b0", "15-29": "b1", "30+": "b2"}
    for b in order:
        tot = m["buckets"][b]["count"]; pv = prev.get(pkeys[b])
        note = f"<b>{tot}</b>"
        if pv is not None and pv != tot:
            arrow = "▲" if tot > pv else "▼"; col = UPRED if tot > pv else DOWNGREEN
            note += f"  <span style='color:{col};font-size:10px'>{arrow} {pv}</span>"
        fig.add_annotation(x=tot, y=labels[b], text=note, showarrow=False, xanchor="left",
                           xshift=8, font=dict(size=15, color=TEAL))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ---- right: Current Quarter ----
with right:
    st.markdown(f"<div style='background:{TEAL_D};color:#E6F6F2;text-align:center;font-weight:600;"
                f"padding:6px;border-radius:8px;text-transform:uppercase;'>Current Quarter</div>", unsafe_allow_html=True)
    a, b, cc = st.columns(3)
    with a: kpi("New Imp", m["cq_new"], "&nbsp;")
    with b: kpi("Launch Ready", m["cq_count"], "&nbsp;")
    with cc: kpi("Med Days to LR", num(m["cq_med"]), "&nbsp;")
    tw, pw = m["tw"], m["pw"]
    cols = [f"Week of {m['pw_start']:%-m/%-d}", f"Week of {m['tw_start']:%-m/%-d}"]
    grade = pd.DataFrame(
        {cols[0]: [pw["ab"], pw["c"], pw["total"]], cols[1]: [tw["ab"], tw["c"], tw["total"]]},
        index=["A & B", "C & No Grade", "Total"])
    st.table(grade)

st.markdown(f"<div style='background:{TEAL_D};color:#E6F6F2;font-weight:600;padding:6px 10px;"
            f"border-radius:8px;text-transform:uppercase;margin-top:6px;'>Key Changes Since Last Week</div>",
            unsafe_allow_html=True)
st.text_area("Key changes", value="", placeholder="Add narrative bullets here…",
             label_visibility="collapsed")
