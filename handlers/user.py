from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import Config
from database.db import Database

router = Router()


# ─── FSM ─────────────────────────────────────────────────────────────────────

class Chain(StatesGroup):
    step1 = State()
    step2 = State()
    step3 = State()
    step4 = State()


# ─── Keyboards ───────────────────────────────────────────────────────────────

def kb_check_sub() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="check_sub")
    ]])

def kb_start_chain() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Поехали!", callback_data="chain_step1")
    ]])

def kb_step(next_cb: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=next_cb)
    ]])

def kb_topics() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 ChatGPT & GPT-4o",     callback_data="topic_chatgpt")],
        [InlineKeyboardButton(text="🎨 Генерация изображений", callback_data="topic_images")],
        [InlineKeyboardButton(text="💼 ИИ для бизнеса",        callback_data="topic_biz")],
        [InlineKeyboardButton(text="🔮 Будущее ИИ",            callback_data="topic_future")],
    ])


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def is_subscribed(bot: Bot, user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ("left", "kicked", "restricted")
    except Exception:
        return False


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, config: Config, db: Database, state: FSMContext):
    await state.clear()
    subscribed = await is_subscribed(bot, message.from_user.id, config.CHANNEL_ID)

    if subscribed:
        await db.set_subscribed(message.from_user.id, True)
        await message.answer(
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            "Ты уже подписан на канал — отлично! 🎉\n"
            "Нажми кнопку, чтобы начать мини-курс по нейросетям.",
            reply_markup=kb_start_chain(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            "Чтобы получить бесплатный мини-курс по нейросетям, "
            "сначала подпишись на наш канал 👇\n\n"
            f"📣 <a href='https://t.me/{config.CHANNEL_ID.lstrip('@')}'>Перейти на канал</a>\n\n"
            "После подписки нажми кнопку ниже 👇",
            reply_markup=kb_check_sub(),
            parse_mode="HTML"
        )


# ─── Проверка подписки ────────────────────────────────────────────────────────

@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery, bot: Bot, config: Config, db: Database):
    subscribed = await is_subscribed(bot, callback.from_user.id, config.CHANNEL_ID)
    if subscribed:
        await db.set_subscribed(callback.from_user.id, True)
        await callback.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Добро пожаловать в мини-курс по нейросетям 🤖\n"
            "Нажми кнопку, чтобы начать!",
            reply_markup=kb_start_chain(),
            parse_mode="HTML"
        )
    else:
        await callback.answer(
            "❌ Ты ещё не подписан! Подпишись на канал и нажми снова.",
            show_alert=True
        )


# ─── Цепочка: Шаг 1 ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "chain_step1")
async def chain_step1(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Chain.step1)
    await db.set_funnel_step(callback.from_user.id, 1)
    await callback.message.edit_text(
        "🤖 <b>Урок 1: Что такое нейросети?</b>\n\n"
        "Нейросеть — это программа, которая учится на данных, как человеческий мозг учится на опыте.\n\n"
        "Сегодня ИИ умеет:\n"
        "• Писать тексты и код ✍️\n"
        "• Генерировать изображения 🎨\n"
        "• Анализировать данные 📊\n"
        "• Вести диалог как человек 💬\n\n"
        "ChatGPT, Midjourney, Claude — всё это нейросети.",
        reply_markup=kb_step("chain_step2", "Следующий урок →"),
        parse_mode="HTML"
    )


# ─── Цепочка: Шаг 2 ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "chain_step2")
async def chain_step2(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Chain.step2)
    await db.set_funnel_step(callback.from_user.id, 2)
    await callback.message.edit_text(
        "💡 <b>Урок 2: Как использовать ИИ прямо сейчас?</b>\n\n"
        "Топ-5 применений, которые экономят часы работы:\n\n"
        "1️⃣ <b>Тексты</b> — посты, статьи, письма за секунды\n"
        "2️⃣ <b>Код</b> — пиши программы без знания языков\n"
        "3️⃣ <b>Изображения</b> — Midjourney, DALL-E, Stable Diffusion\n"
        "4️⃣ <b>Анализ</b> — загрузи таблицу, получи выводы\n"
        "5️⃣ <b>Обучение</b> — ИИ как личный преподаватель 24/7\n\n"
        "Используешь хоть что-то из этого? 👇",
        reply_markup=kb_step("chain_step3", "Дальше! 🔥"),
        parse_mode="HTML"
    )


