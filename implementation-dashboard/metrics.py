"""Shared metric computation for the Implementation Pipeline report.

Pure Python — no I/O of its own. Pass a `read_range(a1_range) -> list[list]` function
(service-account Sheets reader for the app; gws CLI reader for the Slides script), so the
exact same numbers power both the weekly Google Slides deck and the Streamlit dashboard.
"""
import datetime, statistics

SPREADSHEET_ID = "1PODN74TdceQOCEbVbXmA2gP9Ou10yr0ObeV5PRHNDsw"

# Source status was renamed "On Hold" -> "Blocked" (2026-07); match both, display "Blocked".
BLOCKED_STATUSES = {"Blocked", "On Hold"}
STATUS_MAP = {"Setup": "Setup in Progress", "Handoff": "Setup in Progress", "Validation": "Setup in Progress",
              "Launch Ready": "Launch Ready", "Launch Scheduled": "Launch Scheduled",
              "Blocked": "Blocked", "On Hold": "Blocked"}
STATUS_ORDER = ["Setup in Progress", "Launch Ready", "Launch Scheduled", "Blocked"]

def pdate(s):
    s = str(s or "").strip()
    if not s:
        return None
    for f in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None

def rows_as_dicts(values):
    if not values:
        return []
    h = values[0]
    return [{h[i]: (r[i] if i < len(r) else "") for i in range(len(h))}
            for r in values[1:] if any(str(c).strip() for c in r)]

def grade_group(g):
    return "A & B" if str(g or "").strip().upper() in ("A", "B") else "C & No Grade"

def q_range(y, q):
    m0 = (q - 1) * 3 + 1
    start = datetime.date(y, m0, 1)
    end = datetime.date(y + 1, 1, 1) if q == 4 else datetime.date(y, m0 + 3, 1)
    return start, end

