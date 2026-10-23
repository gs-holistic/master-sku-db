"""Write-back and decision read-back, using a fake Sheets client and a throwaway database."""
import pytest

from msku import db, outputs
from msku.consolidate import consolidate
from tests.fixtures import sources
from tests.test_db import conn, run  # noqa: F401  (fixture)


class FakeSheet:
    def __init__(self):
        self.data, self.props, self.requests, self.next_id = {}, {}, [], 1

    def tabs(self):
        return dict(self.props)

    def read(self, tab):
        return [list(r) for r in self.data.get(tab, [])]

    def write(self, tab, rows):
        self.data[tab] = [list(r) for r in rows]

    def batch(self, requests):
        replies = []
        for r in requests:
            self.requests.append(r)
            if "addSheet" in r:
                t = r["addSheet"]["properties"]["title"]
                self.props[t] = {"sheetId": self.next_id, "title": t}
                self.next_id += 1
            elif "duplicateSheet" in r:
                src = next(t for t, p in self.props.items() if p["sheetId"] == r["duplicateSheet"]["sourceSheetId"])
                t = r["duplicateSheet"]["newSheetName"]
                if t in self.props:
                    raise ValueError(f"A sheet with the name {t!r} already exists")   # like the real API
                self.props[t] = {"sheetId": self.next_id, "title": t}
                self.data[t] = self.read(src)
                replies.append({"duplicateSheet": {"properties": self.props[t]}})
                self.next_id += 1
            elif "deleteSheet" in r:
                t = next(t for t, p in self.props.items() if p["sheetId"] == r["deleteSheet"]["sheetId"])
                del self.props[t]
                self.data.pop(t, None)
        return {"replies": replies}


def test_refuses_source_sheets():
    with pytest.raises(SystemExit):
        outputs.check_target("1vMuhrqFVbgF_sgQGQIpfr_BtQPoeTsxJzEHYZSPEqik")


def test_write_has_no_costs(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    outputs.write_all(sheet, conn)
    assert set(sheet.data) >= {outputs.TAB_README, outputs.TAB_SKUS, outputs.TAB_CONFLICTS, outputs.TAB_FIXES}
    text = repr(sheet.data).lower()
    assert "cost" not in repr(sheet.data[outputs.TAB_SKUS][0]).lower()
    assert "13.37" not in text and "12.34" not in text and "16.58" not in text   # fixture costs never leak


def test_price_list_wins_goes_to_fix_list(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    outputs.write_all(sheet, conn)
    fixes = sheet.data[outputs.TAB_FIXES]
    assert any(r[0] == "GPM-001-APZZ" and r[2] == "Cin7" and r[1] == "US distribution" for r in fixes[1:])
    keys = [r[outputs.COL_KEY] for r in sheet.data[outputs.TAB_CONFLICTS][1:]]
    assert "GPM-001-APZZ|price_US_distribution" not in keys     # not a conflict any more
    assert "SG4-KIT-STGR-02|price_US_msrp" not in keys          # master MSRP loses to the price list


def test_decision_round_trip_and_backup(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    outputs.write_all(sheet, conn)
    rows = sheet.data[outputs.TAB_CONFLICTS]
    i = next(i for i, r in enumerate(rows) if r[outputs.COL_KEY] == "GPM-001-APZZ|upc")
    rows[i][outputs.COL_DECISION] = "811736020343"
    rows[i][outputs.COL_NOTE] = "UPC on the box"
    n, problems = outputs.read_decisions(sheet, conn)
    assert (n, problems) == (1, [])
    run(conn, sources())
    assert conn.execute("SELECT upc FROM core.sku WHERE code = 'GPM-001-APZZ'").fetchone()[0] == "811736020343"
    assert conn.execute("SELECT note FROM ops.conflict_resolution WHERE fingerprint = 'GPM-001-APZZ|upc'").fetchone()[0] == "UPC on the box"
    outputs.write_all(sheet, conn)
    assert any(t.startswith("Backup Conflicts") for t in sheet.data)          # previous version kept
    row = next(r for r in sheet.data[outputs.TAB_CONFLICTS] if r[outputs.COL_KEY] == "GPM-001-APZZ|upc")
    assert row[outputs.COL_DECISION] == "811736020343" and row[6] == "Decided"
    assert outputs.read_decisions(sheet, conn) == (0, [])                     # nothing new to record


def test_bad_decisions_are_reported_not_applied(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    outputs.write_all(sheet, conn)
    rows = sheet.data[outputs.TAB_CONFLICTS]
    i = next(i for i, r in enumerate(rows) if r[outputs.COL_KEY] == "GPM-001-APZZ|upc")
    rows[i][outputs.COL_DECISION] = "the old one"
    n, problems = outputs.read_decisions(sheet, conn)
    assert n == 0 and "UPC" in problems[0]
    rows[i][outputs.COL_DECISION] = "811736020343"
    rows[i][outputs.COL_HASH] = "stale"
    n, problems = outputs.read_decisions(sheet, conn)
    assert n == 0 and "sources changed" in problems[0]


def test_backups_are_capped(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    import time
    for k in range(5):
        outputs.write_all(sheet, conn)
        # distinct timestamps without waiting a minute
        for t in [t for t in list(sheet.props) if t.startswith("Backup") and t.endswith("UTC")]:
            sheet.props[t + f" #{k}"] = sheet.props.pop(t)
            sheet.data[t + f" #{k}"] = sheet.data.pop(t)
    assert sum(t.startswith("Backup Conflicts") for t in sheet.props) <= outputs.BACKUPS_KEPT + 1


def test_normalise_decision():
    assert outputs.normalise_decision("Price · US msrp", "$449.95") == ("449.95", None)
    assert outputs.normalise_decision("Price · US msrp", "abc")[1]
    assert outputs.normalise_decision("UPC", "0811736020343") == ("0811736020343", None)
    assert outputs.normalise_decision("Status", "Keep on price list") == ("Keep on price list", None)


def test_two_syncs_in_the_same_minute(conn):  # noqa: F811
    run(conn, sources())
    sheet = FakeSheet()
    for _ in range(3):
        outputs.write_all(sheet, conn)     # same minute each time; the fake rejects duplicate names
    backups = [t for t in sheet.props if t.startswith("Backup Conflicts")]
    assert len(backups) == len(set(backups)) >= 2
