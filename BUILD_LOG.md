# BUILD_LOG — InternHunter → internship-landing system

Autonomous build extending InternHunter into a push-based, tracked, referral-aware
pipeline. Scope: (1) source tuning, (2) alert pipeline, (3) pipeline tracker,
(4) referral engine, (5) cadence/scheduling. Status: **built, tested (550 passing),
end-to-end traced against live boards.**

## What was built

### 1. Source tuning
- **`internhunter/config/targets.yaml`** — the single user-editable file: target firms
  (with domains/tags/priority), include/exclude keywords, seniority bands
  (intern / early / founding), locations + remote policy, funding stages.
- **`internhunter/match/targets.py`** — evaluates every job against that file
  (firm match by domain/slug/canonical name; keyword include; exclude hard-veto;
  location gate). mtime-cached so edits apply on the next run without restart.
- **Registry seeding** — probed candidate ATS tokens for the target list live and
  committed the 12 that verified (HTTP 200 with jobs): Palantir (lever), Polymarket +
  Kalshi (ashby), and greenhouse boards for Hudson River Trading (`wehrtyou`), Jump
  Trading, DRW (`drweng`), IMC, Optiver (`optiverus`), Five Rings, Akuna, Tower
  Research, Virtu. Already present: Anthropic, OpenAI, Scale, Perplexity, Mistral,
  Anduril, Shield AI, Ramp, Mercury, Vercel, Retool.
- **Startup sources**: YC / Work-at-a-Startup / HN / Greenhouse-frontier already
  existed; the VC channel already crawls a16z, Sequoia, General Catalyst (+7 more).
  Added **Wellfound** as an opt-in ingestor (`discovery/wellfound.py`) — see blockers.
- **`listing_common.listing_to_job(keep_early=True)`** — founding/first-hire titles now
  survive the interns-only filter for startup sources, tagged `early-stage`.

### 2. Alert pipeline
- **`notify/telegram.py`** — Bot API channel; one message per job with company, role,
  direct apply link, posting age, score, match reasons, and 🤝 warm-intro / ❄️ cold flag.
- **`notify/runner.py`** — `run_notify()`: selects jobs never alerted before
  (`Job.notified_at IS NULL`) first seen inside the lookback window, applies the
  targets filter (match OR `discovery_score >= notify_min_fit`), suppresses LLM-flagged
  slop, delivers (telegram / discord / ntfy / feed), marks delivered jobs, and
  auto-records each in the tracker. Runs on the scheduler every 30 min (configurable).
- CLI: `internhunter notify [--channel telegram|discord|ntfy|feed|all] [--dry-run]`.

### 3. Pipeline tracker
- **`internhunter/tracker.py`** on the existing `Application` table. Stage flow
  found → applied → referral-requested → interview → offer → rejected (stored in the
  dashboard's display vocabulary — "Referral Requested" added there too — so old rows
  and the web tracker keep working).
- CLI: `tracker summary | list [--stage] | set <id|job_uid> <stage> | intro <id> |
  export --out csv`.

### 4. Referral engine
- **`internhunter/config/connections.yaml`** — firms/domains → people (seeded with the
  GWU / Teach Anything AI / Polymarket-research / ULIMO / AffiliateLink edges as
  placeholders to fill in).
- **`internhunter/referrals.py`** — matching (domain, then suffix-stripped canonical
  firm name) + template-based `draft_intro()`. Warm matches flag the alert and are
  stored on the tracker row (`warm_intro`, `connection_name`, `intro_draft`).

### 5. Cadence
- `notify` job added to the APScheduler loop (`enable_scheduled_notify`,
  `notify_interval_min=30`). Poll(30m) + notify(30m) ⇒ new posting → phone in minutes.
- **`docs/SETUP.md`** — deploy from scratch: BotFather walkthrough, systemd / Docker /
  cron, tuning, troubleshooting.

## Key decisions
- **Once-only alerts** via a `notified_at` column on `jobs` (+ additive migration),
  stamped only after a channel accepts the message → failed sends retry next run;
  duplicates are impossible. `notify_max_per_run` caps a burst; overflow is held,
  best-first. `notify_lookback_hours` (48) stops a first run on a 13k-job DB from
  flooding the channel.
- **Tracker stage vocabulary** reuses the dashboard's statuses instead of introducing a
  second enum; CLI accepts the prompt's stage names as aliases. Existing DBs migrate
  additively (no destructive change anywhere).
- **Score-path alerts require `is_internship`;** keyword/firm-path alerts don't, so
  founding-engineer and quant-research roles can alert while generic high-score
  full-time roles can't.
- **Draft intros are template-based, not LLM** — instant, offline, deterministic; the
  user personalizes before sending.

## Blockers / caveats (build continued around them)
1. **Live Telegram verification requires a real bot token** — not available in this
   environment, so criterion "verified live" was proven with the same runner against
   the real Telegram HTTP API mocked (tests) plus a live end-to-end run using the
   `feed` channel. First real run: `internhunter notify --channel telegram` after
   setting the two env vars (docs/SETUP.md §2). Everything downstream (marking,
   tracking, warm intros) was verified live.
2. **Wellfound** has no official feed/API, a DataDome bot-wall, and ToS that restrict
   crawling → shipped **off by default**, limited to robots-allowed company pages for
   explicitly listed slugs, fail-soft. Startup coverage comes from YC/WaaS/VC/HN
   channels instead.
3. **Two Sigma, Summit Partners, SIG, Jane Street, Citadel, NSA/CIA** run proprietary
   ATSs with no keyless board API — no registry entry possible. They're listed in
   `targets.yaml`, so their postings still alert when they arrive via LinkedIn /
   listing ingestors; NSA/CIA roles arrive via the USAJobs ingestor.
4. Pre-existing classifier quirk: "Campus Recruiter" classifies as internship
   (kind=campus) — surfaced during the live trace; mitigated by adding `recruiter` and
   `phd` to the default exclude keywords rather than touching the tuned classifier.

## Verification
- 550 tests pass (`pytest -q`), ruff clean, mypy --strict clean (160 files).
- New tests: targets (15), referrals (10), telegram (10), notify runner (14, incl.
  API failure / retry / idempotency / cap / empty DB / dup uids), tracker stages (11),
  wellfound (6), scheduler notify wiring (2).
- Live end-to-end trace: seeded boards → `poll` (ashby/polymarket, greenhouse/wehrtyou,
  131 real jobs) → `notify --dry-run` → `notify --channel feed` (5 alerts, 2 warm-intro
  via connections.yaml) → second run alerts 0 (idempotent) → `tracker summary/list/
  intro/set/export` all exercised against the live rows.
