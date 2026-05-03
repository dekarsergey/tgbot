import asyncio
import json
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter
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


# ─── Фильтры ─────────────────────────────────────────────────────────────────

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
    waiting_content = State()
    waiting_buttons = State()

class FunnelEditState(StatesGroup):
    waiting_content  = State()   # ждём контент нового/редактируемого шага
    waiting_buttons  = State()   # ждём кнопки


# ─── Keyboards: главное меню ──────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика",   callback_data="adm_stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
        ],
        [
            InlineKeyboardButton(text="📡 Источники",    callback_data="adm_sources"),
            InlineKeyboardButton(text="🔻 Воронка",      callback_data="adm_funnel_stats"),
        ],
        [
            InlineKeyboardButton(text="✏️ Редактор воронки", callback_data="adm_funnel_editor"),
        ],
        [
            InlineKeyboardButton(text="📥 CSV",                    callback_data="adm_csv"),
        ],
        [
            InlineKeyboardButton(text="📣 Рассылка всем",        callback_data="adm_bc_all"),
            InlineKeyboardButton(text="✅ Рассылка подписчикам", callback_data="adm_bc_sub"),
        ],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="adm_menu")
    ]])

def kb_back_to_editor() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ К редактору", callback_data="adm_funnel_editor")
    ]])


# ─── Keyboards: редактор воронки ─────────────────────────────────────────────

def kb_funnel_editor(steps: list) -> InlineKeyboardMarkup:
    rows = []
    total = len(steps)
    for i, step in enumerate(steps):
        pos = step["position"]
        preview = (step["text"] or "📎 медиа")[:30]
        # Кнопка шага
        rows.append([InlineKeyboardButton(
            text=f"{'📝' if step['media_type'] is None else '🖼'} Шаг {pos}: {preview}",
            callback_data=f"fstep_view_{step['id']}"
        )])
        # Кнопки управления шагом
        nav = []
        if i > 0:
            nav.append(InlineKeyboardButton(text="⬆️", callback_data=f"fstep_up_{step['id']}"))
        if i < total - 1:
            nav.append(InlineKeyboardButton(text="⬇️", callback_data=f"fstep_down_{step['id']}"))
        nav.append(InlineKeyboardButton(text="✏️ Изменить", callback_data=f"fstep_edit_{step['id']}"))
        nav.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fstep_del_{step['id']}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="➕ Добавить шаг", callback_data="fstep_add")])
    rows.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_step_view(step_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить контент", callback_data=f"fstep_edit_{step_id}")],
        [InlineKeyboardButton(text="🗑 Удалить шаг",      callback_data=f"fstep_del_{step_id}")],
        [InlineKeyboardButton(text="◀️ К списку",         callback_data="adm_funnel_editor")],
    ])

def kb_after_content(step_id_or_new: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить кнопку",        callback_data=f"fbtn_add_{step_id_or_new}")],
        [InlineKeyboardButton(text="✅ Сохранить без кнопок",   callback_data=f"fbtn_save_{step_id_or_new}")],
        [InlineKeyboardButton(text="❌ Отмена",                 callback_data="adm_funnel_editor")],
    ])

def kb_after_button(step_id_or_new: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё кнопку",   callback_data=f"fbtn_add_{step_id_or_new}")],
        [InlineKeyboardButton(text="✅ Сохранить",    callback_data=f"fbtn_save_{step_id_or_new}")],
        [InlineKeyboardButton(text="❌ Отмена",       callback_data="adm_funnel_editor")],
    ])

def kb_confirm_delete(step_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить",  callback_data=f"fstep_del_confirm_{step_id}")],
        [InlineKeyboardButton(text="❌ Отмена",       callback_data="adm_funnel_editor")],
    ])

def kb_broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Предпросмотр",         callback_data="adm_bc_preview")],
        [InlineKeyboardButton(text="🚀 Подтвердить отправку", callback_data="adm_bc_confirm")],
        [InlineKeyboardButton(text="➕ Добавить кнопку",      callback_data="adm_bc_add_btn")],
        [InlineKeyboardButton(text="❌ Отмена",               callback_data="adm_menu")],
    ])

STYLE_MAP = {
    "green":   "success",
    "red":     "danger",
    "blue":    "primary",
    "success": "success",
    "danger":  "danger",
    "primary": "primary",
}

