"""Тесты выдачи отчёта KARTA: классификация, HTML/PDF/JSON, письмо без сети."""

from __future__ import annotations

import json

from src.billing import karta_report as kr

SNAPSHOT = [
    {"name": "a/pay", "title": "Payments", "description": "Send USDC payments with a budget per task"},
    {"name": "b/wallet", "title": "Wallet", "description": "Read wallet balances only"},
    {"name": "c/weather", "title": "Weather", "description": "Forecast and temperature"},
    {"name": "d/x402", "title": "x402 buyer", "description": "Pay per call with a daily limit"},
    {"name": "e/invoice", "title": "", "description": "Invoice with audit trail and receipt"},
]


def test_classify_keeps_only_money_servers():
    rows = [r for r in (kr.classify(s) for s in SNAPSHOT) if r]
    names = [r["name"] for r in rows]
    assert "c/weather" not in names, names
    assert set(names) == {"a/pay", "b/wallet", "d/x402", "e/invoice"}, names


def test_flags_are_read_from_text():
    by = {s["name"]: kr.classify(s) for s in SNAPSHOT}
    assert by["a/pay"]["budget"] is True
    assert by["d/x402"]["limit"] is True
    assert by["d/x402"]["kill_switch"] is False
    assert by["e/invoice"]["audit"] is True and by["e/invoice"]["receipt"] is True


def test_matches_published_numbers_on_real_snapshot():
    """Метод из docs/REPORT-AGENT-SPEND-2026.md: 72 сервера, 11 бюджетов, 0 kill switch."""
    from pathlib import Path
    snap_path = Path(__file__).resolve().parents[2] / "scripts" / "registry_snapshot.json"
    if not snap_path.exists():
        import pytest
        pytest.skip("нет снимка реестра")
    rep = kr.build_report(json.loads(snap_path.read_text()))
    c = rep["counts"]
    assert c["sample"] == 2500, c
    assert c["servers"] == 72 and c["budget"] == 11, c
    assert c["kill_switch"] == 0 and c["audit"] == 0, c


def test_report_counts():
    rep = kr.build_report(SNAPSHOT, taken_on="2026-11-20")
    c = rep["counts"]
    assert c["sample"] == 5 and c["servers"] == 4
    assert c["budget"] == 1 and c["limit"] == 1 and c["kill_switch"] == 0
    assert rep["taken_on"] == "2026-11-20"
    assert [r["name"] for r in rep["servers"]] == sorted(
        ["a/pay", "b/wallet", "d/x402", "e/invoice"])


def test_artifacts_are_written_and_pdf_is_real(tmp_path):
    rep = kr.build_report(SNAPSHOT, taken_on="2026-11-20")
    files = kr.write_artifacts(rep, tmp_path)
    assert all(p.exists() and p.stat().st_size > 500 for p in files.values())
    assert files["pdf"].read_bytes()[:5] == b"%PDF-"
    html = files["html"].read_text(encoding="utf-8")
    assert "kill switch" in html.lower() and "a/pay" in html
    assert json.loads(files["json"].read_text())["counts"]["servers"] == 4


def test_send_without_credentials_is_honest_false(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_creds", lambda: ("", ""))
    rep = kr.build_report(SNAPSHOT, taken_on="2026-11-20")
    files = kr.write_artifacts(rep, tmp_path)
    ok, reason = kr.send_report("buyer@example.com", files, rep)
    assert ok is False and reason == "smtp_credentials_missing"


class FakeSMTP:
    def __init__(self):
        self.logged_in = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent = msg


def test_send_attaches_three_files(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_creds", lambda: ("me@example.com", "pw"))
    fake = FakeSMTP()
    rep = kr.build_report(SNAPSHOT, taken_on="2026-11-20")
    files = kr.write_artifacts(rep, tmp_path)
    ok, reason = kr.send_report("buyer@example.com", files, rep, smtp_factory=lambda: fake)
    assert ok is True and reason == ""
    assert fake.logged_in == ("me@example.com", "pw")
    names = {part.get_filename() for part in fake.sent.iter_attachments()}
    assert names == {"karta-report.pdf", "karta-report.html", "karta-report.json"}
    assert fake.sent["Subject"].startswith("KARTA report")


def test_deliver_writes_files_and_skips_email_by_default(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT))
    res = kr.deliver(snap, tmp_path / "out", email="buyer@example.com")
    assert res["emailed"] is False and res["email_reason"] == "not_requested"
    assert (tmp_path / "out" / "karta-report.pdf").exists()
