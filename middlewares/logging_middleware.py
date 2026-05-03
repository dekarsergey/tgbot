from typing import Callable, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database.db import Database


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: Database = data.get("db")
        user = data.get("event_from_user")

        if user and db:
            source = "direct"
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                parts = event.text.split(maxsplit=1)
                if len(parts) > 1:
                    source = parts[1][:64]

            await db.upsert_user(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                source=source,
            )

            event_type = "message"
            payload = None
            if isinstance(event, Message):
                payload = (event.text or "")[:200]
            elif isinstance(event, CallbackQuery):
                event_type = "callback"
                payload = event.data

            await db.log_event(user.id, event_type, payload)

        return await handler(event, data)