def build_inline_kb(buttons: list):
    if not buttons:
        return None
    rows = []
    for btn in buttons:
        if btn.get("url"):
            style = STYLE_MAP.get(btn.get("color", "").lower())
            extra = {"style": style} if style else {}
            rows.append([InlineKeyboardButton(text=btn["text"], url=btn["url"], **extra)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# ─── /admin ──────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def _admin_home_text(db: Database) -> str:
    s = await db.get_stats()
    total = s["total_users"] or 1
    sub_pct = round(s["subscribed"] / total * 100)
    new_today = s["today"]
    active = s["active_today"]
    steps = s["funnel_total_steps"]
    trend = "📈" if new_today > 0 else "➖"
    time_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    last_step_cnt = s.get(f"funnel_step{steps}", 0) if steps else 0
    lines = [
        "╔══════════════════════╗",
        "║  🛡 <b>АДМИН-ПАНЕЛЬ</b>  ║",
        "╚══════════════════════╝",
        "",
        f"🕐 <i>Обновлено: {time_str}</i>",
        "",
        "━━━━━ 👥 <b>АУДИТОРИЯ</b> ━━━━━",
        f"  Всего пользователей:  <b>{total}</b>",
        f"  {trend} Новых сегодня:      <b>{new_today}</b>",
        f"  🔥 Активных за 24ч:    <b>{active}</b>",
        f"  ✅ Подписаны:  <b>{s['subscribed']}</b> <i>({sub_pct}%)</i>",
        "",
        "━━━━━ 📊 <b>ВОРОНКА</b> ━━━━━━",
        f"  Шагов настроено:   <b>{steps}</b>",
        f"  Прошли шаг 1:      <b>{s.get('funnel_step1', 0)}</b>",
        f"  Дошли до конца:    <b>{last_step_cnt}</b>",
        "",
        "━━━━━ 📣 <b>РАССЫЛКИ</b> ━━━━━",
        f"  Всего отправлено:  <b>{s['broadcasts_total']}</b>",
        f"  Ошибок доставки:   <b>{s['broadcasts_errors']}</b>",
        "",
        "👇 <b>Выбери раздел:</b>",
    ]
    return "\n".join(lines)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, db: Database):
    await state.clear()
    await message.answer(await _admin_home_text(db), reply_markup=kb_main(), parse_mode="HTML")

@router.callback_query(F.data == "adm_menu")
async def adm_menu(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    await callback.message.edit_text(await _admin_home_text(db), reply_markup=kb_main(), parse_mode="HTML")


# ─── Статистика ───────────────────────────────────────────────────────────────

async def _stats_text(db: Database) -> str:
    s = await db.get_stats()
    total = s["total_users"] or 1
    sub_pct = round(s["subscribed"] / total * 100)
    active_pct = round(s["active_today"] / total * 100)

    def bar(val, mx, width=10):
        filled = round(val / mx * width) if mx else 0
        return "█" * filled + "░" * (width - filled)

    return (
        "📊 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>\n"
        f"<i>🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>\n\n"

        "━━━━ 👥 <b>ПОЛЬЗОВАТЕЛИ</b> ━━━━\n"
        f"  Всего в базе:      <b>{s['total_users']}</b>\n"
        f"  📅 Новых сегодня:  <b>{s['today']}</b>\n"
        f"  📅 За 7 дней:      <b>{s['week']}</b>\n"
        f"  📅 За 30 дней:     <b>{s['month']}</b>\n\n"

        "━━━━ 🔥 <b>АКТИВНОСТЬ</b> ━━━━━\n"
        f"  За 24 часа:  <b>{s['active_today']}</b> <i>({active_pct}%)</i>\n"
        f"  <code>[{bar(s['active_today'], total)}]</code>\n"
        f"  За 7 дней:   <b>{s['active_week']}</b>\n"
        f"  За 30 дней:  <b>{s['active_month']}</b>\n\n"

        "━━━━ ✅ <b>ПОДПИСКА</b> ━━━━━━\n"
        f"  Подтвердили:     <b>{s['subscribed']}</b>\n"
        f"  Не подтвердили:  <b>{s['not_subscribed']}</b>\n"
        f"  Конверсия:       <b>{sub_pct}%</b>\n"
        f"  <code>[{bar(s['subscribed'], total)}]</code>\n\n"

        "━━━━ 📣 <b>РАССЫЛКИ</b> ━━━━━━\n"
        f"  Запущено:         <b>{s['broadcasts_total']}</b>\n"
        f"  Ошибок доставки:  <b>{s['broadcasts_errors']}</b>\n"
        f"  <i>(ошибки = бот заблокирован у юзера)</i>\n"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database):
    await message.answer(await _stats_text(db), reply_markup=kb_back(), parse_mode="HTML")

@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery, db: Database):
    await callback.message.edit_text(await _stats_text(db), reply_markup=kb_back(), parse_mode="HTML")


# ─── Статистика воронки ───────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_funnel_stats")
async def adm_funnel_stats(callback: CallbackQuery, db: Database):
    s = await db.get_stats()
    total = s["total_users"] or 1
    n = s["funnel_total_steps"]
    steps = await db.get_funnel_steps()

    def bar(val, mx, width=8):
        filled = round(val / mx * width) if mx else 0
        return "█" * filled + "░" * (width - filled)

    lines = [
        "🔻 <b>СТАТИСТИКА ВОРОНКИ</b>\n",
        f"👥 Всего пользователей:  <b>{total}</b>\n",
        f"✅ Подписались:          <b>{s['subscribed']}</b> ({round(s['subscribed']/total*100)}%)\n",
        f"<code>[{bar(s['subscribed'], total)}]</code>\n",
        "\n━━━━━ <b>ШАГИ</b> ━━━━━\n",
    ]
    if n == 0:
        lines.append("\nШагов воронки пока нет.\nДобавь через ✏️ Редактор воронки")
    else:
        prev = s['subscribed'] or 1
        for i, step in enumerate(steps, 1):
            cnt = s.get(f"funnel_step{i}", 0)
            pct_total = round(cnt / total * 100)
            pct_prev = round(cnt / prev * 100) if prev else 0
            preview = (step['text'] or '📎 медиа')[:20]
            drop = 100 - pct_prev if i > 1 else 0
            drop_str = f" <i>(-{drop}%)</i>" if drop > 0 and i > 1 else ""
            lines.append(
                f"\n<b>Шаг {i}</b> — «{preview}»\n"
                f"  👤 Дошли: <b>{cnt}</b> ({pct_total}% от всех){drop_str}\n"
                f"  <code>[{bar(cnt, total)}]</code>"
            )
            prev = cnt or 1
    await callback.message.edit_text("\n".join(lines), reply_markup=kb_back(), parse_mode="HTML")


# ─── Пользователи ────────────────────────────────────────────────────────────

@router.message(Command("users"))
async def cmd_users(message: Message, db: Database):
    await _send_users(message, db)

@router.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery, db: Database):
    await _send_users(callback.message, db, edit=True)

