# Plan: Application Tracker tab ("CSV")

## Goal
A third dashboard tab — **Tracker** — that works like an editable spreadsheet for the
internships you're pursuing. From any job row you click **Add to tracker**; the job is
snapshotted into a row you can edit inline (status, emailed, due date, notes, contact),
and download as CSV anytime.

## Confirmed decisions
- **Live in-dashboard**, DB-backed and editable inline (not a flat .csv file). CSV is a *download*.
- **Statuses:** `To Apply → Applied → Interviewing → Offer → Rejected` (default `To Apply`).
- **Auto-fill best contact** (name + email) for the company on add; editable, blank if none known.

## Columns (tracker table + CSV export)
Company · Role · Location · Due date · Status · Emailed (Y/N) · Contact name · Contact email · Link · Applied on · Notes

---

## Design

Reuse the existing **`applications`** table (already in `core/db.py`, currently
`id, job_uid, status, resume_path, notes, updated_at`). Snapshot the display fields onto
the row at add-time so the tracker/CSV is self-contained and stable even if the job changes;
keep `job_uid` for dedupe + the "already tracked?" badge.

### 1. Model — extend `Application` (`internhunter/core/db.py`)
Add columns to the model **and** to `_ADDED_COLUMNS["applications"]` (the live DB already has
the `applications` table, so `create_all` won't add columns — the ALTER-based migration must):

| column | type | note |
|---|---|---|
| `company` | VARCHAR | snapshot of `Job.company` |
| `role` | VARCHAR | snapshot of `Job.title` |
| `location` | VARCHAR | `Job.location_normalized or location_raw` |
| `link` | VARCHAR | `Job.canonical_url` |
| `due_date` | DATETIME | defaults from `Job.deadline_at`, editable |
| `emailed` | BOOLEAN | default `False` |
| `contact_name` | VARCHAR | auto-filled, editable |
| `contact_email` | VARCHAR | auto-filled, editable |
| `applied_at` | DATETIME | nullable; set when status → Applied, editable |
| `created_at` | DATETIME | default now |

- Change `status` default `"new"` → `"To Apply"`.
- **Idempotency in code** (no unique constraint — `create_all` can't add one to an existing
  table): the add route upserts by `job_uid` (existing → no-op, return it).

### 2. Routes (`internhunter/web/app.py`) — mirror the contacts tab
- `GET /tracker` → `tracker.html`. Rows sorted by `due_date` asc (nullslast) — soonest first;
  optional `?status=` filter. Shows count + Download CSV button.
- `POST /jobs/{job_uid}/track` → idempotent add: snapshot fields + `_best_contact()`,
  status `To Apply`. Returns the swapped button (`✓ Tracked`).
- `POST /tracker/{id}/update` → inline edit one field (status / emailed / due_date / notes /
  contact_name / contact_email / applied_at). Returns the updated `_tracker_row.html`.
  When status set to `Applied` and `applied_at` empty → stamp today.
- `POST /tracker/{id}/delete` → remove; returns empty (row drops out via HTMX swap).
- `GET /tracker/export.csv` → CSV with the columns above (reuse `_csv_safe`).
- Helpers:
  - `_best_contact(company_slug) -> tuple[name|None, email|None]` — top `Contact` by
    `priority` (then `confidence`) that has an email; prefer `email_status` verified/probable.
  - `_tracked_uids(jobs) -> set[str]` — which displayed jobs are already tracked (for the badge),
    added to `_page_context` like `_scores_for`.

### 3. Templates (`internhunter/web/templates/`)
- **`tracker.html`** (new) — page with nav (Jobs · Contacts · **Tracker**), the table,
  Download CSV, per-row delete, status `<select>`, emailed checkbox, due-date `<input type=date>`,
  notes text — all `hx-post`-ing to `/tracker/{id}/update` with `hx-trigger="change"`.
- **`_tracker_table.html`** (new) — table body fragment (HTMX target for add/delete refresh).
- **`_tracker_row.html`** (new) — single-row fragment for inline-update swaps.
- **`_table.html`** (jobs) — add an **Add to tracker** button per row:
  `hx-post="/jobs/{{job.job_uid}}/track" hx-swap="outerHTML"`, renders `✓ Tracked` when in
  `tracked` set. (+1 colspan on the pager row.)
- **`index.html` / `contacts.html`** — add the **Tracker** nav link (and a "Tracked: N" stat on index).

### 4. Tests (`tests/test_tracker.py`, new)
- add creates a row with snapshot + auto-filled contact + status `To Apply`
- add is idempotent (second add → same row, no dup)
- update changes status & flips emailed; status→Applied stamps `applied_at`
- delete removes the row
- `/tracker/export.csv` contains the tracked row's company + email
- `_best_contact` picks highest-priority contact with an email
- `_tracked_uids` reflects in the jobs page context

### 5. Deploy
- rsync changed files (db.py, app.py, templates, tests). `init_db` runs the migration on
  restart (adds the new `applications` columns to the live DB — **data preserved**).
- Restart `serve`; smoke-test add → edit → CSV download.

---

## Files touched
- `internhunter/core/db.py` — extend `Application` + `_ADDED_COLUMNS["applications"]`
- `internhunter/web/app.py` — 5 routes + 2 helpers + context additions
- `internhunter/web/templates/tracker.html`, `_tracker_table.html`, `_tracker_row.html` (new)
- `internhunter/web/templates/_table.html`, `index.html`, `contacts.html` — nav + button
- `tests/test_tracker.py` (new)

## Out of scope
- Calendar/reminder integration for due dates (just stored/sorted).
- Auto-status changes from email sends (manual toggle).
- Editing the underlying job from the tracker (snapshot only; re-add to refresh).

## Verification (success criteria)
1. `pytest` green incl. new tracker tests · ruff · mypy clean.
2. On the live dashboard: **Add to tracker** on a job → appears in Tracker with company/role/
   location/link/due date + auto-filled contact, status `To Apply`.
3. Change status/emailed/due date inline → persists across reload.
4. **Download CSV** → opens in Excel with all columns.
5. Existing 188k jobs + scores + contacts untouched (migration only ADDs columns).
