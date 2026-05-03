import json
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

from config import Config
from database.db import Database

router = Router()


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def is_subscribed(bot: Bot, user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ("left", "kicked", "restricted")
    except Exception:
        return False


def kb_check_sub(channel: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📣 Перейти на канал",
            url=f"https://t.me/{channel.lstrip('@')}"
        )],
        [InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="check_sub")],
    ])

def kb_start_funnel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Начать!", callback_data="funnel_next_0")
    ]])

def build_step_kb(step_id: int, buttons_json: str, position: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    try:
        buttons = json.loads(buttons_json or "[]")
        STYLE_MAP = {"green":"success","red":"danger","blue":"primary",
                     "success":"success","danger":"danger","primary":"primary"}
        for btn in buttons:
            if btn.get("url"):
                style = STYLE_MAP.get(btn.get("color", "").lower())
                extra = {"style": style} if style else {}
                rows.append([InlineKeyboardButton(text=btn["text"], url=btn["url"], **extra)])
            else:
                rows.append([InlineKeyboardButton(text=btn["text"], callback_data=btn.get("cb", "noop"))])
    except Exception:
        pass

    # Кнопка навигации
    if position < total:
        rows.append([InlineKeyboardButton(text="Далее →", callback_data=f"funnel_next_{position}")])

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_funnel_step(target, step, position: int, total: int):
    """Отправляет шаг воронки. target — Message или CallbackQuery."""
    kb = build_step_kb(step["id"], step["buttons"], position, total)
    text = step["text"] or ""
    media_type = step["media_type"]
    media_id = step["media_id"]

    msg = target if isinstance(target, Message) else target.message

    if media_type == "photo":
        await msg.answer_photo(photo=media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    elif media_type == "video":
        await msg.answer_video(video=media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    elif media_type == "document":
        await msg.answer_document(document=media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    elif media_type == "animation":
        await msg.answer_animation(animation=media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, config: Config, db: Database, state: FSMContext):
    await state.clear()
    subscribed = await is_subscribed(bot, message.from_user.id, config.CHANNEL_ID)

    if subscribed:
        await db.set_subscribed(message.from_user.id, True)
        total = await db.count_funnel_steps()
        if total == 0:
            await message.answer(
                f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
                "Ты уже подписан на канал ✅\nСкоро здесь появится контент!",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
                "Ты уже подписан — отлично! 🎉\nНажми кнопку чтобы начать:",
                reply_markup=kb_start_funnel(),
                parse_mode="HTML"
            )
    else:
        channel = config.CHANNEL_ID
        await message.answer(
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            "Чтобы получить материалы, сначала подпишись на канал 👇",
            reply_markup=kb_check_sub(channel),
            parse_mode="HTML"
        )


# ─── Проверка подписки ────────────────────────────────────────────────────────

@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery, bot: Bot, config: Config, db: Database):
    subscribed = await is_subscribed(bot, callback.from_user.id, config.CHANNEL_ID)
    if subscribed:
        await db.set_subscribed(callback.from_user.id, True)
        total = await db.count_funnel_steps()
        if total == 0:
            await callback.message.edit_text(
                "✅ <b>Подписка подтверждена!</b>\nСкоро здесь появится контент!",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                "✅ <b>Подписка подтверждена!</b>\nНажми кнопку чтобы начать 👇",
                reply_markup=kb_start_funnel(),
                parse_mode="HTML"
            )
    else:
        await callback.answer(
            "❌ Ты ещё не подписан! Подпишись и нажми снова.",
            show_alert=True
        )


# ─── Навигация по воронке ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("funnel_next_"))
async def funnel_next(callback: CallbackQuery, db: Database):
    # funnel_next_<текущая_позиция> → показываем позицию + 1
    current = int(callback.data.split("_")[-1])
    next_pos = current + 1

    steps = await db.get_funnel_steps()
    total = len(steps)

    if next_pos > total or total == 0:
        await callback.answer("Это был последний шаг!", show_alert=True)
        return

    step = steps[next_pos - 1]  # position с 1, индекс с 0
    await db.set_funnel_step(callback.from_user.id, next_pos)
    await db.log_event(callback.from_user.id, "funnel_step", str(next_pos))

    await send_funnel_step(callback, step, next_pos, total)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()
