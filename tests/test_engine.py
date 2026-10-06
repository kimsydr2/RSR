from datetime import datetime
from zoneinfo import ZoneInfo
from cadet_tracker import config
from cadet_tracker.engine import Engine
from cadet_tracker.notify import Sender
from cadet_tracker.store import Store

TZ = ZoneInfo("America/New_York")
CFG = {
    "timezone": "America/New_York", "db_path": ":memory:",
    "source": {"type": "xlsx"},
    "columns": {"rank": "Rank", "last": "Last Name", "first": "First Name"},
    "events": [{"name": "Monday PT", "column": "Monday", "weekday": 0, "time": "06:30"}],
    "schedule": {"sunday_reminder": "12:00", "response_deadline": "21:00",
                 "preemptive_warning_minutes": 30, "two_up_delay_hours": 12,
                 "pre_event_minutes": 60, "change_alerts": True},
    "history": {"repeat_offender_threshold": 3},
    "notify": {"dry_run": True},
}
CONTACTS = {"cadets": {
    "Lead, Two": {"email": "two@vt.edu"},
    "Lead, One": {"email": "one@vt.edu", "one_up": "Lead, Two"},
    "Cadet, A":  {"email": "a@vt.edu", "one_up": "Lead, One", "two_up": "Lead, Two"},
}}
HEADER = ["", "Rank", "Last Name", "First Name", "Monday"]


def make(sheet):
    cfg = config.build(CFG, CONTACTS)
    sender = Sender(cfg, log_path="/dev/null")
    eng = Engine(cfg, Store(":memory:"), sender, lambda: [HEADER] + sheet)
    return eng, sender


def at(s):  # week of Mon 2026-09-28; Sunday is 09-27
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


def to(sender):
    return [addr for addr, _, _ in sender.sent]


def test_escalation_timeline_and_no_duplicates():
    sheet = [["", "NC/", "Cadet", "A", ""], ["SL", "", "Lead", "One", "yes"], ["", "", "Lead", "Two", "yes"]]
    eng, s = make(sheet)
    eng.tick(at("2026-09-27T11:00"));  assert to(s) == []                      # too early
    eng.tick(at("2026-09-27T12:05"));  assert to(s) == ["a@vt.edu"]            # Sunday reminder
    eng.tick(at("2026-09-27T12:20"));  assert len(s.sent) == 1                 # no duplicate
    eng.tick(at("2026-09-27T20:35"));  assert to(s)[-1] == "a@vt.edu"          # final warning
    assert "FINAL WARNING" in s.sent[-1][1]
    n = len(s.sent)
    eng.tick(at("2026-09-27T21:05"))                                            # deadline
    assert set(to(s)[n:]) == {"one@vt.edu", "a@vt.edu"}
    assert eng.store.miss_count("Cadet, A") == 1
    n = len(s.sent)
    eng.tick(at("2026-09-28T05:40"))                                            # pre-event window
    new = to(s)[n:]
    assert "a@vt.edu" in new and "one@vt.edu" in new                           # nudge + roster
    roster = [b for a, _, b in s.sent[n:] if a == "one@vt.edu"][0]
    assert "NO RESPONSE (1): Cadet, A" in roster
    n = len(s.sent)
    eng.tick(at("2026-09-28T09:05"))                                            # deadline + 12h
    assert "two@vt.edu" in to(s)[n:]
    eng.tick(at("2026-09-28T09:20"))
    assert eng.store.miss_count("Cadet, A") == 2                                 # deadline + event miss


def test_change_alert_goes_to_one_up():
    sheet = [["", "NC/", "Cadet", "A", "yes"]]
    eng, s = make(sheet)
    eng.tick(at("2026-09-24T10:00"))            # first snapshot of week of 9/21
    sheet[0][4] = "No, sick"
    eng.tick(at("2026-09-24T10:15"))
    assert to(s) == ["one@vt.edu"]
    assert "'yes' -> 'No, sick'" in s.sent[0][2]


def test_digest_bundles_info_messages():
    contacts = {"cadets": {**CONTACTS["cadets"],
                           "Lead, One": {"email": "one@vt.edu", "timing": "digest", "digest_time": "17:00"}}}
    cfg = config.build(CFG, contacts)
    s = Sender(cfg, log_path="/dev/null")
    sheet = [["", "", "Cadet", "A", "yes"]]
    eng = Engine(cfg, Store(":memory:"), s, lambda: [HEADER] + sheet)
    eng.tick(at("2026-09-24T10:00"))
    sheet[0][4] = "no"; eng.tick(at("2026-09-24T10:15"))
    sheet[0][4] = "yes"; eng.tick(at("2026-09-24T11:00"))
    assert s.sent == []                          # held for the digest
    eng.tick(at("2026-09-24T17:00"))
    assert len(s.sent) == 1 and "digest (2 updates)" in s.sent[0][1]


def test_repeat_offender_goes_straight_to_two_up():
    sheet = [["", "", "Cadet", "A", ""]]
    eng, s = make(sheet)
    for wk in ("2026-09-13", "2026-09-20"):
        eng.store.record_miss(wk, "Cadet, A", "deadline", "x")
    eng.tick(at("2026-09-27T21:05"))            # 3rd miss -> threshold hit at the deadline
    assert "two@vt.edu" in to(s)


def test_send_failure_is_recorded_and_retried():
    sheet = [["", "", "Cadet", "A", ""]]
    eng, s = make(sheet)
    boom = []

    def explode(contact, subject, body):
        boom.append(1)
        raise OSError("SMTP_HOST missing")

    s.send = explode
    eng.tick(at("2026-09-27T21:05"))                     # deadline -> 1UP + cadet
    pending = eng.store.pending()
    assert pending and all(p[3] == 1 and "SMTP_HOST" in p[4] for p in pending)
    assert eng.warnings and eng.store.failures() == len(pending)
    eng, s2 = eng, s                                      # now let sending work again
    s.send = Sender(eng.cfg, log_path="/dev/null").send
    eng.tick(at("2026-09-27T21:20"))                      # retried, not dropped
    assert eng.store.pending() == []
