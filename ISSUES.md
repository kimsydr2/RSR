# Issues to file on GitHub

Paste each block below as a separate issue (title = the heading, body = the text under it).
Suggested labels are in brackets. This file is a staging area for the submission requirement
"GitHub issues with known bugs and/or features you would add if there were more time" — it
does not need to stay in the repo once the issues exist.

---

## Bundled SMS messages are truncated at ~300 characters [bug]

`notify.SMS_MAX` caps a text at 300 characters, which carrier gateways enforce anyway. When
one leader is owed several notifications at the same moment, `Engine.flush` merges them into
a single message and the tail is cut off mid-sentence.

Reproduce: run `simulate` over a Sunday where two cadets in the same squad have blanks. The
squad leader's text ends partway through the second cadet's entry.

Fix direction: give SMS recipients their own short format — names and a count, with the full
detail left to email and the dashboard — instead of truncating the email body.

---

## A "like <name>" answer is recorded but never resolved [bug]

`sheet.classify` tags an entry such as `like drew` as `SEE_OTHER`, which counts as a response.
The roster then shows the reference itself rather than what the cadet meant, so a leader
reading "Same as (1): Moss, Avery (drew)" still has to look up Drew's answer by hand.

Fix direction: resolve the referenced name against the same sheet and display the resolved
status, falling back to the current behavior when the name does not match exactly one cadet.

---

## Chain of command has to be maintained by hand in contacts.yaml [enhancement]

`contacts.yaml` declares each cadet's 1UP and 2UP. Every promotion, transfer or squad
reassignment means editing that file, and a stale entry escalates to the wrong leader with no
error.

This was a deliberate trade — the role column in real sheets is inconsistent enough that a
parser would guess wrong silently — but the maintenance now falls on whoever runs the tool.

Fix direction: derive the chain from the sheet's leadership column, keep `contacts.yaml` as an
override, and report at startup any cadet whose leader could not be determined.

---

## Replace carrier SMS gateways with a messaging API [enhancement]

Texts currently go out as email to carrier gateways (`5405550100@vtext.com`). That needs each
cadet's carrier on file, gives no delivery confirmation, sends from an address recipients may
filter as spam, can be blocked by a carrier without notice, and only covers the six US
carriers in `notify.SMS_GATEWAYS`.

Fix direction: move sending to a messaging API such as Twilio. Costs money per message, so it
is a deployment decision rather than a default.

---

## Dashboard uses a single shared password [enhancement]

`webapp` authenticates against one `DASHBOARD_PASSWORD` with no per-user accounts, audit trail
or roles, while the pages display cadet phone numbers and email addresses. That is below what
this data should sit behind before real use.

Fix direction: VT credentials, with access scoped so a squad leader sees their own squad.

---

## Needs a host that stays on [enhancement]

`tick` runs from cron, or from the dashboard's in-process scheduler with `SCHEDULER_MINUTES`.
Both stop when the laptop running them sleeps, so a reminder can be skipped entirely rather
than sent late.

Fix direction: deploy to a hosted environment with the scheduler running continuously.

---

## Never connected to a live Corps sheet [enhancement]

Everything has been validated against sheets with fabricated names in the real layout. Reading
a live company sheet requires organizational approval and a read-only service account, which is
the gate on everything else in deployment.

---

## Notify cadets before an event regardless of response status [enhancement]

Survey responses asked for a reminder shortly before an event starts, not only for missing
responses. The pre-event pass in `Engine._pre_event` already runs at the right moment and
currently messages only cadets whose cell is blank.

---

## Extend the parser to service hours and duty squad rotations [enhancement]

The company sheets we examined carry service-hour logs and duty-squad rotations in separate
sections. Both are tracked by hand with no reminders, which is the same problem this tool
already solves for attendance.
