from typing import Callable, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database.db import Database


class LoggingMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            source = "direct"
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                parts = event.text.split(maxsplit=1)
                if len(parts) > 1:
                    source = parts[1][:64]  # UTM-метка из deep link

            await self.db.upsert_user(
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

            await self.db.log_event(user.id, event_type, payload)

        return await handler(event, data)
