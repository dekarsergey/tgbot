import asyncio
import json
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import Config
from database.db import Database

router = Router()


# ─── Фильтр: только для админов ──────────────────────────────────────────────

from aiogram.filters import BaseFilter

class AdminFilter(BaseFilter):
    async def __call__(self, message: Message, config: Config) -> bool:
        return message.from_user.id in config.ADMIN_IDS

class AdminCbFilter(BaseFilter):
    async def __call__(self, callback: CallbackQuery, config: Config) -> bool:
        return callback.from_user.id in config.ADMIN_IDS

router.message.filter(AdminFilter())
router.callback_query.filter(AdminCbFilter())


# ─── FSM ─────────────────────────────────────────────────────────────────────

class BroadcastState(StatesGroup):
    waiting_content  = State()   # ждём медиа/текст
    waiting_buttons  = State()   # ждём кнопки (опционально)
    confirm          = State()   # подтверждение


# ─── Keyboards ───────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика",  callback_data="adm_stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
        ],
        [
            InlineKeyboardButton(text="📡 Источники",   callback_data="adm_sources"),
            InlineKeyboardButton(text="🔻 Воронка",     callback_data="adm_funnel"),
        ],
        [
            InlineKeyboardButton(text="📥 CSV выгрузка", callback_data="adm_csv"),
        ],
        [
            InlineKeyboardButton(text="📣 Рассылка всем",         callback_data="adm_bc_all"),
            InlineKeyboardButton(text="✅ Рассылка подписчикам",   callback_data="adm_bc_sub"),
        ],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="adm_menu")
    ]])

def kb_broadcast_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="adm_bc_add_btn")],
        [InlineKeyboardButton(text="✅ Отправить без кнопок", callback_data="adm_bc_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_menu")],
    ])

def kb_broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="adm_bc_confirm")],
        [InlineKeyboardButton(text="➕ Ещё кнопку", callback_data="adm_bc_add_btn")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_menu")],
    ])

def build_inline_kb(buttons: list[dict]):
    if not buttons:
        return None
    rows = []
    for btn in buttons:
        rows.append([InlineKeyboardButton(text=btn["text"], url=btn["url"])])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── /admin и шорткаты ───────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛡 <b>Панель администратора</b>\n\nВыбери раздел:",
        reply_markup=kb_main(),
        parse_mode="HTML"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database):
    s = await db.get_stats()
    total = s["total_users"] or 1
    sub_pct = round(s["subscribed"] / total * 100)
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        "<b>Аудитория</b>\n"
        f"👥 Всего: <b>{s['total_users']}</b>\n"
        f"➕ Новые: <b>{s['today']}</b> за 24ч, <b>{s['week']}</b> за 7д, <b>{s['month']}</b> за 30д\n"
        f"🔥 Активные: <b>{s['active_today']}</b> за 24ч, <b>{s['active_week']}</b> за 7д\n\n"
        "<b>Подписка</b>\n"
        f"✅ Подтвердили: <b>{s['subscribed']}</b>\n"
        f"⏳ Не подтвердили: <b>{s['not_subscribed']}</b>\n"
        f"📈 Конверсия: <b>{sub_pct}%</b>\n\n"
        "<b>Рассылки</b>\n"
        f"📨 Завершено: <b>{s['broadcasts_total']}</b>\n"
        f"⚠️ Ошибок: <b>{s['broadcasts_errors']}</b>\n"
    )
    await message.answer(text, reply_markup=kb_back(), parse_mode="HTML")

@router.message(Command("users"))
async def cmd_users(message: Message, db: Database):
    users = await db.get_recent_users(10)
    if not users:
        await message.answer("Пользователей пока нет.", reply_markup=kb_back())
        return
    lines = ["👥 <b>Последние 10 пользователей:</b>\n"]
    for u in users:
        name = f"{u['first_name']} {u['last_name'] or ''}".strip()
        username = f"@{u['username']}" if u['username'] else "—"
        icon = "✅" if u["subscribed"] else "❌"
        lines.append(
            f"{icon} <b>{name}</b> ({username})\n"
            f"   📅 {u['joined_at'][:10]} | 🔗 {u['source']} | шаг {u['funnel_step']}\n"
        )
    await message.answer("\n".join(lines), reply_markup=kb_back(), parse_mode="HTML")

@router.message(Command("sources"))
async def cmd_sources(message: Message, db: Database):
    sources = await db.get_sources()
    if not sources:
        await message.answer("Данных пока нет.", reply_markup=kb_back())
        return
    lines = ["📡 <b>Источники трафика:</b>\n"]
    for row in sources:
        sub = row["subscribed_cnt"] or 0
        lines.append(f"• <code>{row['source']}</code> — <b>{row['cnt']}</b> польз., ✅ {sub}")
    lines.append("\n💡 <i>Ссылка: t.me/бот?start=instagram</i>")
    await message.answer("\n".join(lines), reply_markup=kb_back(), parse_mode="HTML")

