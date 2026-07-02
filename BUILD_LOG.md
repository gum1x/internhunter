# BUILD_LOG — InternHunter → internship-landing system

---

# Round 2 — Company dossiers + outreach enrichment (2026-07-02)

Two additions on top of the round-1 system: a per-firm research **dossier generator**
(`internhunter dossier build`) and an **outreach enrichment pass** that attaches the
dossier, likely contact, and a register-correct draft to every tracked posting.
Status: **built, tested (583 passing), live two-firm trace completed.**

## What was built

### Dossier generator
- **`internhunter/dossier/research.py`** — keyless public-page research per firm:
  homepage/about/blog/news/team through the shared rate-limited + disk-cached fetcher
  (one firm at a time, ≤5 pages), meta/og description, schema.org Organization facts
  (team size, founded), **dated** blog/news links as signal candidates (undated or
  question-headline links are never treated as news), optional SearXNG search.
- **`internhunter/dossier/build.py`** — orchestration: staleness-windowed incremental
  builds (`dossier_staleness_days`, `--force`), LLM synthesis via the existing backend
  (claude CLI / API / local) with **anti-fabrication validation**, heuristic fallback
  when no LLM is available, deterministic confidence rubric, `dossiers/<slug>.md` +
  `dossiers/index.json` + a `dossiers` DB table as the machine-readable index.
- Signals also come from already-verified government data in the DB (recent SEC Form D
  via EDGAR leads, SBIR filings).
- **`internhunter/config/pitch.yaml`** — Ryan's positioning/proof points and per-tag
  "why I fit" angle lines; the dossier's why-fit is seeded from the firm's tags and
  never invents firm facts.

### Anti-fabrication design (criterion 2)
- The LLM never writes a URL, person, or number into a dossier: it summarizes fetched
  text and **selects a signal by index** from deterministically extracted, dated
  candidates (an explicit "nothing notable" is respected).
- `validate_synthesis` drops any stage/team-size value that does not literally appear
  in the fetched material.
- Contacts come only from the contacts pipeline's provenance-carrying rows
  (`person_source` required; emails only if verified/probable). No named person found →
  the dossier says so explicitly and records a real channel (registry board URL or
  `https://<domain>/careers`).
- Confidence is computed by rubric (high = summary + dated signal + sourced contact;
  low = thin/no summary), never self-reported by the LLM.

### Outreach enrichment
- **`internhunter/outreach.py`** — runs inside `track_job` (so both alerted and
  dashboard-tracked postings enrich): attaches the dossier (slug/canonical-name/domain/
  board-token matching — greenhouse's `wehrtyou` resolves to Hudson River Trading via
  the registry), fills the contact, and stores a register-correct draft: warm rows get
  the connections.yaml intro ask; cold rows get a 3-5 sentence founder/eng-lead message
  seeded from the dossier + pitch with a literal `{{proof_link}}` placeholder.
- No dossier yet → the row stays flagged (`dossier_slug IS NULL`, ⏳ in the dashboard);
  the next `dossier build` (scheduled daily) researches that firm — even if it's not in
  targets.yaml — and **backfills** the pending rows.
- `internhunter tracker draft <id>` prints the enriched contact + dossier + draft.
- Dashboard tracker rows show 🤝/📋/⏳/✉️ status per posting.

## Key decisions
- Dossier synthesis reuses the existing `llm/client.py` backend chain (cli/api/local)
  with on-disk caching; `dossier_use_llm=false` or a missing backend degrades to the
  deterministic heuristic — the pipeline never blocks on an LLM.
- Drafts are deliberately template-seeded (dossier facts + pitch angles), so a wrong
  claim can't be generated: every sentence traces to targets.yaml tags, pitch.yaml
  claims, or verified dossier fields.
- Enrichment never overwrites user edits: existing contact/draft/company values are
  preserved; only token-looking company snapshots are upgraded to the verified name.

## Live two-firm trace (criterion 6)
Fresh DB → polled live `ashby/polymarket` (56 jobs) + `greenhouse/wehrtyou` (75 jobs) →
`dossier build --company polymarket` and `--company hudson-river-trading` ran real web
fetches + claude-CLI synthesis:
- **Polymarket** — summary correctly says it runs a prediction market with 0-100¢
  implied-probability shares; about/blog/team pages 403'd (bot-wall) and are recorded
  in notes; no fabricated contact — channel `polymarket.com/careers`; confidence medium.
- **HRT** — summary correctly identifies an automated liquidity-providing trading firm;
  channel `hudsonrivertrading.com/careers`; confidence medium.
- The first Polymarket build surfaced two real bugs, both fixed with tests: market
  question pages ("Will X happen?") were being picked as company news (now filtered +
  the LLM's explicit null respected), and the fallback channel showed an Ashby API URL
  (now prefers a human careers URL).
- `notify --channel feed` → 3 alerts auto-tracked and enriched: the Polymarket row came
  out 🤝 warm (intro ask via the price-discovery contact), the HRT rows ❄️ cold with
  send-ready drafts greeting "Hi Hudson River Trading team", referencing HRT's actual
  business, and carrying `{{proof_link}}`.

## Blockers / caveats
1. **Named contacts require the contacts pipeline to have run** (`find-contacts`);
   in a fresh DB dossiers honestly report "no named person verified" with the careers
   channel. Run `internhunter find-contacts --company <slug>` to upgrade a firm, then
   `dossier build --company <slug> --force`.
2. Several target firms' sites bot-wall subpages (Polymarket about/blog/team 403);
   dossiers note every failed fetch and confidence caps at medium without a signal.
3. Stage/funding data rarely appears on firms' own pages; without SearXNG configured it
   is usually "not verified" (deliberate: no invented funding numbers). Configure
   `INTERNHUNTER_SEARXNG_URL` to improve stage/signal coverage.

## Verification
- 583 tests pass, ruff clean, mypy --strict clean (165 files). New: research
  extraction (10), build/validation/confidence/incremental (14), outreach/enrichment
  (13), scheduler dossier job (1), plus updated tracker/scheduler suites.

---

# Round 1 — alert pipeline, targets, tracker, referrals

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
