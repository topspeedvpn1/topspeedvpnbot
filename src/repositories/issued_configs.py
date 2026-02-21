from __future__ import annotations

import time

from src.db import Database


class IssuedConfigRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def exists_config_name(self, config_name: str) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM issued_configs WHERE config_name = ? LIMIT 1", (config_name,)
        )
        return row is not None

    async def add_many(
        self,
        *,
        profile_id: int,
        panel_id: int,
        chat_id: int,
        records: list[tuple[int, str, str]],
    ) -> None:
        now = int(time.time())
        async with self.db.transaction() as conn:
            for inbound_id, config_name, sub_id in records:
                await conn.execute(
                    """
                    INSERT INTO issued_configs(
                        profile_id, panel_id, inbound_id, chat_id, config_name, sub_id, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (profile_id, panel_id, inbound_id, chat_id, config_name, sub_id, now),
                )
