"""Leader dashboard: current week, history, settings, actions.

Run:  DASHBOARD_PASSWORD=... python -m cadet_tracker.webapp
Set SCHEDULER_MINUTES=10 to also run tick() in a background thread (for hosts
without cron). Everything on this site is cadet PII -> password required.
"""
from __future__ import annotations
import os
import secrets
import threading
from datetime import datetime, timezone
from functools import wraps

import yaml
from flask import (Flask, redirect, render_template, request, session, url_for, flash)

from . import config as config_mod
from .engine import Engine
from .notify import Sender
from .sheet import read_rows, parse_grid
from .store import Store

CONFIG_PATH = os.environ.get("CT_CONFIG", "config.yaml")
CONTACTS_PATH = os.environ.get("CT_CONTACTS", "contacts.yaml")
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_hex(16))
lock = threading.Lock()          # tick() may run from a request and the scheduler


@app.template_filter("local")
def local_time(value, tz=None):
    """UTC timestamps are stored; people read wall-clock time."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%a %d %b, %H:%M") if tz else dt.strftime("%Y-%m-%d %H:%M")


def cfg():
    return config_mod.load(CONFIG_PATH, CONTACTS_PATH)


def engine_for(c):
    return Engine(c, Store(c.db_path), Sender(c), lambda: read_rows(c.source))


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def read_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def write_yaml(path, data):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)


# ---------------- auth ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), PASSWORD):
            session["ok"] = True
            return redirect(request.args.get("next") or url_for("status"))
        flash("Wrong password", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- 1. current week ----------------
@app.route("/")
@login_required
def status():
    c = cfg()
    cadets = parse_grid(read_rows(c.source), c.columns, [e.column for e in c.events])
    cols = [(e.name, e.column) for e in c.events]
    rows, missing_total = [], 0
    for cd in cadets:
        cells = [cd.responses[col] for _, col in cols]
        n = sum(1 for r in cells if r.status == "MISSING")
        missing_total += n
        contact = c.contacts.get(cd.name)
        rows.append({"cadet": cd, "cells": cells, "missing": n,
                     "one_up": contact.one_up if contact else None,
                     "known": contact is not None})
    rows.sort(key=lambda r: (-r["missing"], r["cadet"].name))
    week = engine_for(c).week_start(datetime.now(c.tz))
    return render_template("status.html", rows=rows, cols=cols, week=week,
                           missing_total=missing_total, unknown=[r for r in rows if not r["known"]])


# ---------------- 2. history ----------------
@app.route("/history")
@login_required
def history():
    c = cfg()
    st = Store(c.db_path)
    rows = [{"cadet": cadet, "total": total, "deadline": dl or 0, "event": ev or 0,
             "changes": st.change_count(cadet), "last": last,
             "repeat": total >= c.repeat_offender_threshold}
            for cadet, total, dl, ev, last in st.miss_table()]
    return render_template("history.html", rows=rows, threshold=c.repeat_offender_threshold, tz=c.tz)


# ---------------- 3. settings ----------------
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        if request.form.get("form") == "schedule":
            raw = read_yaml(CONFIG_PATH)
            s = raw["schedule"]
            s["sunday_reminder"] = request.form["sunday_reminder"]
            s["response_deadline"] = request.form["response_deadline"]
            s["preemptive_warning_minutes"] = int(request.form["preemptive_warning_minutes"])
            s["two_up_delay_hours"] = int(request.form["two_up_delay_hours"])
            s["pre_event_minutes"] = int(request.form["pre_event_minutes"])
            s["change_alerts"] = "change_alerts" in request.form
            raw.setdefault("history", {})["repeat_offender_threshold"] = int(request.form["threshold"])
            raw.setdefault("notify", {})["dry_run"] = "dry_run" in request.form
            src = raw["source"]
            src["type"] = request.form["source_type"]
            src["path"] = request.form["path"]
            src["sheet_id"] = request.form["sheet_id"]
            src["worksheet"] = request.form["worksheet"]
            write_yaml(CONFIG_PATH, raw)
            flash("Schedule saved", "ok")
        else:
            raw = read_yaml(CONTACTS_PATH)
            cadets = {}
            for key in request.form.getlist("row"):
                if request.form.get(f"delete[{key}]"):
                    continue
                name = request.form.get(f"name[{key}]", "").strip()
                if not name:
                    continue
                entry = {}
                for f in ("email", "phone", "carrier", "channel", "timing", "digest_time",
                          "one_up", "two_up", "role"):
                    v = request.form.get(f"{f}[{key}]", "").strip()
                    if v:
                        entry[f] = v
                cadets[name] = entry
            raw["cadets"] = cadets
            write_yaml(CONTACTS_PATH, raw)
            flash("Contacts saved", "ok")
        return redirect(url_for("settings"))

    raw_cfg, raw_contacts = read_yaml(CONFIG_PATH), read_yaml(CONTACTS_PATH)
    people = sorted((raw_contacts.get("cadets") or {}).keys())
    return render_template("settings.html", cfg=raw_cfg, s=raw_cfg["schedule"],
                           contacts=raw_contacts.get("cadets") or {}, people=people,
                           defaults=raw_contacts.get("defaults", {}))


# ---------------- 4. actions ----------------
@app.route("/actions", methods=["GET", "POST"])
@login_required
def actions():
    c = cfg()
    eng = engine_for(c)
    if request.method == "POST":
        if request.form["do"] == "tick":
            with lock:
                eng.tick(datetime.now(c.tz))
            msg = ("Checked the sheet and sent anything that was due"
                   + (" (practice mode)" if c.dry_run else ""))
            if eng.warnings:
                flash(msg + ". Some messages could not be sent: "
                      + "; ".join(dict.fromkeys(eng.warnings)), "error")
            else:
                flash(msg, "ok")
        else:
            name = request.form["cadet"]
            contact = c.contacts.get(name)
            if contact:
                try:
                    Sender(c).send(contact, "Cadet Tracker test",
                                   "This is a test message from the Cadet Tracking dashboard.")
                    flash(f"Test message sent to {name}"
                          + (" (practice mode — nothing left your machine)" if c.dry_run else ""), "ok")
                except Exception as e:
                    flash(f"Could not send to {name}: {type(e).__name__}: {e}", "error")
        return redirect(url_for("actions"))

    st = Store(c.db_path)
    now_utc = datetime.now(c.tz).astimezone(timezone.utc).isoformat(timespec="seconds")
    queue = [{"due": due, "recipient": rcpt, "subject": subj, "attempts": att, "error": err,
              "overdue": due <= now_utc}
             for due, rcpt, subj, att, err in st.pending()]
    return render_template("actions.html", sent=st.recent_sent(40), queue=queue,
                           people=sorted(c.contacts), dry_run=c.dry_run, tz=c.tz,
                           stuck=[q for q in queue if q["error"] or q["overdue"]])


def start_scheduler():
    minutes = int(os.environ.get("SCHEDULER_MINUTES", "0"))
    if not minutes:
        return
    def loop():
        c = cfg()
        try:
            with lock:
                engine_for(c).tick(datetime.now(c.tz))
        except Exception as e:      # never kill the timer
            print("scheduler tick failed:", e)
        threading.Timer(minutes * 60, loop).start()
    threading.Timer(5, loop).start()
    print(f"background scheduler: every {minutes} min")


if __name__ == "__main__":
    start_scheduler()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