def compute(read_range, today=None):
    """Return the full metrics dict. `read_range(a1)` returns a sheet's raw values (list of rows)."""
    if today is None:
        today = datetime.date.today()
    impl = rows_as_dicts(read_range("Implementation!A1:W1000"))
    launch = rows_as_dicts(read_range("Launch!A1:N2000"))

    total = len(impl)
    blocked = sum(1 for r in impl if str(r.get("Implementation Status", "")).strip() in BLOCKED_STATUSES)
    unblocked = total - blocked

    buckets = {}
    for b in ["0-14", "15-29", "30+"]:
        br = [r for r in impl if str(r.get("Age Backlog Bucket", "")).strip() == b]
        counts = {k: 0 for k in STATUS_ORDER}
        for r in br:
            g = STATUS_MAP.get(str(r.get("Implementation Status", "")).strip())
            if g:
                counts[g] += 1
        buckets[b] = {"count": len(br), "counts": counts}

    LC = "Account: Launch Date - Lending"; CR = "Implementation: Created Date"; LR = "Launch Ready Date"
    def days_to_lr(r):
        c = pdate(r.get(CR)); l = pdate(r.get(LR))
        return (l - c).days if (c and l) else None

    q = (today.year, (today.month - 1) // 3 + 1)
    qs, _ = q_range(*q)
    pq = (today.year, q[1] - 1) if q[1] > 1 else (today.year - 1, 4)
    ps, pe = q_range(*pq)
    launches_qtd = sum(1 for r in launch if pdate(r.get(LC)) and qs <= pdate(r[LC]) <= today)
    launches_prevq = sum(1 for r in launch if pdate(r.get(LC)) and ps <= pdate(r[LC]) < pe)

    def avg30(a, b):
        v = [days_to_lr(r) for r in launch if pdate(r.get(LC)) and a <= pdate(r[LC]) <= b]
        v = [x for x in v if x is not None]
        return round(sum(v) / len(v), 1) if v else None
    avg_30d = avg30(today - datetime.timedelta(days=30), today)
    avg_prev30 = avg30(today - datetime.timedelta(days=60), today - datetime.timedelta(days=31))

    # launch-ready panel windows (Mon-Sun, most recent completed week)
    this_monday = today - datetime.timedelta(days=today.weekday())
    tw_end = this_monday - datetime.timedelta(days=1); tw_start = tw_end - datetime.timedelta(days=6)
    pw_end = tw_start - datetime.timedelta(days=1); pw_start = pw_end - datetime.timedelta(days=6)
    recs = impl + launch
    def lr_window(s, e):
        ab = c = tot = 0; dd = []
        for r in recs:
            d = pdate(r.get(LR))
            if d and s <= d <= e:
                tot += 1
                if grade_group(r.get("Account Grade")) == "A & B": ab += 1
                else: c += 1
                x = days_to_lr(r)
                if x is not None: dd.append(x)
        med = round(statistics.median(dd)) if dd else None
        return {"ab": ab, "c": c, "total": tot, "med": med}
    tw = lr_window(tw_start, tw_end); pw = lr_window(pw_start, pw_end)

    # projected launches this (current) calendar week, by grade:
    # in-pipeline accounts with Projected Launch Date in the current week + accounts already launched this week
    cw_start = this_monday; cw_end = this_monday + datetime.timedelta(days=6)
    def proj_cw():
        ab = c = 0
        for r in impl:
            d = pdate(r.get("Projected Launch Date"))
            if d and cw_start <= d <= cw_end:
                if grade_group(r.get("Account Grade")) == "A & B": ab += 1
                else: c += 1
        for r in launch:
            d = pdate(r.get(LC))
            if d and cw_start <= d <= cw_end:
                if grade_group(r.get("Account Grade")) == "A & B": ab += 1
                else: c += 1
        return {"ab": ab, "c": c, "total": ab + c}
    proj = proj_cw()

    # current-quarter launch-ready accounts (user-maintained "CQ Launch Ready" tab)
    cq = rows_as_dicts(read_range("CQ Launch Ready!A1:Q1000"))
    cq_lr = [r for r in cq if pdate(r.get("Launch Ready Date"))]
    cq_days = []
    for r in cq_lr:
        try: cq_days.append(float(r.get("Days to Launch Ready")))
        except (TypeError, ValueError): pass
    cq_count = len(cq_lr)
    cq_med = round(statistics.median(cq_days)) if cq_days else None
    # implementations created this quarter (user-maintained "Imp Created CQ" tab)
    imp_cq = rows_as_dicts(read_range("Imp Created CQ!A1:Q1000"))
    cq_new = sum(1 for r in imp_cq if str(r.get("Implementation: Implementation Name", "")).strip())

    # preceding 4 completed calendar weeks (Mon-Sun), by launch date
    fw_cur_end = this_monday - datetime.timedelta(days=1)
    fw_cur_start = fw_cur_end - datetime.timedelta(days=27)
    fw_prev_end = fw_cur_start - datetime.timedelta(days=1)
    fw_prev_start = fw_prev_end - datetime.timedelta(days=27)
    SI = "Were there setup issues?"   # Launch tab col N — Yes/No/blank (replaced numeric score 2026-08-10)
    def win_metrics(s, e):
        c = [r for r in launch if pdate(r.get(LC)) and s <= pdate(r[LC]) <= e]
        ttlr = [x for x in (days_to_lr(r) for r in c) if x is not None]
        median = statistics.median(ttlr) if ttlr else None
        over30 = (100.0 * sum(1 for x in ttlr if x > 30) / len(ttlr)) if ttlr else None
        n_yes = sum(1 for r in c if str(r.get(SI, "")).strip().lower() == "yes")
        n_ans = sum(1 for r in c if str(r.get(SI, "")).strip() != "")
        # % with setup issue = "Yes" over ALL launches in window (blank = no issue; Salesforce "1 of N")
        issues = (100.0 * n_yes / len(c)) if c else None
        return {"median": median, "over30": over30, "issues": issues,
                "n": len(c), "n_ttlr": len(ttlr), "n_yes": n_yes, "n_ans": n_ans}
    fwk_cur = win_metrics(fw_cur_start, fw_cur_end)
    fwk_prev = win_metrics(fw_prev_start, fw_prev_end)

    # previous snapshot (for week-over-week deltas)
    snap = read_range("Report Snapshots!A2:I2000")
    prev = None
    for row in snap:
        d = pdate(row[0]) if row else None
        if d and d < today:
            if prev is None or d > prev["date"]:
                def gi(i):
                    try: return int(row[i]) if str(row[i]).strip() != "" else None
                    except (ValueError, IndexError): return None
                prev = {"date": d, "total": gi(1), "unblocked": gi(2), "blocked": gi(3),
                        "b0": gi(4), "b1": gi(5), "b2": gi(6)}

    return dict(today=today, total=total, blocked=blocked, unblocked=unblocked, buckets=buckets,
                launches_qtd=launches_qtd, launches_prevq=launches_prevq, avg_30d=avg_30d, avg_prev30=avg_prev30,
                tw=tw, pw=pw, tw_start=tw_start, tw_end=tw_end, pw_start=pw_start, prev=prev,
                fwk_cur=fwk_cur, fwk_prev=fwk_prev, fw_start=fw_cur_start, fw_end=fw_cur_end,
                cq_count=cq_count, cq_med=cq_med, cq_new=cq_new, proj=proj)
