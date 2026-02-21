from __future__ import annotations

import time

from src.db import Database
from src.models import Panel


class PanelRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, name: str, base_url: str, username: str, password_enc: str) -> None:
        now = int(time.time())
        await self.db.execute(
            """
            INSERT INTO panels(name, base_url, username, password_enc, created_at, active)
            VALUES(?, ?, ?, ?, ?, 1)
            ON CONFLICT(name)
            DO UPDATE SET
              base_url = excluded.base_url,
              username = excluded.username,
              password_enc = excluded.password_enc,
              active = 1
            """,
            (name, base_url, username, password_enc, now),
        )

    async def get_by_id(self, panel_id: int) -> Panel | None:
        row = await self.db.fetchone("SELECT * FROM panels WHERE id = ?", (panel_id,))
        return self._row_to_panel(row)

    async def get_by_name(self, name: str) -> Panel | None:
        row = await self.db.fetchone("SELECT * FROM panels WHERE name = ?", (name,))
        return self._row_to_panel(row)

    async def list_panels(self, active_only: bool = False) -> list[Panel]:
        if active_only:
            rows = await self.db.fetchall("SELECT * FROM panels WHERE active = 1 ORDER BY id ASC")
        else:
            rows = await self.db.fetchall("SELECT * FROM panels ORDER BY id ASC")
        return [self._row_to_panel(r) for r in rows if r is not None]

    async def set_active(self, panel_id: int, active: bool) -> None:
        await self.db.execute("UPDATE panels SET active = ? WHERE id = ?", (1 if active else 0, panel_id))

    @staticmethod
    def _row_to_panel(row) -> Panel | None:
        if row is None:
            return None
        return Panel(
            id=int(row["id"]),
            name=str(row["name"]),
            base_url=str(row["base_url"]),
            username=str(row["username"]),
            password_enc=str(row["password_enc"]),
            active=bool(row["active"]),
        )
