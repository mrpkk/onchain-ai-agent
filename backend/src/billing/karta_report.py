"""Выдача отчёта KARTA за $19: HTML, PDF, JSON и письмо.

Зачем отдельным модулем: отчёт — товар, у него своя судьба. Он должен
собираться из того же снимка реестра, что описан в `docs/REPORT-AGENT-SPEND-2026.md`,
быть воспроизводимым (один вход — один и тот же отчёт) и уходить покупателю
без человека в цепочке.

    python3 backend/src/billing/karta_report.py --snapshot scripts/registry_snapshot.json \
        --out /tmp/karta --email buyer@example.com [--send]

Без `--send` письмо не отправляется: файлы собираются и путь печатается.
Сеть нужна только для отправки; тесты работают на фикстурах.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Метод ровно тот, что в приложении к docs/REPORT-AGENT-SPEND-2026.md:
# продукт обещает «72 сервера / 11 бюджетов», и отчёт обязан считаться так же,
# иначе покупатель получит другие числа, чем на странице.
MONEY = re.compile(r"x402|usdc|stablecoin|agent wallet|wallets?\b|agent payments|"
                   r"payment rail|on-?chain payment|lightning|l402|billing|invoice")
BUDGET = re.compile(r"budget")
LIMIT = re.compile(r"\blimit|\bcaps?\b")
KILL = re.compile(r"kill[- ]switch|emergency stop")
RECEIPT = re.compile(r"receipt")
AUDIT = re.compile(r"audit")


def classify(server: dict) -> dict | None:
    """Один сервер → строка отчёта, либо None, если деньги он не двигает."""
    text = ((server.get("description") or "") + " " + (server.get("title") or "")).lower()
    if not MONEY.search(text):
        return None
    return {
        "name": server.get("name") or server.get("title") or "—",
        "title": server.get("title") or "",
        "budget": bool(BUDGET.search(text)),
        "limit": bool(LIMIT.search(text)),
        "kill_switch": bool(KILL.search(text)),
        "receipt": bool(RECEIPT.search(text)),
        "audit": bool(AUDIT.search(text)),
    }


def build_report(snapshot: list[dict], taken_on: str | None = None) -> dict:
    rows = [r for r in (classify(s) for s in snapshot) if r]
    counts = {
        "servers": len(rows),
        "sample": len(snapshot),
        "budget": sum(r["budget"] for r in rows),
        "limit": sum(r["limit"] for r in rows),
        "kill_switch": sum(r["kill_switch"] for r in rows),
        "receipt": sum(r["receipt"] for r in rows),
        "audit": sum(r["audit"] for r in rows),
    }
    return {
        "title": "KARTA — who can spend without a ceiling",
        "taken_on": taken_on or datetime.now(timezone.utc).date().isoformat(),
        "source": "registry.modelcontextprotocol.io/v0/servers (snapshot)",
        "counts": counts,
        "servers": sorted(rows, key=lambda r: r["name"].lower()),
    }


def render_html(report: dict) -> str:
    c = report["counts"]
    rows = "\n".join(
        "<tr>"
        f"<td>{r['name']}</td>"
        f"<td>{'да' if r['budget'] else '—'}</td>"
        f"<td>{'да' if r['limit'] else '—'}</td>"
        f"<td class=\"{'' if r['kill_switch'] else 'bad'}\">{'да' if r['kill_switch'] else 'НЕТ'}</td>"
        f"<td>{'да' if r['receipt'] else '—'}</td>"
        f"<td>{'да' if r['audit'] else '—'}</td>"
        "</tr>" for r in report["servers"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{report['title']}</title>
<style>
 body{{margin:0;background:#f7f9fc;color:#14263c;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}}
 main{{max-width:860px;margin:0 auto;padding:36px 20px 60px}}
 h1{{font-size:30px;line-height:1.15;margin:0 0 6px}}
 .s{{color:#6d7c91}} .k{{display:inline-block;border:1px solid #e3e9f2;border-radius:10px;padding:8px 12px;margin:4px 6px 4px 0;background:#fff}}
 .k b{{font-size:20px;display:block}}
 table{{width:100%;border-collapse:collapse;margin-top:18px;background:#fff}}
 th,td{{border-bottom:1px solid #e3e9f2;padding:7px 9px;text-align:left;font-size:13px}}
 th{{background:#eef3f9;font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
 .bad{{color:#c02a2a;font-weight:700}}
 footer{{margin-top:26px;border-top:1px solid #e3e9f2;padding-top:12px;font-size:12px;color:#6d7c91}}
</style></head><body><main>
<h1>{report['title']}</h1>
<p class="s">Snapshot {report['taken_on']} · source: {report['source']}</p>
<div>
 <span class="k"><b>{c['servers']}</b>money-moving servers</span>
 <span class="k"><b>{c['sample']}</b>servers in sample</span>
 <span class="k"><b>{c['budget']}</b>mention a budget</span>
 <span class="k"><b>{c['limit']}</b>mention a limit</span>
 <span class="k"><b>{c['kill_switch']}</b>mention a kill switch</span>
 <span class="k"><b>{c['receipt']}</b>receipt</span>
 <span class="k"><b>{c['audit']}</b>audit trail</span>
</div>
<table><thead><tr><th>server</th><th>budget</th><th>limit</th><th>kill switch</th><th>receipt</th><th>audit</th></tr></thead>
<tbody>{rows}</tbody></table>
<footer>KARTA · report generated {report['taken_on']} · method: keyword analysis of public title/description,
same filter as docs/REPORT-AGENT-SPEND-2026.md. Numbers are a snapshot, not a live claim.</footer>
</main></body></html>"""


