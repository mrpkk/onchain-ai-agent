"""Telegram-интеграция KARTA (SPEC S4-06): inline-approve и уведомления.

Telegram НЕ обходит policy: callback вызывает resolve_approval —
тот же путь, что и web-API, с полным контуром гейтов ядра.
Конфиг: KARTA_TELEGRAM_BOT_TOKEN + KARTA_TELEGRAM_CHAT_ID (fallback TG_USER_ID).
"""

from __future__ import annotations

import html
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("integrations.telegram")


def parse_callback(data: str) -> Optional[tuple[str, str]]:
    """'approve:<id>' | 'reject:<id>' → (action, id); иначе None."""
    if ":" not in (data or ""):
        return None
    action, approval_id = data.split(":", 1)
    if action not in ("approve", "reject") or not approval_id:
        return None
    return action, approval_id


class TelegramNotifier:
    """Минимальный клиент Bot API на httpx (без тяжёлых зависимостей)."""

    def __init__(self, token: str, chat_id: str | int,
                 api_base: str = "https://api.telegram.org",
                 transport: Optional[httpx.AsyncBaseTransport] = None,
                 timeout: float = 35.0):
        self.token = token
        self.chat_id = str(chat_id)
        self.api_base = api_base.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"{self.api_base}/bot{self.token}",
                                 timeout=self._timeout, transport=self._transport)

    async def send_message(self, text: str, reply_markup: Optional[dict] = None) -> dict:
        payload: dict = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with self._client() as client:
                response = await client.post("/sendMessage", json=payload)
        except httpx.HTTPError as e:
            logger.warning("Telegram sendMessage network error: %s", e)
            return {"status_code": 0}
        if response.status_code >= 400:
            logger.warning("Telegram sendMessage %s: %s",
                           response.status_code, response.text[:200])
        return {"status_code": response.status_code}

    async def send_approval(self, approval_id: Optional[str], info: dict) -> None:
        rid = approval_id or "unknown"
        text = (
            "🔐 <b>KARTA: требуется подтверждение</b>\n"
            f"Агент: {html.escape(str(info.get('agent', '—')))}\n"
            f"Действие: <b>{html.escape(str(info.get('action', '—')))}</b>\n"
            f"Параметры: <code>{html.escape(str(info.get('params', {}))[:300])}</code>\n"
            f"Причина: {html.escape(str(info.get('reasoning', ''))[:200])}"
        )
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": f"approve:{rid}"},
            {"text": "❌ Отклонить", "callback_data": f"reject:{rid}"},
        ]]}
        await self.send_message(text, keyboard)

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 25) -> list[dict]:
        params: dict = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        try:
            async with self._client() as client:
                response = await client.get("/getUpdates", params=params)
        except httpx.HTTPError as e:
            logger.warning("Telegram getUpdates error: %s", e)
            return []
        if response.status_code >= 400:
            return []
        return response.json().get("result", [])

    async def answer_callback(self, callback_id: str, text: str) -> None:
        try:
            async with self._client() as client:
                await client.post("/answerCallbackQuery",
                                  json={"callback_query_id": callback_id,
                                        "text": text[:180]})
        except httpx.HTTPError as e:
            logger.warning("Telegram answerCallbackQuery error: %s", e)

    @staticmethod
    def parse_callback(data: str) -> Optional[tuple[str, str]]:
        return parse_callback(data)


def notifier_from_env() -> Optional[TelegramNotifier]:
    token = (
        os.getenv("KARTA_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TG_KARTA_BOT", "").strip()
    )
    chat = os.getenv("KARTA_TELEGRAM_CHAT_ID", "").strip() or os.getenv("TG_USER_ID", "").strip()
    if not token or not chat:
        return None
    return TelegramNotifier(token, chat)
