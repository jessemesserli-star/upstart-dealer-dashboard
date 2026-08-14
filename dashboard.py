"""
Dealer Performance Dashboard — Streamlit v3
Matches the monthly dealer-facing PDF report layout exactly.
Two-column metrics, network rankings, week-by-week charts + table, portfolio health.
"""

import os, warnings, html as _html, urllib.parse
warnings.filterwarnings("ignore")

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials

# ── Sheet IDs ──────────────────────────────────────────────────────────────────
SHEET_UAF     = "14T0ZeqKTFWK3281C52Gu_YTIUfNl3TLZUIu7qVKrb7E"
SHEET_WOW     = "1b-k7e4DwWoHme10g9yZv1BKmYtckBHMVxfdPUuTMT58"
SHEET_HEALTH  = "1womVzH2W-RVdrc9z5diM9iJpmgGm0ZlmJt1t7pFaohU"
SHEET_CREDITS  = "1v8Oe5WB_3sGX58RW6rJC--fR6usmPyed0gP9TFzWspI"
SHEET_PASTDUE  = "1ZuN4H94EfggMz3lqlBaTo0t4BEQwAMQVxl3SH40JXSE"
# Unperfected-titles sheet — 3 tabs by aging bucket; "Rooftop Slug" col maps to dealer_id.
# NOTE: must be shared with the service account for this to load in the deployed dashboard.
SHEET_UNPERFECTED = "16M8FCQu-BwOwZMS8mYeJMBGJKwP8qYEYRa8NcibQQoQ"
SHEET_SF          = "1Fg-N2tkzuDUvYfnkRza6exFWR2N32gBwZOZTKv770lg"

# ── Colors ────────────────────────────────────────────────────────────────────
TEAL  = "#00B3A4"
DTEAL = "#0D7A74"
GREEN = "#388E3C"
RED   = "#D32F2F"
AMBER = "#F57C00"
_MH   = "420px"   # shared min-height for metric tile rows

# ── DRM contacts — update phone numbers here ───────────────────────────────────
DRM_CONTACTS = {
    "Jamal Elzein":      {"phone": "(313) 234-3251", "email": "jamal.elzein@upstart.com"},
    "Jessica Plaxton":   {"phone": "(919) 971-3141", "email": "jessica.plaxton@upstart.com"},
    "Joshua Lopez":      {"phone": "(407) 864-2210", "email": "joshua.lopez@upstart.com"},
    "Kusal Matthew":     {"phone": "(407) 259-9532", "email": "kusal.matthew@upstart.com"},
    "Melissa Alfaro":    {"phone": "(224) 535-0215", "email": "melissa.alfaro@upstart.com"},
    "Melissa Matyas":    {"phone": "(480) 375-1368", "email": "melissa.matyas@upstart.com"},
    "Miranda Pacheco":   {"phone": "(480) 531-0301", "email": "miranda.pacheco@upstart.com"},
    "Xavier Torres":     {"phone": "(973) 965-7303", "email": "xavier.torres@upstart.com"},
    "David Hammond":     {"phone": "(360) 888-6832", "email": "david.hammond@upstart.com"},
}

# ── Formatters ─────────────────────────────────────────────────────────────────
def _d(v):
    if v is None or (isinstance(v, float) and (v != v)): return "—"
    if abs(v) >= 1_000_000: return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:     return f"${v:,.0f}"
    return f"${v:.0f}"

def _p(v, dec=1):
    if v is None or (isinstance(v, float) and (v != v)): return "—"
    return f"{v*100:.{dec}f}%"

def _n(v, dec=0):
    if v is None or (isinstance(v, float) and (v != v)): return "—"
    if dec == 0: return str(int(round(v)))
    return f"{v:.{dec}f}"


