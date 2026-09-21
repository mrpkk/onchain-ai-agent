"""Long-poll цикл Telegram (SPEC S4-06): callback → resolve_approval → ответ."""

from __future__ import annotations

import asyncio
import logging

from .telegram import TelegramNotifier, parse_callback

logger = logging.getLogger("integrations.telegram_poller")


async def poll_loop(notifier: TelegramNotifier, stop_event: asyncio.Event) -> None:
    """Опрашивает getUpdates; кнопки approve/reject идут через общий resolve_approval."""
    from ..runtime.approvals import resolve_approval

    offset = None
    logger.info("Telegram poller started")
    while not stop_event.is_set():
        updates = await notifier.get_updates(offset)
        for update in updates:
            offset = int(update.get("update_id", 0)) + 1
            callback = update.get("callback_query") or {}
            parsed = parse_callback(callback.get("data", ""))
            if not parsed:
                continue
            action, approval_id = parsed
            try:
                result = await resolve_approval(approval_id, action,
                                                comment="via telegram")
            except Exception as e:  # noqa: BLE001 — цикл не должен падать
                logger.error("Telegram resolve error: %s", e)
                result = {"error": "internal error"}

            if result.get("error"):
                reply = f"⚠️ {result['error']}"
            elif result.get("status") == "approved":
                reply = "✅ Одобрено" + (" и исполнено" if result.get("executed")
                                         else " (агент не запущен)")
            else:
                reply = "❌ Отклонено"
            await notifier.answer_callback(str(callback.get("id", "")), reply)
            await notifier.send_message(reply)
        await asyncio.sleep(0 if updates else 1)
    logger.info("Telegram poller stopped")
