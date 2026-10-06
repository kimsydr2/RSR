"""python -m cadet_tracker {tick,simulate,status,report}"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from . import config as config_mod
from .engine import Engine
from .notify import Sender
from .sheet import read_rows, parse_grid
from .store import Store


def _parse_now(s, tz):
    if not s:
        return datetime.now(tz)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def main(argv=None):
    p = argparse.ArgumentParser(prog="cadet_tracker")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--contacts", default="contacts.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick", help="run one scheduling pass (call from cron)")
    t.add_argument("--now", help="pretend the time is this ISO datetime (for demos)")
    s = sub.add_parser("simulate", help="run ticks over a time range (dry-run demo)")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--step", type=int, default=15, help="minutes between ticks")
    sub.add_parser("status", help="show this sheet's current responses")
    sub.add_parser("report", help="miss/change history per cadet")
    a = p.parse_args(argv)

    cfg = config_mod.load(a.config, a.contacts)
    store = Store(cfg.db_path)
    engine = Engine(cfg, store, Sender(cfg), lambda: read_rows(cfg.source))

    if a.cmd == "tick":
        engine.tick(_parse_now(a.now, cfg.tz))
    elif a.cmd == "simulate":
        now, end = _parse_now(a.start, cfg.tz), _parse_now(a.end, cfg.tz)
        while now <= end:
            engine.tick(now)
            now += timedelta(minutes=a.step)
    elif a.cmd == "status":
        cadets = parse_grid(read_rows(cfg.source), cfg.columns, [e.column for e in cfg.events])
        cols = [e.column for e in cfg.events]
        print(f"{'Cadet':22} {'Role':5} " + " ".join(f"{c[:10]:10}" for c in cols))
        for c in cadets:
            print(f"{c.name[:22]:22} {c.role[:5]:5} " +
                  " ".join(f"{c.responses[col].status[:10]:10}" for col in cols))
    elif a.cmd == "report":
        th = cfg.repeat_offender_threshold
        print(f"{'Cadet':22} {'Total':>5} {'Deadln':>6} {'Event':>5} {'Chg':>4}  Flag")
        for cadet, total, dl, ev, _last in store.miss_table():
            flag = "REPEAT" if total >= th else ""
            print(f"{cadet[:22]:22} {total:5} {dl or 0:6} {ev or 0:5} {store.change_count(cadet):4}  {flag}")

    for w in dict.fromkeys(engine.warnings):
        print("WARNING:", w)


if __name__ == "__main__":
    main()