# ── Auth ───────────────────────────────────────────────────────────────────────
def _gs_client():
    try:
        info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        creds_file = os.path.join(base, "DRM Reporting", "upstart-reporting-d62f862b99d3.json")
        creds = Credentials.from_service_account_file(
            creds_file, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return gspread.authorize(creds)


# ── Data loading ───────────────────────────────────────────────────────────────
_EPOCH = pd.Timestamp("1899-12-30")

def _date(v):
    try:
        n = float(str(v))
        return (_EPOCH + pd.Timedelta(days=int(n))) if n > 0 else pd.NaT
    except Exception:
        return pd.to_datetime(v, errors="coerce")


@st.cache_data(ttl=1800, show_spinner=False)
def load_all_data():
    gc = _gs_client()

    # ── Funnel ───────────────────────────────────────────────────────────────
    ws   = gc.open_by_key(SHEET_UAF).worksheet("funnel_dta")
    rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    funnel = pd.DataFrame(rows[1:], columns=rows[0])
    funnel["week"] = funnel["week"].apply(_date)
    NUM_COLS = [
        "FFS", "GR", "RIC", "FL", "Logins", "unique_users",
        "avg_fico_score_at_pricing", "avg_fico_score_at_orig",
        "avg_origination_principal", "avg_ltv_at_approval",
        "avg_apr_at_orig", "avg_buy_rate_at_orig",
        "total_reserve_at_orig", "avg_reserve_at_orig",
        "avg_be_at_orig", "total_be_at_orig", "avg_days_to_fund",
    ]
    for col in NUM_COLS:
        if col in funnel.columns:
            funnel[col] = pd.to_numeric(funnel[col], errors="coerce").fillna(0)
    funnel["dealer_id"] = funnel["dealer_id"].astype(str).str.strip()

    # ── Dealer / DSM map ─────────────────────────────────────────────────────
    rc_ws   = gc.open_by_key(SHEET_WOW).worksheet("Rate Checks")
    rc_rows = rc_ws.get_all_values()
    rc      = pd.DataFrame(rc_rows[1:], columns=rc_rows[0])
    name_map = dict(zip(rc["Chairman Account ID"].astype(str).str.strip(),
                        rc["Account Name"].astype(str)))
    dsm_map  = dict(zip(rc["Chairman Account ID"].astype(str).str.strip(),
                        rc["Account Owner"].astype(str)))

    # ── Portfolio health ─────────────────────────────────────────────────────
    try:
        h_ws   = gc.open_by_key(SHEET_HEALTH).worksheet("output_dealer_data")
        h_rows = h_ws.get_all_values()
        health = pd.DataFrame(h_rows[1:], columns=h_rows[0])
        for col in ["cumulative_loan_count", "cumulative_loans_in_FPD",
                    "cumulative_charge_off_cnt", "cumulative_loans_in_epd"]:
            if col in health.columns:
                health[col] = pd.to_numeric(health[col], errors="coerce").fillna(0)
        if "cumulative_originations" in health.columns:
            health["cumulative_originations"] = pd.to_numeric(
                health["cumulative_originations"].astype(str)
                    .str.replace("$", "", regex=False).str.replace(",", ""),
                errors="coerce").fillna(0)
        for col in ["pct_loans_in_FPD", "pct_loans_charged_off",
                    "pct_originations_31dpd_plus", "pct_originations_61dpd_plus"]:
            if col in health.columns:
                health[col] = pd.to_numeric(
                    health[col].astype(str).str.replace("%", "", regex=False).str.strip(),
                    errors="coerce").fillna(0) / 100.0
        health["dealer_id"] = health["dealer_id"].astype(str).str.strip()
    except Exception:
        health = pd.DataFrame()

    return funnel, name_map, dsm_map, health


# ── Metric computation ─────────────────────────────────────────────────────────
def _wavg(df, val_col, wt_col):
    if val_col not in df.columns or wt_col not in df.columns:
        return None
    sub = df[(df[wt_col] > 0) & (df[val_col] > 0)]
    if sub.empty:
        return None
    return (sub[val_col] * sub[wt_col]).sum() / sub[wt_col].sum()


@st.cache_data(ttl=1800, show_spinner=False)
def load_credit_apps():
    """Load individual deal-level credit applications from the Credits sheet."""
    try:
        gc = _gs_client()
        ws   = gc.open_by_key(SHEET_CREDITS).worksheet("Credit Apps Approved")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame()

        # Deduplicate column names (sheet has two "ID" and two "Finance Amount" cols)
        seen, headers = {}, []
        for h in rows[0]:
            if h in seen:
                seen[h] += 1
                headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                headers.append(h)

        df = pd.DataFrame(rows[1:], columns=headers)
        df.replace("", pd.NA, inplace=True)

        # Date
        if "Funding Form Submitted At Date" in df.columns:
            df["Funding Form Submitted At Date"] = pd.to_datetime(
                df["Funding Form Submitted At Date"], errors="coerce"
            )

        # Year is stored as "2,017" — strip comma before converting
        if "Year" in df.columns:
            df["Year"] = pd.to_numeric(
                df["Year"].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )

        # APR is stored as "8.9%" — strip percent sign; value is already a percentage (8.9)
        if "Finance Responses Apr" in df.columns:
            df["Finance Responses Apr"] = pd.to_numeric(
                df["Finance Responses Apr"].astype(str).str.replace("%", "", regex=False).str.strip(),
                errors="coerce",
            )

        # Plain numeric columns (no special formatting)
        for col in ["Fico At Pricing", "Finance Amount", "Finance Amount_1",
                    "Initial Ltv At Pricing", "Mileage", "Term"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "", regex=False),
                    errors="coerce",
                )

        # Currency columns (may have "$" and commas)
        for col in ["Vehicle Price", "Downpayment", "Net Trade Amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace("$", "", regex=False)
                                        .str.replace(",", "", regex=False).str.strip(),
                    errors="coerce",
                )

        # Dealer ID is the 3rd column (index 2) — slug like "auffenberg-volkswagen"
        dealer_id_col = df.columns[2]
        df[dealer_id_col] = df[dealer_id_col].astype(str).str.strip()

        # Deal UUID is the 4th column (index 3, deduplicated to "ID_1")
        uuid_col = df.columns[3]
        df[uuid_col] = df[uuid_col].astype(str).str.strip()

        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def load_pastdue_loans():
    """Load past-due (not yet charged off) loans from the past-due sheet."""
    try:
        gc   = _gs_client()
        ws   = gc.open_by_key(SHEET_PASTDUE).worksheet("Active loans missed payments")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame()

        # Use positional column mapping — header names in the sheet may vary
        df = pd.DataFrame(rows[1:], columns=[
            "chairman_id", "loan_id", "origination_date", "vin",
            "days_past_due", "payments_made", "payments_due",
            "first_payment_due_date", "earliest_unpaid_due_date",
        ] + [f"_extra_{i}" for i in range(max(0, len(rows[0]) - 9))])

        df["chairman_id"] = df["chairman_id"].astype(str).str.strip()
        df["loan_id"]     = df["loan_id"].astype(str).str.strip()

        for col in ("days_past_due", "payments_made", "payments_due"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        for col in ("origination_date", "first_payment_due_date", "earliest_unpaid_due_date"):
            df[col] = df[col].apply(_date)

        return df
    except Exception:
        return pd.DataFrame()


def get_pastdue_loans(pastdue_df, dealer_id):
    """Return past-due loans for a single dealer, sorted worst-first."""
    if pastdue_df.empty:
        return pd.DataFrame()
    df = pastdue_df[pastdue_df["chairman_id"] == str(dealer_id).strip()].copy()
    if df.empty:
        return pd.DataFrame()
    return df.sort_values(["payments_made", "days_past_due"], ascending=[True, False])


def _norm_slug(s):
    return str(s).strip().lower().replace("_", "-")


def _read_unperfected_raw_sa():
    """Read the 3 aging tabs via the service account. {bucket: rows} or {} on failure."""
    try:
        gc = _gs_client()
        sh = gc.open_by_key(SHEET_UNPERFECTED)
    except Exception:
        return {}
    want = {">44 days": ">44 Days", "30-44 days": "30-44 Days", "<30 days": "<30 Days"}
    ws_by_norm = {ws.title.strip().lower(): ws for ws in sh.worksheets()}
    out = {}
    for norm_title, bucket in want.items():
        ws = ws_by_norm.get(norm_title)
        if ws is None:
            continue
        try:
            out[bucket] = ws.get_all_values()
        except Exception:
            continue
    return out


def _read_unperfected_raw_oauth():
    """Local/dev fallback: read via the signed-in user's OAuth token (the 'drive'
    scope covers Sheets reads). Used only when the service account lacks access
    AND a token file is present — so it no-ops in the cloud. {bucket: rows} or {}."""
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "DRM Reporting", "drive_token.json")
    if not os.path.exists(token_path):
        return {}
    try:
        import json
        from google.oauth2.credentials import Credentials as OAuthCreds
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        with open(token_path) as f:
            d = json.load(f)
        creds = OAuthCreds(
            token=d["token"], refresh_token=d["refresh_token"],
            token_uri=d["token_uri"], client_id=d["client_id"],
            client_secret=d["client_secret"],
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        svc = build("sheets", "v4", credentials=creds)
        out = {}
        for tab in [">44 Days", "30-44 Days", "<30 Days"]:
            try:
                r = svc.spreadsheets().values().get(
                    spreadsheetId=SHEET_UNPERFECTED, range=f"'{tab}'").execute()
                out[tab] = r.get("values", [])
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _parse_unperfected(raw_by_bucket):
    """Turn {bucket: rows} into a normalized DataFrame keyed by rooftop slug."""
    frames = []
    for bucket, rows in raw_by_bucket.items():
        if not rows or len(rows) < 2:
            continue
        idx = {name: i for i, name in enumerate(rows[0])}

        def cell(r, name):
            i = idx.get(name)
            return r[i].strip() if (i is not None and i < len(r) and r[i] is not None) else ""

        recs = []
        for r in rows[1:]:
            slug = _norm_slug(cell(r, "Rooftop Slug"))
            if not slug:
                continue
            amt = cell(r, "Loan Amount").replace("$", "").replace(",", "")
            recs.append({
                "slug":     slug,
                "loan_id":  cell(r, "Loan ID"),
                "vin":      cell(r, "VIN"),
                "days":     pd.to_numeric(cell(r, "Days Unperfected"), errors="coerce"),
                "customer": cell(r, "Customer Account Name"),
                "orig":     cell(r, "Origination Date"),
                "amount":   pd.to_numeric(amt, errors="coerce"),
                "bucket":   bucket,
            })
        if recs:
            frames.append(pd.DataFrame(recs))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def load_unperfected_loans():
    """Load unperfected-title loans from all 3 aging tabs, keyed by rooftop slug.
    Tries the service account first; falls back to the local OAuth token when the
    service account can't reach the sheet. Empty DataFrame if neither works."""
    df = _parse_unperfected(_read_unperfected_raw_sa())
    if df.empty:
        df = _parse_unperfected(_read_unperfected_raw_oauth())
    return df


def get_unperfected_loans(unp_df, dealer_id):
    """Return unperfected-title loans for a single dealer, oldest-first."""
    if unp_df is None or unp_df.empty:
        return pd.DataFrame()
    df = unp_df[unp_df["slug"] == _norm_slug(dealer_id)].copy()
    if df.empty:
        return df
    return df.sort_values("days", ascending=False)


def render_unperfected_section(unp_df, dealer_id):
    """Render the Unperfected Titles block (3 aging-bucket metric chips + a
    deal list sorted oldest-first) inside the portfolio-health card."""
    st.markdown(f"<div style='color:{DTEAL};font-size:12px;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:.6px;margin-top:18px;margin-bottom:6px;'>"
                f"Unperfected Titles</div>", unsafe_allow_html=True)

    st.markdown(
        f"<div style='background:#fff8f0;border-left:3px solid {AMBER};padding:8px 12px;"
        f"font-size:12px;color:#7a4a00;margin-bottom:10px;border-radius:0 4px 4px 0;line-height:1.45;'>"
        f"<b>Unperfected titles over 45 days old are subject to buyback per Upstart's "
        f"Dealer Agreement.</b> Please ensure all titles are processed in a timely manner "
        f"to avoid buybacks or disruption to your Upstart Account.</div>",
        unsafe_allow_html=True,
    )

    # If the full dataset is empty, the source sheet is unreachable (not shared
    # with the service account) — show an explicit note rather than a false
    # "all clear", which would otherwise appear for every dealer.
    if unp_df is None or unp_df.empty:
        st.info("Unperfected-title data is currently unavailable — the source sheet "
                "is not shared with the dashboard's service account yet.")
        return

    u_df = get_unperfected_loans(unp_df, dealer_id)

    # (display_label, data bucket key, color, bg)
    BUCKETS = [
        (">44 Days",    ">44 Days",   RED,   "#fff5f5"),
        ("30–44 Days",  "30-44 Days", AMBER, "#fff8f0"),
        ("&lt;30 Days", "<30 Days",   TEAL,  "#e8f8f7"),
    ]
    cols = st.columns(3, gap="small")
    for (label, key, color, bg), col in zip(BUCKETS, cols):
        if u_df.empty:
            cnt, amt = 0, 0
        else:
            sub = u_df[u_df["bucket"] == key]
            cnt, amt = len(sub), sub["amount"].fillna(0).sum()
        with col:
            st.markdown(f"""
            <div style="background:{bg};border:2px solid {color};border-radius:8px;
                        padding:10px 14px;text-align:center;">
              <div style="font-size:10px;font-weight:700;color:{color};text-transform:uppercase;
                          letter-spacing:.5px;">{label}</div>
              <div style="font-size:24px;font-weight:800;color:{color};">{cnt}</div>
              <div style="font-size:11px;color:{color};">${amt:,.0f} at risk</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

    if u_df.empty:
        st.markdown(f"<div style='color:{GREEN};font-size:13px;font-weight:700;margin-bottom:8px;'>"
                    f"✓ No unperfected titles for this dealer.</div>", unsafe_allow_html=True)
        return

    BCOLOR = {">44 Days": RED, "30-44 Days": AMBER, "<30 Days": TEAL}

    def _fmt_amt(v):
        return f"${v:,.0f}" if pd.notna(v) else "—"

    rows_html, alt_i = "", 0
    for _, row in u_df.iterrows():
        bg = "#F5F7FA" if alt_i % 2 == 0 else "white"
        alt_i += 1
        dcol = BCOLOR.get(row["bucket"], "#111")
        days = "—" if pd.isna(row["days"]) else str(int(row["days"]))
        rows_html += (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:6px 10px;text-align:center;font-weight:700;color:{dcol};'>{days}</td>"
            f"<td style='padding:6px 10px;font-family:monospace;'>{_html.escape(str(row['loan_id']))}</td>"
            f"<td style='padding:6px 10px;font-family:monospace;'>{_html.escape(str(row['vin']))}</td>"
            f"<td style='padding:6px 10px;'>{_html.escape(str(row['customer']))}</td>"
            f"<td style='padding:6px 10px;'>{_html.escape(str(row['orig']))}</td>"
            f"<td style='padding:6px 10px;text-align:right;'>{_fmt_amt(row['amount'])}</td>"
            f"</tr>"
        )

    st.markdown(f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">
      <thead>
        <tr style="background:{TEAL};">
          <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">Days</th>
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Loan ID</th>
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">VIN</th>
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Customer</th>
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Orig. Date</th>
          <th style="padding:7px 10px;text-align:right;color:white;font-weight:600;">Loan Amount</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    """, unsafe_allow_html=True)


def get_opportunities(credit_df, dealer_id, start_dt, end_dt):
    """
    Return buy-box credit apps for the dealer in the date range.
    Buy box: FICO 620–740, APR <20%, vehicle 5–10 years old.
    """
    import datetime
    if credit_df.empty:
        return pd.DataFrame()

    cur_year   = datetime.date.today().year
    dealer_col = credit_df.columns[2]   # slug / Chairman Account ID
    uuid_col   = credit_df.columns[3]   # deal UUID
    date_col   = "Funding Form Submitted At Date"

    df = credit_df[credit_df[dealer_col] == str(dealer_id).strip()].copy()
    if df.empty:
        return pd.DataFrame()

    if date_col in df.columns:
        df = df[df[date_col].notna() &
                (df[date_col] >= start_dt) &
                (df[date_col] <= end_dt)]
    if df.empty:
        return pd.DataFrame()

    # Buy box: FICO 620–740, APR < 20% (stored as 8.9, not 0.089), age 5–10 yrs
    keep = pd.Series(True, index=df.index)
    if "Fico At Pricing" in df.columns:
        keep &= df["Fico At Pricing"].between(620, 740)
    if "Finance Responses Apr" in df.columns:
        keep &= df["Finance Responses Apr"] < 20        # already a percentage value
    if "Year" in df.columns:
        age = cur_year - df["Year"]
        keep &= age.between(5, 10)

    result = df[keep].sort_values(date_col, ascending=False).copy()
    if result.empty:
        return pd.DataFrame()

    rows_out = []
    for _, r in result.iterrows():
        dt = r.get(date_col)
        date_str = pd.Timestamp(dt).strftime("%-m/%-d") if pd.notna(dt) else "—"

        yr    = int(r["Year"])                            if pd.notna(r.get("Year"))            else ""
        make  = str(r.get("Make",  "") or "").strip()
        model = str(r.get("Model", "") or "").strip()
        vehicle = f"{yr} {make} {model}".strip()

        fico    = int(r["Fico At Pricing"])               if pd.notna(r.get("Fico At Pricing"))  else "—"
        apr_raw = r.get("Finance Responses Apr")
        apr_str = f"{apr_raw:.1f}%"                       if pd.notna(apr_raw)                   else "—"

        amt = r.get("Finance Amount")
        if pd.isna(amt):
            amt = r.get("Finance Amount_1")
        amount_str = f"${float(amt):,.0f}"                if pd.notna(amt)                       else "—"

        # "Deal Link" column contains display text "Deal Link", not the URL — build from UUID
        uuid = str(r.get(uuid_col, "") or "").strip()
        deal_link = f"https://autoretail.upstart.com/deals/financing/{uuid}" if uuid and uuid != "nan" else ""

        rows_out.append({
            "Date": date_str, "Vehicle": vehicle, "FICO": fico,
            "APR": apr_str, "Amount": amount_str, "_link": deal_link,
        })

    return pd.DataFrame(rows_out)


def period_metrics(funnel, dealer_id, weeks):
    df = funnel[(funnel["dealer_id"] == dealer_id) & (funnel["week"].isin(weeks))]
    if df.empty:
        return {k: None for k in [
            "logins","unique_users","ffs","gr","ric","fl","declined",
            "approval_rate","l2b","a2b","avg_fico","avg_fico_orig",
            "avg_principal","avg_ltv","avg_apr","avg_buy_rate",
            "avg_reserve","total_reserve","avg_be","avg_days_to_fund",
        ]}
    ffs = int(df["FFS"].sum())
    gr  = int(df["GR"].sum())
    ric = int(df["RIC"].sum())
    fl  = int(df["FL"].sum())

    total_reserve = float(df["total_reserve_at_orig"].sum()) if "total_reserve_at_orig" in df.columns else None
    total_be      = float(df["total_be_at_orig"].sum())      if "total_be_at_orig" in df.columns else None

    return {
        "logins":       int(df["Logins"].sum()),
        "unique_users": int(df["unique_users"].sum()) if "unique_users" in df.columns else 0,
        "ffs":   ffs, "gr": gr, "ric": ric, "fl": fl,
        "declined":      max(0, ffs - gr),
        "approval_rate": gr / ffs if ffs > 0 else None,
        "l2b":           fl / ffs if ffs > 0 else None,
        "a2b":           fl / gr  if gr  > 0 else None,
        "avg_fico":      _wavg(df, "avg_fico_score_at_pricing", "FFS"),
        "avg_fico_orig": _wavg(df, "avg_fico_score_at_orig",    "FL"),
        "avg_principal": _wavg(df, "avg_origination_principal", "FL"),
        "avg_ltv":       _wavg(df, "avg_ltv_at_approval",       "FL"),
        "avg_apr":       _wavg(df, "avg_apr_at_orig",            "FL"),
        "avg_buy_rate":  _wavg(df, "avg_buy_rate_at_orig",       "FL"),
        "avg_reserve":   total_reserve / fl if (total_reserve is not None and fl > 0) else None,
        "total_reserve": total_reserve,
        "avg_be":        total_be / fl if (total_be is not None and fl > 0) else None,
        "avg_days_to_fund": _wavg(df, "avg_days_to_fund", "FL"),
    }


def compute_network_stats(funnel, selected_weeks):
    df = funnel[funnel["week"].isin(selected_weeks)].copy()
    dealer_stats = {}
    for did in df["dealer_id"].unique():
        m = period_metrics(funnel, did, selected_weeks)
        if m["ffs"] and m["ffs"] > 0:
            dealer_stats[did] = m

    if not dealer_stats:
        return {}, {}

    vals = list(dealer_stats.values())

    def _mean(key):
        vs = [v[key] for v in vals if v.get(key) is not None]
        return sum(vs) / len(vs) if vs else None

    nav = {k: _mean(k) for k in [
        "logins","ffs","gr","ric","fl","declined",
        "approval_rate","l2b","a2b","avg_fico","avg_fico_orig",
        "avg_principal","avg_ltv","avg_apr","avg_buy_rate",
        "avg_reserve","total_reserve","avg_be","avg_days_to_fund",
    ]}
    nav["n_dealers"] = len(dealer_stats)
    return dealer_stats, nav


def percentile_rank(dealer_stats, metric_key, dealer_id, higher_is_better=True):
    vals = [s[metric_key] for s in dealer_stats.values() if s.get(metric_key) is not None]
    my_val = dealer_stats.get(dealer_id, {}).get(metric_key)
    if not vals or my_val is None:
        return None, None, None
    if higher_is_better:
        pct = sum(1 for v in vals if v < my_val) / len(vals) * 100
    else:
        pct = sum(1 for v in vals if v > my_val) / len(vals) * 100
    if pct >= 50:
        return pct, f"Top {max(1, round(100 - pct))}%", "top"
    return pct, f"Bottom {max(1, round(pct))}%", "bottom"


def weekly_breakdown(funnel, dealer_id, weeks):
    df = funnel[(funnel["dealer_id"] == dealer_id) & (funnel["week"].isin(weeks))].copy()
    df = df.sort_values("week")
    rows = []
    for _, r in df.iterrows():
        ffs = int(r["FFS"])
        gr  = int(r["GR"])
        fl  = int(r["FL"])
        rows.append({
            "week":      r["week"],
            "label":     pd.Timestamp(r["week"]).strftime("%-m/%-d"),
            "apps":      ffs,
            "approved":  gr,
            "appr_rate": f"{gr/ffs:.0%}" if ffs > 0 else "0%",
            "funded":    fl,
            "l2b":       f"{fl/ffs:.0%}" if ffs > 0 else "0%",
            "logins":    int(r.get("Logins", 0)),
        })
    return rows


def get_health(health_df, dealer_id):
    if health_df.empty:
        return None
    row = health_df[health_df["dealer_id"] == dealer_id]
    if row.empty:
        return None
    r = row.iloc[0]
    loan_count = int(r.get("cumulative_loan_count", 0) or 0)
    fpd_count  = int(r.get("cumulative_loans_in_FPD", 0) or 0)
    epd_count  = int(r.get("cumulative_loans_in_epd", 0) or 0)
    co_count   = int(r.get("cumulative_charge_off_cnt", 0) or 0)
    dpd31_pct  = float(r.get("pct_originations_31dpd_plus", 0) or 0)
    dpd61_pct  = float(r.get("pct_originations_61dpd_plus", 0) or 0)
    return {
        "loan_count":   loan_count,
        "originations": float(r.get("cumulative_originations", 0) or 0),
        "fpd_pct":      float(r.get("pct_loans_in_FPD", 0) or 0),
        "fpd_count":    fpd_count,
        "epd_pct":      epd_count / loan_count if loan_count > 0 else 0.0,
        "epd_count":    epd_count,
        "co_pct":       float(r.get("pct_loans_charged_off", 0) or 0),
        "co_count":     co_count,
        "dpd31_pct":    dpd31_pct,
        "dpd31_count":  round(dpd31_pct * loan_count),
        "dpd61_pct":    dpd61_pct,
        "dpd61_count":  round(dpd61_pct * loan_count),
    }


# ── Upstart-wide portfolio benchmarks ─────────────────────────────────────────
# Source: total Upstart Auto portfolio as of latest reporting period.
# FPD and CO are locked to the confirmed Upstart-wide totals.
# Update these when the portfolio-level numbers are refreshed.
UPSTART_FPD_BENCHMARK = 0.025    # 2.5%   First Payment Delinquency — confirmed Upstart-wide rate
UPSTART_EPD_BENCHMARK = 0.0026   # 0.26%  Early Payment Default — confirmed Upstart-wide rate
UPSTART_CO_BENCHMARK  = 0.0101   # 1.01%  ($6.1M charge-off / $605M originations)


def health_benchmark(health_df):
    """
    FPD and CO use confirmed Upstart-wide totals (not computed from the sheet,
    which only covers this team's dealers and would overstate both rates).
    31+/61+ DPD are computed as a weighted aggregate from the sheet since we
    don't have a confirmed portfolio-level figure for those.
    """
    bm = {
        "fpd_pct":  UPSTART_FPD_BENCHMARK,
        "epd_pct":  UPSTART_EPD_BENCHMARK,
        "co_pct":   UPSTART_CO_BENCHMARK,
        "dpd31_pct": None,
        "dpd61_pct": None,
    }
    if health_df.empty:
        return bm
    df = health_df[health_df["cumulative_loan_count"] >= 5].copy()
    total = df["cumulative_loan_count"].sum()
    if total > 0:
        if "cumulative_loans_in_epd" in df.columns:
            bm["epd_pct"] = df["cumulative_loans_in_epd"].sum() / total
        bm["dpd31_pct"] = (df["pct_originations_31dpd_plus"] * df["cumulative_loan_count"]).sum() / total
        bm["dpd61_pct"] = (df["pct_originations_61dpd_plus"] * df["cumulative_loan_count"]).sum() / total
    return bm


def generate_opportunity(p, nav, dealer_name):
    """Generate growth opportunity title + body matching PDF style."""
    ric_v  = p.get("ric") or 0
    l2b_v  = p.get("l2b")
    fico_v = p.get("avg_fico_orig")
    nav_l2b = nav.get("l2b")
    nav_ric = nav.get("ric")

    # Pick a title
    if l2b_v and nav_l2b and l2b_v >= nav_l2b * 0.9:
        title = "Good deal quality — opportunity to grow share of wallet"
    elif ric_v == 0:
        title = "No funded loans in this period — focus on application volume"
    elif l2b_v and nav_l2b and l2b_v < nav_l2b * 0.7:
        title = "Opportunity to improve deal conversion and grow funded loan volume"
    else:
        title = "Opportunity to increase Upstart submission volume"

    # Build body sentences
    body = []
    if l2b_v:
        l2b_str = f"{l2b_v:.1%}"
        body.append(f"Look-to-book of {l2b_str} is {'solid' if l2b_v >= (nav_l2b or 0)*0.9 else 'below the network average'}.")
    if fico_v and fico_v >= 640:
        body.append(f"Avg funded FICO of {round(fico_v)} is within Upstart's buy box, indicating strong deal quality.")
    if nav_ric and ric_v < nav_ric:
        gap = round(nav_ric - ric_v, 1)
        body.append(f"Increasing submissions from FICO 620+ customers could significantly grow funded loan volume toward the network average.")
    if not body:
        body.append("Contact your DRM to review strategies for growing Upstart volume at your dealership.")

    return title, " ".join(body[:2])


# ── Gmail send ────────────────────────────────────────────────────────────────
def send_report_email(to_addr, dealer_name, dsm_name, drm_email, period_str,
                      pdf_bytes, subject, body_text):
    import base64, json
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials as OAuthCreds
    from google.auth.transport.requests import Request

    # On Streamlit Cloud use secrets; locally fall back to the token file
    try:
        s = st.secrets["gmail_oauth"]
        creds = OAuthCreds(
            token=None,
            refresh_token=s["refresh_token"],
            token_uri=s.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=s["client_id"],
            client_secret=s["client_secret"],
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        creds.refresh(Request())
    except Exception:
        token_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "DRM Reporting", "drive_token.json"
        )
        with open(token_file) as f:
            data = json.load(f)
        creds = OAuthCreds(
            token=data["token"], refresh_token=data["refresh_token"],
            token_uri=data["token_uri"], client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=["https://www.googleapis.com/auth/gmail.send",
                    "https://www.googleapis.com/auth/drive"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data["token"] = creds.token
            with open(token_file, "w") as f:
                json.dump(data, f, indent=2)

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart()
    msg["To"]       = to_addr
    msg["From"]     = drm_email
    msg["Reply-To"] = drm_email
    msg["Cc"]       = drm_email
    msg["Subject"]  = subject
    msg.attach(MIMEText(body_text, "plain"))

    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header("Content-Disposition", "attachment",
                        filename=f"{dealer_name.replace(' ','_')}_Upstart_Report.pdf")
    msg.attach(pdf_part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ── HTML helpers ───────────────────────────────────────────────────────────────
def metric_table(section, rows):
    """rows: list of (label, your_result_str, network_avg_str)"""
    tr = ""
    for label, yr, na in rows:
        tr += f"""
      <tr>
        <td style="padding:5px 4px 5px 10px;color:#333;border-bottom:1px solid #f0f0f0;
                   font-size:12.5px;">{label}</td>
        <td style="padding:5px 4px;text-align:center;font-weight:700;color:#111;
                   border-bottom:1px solid #f0f0f0;font-size:12.5px;">{yr}</td>
        <td style="padding:5px 0 5px 4px;text-align:center;color:#777;
                   border-bottom:1px solid #f0f0f0;font-size:12.5px;">{na}</td>
      </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;table-layout:fixed;">
      <colgroup>
        <col style="width:58%">
        <col style="width:21%">
        <col style="width:21%">
      </colgroup>
      <tr>
        <th style="text-align:left;color:{TEAL};font-size:11px;font-weight:700;
                   text-transform:uppercase;letter-spacing:.6px;
                   padding:8px 4px 5px 10px;border-bottom:2px solid {TEAL};">{section}</th>
        <th style="text-align:center;color:#999;font-size:10px;font-weight:400;
                   padding:8px 4px 5px;border-bottom:2px solid {TEAL};">Your Results</th>
        <th style="text-align:center;color:#999;font-size:10px;font-weight:400;
                   padding:8px 0 5px 4px;border-bottom:2px solid {TEAL};">Network Avg</th>
      </tr>
      {tr}
    </table>"""


def rank_badge(label, pct_label, tier):
    if tier == "top":
        bg, border, color = "#e8f8f7", TEAL, DTEAL
    elif tier == "bottom":
        bg, border, color = "#fff8f0", AMBER, AMBER
    else:
        bg, border, color = "#f5f5f5", "#ccc", "#999"
    val = pct_label or "N/A"
    return f"""
    <div style="background:{bg};border:1px solid {border};border-radius:6px;
                padding:12px 10px;text-align:center;flex:1;margin:0 4px;">
      <div style="font-size:11px;font-weight:700;color:#555;text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:5px;">{label}</div>
      <div style="font-size:20px;font-weight:800;color:{color};">{val}</div>
      <div style="font-size:10px;color:#888;margin-top:2px;">of Upstart network</div>
    </div>"""


# ── PDF generation ────────────────────────────────────────────────────────────
def generate_dealer_pdf(dealer_name, dsm_name, drm_phone, drm_email, period_str,
                        p, nav, dh, bm, ric_rank, res_rank, be_rank,
                        opp_title, opp_body, wkly, n_weeks):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors as rc
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from io import BytesIO
    from datetime import datetime as _dt

    CT  = rc.HexColor("#00B3A4")
    CDT = rc.HexColor("#0D7A74")
    CG  = rc.HexColor("#388E3C")
    CR  = rc.HexColor("#D32F2F")
    CA  = rc.HexColor("#F57C00")
    CLG = rc.HexColor("#F5F7FA")
    CMG = rc.HexColor("#DDDDDD")
    CDG = rc.HexColor("#555555")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=.5*inch, rightMargin=.5*inch,
                            topMargin=.4*inch, bottomMargin=.45*inch)

    def ps(name, **kw):
        d = dict(fontName="Helvetica", fontSize=9, leading=12, textColor=rc.black)
        d.update(kw); return ParagraphStyle(name, **d)

    # Reusable header table
    def header_tbl():
        t = Table([[
            Paragraph("<font color='white'><b>UPSTART | AUTO RETAIL</b></font>",
                      ps("hL", fontSize=15, fontName="Helvetica-Bold")),
            Paragraph(f"<font color='white'>Dealer Performance Report<br/><b>{period_str}</b></font>",
                      ps("hR", fontSize=9, alignment=TA_RIGHT, leading=14)),
        ]], colWidths=[4.0*inch, 3.6*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), CT),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",(0,0), (-1,-1), 12),
            ("RIGHTPADDING",(0,0),(-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0),(-1,-1), 10),
        ]))
        return t

    def mt(section, rows, cw=None):
        """Build a metric comparison mini-table."""
        cw = cw or [1.95*inch, 0.72*inch, 0.72*inch]
        hdr = [
            Paragraph(f"<b>{section}</b>",
                      ps(f"s{section[:4]}", fontSize=8.5, fontName="Helvetica-Bold", textColor=CT)),
            Paragraph("<b>Your Results</b>",
                      ps("yr", fontSize=7, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
            Paragraph("<b>Network Avg</b>",
                      ps("na", fontSize=7, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
        ]
        data = [hdr]
        for i, (label, yr, na) in enumerate(rows):
            data.append([
                Paragraph(label, ps(f"l{i}", fontSize=8)),
                Paragraph(f"<b>{yr}</b>",
                          ps(f"r{i}", fontSize=8.5, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph(na, ps(f"n{i}", fontSize=8, textColor=CDG, alignment=TA_RIGHT)),
            ])
        tbl = Table(data, colWidths=cw)
        cmds = [
            ("LINEBELOW",   (0,0), (-1,0), 1.5, CT),
            ("TOPPADDING",  (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING",(0,0), (-1,-1), 3),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ]
        for i in range(1, len(data)):
            if i % 2 == 1:
                cmds.append(("BACKGROUND", (0,i), (-1,i), CLG))
            cmds.append(("LINEBELOW", (0,i), (-1,i), 0.3, CMG))
        tbl.setStyle(TableStyle(cmds))
        return tbl

    story = []

    # ── Page 1 ──────────────────────────────────────────────────────────────────
    story.append(header_tbl())
    story.append(Spacer(1, 6))

    story.append(Paragraph(f"<b>{dealer_name}</b>", ps("dn", fontSize=16, fontName="Helvetica-Bold")))
    cl = f"DSM: <b>{dsm_name}</b>"
    if drm_phone: cl += f"  ·  {drm_phone}"
    if drm_email: cl += f"  ·  {drm_email}"
    story.append(Paragraph(f"<font color='#555555'>{cl}</font>", ps("dsm")))
    story.append(Spacer(1, 8))

    # Network rankings
    story.append(Paragraph("UPSTART NETWORK RANKING",
                           ps("nrhdr", fontSize=7.5, fontName="Helvetica-Bold",
                              textColor=rc.HexColor("#888888"), spaceAfter=4)))

    def _rbg(tier):
        return CDT if tier == "top" else (CA if tier == "bottom" else CDG)

    rk = Table([[
        Paragraph(f"<font color='white'><b>Funded Loans</b></font><br/>"
                  f"<font color='white' size='11'><b>{ric_rank[1] or 'N/A'}</b></font>",
                  ps("rk1", alignment=TA_CENTER, leading=16)),
        Paragraph(f"<font color='white'><b>Total Reserve Earned</b></font><br/>"
                  f"<font color='white' size='11'><b>{res_rank[1] or 'N/A'}</b></font>",
                  ps("rk2", alignment=TA_CENTER, leading=16)),
        Paragraph(f"<font color='white'><b>Avg Back End</b></font><br/>"
                  f"<font color='white' size='11'><b>{be_rank[1] or 'N/A'}</b></font>",
                  ps("rk3", alignment=TA_CENTER, leading=16)),
    ]], colWidths=[2.47*inch]*3)
    rk.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), _rbg(ric_rank[2])),
        ("BACKGROUND",  (1,0), (1,-1), _rbg(res_rank[2])),
        ("BACKGROUND",  (2,0), (2,-1), _rbg(be_rank[2])),
        ("ALIGN",       (0,0), (-1,-1), "CENTER"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LINEAFTER",   (0,0), (1,-1), 0.5, rc.white),
    ]))
    story.append(rk)
    story.append(Spacer(1, 8))

    # Growth opportunity
    opp = Table([[
        Paragraph("<font color='white'><b>Growth\nOpportunity</b></font>",
                  ps("goL", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=14)),
        [Paragraph(f"<b>{opp_title}</b>", ps("goT", fontSize=9, fontName="Helvetica-Bold")),
         Spacer(1, 3),
         Paragraph(opp_body, ps("goB", fontSize=8.5, textColor=CDG))],
    ]], colWidths=[1.05*inch, 6.30*inch])
    opp.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), CT),
        ("BACKGROUND",  (1,0), (1,-1), rc.HexColor("#F0FAF9")),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING", (0,0), (0,-1), 6),
        ("RIGHTPADDING",(0,0), (0,-1), 6),
        ("LEFTPADDING", (1,0), (1,-1), 10),
        ("RIGHTPADDING",(1,0), (1,-1), 8),
        ("BOX",         (0,0), (-1,-1), 0.5, CMG),
    ]))
    story.append(opp)
    story.append(Spacer(1, 10))

    # Two-column metrics
    nav_dec = max(0, (nav.get("ffs") or 0) - (nav.get("gr") or 0))
    left_col = [
        mt("User Engagement", [
            ("Total Logins", _n(p["logins"]), "—"),
            ("Avg Weekly Unique Users", _n((p["unique_users"] or 0) / max(1, n_weeks), 1), "—"),
        ]),
        Spacer(1, 8),
        mt("Application Performance", [
            ("Apps Submitted", _n(p["ffs"]),         _n(nav.get("ffs"))),
            ("Approved",       _n(p["gr"]),           _n(nav.get("gr"))),
            ("Declined",       _n(p["declined"]),     _n(nav_dec)),
            ("Approval Rate",  _p(p["approval_rate"]),_p(nav.get("approval_rate"))),
            ("Avg FICO at App",_n(p["avg_fico"]),     _n(nav.get("avg_fico"))),
        ]),
    ]
    right_col = [
        mt("Funding Performance", [
            ("Funded Loans",    _n(p["ric"]),                   _n(nav.get("ric"))),
            ("Look to Book",    _p(p["l2b"]),                   _p(nav.get("l2b"))),
            ("Approve to Book", _p(p["a2b"]),                   _p(nav.get("a2b"))),
            ("Avg Days to Fund",_n(p["avg_days_to_fund"], 1),   _n(nav.get("avg_days_to_fund"), 1)),
        ]),
        Spacer(1, 8),
        mt("Deal Quality & Profitability", [
            ("Avg FICO (Funded)",      _n(p["avg_fico_orig"]), _n(nav.get("avg_fico_orig"))),
            ("Avg Amount Financed",    _d(p["avg_principal"]), _d(nav.get("avg_principal"))),
            ("Avg LTV",                _p(p["avg_ltv"]),       _p(nav.get("avg_ltv"))),
            ("Avg Contract Rate (APR)",_p(p["avg_apr"]),       _p(nav.get("avg_apr"))),
            ("Avg Buy Rate",           _p(p["avg_buy_rate"]),  _p(nav.get("avg_buy_rate"))),
            ("Avg Reserve",            _d(p["avg_reserve"]),   _d(nav.get("avg_reserve"))),
            ("Total Reserve Earned",   _d(p["total_reserve"]), _d(nav.get("total_reserve"))),
            ("Avg Back End",           _d(p["avg_be"]),        _d(nav.get("avg_be"))),
        ]),
    ]
    two = Table([[left_col, right_col]], colWidths=[3.7*inch, 3.7*inch])
    two.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (0,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ("LINEAFTER",    (0,0), (0,-1), 0.5, CMG),
    ]))
    story.append(two)

    # Week-by-week table
    if wkly:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Week-by-Week — {period_str}",
                               ps("wbw", fontSize=10, fontName="Helvetica-Bold",
                                  textColor=CDT, spaceAfter=4)))
        total_apps = sum(r["apps"] for r in wkly)
        total_appr = sum(r["approved"] for r in wkly)
        total_fund = sum(r["funded"] for r in wkly)
        wd = [["Week","Apps","Approved","Appr. Rate","Funded","L2B"]]
        for r in wkly:
            wd.append([r["label"], str(r["apps"]), str(r["approved"]),
                       r["appr_rate"], str(r["funded"]), r["l2b"]])
        wd.append(["Total", str(total_apps), str(total_appr),
                   f"{total_appr/total_apps:.0%}" if total_apps else "0%",
                   str(total_fund),
                   f"{total_fund/total_apps:.0%}" if total_apps else "0%"])
        wt = Table(wd, colWidths=[.8*inch,.9*inch,.9*inch,1.0*inch,.9*inch,.8*inch])
        wt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), CT),
            ("TEXTCOLOR",     (0,0), (-1,0), rc.white),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND",    (0,-1),(-1,-1), CT),
            ("TEXTCOLOR",     (0,-1),(-1,-1), rc.white),
            ("FONTNAME",      (0,-1),(-1,-1), "Helvetica-Bold"),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("FONTSIZE",      (0,0), (-1,-1), 8.5),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("GRID",          (0,0), (-1,-1), 0.3, CMG),
            ("ROWBACKGROUNDS",(0,1), (-1,-2), [CLG, rc.white]),
        ]))
        story.append(wt)

    # ── Page 2: Portfolio Health ─────────────────────────────────────────────────
    if dh is not None:
        story.append(PageBreak())
        story.append(header_tbl())
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>{dealer_name}</b>",
                               ps("ph_dn", fontSize=16, fontName="Helvetica-Bold")))
        story.append(Paragraph("Portfolio Health — Since Launch on Upstart",
                               ps("ph_sub", fontSize=10, fontName="Helvetica-Bold",
                                  textColor=CDT, spaceAfter=4)))
        story.append(Paragraph(
            "Cumulative performance of all loans funded through Upstart since launch. "
            "Network benchmark is a weighted average across dealers with 5+ funded loans.",
            ps("ph_d", fontSize=8.5, textColor=CDG, spaceAfter=8)
        ))

        def phc(val, bench):
            if not bench: return rc.black
            r = val / bench
            return CG if r <= 1.0 else (CA if r <= 1.5 else CR)

        ph_secs = [
            ("Portfolio Volume", [
                ("Total Funded Loans (cumulative)", f"{dh['loan_count']:,}", "—", rc.black),
                ("Total Originations (cumulative)",  _d(dh['originations']),  "—", rc.black),
            ]),
            ("Loan Performance", [
                ("First Payment Delinquency", _p(dh['fpd_pct'],2),
                 _p(bm.get('fpd_pct'),2), phc(dh['fpd_pct'], bm.get('fpd_pct'))),
                ("Early Payment Default", _p(dh['epd_pct'],2),
                 _p(bm.get('epd_pct'),2), phc(dh['epd_pct'], bm.get('epd_pct'))),
                ("Charge-off Rate", _p(dh['co_pct'],2),
                 _p(bm.get('co_pct'),2), phc(dh['co_pct'], bm.get('co_pct'))),
            ]),
            ("Delinquency", [
                ("31+ Days Past Due Rate", _p(dh['dpd31_pct'],1),
                 _p(bm.get('dpd31_pct'),1), phc(dh['dpd31_pct'], bm.get('dpd31_pct'))),
                ("61+ Days Past Due Rate", _p(dh['dpd61_pct'],1),
                 _p(bm.get('dpd61_pct'),1), phc(dh['dpd61_pct'], bm.get('dpd61_pct'))),
            ]),
        ]
        for sec_name, sec_rows in ph_secs:
            sd = [[
                Paragraph(f"<b>{sec_name}</b>",
                          ps(f"phs{sec_name[:3]}", fontSize=8.5, fontName="Helvetica-Bold", textColor=CT)),
                Paragraph("<b>Your Portfolio</b>",
                          ps("phyp", fontSize=7.5, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
                Paragraph("<b>Network Avg</b>",
                          ps("phna", fontSize=7.5, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
            ]] + [
                [Paragraph(label, ps(f"phl{i}", fontSize=8.5)),
                 Paragraph(f"<b>{yr}</b>", ps(f"phv{i}", fontSize=9, fontName="Helvetica-Bold",
                                               textColor=color, alignment=TA_RIGHT)),
                 Paragraph(na, ps(f"phn{i}", fontSize=8.5, textColor=CDG, alignment=TA_RIGHT))]
                for i, (label, yr, na, color) in enumerate(sec_rows)
            ]
            st_tbl = Table(sd, colWidths=[4.6*inch, 1.0*inch, 1.1*inch])
            st_tbl.setStyle(TableStyle([
                ("LINEBELOW",    (0,0), (-1,0), 1.5, CT),
                ("TOPPADDING",   (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
                ("LEFTPADDING",  (0,0), (-1,-1), 3),
                ("RIGHTPADDING", (0,0), (-1,-1), 3),
                ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
                ("ROWBACKGROUNDS",(0,1),(-1,-1), [CLG, rc.white]),
                ("LINEBELOW",    (0,1), (-1,-1), 0.3, CMG),
            ]))
            story.append(st_tbl)
            story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Generated {_dt.now().strftime('%B %d, %Y')}  ·  Confidential — For dealer use only  ·  Upstart Auto Retail",
        ps("foot", fontSize=7.5, textColor=rc.HexColor("#AAAAAA"), alignment=TA_CENTER)
    ))
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ── Group PDF generation ──────────────────────────────────────────────────────
def generate_group_pdf(group_name, g_dsm, period_str, gp, g_bench, g_rank,
                       total_grps, ins_sub, ins_body, g_wkly, g_bkdn):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors as rc
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from io import BytesIO
    from datetime import datetime as _dt

    CT  = rc.HexColor("#00B3A4")
    CDT = rc.HexColor("#0D7A74")
    CLG = rc.HexColor("#F5F7FA")
    CMG = rc.HexColor("#DDDDDD")
    CDG = rc.HexColor("#555555")
    CA  = rc.HexColor("#F57C00")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=.5*inch, rightMargin=.5*inch,
                            topMargin=.4*inch, bottomMargin=.45*inch)

    def ps(name, **kw):
        d = dict(fontName="Helvetica", fontSize=9, leading=12, textColor=rc.black)
        d.update(kw); return ParagraphStyle(name, **d)

    def header_tbl():
        t = Table([[
            Paragraph("<font color='white'><b>UPSTART | AUTO RETAIL</b></font>",
                      ps("hL", fontSize=15, fontName="Helvetica-Bold")),
            Paragraph(f"<font color='white'>Group Performance Report<br/><b>{period_str}</b></font>",
                      ps("hR", fontSize=9, alignment=TA_RIGHT, leading=14)),
        ]], colWidths=[4.0*inch, 3.6*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,-1), CT),
            ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",  (0,0), (-1,-1), 12),
            ("RIGHTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING",   (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ]))
        return t

    def mt(section, rows, bench_hdr="Group Median"):
        cw = [1.95*inch, 0.72*inch, 0.72*inch]
        hdr = [
            Paragraph(f"<b>{section}</b>",
                      ps(f"s{section[:4]}", fontSize=8.5, fontName="Helvetica-Bold", textColor=CT)),
            Paragraph("<b>This Group</b>",
                      ps("yr", fontSize=7, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
            Paragraph(f"<b>{bench_hdr}</b>",
                      ps("na", fontSize=7, textColor=rc.HexColor("#999999"), alignment=TA_RIGHT)),
        ]
        data = [hdr]
        for i, (label, yr, na) in enumerate(rows):
            data.append([
                Paragraph(label, ps(f"l{i}", fontSize=8)),
                Paragraph(f"<b>{yr}</b>",
                          ps(f"r{i}", fontSize=8.5, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph(na, ps(f"n{i}", fontSize=8, textColor=CDG, alignment=TA_RIGHT)),
            ])
        tbl = Table(data, colWidths=cw)
        cmds = [
            ("LINEBELOW",    (0,0), (-1,0), 1.5, CT),
            ("TOPPADDING",   (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0), (-1,-1), 3),
            ("LEFTPADDING",  (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 3),
            ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ]
        for i in range(1, len(data)):
            if i % 2 == 1:
                cmds.append(("BACKGROUND", (0,i), (-1,i), CLG))
            cmds.append(("LINEBELOW", (0,i), (-1,i), 0.3, CMG))
        tbl.setStyle(TableStyle(cmds))
        return tbl

    story = []

    # ── Page 1 ──────────────────────────────────────────────────────────────────
    story.append(header_tbl())
    story.append(Spacer(1, 6))

    story.append(Paragraph(f"<b>{group_name}</b>", ps("gn", fontSize=16, fontName="Helvetica-Bold")))
    story.append(Paragraph(
        f"<font color='#555555'>{len(g_bkdn)} dealer location{'s' if len(g_bkdn) != 1 else ''}</font>",
        ps("dsm")
    ))
    story.append(Spacer(1, 8))

    # Rankings
    story.append(Paragraph("GROUP NETWORK RANKING",
                           ps("nrhdr", fontSize=7.5, fontName="Helvetica-Bold",
                              textColor=rc.HexColor("#888888"), spaceAfter=4)))

    def _rank_lbl(rank_key):
        rank = g_rank.get(rank_key)
        if rank is None or total_grps < 2:
            return "N/A"
        pct = (1 - rank / total_grps) * 100
        return f"Top {max(1, round(100 - pct))}%" if pct >= 50 else f"Bottom {max(1, round(pct))}%"

    def _rbg(rank_key):
        rank = g_rank.get(rank_key)
        if rank is None or total_grps < 2:
            return CDG
        pct = (1 - rank / total_grps) * 100
        return CDT if pct >= 50 else CA

    rk = Table([[
        Paragraph(f"<font color='white'><b>Funded Loans</b></font><br/>"
                  f"<font color='white' size='11'><b>{_rank_lbl('fl_rank')}</b></font>",
                  ps("rk1", alignment=TA_CENTER, leading=16)),
        Paragraph(f"<font color='white'><b>Total Reserve Earned</b></font><br/>"
                  f"<font color='white' size='11'><b>{_rank_lbl('reserve_rank')}</b></font>",
                  ps("rk2", alignment=TA_CENTER, leading=16)),
        Paragraph(f"<font color='white'><b>Avg Back End</b></font><br/>"
                  f"<font color='white' size='11'><b>{_rank_lbl('be_rank')}</b></font>",
                  ps("rk3", alignment=TA_CENTER, leading=16)),
    ]], colWidths=[2.47*inch]*3)
    rk.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), _rbg("fl_rank")),
        ("BACKGROUND",  (1,0), (1,-1), _rbg("reserve_rank")),
        ("BACKGROUND",  (2,0), (2,-1), _rbg("be_rank")),
        ("ALIGN",       (0,0), (-1,-1), "CENTER"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LINEAFTER",   (0,0), (1,-1), 0.5, rc.white),
    ]))
    story.append(rk)
    story.append(Spacer(1, 8))

    # Group insight
    opp = Table([[
        Paragraph("<font color='white'><b>Group\nInsight</b></font>",
                  ps("goL", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=14)),
        [Paragraph(f"<b>{ins_sub}</b>", ps("goT", fontSize=9, fontName="Helvetica-Bold")),
         Spacer(1, 3),
         Paragraph(ins_body, ps("goB", fontSize=8.5, textColor=CDG))],
    ]], colWidths=[1.05*inch, 6.30*inch])
    opp.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (0,-1), CT),
        ("BACKGROUND",  (1,0), (1,-1), rc.HexColor("#F0FAF9")),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING", (0,0), (0,-1), 6),
        ("RIGHTPADDING",(0,0), (0,-1), 6),
        ("LEFTPADDING", (1,0), (1,-1), 10),
        ("RIGHTPADDING",(1,0), (1,-1), 8),
        ("BOX",         (0,0), (-1,-1), 0.5, CMG),
    ]))
    story.append(opp)
    story.append(Spacer(1, 10))

    # Two-column metrics
    nav_dec_g = max(0, (g_bench.get("ffs") or 0) - (g_bench.get("gr") or 0))
    left_col = [
        mt("User Engagement", [
            ("Total Logins", _n(gp["logins"]), "—"),
            ("Avg Weekly Unique Users",
             _n((gp.get("avg_users") or 0), 1) if gp.get("avg_users") else "—", "—"),
        ]),
        Spacer(1, 8),
        mt("Application Performance", [
            ("Apps Submitted", _n(gp["ffs"]),         _n(g_bench.get("ffs"))),
            ("Approved",       _n(gp["gr"]),           _n(g_bench.get("gr"))),
            ("Declined",       _n(gp["declined"]),     _n(nav_dec_g)),
            ("Approval Rate",  _p(gp["approval_rate"]),_p(g_bench.get("approval_rate"))),
            ("Avg FICO at App",_n(gp["avg_fico"]),     _n(g_bench.get("avg_fico"))),
        ]),
    ]
    right_col = [
        mt("Funding Performance", [
            ("Funded Loans",    _n(gp["fl"]),                        _n(g_bench.get("fl"))),
            ("Look to Book",    _p(gp["l2b"]),                       _p(g_bench.get("l2b"))),
            ("Approve to Book", _p(gp["a2b"]),                       _p(g_bench.get("a2b"))),
            ("Avg Days to Fund",_n(gp["avg_days_to_fund"], 1),       _n(g_bench.get("avg_days_to_fund"), 1)),
        ]),
        Spacer(1, 8),
        mt("Deal Quality & Profitability", [
            ("Avg FICO (Funded)",       _n(gp["avg_fico_orig"]), _n(g_bench.get("avg_fico_orig"))),
            ("Avg Amount Financed",     _d(gp["avg_principal"]), _d(g_bench.get("avg_principal"))),
            ("Avg LTV",                 _p(gp["avg_ltv"]),       _p(g_bench.get("avg_ltv"))),
            ("Avg Contract Rate (APR)", _p(gp["avg_apr"]),       _p(g_bench.get("avg_apr"))),
            ("Avg Buy Rate",            _p(gp["avg_buy_rate"]),  _p(g_bench.get("avg_buy_rate"))),
            ("Avg Reserve",             _d(gp["avg_reserve"]),   _d(g_bench.get("avg_reserve"))),
            ("Total Reserve Earned",    _d(gp["total_reserve"]), _d(g_bench.get("total_reserve"))),
            ("Avg Back End",            _d(gp["avg_be"]),        _d(g_bench.get("avg_be"))),
        ]),
    ]
    two = Table([[left_col, right_col]], colWidths=[3.7*inch, 3.7*inch])
    two.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (0,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ("LINEAFTER",    (0,0), (0,-1), 0.5, CMG),
    ]))
    story.append(two)

    # Weekly table
    if g_wkly:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Week-by-Week — {period_str}",
                               ps("wbw", fontSize=10, fontName="Helvetica-Bold",
                                  textColor=CDT, spaceAfter=4)))
        total_apps = sum(r["apps"] for r in g_wkly)
        total_appr = sum(r["approved"] for r in g_wkly)
        total_fund = sum(r["funded"] for r in g_wkly)
        wd = [["Week", "Apps", "Approved", "Appr. Rate", "Funded", "L2B"]]
        for r in g_wkly:
            wd.append([r["label"], str(r["apps"]), str(r["approved"]),
                       r["appr_rate"], str(r["funded"]), r["l2b"]])
        wd.append(["Total", str(total_apps), str(total_appr),
                   f"{total_appr/total_apps:.0%}" if total_apps else "0%",
                   str(total_fund),
                   f"{total_fund/total_apps:.0%}" if total_apps else "0%"])
        wt = Table(wd, colWidths=[.8*inch, .9*inch, .9*inch, 1.0*inch, .9*inch, .8*inch])
        wt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),  (-1,0),  CT),
            ("TEXTCOLOR",     (0,0),  (-1,0),  rc.white),
            ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
            ("BACKGROUND",    (0,-1), (-1,-1), CT),
            ("TEXTCOLOR",     (0,-1), (-1,-1), rc.white),
            ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
            ("ALIGN",         (0,0),  (-1,-1), "CENTER"),
            ("FONTSIZE",      (0,0),  (-1,-1), 8.5),
            ("TOPPADDING",    (0,0),  (-1,-1), 4),
            ("BOTTOMPADDING", (0,0),  (-1,-1), 4),
            ("GRID",          (0,0),  (-1,-1), 0.3, CMG),
            ("ROWBACKGROUNDS",(0,1),  (-1,-2), [CLG, rc.white]),
        ]))
        story.append(wt)

    # ── Page 2: Dealer Breakdown ─────────────────────────────────────────────────
    active_bkdn = [(n, s) for n, s in g_bkdn if s is not None]
    if active_bkdn:
        story.append(PageBreak())
        story.append(header_tbl())
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>{group_name}</b>",
                               ps("gn2", fontSize=16, fontName="Helvetica-Bold")))
        story.append(Paragraph("Dealer Breakdown",
                               ps("bkdn_sub", fontSize=10, fontName="Helvetica-Bold",
                                  textColor=CDT, spaceAfter=6)))

        hdr_row = [
            Paragraph("<b>Dealer</b>",         ps("bh0", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white)),
            Paragraph("<b>Logins</b>",          ps("bh1", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>Apps</b>",            ps("bh2", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>Approved</b>",        ps("bh3", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>Appr. Rate</b>",      ps("bh4", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>Funded</b>",          ps("bh5", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>L2B</b>",             ps("bh6", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_CENTER)),
            Paragraph("<b>Total Reserve</b>",   ps("bh7", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_RIGHT)),
            Paragraph("<b>Avg Back End</b>",    ps("bh8", fontSize=8, fontName="Helvetica-Bold", textColor=rc.white, alignment=TA_RIGHT)),
        ]
        bkdn_data = [hdr_row]
        for dname, ds in active_bkdn:
            bkdn_data.append([
                Paragraph(dname, ps(f"bd{dname[:4]}", fontSize=8)),
                Paragraph(_n(ds["logins"]),       ps("bc1", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_n(ds["ffs"]),           ps("bc2", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_n(ds["gr"]),            ps("bc3", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_p(ds["approval_rate"]), ps("bc4", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_n(ds["ric"]),           ps("bc5", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_p(ds["l2b"]),           ps("bc6", fontSize=8, alignment=TA_CENTER)),
                Paragraph(_d(ds["total_reserve"]), ps("bc7", fontSize=8, alignment=TA_RIGHT)),
                Paragraph(_d(ds["avg_be"]),        ps("bc8", fontSize=8, alignment=TA_RIGHT)),
            ])
        bkdn_tbl = Table(bkdn_data,
                         colWidths=[2.0*inch, .55*inch, .55*inch, .65*inch, .65*inch, .55*inch, .55*inch, .85*inch, .85*inch])
        bkdn_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),  (-1,0),  CT),
            ("TEXTCOLOR",     (0,0),  (-1,0),  rc.white),
            ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
            ("ALIGN",         (1,0),  (-1,-1), "CENTER"),
            ("ALIGN",         (7,0),  (-1,-1), "RIGHT"),
            ("FONTSIZE",      (0,0),  (-1,-1), 8),
            ("TOPPADDING",    (0,0),  (-1,-1), 4),
            ("BOTTOMPADDING", (0,0),  (-1,-1), 4),
            ("LEFTPADDING",   (0,0),  (-1,-1), 4),
            ("RIGHTPADDING",  (0,0),  (-1,-1), 4),
            ("GRID",          (0,0),  (-1,-1), 0.3, CMG),
            ("ROWBACKGROUNDS",(0,1),  (-1,-1), [CLG, rc.white]),
        ]))
        story.append(bkdn_tbl)

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Generated {_dt.now().strftime('%B %d, %Y')}  ·  Confidential — For internal use only  ·  Upstart Auto Retail",
        ps("foot", fontSize=7.5, textColor=rc.HexColor("#AAAAAA"), alignment=TA_CENTER)
    ))
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ── Metric box helpers ────────────────────────────────────────────────────────
TIER_M = {
    "good":    {"bg":"#e8f8f7", "border":TEAL,  "hdr":DTEAL, "label":"✓ Above Network Average"},
    "warn":    {"bg":"#fff8e1", "border":AMBER,  "hdr":AMBER, "label":"⚠ Near Network Average"},
    "bad":     {"bg":"#fff5f5", "border":RED,    "hdr":RED,   "label":"● Below Network Average"},
    "neutral": {"bg":"#f0faf9", "border":TEAL,   "hdr":DTEAL, "label":""},
}

def _mbox_tier(val, nav_val, higher_better=True):
    if val is None or nav_val is None or nav_val == 0: return "neutral"
    ratio = val / nav_val
    if higher_better:
        return "good" if ratio >= 0.9 else ("warn" if ratio >= 0.75 else "bad")
    else:
        return "good" if ratio <= 1.1 else ("warn" if ratio <= 1.25 else "bad")

def _mbox(section, tier, rows, min_height=None, bench_label="Network Avg"):
    """rows: list of (label, your_val, net_val)"""
    s  = TIER_M[tier]
    mh = f"min-height:{min_height};" if min_height else ""
    status = (f"<div style='font-size:10.5px;font-weight:600;color:{s['hdr']};margin-top:2px;"
              f"margin-bottom:8px;'>{s['label']}</div>") if s["label"] else "<div style='margin-bottom:8px;'></div>"
    sub = (f"<div style='display:flex;padding:2px 0 4px;border-bottom:1px solid rgba(0,0,0,.1);'>"
           f"<span style='flex:1;font-size:9.5px;color:#888;'></span>"
           f"<span style='width:82px;text-align:center;font-size:9.5px;color:#888;'>Your Results</span>"
           f"<span style='width:82px;text-align:center;font-size:9.5px;color:#888;'>{bench_label}</span>"
           f"</div>")
    rows_html = ""
    for label, yv, nv in rows:
        rows_html += (
            f"<div style='display:flex;align-items:center;padding:6px 0;"
            f"border-bottom:1px solid rgba(0,0,0,.06);'>"
            f"<span style='flex:1;font-size:12px;color:#444;'>{label}</span>"
            f"<span style='width:82px;text-align:center;font-size:13px;"
            f"font-weight:700;color:{s['hdr']};'>{yv}</span>"
            f"<span style='width:82px;text-align:center;font-size:12px;color:#777;'>{nv}</span>"
            f"</div>"
        )
    return (f"<div style='background:{s['bg']};border:2px solid {s['border']};"
            f"border-radius:10px;padding:14px 16px;{mh}'>"
            f"<div style='color:{s['hdr']};font-size:11px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.6px;'>{section}</div>"
            f"{status}{sub}{rows_html}</div>")


# ── Group data ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def load_sf_data():
    """Load Salesforce account sheet to build the dealer → group map."""
    try:
        gc = _gs_client()
        ws = gc.open_by_key(SHEET_SF).worksheet("Live Accounts")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame()
        return pd.DataFrame(rows[1:], columns=rows[0])
    except Exception:
        return pd.DataFrame()


def build_group_map(sf_df):
    """Return {group_name: {dealer_ids, dealer_names, dsm_counts, states}}."""
    groups = {}
    for _, row in sf_df.iterrows():
        parent = str(row.get("Parent Account", "")).strip()
        did    = str(row.get("Chairman Account ID", "")).strip()
        name   = str(row.get("Account Name", "")).strip()
        dsm    = str(row.get("Account Owner", "")).strip()
        state  = str(row.get("Billing State/Province", "")).strip()
        if not parent or not did:
            continue
        if parent not in groups:
            groups[parent] = {"dealer_ids": [], "dealer_names": {}, "dsm_counts": {}, "states": set()}
        groups[parent]["dealer_ids"].append(did)
        groups[parent]["dealer_names"][did] = name
        groups[parent]["dsm_counts"][dsm] = groups[parent]["dsm_counts"].get(dsm, 0) + 1
        if state:
            groups[parent]["states"].add(state)
    return groups


def group_period_metrics(funnel, dealer_ids, sel_weeks):
    """Aggregate funnel stats for a set of dealer IDs over the selected weeks."""
    df = funnel[funnel["dealer_id"].isin(dealer_ids) & funnel["week"].isin(sel_weeks)]
    if df.empty:
        return None
    ffs = int(df["FFS"].sum())
    gr  = int(df["GR"].sum())
    fl  = int(df["FL"].sum())
    total_reserve = float(df["total_reserve_at_orig"].sum()) if "total_reserve_at_orig" in df.columns else None
    total_be      = float(df["total_be_at_orig"].sum())      if "total_be_at_orig"      in df.columns else None
    return {
        "ffs": ffs, "gr": gr, "fl": fl,
        "declined":      max(0, ffs - gr),
        "approval_rate": gr / ffs if ffs > 0 else None,
        "l2b":           fl / ffs if ffs > 0 else None,
        "a2b":           fl / gr  if gr  > 0 else None,
        "logins":        int(df["Logins"].sum()),
        "avg_users":     df.groupby("week")["unique_users"].sum().mean() if "unique_users" in df.columns else None,
        "avg_fico":      _wavg(df, "avg_fico_score_at_pricing", "FFS"),
        "avg_fico_orig": _wavg(df, "avg_fico_score_at_orig",    "FL"),
        "avg_principal": _wavg(df, "avg_origination_principal", "FL"),
        "avg_ltv":       _wavg(df, "avg_ltv_at_approval",       "FL"),
        "avg_apr":       _wavg(df, "avg_apr_at_orig",           "FL"),
        "avg_buy_rate":  _wavg(df, "avg_buy_rate_at_orig",      "FL"),
        "avg_reserve":   total_reserve / fl if (total_reserve is not None and fl > 0) else None,
        "total_reserve": total_reserve,
        "avg_be":        total_be / fl if (total_be is not None and fl > 0) else None,
        "avg_days_to_fund": _wavg(df, "avg_days_to_fund", "FL"),
    }


def group_weekly_trend(funnel, dealer_ids, sel_weeks):
    """Weekly rows for the group trend chart/table."""
    df = funnel[funnel["dealer_id"].isin(dealer_ids) & funnel["week"].isin(sel_weeks)].copy()
    rows = []
    for wk, grp in sorted(df.groupby("week"), key=lambda x: x[0]):
        ffs    = int(grp["FFS"].sum())
        gr     = int(grp["GR"].sum())
        fl     = int(grp["FL"].sum())
        logins = int(grp["Logins"].sum())
        rows.append({
            "label":     pd.Timestamp(wk).strftime("%-m/%-d"),
            "apps":      ffs,
            "approved":  gr,
            "appr_rate": f"{gr/ffs:.0%}" if ffs > 0 else "0%",
            "funded":    fl,
            "l2b":       f"{fl/ffs:.0%}" if ffs > 0 else "0%",
            "logins":    logins,
        })
    return rows


def group_dealer_breakdown(funnel, dealer_ids, dealer_names, sel_weeks):
    """Per-dealer stats within the group, sorted by FL desc."""
    result = []
    for did in dealer_ids:
        name = dealer_names.get(did, did.replace("-", " ").title())
        m = period_metrics(funnel, did, sel_weeks)
        if m is None or not m.get("ffs"):
            result.append((name, None))
            continue
        result.append((name, m))
    active   = sorted([(n, s) for n, s in result if s], key=lambda x: x[1]["fl"], reverse=True)
    inactive = [(n, s) for n, s in result if not s]
    return active + inactive


def compute_all_groups(funnel, group_map, sel_weeks):
    """Stats dict for every group that had activity in the period."""
    result = {}
    for gname, ginfo in group_map.items():
        s = group_period_metrics(funnel, ginfo["dealer_ids"], sel_weeks)
        if s and s["ffs"] > 0:
            result[gname] = s
    return result


def compute_group_benchmarks_dash(all_group_stats):
    """Median across active groups for each metric."""
    rows = list(all_group_stats.values())
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    result = {}
    for col in df.columns:
        vals = df[col].dropna()
        result[col] = float(vals.median()) if len(vals) > 0 else 0
    return result


def compute_group_rankings_dash(all_group_stats):
    """FL / reserve / avg_be rankings across groups."""
    rows = [
        {"group": g, "fl": s["fl"], "reserve": s.get("total_reserve") or 0, "avg_be": s.get("avg_be") or 0}
        for g, s in all_group_stats.items()
    ]
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    total = len(df)
    df["fl_rank"]      = df["fl"].rank(ascending=False,      method="min").astype(int)
    df["reserve_rank"] = df["reserve"].rank(ascending=False, method="min").astype(int)
    df["be_rank"]      = df["avg_be"].rank(ascending=False,  method="min").astype(int)
    result = {}
    for _, row in df.iterrows():
        result[row["group"]] = {
            "fl_rank":      int(row["fl_rank"]),
            "reserve_rank": int(row["reserve_rank"]),
            "be_rank":      int(row["be_rank"]),
            "total":        total,
        }
    return result


def group_performance_insight(stats, benchmarks):
    """Growth insight text for the group view."""
    ffs   = stats["ffs"]
    l2b   = stats["l2b"] or 0
    fico  = stats["avg_fico"] or 0
    b_l2b = benchmarks.get("l2b") or 0.05
    b_ffs = benchmarks.get("ffs") or 20

    if fico > 0 and fico < 615 and l2b < b_l2b * 0.7:
        return ("Deal Mix Review",
                "Application mix skews toward subprime",
                f"Avg FICO at submission is {fico:.0f}, below Upstart's buy box (620+). "
                f"Look-to-book of {l2b:.1%} reflects low approvals on this mix. "
                f"Prioritize customers with FICO 620–740 on vehicles 5–10 years old.")
    if ffs > 0 and ffs < b_ffs * 0.4:
        return ("Low Volume",
                "Below-average credit application volume",
                f"This group submitted {int(ffs)} application{'s' if ffs != 1 else ''} this period "
                f"(group median: {int(b_ffs)}). Growing submission volume is the fastest path to "
                f"increasing funded loans across the group.")
    if l2b >= b_l2b * 0.9:
        return ("Strong Performer",
                "Above-average deal quality across the group",
                f"Look-to-book of {l2b:.1%} is at or above the group network median ({b_l2b:.1%}). "
                f"Well positioned to grow funded loan volume group-wide.")
    if l2b < b_l2b * 0.7:
        return ("Conversion Opportunity",
                "Look-to-book below group network average",
                f"Look-to-book of {l2b:.1%} trails the group median ({b_l2b:.1%}). "
                f"Review deal mix across locations — focus on FICO 620–740, vehicles 5–10 years old.")
    return ("On Track",
            "Performing in line with group network averages",
            f"Submission volume and conversion are tracking with the Upstart group network.")


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Upstart | Dealer Performance",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
  /* Shrink Streamlit's header to just the sidebar toggle; hide branding/actions */
  @media (min-width: 768px) {{
    header[data-testid="stHeader"] {{
      height: 2rem !important;
      min-height: 2rem !important;
      background: transparent !important;
      box-shadow: none !important;
    }}
    [data-testid="stHeaderActionElements"],
    [data-testid="stHeaderLogo"] {{ display: none !important; }}
  }}
  /* On mobile keep the full header with teal background for hamburger */
  @media (max-width: 767px) {{
    header[data-testid="stHeader"] {{ background: {DTEAL} !important; }}
  }}
  .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; }}

  /* Sidebar */
  section[data-testid="stSidebar"] > div {{ background:{DTEAL}; }}
  section[data-testid="stSidebar"] label,
  section[data-testid="stSidebar"] p,
  section[data-testid="stSidebar"] span,
  section[data-testid="stSidebar"] div {{ color:white !important; }}
  section[data-testid="stSidebar"] .stSelectbox > div > div {{
    background:rgba(255,255,255,0.15) !important; color:white !important;
  }}

  /* Print styles — hides sidebar, action buttons, and Streamlit chrome */
  @media print {{
    header[data-testid="stHeader"],
    section[data-testid="stSidebar"],
    [data-testid="stToolbar"],
    .no-print {{ display: none !important; }}
    .block-container {{ padding: 0 !important; margin: 0 !important; max-width: 100% !important; }}
    @page {{ margin: 0.45in; size: letter; }}
  }}
