"""Read Google Sheets (read-only scopes) into a local cache: .cache/sources/<key>.json."""
import json
import os
from datetime import date

from . import mapping_rules as R

CACHE = ".cache/sources"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def fetch_all(keys=None):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/google-service-account.json"), scopes=SCOPES)
    api = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
    os.makedirs(CACHE, exist_ok=True)
    for key, (sid, _) in R.SPREADSHEETS.items():
        if keys and key not in keys:
            continue
        meta = api.get(spreadsheetId=sid, fields="properties(title),sheets(properties(title))").execute()
        titles = [s["properties"]["title"] for s in meta["sheets"]]
        ranges = api.values().batchGet(spreadsheetId=sid, ranges=[f"'{t}'" for t in titles]).execute()["valueRanges"]
        doc = {"key": key, "id": sid, "name": meta["properties"]["title"], "read_at": date.today().isoformat(),
               "tabs": {t: r.get("values", []) for t, r in zip(titles, ranges)}}
        json.dump(doc, open(f"{CACHE}/{key}.json", "w"), ensure_ascii=False)
        print(f"fetched {doc['name']}: {len(titles)} tabs")


def load_all():
    out = {}
    for key in R.SPREADSHEETS:
        path = f"{CACHE}/{key}.json"
        if not os.path.exists(path):
            raise SystemExit(f"Missing {path}. Run: python -m msku fetch")
        out[key] = json.load(open(path))
    return out
