"""Command line: python -m msku <command>

  migrate                 apply new migrations
  fetch                   read all Google Sheets into .cache/sources (read-only)
  import [--dry-run]      load the cached sheets into the database (--dry-run shows changes, then rolls back)
  conflicts [--all]       list open conflicts
  resolve FP VALUE [--note TEXT]   record Ken's decision for a conflict (remembered on later imports)
  preview                 build master-sku-preview.html from the database
"""
import argparse
import getpass
import json
import os

from . import db


def main():
    ap = argparse.ArgumentParser(prog="msku")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("fetch")
    p = sub.add_parser("import")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--actor", default=os.environ.get("MSKU_ACTOR", getpass.getuser()))
    p = sub.add_parser("conflicts")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("resolve")
    p.add_argument("fingerprint")
    p.add_argument("value")
    p.add_argument("--note")
    p.add_argument("--actor", default=os.environ.get("MSKU_ACTOR", getpass.getuser()))
    sub.add_parser("preview")
    a = ap.parse_args()

    if a.cmd == "fetch":
        from .sheets import fetch_all
        fetch_all()
        return
    conn = db.connect()
    if a.cmd == "migrate":
        print("applied:", db.migrate(conn) or "nothing new")
    elif a.cmd == "import":
        from .consolidate import consolidate
        from .sheets import load_all
        src = load_all()
        stats = db.load(conn, consolidate(src), src, a.actor, dry_run=a.dry_run)
        print(("DRY RUN, nothing saved. " if a.dry_run else "") + json.dumps(stats, indent=2, ensure_ascii=False))
    elif a.cmd == "conflicts":
        q = "SELECT fingerprint, status, detail, candidates FROM ops.conflict"
        q += "" if a.all else " WHERE status IN ('open','reopened')"
        for fp, status, detail, cands in conn.execute(q + " ORDER BY fingerprint"):
            print(f"{fp}  [{status}]  {detail}")
            for c in cands:
                print(f"      {c['value']:<14} {c['source']} {c.get('ref', '')}")
    elif a.cmd == "resolve":
        db.resolve(conn, a.fingerprint, a.value, a.actor, a.note)
        print(f"Recorded. Run `python -m msku import` to apply it.")
    elif a.cmd == "preview":
        from .preview import build
        build(conn)


if __name__ == "__main__":
    main()