</style>
""", unsafe_allow_html=True)


# ── Load data ──────────────────────────────────────────────────────────────────
with st.spinner("Loading data…"):
    try:
        funnel, name_map, dsm_map, health_df = load_all_data()
        credit_apps   = load_credit_apps()
        pastdue_loans = load_pastdue_loans()
        unperfected_loans = load_unperfected_loans()
        sf_df         = load_sf_data()
        group_map     = build_group_map(sf_df) if not sf_df.empty else {}
    except Exception as e:
        st.error(f"Could not load data: {e}")
        st.stop()

all_weeks        = sorted(funnel["week"].dropna().unique())
week_label_list  = [pd.Timestamp(w).strftime("Week of %-m/%-d/%y") for w in all_weeks]

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<div style='color:white;font-size:17px;font-weight:700;margin-bottom:14px;'>"
                "UPSTART | AUTO RETAIL</div>", unsafe_allow_html=True)

    view = st.radio("View", ["Dealer", "Group"], horizontal=True,
                    label_visibility="collapsed")

    st.markdown("---")

    if view == "Dealer":
        dealer_ids   = sorted(funnel["dealer_id"].dropna().unique(), key=lambda d: name_map.get(d, d))
        display_opts = [f"{name_map.get(d, d)}  ({d})" for d in dealer_ids]
        sel_disp   = st.selectbox("Dealer", display_opts)
        sel_dealer = dealer_ids[display_opts.index(sel_disp)]
    else:
        group_names = sorted(group_map.keys()) if group_map else []
        if not group_names:
            st.warning("No group data available.")
            st.stop()
        sel_group = st.selectbox("Group", group_names)

    st.markdown("---")
    st.markdown("<span style='color:white;font-weight:600;font-size:13px;'>Date Range</span>",
                unsafe_allow_html=True)

    # Start options: week-start dates; end options: corresponding week-end dates
    start_opts = [pd.Timestamp(w).strftime("%-m/%-d/%Y") for w in all_weeks]
    end_opts   = [(pd.Timestamp(w) + pd.Timedelta(days=6)).strftime("%-m/%-d/%Y")
                  for w in all_weeks]

    default_si = max(0, len(all_weeks) - 5)
    si = start_opts.index(st.selectbox("Start Date", start_opts, index=default_si))
    ei = end_opts.index(st.selectbox("End Date",   end_opts,   index=len(all_weeks) - 1))

    if si > ei:
        st.error("Start date must be before end date.")
        st.stop()

    sel_weeks   = all_weeks[si : ei + 1]
    n_weeks     = len(sel_weeks)
    prior_weeks = all_weeks[max(0, si - n_weeks) : si]

    st.markdown("---")
    st.caption(f"{n_weeks} week(s)")
    if prior_weeks:
        _prior_start = pd.Timestamp(prior_weeks[0]).strftime("%-m/%-d")
        _prior_end   = (pd.Timestamp(prior_weeks[-1]) + pd.Timedelta(days=6)).strftime("%-m/%-d/%Y")
        st.caption(f"Prior: {_prior_start} → {_prior_end}")

    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Auto-refreshes every 30 min")


# ── Shared period string ───────────────────────────────────────────────────────
period_str = (f"{pd.Timestamp(sel_weeks[0]).strftime('%-m/%-d')} – "
              f"{(pd.Timestamp(sel_weeks[-1]) + pd.Timedelta(days=6)).strftime('%-m/%-d/%Y')}")

# ── DEALER VIEW ────────────────────────────────────────────────────────────────
if view == "Dealer":
    p           = period_metrics(funnel, sel_dealer, sel_weeks)
    dealer_name = name_map.get(sel_dealer, sel_dealer)
    dsm_name    = dsm_map.get(sel_dealer, "—")
    drm_info    = DRM_CONTACTS.get(dsm_name, {})
    drm_phone   = drm_info.get("phone", "")
    drm_email   = drm_info.get("email", "")

    dealer_stats, nav = compute_network_stats(funnel, sel_weeks)

    ric_rank    = percentile_rank(dealer_stats, "ric",          sel_dealer, True)
    res_rank    = percentile_rank(dealer_stats, "total_reserve",sel_dealer, True)
    be_rank     = percentile_rank(dealer_stats, "avg_be",       sel_dealer, True)

    opp_title, opp_body = generate_opportunity(p, nav, dealer_name)

    wkly = weekly_breakdown(funnel, sel_dealer, sel_weeks)
    dh   = get_health(health_df, sel_dealer)
    bm   = health_benchmark(health_df)


# ── GROUP VIEW ────────────────────────────────────────────────────────────────
if view == "Group":
    ginfo      = group_map.get(sel_group, {})
    g_dealer_ids   = ginfo.get("dealer_ids", [])
    g_dealer_names = ginfo.get("dealer_names", {})
    g_dsm      = max(ginfo.get("dsm_counts", {"—": 1}), key=lambda k: ginfo["dsm_counts"][k])
    gp         = group_period_metrics(funnel, g_dealer_ids, sel_weeks)
    g_wkly     = group_weekly_trend(funnel, g_dealer_ids, sel_weeks)
    g_bkdn     = group_dealer_breakdown(funnel, g_dealer_ids, g_dealer_names, sel_weeks)
    all_gstats = compute_all_groups(funnel, group_map, sel_weeks)
    g_bench    = compute_group_benchmarks_dash(all_gstats)
    g_ranks    = compute_group_rankings_dash(all_gstats)
    g_rank     = g_ranks.get(sel_group, {})
    total_grps = g_rank.get("total", len(all_gstats))

    # ── Group header ─────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="background:linear-gradient(135deg,{DTEAL} 0%,{TEAL} 60%,#00c9ba 100%);
            padding:14px 20px 12px;border-radius:8px;
            display:flex;justify-content:space-between;align-items:center;
            margin-bottom:4px;box-shadow:0 2px 8px rgba(0,0,0,.12);">
  <div>
    <span style="color:white;font-size:20px;font-weight:900;letter-spacing:.5px;">UPSTART</span>
    <span style="color:rgba(255,255,255,.75);font-size:14px;"> | AUTO RETAIL</span>
  </div>
  <div style="text-align:right;">
    <div style="color:rgba(255,255,255,.75);font-size:11px;">Group Performance Report</div>
    <div style="color:white;font-size:14px;font-weight:700;">{period_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown(f"""
