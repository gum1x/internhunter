# InternHunter Upgrade Plan — More Jobs · Anti-Slop Reading · Better People/Emails

> Three goals: (1) find **many more jobs incl. niche/rare great ones**, (2) an **anti-slop stage that actually reads jobs** so spam/ghost/low-quality are filtered, (3) **much better people/email finding**. Self-hosted, $0. Built on a fresh 7-agent audit + web-research pass (see workflow `wf_5429ba35-179`).

**Status:** BUILT (Phases 0–3) — scheduled discovery + channel multipliers, anti-slop quality reading (heuristics + sightings + LLM judge + keep-and-flag gates), and contacts upgrades (domain resolver + GitHub/Gravatar HTTPS verification + re-ranking) are implemented and tested. Phase 4–5 (new ATS pollers, aggregator APIs, MinHash cross-board dedup, calibration loop) remain as future work.

---

## 0. Decisions locked in

| Topic | Decision | Effect on plan |
|---|---|---|
| Discovery priority | **New discovery channels** (not new ATS pollers, not aggregator APIs) | Workstream A leads with channels: scheduled discovery, broadened dorks, GitHub lists, crt.sh, JSON-LD. New ATS pollers + aggregator APIs deferred to later phases. |
| Anti-slop bias | **Keep + flag, never hard-hide** | Nothing is deleted or hard-filtered from the store. Quality is scored + flagged; the dashboard **defaults** to hiding low quality but it's a toggle; only push-notifications skip clear-bad (the job still shows in the dashboard). |
| LLM reading | **Cheap-first; LLM only on borderline** (GPU is a GTX 1050 Ti) | Heuristics + embedding prefilter do the bulk for free; the local LLM reads only heuristic-flagged / borderline top-k jobs. |

### Constraints (reuse, don't rebuild)
- **$0 / self-hosted.** No paid APIs. Free keys (GitHub PAT, optionally USAJOBS/Findwork) only behind env config. Aggregator *pages* (TheOrg, RocketReach public) reached via **SearXNG dorks**, never their APIs.
- **Reuse infra verbatim:** SearXNG, stealth browser (`needs_browser` like `icims`/`adp`), local llama.cpp `LocalBackend` + `LlmCache`, `match/embed.py` cache, residential IP, `settings.github_token`.
- **Port 25 blocked (confirmed).** `verify_smtp.py` stays wired-but-off. All verification is HTTPS-based (holehe, **GitHub commit-search**, **Gravatar**) or inference. No SMTP relay.
- **SQLite `create_all` only CREATES tables, never ALTERs.** No Alembic. So **all new columns on existing tables ship in ONE batched idempotent `ALTER TABLE` migration** (`PRAGMA table_info` → add-if-missing); new tables (`Sighting`) are free. Design columns up front.
- **False-keep > false-drop** for great niche jobs. Anti-slop *annotates and ranks*; never silently deletes.

---

## Workstream A — Discovery Expansion (channels-first)

Two-stage architecture: **discovery** grows a `(ats, token)` board registry; **sources** poll each board. The chokepoint for the whole long tail is `discovery/fingerprint.detect_from_url` — an unrecognized ATS is invisible to every channel. New channel = `async def discover_from_X(ctx, ...) -> list[Detection]` wired into `cli._cmd_discover` + argparse, flowing through `merge_boards` for free.

### A0. Schedule discovery — *the single highest-leverage change* — `scheduler.py` + `core/runner.py`
Today `scheduler.py` runs only `run_poll` + `run_find_contacts`; **discovery never runs automatically**, so the 160-board registry stays starved (95 greenhouse / 40 lever / 20 ashby / 5 misc; **14 supported ATS at zero**). Add `run_discovery()` that runs the cheap channels (`common_crawl`, `urlscan`, `hackernews`, `internship_lists`, `job_apis`) in one `build_fetch_context` → `merge_boards`; register on a daily `IntervalTrigger` gated by `settings.enable_scheduled_discovery=True`.
- **Verify:** `build_scheduler()` contains job id `discover-all`; integration test runs `run_discovery()` on fixtures and asserts `Board` rows grow and span ≥10 distinct ATS (vs 6 today).

