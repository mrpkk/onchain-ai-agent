"""Attack 3 — the runaway loop: 41 000 correct payments over one weekend.

Every single payment is valid and signed. The bug is pagination in the agent's
tool wrapper: it keeps requesting the same pages. A per-call limit never notices.
The task envelope does — the budget belongs to the task, not to the call.

Run:  python attacks/runaway_loop.py
Exit: 0 if the loop stopped at the boundary, 1 if it overspent.
"""

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("KARTA_LEDGER_DB",
                      str(Path(tempfile.mkdtemp(prefix="karta-attack-")) / "ledger.db"))

from src.security import ledger  # noqa: E402


def main() -> int:
    ledger.init()
    envelope = ledger.create(budget_total=Decimal("100"), per_call_max=Decimal("0.05"),
                             calls_max=2000, allowlist=("api.marketdata.example",),
                             ttl_hours=1)
    eid = envelope["envelope_id"]

    allowed = blocked = 0
    for _ in range(41000):
        verdict, _receipt = ledger.reserve(eid, amount=Decimal("0.05"),
                                           payee="api.marketdata.example")
        if verdict.verdict == "ALLOW":
            allowed += 1
        else:
            blocked += 1
            if blocked == 1:
                print(f"first refusal at call #{allowed + 1}: {verdict.rule} — {verdict.counterfactual}")

    state = ledger.get(eid)
    print(f"allowed: {allowed}  blocked: {blocked}  spent: {state['spent']}  remaining: {state['remaining']}")

    if Decimal(state["spent"]) == Decimal("100") and Decimal(state["remaining"]) == 0:
        print("RESULT: the loop stopped at the task boundary — no cent above the envelope.")
        return 0
    print("RESULT: FAILED — the task overspent its envelope.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
