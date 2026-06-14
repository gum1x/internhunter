# InternHunter "Big-Smart" Upgrade — Net-New Discovery & People/Email Plan

> Round 3. Net-new clever ways to find MORE internships AND more hiring managers/employees+emails. Balanced across both; a mix of high-payoff-smart + proven-unused methods; nothing unnecessary; must not increase slop. Built on a fresh 6-agent audit+research workflow (`wf_e85ff740-4a2`), verified against the live code.

**Status:** BUILT (Phases 0–2) — MX-provider plumbing + OfficerLead; Wayback CDX, company-similarity expansion, ATS/description people-mining, GitHub events+profile+gated-graph; SEC EDGAR Form D channel, M365 GetCredentialType mailbox verification, and one-verified-email pattern-lock. All tested (279 passing, ruff+mypy clean). Phase 3 (Telegram channels, Wayback email-harvest) remains optional/deferred.

## 0. Decisions & constraints (verified against the live code, not just the reports)

- **Discovery chokepoint is well-factored.** A new channel is just `async def discover_from_X(ctx) -> list[Detection]` → `merge_boards()` (dedupe by `(ats,token)` + insert Board + append `registry/boards.jsonl`, which is what `run_poll` actually polls).
- **SmartRecruiters already FETCHES per-posting detail and THROWS IT AWAY** (`sources/tier_a/smartrecruiters.py:75,161`): `detail` (can carry `creator.name`) never reaches the DB. Zero-new-fetch people signal — but `creator` is often empty on large orgs → opportunistic, not the headline.
- **`description_text` is stored on every job and never scanned** for people or `@domain` emails — the broader untapped in-job signal.
- **`match/embed.py` (MiniLM + cache) is used only for job↔profile fit + intra-company dedup.** No company vector exists; the cache makes per-company embedding cheap.
- **`github_people.py` reads only org members + top-5-repo commit authors** — never `/users/{login}/events/public` (live-probed 200), never profile `.email`/`.blog`/`.company`.
- **`domain.py::has_mx` discards the MX exchange host** — no provider classification, so no per-mailbox HTTPS check today.
- **Already done (excluded as net-new):** early-career aliases (`RECRUITING_ALIASES` already has `university`/`campus`/`internships`); `verify_emails=True` by default.
- **Live-probed valid:** SEC EDGAR Form D full-text search returns real just-funded software startups + officer names; Telegram `t.me/s/<channel>` HTML; GitHub events API.
- **Constraints:** strictly $0/keyless/self-hosted; aggressive scraping OK; **port 25 blocked** (every verifier HTTPS/DNS); everything routes through `merge_boards`/the `DiscoveredPerson` funnel so it inherits the existing quality+sighting+dedup gates — the structural anti-slop guarantee.
- **Data-model rule:** new tables auto-create; new COLUMNS need a `(name,sql_type)` tuple in `_ADDED_COLUMNS` (idempotent `_migrate`) + `_SCALAR_FIELDS` for `Job` fields.
- **Balance:** Workstream A (jobs) and B (people+email) are equal-weight — three primary net-new methods each + shared embedding infra.

---

## Workstream A — Net-new JOB discovery

### A1. SEC EDGAR Form D — just-funded-startup channel (also seeds People) — **PRIMARY**
New `discovery/edgar.py::discover_from_edgar(ctx, days=14)`. Query `efts.sec.gov` Form D full-text (UA must carry a contact email, <10 req/s), read `primary_doc.xml` → `entityName`, `relatedPersonName[]`, industry; drop funds/SPVs; resolve name→website via one SearXNG dork → `resolve_company_ats` → `Detection`. **Bonus cross-link:** write officers to a new `OfficerLead(company_slug, full_name, source, filed_at)` table (auto-created) that Workstream B reads. *Net-new:* no funding/temporal signal exists; catches startups weeks before their first req. **Effort: M.**