<div style="margin:6px 0 2px;">
  <span style="font-size:22px;font-weight:800;color:#111;">{_html.escape(sel_group)}</span>
</div>
<div style="font-size:13px;color:#555;margin-bottom:8px;">
  {len(g_dealer_ids)} dealer location{'s' if len(g_dealer_ids) != 1 else ''}
</div>
""", unsafe_allow_html=True)

    if gp is None:
        st.info("No activity data found for this group in the selected period.")
        st.stop()

    _ins_title, _ins_sub, _ins_body = group_performance_insight(gp, g_bench)

    # ── Action buttons ───────────────────────────────────────────────────────
    _gbtn1, _gbtn2, _gspacer = st.columns([1.1, 1.8, 5], gap="small")

    with _gbtn1:
        _g_print_clicked = st.button("🖨️  Print to PDF", use_container_width=True, key="g_print_btn")

    with _gbtn2:
        with st.popover("📧  Send Report", use_container_width=True):
            st.markdown(f"**Email group report — {_html.escape(sel_group)}**")

            _g_to_email = st.text_input("Recipient email address",
                                        placeholder="contact@grouphq.com",
                                        label_visibility="collapsed",
                                        key="g_email_input")

            st.markdown("<div style='font-size:12px;color:#555;margin:8px 0 3px;font-weight:600;'>"
                        "Personal message (optional)</div>", unsafe_allow_html=True)
            _g_personal_msg = st.text_area(
                "g_personal_msg",
                placeholder="e.g. Here's your group performance report for the period. "
                            "Let me know if you'd like to connect to review.",
                label_visibility="collapsed",
                height=90,
                key="g_personal_msg_input",
            )

            _g_drm_info  = DRM_CONTACTS.get(g_dsm, {})
            _g_drm_phone = _g_drm_info.get("phone", "")
            _g_drm_email = _g_drm_info.get("email", "")
            st.markdown(f"""
            <div style="background:#f5f5f5;border-left:3px solid {TEAL};
                        padding:8px 12px;border-radius:0 4px 4px 0;
                        font-size:11.5px;color:#444;margin:8px 0 10px;line-height:1.7;">
              <b>{_html.escape(g_dsm)}</b><br>
              Dealer Relationship Manager · Upstart Auto Retail<br>
              {_g_drm_phone}{' · ' if _g_drm_phone and _g_drm_email else ''}
              <span style="color:{TEAL};">{_g_drm_email}</span>
            </div>
            """, unsafe_allow_html=True)

            _g_send_clicked = st.button("Send Report", type="primary",
                                        use_container_width=True, key="g_send_btn",
                                        disabled=not bool(_g_to_email.strip()))

            if _g_send_clicked and _g_to_email.strip():
                with st.spinner("Generating PDF and sending email…"):
                    try:
                        _g_pdf_bytes = generate_group_pdf(
                            sel_group, g_dsm, period_str, gp, g_bench, g_rank,
                            total_grps, _ins_sub, _ins_body, g_wkly, g_bkdn,
                        )
                        _g_subject = f"Group Performance Report — {sel_group} — {period_str}"
                        _g_personal_block = f"{_g_personal_msg.strip()}\n\n" if _g_personal_msg.strip() else ""
                        _g_body = (
                            f"Hi,\n\n"
                            f"{_g_personal_block}"
                            f"Please find the Upstart Group Performance Report attached for {period_str}.\n\n"
                            f"Group Highlights:\n"
                            f"  • Funded Loans:   {_n(gp['fl'])}  (group median {_n(g_bench.get('fl'))})\n"
                            f"  • Look to Book:   {_p(gp['l2b'])}  (group median {_p(g_bench.get('l2b'))})\n"
                            f"  • Approval Rate:  {_p(gp['approval_rate'])}  (group median {_p(g_bench.get('approval_rate'))})\n"
                            f"  • Total Reserve:  {_d(gp['total_reserve'])}  (group median {_d(g_bench.get('total_reserve'))})\n"
                            f"  • Avg Back End:   {_d(gp['avg_be'])}  (group median {_d(g_bench.get('avg_be'))})\n\n"
                            f"Feel free to reach out anytime.\n\n"
                            f"--\n"
                            f"{g_dsm}\n"
                            f"Dealer Relationship Manager · Upstart Auto Retail\n"
                            f"{_g_drm_phone}{' · ' if _g_drm_phone and _g_drm_email else ''}{_g_drm_email}"
                        )
                        send_report_email(
                            _g_to_email.strip(), sel_group, g_dsm, _g_drm_email,
                            period_str, _g_pdf_bytes, _g_subject, _g_body,
                        )
                        st.success(f"✅ Report sent to {_g_to_email.strip()}")
                    except Exception as _ge:
                        err = str(_ge)
                        if "insufficient" in err.lower() or "scope" in err.lower() or "forbidden" in err.lower():
                            st.error("Gmail permission not yet granted. Run `python3 'setup_gmail_auth.py'` then try again.")
                        else:
                            st.error(f"Send failed: {err}")

    if _g_print_clicked:
        components.html("<script>window.parent.print();</script>", height=0)

    st.markdown("---")

    # ── Rankings ─────────────────────────────────────────────────────────────
    def _grp_rank_badge(label, rank_key):
        rank = g_rank.get(rank_key)
        if rank is None:
            return rank_badge(label, "N/A", "neutral")
        pct_val = (1 - rank / total_grps) * 100 if total_grps > 1 else 100
        pct_lbl = f"Top {max(1, round(100 - pct_val))}%" if pct_val >= 50 else f"Bottom {max(1, round(pct_val))}%"
        tier    = "top" if pct_val >= 50 else "bottom"
        return rank_badge(label, pct_lbl, tier)

    st.markdown(
        f"<div style='display:flex;gap:0;margin-bottom:14px;'>"
        + _grp_rank_badge("Funded Loans",        "fl_rank")
        + _grp_rank_badge("Total Reserve Earned", "reserve_rank")
        + _grp_rank_badge("Avg Back End",          "be_rank")
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── Performance insight ───────────────────────────────────────────────────
    st.markdown(f"""