# ─── Цепочка: Шаг 3 ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "chain_step3")
async def chain_step3(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Chain.step3)
    await db.set_funnel_step(callback.from_user.id, 3)
    await callback.message.edit_text(
        "⚡️ <b>Урок 3: Промпты — язык общения с ИИ</b>\n\n"
        "Промпт — это твой запрос к нейросети. Чем точнее, тем лучше результат.\n\n"
        "<b>Плохой промпт:</b>\n"
        "«Напиши пост про бизнес»\n\n"
        "<b>Хороший промпт:</b>\n"
        "«Напиши пост для Instagram о том, как малый бизнес может использовать ChatGPT, "
        "в разговорном стиле, 150 слов, с призывом подписаться»\n\n"
        "Разница — как между «приготовь еду» и точным заказом в ресторане 🍽",
        reply_markup=kb_step("chain_step4", "Последний урок →"),
        parse_mode="HTML"
    )


# ─── Цепочка: Шаг 4 (финал) ──────────────────────────────────────────────────

@router.callback_query(F.data == "chain_step4")
async def chain_step4(callback: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Chain.step4)
    await db.set_funnel_step(callback.from_user.id, 4)
    await callback.message.edit_text(
        "🏆 <b>Финал: Выбери, что тебя интересует больше всего!</b>\n\n"
        "Мы подготовили углублённые материалы по каждой теме.\n"
        "Что хочешь изучить первым? 👇",
        reply_markup=kb_topics(),
        parse_mode="HTML"
    )
    await state.clear()


# ─── Выбор темы ───────────────────────────────────────────────────────────────

TOPIC_TEXTS = {
    "topic_chatgpt": (
        "🤖 <b>ChatGPT & GPT-4o</b>\n\n"
        "GPT-4o — самая мощная публичная модель OpenAI на 2024 год.\n\n"
        "Умеет:\n• Видеть изображения и описывать их\n"
        "• Работать с документами и таблицами\n"
        "• Писать и выполнять код\n"
        "• Общаться голосом в реальном времени\n\n"
        "🔗 Попробуй: chat.openai.com"
    ),
    "topic_images": (
        "🎨 <b>Генерация изображений</b>\n\n"
        "Топ инструменты:\n\n"
        "• <b>Midjourney</b> — лучшее качество, платный\n"
        "• <b>DALL-E 3</b> — внутри ChatGPT Plus\n"
        "• <b>Stable Diffusion</b> — бесплатный, локально\n"
        "• <b>Leonardo AI</b> — бесплатный онлайн\n\n"
        "Для старта рекомендую Leonardo AI — бесплатно и просто 🎯"
    ),
    "topic_biz": (
        "💼 <b>ИИ для бизнеса</b>\n\n"
        "Как компании экономят на ИИ:\n\n"
        "• Автоматизация поддержки клиентов (чат-боты)\n"
        "• Генерация контента для соцсетей\n"
        "• Анализ отзывов и обратной связи\n"
        "• Автоматические отчёты\n"
        "• Найм и обработка резюме\n\n"
        "Уже сейчас ИИ заменяет часть задач копирайтеров, операторов и аналитиков 📈"
    ),
    "topic_future": (
        "🔮 <b>Будущее ИИ</b>\n\n"
        "Что нас ждёт в ближайшие годы:\n\n"
        "• <b>AGI</b> — ИИ, равный человеку по интеллекту (OpenAI ставит 2-3 года)\n"
        "• <b>Агенты</b> — ИИ, который сам выполняет задачи без участия человека\n"
        "• <b>ИИ-сотрудники</b> — нанимаешь модель вместо фрилансера\n"
        "• <b>Персонализация</b> — твой личный ИИ, знающий всё о тебе\n\n"
        "Главный совет: начни использовать ИИ сейчас — это конкурентное преимущество 🚀"
    ),
}

@router.callback_query(F.data.startswith("topic_"))
async def show_topic(callback: CallbackQuery, db: Database):
    text = TOPIC_TEXTS.get(callback.data, "Скоро будет 🔜")
    await db.log_event(callback.from_user.id, "topic_selected", callback.data)
    await callback.message.edit_text(
        text + "\n\n─────────────────\n"
               "📣 Больше материалов — в канале. Следи за обновлениями!",
        parse_mode="HTML"
    )
