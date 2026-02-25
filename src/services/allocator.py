from __future__ import annotations

import asyncio
import base64
import json
import secrets
import string
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from src.db import Database
from src.models import AllocationResult
from src.repositories.panels import PanelRepository
from src.repositories.profiles import ProfileRepository
from src.services.crypto import CryptoService
from src.services.link_resolver import LinkResolverError, LinkResolverService
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


@dataclass(slots=True)
class _StagedClient:
    inbound_id: int
    config_name: str
    sub_id: str
    client: dict[str, Any]


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
                staged_allocations: list[_StagedClient] = []
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

                    selected_idx = self._select_next_port_index_fill_first(port_runtimes, local_used)
                    if selected_idx is None:
                        raise AllocationError("Capacity check failed during allocation")

                    runtime_port = port_runtimes[selected_idx]
                    local_used[selected_idx] += 1

                    client = self._build_client_payload(
                        protocol=runtime_port.protocol,
                        email=config_name,
                        traffic_gb=profile.traffic_gb,
                        expiry_days=profile.expiry_days,
                    )

                    assigned_by_inbound[runtime_port.inbound_id].append(client)
                    staged_allocations.append(
                        _StagedClient(
                            inbound_id=runtime_port.inbound_id,
                            config_name=config_name,
                            sub_id=str(client["subId"]),
                            client=client,
                        )
                    )

                for inbound_id, clients in assigned_by_inbound.items():
                    await xui.add_clients(inbound_id, clients)

                all_links: list[str] = []
                inbound_by_id = {int(i.get("id")): i for i in inbounds if i.get("id") is not None}
                settings = await xui.get_settings()

                for alloc in staged_allocations:
                    links: list[str] = []
                    if settings.sub_enable:
                        try:
                            raw_text = await xui.fetch_subscription(alloc.sub_id)
                            links = LinkResolverService.extract_links(raw_text)
                        except (XUIError, LinkResolverError):
                            links = []

                    if not links:
                        inbound = inbound_by_id.get(alloc.inbound_id)
                        fallback = self._build_direct_link_fallback(
                            inbound=inbound,
                            client=alloc.client,
                            config_name=alloc.config_name,
                            base_url=panel.base_url,
                        )
                        if fallback is not None:
                            links = [fallback]

                    if not links:
                        raise AllocationError(
                            f"Failed to build direct link for config `{alloc.config_name}`"
                        )

                    all_links.extend(links)

                now = int(time.time())
                for alloc in staged_allocations:
                    await conn.execute(
                        """
                        INSERT INTO issued_configs(
                            profile_id, panel_id, inbound_id, chat_id, config_name, sub_id, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (profile.id, panel.id, alloc.inbound_id, chat_id, alloc.config_name, alloc.sub_id, now),
                    )

                await conn.execute(
                    "UPDATE profile_counters SET last_number = ? WHERE profile_id = ?",
                    (last_number, profile.id),
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
    def _select_next_port_index_fill_first(
        port_runtimes: list[_PortRuntime],
        local_used: list[int],
    ) -> int | None:
        for idx, runtime in enumerate(port_runtimes):
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

    @staticmethod
    def _parse_json_obj(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _extract_host_port(base_url: str, inbound: dict[str, Any], stream: dict[str, Any]) -> tuple[str, int]:
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
        try:
            port = int(inbound.get("port"))
        except (TypeError, ValueError):
            port = 0

        external_proxy = stream.get("externalProxy")
        if isinstance(external_proxy, list) and external_proxy:
            first = external_proxy[0]
            if isinstance(first, dict):
                ext_host = str(first.get("dest") or "").strip()
                if ext_host:
                    host = ext_host
                try:
                    ext_port = int(first.get("port"))
                except (TypeError, ValueError):
                    ext_port = 0
                if ext_port > 0:
                    port = ext_port

        if port <= 0 and parsed.port:
            port = int(parsed.port)
        return host, port

    @staticmethod
    def _first_str(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        return ""

    @classmethod
    def _apply_stream_query(cls, params: dict[str, str], stream: dict[str, Any], network: str) -> None:
        net = network.lower()
        if net == "tcp":
            tcp = cls._parse_json_obj(stream.get("tcpSettings"))
            header = cls._parse_json_obj(tcp.get("header"))
            header_type = str(header.get("type") or "none")
            params["headerType"] = header_type
            if header_type == "http":
                request = cls._parse_json_obj(header.get("request"))
                path = cls._first_str(request.get("path"))
                if path:
                    params["path"] = path
                headers = cls._parse_json_obj(request.get("headers"))
                host = cls._first_str(headers.get("Host"))
                if host:
                    params["host"] = host
        elif net == "ws":
            ws = cls._parse_json_obj(stream.get("wsSettings"))
            path = str(ws.get("path") or "")
            if path:
                params["path"] = path
            headers = cls._parse_json_obj(ws.get("headers"))
            host = cls._first_str(headers.get("Host"))
            if host:
                params["host"] = host
        elif net == "grpc":
            grpc = cls._parse_json_obj(stream.get("grpcSettings"))
            service = str(grpc.get("serviceName") or "")
            if service:
                params["serviceName"] = service

    @classmethod
    def _apply_security_query(cls, params: dict[str, str], stream: dict[str, Any], security: str) -> None:
        sec = security.lower()
        if sec == "tls":
            tls = cls._parse_json_obj(stream.get("tlsSettings"))
            sni = str(tls.get("serverName") or "")
            if sni:
                params["sni"] = sni
            alpn = tls.get("alpn")
            if isinstance(alpn, list) and alpn:
                params["alpn"] = ",".join(str(x) for x in alpn if str(x))
            fp = str(tls.get("fingerprint") or "")
            if fp:
                params["fp"] = fp
        elif sec == "reality":
            reality = cls._parse_json_obj(stream.get("realitySettings"))
            names = reality.get("serverNames")
            if isinstance(names, list) and names:
                sni = cls._first_str(names)
                if sni:
                    params["sni"] = sni
            public_key = str(reality.get("publicKey") or "")
            if public_key:
                params["pbk"] = public_key
            short_ids = reality.get("shortIds")
            if isinstance(short_ids, list) and short_ids:
                sid = cls._first_str(short_ids)
                if sid:
                    params["sid"] = sid
            spider = str(reality.get("spiderX") or "")
            if spider:
                params["spx"] = spider
            fp = str(reality.get("fingerprint") or "")
            if fp:
                params["fp"] = fp

    @classmethod
    def _build_direct_link_fallback(
        cls,
        *,
        inbound: dict[str, Any] | None,
        client: dict[str, Any],
        config_name: str,
        base_url: str,
    ) -> str | None:
        if not inbound:
            return None

        protocol = str(inbound.get("protocol") or "").lower()
        stream = cls._parse_json_obj(inbound.get("streamSettings"))
        settings = cls._parse_json_obj(inbound.get("settings"))
        network = str(stream.get("network") or "tcp")
        security = str(stream.get("security") or "none")
        host, port = cls._extract_host_port(base_url, inbound, stream)
        if not host or port <= 0:
            return None

        fragment = quote(config_name, safe="-._~")

        if protocol == "vless":
            client_id = str(client.get("id") or "")
            if not client_id:
                return None
            params: dict[str, str] = {
                "type": network,
                "security": security,
                "encryption": "none",
            }
            flow = str(client.get("flow") or "")
            if flow:
                params["flow"] = flow
            cls._apply_stream_query(params, stream, network)
            cls._apply_security_query(params, stream, security)
            return f"vless://{client_id}@{host}:{port}?{urlencode(params)}#{fragment}"

        if protocol == "trojan":
            password = str(client.get("password") or "")
            if not password:
                return None
            params = {"type": network, "security": security}
            cls._apply_stream_query(params, stream, network)
            cls._apply_security_query(params, stream, security)
            return f"trojan://{password}@{host}:{port}?{urlencode(params)}#{fragment}"

        if protocol == "shadowsocks":
            password = str(client.get("password") or "")
            method = str(settings.get("method") or "aes-128-gcm")
            if not password:
                return None
            raw = f"{method}:{password}".encode()
            userinfo = base64.urlsafe_b64encode(raw).decode().rstrip("=")
            return f"ss://{userinfo}@{host}:{port}#{fragment}"

        if protocol == "vmess":
            client_id = str(client.get("id") or "")
            if not client_id:
                return None
            vmess: dict[str, str] = {
                "v": "2",
                "ps": config_name,
                "add": host,
                "port": str(port),
                "id": client_id,
                "aid": "0",
                "scy": str(client.get("security") or "auto"),
                "net": network,
                "type": "none",
                "host": "",
                "path": "",
                "tls": "tls" if security in {"tls", "reality"} else "",
                "sni": "",
            }
            params: dict[str, str] = {}
            cls._apply_stream_query(params, stream, network)
            cls._apply_security_query(params, stream, security)
            vmess["type"] = params.get("headerType", "none")
            vmess["host"] = params.get("host", "")
            vmess["path"] = params.get("path", params.get("serviceName", ""))
            vmess["sni"] = params.get("sni", "")
            token = base64.b64encode(
                json.dumps(vmess, ensure_ascii=False, separators=(",", ":")).encode()
            ).decode()
            return f"vmess://{token}"

        return None
