"""Read-only inventory of every shared spreadsheet: tabs, sizes, header candidates.
Raw values are cached to .cache/sheets/<id>/<tab>.json (git-ignored) for later steps."""
import json, os, re, sys
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly",
          "https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = service_account.Credentials.from_service_account_file(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/google-service-account.json"), scopes=SCOPES)
drive = build("drive", "v3", credentials=creds, cache_discovery=False)
sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

files = drive.files().list(q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                           fields="files(id,name)", pageSize=200).execute()["files"]
for f in files:
    meta = sheets.spreadsheets().get(spreadsheetId=f["id"],
            fields="sheets(properties(title,sheetId,hidden,gridProperties))").execute()
    print(f"\n######## {f['name']}  [{f['id']}]")
    os.makedirs(f".cache/sheets/{f['id']}", exist_ok=True)
    for s in meta["sheets"]:
        p = s["properties"]; t = p["title"]
        vals = sheets.spreadsheets().values().get(spreadsheetId=f["id"], range=f"'{t}'",
                    valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        safe = re.sub(r"[^\w.-]+", "_", t)
        json.dump(vals, open(f".cache/sheets/{f['id']}/{safe}.json", "w"))
        nonempty = [r for r in vals if any(str(c).strip() for c in r)]
        width = max((len(r) for r in vals), default=0)
        print(f"\n== tab '{t}'{' (HIDDEN)' if p.get('hidden') else ''}: {len(nonempty)} non-empty rows, {width} cols used")
        for i, r in enumerate(vals[:6]):
            print(f"   r{i+1}: {[c for c in r][:30]}")