### A1. Broaden SearXNG dorks to all 20 ATS × niche keywords — `discovery/searxng.py`
Replace the 5 hardcoded queries with generated `site:` dorks across **all 20 ATS hosts** × {`intern`, `co-op`, `"summer 2026"`, `"early career"`, `apprentice`, `"working student"`, `new grad`}; raise `max_pages`. Pure data change.
- **Verify:** generated queries cover every ATS in `fingerprint._SUBDOMAIN_ATS` + each keyword; recorded-response test merges detections.

### A2. Expand GitHub list ingestion — `discovery/internship_lists.py`
Extend `_LISTS` (2 → 7+): add `SimplifyJobs/New-Grad-Positions`, `speedyapply/2026-SWE-College-Jobs`, `zapplyjobs/Internships-2026`, `zapplyjobs/New-Grad-Jobs-2026`, `vanshb03/Summer2027-Internships`, `Ouckah/Summer2025-Internships`. Apply URLs auto-feed `detect_from_url` → free registry growth. **Cheapest large gain.**
- **Verify:** per-repo fixture test: `entry_to_job` yields a `NormalizedJob` and `detect_from_url` resolves a board.

### A3. crt.sh certificate-transparency careers-subdomain enumeration — new `discovery/crt_sh.py`
Query `crt.sh/?q=%25.{domain}&output=json` (keyless), filter SANs to `careers.*`/`jobs.*`/`talent.*`/`apply.*`, resolve CNAMEs (`careers.x.com` CNAME'd to `*.greenhouse.io`/`*.myworkdayjobs.com` = an instant board), `detect_from_url` each. **Unlocks custom-domain ATS deployments that URL-pattern matching structurally cannot see — where the rarest boards hide.** Wire `--method crtsh` + the scheduled per-company pass.
- **Verify:** recorded crt.sh fixture + CNAME→ATS map test resolves a custom-domain careers host.

### A4. JSON-LD `JobPosting` harvesting — `discovery/sitemap.py` / `core/fetch.py`
Parse `<script type="application/ld+json">` for `@type:JobPosting` (`title`, `datePosted`, `validThrough`, `hiringOrganization`, `url`) → run `url` through `detect_from_url`. Covers **ATS-less custom career pages** (the Google-for-Jobs surface) no poller reaches.
- **Verify:** HTML-with-embedded-JobPosting fixture yields detections.

### A5. Paginate Common Crawl + fill urlscan gaps — `common_crawl.py`, `urlscan.py`
Page the CDX index (don't `break` after first crawl); add host globs (`*.pinpointhq.com`, `careers.jobscore.com`, `*.teamtailor.com`, `*.taleo.net`, `feed.homerun.co`). Extend `urlscan._ATS_QUERIES` to the 7-8 missing supported ATS.
- **Verify:** CDX pagination yields >1 page on a fixture; queries/patterns cover all 20 ATS.

### A6. Re-resolve `listing` jobs into real boards — new pass
`job_apis.py`/`internship_lists.py` store unresolved apply URLs as `ats="listing"`. Add a pass that selects those DB jobs, runs `detect_from_url` (+ careers-page fetch via `resolve_company_ats`), `merge_boards`. Free long-tail already in the DB.
- **Verify:** a `listing` job whose apply URL is a Greenhouse board mints a Greenhouse `Board`.

### A7 (deferred per "channels-first"). New ATS pollers (Pinpoint/JobScore/Polymer/Trakstar, then Teamtailor/Comeet), free aggregator APIs (USAJOBS/Findwork/RemoteOK), Workday tenant enumeration, accelerator portfolios, favicon/HTML fingerprinting. Sequenced after the channels prove out.

---

## Workstream B — Anti-Slop Quality Reading (keep + flag)

Tier-A jobs come from company-owned ATS boards, so outright scams are rare; dominant slop in priority order: **(1) ghost/evergreen, (2) cross-board/agency reposts, (3) boilerplate/low-substance, (4) scam/MLM**. Architecture: **cheap heuristics gate the expensive LLM read**, mirroring the existing regex-classify → embedding → LLM-top-k pattern. **Nothing is hard-dropped** — every signal is stored and the dashboard filters.

### B1. Heuristic anti-slop pre-filter (free, per-job) — new `match/quality.py`
Pure `classify_quality(...) -> (score, flags, verdict_hint)` called in each source's `normalize()` right after `classify_internship`. Detects: content-free (<~300 chars), agency/recruiter (`our client`, `staffing`), MLM/scam (`commission only`, `pay a fee`, Telegram/WhatsApp-only, personal-gmail apply — weighted by source trust), ghost/evergreen language (`always hiring`, `talent pool`, `pipeline`), ghost duration (`days_open` vs ~41d US avg), requirement incoherence (intern + "5+ years", reuse `internship_filter._SENIOR_RE`). Soft score + flags, **never a drop**. `is_rolling` weighted near zero (internships legitimately use rolling — the prime false-drop trap).
- **Verify:** crafted fixture per flag class; a rolling-internship fixture stays well above any threshold.

### B2. Per-job sighting log (strongest ghost signal) — new `Sighting` table
`create_all`-free table `(job_uid, content_fingerprint, first_seen, last_present, poll_count)`, written each poll in `runner.poll_boards`. Enables open-duration + evergreen detection (reqs that vanish/reappear every ~30-45d with unchanged text). Feeds B1's ghost score.
- **Verify:** 3 simulated polls increment `poll_count` and compute `days_open`; identical-fingerprint repost after a gap is flagged.

### B3. LLM "read-the-content" verdict (borderline-gated) — new `llm/quality.py`
Mirror `llm/score.py` (same loop, `complete(... system=QUALITY_SYSTEM, cache=LlmCache)`; `sha256(model+system+prompt)` auto-namespaces from fit scores). The model **reads** the JD → enum-constrained JSON: `{"legit":0-100,"substance":0-100,"verdict":"ok|spam|ghost|agency|mlm|unclear","flags":[...],"confidence":0-100,"reason":"..."}`. **Separate axes** (a low-*fit* niche job is never marked low-*quality*); **explicit abstention** (`unclear`) is the key anti-false-drop lever; free-text `reason` first, then constrain final JSON; unparseable → `unclear`, never auto-pass. **Gated to heuristic-flagged / borderline top-k** ordered by `discovery_score` to bound GPU cost.
- **Verify:** clear-scam fixture → `spam`; terse legit-startup fixture → `unclear`/`ok` not `spam`; unparseable → `unclear`.

### B4. Persist verdicts + wire gates (keep + flag) — `core/db.py`, `core/models.py`, `notify/select.py`, `web/app.py`, `match/score.py`
Batched-migration `Job` columns: `quality_score`, `quality_verdict`, `quality_flags` (JSON), `quality_confidence`, `quality_model`, `quality_checked_at`, `quality_flags_heuristic` (JSON). Mirror in `NormalizedJob` + `_SCALAR_FIELDS`.
- **Dashboard** (`web/app.py`): add a quality column + a **default-on "hide low quality" toggle** the user can switch off — jobs are never removed from the store, only filtered in the view.
- **Notifications** (`notify/select.py`): push-notify skips high-confidence `spam/ghost/agency/mlm` (the job still appears in the dashboard — this isn't hiding, just not paging you about slop).
- Optionally fold quality into `discovery_score` as a soft multiplier in `match/score.py` for ranking.
- **Verify:** a `spam`/high-confidence job is filtered from the default dashboard view but still query-able with the toggle off; migration test adds columns idempotently on a pre-existing DB with rows intact.

### B5 (later). Cross-board/agency repost dedup: extend `core/dedup.py` with a `company_domain` secondary key + **MinHash-LSH (datasketch, $0)**; wire the currently-unused `semantic_dedup.py`; conservative threshold (prefer tier-A canonical). Plus an embedding-centroid boilerplate pre-score. **B6 (recurring):** hand-label 50-100 postings, target ≥75% judge agreement, version the rubric.

---

## Workstream C — People/Email Upgrades

Baseline is solid but **domain-gated and mostly opt-in**. The #1 defect: no source populates `company_domain`, so `_guess_domain` returns `{slug}.com` and silently zeroes hit-rate.

### C1. Resolve real company domains (unblocks everything) — `contacts/runner.py`
Replace `_guess_domain`'s slug fallback with a resolver: (1) apply/careers URL host from the company's job rows (already in DB); (2) SearXNG `"{name}" official site` dork; (3) MX existence (dnspython) + homepage-title sanity; (4) crt.sh domains from A3. Persist `Company.domain` + `domain_confidence`; **require corroboration (MX + a same-domain scraped email/pattern) before *trusting*** a domain, to avoid confidently-wrong emails.
- **Verify:** when a job's apply-URL host ≠ `{slug}.com`, resolver picks the real host; non-resolvable falls back + marks low confidence.

### C2. Working defaults + startup self-check — `config/settings.py`, `contacts/runner.py`
Flip the good-but-off parts on: document GitHub PAT, `verify_emails=True`, enable team-page extraction when a domain resolves, default `searxng_url`. Add a self-check logging which sources are actually live (SearXNG reachable? PAT set? browser? LLM up?).
- **Verify:** self-check reports each source live/dead from settings.

### C3. GitHub commit-search email↔account bridge (highest single win) — new `contacts/people/github_commits.py` + `contacts/email/verify_github.py`
Use `GET /search/commits?q=author-email:<email>` / `?q=author:<login>` with the PAT; read the **resolved top-level `author.login`** (non-spoofable, *not* the spoofable `commit.author`). Three uses: email→account existence (near-proof a mailbox is real — cleaner than holehe for tech cos); username→historical emails (corpus fuel for `infer.py`); `@domain` commit search → many real `(name,email)` pairs to push domains past the K≥2 pattern lock.
- **Verify:** recorded fixture extracts the resolved `login` (not commit email); an email with a resolved login is marked verified.

### C4. Gravatar verification + enrichment — new `contacts/email/verify_gravatar.py`
SHA-256/MD5 the email, `GET gravatar.com/<hash>.json`: 200 = real used mailbox (+confidence); `verified_accounts` backfills LinkedIn/GitHub/Twitter URLs in one call. ~30 LOC, no dep, hard-cached.
- **Verify:** Gravatar fixture raises confidence and parses social URLs.

### C5. New free people sources — `contacts/people/`
SEO-aggregator dorks in the existing `searxng_people.py` loop (**TheOrg first** — structured org charts, recruiter-rich; then rocketreach/signalhire/zoominfo/apollo public pages); search-engine diversity (Brave/DDG/Bing/Mojeek/Marginalia) for better `/in/` indexation; GitHub `/search/users?q=` by company + social-graph walk; non-LLM JSON-LD `Person` team-page crawler fallback; parse recruiter names from the JD itself. All feed existing `DiscoveredPerson` dedupe.
- **Verify:** per-source fixture extracts people; dork-builder generates TheOrg/RocketReach queries per company.

### C6. Expand email pattern corpus — `contacts/email/harvest.py`, `infer.py`
Add free fuel: GitHub `@domain` commit search (C3); **search-snippet scraping** of `"@{domain}"` across SearXNG (regex emails from snippets — Hunter's seeding method); **PDF mailto mining** (`site:{domain} filetype:pdf` + pdfminer). Skip WHOIS (GDPR-redacted). More pairs → more K≥2 locks → `guessed`→`probable`.
- **Verify:** snippet/PDF pairs feed `infer_pattern`; a previously-unlocked domain now locks.

### C7. Provider-aware modeling + fix always-None headcount — `contacts/email/priors.py`, `runner.py`
Classify MX (Google Workspace / M365 / Zoho / parked) via dnspython; condition prior + permutation order on provider; handle subdomain mail + accent/hyphen variants. Populate `headcount_band` (job count / GitHub org size) so size-aware priors actually fire. Keep `is_catch_all=null` (untestable without port 25 — don't fake).
- **Verify:** MX classification selects the right provider prior; non-None headcount changes the default template.

### C8. Recalibrate confidence + re-rank after email finding — `contacts/score.py`, `runner.py`
Raise locked-pattern (votes≥2) confidence; weight holehe by which site matched; gate the hardcoded-80 alias on real evidence. **Move top-N truncation to AFTER email finding**, rank by `role_priority × contactability(email_confidence)` (a reachable "probable" recruiter > an unreachable "guessed" VP). Better cross-source dedup (LinkedIn-URL/GitHub-login exact > RapidFuzz token-sort). Populate unused `Company` columns. Skip missing `theHarvester` cleanly.
- **Verify:** locked pattern scores ≥ new "probable" floor; reachable recruiter out-ranks unreachable VP.

---

## Data model & migration (design once, migrate once)
- **New table (free):** `Sighting(id, job_uid, content_fingerprint, first_seen, last_present, poll_count)`.
- **New `Job` columns → one batched idempotent migration:** `quality_score`, `quality_verdict`, `quality_flags`, `quality_confidence`, `quality_model`, `quality_checked_at`, `quality_flags_heuristic`. Mirror in `NormalizedJob` + `_SCALAR_FIELDS`.
- **`Company`:** add `domain_confidence`; populate existing-but-unwritten `is_catch_all`/`linkedin_url`/`github_org`/`headcount_band`.
- **Settings:** `enable_scheduled_discovery=True`, `discovery_interval_min=1440`, default flips for `verify_emails`/`contacts_methods`, optional `usajobs_api_key`/`findwork_api_key`.
- **Migration verify:** open a pre-existing DB without the columns, run `init_db`, assert all new columns/tables exist and existing rows intact.

---

## Phased rollout (each independently verifiable)
- **Phase 0 — Fill the starved registry.** A0 (schedule discovery). *Verify: board count + ATS spread jump.* ← biggest job win, near-zero code.
- **Phase 1 — Cheap channel multipliers.** A1 (dorks), A2 (lists), A3 (crt.sh), A4 (JSON-LD), A5 (CC pagination/urlscan), A6 (re-resolve listings). *Per-fixture registry-growth tests.*
- **Phase 2 — Anti-slop core.** Batched migration + `Sighting`, B1 (heuristics), B2 (sightings), B3 (LLM judge, borderline-gated), B4 (keep+flag gates). *Slop fixtures flagged; niche-rolling not dropped; migration idempotent.*
- **Phase 3 — Contacts unblock.** C1 (domain resolver), C2 (defaults+self-check), C3 (GitHub bridge), C4 (Gravatar). *Real-domain resolution + HTTPS verify raise confidence.*
- **Phase 4 — Corpus + sources + recalibration.** C5, C6, C7, C8. Then the deferred A7 (new ATS pollers, aggregator APIs) if wanted.
- **Phase 5 — Long-tail.** B5 (MinHash cross-board dedup + boilerplate centroid), B6 (calibration loop), heavier discovery.

---

## Risks & mitigations
- **SQLite alter trap** → one batched idempotent `ALTER TABLE` + migration test on a pre-existing DB.
- **False-dropping niche jobs** (explicit anti-goal) → soft scores, separate LLM axes + abstention, keep+flag (never delete), `is_rolling`/duration near-zero for internships.
- **Wrong domain → wrong emails** → require MX + same-domain corroboration before trusting; store `domain_confidence`.
- **Rate limits / bans** (SearXNG, GitHub 30/min, crt.sh) → per-host limiter, PAT pacing, daily cadence, caching, graceful per-source failure.
- **Prompt injection from job text** → enum-constrained verdict, unparseable→`unclear`, don't reveal the source board (avoids "big co = legit" bias).
- **LLM cost/latency on the 1050 Ti** → heuristics + embedding prefilter gate the judge to top-k; cache keyed on text+rubric version (not timestamp).

## Realistic expectations
- **Jobs:** the largest jump is Phase 0/1 — *running* discovery into the 14 zero-coverage ATS the engine already supports. crt.sh + JSON-LD add genuine custom-domain long-tail; new pollers add breadth at diminishing rates.
- **Anti-slop:** heuristics + sightings catch the majority of ghost/content-free/agency slop for free; the LLM handles the ambiguous minority. Rank-and-hide, not perfect classification.
- **People/email:** fixing domain resolution + turning on already-built sources is most of the win; GitHub commit-search + Gravatar give real HTTPS verification for tech mailboxes. Labels stay honest: scraped/GitHub-resolved+confirm ≈ "verified" ceiling 85-90; pattern-inferred → "probable"; prior-only → "guessed".

---

## Open questions (need a decision before/within build)
1. **SearXNG URL** — `settings.searxng_url` is empty today; many channels (dorks, TheOrg/people dorks, official-site domain resolution) are inert without it. What's the instance URL? (You have SearXNG on the VPS.)
2. **GitHub PAT** — OK to set `settings.github_token` (free)? Lifts 60→5000 req/hr and enables the commit-search bridge + list ingestion + user search. Biggest single people/email lever.
3. **DB migration vs rebuild** — preserve existing rows (→ batched `ALTER TABLE` migration, the plan's default) or is a drop-and-recreate acceptable for now?
4. **LLM backend for the judge** — confirm `llm_base_url`/model is live (the box runs `llama-server`, was on `:8770`) and whether it supports GBNF/JSON-schema constrained decoding (else we rely on `extract_json` best-effort).
