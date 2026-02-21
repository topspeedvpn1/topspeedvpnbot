from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Panel:
    id: int
    name: str
    base_url: str
    username: str
    password_enc: str
    active: bool


@dataclass(slots=True)
class Profile:
    id: int
    panel_id: int
    name: str
    prefix: str
    suffix: str
    traffic_gb: int
    expiry_days: int
    active: bool
    rr_index: int


@dataclass(slots=True)
class ProfilePort:
    id: int
    profile_id: int
    inbound_id: int
    port: int
    max_active_clients: int
    sort_order: int


@dataclass(slots=True)
class AllocationResult:
    profile_name: str
    quantity: int
    links: list[str]
