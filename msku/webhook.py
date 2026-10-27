"""Tell the G Pen Hub which SKUs changed, so an edit shows up in both places straight away.

One POST per write: a Hub POST/PATCH, or a whole sheet sync. Fire and forget: a 5-second timeout, and a failure is
only logged, never raised. The Hub also re-checks every 15 minutes.

  HUB_WEBHOOK_KEY  the Hub's key, sent as x-api-key. Unset = no ping (local runs, throwaway databases)
  HUB_WEBHOOK_URL  optional, defaults to the Hub's endpoint below
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

URL = "https://gpen-crm.vercel.app/api/master-sku/changed"
log = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def notify(skus, changed_at=None):
    """POST {"skus": [...], "changed_at": ...} to the Hub. Returns True if the Hub answered 2xx."""
    key = os.environ.get("HUB_WEBHOOK_KEY", "").strip()
    skus = sorted(set(skus))
    if not key or not skus:
        return False
    req = urllib.request.Request(
        os.environ.get("HUB_WEBHOOK_URL") or URL, method="POST",
        data=json.dumps({"skus": skus, "changed_at": changed_at or now_iso()}).encode(),
        headers={"Content-Type": "application/json", "x-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return 200 <= r.status < 300
    except Exception as e:   # the write already succeeded; the Hub's 15-minute check catches up
        log.warning("Hub ping failed for %d SKU(s): %s", len(skus), type(e).__name__)
        return False
