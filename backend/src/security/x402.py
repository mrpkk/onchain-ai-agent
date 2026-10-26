"""x402-guard (S4): платить только внутри конверта задачи.

x402 отвечает на вопрос «можно ли проверить платёж». Наш слой отвечает на
другой: «должен ли этот агент платить сейчас». Guard разбирает вызов 402,
сверяет сумму и получателя с конвертом и либо разрешает (списание в ledger),
либо отказывает — без ключей, без средств, без доверия к модели.

Сеть намеренно не трогается: этот модуль только решает. Исполнение платежа —
отдельный адаптер, который включается по STOP-гейту владельца.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

USDC_DECIMALS = 6


class ChallengeError(ValueError):
    """Вызов 402 не разобран: лучше отказать, чем угадать сумму."""


@dataclass(frozen=True)
class Challenge:
    scheme: str
    network: str
    asset: str
    amount: Decimal
    pay_to: str
    resource: str

    @property
    def payee(self) -> str:
        """Получатель в терминах allowlist — хост ресурса, а не адрес кошелька."""
        host = urlparse(self.resource).hostname if self.resource else None
        return (host or self.pay_to).lower()


def parse_challenge(payload: dict) -> Challenge:
    """Принять challenge в форме x402 v2 (`accepts[0]` или плоский объект)."""
    if not isinstance(payload, dict):
        raise ChallengeError("challenge must be an object")

    item = payload
    accepts = payload.get("accepts")
    if isinstance(accepts, list) and accepts:
        item = accepts[0]
    if not isinstance(item, dict):
        raise ChallengeError("accepts[0] must be an object")

    raw_amount = item.get("amount", item.get("maxAmountRequired"))
    if raw_amount is None:
        raise ChallengeError("amount is required")
    try:
        atomic = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError) as exc:
        raise ChallengeError("amount is not a number") from exc
    if atomic < 0:
        raise ChallengeError("amount must be >= 0")

    decimals = int(item.get("decimals", USDC_DECIMALS))
    amount = atomic / (Decimal(10) ** decimals)

    resource = str(item.get("resource") or payload.get("resource") or "")
    pay_to = str(item.get("payTo") or item.get("pay_to") or "")
    if not resource and not pay_to:
        raise ChallengeError("resource or payTo is required")

    return Challenge(
        scheme=str(item.get("scheme", "exact")),
        network=str(item.get("network", "")),
        asset=str(item.get("asset", "")),
        amount=amount,
        pay_to=pay_to,
        resource=resource,
    )
