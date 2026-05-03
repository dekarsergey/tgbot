import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat

from config import Config
from database.db import Database
from handlers import user, admin
from middlewares.logging_middleware import LoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def set_commands(bot: Bot, config: Config):
    # Команды для обычных пользователей
    user_commands = [
        BotCommand(command="start", description="Проверить пользовательский сценарий"),
    ]

    # Команды для администраторов (расширенный список)
    admin_commands = [
        BotCommand(command="start",   description="Проверить пользовательский сценарий"),
        BotCommand(command="admin",   description="Открыть админ-панель"),
        BotCommand(command="mailing", description="Создать рассылку"),
        BotCommand(command="stats",   description="Показать статистику"),
        BotCommand(command="users",   description="Последние пользователи"),
        BotCommand(command="sources", description="Источники переходов"),
        BotCommand(command="export",  description="Выгрузить CSV"),
    ]

    # Ставим дефолтные команды для всех
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    # Ставим расширенные команды для каждого админа
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as e:
            logger.warning(f"Не удалось установить команды для админа {admin_id}: {e}")


async def main():
    config = Config()
    db = Database(config.DB_PATH)
    await db.init()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(LoggingMiddleware(db))
    dp.callback_query.middleware(LoggingMiddleware(db))

    # Routers
    dp.include_router(admin.router)
    dp.include_router(user.router)

    # Pass shared objects via workflow_data
    dp["config"] = config
    dp["db"] = db

    # Устанавливаем меню команд
    await set_commands(bot, config)

    logger.info("Bot starting...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
