from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class XUIError(Exception):
    pass


@dataclass(slots=True)
class XUISettings:
    sub_uri: str
    sub_path: str
    sub_port: int


class XUIClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        verify_tls: bool,
        timeout_seconds: int = 30,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.username = username
        self.password = password
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=verify_tls,
            follow_redirects=True,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "topspeedvpnbot/1.0",
            },
        )
        self._logged_in = False

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def test_connection(self) -> int:
        inbounds = await self.list_inbounds()
        return len(inbounds)

    async def list_inbounds(self) -> list[dict[str, Any]]:
        msg = await self._request_panel_json("GET", "/panel/api/inbounds/list")
        obj = msg.get("obj")
        if not isinstance(obj, list):
            raise XUIError("Invalid inbounds response")
        return obj

    async def add_clients(self, inbound_id: int, clients: list[dict[str, Any]]) -> None:
        if not clients:
            return
        payload = {
            "id": str(inbound_id),
            "settings": json.dumps({"clients": clients}, ensure_ascii=False),
        }
        await self._request_panel_json("POST", "/panel/api/inbounds/addClient", data=payload)

    async def get_settings(self) -> XUISettings:
        msg = await self._request_panel_json("POST", "/panel/setting/all", data={})
        obj = msg.get("obj")
        if not isinstance(obj, dict):
            raise XUIError("Invalid panel settings response")
        sub_uri = str(obj.get("subURI") or "").strip()
        sub_path = str(obj.get("subPath") or "/sub/").strip() or "/sub/"
        sub_port_raw = obj.get("subPort")
        try:
            sub_port = int(sub_port_raw)
        except (TypeError, ValueError):
            sub_port = 0
        return XUISettings(sub_uri=sub_uri, sub_path=sub_path, sub_port=sub_port)

    async def fetch_subscription(self, sub_id: str) -> str:
        settings = await self.get_settings()
        urls = self._subscription_candidate_urls(settings, sub_id)
        errors: list[str] = []

        for url in urls:
            try:
                response = await self._client.get(url)
            except httpx.HTTPError as exc:
                errors.append(f"{url} -> connect error: {exc}")
                continue

            if response.status_code != 200:
                errors.append(f"{url} -> status {response.status_code}")
                continue

            text = response.text.strip()
            if not text or text == "Error!":
                errors.append(f"{url} -> empty/error body")
                continue

            return text

        details = " | ".join(errors) if errors else "unknown subscription error"
        raise XUIError(f"Subscription fetch failed: {details}")

    def _subscription_candidate_urls(self, settings: XUISettings, sub_id: str) -> list[str]:
        primary = self._build_subscription_url(settings, sub_id)
        urls = [primary]

        # Fallback for installations where subscription is served on panel port.
        if not settings.sub_uri and settings.sub_port > 0:
            parsed = urlparse(self.base_url)
            scheme = parsed.scheme or "https"
            host = parsed.hostname
            base_port = parsed.port
            if host and base_port and base_port != settings.sub_port:
                sub_path = settings.sub_path or "/sub/"
                if not sub_path.startswith("/"):
                    sub_path = "/" + sub_path
                if not sub_path.endswith("/"):
                    sub_path += "/"
                fallback = f"{scheme}://{host}:{base_port}{sub_path}{sub_id}"
                if fallback not in urls:
                    urls.append(fallback)

        return urls

    def _build_subscription_url(self, settings: XUISettings, sub_id: str) -> str:
        if settings.sub_uri:
            if settings.sub_uri.startswith("http://") or settings.sub_uri.startswith("https://"):
                if "{subid}" in settings.sub_uri:
                    return settings.sub_uri.replace("{subid}", sub_id)
                return settings.sub_uri.rstrip("/") + "/" + sub_id

            parsed_base = urlparse(self.base_url)
            scheme = parsed_base.scheme or "https"
            if not parsed_base.netloc:
                raise XUIError("Cannot resolve host for subscription URL")
            relative = settings.sub_uri
            if not relative.startswith("/"):
                relative = "/" + relative
            if "{subid}" in relative:
                relative = relative.replace("{subid}", sub_id)
                return f"{scheme}://{parsed_base.netloc}{relative}"
            return f"{scheme}://{parsed_base.netloc}{relative.rstrip('/')}/{sub_id}"

        parsed = urlparse(self.base_url)
        scheme = parsed.scheme or "https"
        host = parsed.hostname
        if not host:
            raise XUIError("Cannot resolve host for subscription URL")

        if settings.sub_port > 0:
            netloc = f"{host}:{settings.sub_port}"
        elif parsed.port:
            netloc = f"{host}:{parsed.port}"
        else:
            netloc = host

        sub_path = settings.sub_path or "/sub/"
        if not sub_path.startswith("/"):
            sub_path = "/" + sub_path
        if not sub_path.endswith("/"):
            sub_path += "/"

        return f"{scheme}://{netloc}{sub_path}{sub_id}"

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        await self._login()

    async def _login(self) -> None:
        response = await self._client.post(
            self._full_url("/login"),
            data={"username": self.username, "password": self.password},
        )
        if response.status_code != 200:
            raise XUIError(f"Login failed with status {response.status_code}")

        data = self._parse_json(response)
        if not data.get("success"):
            raise XUIError(data.get("msg") or "Panel login failed")

        self._logged_in = True

    async def _request_panel_json(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        await self._ensure_login()
        response = await self._client.request(method, self._full_url(path), data=data)

        if response.status_code in {401, 404} and retry:
            self._logged_in = False
            await self._ensure_login()
            return await self._request_panel_json(method, path, data=data, retry=False)

        if response.status_code not in {200, 201}:
            raise XUIError(f"Panel API {path} failed with status {response.status_code}")

        payload = self._parse_json(response)
        if payload.get("success") is False:
            msg = str(payload.get("msg") or "Panel API rejected request")
            if retry and "login" in msg.lower():
                self._logged_in = False
                await self._ensure_login()
                return await self._request_panel_json(method, path, data=data, retry=False)
            raise XUIError(msg)

        return payload

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise XUIError("Panel returned non-JSON response") from exc
        if not isinstance(data, dict):
            raise XUIError("Unexpected panel JSON format")
        return data

    def _full_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        url = (value or "").strip()
        if not url:
            raise XUIError("Empty panel URL")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url.rstrip("/")
