"""List every Google Sheet shared with the service account (read-only)."""
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly",
          "https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = service_account.Credentials.from_service_account_file(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/google-service-account.json"), scopes=SCOPES)
drive = build("drive", "v3", credentials=creds, cache_discovery=False)
token = None
n = 0
while True:
    r = drive.files().list(q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                           fields="nextPageToken, files(id,name,modifiedTime,owners(emailAddress))",
                           pageSize=200, pageToken=token, supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    for f in r.get("files", []):
        n += 1
        owner = ",".join(o["emailAddress"] for o in f.get("owners", []))
        print(f"{f['id']}\t{f['modifiedTime'][:10]}\t{owner}\t{f['name']}")
    token = r.get("nextPageToken")
    if not token:
        break
print(f"-- {n} spreadsheet(s) visible")
