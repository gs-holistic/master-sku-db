"""Command line: python -m msku <command>

  migrate                 apply new migrations
  fetch                   read all Google Sheets into .cache/sources (read-only)
  import [--dry-run]      load the cached sheets into the database (--dry-run shows changes, then rolls back)
  conflicts [--all]       list open conflicts
  resolve FP VALUE [--note TEXT]   record Ken's decision for a conflict (remembered on later imports)
  preview                 build master-sku-preview.html from the database
  outputs                 read decisions from, then rewrite, the "Master SKU Database – Outputs" sheet
  sync [--dry-run]        fetch + read decisions + import + rewrite the outputs sheet (the normal routine)
  serve [--port N]        run the G Pen Hub API locally over plain HTTP (development only; see docs/HUB_API.md)
  new-api-key             print a new random key for MSKU_API_KEY
  hub-login               create (or give a new password to) the API's database login, which can't see costs,
                          and print the URL for MSKU_API_DATABASE_URL. Run with the owner's DATABASE_URL.
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
    p = sub.add_parser("outputs")
    p.add_argument("--actor", default="Ken (Outputs sheet)")
    p = sub.add_parser("sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--actor", default=os.environ.get("MSKU_ACTOR", getpass.getuser()))
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8080)
    sub.add_parser("new-api-key")
    sub.add_parser("hub-login")
    a = ap.parse_args()

    if a.cmd == "new-api-key":
        import secrets
        # 48 random bytes, URL-safe: 64 characters. Printed once; paste it straight into the host's secrets.
        print(secrets.token_urlsafe(48))
        return
    if a.cmd == "hub-login":
        print(db.hub_login(db.connect(), os.environ.get("MSKU_DATABASE_URL") or os.environ["DATABASE_URL"]))
        return
    if a.cmd == "serve":
        from wsgiref.simple_server import make_server
        from .hub_api import app
        os.environ["MSKU_ALLOW_HTTP"] = "1"
        os.environ.setdefault("MSKU_API_DATABASE_URL", "postgresql://postgres@/master_sku?host=/tmp&port=5433")
        print(f"G Pen Hub API on http://localhost:{a.port} (development only: plain HTTP)")
        make_server("127.0.0.1", a.port, app).serve_forever()
        return
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
    elif a.cmd in ("outputs", "sync"):
        from . import outputs
        if a.cmd == "sync":
            from .sheets import fetch_all
            fetch_all()
        try:
            sheet = outputs.open_output_sheet()
        except SystemExit as e:
            sheet = None
            print(f"Outputs sheet skipped: {e}")
        if sheet:
            n, problems = outputs.read_decisions(sheet, conn)
            print(f"Decisions recorded from the Conflicts tab: {n}")
            for p_ in problems:
                print("  !", p_)
        if a.cmd == "sync":
            from .consolidate import consolidate
            from .sheets import load_all
            src = load_all()
            stats = db.load(conn, consolidate(src), src, a.actor, dry_run=a.dry_run)
            print(("DRY RUN, nothing saved. " if a.dry_run else "") + json.dumps(
                {k: stats[k] for k in ("skus", "tier_moves", "prices_opened", "prices_closed", "conflicts_open", "source_fixes_open", "warnings")},
                indent=2, ensure_ascii=False))
            if a.dry_run:
                return
            if sheet:
                # On a fresh database the conflicts only exist after the import, so decisions already in the
                # sheet couldn't be matched above. Read them again before the tab is rewritten, then apply them.
                n, problems = outputs.read_decisions(sheet, conn)
                if n:
                    print(f"Decisions recovered from the sheet after import: {n}")
                    db.load(conn, consolidate(src), src, a.actor)
        if sheet:
            print("Outputs sheet updated:", outputs.write_all(sheet, conn))


if __name__ == "__main__":
    main()