<div style="display:flex;align-items:stretch;margin-bottom:18px;gap:0;
            border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
  <div style="background:{TEAL};color:white;padding:12px 14px;font-size:11.5px;
              font-weight:700;text-align:center;min-width:90px;max-width:90px;
              display:flex;align-items:center;justify-content:center;line-height:1.4;">
    Group<br>Insight
  </div>
  <div style="padding:12px 16px;background:white;flex:1;">
    <div style="font-weight:700;font-size:13.5px;color:#111;margin-bottom:4px;">
      {_html.escape(_ins_sub)}
    </div>
    <div style="font-size:13px;color:#444;line-height:1.55;">
      {_html.escape(_ins_body)}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Metric grid ───────────────────────────────────────────────────────────
    nav_dec_g = max(0, (g_bench.get("ffs") or 0) - (g_bench.get("gr") or 0))
    ap_tier_g = _mbox_tier(gp.get("approval_rate"), g_bench.get("approval_rate"), higher_better=True)
    fp_tier_g = _mbox_tier(gp.get("l2b"),           g_bench.get("l2b"),           higher_better=True)
    dq_tier_g = _mbox_tier(gp.get("avg_fico_orig"), g_bench.get("avg_fico_orig"), higher_better=True)

    _gc1, _gc2, _gc3 = st.columns(3, gap="medium")
    with _gc1:
        st.markdown(_mbox("Engagement", ap_tier_g, [
            ("Total Logins",            _n(gp["logins"]),  "—"),
            ("Avg Weekly Unique Users",
             _n((gp.get("avg_users") or 0), 1) if gp.get("avg_users") else "—", "—"),
            ("Apps Submitted", _n(gp["ffs"]), _n(g_bench.get("ffs"))),
            ("Approved",       _n(gp["gr"]),  _n(g_bench.get("gr"))),
            ("Declined",       _n(gp["declined"]), _n(nav_dec_g or None)),
            ("Approval Rate",  _p(gp["approval_rate"]), _p(g_bench.get("approval_rate"))),
            ("Avg FICO at App",_n(gp["avg_fico"]),       _n(g_bench.get("avg_fico"))),
        ], min_height=_MH, bench_label="Group Median"), unsafe_allow_html=True)
    with _gc2:
        st.markdown(_mbox("Funding Performance", fp_tier_g, [
            ("Funded Loans",     _n(gp["fl"]),                  _n(g_bench.get("fl"))),
            ("Look to Book",     _p(gp["l2b"]),                 _p(g_bench.get("l2b"))),
            ("Approve to Book",  _p(gp["a2b"]),                 _p(g_bench.get("a2b"))),
            ("Avg Days to Fund", _n(gp["avg_days_to_fund"], 1), _n(g_bench.get("avg_days_to_fund"), 1)),
        ], min_height=_MH, bench_label="Group Median"), unsafe_allow_html=True)
    with _gc3:
        st.markdown(_mbox("Deal Quality & Profitability", dq_tier_g, [
            ("Avg FICO (Funded)",       _n(gp["avg_fico_orig"]), _n(g_bench.get("avg_fico_orig"))),
            ("Avg Amount Financed",     _d(gp["avg_principal"]), _d(g_bench.get("avg_principal"))),
            ("Avg LTV",                 _p(gp["avg_ltv"]),       _p(g_bench.get("avg_ltv"))),
            ("Avg Contract Rate (APR)", _p(gp["avg_apr"]),       _p(g_bench.get("avg_apr"))),
            ("Avg Buy Rate",            _p(gp["avg_buy_rate"]),  _p(g_bench.get("avg_buy_rate"))),
            ("Avg Reserve",             _d(gp["avg_reserve"]),   _d(g_bench.get("avg_reserve"))),
            ("Total Reserve Earned",    _d(gp["total_reserve"]), _d(g_bench.get("total_reserve"))),
            ("Avg Back End",            _d(gp["avg_be"]),        _d(g_bench.get("avg_be"))),
        ], min_height=_MH, bench_label="Group Median"), unsafe_allow_html=True)

    # ── Weekly trend ─────────────────────────────────────────────────────────
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='color:{DTEAL};font-size:13px;font-weight:700;margin:4px 0 8px;'>"
                f"Week-by-Week — {period_str}</div>", unsafe_allow_html=True)

    if not g_wkly:
        st.info("No weekly data for this group in the selected period.")
    else:
        wk_labels_g = [r["label"] for r in g_wkly]
        fig_g = go.Figure()
        fig_g.add_trace(go.Bar(
            x=wk_labels_g, y=[r["apps"] for r in g_wkly],
            name="FFS Submitted", marker_color="#80cbc4", opacity=0.85,
        ))
        fig_g.add_trace(go.Bar(
            x=wk_labels_g, y=[r["funded"] for r in g_wkly],
            name="Funded Loans", marker_color=TEAL,
        ))
        fig_g.add_trace(go.Scatter(
            x=wk_labels_g, y=[r["logins"] for r in g_wkly],
            name="Log-ins", mode="lines+markers",
            line=dict(color=DTEAL, width=2), marker=dict(size=7),
            yaxis="y2",
        ))
        fig_g.update_layout(
            barmode="group", height=280,
            margin=dict(t=20, b=20, l=0, r=0),
            plot_bgcolor="white", paper_bgcolor="white",
            yaxis=dict(title="FFS / Funded", gridcolor="#eee", gridwidth=1),
            yaxis2=dict(title="Log-ins", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})

        g_total_apps = sum(r["apps"] for r in g_wkly)
        g_total_appr = sum(r["approved"] for r in g_wkly)
        g_total_fund = sum(r["funded"] for r in g_wkly)
        g_wkly_body  = ""
        for i, r in enumerate(g_wkly):
            bg = "#F5F7FA" if i % 2 == 0 else "white"
            g_wkly_body += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['label']}</td>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['apps']}</td>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['approved']}</td>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['appr_rate']}</td>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['funded']}</td>"
                f"<td style='padding:7px 12px;text-align:center;'>{r['l2b']}</td>"
                f"</tr>"
            )
        g_appr_rate = f"{g_total_appr/g_total_apps:.0%}" if g_total_apps > 0 else "0%"
        g_l2b       = f"{g_total_fund/g_total_apps:.0%}"  if g_total_apps > 0 else "0%"
        g_wkly_body += (
            f"<tr style='background:{TEAL};color:white;font-weight:700;'>"
            f"<td style='padding:7px 12px;text-align:center;'>Total</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{g_total_apps}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{g_total_appr}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{g_appr_rate}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{g_total_fund}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{g_l2b}</td>"
            f"</tr>"
        )
        st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">
  <thead>
    <tr style="background:{TEAL};">
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Week</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Apps</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Approved</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Appr. Rate</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Funded</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">L2B</th>
    </tr>
  </thead>
  <tbody>{g_wkly_body}</tbody>
