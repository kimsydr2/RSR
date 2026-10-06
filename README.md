# Cadet Tracking

Automated attendance-response reminders and chain-of-command notifications built on top of
the Virginia Tech Corps of Cadets' existing attendance spreadsheet. The sheet is
**read-only** to this tool; its format is never changed.

CS3704, Fall 2026 — Team RSR.

## Team

| Name          | Email                 |
| ------------- | --------------------- |
| Robert Rooney | `robertrooney@vt.edu` |
| Seo-Yeon Kim  | `seoyeonk@vt.edu`     |
| Ryan Cochling | `ryancochling@vt.edu` |

## The problem

Every cadet company tracks event attendance in a standardized Excel sheet. For each event a
cadet records whether they will attend and why not if they won't, so leaders can plan
headcounts, formation and equipment. Nothing in that process is automated. Cadets have to
remember on their own to open the sheet, and leaders have to reopen it repeatedly before
each event and work out by eye who is still missing. When responses are late, missing, or
changed close to an event, leaders plan against a headcount that is already wrong, and the
cadets who never responded hear nothing until the consequences of a no-show.

This tool closes that gap without replacing the spreadsheet. It reads the sheet on a
schedule, reminds the cadets who still have blanks, escalates up the chain of command only
when a blank stays blank, and delivers each leader a current roster before the event starts.

## What it does

| Feature                                 | Source                                                                     | How                                                                                         |
| --------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Parse the attendance grid on a schedule | Proposal (core)                                                            | `tick` re-reads the sheet every run; blank cell = no response                               |
| Sunday reminder to non-responders       | Proposal (core)                                                            | Sun 12:00 by default                                                                        |
| Pre-event status to leaders             | Proposal (core)                                                            | 60 min before each event, each 1UP gets a roster of their squad; blank cadets get a nudge   |
| Text notifications                      | Survey: text strongly preferred                                            | Carrier email-to-SMS gateways (no paid SMS API) — per-cadet `channel: email / sms / both`   |
| Escalation chain cadet → 1UP → 2UP      | Survey                                                                     | Deadline → 1UP (cadet is told); still blank 12h later → 2UP                                 |
| Warning before escalation               | Survey: "notify me before the 1UP is told"                                 | Final warning N minutes before the deadline                                                 |
| Configurable timing                     | Survey: answers ranged from "immediately" to "midnight" to "daily summary" | All times in `config.yaml`; leaders can pick `timing: digest` for one bundled message a day |
| Change alerts                           | Survey: "notify when they change accountability"                           | Changed existing answer → 1UP alert                                                         |
| Miss history / repeat offenders         | Survey: "track pattern of behavior"                                        | SQLite log; `report` command; repeat offenders go straight to 2UP                           |

**Simplifications (on purpose):** chain of command is hardcoded in `contacts.yaml`, not derived
from the sheet; cell text is classified with simple rules (yes / no, reason / late / like X / other).
Time-critical messages (reminders, warnings, rosters) ignore digest mode; informational ones
(escalations, change alerts) respect it.

## Dependencies

Python 3.10 or newer. Everything else installs from `requirements.txt`:

| Package    | Used for                                                            |
| ---------- | ------------------------------------------------------------------- |
| `openpyxl` | reading a local `.xlsx` attendance sheet                            |
| `PyYAML`   | `config.yaml` and `contacts.yaml`                                   |
| `gspread`  | reading a live Google Sheet (only needed for `source.type: gsheet`) |
| `Flask`    | the leader dashboard                                                |
| `pytest`   | the test suite                                                      |

Email and SMS go out over SMTP, so sending for real also needs an SMTP account — see
[Going live](#going-live). Nothing is sent while `dry_run: true`.

## Quick start (dry run, fake data)

Run these from the repository root. A virtual environment is recommended:
`python3 -m venv .venv && source .venv/bin/activate`

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp contacts.example.yaml contacts.yaml
python scripts/make_sample_sheet.py
python -m cadet_tracker status
python -m cadet_tracker simulate --start 2026-09-27T11:00 --end 2026-09-28T18:00 --step 15
python -m cadet_tracker report
python -m pytest
```

`dry_run: true` prints every message instead of sending it. Delete `cadet_tracker.db` to reset.

## Leader dashboard (web)

```bash
DASHBOARD_PASSWORD=pick-something python -m cadet_tracker.webapp
# open http://127.0.0.1:5000
```

On macOS, AirPlay Receiver holds port 5000; set `PORT=5050` and open `http://127.0.0.1:5050`
instead.

Four pages: **This week** (live sheet, blanks first), **History** (misses, answer changes,
repeat flags), **Settings** (schedule, escalation rules, and every cadet's contact info,
channel, digest time and 1UP/2UP — writes config.yaml and contacts.yaml), **Messages**
(check the sheet now, send a test message, see what went out and what is still queued).
Queued messages are labelled: held for a digest, due now, or failed with the error. A send
that fails is retried on the next check instead of disappearing, and the failure is shown
on the page. All times are displayed in the timezone from config.yaml.

Cadets never open it; they fill in the sheet and receive messages as they do now.
Everything is behind one password because the pages show cadet phone numbers and email.
Saving from Settings rewrites the YAML files, so comments in them are not preserved.

To run the schedule without cron (e.g. on a small host), set `SCHEDULER_MINUTES=10` and the
app runs a tick in the background on that interval.

## Going live

1. Google Cloud → create a service account, enable the Sheets API, download the key as
   `service_account.json`.
2. Share the attendance sheet with the service account's email as **Viewer**.
3. In `config.yaml`: `source.type: gsheet`, set `sheet_id` and `worksheet`, `dry_run: false`.
4. Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (e.g. a Gmail account with an app password).
5. Run `tick` every 10–15 minutes on an always-on machine:
   ```
   */10 * * * * cd /path/to/cadet-tracker && python -m cadet_tracker tick >> tick.log 2>&1
   ```

**Do not** run this from GitHub Actions on the public repo or commit `config.yaml`,
`contacts.yaml`, `*.db` or the key: they contain cadet contact info and are git-ignored.

## Layout

```
cadet_tracker/
  sheet.py    read sheet (xlsx or Google Sheets) + classify cells
  engine.py   the weekly timeline, escalation, change detection, digests
  store.py    SQLite: snapshots, changes, misses, sent-keys, outbox
  notify.py   email / SMS gateway / dry run
  config.py   config.yaml + contacts.yaml
  cli.py      tick | simulate | status | report
  webapp.py   Flask dashboard (+ templates/)
scripts/make_sample_sheet.py   fake sheet in the real layout
tests/                         timeline, dedup, change alert, digest, repeat offender
```