def render_pdf(report: dict, path: Path) -> Path:
    """PDF без сети и без шрифтовых сюрпризов: reportlab, таблица + шапка."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    c = report["counts"]
    story = [Paragraph(report["title"], st["Title"]),
             Paragraph(f"Snapshot {report['taken_on']} · {report['source']}", st["Normal"]),
             Spacer(1, 10),
             Paragraph(f"{c['servers']} money-moving servers of {c['sample']}; "
                       f"budget {c['budget']}, limit {c['limit']}, kill switch {c['kill_switch']}, "
                       f"receipt {c['receipt']}, audit {c['audit']}.", st["Normal"]),
             Spacer(1, 12)]
    data = [["server", "budget", "limit", "kill", "receipt", "audit"]]
    for r in report["servers"]:
        data.append([r["name"][:58], "y" if r["budget"] else "-", "y" if r["limit"] else "-",
                     "y" if r["kill_switch"] else "NO", "y" if r["receipt"] else "-",
                     "y" if r["audit"] else "-"])
    table = Table(data, repeatRows=1, colWidths=[210, 55, 50, 50, 55, 50])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f9")),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e9f2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=report["title"])
    doc.build(story)
    return path


def write_artifacts(report: dict, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / "karta-report.html"
    js = out_dir / "karta-report.json"
    pdf = out_dir / "karta-report.pdf"
    html.write_text(render_html(report), encoding="utf-8")
    js.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    render_pdf(report, pdf)
    return {"html": html, "json": js, "pdf": pdf}


def _creds() -> tuple[str, str]:
    """Логин и app password из ~/.env: EMAIL + MYACCOUNT_GOOGLE (как в остальных выдачах)."""
    env: dict[str, str] = {}
    path = Path.home() / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r'^([A-Z0-9_]+)=["\']?([^"\'\n]*)', line)
            if m:
                env[m.group(1)] = m.group(2).strip()
    return env.get("EMAIL", ""), env.get("MYACCOUNT_GOOGLE", "")


def send_report(to: str, files: dict[str, Path], report: dict, smtp_factory=None) -> tuple[bool, str]:
    """(отправлено, причина). Без кредов или сети — честный False, файлы уже на диске."""
    user, password = _creds()
    if not user or not password:
        return False, "smtp_credentials_missing"
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = "KARTA report — 72 servers that move money"
    c = report["counts"]
    msg.set_content(
        f"Your KARTA report is attached (PDF, HTML, JSON).\n\n"
        f"{c['servers']} money-moving servers of {c['sample']}; kill switch mentioned {c['kill_switch']}, "
        f"budget {c['budget']}, limit {c['limit']}.\n\n"
        f"Snapshot {report['taken_on']}. One round of questions by email is included.\n")
    for name, p in files.items():
        maintype = "application" if name == "pdf" else ("text/html" if name == "html" else "application")
        subtype = {"pdf": "pdf", "html": "html", "json": "json"}[name]
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    try:
        factory = smtp_factory or (lambda: smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                                                           context=ssl.create_default_context(),
                                                           timeout=20))
        with factory() as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:
        return False, f"smtp_error: {exc.__class__.__name__}"


def deliver(snapshot_path: Path, out_dir: Path, email: str = "", send: bool = False,
            smtp_factory=None) -> dict:
    snapshot = json.loads(Path(snapshot_path).read_text())
    report = build_report(snapshot)
    files = write_artifacts(report, Path(out_dir))
    result = {"counts": report["counts"], "files": {k: str(v) for k, v in files.items()},
              "emailed": False, "email_reason": "not_requested"}
    if send and email:
        ok, reason = send_report(email, files, report, smtp_factory=smtp_factory)
        result["emailed"], result["email_reason"] = ok, reason
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Собрать и (по флагу) отправить отчёт KARTA")
    ap.add_argument("--snapshot", default="scripts/registry_snapshot.json")
    ap.add_argument("--out", default="/tmp/karta-report")
    ap.add_argument("--email", default="")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    res = deliver(Path(a.snapshot), Path(a.out), email=a.email, send=a.send)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
