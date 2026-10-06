"""Loads config.yaml + contacts.yaml into plain dataclasses."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo
import yaml


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class Event:
    name: str
    column: str
    weekday: int
    time: time


@dataclass
class Contact:
    name: str
    email: str = ""
    phone: str = ""
    carrier: str = ""
    channel: str = "email"      # email | sms | both
    timing: str = "immediate"   # immediate | digest
    digest_time: time = time(17, 0)
    one_up: str | None = None
    two_up: str | None = None
    role: str = ""


@dataclass
class Config:
    tz: ZoneInfo
    db_path: str
    source: dict
    columns: dict
    events: list[Event]
    sunday_reminder: time
    response_deadline: time
    preemptive_warning_minutes: int
    two_up_delay_hours: int
    pre_event_minutes: int
    change_alerts: bool
    repeat_offender_threshold: int
    dry_run: bool
    email_from: str
    contacts: dict[str, Contact] = field(default_factory=dict)


def load(config_path: str = "config.yaml", contacts_path: str = "contacts.yaml") -> Config:
    with open(config_path) as f:
        c = yaml.safe_load(f)
    with open(contacts_path) as f:
        k = yaml.safe_load(f) or {}
    return build(c, k)


def build(c: dict, k: dict) -> Config:
    s = c["schedule"]
    defaults = k.get("defaults", {})
    contacts = {}
    for name, info in (k.get("cadets") or {}).items():
        merged = {**defaults, **(info or {})}
        contacts[name] = Contact(
            name=name,
            email=merged.get("email", ""),
            phone=str(merged.get("phone", "") or ""),
            carrier=merged.get("carrier", ""),
            channel=merged.get("channel", "email"),
            timing=merged.get("timing", "immediate"),
            digest_time=_t(merged.get("digest_time", "17:00")),
            one_up=merged.get("one_up"),
            two_up=merged.get("two_up"),
            role=merged.get("role", ""),
        )
    return Config(
        tz=ZoneInfo(c.get("timezone", "America/New_York")),
        db_path=c.get("db_path", "cadet_tracker.db"),
        source=c["source"],
        columns=c["columns"],
        events=[Event(e["name"], e["column"], int(e["weekday"]), _t(e["time"])) for e in c["events"]],
        sunday_reminder=_t(s["sunday_reminder"]),
        response_deadline=_t(s["response_deadline"]),
        preemptive_warning_minutes=int(s["preemptive_warning_minutes"]),
        two_up_delay_hours=int(s["two_up_delay_hours"]),
        pre_event_minutes=int(s["pre_event_minutes"]),
        change_alerts=bool(s.get("change_alerts", True)),
        repeat_offender_threshold=int(c.get("history", {}).get("repeat_offender_threshold", 3)),
        dry_run=bool(c.get("notify", {}).get("dry_run", True)),
        email_from=c.get("notify", {}).get("email_from", "cadet-tracker@example.com"),
        contacts=contacts,
    )
