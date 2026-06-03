"""
Run this ONCE to add Gmail send permission to your Google credentials.
It will open a browser window for you to approve the permission, then save the
updated token back to drive_token.json.

Usage:
    python3 setup_gmail_auth.py
"""
import json, os, warnings
warnings.filterwarnings("ignore")

from google_auth_oauthlib.flow import InstalledAppFlow

TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "DRM Reporting", "drive_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]

print(f"Reading credentials from:\n  {TOKEN_FILE}\n")
with open(TOKEN_FILE) as f:
    existing = json.load(f)

client_config = {
    "installed": {
        "client_id":     existing["client_id"],
        "client_secret": existing["client_secret"],
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     existing.get("token_uri", "https://oauth2.googleapis.com/token"),
        "redirect_uris": ["http://localhost"],
    }
}

print("Opening browser for Google sign-in…")
print("Sign in with the Upstart account that owns the Drive folder.\n")

flow  = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

new_token = {
    "token":         creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri":     creds.token_uri,
    "client_id":     creds.client_id,
    "client_secret": creds.client_secret,
    "scopes":        list(creds.scopes) if creds.scopes else SCOPES,
}

with open(TOKEN_FILE, "w") as f:
    json.dump(new_token, f, indent=2)

print("✅  Done! Gmail send permission added.")
print("    You can now use 'Send Report to Dealer' in the dashboard.")
