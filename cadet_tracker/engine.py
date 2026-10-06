"""The scheduler brain. Run tick() every ~10-15 minutes (cron). Each call
re-reads the sheet, diffs it against the last snapshot, and sends whatever is
due. Every notification has a unique key, so repeated ticks never double-send.

Timeline for one week (all times configurable):

  Sun 12:00  reminder -> every cadet with a blank cell for the coming week
  Sun 20:30  final warning -> cadets still blank ("your 1UP is told in 30 min")
  Sun 21:00  deadline: miss recorded; 1UP notified (cadet told they were escalated)
  Mon 09:00  still blank 12h later -> 2UP notified
             (or immediately at the deadline if the cadet is a repeat offender)
  event-60m  1UP gets the squad roster for that event; blank cadets get a nudge
  event      anyone still blank for that event gets an event miss recorded
  anytime    a cadet changes an existing answer -> 1UP gets a change alert
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from .sheet import parse_grid, MISSING, ATTENDING, NOT_ATTENDING, LATE, SEE_OTHER

URGENT, INFO = True, False


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Engine:
    def __init__(self, cfg, store, sender, rows_provider):
        self.cfg, self.store, self.sender, self.rows = cfg, store, sender, rows_provider
        self.warnings: list[str] = []

    # ---------- time helpers ----------
    def week_start(self, now: datetime) -> date:
        d = now.date()
        return d + timedelta(days=1) if d.weekday() == 6 else d - timedelta(days=d.weekday())

    def at(self, d: date, t) -> datetime:
        return datetime.combine(d, t, self.cfg.tz)

    def event_dt(self, ws: date, ev) -> datetime:
        return self.at(ws + timedelta(days=ev.weekday), ev.time)

    # ---------- messaging ----------
    def notify(self, name: str | None, subject: str, body: str, now: datetime, urgent: bool):
        if not name:
            return
        c = self.cfg.contacts.get(name)
        if c is None:
            self.warnings.append(f"No contact entry for {name!r}; message skipped")
            return
        due = now
        if c.timing == "digest" and not urgent:
            due = self.at(now.date(), c.digest_time)
            if due <= now:
                due = self.at(now.date() + timedelta(days=1), c.digest_time)
        self.store.enqueue(name, subject, body, _utc(due), _utc(now))

    def flush(self, now: datetime):
        grouped = defaultdict(list)
        for mid, rcpt, subj, body in self.store.due(_utc(now)):
            grouped[rcpt].append((mid, subj, body))
        for rcpt, msgs in grouped.items():
            ids = [m[0] for m in msgs]
            c = self.cfg.contacts.get(rcpt)
            if c is None:
                self.store.record_failure(ids, f"No contact entry for {rcpt}", _utc(now))
                self.warnings.append(f"No contact entry for {rcpt!r}; message held")
                continue
            if len(msgs) == 1:
                _, subj, body = msgs[0]
            else:
                subj = f"Cadet Tracker digest ({len(msgs)} updates)"
                body = "\n\n".join(f"- {s}\n{b}" for _, s, b in msgs)
            try:
                self.sender.send(c, subj, body)
            except Exception as e:      # keep the rest of the queue moving; retry next tick
                self.store.record_failure(ids, f"{type(e).__name__}: {e}", _utc(now))
                self.warnings.append(f"Could not send to {rcpt}: {type(e).__name__}: {e}")
                continue
            self.store.mark_sent(ids, _utc(now))

    # ---------- main loop ----------
    def tick(self, now: datetime):
        cfg, st = self.cfg, self.store
        now = now.astimezone(cfg.tz)
        ws = self.week_start(now)
        week = ws.isoformat()
        cadets = parse_grid(self.rows(), cfg.columns, [e.column for e in cfg.events])
        by_name = {c.name: c for c in cadets}

        self._detect_changes(week, cadets, now)

        missing = {c.name: [e for e in cfg.events if not c.responses[e.column].responded] for c in cadets}
        missing = {n: evs for n, evs in missing.items() if evs}

        sunday = ws - timedelta(days=1)
        remind_at = self.at(sunday, cfg.sunday_reminder)
        deadline = self.at(sunday, cfg.response_deadline)
        warn_at = deadline - timedelta(minutes=cfg.preemptive_warning_minutes)
        two_up_at = deadline + timedelta(hours=cfg.two_up_delay_hours)
        dl = deadline.strftime("%a %H:%M")
        stamp = _utc(now)

        for name, evs in missing.items():
            ev_list = ", ".join(e.name for e in evs)
            contact = cfg.contacts.get(name)
            one_up = contact.one_up if contact else None
            two_up = contact.two_up if contact else None

            if remind_at <= now < deadline and st.once(f"{week}:remind:{name}", stamp):
                self.notify(name, "Accountability response needed",
                            f"You have not filled out accountability for the week of {week}: {ev_list}. "
                            f"Please respond by {dl}.", now, URGENT)

            if warn_at <= now < deadline and st.once(f"{week}:warn:{name}", stamp):
                self.notify(name, "FINAL WARNING: accountability due",
                            f"Still missing: {ev_list}. Your 1UP will be notified at {dl} "
                            f"({cfg.preemptive_warning_minutes} min) if this stays blank.", now, URGENT)

            if now >= deadline:
                if st.record_miss(week, name, "deadline", stamp):
                    pass
                count = st.miss_count(name)
                if st.once(f"{week}:1up:{name}", stamp):
                    self.notify(one_up, f"Missing accountability: {name}",
                                f"{name} did not fill out accountability by {dl} for: {ev_list}. "
                                f"Total misses on record: {count}.", now, INFO)
                    self.notify(name, "Your 1UP has been notified",
                                f"You missed the {dl} deadline ({ev_list}). {one_up or 'Your leader'} "
                                f"has been notified. Fill out the sheet as soon as possible.", now, URGENT)
                repeat = count >= cfg.repeat_offender_threshold
                if (now >= two_up_at or repeat) and st.once(f"{week}:2up:{name}", stamp):
                    why = (f"repeat offender ({count} misses on record)" if repeat
                           else f"still blank {cfg.two_up_delay_hours}h after the deadline")
                    self.notify(two_up, f"Escalation: {name} accountability",
                                f"{name} is missing accountability for {ev_list}: {why}. "
                                f"1UP: {one_up or 'n/a'}.", now, INFO)

        self._pre_event(week, ws, cadets, by_name, now)
        st.commit()
        self.flush(now)

    # ---------- pieces ----------
    def _detect_changes(self, week, cadets, now):
        prev = self.store.previous(week)
        first_run = not prev
        stamp = _utc(now)
        for c in cadets:
            changed = []
            for ev in self.cfg.events:
                r = c.responses[ev.column]
                old = prev.get((c.name, ev.column))
                if not first_run and old is not None and old != r.raw:
                    self.store.log_change(week, c.name, ev.column, old, r.raw, stamp)
                    if old:     # an existing answer was changed (not a first fill-in)
                        changed.append(f"{ev.name}: '{old}' -> '{r.raw or '(blank)'}'")
                self.store.save_cell(week, c.name, ev.column, r.status, r.raw, stamp)
            if changed and self.cfg.change_alerts:
                contact = self.cfg.contacts.get(c.name)
                self.notify(contact.one_up if contact else None,
                            f"Accountability changed: {c.name}", "; ".join(changed), now, INFO)

    def _pre_event(self, week, ws, cadets, by_name, now):
        cfg, st = self.cfg, self.store
        stamp = _utc(now)
        for ev in cfg.events:
            start = self.event_dt(ws, ev)
            window = start - timedelta(minutes=cfg.pre_event_minutes)
            if window <= now < start:
                squads = defaultdict(list)
                for c in cadets:
                    contact = cfg.contacts.get(c.name)
                    squads[contact.one_up if contact else None].append(c)
                    if c.responses[ev.column].status == MISSING and st.once(f"{week}:nudge:{ev.column}:{c.name}", stamp):
                        self.notify(c.name, f"{ev.name} starts at {ev.time:%H:%M}",
                                    f"You have no response for {ev.name}. Update the sheet now; "
                                    f"your 1UP sees this roster.", now, URGENT)
                for leader, members in squads.items():
                    if leader and st.once(f"{week}:roster:{ev.column}:{leader}", stamp):
                        self.notify(leader, f"{ev.name} roster ({start:%a %H:%M})",
                                    self._roster(members, ev.column), now, URGENT)
            if now >= start:
                for c in cadets:
                    if c.responses[ev.column].status == MISSING:
                        st.record_miss(week, c.name, f"event:{ev.column}", stamp)

    @staticmethod
    def _roster(members, col) -> str:
        buckets = defaultdict(list)
        for m in members:
            r = m.responses[col]
            label = {ATTENDING: "Attending", NOT_ATTENDING: "Not attending", LATE: "Late",
                     MISSING: "NO RESPONSE", SEE_OTHER: "Same as"}.get(r.status, "Other")
            buckets[label].append(m.name + (f" ({r.reason or r.raw})" if label in ("Not attending", "Late", "Other", "Same as") else ""))
        order = ["NO RESPONSE", "Not attending", "Late", "Other", "Same as", "Attending"]
        return "\n".join(f"{k} ({len(buckets[k])}): {', '.join(buckets[k])}" for k in order if buckets[k])
