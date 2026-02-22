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

    async def get_user(self, chat_id: int) -> tuple[int, str] | None:
        row = await self.db.fetchone(
            "SELECT chat_id, COALESCE(note, '') AS note FROM allowed_users WHERE chat_id = ?",
            (chat_id,),
        )
        if row is None:
            return None
        return (int(row["chat_id"]), str(row["note"]))

    async def set_profile_access(self, chat_id: int, profile_ids: list[int]) -> None:
        now = int(time.time())
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM user_profile_access WHERE chat_id = ?", (chat_id,))
            for profile_id in profile_ids:
                await conn.execute(
                    """
                    INSERT INTO user_profile_access(chat_id, profile_id, created_at)
                    VALUES(?, ?, ?)
                    """,
                    (chat_id, profile_id, now),
                )

    async def get_profile_access(self, chat_id: int) -> set[int]:
        rows = await self.db.fetchall(
            "SELECT profile_id FROM user_profile_access WHERE chat_id = ?",
            (chat_id,),
        )
        return {int(r["profile_id"]) for r in rows}
