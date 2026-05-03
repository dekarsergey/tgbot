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
