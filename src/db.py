from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS allowed_users (
  chat_id INTEGER PRIMARY KEY,
  note TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS panels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL,
  username TEXT NOT NULL,
  password_enc TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  panel_id INTEGER NOT NULL,
  name TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL UNIQUE,
  suffix TEXT NOT NULL DEFAULT '',
  traffic_gb INTEGER NOT NULL,
  expiry_days INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  rr_index INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_ports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  inbound_id INTEGER NOT NULL,
  port INTEGER NOT NULL,
  max_active_clients INTEGER NOT NULL,
  sort_order INTEGER NOT NULL,
  UNIQUE(profile_id, port),
  FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_counters (
  profile_id INTEGER PRIMARY KEY,
  last_number INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS issued_configs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  panel_id INTEGER NOT NULL,
  inbound_id INTEGER NOT NULL,
  chat_id INTEGER NOT NULL,
  config_name TEXT NOT NULL UNIQUE,
  sub_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
  FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_issued_configs_profile_created
  ON issued_configs(profile_id, created_at);
CREATE INDEX IF NOT EXISTS idx_profile_ports_profile_sort
  ON profile_ports(profile_id, sort_order);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_lock = asyncio.Lock()

    async def init(self) -> None:
        async with self._init_lock:
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.executescript(SCHEMA_SQL)
                await conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(sql, params)
            await conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            cursor = await conn.execute(sql, params)
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            cursor = await conn.execute(sql, params)
            return await cursor.fetchall()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self.db_path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("BEGIN IMMEDIATE")
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()