</table>
""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Dealer breakdown ──────────────────────────────────────────────────────
    st.markdown(f"<div style='color:{DTEAL};font-size:13px;font-weight:700;margin-bottom:8px;'>"
                f"Dealer Breakdown</div>", unsafe_allow_html=True)

    if not g_bkdn:
        st.info("No dealer data available for this group.")
    else:
        bkdn_rows = ""
        for i, (dname, ds) in enumerate(g_bkdn):
            bg = "#F5F7FA" if i % 2 == 0 else "white"
            if ds is None:
                bkdn_rows += (
                    f"<tr style='background:{bg};color:#aaa;font-style:italic;'>"
                    f"<td style='padding:7px 12px;'>{_html.escape(dname)}</td>"
                    + "<td style='padding:7px 12px;text-align:center;'>—</td>" * 9
                    + "</tr>"
                )
            else:
                bkdn_rows += (
                    f"<tr style='background:{bg};'>"
                    f"<td style='padding:7px 12px;font-weight:600;'>{_html.escape(dname)}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_n(ds['logins'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_n(ds['ffs'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_n(ds['gr'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_p(ds['approval_rate'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_n(ds['ric'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_p(ds['l2b'])}</td>"
                    f"<td style='padding:7px 12px;text-align:center;'>{_p(ds['a2b'])}</td>"
                    f"<td style='padding:7px 12px;text-align:right;'>{_d(ds['total_reserve'])}</td>"
                    f"<td style='padding:7px 12px;text-align:right;'>{_d(ds['avg_be'])}</td>"
                    f"</tr>"
                )
        st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:12.5px;margin-top:4px;">
  <thead>
    <tr style="background:{TEAL};">
      <th style="padding:7px 12px;text-align:left;color:white;font-weight:600;">Dealer</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Logins</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Apps</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Approved</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Appr. Rate</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Funded</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">L2B</th>
      <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">A2B</th>
      <th style="padding:7px 12px;text-align:right;color:white;font-weight:600;">Total Reserve</th>
      <th style="padding:7px 12px;text-align:right;color:white;font-weight:600;">Avg Back End</th>
    </tr>
  </thead>
  <tbody>{bkdn_rows}</tbody>
