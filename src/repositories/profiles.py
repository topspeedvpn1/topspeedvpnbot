from __future__ import annotations

import time

from src.db import Database
from src.models import Profile, ProfilePort


class ProfileRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        *,
        panel_id: int,
        name: str,
        prefix: str,
        suffix: str,
        traffic_gb: int,
        expiry_days: int,
        ports: list[tuple[int, int, int]],
    ) -> int:
        now = int(time.time())
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                """
                INSERT INTO profiles(panel_id, name, prefix, suffix, traffic_gb, expiry_days, active, rr_index, created_at)
                VALUES(?, ?, ?, ?, ?, ?, 1, 0, ?)
                """,
                (panel_id, name, prefix, suffix, traffic_gb, expiry_days, now),
            )
            profile_id = int(cur.lastrowid)

            sort_order = 0
            for inbound_id, port, max_active in ports:
                await conn.execute(
                    """
                    INSERT INTO profile_ports(profile_id, inbound_id, port, max_active_clients, sort_order)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (profile_id, inbound_id, port, max_active, sort_order),
                )
                sort_order += 1

            await conn.execute(
                "INSERT OR IGNORE INTO profile_counters(profile_id, last_number) VALUES(?, 0)",
                (profile_id,),
            )

        return profile_id

    async def get_by_id(self, profile_id: int) -> Profile | None:
        row = await self.db.fetchone("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        return self._row_to_profile(row)

    async def get_by_name(self, name: str) -> Profile | None:
        row = await self.db.fetchone("SELECT * FROM profiles WHERE name = ?", (name,))
        return self._row_to_profile(row)

    async def list_profiles(self, active_only: bool = False) -> list[Profile]:
        if active_only:
            rows = await self.db.fetchall("SELECT * FROM profiles WHERE active = 1 ORDER BY id ASC")
        else:
            rows = await self.db.fetchall("SELECT * FROM profiles ORDER BY id ASC")
        return [self._row_to_profile(r) for r in rows if r is not None]

    async def set_active(self, profile_id: int, active: bool) -> None:
        await self.db.execute("UPDATE profiles SET active = ? WHERE id = ?", (1 if active else 0, profile_id))

    async def list_ports(self, profile_id: int) -> list[ProfilePort]:
        rows = await self.db.fetchall(
            "SELECT * FROM profile_ports WHERE profile_id = ? ORDER BY sort_order ASC, id ASC",
            (profile_id,),
        )
        return [
            ProfilePort(
                id=int(r["id"]),
                profile_id=int(r["profile_id"]),
                inbound_id=int(r["inbound_id"]),
                port=int(r["port"]),
                max_active_clients=int(r["max_active_clients"]),
                sort_order=int(r["sort_order"]),
            )
            for r in rows
        ]

    async def add_port(
        self,
        *,
        profile_id: int,
        inbound_id: int,
        port: int,
        max_active_clients: int,
    ) -> None:
        async with self.db.transaction() as conn:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM profile_ports WHERE profile_id = ?",
                (profile_id,),
            )
            row = await cur.fetchone()
            next_sort = int(row["next_sort"]) if row is not None else 0
            await conn.execute(
                """
                INSERT INTO profile_ports(profile_id, inbound_id, port, max_active_clients, sort_order)
                VALUES(?, ?, ?, ?, ?)
                """,
                (profile_id, inbound_id, port, max_active_clients, next_sort),
            )

    async def update_port_capacity(
        self,
        *,
        profile_id: int,
        port: int,
        max_active_clients: int,
    ) -> bool:
        existing = await self.db.fetchone(
            "SELECT id FROM profile_ports WHERE profile_id = ? AND port = ?",
            (profile_id, port),
        )
        if existing is None:
            return False
        await self.db.execute(
            "UPDATE profile_ports SET max_active_clients = ? WHERE profile_id = ? AND port = ?",
            (max_active_clients, profile_id, port),
        )
        return True

    async def set_rr_index(self, profile_id: int, rr_index: int) -> None:
        await self.db.execute("UPDATE profiles SET rr_index = ? WHERE id = ?", (rr_index, profile_id))

    @staticmethod
    def _row_to_profile(row) -> Profile | None:
        if row is None:
            return None
        return Profile(
            id=int(row["id"]),
            panel_id=int(row["panel_id"]),
            name=str(row["name"]),
            prefix=str(row["prefix"]),
            suffix=str(row["suffix"]),
            traffic_gb=int(row["traffic_gb"]),
            expiry_days=int(row["expiry_days"]),
            active=bool(row["active"]),
            rr_index=int(row["rr_index"]),
        )
