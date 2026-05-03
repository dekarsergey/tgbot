import aiosqlite
import csv
import io
import json
from datetime import datetime


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                last_name   TEXT,
                source      TEXT DEFAULT 'direct',
                subscribed  INTEGER DEFAULT 0,
                funnel_step INTEGER DEFAULT 0,
                joined_at   TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                event_type  TEXT NOT NULL,
                payload     TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS broadcasts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sent        INTEGER DEFAULT 0,
                failed      INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS funnel_steps (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                position     INTEGER NOT NULL,
                text         TEXT,
                media_type   TEXT,
                media_id     TEXT,
                buttons      TEXT DEFAULT '[]',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
        """)
        # Миграции для старых баз
        for col, definition in [
            ("funnel_step", "INTEGER DEFAULT 0"),
        ]:
            try:
                await self._conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ─── Users ───────────────────────────────────────────────────────────────

    async def upsert_user(self, user_id: int, username: str, first_name: str,
                          last_name: str, source: str = "direct"):
        now = datetime.utcnow().isoformat()
        await self._conn.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, source, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                last_seen  = excluded.last_seen
        """, (user_id, username, first_name, last_name, source, now, now))
        await self._conn.commit()

    async def set_subscribed(self, user_id: int, subscribed: bool):
        await self._conn.execute(
            "UPDATE users SET subscribed = ? WHERE user_id = ?",
            (1 if subscribed else 0, user_id)
        )
        await self._conn.commit()

    async def set_funnel_step(self, user_id: int, step: int):
        await self._conn.execute(
            "UPDATE users SET funnel_step = MAX(funnel_step, ?) WHERE user_id = ?",
            (step, user_id)
        )
        await self._conn.commit()

    async def get_user(self, user_id: int):
        async with self._conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()

    # ─── Events ──────────────────────────────────────────────────────────────

    async def log_event(self, user_id: int, event_type: str, payload: str = None):
        now = datetime.utcnow().isoformat()
        await self._conn.execute(
            "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?,?,?,?)",
            (user_id, event_type, payload, now)
        )
        await self._conn.commit()

    async def log_broadcast(self, sent: int, failed: int):
        now = datetime.utcnow().isoformat()
        await self._conn.execute(
            "INSERT INTO broadcasts (sent, failed, created_at) VALUES (?,?,?)",
            (sent, failed, now)
        )
        await self._conn.commit()

    # ─── Funnel Steps ─────────────────────────────────────────────────────────

    async def get_funnel_steps(self) -> list:
        async with self._conn.execute(
            "SELECT * FROM funnel_steps ORDER BY position ASC"
        ) as cur:
            return await cur.fetchall()

    async def get_funnel_step(self, step_id: int):
        async with self._conn.execute(
            "SELECT * FROM funnel_steps WHERE id = ?", (step_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_funnel_step_by_position(self, position: int):
        async with self._conn.execute(
            "SELECT * FROM funnel_steps WHERE position = ?", (position,)
        ) as cur:
            return await cur.fetchone()

    async def count_funnel_steps(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM funnel_steps") as cur:
            row = await cur.fetchone()
            return row[0]

    async def add_funnel_step(self, text: str, media_type: str, media_id: str,
                               buttons: list) -> int:
        now = datetime.utcnow().isoformat()
        # Получаем следующую позицию
        async with self._conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM funnel_steps"
        ) as cur:
            row = await cur.fetchone()
            position = row[0]
        cursor = await self._conn.execute(
            """INSERT INTO funnel_steps (position, text, media_type, media_id, buttons, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (position, text, media_type, media_id, json.dumps(buttons, ensure_ascii=False), now, now)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def update_funnel_step(self, step_id: int, text: str, media_type: str,
                                  media_id: str, buttons: list):
        now = datetime.utcnow().isoformat()
        await self._conn.execute(
            """UPDATE funnel_steps SET text=?, media_type=?, media_id=?, buttons=?, updated_at=?
               WHERE id=?""",
            (text, media_type, media_id, json.dumps(buttons, ensure_ascii=False), now, step_id)
        )
        await self._conn.commit()

    async def delete_funnel_step(self, step_id: int):
        # Получаем позицию удаляемого
        step = await self.get_funnel_step(step_id)
        if not step:
            return
        pos = step["position"]
        await self._conn.execute("DELETE FROM funnel_steps WHERE id = ?", (step_id,))
        # Сдвигаем позиции оставшихся
        await self._conn.execute(
            "UPDATE funnel_steps SET position = position - 1 WHERE position > ?", (pos,)
        )
        await self._conn.commit()

    async def move_funnel_step(self, step_id: int, direction: str):
        """direction: 'up' | 'down'"""
        step = await self.get_funnel_step(step_id)
        if not step:
            return
        pos = step["position"]
        target_pos = pos - 1 if direction == "up" else pos + 1
        # Находим соседа
        async with self._conn.execute(
            "SELECT id FROM funnel_steps WHERE position = ?", (target_pos,)
        ) as cur:
            neighbor = await cur.fetchone()
        if not neighbor:
            return
        # Меняем местами
        await self._conn.execute(
            "UPDATE funnel_steps SET position = ? WHERE id = ?", (target_pos, step_id)
        )
        await self._conn.execute(
            "UPDATE funnel_steps SET position = ? WHERE id = ?", (pos, neighbor["id"])
        )
        await self._conn.commit()

    # ─── Stats ───────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        stats = {}
        # Динамически считаем шаги воронки
        steps = await self.get_funnel_steps()
        queries = {
            "total_users":      "SELECT COUNT(*) FROM users",
            "subscribed":       "SELECT COUNT(*) FROM users WHERE subscribed = 1",
            "not_subscribed":   "SELECT COUNT(*) FROM users WHERE subscribed = 0",
            "today":            "SELECT COUNT(*) FROM users WHERE DATE(joined_at) = DATE('now')",
            "week":             "SELECT COUNT(*) FROM users WHERE joined_at >= datetime('now', '-7 days')",
            "month":            "SELECT COUNT(*) FROM users WHERE joined_at >= datetime('now', '-30 days')",
            "active_today":     "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now', '-1 day')",
            "active_week":      "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now', '-7 days')",
            "active_month":     "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= datetime('now', '-30 days')",
            "broadcasts_total": "SELECT COUNT(*) FROM broadcasts",
            "broadcasts_errors":"SELECT COALESCE(SUM(failed), 0) FROM broadcasts",
        }
        for key, query in queries.items():
            async with self._conn.execute(query) as cur:
                row = await cur.fetchone()
                stats[key] = row[0]
        # Статистика по каждому шагу воронки
        for i, step in enumerate(steps, 1):
            async with self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE funnel_step >= ?", (i,)
            ) as cur:
                row = await cur.fetchone()
                stats[f"funnel_step{i}"] = row[0]
        stats["funnel_total_steps"] = len(steps)
        return stats

    async def get_recent_users(self, limit: int = 10) -> list:
        async with self._conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

    async def get_sources(self) -> list:
        async with self._conn.execute("""
            SELECT source, COUNT(*) as cnt, SUM(subscribed) as subscribed_cnt
            FROM users GROUP BY source ORDER BY cnt DESC
        """) as cur:
            return await cur.fetchall()

    async def get_all_user_ids(self) -> list:
        async with self._conn.execute("SELECT user_id FROM users") as cur:
            return [r[0] for r in await cur.fetchall()]

    async def get_subscribed_user_ids(self) -> list:
        async with self._conn.execute(
            "SELECT user_id FROM users WHERE subscribed = 1"
        ) as cur:
            return [r[0] for r in await cur.fetchall()]

    async def export_csv(self) -> bytes:
        async with self._conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Username", "Имя", "Фамилия", "Источник",
                         "Подписан", "Шаг воронки", "Дата регистрации", "Последняя активность"])
        for r in rows:
            writer.writerow([
                r["user_id"], r["username"] or "", r["first_name"] or "",
                r["last_name"] or "", r["source"],
                "Да" if r["subscribed"] else "Нет",
                r["funnel_step"], r["joined_at"][:16], r["last_seen"][:16],
            ])
        return output.getvalue().encode("utf-8-sig")
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
        [InlineKeyboardButton(text="➕ Добавить кнопку",      callback_data="adm_bc_add_btn")],
        [InlineKeyboardButton(text="🚀 Запустить рассылку",   callback_data="adm_bc_confirm")],
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
    data = await state.get_data()
    step_key = "bc"
    await message.answer(
        "👆 Сообщение получено!\n\n"
        "Добавить кнопки-ссылки?\n"
        "<code>Текст | https://ссылка</code>",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_add_btn", BroadcastState.waiting_buttons)
async def bc_add_btn(callback: CallbackQuery):
    await callback.message.edit_text(
        "Отправь кнопку:\n<code>Текст | https://ссылка</code>",
        parse_mode="HTML"
    )

@router.message(BroadcastState.waiting_buttons)
async def bc_got_button(message: Message, state: FSMContext):
    if "|" not in message.text:
        await message.answer("❌ Формат: <code>Текст | https://ссылка</code>", parse_mode="HTML")
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
    color_str = f" 🎨 {color}" if color else ""
    await message.answer(
        f"✅ Кнопка добавлена: <b>{btn_text}</b>{color_str}\nВсего: <b>{len(buttons)}</b>",
        reply_markup=kb_broadcast_confirm(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "adm_bc_confirm")
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
    status = await callback.message.edit_text(f"⏳ 0 / {total}")

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
        f"✅ <b>Рассылка завершена!</b>\n📤 Отправлено: <b>{sent}</b>\n❌ Ошибок: <b>{failed}</b>",
        reply_markup=kb_back(), parse_mode="HTML"
    )