</table>
""", unsafe_allow_html=True)

    # ── Group footer ──────────────────────────────────────────────────────────
    from datetime import datetime as _dt_g
    st.markdown(
        f"<div style='text-align:center;font-size:11px;color:#aaa;margin-top:12px;'>"
        f"Generated {_dt_g.now().strftime('%B %d, %Y')} · Confidential — For internal use only · Upstart Auto Retail"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ── DEALER VIEW: HEADER ────────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:linear-gradient(135deg,{DTEAL} 0%,{TEAL} 60%,#00c9ba 100%);
            padding:14px 20px 12px;border-radius:8px;
            display:flex;justify-content:space-between;align-items:center;
            margin-bottom:4px;box-shadow:0 2px 8px rgba(0,0,0,.12);">
  <div>
    <span style="color:white;font-size:20px;font-weight:900;letter-spacing:.5px;">UPSTART</span>
    <span style="color:rgba(255,255,255,.75);font-size:14px;"> | AUTO RETAIL</span>
  </div>
  <div style="text-align:right;">
    <div style="color:rgba(255,255,255,.75);font-size:11px;">Dealer Performance Report</div>
    <div style="color:white;font-size:14px;font-weight:700;">{period_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
<div style="margin:6px 0 2px;">
  <span style="font-size:22px;font-weight:800;color:#111;">{_html.escape(dealer_name)}</span>
</div>
<div style="font-size:13px;color:#555;margin-bottom:8px;">
  DSM: <b>{_html.escape(dsm_name)}</b>
  {"&nbsp;·&nbsp;" + drm_phone if drm_phone else ""}
  {"&nbsp;·&nbsp;<a href='mailto:" + drm_email + "' style='color:" + TEAL + ";'>" + drm_email + "</a>" if drm_email else ""}
</div>
""", unsafe_allow_html=True)

# ── ACTION BUTTONS ─────────────────────────────────────────────────────────────
_btn_col1, _btn_col2, _spacer = st.columns([1.1, 1.5, 5], gap="small")

with _btn_col1:
    _print_clicked = st.button("🖨️  Print to PDF", use_container_width=True, key="print_btn")

with _btn_col2:
    with st.popover("📧  Send Report to Dealer", use_container_width=True):
        st.markdown(f"**Email report to {_html.escape(dealer_name)}**")

        _to_email = st.text_input("Dealer email address",
                                  placeholder="f&i@dealership.com",
                                  label_visibility="collapsed",
                                  key="dealer_email_input")

        st.markdown("<div style='font-size:12px;color:#555;margin:8px 0 3px;font-weight:600;'>"
                    "Personal message (optional)</div>", unsafe_allow_html=True)
        _personal_msg = st.text_area(
            "personal_msg",
            placeholder="e.g. Great speaking with you last week — here's your monthly report. "
                        "Let me know if you'd like to connect to review.",
            label_visibility="collapsed",
            height=90,
            key="personal_msg_input",
        )

        # Pre-populated signature preview
        st.markdown(f"""
        <div style="background:#f5f5f5;border-left:3px solid {TEAL};
                    padding:8px 12px;border-radius:0 4px 4px 0;
                    font-size:11.5px;color:#444;margin:8px 0 10px;line-height:1.7;">
          <b>{_html.escape(dsm_name)}</b><br>
          Dealer Relationship Manager · Upstart Auto Retail<br>
          {drm_phone} · <span style="color:{TEAL};">{drm_email}</span>
        </div>
        """, unsafe_allow_html=True)

        _send_clicked = st.button("Send Report", type="primary",
                                  use_container_width=True, key="send_btn",
                                  disabled=not bool(_to_email.strip()))

        if _send_clicked and _to_email.strip():
            with st.spinner("Generating PDF and sending email…"):
                try:
                    _pdf_bytes = generate_dealer_pdf(
                        dealer_name, dsm_name, drm_phone, drm_email, period_str,
                        p, nav, dh, bm, ric_rank, res_rank, be_rank,
                        opp_title, opp_body, wkly, n_weeks,
                    )
                    _subject = f"Your Upstart Performance Report — {period_str}"

                    # Build body: optional personal note → highlights → signature
                    _personal_block = f"{_personal_msg.strip()}\n\n" if _personal_msg.strip() else ""
                    _body = (
                        f"Hi,\n\n"
                        f"{_personal_block}"
                        f"Please find your Upstart Dealer Performance Report attached for {period_str}.\n\n"
                        f"Highlights:\n"
                        f"  • Funded Loans:   {_n(p['ric'])}  (network avg {_n(nav.get('ric'))})\n"
                        f"  • Look to Book:   {_p(p['l2b'])}  (network avg {_p(nav.get('l2b'))})\n"
                        f"  • Approval Rate:  {_p(p['approval_rate'])}  (network avg {_p(nav.get('approval_rate'))})\n"
                        f"  • Avg FICO:       {_n(p['avg_fico'])}  (network avg {_n(nav.get('avg_fico'))})\n"
                        f"  • Total Reserve:  {_d(p['total_reserve'])}  (network avg {_d(nav.get('total_reserve'))})\n"
                        f"  • Avg Back End:   {_d(p['avg_be'])}  (network avg {_d(nav.get('avg_be'))})\n\n"
                        f"Feel free to reach out anytime.\n\n"
                        f"--\n"
                        f"{dsm_name}\n"
                        f"Dealer Relationship Manager · Upstart Auto Retail\n"
                        f"{drm_phone} · {drm_email}"
                    )
                    send_report_email(
                        _to_email.strip(), dealer_name, dsm_name, drm_email,
                        period_str, _pdf_bytes, _subject, _body,
                    )
                    st.success(f"✅ Report sent to {_to_email.strip()}")
                except Exception as _e:
                    err = str(_e)
                    if "insufficient" in err.lower() or "scope" in err.lower() or "forbidden" in err.lower():
                        st.error("Gmail permission not yet granted. Run this once in your terminal:\n\n"
                                 "`python3 'setup_gmail_auth.py'`\n\nthen try again.")
                    else:
                        st.error(f"Send failed: {err}")

if _print_clicked:
    components.html("<script>window.parent.print();</script>", height=0)

st.markdown("---")

# ── NETWORK RANKINGS ───────────────────────────────────────────────────────────
st.markdown(f"<div style='font-size:11px;font-weight:700;color:#888;text-transform:uppercase;"
            f"letter-spacing:.8px;margin-bottom:6px;'>UPSTART NETWORK RANKING</div>",
            unsafe_allow_html=True)

st.markdown(
    f"<div style='display:flex;gap:0;margin-bottom:14px;'>"
    + rank_badge("Funded Loans",        ric_rank[1], ric_rank[2])
    + rank_badge("Total Reserve Earned",res_rank[1], res_rank[2])
    + rank_badge("Avg Back End",        be_rank[1],  be_rank[2])
    + "</div>",
    unsafe_allow_html=True,
)

# ── GROWTH OPPORTUNITY ─────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex;align-items:stretch;margin-bottom:18px;gap:0;
            border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
  <div style="background:{TEAL};color:white;padding:12px 14px;font-size:11.5px;
              font-weight:700;text-align:center;min-width:90px;max-width:90px;
              display:flex;align-items:center;justify-content:center;
              line-height:1.4;">
    Growth<br>Opportunity
  </div>
  <div style="padding:12px 16px;background:white;flex:1;">
    <div style="font-weight:700;font-size:13.5px;color:#111;margin-bottom:4px;">
      {_html.escape(opp_title)}
    </div>
    <div style="font-size:13px;color:#444;line-height:1.55;">
      {_html.escape(opp_body)}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── 2×2 METRIC GRID ───────────────────────────────────────────────────────────
# Tier per section — drives box color
nav_dec  = max(0, (nav.get("ffs") or 0) - (nav.get("gr") or 0))
ap_tier  = _mbox_tier(p.get("approval_rate"), nav.get("approval_rate"), higher_better=True)
fp_tier  = _mbox_tier(p.get("l2b"),           nav.get("l2b"),           higher_better=True)
dq_tier2 = _mbox_tier(p.get("avg_fico_orig"), nav.get("avg_fico_orig"), higher_better=True)

_mc1, _mc2, _mc3 = st.columns(3, gap="medium")
with _mc1:
    st.markdown(_mbox("Engagement", ap_tier, [
        ("Total Logins",            _n(p["logins"]),                                "—"),
        ("Avg Weekly Unique Users", _n((p["unique_users"] or 0) / max(1, n_weeks), 1), "—"),
        ("Apps Submitted",          _n(p["ffs"]),            _n(nav.get("ffs"))),
        ("Approved",                _n(p["gr"]),             _n(nav.get("gr"))),
        ("Declined",                _n(p["declined"]),       _n(nav_dec or None)),
        ("Approval Rate",           _p(p["approval_rate"]),  _p(nav.get("approval_rate"))),
        ("Avg FICO at App",         _n(p["avg_fico"]),       _n(nav.get("avg_fico"))),
    ], min_height=_MH), unsafe_allow_html=True)

with _mc2:
    st.markdown(_mbox("Funding Performance", fp_tier, [
        ("Funded Loans",     _n(p["ric"]),                 _n(nav.get("ric"))),
        ("Look to Book",     _p(p["l2b"]),                 _p(nav.get("l2b"))),
        ("Approve to Book",  _p(p["a2b"]),                 _p(nav.get("a2b"))),
        ("Avg Days to Fund", _n(p["avg_days_to_fund"], 1), _n(nav.get("avg_days_to_fund"), 1)),
    ], min_height=_MH), unsafe_allow_html=True)

with _mc3:
    st.markdown(_mbox("Deal Quality & Profitability", dq_tier2, [
        ("Avg FICO (Funded)",      _n(p["avg_fico_orig"]), _n(nav.get("avg_fico_orig"))),
        ("Avg Amount Financed",    _d(p["avg_principal"]), _d(nav.get("avg_principal"))),
        ("Avg LTV",                _p(p["avg_ltv"]),       _p(nav.get("avg_ltv"))),
        ("Avg Contract Rate (APR)",_p(p["avg_apr"]),       _p(nav.get("avg_apr"))),
        ("Avg Buy Rate",           _p(p["avg_buy_rate"]),  _p(nav.get("avg_buy_rate"))),
        ("Avg Reserve",            _d(p["avg_reserve"]),   _d(nav.get("avg_reserve"))),
        ("Total Reserve Earned",   _d(p["total_reserve"]), _d(nav.get("total_reserve"))),
        ("Avg Back End",           _d(p["avg_be"]),        _d(nav.get("avg_be"))),
    ], min_height=_MH), unsafe_allow_html=True)


# ── WEEK-BY-WEEK ───────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
st.markdown(f"<div style='color:{DTEAL};font-size:13px;font-weight:700;margin:4px 0 8px;'>"
            f"Week-by-Week — {period_str}</div>", unsafe_allow_html=True)

if not wkly:
    st.info("No weekly data for this dealer in the selected period.")
else:
    wk_labels = [r["label"] for r in wkly]

    # Single combined chart: FFS + Funded bars, Logins line on y2
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=wk_labels, y=[r["apps"] for r in wkly],
        name="FFS Submitted", marker_color="#80cbc4", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=wk_labels, y=[r["funded"] for r in wkly],
        name="Funded Loans", marker_color=TEAL,
    ))
    fig.add_trace(go.Scatter(
        x=wk_labels, y=[r["logins"] for r in wkly],
        name="Log-ins", mode="lines+markers",
        line=dict(color=DTEAL, width=2), marker=dict(size=7),
        yaxis="y2",
    ))
    fig.update_layout(
        barmode="group", height=280,
        margin=dict(t=20, b=20, l=0, r=0),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(title="FFS / Funded", gridcolor="#eee", gridwidth=1),
        yaxis2=dict(title="Log-ins", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Weekly summary table
    total_apps = sum(r["apps"] for r in wkly)
    total_appr = sum(r["approved"] for r in wkly)
    total_fund = sum(r["funded"] for r in wkly)

    wkly_body = ""
    for i, r in enumerate(wkly):
        bg = "#F5F7FA" if i % 2 == 0 else "white"
        wkly_body += (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['label']}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['apps']}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['approved']}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['appr_rate']}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['funded']}</td>"
            f"<td style='padding:7px 12px;text-align:center;'>{r['l2b']}</td>"
            f"</tr>"
        )
    total_appr_rate = f"{total_appr/total_apps:.0%}" if total_apps > 0 else "0%"
    total_l2b       = f"{total_fund/total_apps:.0%}"  if total_apps > 0 else "0%"
    wkly_body += (
        f"<tr style='background:{TEAL};color:white;font-weight:700;'>"
        f"<td style='padding:7px 12px;text-align:center;'>Total</td>"
        f"<td style='padding:7px 12px;text-align:center;'>{total_apps}</td>"
        f"<td style='padding:7px 12px;text-align:center;'>{total_appr}</td>"
        f"<td style='padding:7px 12px;text-align:center;'>{total_appr_rate}</td>"
        f"<td style='padding:7px 12px;text-align:center;'>{total_fund}</td>"
        f"<td style='padding:7px 12px;text-align:center;'>{total_l2b}</td>"
        f"</tr>"
    )
    st.markdown(f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">
      <thead>
        <tr style="background:{TEAL};">
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Week</th>
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Apps</th>
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Approved</th>
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Appr. Rate</th>
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">Funded</th>
          <th style="padding:7px 12px;text-align:center;color:white;font-weight:600;">L2B</th>
        </tr>
      </thead>
      <tbody>{wkly_body}</tbody>
    </table>
    """, unsafe_allow_html=True)

st.markdown("---")


# ── UPSTART OPPORTUNITIES ──────────────────────────────────────────────────────
st.markdown(f"<div style='color:{DTEAL};font-size:13px;font-weight:700;margin-bottom:4px;'>"
            f"Upstart Opportunities — Deals In Our Wheelhouse</div>", unsafe_allow_html=True)
st.caption("Credit apps from this period matching Upstart's buy box (FICO 620–740, APR <20%, vehicle 5–10 years old).")

opp_start = pd.Timestamp(sel_weeks[0])
opp_end   = pd.Timestamp(sel_weeks[-1]) + pd.Timedelta(days=6)
opp_df    = get_opportunities(credit_apps, sel_dealer, opp_start, opp_end)

if opp_df.empty:
    st.markdown("<div style='color:#666;font-size:13px;font-style:italic;'>"
                "No opportunities matching Upstart's buy box found for this period.</div>",
                unsafe_allow_html=True)
else:
    # Build HTML table with clickable View Deal links (matching PDF format)
    opp_rows = ""
    for i, row in opp_df.iterrows():
        bg = "#F5F7FA" if i % 2 == 0 else "white"
        link_cell = (f"<a href='{row['_link']}' target='_blank' "
                     f"style='color:{TEAL};font-weight:600;text-decoration:none;'>View Deal</a>"
                     if row["_link"] else "—")
        opp_rows += (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:6px 10px;'>{row['Date']}</td>"
            f"<td style='padding:6px 10px;'>{_html.escape(str(row['Vehicle']))}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{row['FICO']}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{row['APR']}</td>"
            f"<td style='padding:6px 10px;text-align:right;'>{row['Amount']}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{link_cell}</td>"
            f"</tr>"
        )
    st.markdown(f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">
      <thead>
        <tr style="background:{TEAL};">
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Date</th>
          <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Vehicle</th>
          <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">FICO</th>
          <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">APR</th>
          <th style="padding:7px 10px;text-align:right;color:white;font-weight:600;">Amount</th>
          <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">Link</th>
        </tr>
      </thead>
      <tbody>{opp_rows}</tbody>
    </table>
    """, unsafe_allow_html=True)

