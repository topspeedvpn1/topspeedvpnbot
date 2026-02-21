from __future__ import annotations

import asyncio
import secrets
import string
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.db import Database
from src.models import AllocationResult
from src.repositories.panels import PanelRepository
from src.repositories.profiles import ProfileRepository
from src.services.crypto import CryptoService
from src.services.link_resolver import LinkResolverService
from src.services.xui_client import XUIClient, XUIError


class AllocationError(Exception):
    pass


@dataclass(slots=True)
class _PortRuntime:
    inbound_id: int
    port: int
    max_active_clients: int
    active_clients: int
    protocol: str


class AllocatorService:
    def __init__(
        self,
        *,
        db: Database,
        profiles_repo: ProfileRepository,
        panels_repo: PanelRepository,
        crypto: CryptoService,
        verify_tls: bool,
        timeout_seconds: int,
    ) -> None:
        self.db = db
        self.profiles_repo = profiles_repo
        self.panels_repo = panels_repo
        self.crypto = crypto
        self.verify_tls = verify_tls
        self.timeout_seconds = timeout_seconds
        self._profile_locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, profile_id: int) -> asyncio.Lock:
        lock = self._profile_locks.get(profile_id)
        if lock is None:
            lock = asyncio.Lock()
            self._profile_locks[profile_id] = lock
        return lock

    async def get_capacity_report(self, profile_id: int) -> dict[str, Any]:
        profile = await self.profiles_repo.get_by_id(profile_id)
        if profile is None:
            raise AllocationError("Profile not found")

        panel = await self.panels_repo.get_by_id(profile.panel_id)
        if panel is None:
            raise AllocationError("Panel not found for profile")

        password = self.crypto.decrypt(panel.password_enc)
        ports = await self.profiles_repo.list_ports(profile.id)
        if not ports:
            raise AllocationError("Profile has no configured ports")

        async with XUIClient(
            base_url=panel.base_url,
            username=panel.username,
            password=password,
            verify_tls=self.verify_tls,
            timeout_seconds=self.timeout_seconds,
        ) as xui:
            inbounds = await xui.list_inbounds()

        port_runtimes = self._build_port_runtime(ports, inbounds)
        total_capacity = sum(p.max_active_clients for p in port_runtimes)
        used = sum(p.active_clients for p in port_runtimes)

        return {
            "profile_name": profile.name,
            "total_capacity": total_capacity,
            "used": used,
            "free": total_capacity - used,
            "ports": [
                {
                    "port": p.port,
                    "inbound_id": p.inbound_id,
                    "used": p.active_clients,
                    "max": p.max_active_clients,
                    "free": max(0, p.max_active_clients - p.active_clients),
                }
                for p in port_runtimes
            ],
        }

    async def allocate_and_create(
        self,
        *,
        profile_id: int,
        quantity: int,
        chat_id: int,
    ) -> AllocationResult:
        if quantity not in {10, 50, 100}:
            raise AllocationError("Quantity must be one of: 10, 50, 100")

        lock = self._get_lock(profile_id)
        async with lock:
            return await self._allocate_locked(profile_id=profile_id, quantity=quantity, chat_id=chat_id)

    async def _allocate_locked(self, *, profile_id: int, quantity: int, chat_id: int) -> AllocationResult:
        profile = await self.profiles_repo.get_by_id(profile_id)
        if profile is None or not profile.active:
            raise AllocationError("Profile is not available")

        panel = await self.panels_repo.get_by_id(profile.panel_id)
        if panel is None or not panel.active:
            raise AllocationError("Panel is not available")

        ports = await self.profiles_repo.list_ports(profile.id)
        if not ports:
            raise AllocationError("Profile has no ports configured")

        password = self.crypto.decrypt(panel.password_enc)

        async with XUIClient(
            base_url=panel.base_url,
            username=panel.username,
            password=password,
            verify_tls=self.verify_tls,
            timeout_seconds=self.timeout_seconds,
        ) as xui:
            inbounds = await xui.list_inbounds()
            port_runtimes = self._build_port_runtime(ports, inbounds)

            total_free = sum(max(0, p.max_active_clients - p.active_clients) for p in port_runtimes)
            if total_free < quantity:
                raise AllocationError(
                    f"Insufficient capacity. Free={total_free}, requested={quantity}."
                )

            existing_emails = self._extract_existing_emails(inbounds)

            async with self.db.transaction() as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO profile_counters(profile_id, last_number) VALUES(?, 0)",
                    (profile.id,),
                )

                cur = await conn.execute(
                    "SELECT last_number FROM profile_counters WHERE profile_id = ?",
                    (profile.id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise AllocationError("Counter row missing")

                last_number = int(row["last_number"])
                rr_cursor = int(profile.rr_index) % len(port_runtimes)

                staged_clients: list[dict[str, Any]] = []
                staged_records: list[tuple[int, str, str]] = []
                assigned_by_inbound: dict[int, list[dict[str, Any]]] = defaultdict(list)
                local_used = [0 for _ in port_runtimes]
                names_in_request: set[str] = set()

                for _ in range(quantity):
                    config_name, last_number = await self._next_unique_name(
                        conn=conn,
                        prefix=profile.prefix,
                        suffix=profile.suffix,
                        start_number=last_number,
                        existing_emails=existing_emails,
                        names_in_request=names_in_request,
                    )

                    selected_idx = self._select_next_port_index(
                        port_runtimes,
                        local_used,
                        start_index=rr_cursor,
                    )
                    if selected_idx is None:
                        raise AllocationError("Capacity check failed during allocation")

                    runtime_port = port_runtimes[selected_idx]
                    local_used[selected_idx] += 1
                    rr_cursor = (selected_idx + 1) % len(port_runtimes)

                    client = self._build_client_payload(
                        protocol=runtime_port.protocol,
                        email=config_name,
                        traffic_gb=profile.traffic_gb,
                        expiry_days=profile.expiry_days,
                    )

                    staged_clients.append(client)
                    assigned_by_inbound[runtime_port.inbound_id].append(client)
                    staged_records.append((runtime_port.inbound_id, config_name, str(client["subId"])))

                for inbound_id, clients in assigned_by_inbound.items():
                    await xui.add_clients(inbound_id, clients)

                all_links: list[str] = []
                for client in staged_clients:
                    sub_id = str(client["subId"])
                    raw_text = await xui.fetch_subscription(sub_id)
                    links = LinkResolverService.extract_links(raw_text)
                    all_links.extend(links)

                now = int(time.time())
                for inbound_id, config_name, sub_id in staged_records:
                    await conn.execute(
                        """
                        INSERT INTO issued_configs(
                            profile_id, panel_id, inbound_id, chat_id, config_name, sub_id, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (profile.id, panel.id, inbound_id, chat_id, config_name, sub_id, now),
                    )

                await conn.execute(
                    "UPDATE profile_counters SET last_number = ? WHERE profile_id = ?",
                    (last_number, profile.id),
                )
                await conn.execute(
                    "UPDATE profiles SET rr_index = ? WHERE id = ?",
                    (rr_cursor, profile.id),
                )

        return AllocationResult(profile_name=profile.name, quantity=quantity, links=all_links)

    async def _next_unique_name(
        self,
        *,
        conn,
        prefix: str,
        suffix: str,
        start_number: int,
        existing_emails: set[str],
        names_in_request: set[str],
    ) -> tuple[str, int]:
        number = start_number
        while True:
            number += 1
            name = f"{prefix}{number}{suffix}"
            lowered = name.lower()

            if lowered in existing_emails or lowered in names_in_request:
                continue

            cur = await conn.execute(
                "SELECT 1 FROM issued_configs WHERE config_name = ? LIMIT 1",
                (name,),
            )
            row = await cur.fetchone()
            if row is not None:
                continue

            names_in_request.add(lowered)
            return name, number

    @staticmethod
    def _extract_existing_emails(inbounds: list[dict[str, Any]]) -> set[str]:
        result: set[str] = set()
        for inbound in inbounds:
            for stat in inbound.get("clientStats") or []:
                email = str(stat.get("email") or "").strip().lower()
                if email:
                    result.add(email)
        return result

    @staticmethod
    def _build_port_runtime(profile_ports, inbounds: list[dict[str, Any]]) -> list[_PortRuntime]:
        inbound_by_id = {int(i.get("id")): i for i in inbounds if i.get("id") is not None}
        inbound_by_port: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for inbound in inbounds:
            try:
                port = int(inbound.get("port"))
            except (TypeError, ValueError):
                continue
            inbound_by_port[port].append(inbound)

        runtimes: list[_PortRuntime] = []
        for profile_port in profile_ports:
            inbound = inbound_by_id.get(profile_port.inbound_id)
            if inbound is None:
                matches = inbound_by_port.get(profile_port.port, [])
                if len(matches) == 1:
                    inbound = matches[0]
                elif len(matches) == 0:
                    raise AllocationError(
                        f"Inbound for port {profile_port.port} not found on panel"
                    )
                else:
                    raise AllocationError(
                        f"Multiple inbounds found for port {profile_port.port}; use unique ports"
                    )

            active_count = 0
            for stat in inbound.get("clientStats") or []:
                enabled = stat.get("enable")
                if enabled is False:
                    continue
                active_count += 1

            runtime = _PortRuntime(
                inbound_id=int(inbound.get("id")),
                port=int(inbound.get("port")),
                max_active_clients=int(profile_port.max_active_clients),
                active_clients=active_count,
                protocol=str(inbound.get("protocol") or "").lower(),
            )
            runtimes.append(runtime)

        return runtimes

    @staticmethod
    def _select_next_port_index(
        port_runtimes: list[_PortRuntime],
        local_used: list[int],
        *,
        start_index: int,
    ) -> int | None:
        count = len(port_runtimes)
        for offset in range(count):
            idx = (start_index + offset) % count
            runtime = port_runtimes[idx]
            used = runtime.active_clients + local_used[idx]
            if used < runtime.max_active_clients:
                return idx
        return None

    @staticmethod
    def _build_client_payload(
        *,
        protocol: str,
        email: str,
        traffic_gb: int,
        expiry_days: int,
    ) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        expiry = 0 if expiry_days <= 0 else now_ms + (expiry_days * 24 * 60 * 60 * 1000)
        total_bytes = int(traffic_gb) * 1024 * 1024 * 1024

        payload: dict[str, Any] = {
            "email": email,
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry,
            "enable": True,
            "subId": "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16)),
            "comment": "",
            "tgId": 0,
        }

        if protocol == "trojan":
            payload["password"] = uuid.uuid4().hex
        elif protocol == "shadowsocks":
            payload["password"] = secrets.token_urlsafe(16)
        elif protocol in {"vmess", "vless"}:
            payload["id"] = str(uuid.uuid4())
            payload["security"] = "auto"
            payload["flow"] = ""
        else:
            raise AllocationError(f"Unsupported inbound protocol for auto client creation: {protocol}")

        return payload
