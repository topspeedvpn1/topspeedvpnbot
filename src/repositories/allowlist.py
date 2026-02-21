from __future__ import annotations

import time

from src.db import Database


class AllowlistRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, chat_id: int, note: str = "") -> None:
        now = int(time.time())
        await self.db.execute(
            """
            INSERT INTO allowed_users(chat_id, note, created_at)
            VALUES(?, ?, ?)
            ON CONFLICT(chat_id)
            DO UPDATE SET note = excluded.note
            """,
            (chat_id, note, now),
        )

    async def remove(self, chat_id: int) -> None:
        await self.db.execute("DELETE FROM allowed_users WHERE chat_id = ?", (chat_id,))

    async def is_allowed(self, chat_id: int) -> bool:
        row = await self.db.fetchone("SELECT 1 FROM allowed_users WHERE chat_id = ?", (chat_id,))
        return row is not None

    async def list_users(self) -> list[tuple[int, str]]:
        rows = await self.db.fetchall(
            "SELECT chat_id, COALESCE(note, '') AS note FROM allowed_users ORDER BY created_at ASC"
        )
        return [(int(r["chat_id"]), str(r["note"])) for r in rows]