### A2. Company-similarity expansion — embed boards you win on, crawl semantic neighbors — **PRIMARY (shared infra)**
New `discovery/similar.py::discover_similar_companies(ctx, top_k_neighbors=8)`. Reuse `match/embed.py`: embed `name + long_description` for the ~6k YC companies (currently `yc.py` discards `long_description`/`batch`/`subindustry` — start reading them); seed = high-`discovery_score`/high-fit companies; `cosine_matrix` → top-k unseen `isHiring` neighbors → `resolve_many` → `merge_boards`. Anchor to per-sector centroids (`config/sectors.yaml`) to avoid drift. *Net-new:* no company vector / similarity traversal today; targets the long tail by **relevance** not brute breadth. **Effort: S–M.**

### A3. Wayback Machine CDX — second keyless URL index — **PRIMARY**
New `discovery/wayback.py::discover_from_wayback(ctx)` mirroring `common_crawl.py`'s `_ATS_PATTERNS`. For each of the 20 ATS hosts, query `web.archive.org/cdx/search/cdx?url=<host>*&matchType=domain&collapse=urlkey&fl=original&output=json` (paginate, fail soft, cache) → `detect_from_url`. *Net-new:* a different, continuously-refreshed corpus vs CC's lagging snapshot; `merge_boards` dedupes and polling validates liveness. **Effort: S.**

### A4. (Secondary) Telegram public-channel apply-link harvest
New `discovery/telegram.py::discover_from_telegram(ctx, channels)`. Scrape `t.me/s/<channel>` HTML, `detect_from_html` → **resolve only the linked BOARD**; the trusted poller re-ingests the canonical job — the message is NEVER ingested as a job ("launders" a noisy signal). Seed list in `settings`, empty by default. **Effort: S, payoff: medium.**

**A wiring:** add each Detection channel to `runner.discover_all`'s `detection_channels` dict (daily pass) + CLI `--method` choices + `settings` knobs.

---

## Workstream B — Net-new PEOPLE + EMAIL finding

### B1. Mine the ATS detail + `description_text` we already store — zero new fetches — **PRIMARY**
New `contacts/people/ats_raw.py::discover_people_ats_raw(session, company_slug)` reading `Job.raw` + `Job.description_text` from the DB. (a) **SmartRecruiters `creator`:** persist `detail.creator` (merge into stored `raw` — no migration) → `DiscoveredPerson(role_category="recruiter", person_source="ats_creator")` when non-empty (opportunistic). (b) **In-description regex/NER (the real volume):** literal `@<company-domain>` emails → `known_email` (highest confidence); "Hiring Manager: X"/"report to X" patterns; bounded local-LLM only on borderline snippets (mirror `team_pages.py`). Wire `"ats_raw"` into `_discover_people` + `selfcheck`. *Net-new:* nothing reads `raw`/`description_text` for people. **Effort: M.**

### B2. GitHub deep-mine: `/events/public` + profile fields + gated social-graph — **PRIMARY**
Extend `github_people.py`. **Events API:** for each confirmed `login`, GET `/users/{login}/events/public`, read PushEvent `payload.commits[].author.{email,name}` (all repos, not just org top-5; drop `*@users.noreply.github.com`) — uses the 5000/hr token quota vs Search API's 10/min. **Profile fields:** read `.email`/`.blog`/`.company`/`.twitter_username` (already in memory, never read) → public `.email` = instant `known_email`. **Social-graph (gated):** from a confirmed `@domain` committer walk `/following` + `repo.get_contributors()`, admit only if `.company` matches or shares org/`@domain` email; cap fan-out ~30. *Net-new:* current module never touches events/profile/graph. **Effort: S (events+profile) → M (graph).**

### B3. MX-provider routing + M365 GetCredentialType HTTPS mailbox check + verified-sample lock — **PRIMARY (closes the no-real-verification gap)**
- **`domain.py`:** return + classify the MX host (`*.mail.protection.outlook.com`→microsoft, google MX→google, else other) — ~5 lines, unlocks the rest + provider-aware priors.
- **New `contacts/email/verify_m365.py::m365_confirms(email)->bool|None`:** for microsoft domains POST `login.microsoftonline.com/common/GetCredentialType`, read `IfExistsResult` (0=exists,1=no,5/6=federated→None); cross-check `outlook.office365.com/autodiscover/...` (200 vs 302); require both; cache per domain; back off on throttle.
- **Scoring:** add `mailbox_confirmed` to `EmailSignals`; a branch that **overrides the catch-all cap** to reach `verified` (queries identity, not SMTP). Wire into `_verify_email` routed by provider.
- **Verified-sample lock (multiplier):** in `infer.py`, a single *verified* `(name,email)` pair (B2 commit email or M365-confirmed) locks the company template (today needs `votes>=2`); mint others as `probable`, promote each via its own M365 check. *Net-new:* there is **no per-mailbox existence check** today. **Effort: M.**