st.markdown("---")


# ── PORTFOLIO HEALTH ───────────────────────────────────────────────────────────
# Banner — description text fills the space inside the header, no blank gap
st.markdown(f"""
<div style="background:{TEAL};padding:10px 16px 10px;border-radius:6px 6px 0 0;
            display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0;">
  <div>
    <div>
      <span style="color:white;font-size:15px;font-weight:900;">UPSTART</span>
      <span style="color:rgba(255,255,255,.75);font-size:12px;"> | AUTO RETAIL</span>
    </div>
    <div style="color:rgba(255,255,255,.82);font-size:11.5px;margin-top:4px;
                max-width:520px;line-height:1.45;">
      Cumulative performance of all loans funded through Upstart since this dealership launched.
      Network benchmark is a weighted average across Upstart dealers with 5+ funded loans.
    </div>
  </div>
  <div style="text-align:right;flex-shrink:0;margin-left:16px;">
    <div style="color:rgba(255,255,255,.75);font-size:10px;">Portfolio Health Report</div>
    <div style="color:white;font-size:12px;font-weight:700;">Since Launch on Upstart</div>
  </div>
</div>
<div style="border:1px solid #e0e0e0;border-top:none;border-radius:0 0 6px 6px;
            padding:12px 16px 10px;margin-bottom:16px;">
""", unsafe_allow_html=True)

if dh is None:
    st.info("Portfolio health data not yet available for this dealer (requires funded loan history).")

if dh is None:
    # Still render past due loans even without health stats
    _pd_df_none = get_pastdue_loans(pastdue_loans, sel_dealer)
    if not _pd_df_none.empty:
        st.markdown(f"<div style='color:{DTEAL};font-size:12px;font-weight:700;text-transform:uppercase;"
                    f"letter-spacing:.6px;margin-top:12px;margin-bottom:6px;'>"
                    f"Past Due Loans — Active (Not Yet Charged Off)</div>", unsafe_allow_html=True)
        st.dataframe(_pd_df_none[["loan_id","origination_date","vin","days_past_due",
                                   "payments_made","payments_due","first_payment_due_date"]],
                     use_container_width=True, hide_index=True)
    # ── Unperfected Titles (below delinquent / past due accounts) ──────────────
    render_unperfected_section(unperfected_loans, sel_dealer)
    st.markdown("</div>", unsafe_allow_html=True)
else:
    # Determine box tier from worst ratio in a section
    def _ratio(val, bench):
        if not bench or bench == 0 or val is None: return None
        return val / bench

    def _box_tier(ratios):
        valid = [r for r in ratios if r is not None]
        if not valid: return "neutral"
        worst = max(valid)
        if worst <= 1.0: return "good"
        if worst <= 1.5: return "warn"
        return "bad"

    TIER = {
        "good":    {"bg":"#e8f8f7", "border":TEAL,  "hdr":DTEAL,  "label":"✓ At or Below Benchmark"},
        "warn":    {"bg":"#fff8e1", "border":AMBER,  "hdr":AMBER,  "label":"⚠ Above Average"},
        "bad":     {"bg":"#fff5f5", "border":RED,    "hdr":RED,    "label":"● Needs Attention"},
        "neutral": {"bg":"#f0faf9", "border":TEAL,   "hdr":DTEAL,  "label":""},
    }

    lp_tier = _box_tier([_ratio(dh["epd_pct"], bm.get("epd_pct")),
                          _ratio(dh["co_pct"],  bm.get("co_pct"))])
    dq_tier = _box_tier([_ratio(dh["fpd_pct"],   bm.get("fpd_pct")),
                          _ratio(dh["dpd31_pct"], bm.get("dpd31_pct")),
                          _ratio(dh["dpd61_pct"], bm.get("dpd61_pct"))])

    def _val_color(val, bench):
        r = _ratio(val, bench)
        if r is None: return "#111"
        if r <= 1.0: return GREEN
        if r <= 1.5: return AMBER
        return RED

    def _ph_box(section, tier, rows, show_count=False, show_network=True, min_height=None):
        """
        rows: list of (label, count_or_none, your_val, net_val, val_color)
        show_count:   adds '# Loans' column left of 'Your Portfolio'
        show_network: show/hide the Network Avg column
        min_height:   CSS min-height string (e.g. '230px') for equal-height boxes
        """
        s = TIER[tier]
        mh = f"min-height:{min_height};" if min_height else ""
        status = (f"<div style='font-size:10.5px;font-weight:600;color:{s['hdr']};margin-top:2px;"
                  f"margin-bottom:8px;'>{s['label']}</div>") if s["label"] else "<div style='margin-bottom:8px;'></div>"

        count_hdr = (f"<span style='width:56px;text-align:center;font-size:9.5px;color:#888;'># Loans</span>"
                     if show_count else "")
        net_hdr   = (f"<span style='width:62px;text-align:center;font-size:9.5px;color:#888;'>Network Avg</span>"
                     if show_network else "")
        sub = (f"<div style='display:flex;padding:2px 0 4px;border-bottom:1px solid rgba(0,0,0,.1);'>"
               f"<span style='flex:1;font-size:9.5px;color:#888;'></span>"
               f"{count_hdr}"
               f"<span style='width:62px;text-align:center;font-size:9.5px;color:#888;'>Your Portfolio</span>"
               f"{net_hdr}"
               f"</div>")

        row_html = ""
        for label, cnt, yv, nv, vc in rows:
            count_cell = ""
            if show_count:
                count_cell = (f"<span style='width:56px;text-align:center;font-size:12px;"
                              f"color:#555;font-weight:600;'>{cnt if cnt is not None else '—'}</span>")
            net_cell = (f"<span style='width:62px;text-align:center;font-size:12px;color:#777;'>{nv}</span>"
                        if show_network else "")
            row_html += (
                f"<div style='display:flex;align-items:center;padding:6px 0;"
                f"border-bottom:1px solid rgba(0,0,0,.06);'>"
                f"<span style='flex:1;font-size:12px;color:#444;'>{label}</span>"
                f"{count_cell}"
                f"<span style='width:62px;text-align:center;font-size:13px;"
                f"font-weight:700;color:{vc};'>{yv}</span>"
                f"{net_cell}"
                f"</div>"
            )
        return (
            f"<div style='background:{s['bg']};border:2px solid {s['border']};"
            f"border-radius:10px;padding:14px 16px;{mh}'>"
            f"<div style='color:{s['hdr']};font-size:11px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.6px;'>{section}</div>"
            f"{status}{sub}{row_html}"
            f"</div>"
        )

    # Use the same min-height on all three so boxes stay equal regardless of row count
    _BOX_H = "230px"

    ph_col1, ph_col2, ph_col3 = st.columns(3, gap="medium")

    with ph_col1:
        st.markdown(_ph_box("Portfolio Volume", "neutral", [
            ("Total Funded Loans", None, f"{dh['loan_count']:,}", "—", "#111"),
            ("Total Originations",  None, _d(dh["originations"]),  "—", "#111"),
        ], show_count=False, show_network=False, min_height=_BOX_H), unsafe_allow_html=True)

    with ph_col2:
        st.markdown(_ph_box("Loan Performance", lp_tier, [
            ("Early Payment Default",
             dh["epd_count"],
             _p(dh["epd_pct"], 2), _p(bm.get("epd_pct"), 2),
             _val_color(dh["epd_pct"], bm.get("epd_pct"))),
            ("Charge-off Rate",
             dh["co_count"],
             _p(dh["co_pct"],  2), _p(bm.get("co_pct"),  2),
             _val_color(dh["co_pct"],  bm.get("co_pct"))),
        ], show_count=True, show_network=True, min_height=_BOX_H), unsafe_allow_html=True)

    with ph_col3:
        st.markdown(_ph_box("Delinquency", dq_tier, [
            ("First Payment Delinquency",
             dh["fpd_count"],
             _p(dh["fpd_pct"], 2), _p(bm.get("fpd_pct"), 2),
             _val_color(dh["fpd_pct"], bm.get("fpd_pct"))),
            ("31+ Days Past Due",
             dh["dpd31_count"],
             _p(dh["dpd31_pct"], 1), _p(bm.get("dpd31_pct"), 1),
             _val_color(dh["dpd31_pct"], bm.get("dpd31_pct"))),
            ("61+ Days Past Due",
             dh["dpd61_count"],
             _p(dh["dpd61_pct"], 1), _p(bm.get("dpd61_pct"), 1),
             _val_color(dh["dpd61_pct"], bm.get("dpd61_pct"))),
        ], show_count=True, show_network=True, min_height=_BOX_H), unsafe_allow_html=True)

    st.markdown(
        f"<div style='font-size:11px;color:#555;margin-top:10px;'>"
        f"Box color = overall section performance vs network benchmark &nbsp;·&nbsp; "
        f"<span style='color:{GREEN};font-weight:700;'>■ at/below</span> &nbsp;"
        f"<span style='color:{AMBER};font-weight:700;'>■ up to 1.5×</span> &nbsp;"
        f"<span style='color:{RED};font-weight:700;'>■ above 1.5×</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Past Due Loans (inside portfolio health card) ──────────────────────────
    st.markdown(f"<div style='color:{DTEAL};font-size:12px;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:.6px;margin-top:18px;margin-bottom:6px;'>"
                f"Past Due Loans — Active (Not Yet Charged Off)</div>", unsafe_allow_html=True)

    pd_df = get_pastdue_loans(pastdue_loans, sel_dealer)

    if pd_df.empty:
        st.markdown("<div style='color:#666;font-size:13px;font-style:italic;margin-bottom:8px;'>"
                    "No past due loans on record for this dealer.</div>", unsafe_allow_html=True)
    else:
        n_loans   = len(pd_df)
        avg_dpd   = pd_df["days_past_due"].mean()
        max_dpd   = pd_df["days_past_due"].max()
        zero_pmts = int((pd_df["payments_made"] == 0).sum())

        # Summary chips — 4 equal-width columns spanning full page width
        _s1, _s2, _s3, _s4 = st.columns(4, gap="small")
        with _s1:
            st.markdown(f"""
            <div style="background:#fff5f5;border:2px solid {RED};border-radius:8px;
                        padding:10px 14px;text-align:center;">
              <div style="font-size:10px;font-weight:700;color:{RED};text-transform:uppercase;
                          letter-spacing:.5px;">Past Due Loans</div>
              <div style="font-size:24px;font-weight:800;color:{RED};">{n_loans}</div>
            </div>""", unsafe_allow_html=True)
        with _s2:
            st.markdown(f"""
            <div style="background:#fff8f0;border:2px solid {AMBER};border-radius:8px;
                        padding:10px 14px;text-align:center;">
              <div style="font-size:10px;font-weight:700;color:{AMBER};text-transform:uppercase;
                          letter-spacing:.5px;">Avg Days Past Due</div>
              <div style="font-size:24px;font-weight:800;color:{AMBER};">{avg_dpd:.0f}</div>
            </div>""", unsafe_allow_html=True)
        with _s3:
            st.markdown(f"""
            <div style="background:#fff8f0;border:2px solid {AMBER};border-radius:8px;
                        padding:10px 14px;text-align:center;">
              <div style="font-size:10px;font-weight:700;color:{AMBER};text-transform:uppercase;
                          letter-spacing:.5px;">Most Days Past Due</div>
              <div style="font-size:24px;font-weight:800;color:{AMBER};">{int(max_dpd)}</div>
            </div>""", unsafe_allow_html=True)
        with _s4:
            _z_color  = RED   if zero_pmts > 0 else TEAL
            _z_border = RED   if zero_pmts > 0 else TEAL
            _z_bg     = "#fff5f5" if zero_pmts > 0 else "#e8f8f7"
            st.markdown(f"""
            <div style="background:{_z_bg};border:2px solid {_z_border};border-radius:8px;
                        padding:10px 14px;text-align:center;">
              <div style="font-size:10px;font-weight:700;color:{_z_color};text-transform:uppercase;
                          letter-spacing:.5px;">0 Payments Made</div>
              <div style="font-size:24px;font-weight:800;color:{_z_color};">{zero_pmts}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

        def _fmt_date(v):
            if pd.isna(v): return "—"
            return pd.Timestamp(v).strftime("%-m/%-d/%y")

        def _dpd_color(v):
            if pd.isna(v): return "#111"
            if v >= 60: return RED
            if v >= 30: return AMBER
            return "#111"

        tbl_html = ""
        alt_i = 0  # separate counter so zero-pmt rows don't break alternation logic
        for _, row in pd_df.iterrows():
            zero_pmts = pd.notna(row["payments_made"]) and row["payments_made"] == 0
            if zero_pmts:
                bg = "#FDECEA"
            else:
                bg = "#F5F7FA" if alt_i % 2 == 0 else "white"
                alt_i += 1

            dpd = row["days_past_due"]
            dpd_color = _dpd_color(dpd)
            dpd_str   = str(int(dpd)) if pd.notna(dpd) else "—"
            pmts      = (f"{int(row['payments_made'])}/{int(row['payments_due'])}"
                         if pd.notna(row["payments_made"]) and pd.notna(row["payments_due"])
                         else "—")
            tbl_html += (
                f"<tr style='background:{bg};'>"
                f"<td style='padding:6px 10px;font-family:monospace;'>{_html.escape(str(row['loan_id']))}</td>"
                f"<td style='padding:6px 10px;'>{_fmt_date(row['origination_date'])}</td>"
                f"<td style='padding:6px 10px;font-family:monospace;'>{_html.escape(str(row['vin']))}</td>"
                f"<td style='padding:6px 10px;text-align:center;font-weight:700;color:{dpd_color};'>{dpd_str}</td>"
                f"<td style='padding:6px 10px;text-align:center;'>{pmts}</td>"
                f"<td style='padding:6px 10px;'>{_fmt_date(row['first_payment_due_date'])}</td>"
                f"</tr>"
            )

        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px;">
          <thead>
            <tr style="background:{TEAL};">
              <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Loan ID</th>
              <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">Orig. Date</th>
              <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">VIN</th>
              <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">Days Past Due</th>
              <th style="padding:7px 10px;text-align:center;color:white;font-weight:600;">Pmts Made/Due</th>
              <th style="padding:7px 10px;text-align:left;color:white;font-weight:600;">1st Pmt Due</th>
            </tr>
          </thead>
          <tbody>{tbl_html}</tbody>
        </table>
        <div style='font-size:11px;color:#888;margin-top:6px;'>
          <span style='display:inline-block;width:12px;height:12px;background:#FDECEA;
                border:1px solid #f5c6cb;border-radius:2px;vertical-align:middle;margin-right:4px;'></span>
          No payments made
        </div>
        """, unsafe_allow_html=True)

    # ── Unperfected Titles (below delinquent / past due accounts) ──────────────
    render_unperfected_section(unperfected_loans, sel_dealer)

    st.markdown("</div>", unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
from datetime import datetime
st.markdown(
    f"<div style='text-align:center;font-size:11px;color:#aaa;margin-top:12px;'>"
    f"Generated {datetime.now().strftime('%B %d, %Y')} · Confidential — For dealer use only · Upstart Auto Retail"
    f"</div>",
    unsafe_allow_html=True,
)