async def _send_users(msg, db: Database, edit: bool = False):
    users = await db.get_recent_users(10)
    if not users:
        text = "Пользователей пока нет."
    else:
        lines = ["👥 <b>Последние 10 пользователей:</b>\n"]
        for u in users:
            name = f"{u['first_name']} {u['last_name'] or ''}".strip()
            username = f"@{u['username']}" if u['username'] else "—"
            icon = "✅" if u["subscribed"] else "❌"
            lines.append(f"{icon} <b>{name}</b> ({username})\n   📅 {u['joined_at'][:10]} | 🔗 {u['source']} | шаг {u['funnel_step']}\n")
        text = "\n".join(lines)
    if edit:
        await msg.edit_text(text, reply_markup=kb_back(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb_back(), parse_mode="HTML")


# ─── Источники ───────────────────────────────────────────────────────────────

@router.message(Command("sources"))
async def cmd_sources(message: Message, db: Database):
    await _send_sources(message, db)

@router.callback_query(F.data == "adm_sources")
async def adm_sources(callback: CallbackQuery, db: Database):
    await _send_sources(callback.message, db, edit=True)

async def _send_sources(msg, db: Database, edit: bool = False):
    sources = await db.get_sources()
    if not sources:
        text = "Данных пока нет."
    else:
        lines = ["📡 <b>Источники трафика:</b>\n"]
        for row in sources:
            sub = row["subscribed_cnt"] or 0
            lines.append(f"• <code>{row['source']}</code> — <b>{row['cnt']}</b> польз., ✅ {sub}")
        lines.append("\n💡 <i>t.me/бот?start=instagram</i>")
        text = "\n".join(lines)
    if edit:
        await msg.edit_text(text, reply_markup=kb_back(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb_back(), parse_mode="HTML")


# ─── CSV ─────────────────────────────────────────────────────────────────────

@router.message(Command("export"))
async def cmd_export(message: Message, db: Database):
    await _send_csv(message, db)

@router.callback_query(F.data == "adm_csv")
async def adm_csv(callback: CallbackQuery, db: Database):
    await callback.answer("Формирую файл...")
    await _send_csv(callback.message, db)

async def _send_csv(msg, db: Database):
    data = await db.export_csv()
    filename = f"users_{datetime.now():%Y%m%d_%H%M}.csv"
    await msg.answer_document(
        BufferedInputFile(data, filename=filename),
        caption="📥 <b>Выгрузка пользователей</b>",
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════════════════════════
# РЕДАКТОР ВОРОНКИ
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_funnel_editor")
async def adm_funnel_editor_real(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    steps = await db.get_funnel_steps()
    text = f"✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>\n\nВыбери шаг для редактирования или добавь новый:"
    await callback.message.edit_text(text, reply_markup=kb_funnel_editor(steps), parse_mode="HTML")

@router.message(Command("funnel"))
async def cmd_funnel_real(message: Message, state: FSMContext, db: Database):
    await state.clear()
    steps = await db.get_funnel_steps()
    text = f"✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>\n\nВыбери шаг для редактирования или добавь новый:"
    await message.answer(text, reply_markup=kb_funnel_editor(steps), parse_mode="HTML")


# ─── Просмотр шага ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fstep_view_"))
async def fstep_view(callback: CallbackQuery, db: Database):
    step_id = int(callback.data.split("_")[-1])
    step = await db.get_funnel_step(step_id)
    if not step:
        await callback.answer("Шаг не найден", show_alert=True)
        return

    buttons = json.loads(step["buttons"] or "[]")
    btn_text = "\n".join([f"  • {b['text']} → {b.get('url','')}" for b in buttons]) or "нет"
    media_info = f"{step['media_type']} ({step['media_id'][:20]}...)" if step['media_type'] else "нет"

    text = (
        f"📍 <b>Шаг {step['position']}</b>\n\n"
        f"<b>Текст:</b>\n{step['text'] or '—'}\n\n"
        f"<b>Медиа:</b> {media_info}\n"
        f"<b>Кнопки:</b>\n{btn_text}\n\n"
        f"<i>Обновлён: {step['updated_at'][:16]}</i>"
    )
    await callback.message.edit_text(text, reply_markup=kb_step_view(step_id), parse_mode="HTML")


# ─── Добавить шаг ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "fstep_add")
async def fstep_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FunnelEditState.waiting_content)
    await state.update_data(edit_step_id=None, buttons=[])
    await callback.message.edit_text(
        "➕ <b>Новый шаг воронки</b>\n\n"
        "Отправь сообщение для этого шага.\n"
        "Можно: текст, фото с подписью, видео, документ, GIF.\n\n"
        "❌ Отмена — /cancel",
        parse_mode="HTML"
    )


# ─── Редактировать шаг ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fstep_edit_"))
async def fstep_edit(callback: CallbackQuery, state: FSMContext, db: Database):
    step_id = int(callback.data.split("_")[-1])
    step = await db.get_funnel_step(step_id)
    if not step:
        await callback.answer("Шаг не найден", show_alert=True)
        return
    buttons = json.loads(step["buttons"] or "[]")
    await state.set_state(FunnelEditState.waiting_content)
    await state.update_data(edit_step_id=step_id, buttons=buttons)
    await callback.message.edit_text(
        f"✏️ <b>Редактирование шага {step['position']}</b>\n\n"
        "Отправь новое сообщение (текст, фото, видео, документ).\n"
        "Текущий контент будет заменён.\n\n"
        "❌ Отмена — /cancel",
        parse_mode="HTML"
    )


# ─── Получили контент шага ───────────────────────────────────────────────────

@router.message(FunnelEditState.waiting_content)
async def fstep_got_content(message: Message, state: FSMContext):
    # Определяем тип медиа
    media_type = None
    media_id = None
    text = message.text or message.caption or ""

    if message.photo:
        media_type = "photo"
        media_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        media_id = message.video.file_id
    elif message.document:
        media_type = "document"
        media_id = message.document.file_id
    elif message.animation:
        media_type = "animation"
        media_id = message.animation.file_id

    data = await state.get_data()
    await state.update_data(
        content_text=text,
        content_media_type=media_type,
        content_media_id=media_id,
    )
    await state.set_state(FunnelEditState.waiting_buttons)

    step_key = str(data.get("edit_step_id") or "new")
    await message.answer(
        "👆 Контент получен!\n\n"
        "Хочешь добавить кнопки-ссылки под это сообщение?\n"
        "Формат: <code>Текст кнопки | https://ссылка</code>",
        reply_markup=kb_after_content(step_key),
        parse_mode="HTML"
    )


# ─── Добавить кнопку к шагу ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fbtn_add_"))
async def fbtn_add(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    btns = data.get("buttons", [])
    await callback.message.edit_text(
        f"Кнопок: <b>{len(btns)}</b>\n\n"
        "Отправь кнопку:\n"
        "<code>Текст кнопки | https://ссылка</code>\n\n"
        "Пример: <code>Смотреть урок | https://youtube.com/...</code>",
        parse_mode="HTML"
    )


@router.message(FunnelEditState.waiting_buttons)
async def fbtn_got_text(message: Message, state: FSMContext):
    if "|" not in message.text:
        await message.answer(
            "❌ Неверный формат.\n"
            "<code>Текст кнопки | https://ссылка</code>",
            parse_mode="HTML"
        )
        return
    parts = [p.strip() for p in message.text.split("|")]
    btn_text = parts[0]
    url = parts[1] if len(parts) > 1 else ""
    color = parts[2].lower() if len(parts) > 2 else ""
    if not url.startswith("http"):
        await message.answer("❌ Ссылка должна начинаться с http:// или https://")
        return

    data = await state.get_data()
    buttons = data.get("buttons", [])
    buttons.append({"text": btn_text, "url": url, "color": color})
    await state.update_data(buttons=buttons)

    step_key = str(data.get("edit_step_id") or "new")
    color_str = f" 🎨 {color}" if color else ""
    await message.answer(
        f"✅ Кнопка добавлена: <b>{btn_text}</b>{color_str}\nВсего кнопок: <b>{len(buttons)}</b>",
        reply_markup=kb_after_button(step_key),
        parse_mode="HTML"
    )


# ─── Сохранить шаг ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fbtn_save_"))
async def fbtn_save(callback: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    await state.clear()

    text = data.get("content_text", "")
    media_type = data.get("content_media_type")
    media_id = data.get("content_media_id")
    buttons = data.get("buttons", [])
    edit_step_id = data.get("edit_step_id")

    if edit_step_id:
        await db.update_funnel_step(edit_step_id, text, media_type, media_id, buttons)
        msg = f"✅ <b>Шаг обновлён!</b>"
    else:
        await db.add_funnel_step(text, media_type, media_id, buttons)
        total = await db.count_funnel_steps()
        msg = f"✅ <b>Шаг добавлен!</b> Всего шагов: {total}"

    steps = await db.get_funnel_steps()
    await callback.message.edit_text(
        msg + f"\n\n✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>",
        reply_markup=kb_funnel_editor(steps),
        parse_mode="HTML"
    )


# ─── Удалить шаг ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fstep_del_confirm_"))
async def fstep_del_confirm(callback: CallbackQuery, db: Database):
    step_id = int(callback.data.split("_")[-1])
    await db.delete_funnel_step(step_id)
    steps = await db.get_funnel_steps()
    await callback.message.edit_text(
        f"🗑 Шаг удалён.\n\n✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>",
        reply_markup=kb_funnel_editor(steps),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("fstep_del_"))
async def fstep_del(callback: CallbackQuery, db: Database):
    # Проверяем что это не confirm (он обрабатывается выше)
    if "confirm" in callback.data:
        return
    step_id = int(callback.data.split("_")[-1])
    step = await db.get_funnel_step(step_id)
    if not step:
        await callback.answer("Шаг не найден", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑 Удалить <b>Шаг {step['position']}</b>?\n\n"
        f"«{(step['text'] or 'медиа')[:50]}»\n\n"
        "Это действие нельзя отменить.",
        reply_markup=kb_confirm_delete(step_id),
        parse_mode="HTML"
    )


# ─── Переместить шаг ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fstep_up_"))
async def fstep_up(callback: CallbackQuery, db: Database):
    step_id = int(callback.data.split("_")[-1])
    await db.move_funnel_step(step_id, "up")
    steps = await db.get_funnel_steps()
    await callback.message.edit_text(
        f"✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>",
        reply_markup=kb_funnel_editor(steps),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("fstep_down_"))
async def fstep_down(callback: CallbackQuery, db: Database):
    step_id = int(callback.data.split("_")[-1])
    await db.move_funnel_step(step_id, "down")
    steps = await db.get_funnel_steps()
    await callback.message.edit_text(
        f"✏️ <b>Редактор воронки</b>\nШагов: <b>{len(steps)}</b>",
        reply_markup=kb_funnel_editor(steps),
        parse_mode="HTML"
    )


# ─── /cancel ─────────────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext, db: Database):
    await state.clear()
    steps = await db.get_funnel_steps()
    await message.answer(
        "❌ Отменено.\n\n✏️ <b>Редактор воронки</b>",
        reply_markup=kb_funnel_editor(steps),
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════════════════════════
# РАССЫЛКА
# ══════════════════════════════════════════════════════════════════════════════

async def _start_broadcast(callback: CallbackQuery, state: FSMContext, target: str):
    await state.set_state(BroadcastState.waiting_content)
    await state.update_data(target=target, buttons=[], bc_msg_id=None, bc_chat_id=None)
    label = "всем" if target == "all" else "только подписчикам"
    await callback.message.edit_text(
        f"📣 <b>Рассылка — {label}</b>\n\n"
        "Отправь сообщение: текст, фото, видео, документ.\n"
        "❌ Отмена — /cancel",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_all")
async def bc_all(callback: CallbackQuery, state: FSMContext):
    await _start_broadcast(callback, state, "all")

@router.callback_query(F.data == "adm_bc_sub")
async def bc_sub(callback: CallbackQuery, state: FSMContext):
    await _start_broadcast(callback, state, "subscribed")

@router.message(Command("mailing"))
async def cmd_mailing(message: Message, state: FSMContext):
    await state.set_state(BroadcastState.waiting_content)
    await state.update_data(target="all", buttons=[])
    await message.answer(
        "📣 <b>Рассылка всем</b>\n\nОтправь сообщение.\n❌ Отмена — /cancel",
        parse_mode="HTML"
    )

@router.message(BroadcastState.waiting_content)
async def bc_got_content(message: Message, state: FSMContext):
    await state.update_data(bc_msg_id=message.message_id, bc_chat_id=message.chat.id)
    await state.set_state(BroadcastState.waiting_buttons)
    await message.answer(
        "👆 Сообщение получено!\n\n"
        "Добавить кнопки-ссылки? Каждую кнопку — отдельным сообщением:\n"
        "<code>Текст | https://ссылка | green</code>\n\n"
        "Цвета: <b>green</b> 🟢 · <b>blue</b> 🔵 · <b>red</b> 🔴 · без цвета — серый\n\n"
        "Или сразу смотри предпросмотр 👇",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_add_btn", BroadcastState.waiting_buttons)
async def bc_add_btn(callback: CallbackQuery):
    await callback.message.edit_text(
        "Отправь кнопку отдельным сообщением:\n"
        "<code>Текст | https://ссылка</code>\n"
        "<code>Текст | https://ссылка | green</code>\n"
        "<code>Текст | https://ссылка | blue</code>\n"
        "<code>Текст | https://ссылка | red</code>",
        parse_mode="HTML"
    )

@router.message(BroadcastState.waiting_buttons)
async def bc_got_button(message: Message, state: FSMContext):
    if not message.text or "|" not in message.text:
        await message.answer("❌ Формат: <code>Текст | https://ссылка</code> или с цветом: <code>Текст | https://ссылка | green</code>", parse_mode="HTML")
        return
    parts = [p.strip() for p in message.text.split("|")]
    btn_text = parts[0]
    url = parts[1] if len(parts) > 1 else ""
    color = parts[2].lower() if len(parts) > 2 else ""
    if not url.startswith("http"):
        await message.answer("❌ Ссылка должна начинаться с http://")
        return
    data = await state.get_data()
    buttons = data.get("buttons", [])
    buttons.append({"text": btn_text, "url": url, "color": color})
    await state.update_data(buttons=buttons)
    color_icons = {"green": "🟢", "blue": "🔵", "red": "🔴"}
    color_str = f" {color_icons.get(color, '')} {color}" if color else ""
    btn_list = "\n".join([f"  • {b['text']} {color_icons.get(b.get('color',''),'')}" for b in buttons])
    await message.answer(
        f"✅ Кнопка добавлена!\n\n<b>Все кнопки:</b>\n{btn_list}",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_preview")
async def bc_preview(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("bc_msg_id")
    from_chat = data.get("bc_chat_id")
    buttons = data.get("buttons", [])
    reply_markup = build_inline_kb(buttons)

    if not msg_id:
        await callback.answer("❌ Сначала отправь сообщение для рассылки", show_alert=True)
        return

    await callback.answer("Отправляю предпросмотр...")
    await callback.message.answer("👁 <b>Предпросмотр — так увидят пользователи:</b>", parse_mode="HTML")
    await bot.copy_message(
        chat_id=callback.from_user.id,
        from_chat_id=from_chat,
        message_id=msg_id,
        reply_markup=reply_markup
    )
    await callback.message.answer(
        "☝️ Всё верно? Запускай или вноси правки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="adm_bc_send")],
            [InlineKeyboardButton(text="➕ Добавить кнопку",    callback_data="adm_bc_add_btn")],
            [InlineKeyboardButton(text="🗑 Убрать все кнопки",  callback_data="adm_bc_clear_btns")],
            [InlineKeyboardButton(text="❌ Отмена",             callback_data="adm_menu")],
        ]),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_clear_btns")
async def bc_clear_btns(callback: CallbackQuery, state: FSMContext):
    await state.update_data(buttons=[])
    await callback.message.edit_text(
        "🗑 Кнопки удалены.\n\nМожешь добавить новые или запустить рассылку.",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_confirm")
async def bc_show_confirm(callback: CallbackQuery, state: FSMContext):
    """Показываем финальное подтверждение с кол-вом получателей."""
    data = await state.get_data()
    target = data.get("target", "all")
    buttons = data.get("buttons", [])
    btn_list = "\n".join([f"  • {b['text']}" for b in buttons]) if buttons else "  нет"
    label = "всем пользователям" if target == "all" else "только подписчикам"
    await callback.message.edit_text(
        f"📣 <b>Готово к отправке</b>\n\n"
        f"Получатели: <b>{label}</b>\n"
        f"Кнопки:\n{btn_list}\n\n"
        f"Нажми 👁 Предпросмотр чтобы проверить, или сразу запускай.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Предпросмотр",        callback_data="adm_bc_preview")],
            [InlineKeyboardButton(text="🚀 Запустить рассылку",  callback_data="adm_bc_send")],
            [InlineKeyboardButton(text="➕ Добавить кнопку",     callback_data="adm_bc_add_btn")],
            [InlineKeyboardButton(text="🗑 Убрать все кнопки",   callback_data="adm_bc_clear_btns")],
            [InlineKeyboardButton(text="❌ Отмена",              callback_data="adm_menu")],
        ]),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_send")
async def bc_send(callback: CallbackQuery, bot: Bot, db: Database, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    msg_id = data.get("bc_msg_id")
    from_chat = data.get("bc_chat_id")
    target = data.get("target", "all")
    buttons = data.get("buttons", [])
    reply_markup = build_inline_kb(buttons)

    if not msg_id:
        await callback.message.edit_text("❌ Нет сообщения для рассылки.")
        return

    user_ids = await db.get_all_user_ids() if target == "all" else await db.get_subscribed_user_ids()
    total = len(user_ids)
    sent = failed = 0
    status = await callback.message.answer(f"⏳ Запускаю... 0 / {total}")

    for i, uid in enumerate(user_ids):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat,
                                   message_id=msg_id, reply_markup=reply_markup)
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % 20 == 0:
            try:
                await status.edit_text(f"⏳ {i+1} / {total}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await db.log_broadcast(sent, failed)
    await status.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"<i>(ошибки = бот заблокирован у пользователя)</i>",
        reply_markup=kb_back(), parse_mode="HTML"
    )