### B4. (Secondary) Wayback CDX mailto-harvest into the email corpus
`harvest.py::harvest_wayback_emails(domain)` — Wayback CDX for the domain, fetch a capped set of snapshots, run existing `extract_emails` → recovers `(name,email)` pairs from removed/JS-ified pages (stale addresses still teach the format). **Effort: M, payoff: medium.**

### Explicitly NOT in B (settles tempting-but-doomed ideas)
- No generic recruiter-from-ATS for Greenhouse/Lever/Ashby — live-probed authenticated-only (null). Only SmartRecruiters `creator` is public.
- No remote port-25 verifier microservice — free tiers block 25; RCPT unreliable for Gmail/MS + RBL risk. B3 gives the same yes/no over HTTPS.
- No early-career alias work — already implemented.

---

## Phased rollout (each independently verifiable)
- **Phase 0 — Plumbing:** MX-provider classification, `OfficerLead` table stub, settings knobs. *Verify:* `classify_provider` unit test; `init_db` idempotent on fresh + pre-existing DB.
- **Phase 1 — Zero/low-cost highest-payoff:** A3 Wayback, A2 similar-company, B1 ATS/description mining, B2 GitHub events+profile. *Verify:* `fake_fetch_context` fixtures per channel → expected `Detection`/`DiscoveredPerson`; `discover-all` end-to-end adds boards.
- **Phase 2 — Temporal + verification:** A1 Form D (+OfficerLead), B3 M365 verifier + verified-sample lock + score override. *Verify:* canned EDGAR + GetCredentialType fixtures; `score_email(mailbox_confirmed=True, catch_all=True)` → `verified`; one verified pair locks template at `votes<2`.
- **Phase 3 — Secondary breadth (only if 1–2 land clean):** A4 Telegram, B4 Wayback emails. *Verify:* Telegram HTML → only board links (message never a job); Wayback emails improve inference on a held-out pair.

## Anti-slop safeguards
Discovery launders through `merge_boards` + the trusted poller (new channels emit only board URLs; the canonical job re-enters via the poller and passes `_annotate_quality`+`_record_sighting`). People launder through the existing `_dedupe→classify→infer→verify→score` funnel; social-graph/triangulation admitted only behind a same-company gate. LLM use stays behind regex/`@domain` prefilters + caps. `verified` is reserved for mailbox-confirmed/scraped-exact/real on-domain commit email; Gravatar/holehe stay `probable`.

## Deliberately NOT doing (honoring "nothing unnecessary")
Auto-fingerprint unknown ATS (favicon/Wappalyzer/MinHash — L effort, operator-in-loop; defer); coverage-gap dork generation (L, needs big corpus); Google Workspace mailbox enumeration (brittle); Sourcegraph/grep.app token mining (rate-limited); Product Hunt/blog-RSS/Discord (marginal vs A1–A3); conference/patent/Scholar people sources (low payoff).

## Open questions (need a decision before/within build)
1. **SmartRecruiters `creator`:** persist by merging into the existing JSON `raw` (no migration, surgical — recommended) or a typed `recruiter_name` column?
2. **M365 GetCredentialType** is a gray-area enumeration technique (Microsoft calls it "not a bug" but it probes their endpoint). OK to ship given strictly-personal $0 self-hosted use? If not, B3 degrades to provider-routing + priors only.
3. **Form D** unresolved companies (fuzzy name→site): silently drop unresolved filers (keep only their `OfficerLead` names) or surface for manual review?
4. **Telegram** seed channels: provide a starter list or leave empty by default (safer anti-slop)?
5. **YC corpus embedding** (~6k MiniLM passes, cached): OK to embed at first run, or cap to `isHiring`-only to bound cold-start?
