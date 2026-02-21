from __future__ import annotations

import base64


class LinkResolverError(Exception):
    pass


class LinkResolverService:
    @staticmethod
    def extract_links(raw_text: str) -> list[str]:
        text = (raw_text or "").strip()
        if not text:
            raise LinkResolverError("Subscription response is empty")

        decoded = LinkResolverService._maybe_decode_base64(text)
        final_text = decoded if decoded is not None else text

        links: list[str] = []
        seen: set[str] = set()
        for line in final_text.splitlines():
            value = line.strip()
            if not value or "://" not in value:
                continue
            if value in seen:
                continue
            seen.add(value)
            links.append(value)

        if not links:
            raise LinkResolverError("No direct links found in subscription content")

        return links

    @staticmethod
    def chunk_links(links: list[str], chunk_size: int = 20) -> list[str]:
        chunks: list[str] = []
        for i in range(0, len(links), chunk_size):
            part = links[i : i + chunk_size]
            chunks.append("\n".join(part))
        return chunks

    @staticmethod
    def _maybe_decode_base64(text: str) -> str | None:
        candidate = "".join(text.split())
        if not candidate:
            return None
        if "://" in candidate:
            return None

        pad = len(candidate) % 4
        if pad != 0:
            candidate += "=" * (4 - pad)

        try:
            decoded = base64.b64decode(candidate, validate=False).decode("utf-8", errors="ignore").strip()
        except Exception:
            return None

        if "://" in decoded:
            return decoded
        return None