@router.message(Command("export"))
async def cmd_export(message: Message, db: Database):
    from datetime import datetime
    data = await db.export_csv()
    filename = f"users_{datetime.now():%Y%m%d_%H%M}.csv"
    await message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption="📥 <b>Выгрузка пользователей</b>",
        parse_mode="HTML"
    )

@router.message(Command("mailing"))
async def cmd_mailing(message: Message, state: FSMContext):
    await state.set_state(BroadcastState.waiting_content)
    await state.update_data(target="all", buttons=[])
    await message.answer(
        "📣 <b>Рассылка всем пользователям</b>\n\n"
        "Отправь сообщение для рассылки.\n"
        "Поддерживается: текст, фото, видео, файл.\n\n"
        "❌ Отмена — /cancel",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_menu")
async def adm_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🛡 <b>Панель администратора</b>\n\nВыбери раздел:",
        reply_markup=kb_main(),
        parse_mode="HTML"
    )


# ─── Статистика ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery, db: Database):
    s = await db.get_stats()
    total = s["total_users"] or 1
    sub_pct = round(s["subscribed"] / total * 100)
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        "<b>Аудитория</b>\n"
        f"👥 Всего: <b>{s['total_users']}</b>\n"
        f"➕ Новые: <b>{s['today']}</b> за 24ч, <b>{s['week']}</b> за 7д, <b>{s['month']}</b> за 30д\n"
        f"🔥 Активные: <b>{s['active_today']}</b> за 24ч, <b>{s['active_week']}</b> за 7д, <b>{s['active_month']}</b> за 30д\n\n"
        "<b>Подписка</b>\n"
        f"✅ Подтвердили: <b>{s['subscribed']}</b>\n"
        f"⏳ Не подтвердили: <b>{s['not_subscribed']}</b>\n"
        f"📈 Конверсия: <b>{sub_pct}%</b>\n\n"
        "<b>Рассылки</b>\n"
        f"📨 Завершено: <b>{s['broadcasts_total']}</b>\n"
        f"⚠️ Ошибок доставки: <b>{s['broadcasts_errors']}</b>\n"
    )
    await callback.message.edit_text(text, reply_markup=kb_back(), parse_mode="HTML")


# ─── Воронка ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_funnel")
async def adm_funnel(callback: CallbackQuery, db: Database):
    s = await db.get_stats()
    total = s["total_users"] or 1

    def pct(n): return round(n / total * 100)

    text = (
        "🔻 <b>Воронка</b>\n\n"
        f"👥 Всего пришло:        <b>{total}</b> (100%)\n"
        f"✅ Подписались:         <b>{s['subscribed']}</b> ({pct(s['subscribed'])}%)\n"
        f"🚀 Урок 1 (старт):     <b>{s['funnel_step1']}</b> ({pct(s['funnel_step1'])}%)\n"
        f"📖 Урок 2:             <b>{s['funnel_step2']}</b> ({pct(s['funnel_step2'])}%)\n"
        f"⚡️ Урок 3:             <b>{s['funnel_step3']}</b> ({pct(s['funnel_step3'])}%)\n"
        f"🏆 Финал (выбор темы): <b>{s['funnel_step4']}</b> ({pct(s['funnel_step4'])}%)\n"
    )
    await callback.message.edit_text(text, reply_markup=kb_back(), parse_mode="HTML")


# ─── Пользователи ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery, db: Database):
    users = await db.get_recent_users(10)
    if not users:
        await callback.message.edit_text("Пользователей пока нет.", reply_markup=kb_back())
        return
    lines = ["👥 <b>Последние 10 пользователей:</b>\n"]
    for u in users:
        name = f"{u['first_name']} {u['last_name'] or ''}".strip()
        username = f"@{u['username']}" if u['username'] else "—"
        icon = "✅" if u["subscribed"] else "❌"
        lines.append(
            f"{icon} <b>{name}</b> ({username})\n"
            f"   📅 {u['joined_at'][:10]} | 🔗 {u['source']} | шаг {u['funnel_step']}\n"
        )
    await callback.message.edit_text("\n".join(lines), reply_markup=kb_back(), parse_mode="HTML")


# ─── Источники ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_sources")
async def adm_sources(callback: CallbackQuery, db: Database):
    sources = await db.get_sources()
    if not sources:
        await callback.message.edit_text("Данных пока нет.", reply_markup=kb_back())
        return
    lines = ["📡 <b>Источники трафика:</b>\n"]
    for row in sources:
        sub = row["subscribed_cnt"] or 0
        lines.append(f"• <code>{row['source']}</code> — <b>{row['cnt']}</b> польз., ✅ {sub}")
    lines.append("\n💡 <i>Ссылка: t.me/бот?start=instagram</i>")
    await callback.message.edit_text("\n".join(lines), reply_markup=kb_back(), parse_mode="HTML")


