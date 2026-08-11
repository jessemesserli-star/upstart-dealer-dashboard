# Implementation Pipeline Summary — Streamlit dashboard

A live, always-on version of the weekly Implementation report. Reads the **Implementation Claude**
Google Sheet through a **service account** and renders the same metrics as the Slides deck, so
anyone with the app URL can view current numbers — no dependency on anyone's laptop being on.

The weekly Google Slides deck still runs separately (see `~/Library/Application Support/ImplementationReport/`);
this app and that script share the exact same calculations via `metrics.py`.

Verified rendering locally 2026-08-11 (matches the current slide: gold Setup, 5 KPI tiles,
Pipeline by Age stacked bar, Current Quarter 3 cards + grade table).

## Files
- `metrics.py` — all the calculations (shared source of truth). No I/O; you pass it a `read_range()`.
- `app.py` — the Streamlit UI (5 KPI tiles, Pipeline by Age stacked bar, Current Quarter cards + grade table). **Deploy this one.**
- `app_local.py` — identical to app.py except it reads via the `gws` CLI instead of a service account,
  for **local preview without secrets** (`streamlit run app_local.py`). Do NOT deploy this one.
- `requirements.txt` — dependencies.

## Setup (mirror the existing DRM Streamlit app)

1. **Service account** — use the existing DRM app's service account, or create one in the Upstart GCP
   project (via go/escapevelocity infra — do not use a personal cloud account). Enable the **Google Sheets API**.
2. **Grant read access** — share the Implementation Claude sheet
   (`1PODN74TdceQOCEbVbXmA2gP9Ou10yr0ObeV5PRHNDsw`) with the service-account email as **Viewer**.
3. **Secrets** — put the service-account JSON in `st.secrets` under `gcp_service_account`
   (`.streamlit/secrets.toml` locally, or the deploy platform's secrets store):

   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "impl-dashboard@<project>.iam.gserviceaccount.com"
   client_id = "..."
   token_uri = "https://oauth2.googleapis.com/token"
   ```

4. **Run locally**
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

5. **Deploy** — drop these files into the same internal Streamlit deployment as the DRM app
   (go/escapevelocity / Upstart-owned infra) and point it at this repo/folder.

## Notes
- Data is cached for 10 minutes per view; the **↻ Refresh data** button clears the cache.
- Week-over-week deltas read the hidden **Report Snapshots** tab, which the weekly Slides job appends to.
  If the Slides job is ever retired, add a tiny scheduled writer (or have the app append a snapshot) so
  deltas keep working.
- "Key Changes" is an in-session text box (not persisted) — it's a manual narrative field.
- Keep `metrics.py` in sync with the Slides generator's logic. (Longer term: point the Slides script at
  this same `metrics.py` so there's only one copy — safe to do when the weekly run isn't imminent.)