# ─── CSV ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_csv")
async def adm_csv(callback: CallbackQuery, db: Database):
    await callback.answer("Формирую файл...")
    data = await db.export_csv()
    filename = f"users_{datetime.now():%Y%m%d_%H%M}.csv"
    await callback.message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption="📥 <b>Выгрузка пользователей</b>",
        parse_mode="HTML"
    )

from datetime import datetime  # noqa: E402 (повторный импорт для clarity)


# ─── РАССЫЛКА ────────────────────────────────────────────────────────────────

async def _start_broadcast(callback: CallbackQuery, state: FSMContext, target: str):
    """target = 'all' | 'subscribed'"""
    await state.set_state(BroadcastState.waiting_content)
    await state.update_data(target=target, buttons=[])
    label = "всем пользователям" if target == "all" else "только подписчикам канала"
    await callback.message.edit_text(
        f"📣 <b>Рассылка — {label}</b>\n\n"
        "Отправь сообщение для рассылки.\n"
        "Поддерживается: текст, фото, видео, файл.\n\n"
        "Текст можно форматировать жирным, курсивом и т.д.\n"
        "❌ Отмена — /cancel",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_all")
async def bc_all(callback: CallbackQuery, state: FSMContext):
    await _start_broadcast(callback, state, "all")

@router.callback_query(F.data == "adm_bc_sub")
async def bc_sub(callback: CallbackQuery, state: FSMContext):
    await _start_broadcast(callback, state, "subscribed")

@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=kb_main())


# Получили контент для рассылки
@router.message(BroadcastState.waiting_content)
async def bc_got_content(message: Message, state: FSMContext):
    # Сохраняем message_id и chat_id для copy_message
    await state.update_data(
        msg_id=message.message_id,
        from_chat=message.chat.id,
    )
    await state.set_state(BroadcastState.waiting_buttons)
    await message.answer(
        "👆 Сообщение получено!\n\n"
        "Хочешь добавить кнопки-ссылки?\n"
        "Каждая кнопка — отдельное сообщение в формате:\n"
        "<code>Текст кнопки | https://ссылка</code>\n\n"
        "Или сразу отправляй без кнопок 👇",
        reply_markup=kb_broadcast_buttons(),
        parse_mode="HTML"
    )

# Хотим добавить кнопку
@router.callback_query(F.data == "adm_bc_add_btn", BroadcastState.waiting_buttons)
async def bc_add_btn(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    btns = data.get("buttons", [])
    await callback.message.edit_text(
        f"Кнопок добавлено: <b>{len(btns)}</b>\n\n"
        "Отправь кнопку в формате:\n"
        "<code>Текст кнопки | https://ссылка</code>\n\n"
        "Пример:\n<code>Перейти на сайт | https://example.com</code>",
        parse_mode="HTML"
    )

# Получили текст кнопки
@router.message(BroadcastState.waiting_buttons)
async def bc_got_button(message: Message, state: FSMContext):
    if "|" not in message.text:
        await message.answer(
            "❌ Неверный формат. Нужно:\n"
            "<code>Текст кнопки | https://ссылка</code>",
            parse_mode="HTML"
        )
        return
    parts = message.text.split("|", 1)
    text = parts[0].strip()
    url = parts[1].strip()
    if not url.startswith("http"):
        await message.answer("❌ Ссылка должна начинаться с http:// или https://")
        return

    data = await state.get_data()
    buttons = data.get("buttons", [])
    buttons.append({"text": text, "url": url})
    await state.update_data(buttons=buttons)

    await message.answer(
        f"✅ Кнопка добавлена: <b>{text}</b>\n"
        f"Всего кнопок: <b>{len(buttons)}</b>",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

# Подтверждение и запуск
@router.callback_query(F.data == "adm_bc_confirm")
async def bc_confirm(callback: CallbackQuery, bot: Bot, db: Database, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    msg_id   = data.get("msg_id")
    from_chat = data.get("from_chat")
    target   = data.get("target", "all")
    buttons  = data.get("buttons", [])
    reply_markup = build_inline_kb(buttons)

    if not msg_id:
        await callback.message.edit_text("❌ Нет сообщения для рассылки.")
        return

    if target == "subscribed":
        user_ids = await db.get_subscribed_user_ids()
    else:
        user_ids = await db.get_all_user_ids()

    total = len(user_ids)
    sent = failed = 0

    status = await callback.message.edit_text(f"⏳ Запускаю рассылку... 0 / {total}")

    for i, uid in enumerate(user_ids):
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=from_chat,
                message_id=msg_id,
                reply_markup=reply_markup,
            )
            sent += 1
        except Exception:
            failed += 1

        # Обновляем счётчик каждые 20 человек
        if (i + 1) % 20 == 0:
            try:
                await status.edit_text(f"⏳ Рассылка... {i+1} / {total}")
            except Exception:
                pass

        await asyncio.sleep(0.05)

    await db.log_broadcast(sent, failed)
    await status.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b> (заблокировали бота)\n"
        f"🎯 Аудитория: {'все' if target == 'all' else 'подписчики'}",
        reply_markup=kb_back(),
        parse_mode="HTML"
    )
