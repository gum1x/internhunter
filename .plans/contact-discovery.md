# InternHunter — Contact Discovery & Outreach-Prep Plan

> Add a **self-hosted contact-discovery subsystem**: for every company behind a discovered job, find the people worth reaching (recruiters, hiring managers, a few relevant engineers), find/infer their email addresses, score confidence, store them, and surface them in the dashboard with CSV export.

**Status:** PLAN ONLY — no code until approved.
**Target host:** the existing Linux box (home machine acting as VPS) + macOS dev. Python 3.12, async-first.
**License:** MIT (new code); note Reacher/AGPL is *out* — see §3.

---

## 0. Decisions locked in from clarification

| Topic | Decision |
|---|---|
| **Budget** | **Strictly $0, self-hosted only.** No third-party APIs, not even free tiers (no Apollo/Hunter/Clearbit). Pure scraping + pattern inference + (where possible) verification. |
| **Scope** | **Find + store + export only.** Discover, score, store contacts; show them in the dashboard; CSV export. No auto-drafting, no sending. You do outreach yourself. |
| **Targets** | **Recruiters + hiring team + a few ICs** — recruiters, university/talent recruiters, hiring/eng managers, plus a couple of relevant engineers per company. |
| **Risk appetite** | **Aggressive — max coverage.** LinkedIn scraping, proxy rotation, headless browsers all on the table. |
| This deliverable | This plan document only. |

---

## 1. Key environmental finding (decided by live test, not assumption)

The two biggest "is this even possible for free" questions were tested on the actual host:

1. **Outbound port 25 is BLOCKED.** Forcing IPv4, SMTP RCPT probes to `gmail-smtp-in.l.google.com`, `aspmx.l.google.com`, and `mx1.emailsrvr.com` **all time out**. → **Live SMTP/RCPT email verification will not work from this host**, and neither will the Reacher/`check-if-email-exists` Docker backend (it needs the same port 25). This is the single most important constraint on the design.
   - **Consequence:** verification leans on **HTTPS-based** signals instead — published/scraped emails, GitHub commit emails (self-reported = real), **holehe** (checks site registration over HTTPS), pattern-corpus consensus, and global priors. SMTP is built as an **optional, off-by-default module** that only activates if a port-25-capable host is ever added (cheap Oracle free-tier VPS, etc.).
2. **Residential IP is a genuine asset** for scraping LinkedIn/Google (datacenter IPs get flagged instantly) — so the people-discovery side leans into it, but the email-verification side cannot lean on port 25.

This resolves a direct disagreement between two research passes: the optimistic "residential IP means SMTP works" is **false here** — the ISP blocks 25 regardless.

---

## 2. Architecture overview

A new `internhunter/contacts/` subsystem, plugged in as a **post-discovery enrichment stage** that mirrors the existing `poll` / `score` command shape (DB-read → async work → DB-write).

```
companies behind jobs ──▶ [Stage 1: PEOPLE DISCOVERY] ──▶ raw people (name, title, source)
                              ├─ SearXNG LinkedIn dorking      (zero ban risk, reuses searxng.py)
                              ├─ GitHub org members + commits  (zero ban risk, yields real emails)
                              ├─ StaffSpy (burner LinkedIn)     (aggressive, account-burning, last resort)
                              └─ company team/leadership pages  (CloakBrowser render)
                                          │
                              [Stage 2: CLASSIFY + RANK] ──▶ role_category + priority (local LLM)
                                          │
                              [Stage 3: EMAIL FINDING] ──▶ best email + evidence
                                          ├─ scraped/published email (mailto, site)         [highest conf]
                                          ├─ GitHub commit email (real)                      [high conf]
                                          ├─ pattern inference from same-domain corpus       [medium]
                                          ├─ size-aware global prior                         [low]
                                          └─ recruiting aliases (careers@/jobs@/...)         [pragmatic win]
                                          │
                              [Stage 4: VERIFY] ──▶ holehe registration check (HTTPS)        [SMTP optional/off]
                                          │
                              [Stage 5: SCORE] ──▶ confidence 0–100 + label (verified/probable/guessed)
                                          │
                              [Stage 6: PERSIST] ──▶ contacts + companies tables  ──▶ dashboard + CSV
```

**Design rule:** every stage degrades gracefully. A company with no GitHub org and no SMTP still gets dorked recruiters + pattern-guessed emails + scraped `careers@`. Nothing in the pipeline hard-requires a single source.

---

## 3. Tooling decisions (what we integrate vs. build vs. skip)

Distilled from four research passes. Everything here is $0 / self-hostable.

| Need | Decision | Why |
|---|---|---|
| People: LinkedIn via search index | **SearXNG dorking** (reuse `discovery/searxng.py`) | Zero LinkedIn ban risk, reuses our infra + residential IP. **Do first.** |
| People: engineers + real emails | **GitHub** via `PyGithub` (org members) + `PyDriller`/commits API (author emails) | Zero ban risk, uniquely yields *real* corporate emails for free. **Do in parallel.** |
| People: precise recruiter list | **StaffSpy** (burner account, residential IP, `max_results≤25`) | Only maintained tool that filters staff by `search_term="recruiter"`. **Escalation only** — it burns accounts. |
| People: HR/leads, thin-presence startups | **Company team/leadership pages** via existing `CloakBrowser` + LLM extract | Public, low risk, good for execs/People-ops. |
| Email: domain-wide real samples | **theHarvester** (keyless sources: crtsh, certspotter, duckduckgo, bing) | Maintained; harvests real emails → pattern-inference fuel. |
| Email: permutation + patterns | **Write ~50 LOC ourselves** (vendor the 9–43 template set) | No maintained lib worth a dependency; logic is trivial. |
| Email: format inference | **Custom** — vote known (name,email) pairs against templates | This is the accuracy multiplier; same core logic Hunter uses. |
| Email: global priors | **Interseller size-aware frequency table** (hard-coded) | Large co → `{first}.{last}`, mid → `{f}{last}`, tiny → `{first}`. |
| Verify: registration signal | **holehe** (async module) | HTTPS-based, works despite port-25 block. Secondary signal. |
| Verify: SMTP/MX | **Optional module, OFF by default** | Port 25 blocked here (§1). Wire it, gate it, don't depend on it. |
| Verify engine: Reacher | **SKIP** | Needs port 25 (blocked) **and** is AGPL. Both disqualify. |
| Anti-detect browser | **Defer** `rebrowser-playwright`/Patchright swap | Our `CloakBrowser` is the swap point if direct LinkedIn renders get blocked. Not needed for v1 (dorking avoids it). |
| Proxies | **Add a single optional upstream-proxy setting**; skip free-proxy pools for v1 | Free proxy pools are mostly dead; residential IP + pacing beats them. Rotation can come later behind the same setting. |

---

## 4. Data model

Two new tables in `internhunter/core/db.py`, defined as `Base` subclasses. **No migration framework needed** — `init_db()` → `Base.metadata.create_all()` auto-creates new tables (it does *not* alter existing ones, so design columns up front). Mirror the `Score`/`Board` conventions (`Integer` PK, `_utcnow` defaults, `JSON` for dict/list, constraints in `__table_args__`).

```python
class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("company_slug", name="uq_companies_slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(String, index=True)   # join key to Job.company_slug
    name: Mapped[str | None]
    domain: Mapped[str | None] = mapped_column(String, index=True)
    email_pattern: Mapped[str | None]            # inferred template, e.g. "{first}.{last}"
    email_pattern_conf: Mapped[float | None]     # how sure we are of the pattern
    is_catch_all: Mapped[bool | None]            # null=unknown (can't test w/o SMTP)
    linkedin_url: Mapped[str | None]
    github_org: Mapped[str | None]
    headcount_band: Mapped[str | None]           # tiny|mid|large -> picks the prior
    enriched_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|done|failed
    notes: Mapped[dict] = mapped_column(JSON, default=dict)

class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("company_slug", "email", name="uq_contacts_company_email"),
        Index("ix_contacts_company_slug", "company_slug"),
        Index("ix_contacts_role_category", "role_category"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(String, index=True)
    company_domain: Mapped[str | None]
    full_name: Mapped[str | None]
    title: Mapped[str | None]                     # raw title as scraped
    role_category: Mapped[str | None]             # recruiter|university_recruiter|hiring_manager|eng_manager|ic_engineer|hr|other
    priority: Mapped[float | None]                # ranked outreach priority for this job/company
    linkedin_url: Mapped[str | None]
    github_login: Mapped[str | None]
    email: Mapped[str | None]
    email_status: Mapped[str] = mapped_column(String, default="guessed")  # scraped|github|guessed|holehe_confirmed|smtp_valid|invalid
    email_source: Mapped[str | None]              # how the email was obtained
    confidence: Mapped[float | None]              # 0–100 (see §6 rubric)
    label: Mapped[str | None]                     # verified|probable|guessed
    person_source: Mapped[str | None]             # searxng|github|staffspy|team_page
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # {sources, template, K, smtp_code, catch_all, holehe_sites}
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

**Join key:** `company_slug` (always non-null on every `Job`). `company_domain` denormalized onto `Contact` for the email stage. Add `upsert_contacts(session, contacts)` and `upsert_company(...)` modeled verbatim on the existing `upsert_jobs` (look up by `(company_slug, email)` / `(company_slug, linkedin_url)`, insert-or-update).

---

## 5. The pipeline, stage by stage

New package `internhunter/contacts/`:

```
contacts/
  runner.py          run_find_contacts(...) orchestrator (sync wrapper + async core), mirrors core/runner.py
  select.py          which companies to enrich (gate to notifiable / high-fit jobs first)
  people/
    searxng_people.py  dork queries + parse title/content -> (name, title, /in/url)
    github_people.py   PyGithub org members + commit-author emails
    staffspy_people.py thin wrapper, burner-cookie session, max_results cap
    team_pages.py      CloakBrowser render + LLM extract
  classify.py        local-LLM role classification + ranking (cache by title)
  email/
    permute.py        the 9–43 template set + name normalization (accents/hyphens)
    infer.py          vote known (name,email) pairs -> dominant template + K
    priors.py         Interseller size-aware frequency table
    harvest.py        theHarvester subprocess + JSON parse; site mailto regex; aliases
    verify_holehe.py  async holehe registration check (HTTPS)
    verify_smtp.py    OPTIONAL MX+RCPT+catch-all probe; OFF unless port-25 host set
  score.py           confidence rubric -> 0–100 + label
```

**Stage 0 — company selection (`select.py`).** Don't enrich all companies — gate to companies behind **notifiable / high-`discovery_score`** jobs first (reuse `notify/select.py` logic). `select(distinct Job.company_slug)` left-joined against `companies.status` to skip already-enriched. Respects `--company <slug>` and `--limit`.

**Stage 1 — people discovery.** Order = cheapest/safest first:
1. **SearXNG dorks** (reuse `discover_from_searxng` query loop; additionally read `result["title"]`/`result["content"]`, currently only `.url` is used). Dork set per company:
   ```
   site:linkedin.com/in ("recruiter" OR "talent acquisition") "{COMPANY}"
   site:linkedin.com/in ("university recruiter" OR "campus" OR "early careers") "{COMPANY}"
   site:linkedin.com/in ("hiring manager" OR "engineering manager") "{COMPANY}"
   site:linkedin.com/in ("software engineer" OR intern) "{COMPANY}"
   ```
   Parse `"First Last - Title at Company | LinkedIn"` → split on ` - ` / ` | ` / ` at `.
2. **GitHub** (`github_people.py`): resolve company GitHub org → `org.get_members()` + commit author emails (filter to `@domain`, drop `users.noreply.github.com`). Needs a **free GitHub PAT** (5000 req/hr vs 60) — flagged optional but strongly recommended; this is also the best free source of *real* engineer emails.
3. **StaffSpy** (`staffspy_people.py`): **escalation only**, when 1–2 underdeliver. Burner LinkedIn cookie in `session.pkl`, `scrape_staff(company, search_term="recruiter", max_results≤25)`, jittered pacing, hard-stop on Challenge/rate-limit.
4. **Team pages** (`team_pages.py`): `CloakBrowser.render()` company `/team` `/about` `/leadership` → LLM-extract name/title. Fallback for startups thin on LinkedIn/GitHub.

**Stage 2 — classify + rank (`classify.py`).** Reuse `llm/client.py` `complete(prompt, backend, cache=LlmCache, model=...)` + `extract_json`. Zero-shot map each raw title → `{recruiter, university_recruiter, technical_recruiter, hiring_manager, eng_manager, ic_engineer, hr, other}`, temp ~0.1, cache by title string. Rank for an internship: `university_recruiter` > `technical_recruiter` > `recruiter` ≈ HM/eng-manager of the matching team > senior IC on team. Requires wiring a **local-LLM backend** (the box runs llama.cpp) — see §7.

**Stage 3 — email finding (`email/`).** For each kept person, in confidence order:
1. **Scraped/published** match (from site mailto / theHarvester corpus) where localpart matches this person's normalized name → take it (highest confidence).
2. **GitHub commit email** for this person if we have their login.
3. **Pattern inference**: collect same-domain known emails (GitHub + theHarvester + site), vote against templates → dominant template (need ≥2 agreeing to "lock") → apply to normalized name.
4. **Global prior** if no corpus: size-aware (`headcount_band`) → `{first}.{last}` (large) / `{f}{last}` (mid) / `{first}` (tiny).
5. **Recruiting aliases** always also collected: scrape/guess `careers@ jobs@ recruiting@ talent@ university@ hr@` — legitimately the *intended* outreach target and often higher-deliverability than a guessed personal address.
   - **Name normalization** (load-bearing): NFD accent-strip via `unicodedata` **and** `unidecode` (generate both for German-style ü→u/ue); hyphen drop/keep/first-segment; strip apostrophes/spaces; lowercase.

**Stage 4 — verify (`email/verify_*.py`).**
- **holehe** (default ON): async check whether the candidate email is registered on real sites (LinkedIn/GitHub/Twitter). A hit upgrades confidence — works over HTTPS, immune to the port-25 block. Flaky sites; cache results.
- **SMTP** (default **OFF**, `verify_emails=false`): MX lookup + catch-all probe (random localpart) + RCPT. Only meaningful if a port-25-capable host is configured (`smtp_verify_host`). Built for completeness; not active on this box.

**Stage 5 — score (`score.py`).** Apply the §6 rubric → `confidence` + `label`.

**Stage 6 — persist.** `upsert_company` (pattern, catch-all, status) + `upsert_contacts`.

---

## 6. Confidence rubric (additive, cap 100, start 0)

| Signal | Points |
|---|---|
| Email **scraped/published** matching the person | **+70** |
| **GitHub commit email** (real, self-reported) | **+65** |
| Pattern inferred, **K≥3** same-domain emails agree | +45 |
| Pattern inferred, **K=2** agree | +30 |
| Pattern inferred, **K=1** | +15 |
| **Global prior only** (large-co `{first}.{last}`) | +10 |
| **holehe** finds the address registered on real sites | +20 |
| **SMTP 250** on non-catch-all domain (if SMTP ever enabled) | +25 |
| Domain is **catch-all** (random probe accepted) | −15, hard-cap total at 60, never "verified" |
| **SMTP 550** (mailbox rejected) | candidate → 0, try next permutation |
| Disposable / role-account where a *person* was expected | −10 |

**Labels:** **verified ≥85** · **probable 55–84** · **guessed <55** · **invalid = 0**.
Because SMTP is off here, the realistic top of the range on this host is: **scraped (70) / GitHub (65) + holehe (20) → 85–90 "verified"**, with most pattern-inferred personal emails landing **"probable"** and prior-only landing **"guessed."** That's honest and the dashboard should show the label + evidence so you know which to trust.

---

## 7. Infrastructure changes required (greenfield bits)

These don't exist yet and must be built:

1. **Local-LLM backend** (`llm/client.py`): today only Anthropic API or the `claude` CLI exist. Add a tiny `LocalBackend` implementing the `LlmBackend` Protocol (`generate(prompt, system, max_tokens)`) pointing at the box's **llama.cpp OpenAI-compatible server**; register it in `get_backend` keyed off `llm_backend == "local"` + new `llm_base_url`. ~15 LOC. (Used by Stage 2 classification and team-page extraction.)
2. **Proxy support** (optional, single upstream URL):
   - httpx: pass `proxy=settings.http_proxy` in `build_fetch_context` (`core/fetch.py`).
   - Playwright: thread proxy into `PlaywrightBrowser._new_context(proxy=...)` (`core/browser.py`). Per-context is the rotation-friendly spot.
   - v1 ships the setting but defaults empty (residential IP + pacing is the primary strategy).
3. **Robots bypass**: already supported — call `ctx.get_text(url, respect_robots=False)` exactly like `searxng.py` does. No change.
4. **GitHub PAT** plumbing: optional `github_token` setting for the 60→5000 req/hr bump.
5. **SMTP-verify host** plumbing (off by default), so the optional verifier can target a port-25-capable relay later.

---

## 8. CLI + scheduler integration

- **New command** `internhunter find-contacts` (`cli.py`): add subparser (mirror `discover`) with `--limit`, `--company <slug>`, `--methods searxng,github,staffspy,team`, `--verify/--no-verify`. Handler `_cmd_find_contacts` lazy-imports and `asyncio.run(run_find_contacts(...))` (it needs both a DB session and a `FetchContext`, like `poll`).
- **Orchestrator** `contacts/runner.py::run_find_contacts` — sync wrapper (`asyncio.run`) so APScheduler can call it, async core opens `build_fetch_context(settings.model_copy(update={"enable_browser": True}))` when StaffSpy/team-pages need the browser (same `model_copy` trick `poll`/`discover` use).
- **Scheduler** (`scheduler.py`): `scheduler.add_job(run_find_contacts, IntervalTrigger(hours=N), id="find-contacts")` after the poll tiers, so enrichment runs periodically on freshly-discovered companies.

---

## 9. Web dashboard (find + store + export)

Reuse the exact `/jobs` + `_table.html` + `export_csv` patterns in `web/app.py`:
- `GET /contacts` → full `contacts.html` page (filters: company, role_category, label, has-email).
- `GET /contacts/table` → HTMX fragment `_contacts_table.html` (target `#contacts`).
- `GET /contacts/export.csv` → CSV via the existing `_csv_safe` injection-guarded writer; columns `full_name,title,role_category,email,email_status,confidence,label,linkedin_url,company,job_url`.
- **Per-job contacts**: add an expand column in `_table.html` with `hx-get="/jobs/{{ job.job_uid }}/contacts"` → fragment running `select(Contact).where(Contact.company_slug == job.company_slug).order_by(Contact.priority.desc())`. Show name · title · role badge · email · **label/confidence badge** · LinkedIn link.
- Import `Contact, Company` from `core.db` alongside `Job, Score`. Dark-theme inline CSS + htmx@2, same as today.

---

## 10. Dependencies to add

```toml
[project.optional-dependencies]
contacts = [
  "dnspython",          # MX lookup (for optional SMTP verify + provider detection)
  "PyGithub",           # GitHub org members
  "pydriller",          # commit-author emails (or raw commits API + regex)
  "unidecode",          # name -> ascii localpart normalization
  "holehe",             # HTTPS registration-based verification signal
  # theHarvester invoked as a subprocess (pipx/standalone), not imported
  # staffspy installed in the 'aggressive' extra below (heavier, optional)
]
contacts-aggressive = [
  "staffspy",           # burner-account LinkedIn staff scraping
]
```
- **theHarvester**: install standalone (`pipx install theHarvester`) and shell out; keeps its heavy dep tree out of our venv.
- **Reacher / check-if-email-exists**: **not added** (port 25 + AGPL).
- Keep everything under optional extras so the core engine stays lean (matches the existing `match`/`browser`/`llm` extras pattern).

---

## 11. Phased rollout (each phase independently verifiable)

| Phase | Deliverable | Verify |
|---|---|---|
| **P1 — schema + plumbing** | `Company`/`Contact` tables, `upsert_*`, settings fields, empty `find-contacts` command | `init-db` creates tables; `find-contacts --limit 0` runs no-op; unit tests on upsert dedup |
| **P2 — people: zero-ban sources** | SearXNG dorking + GitHub people, dedupe | On 5 sample companies, ≥1 named recruiter or engineer each; `pytest` parses canned SearXNG/GitHub fixtures |
| **P3 — classify + rank** | local-LLM backend + role classification + ranking | Titles map to correct `role_category` on a labeled fixture set; cache hit on repeat |
| **P4 — email finding** | permute + normalize + infer + priors + aliases + theHarvester | Given known (domain, sample emails), inferred template matches reality; accent/hyphen names normalize correctly (unit tests) |
| **P5 — verify + score** | holehe signal + confidence rubric (+ SMTP module wired but OFF) | Scored contacts carry sensible labels; holehe upgrades a known-registered address; SMTP module unit-tested against a mock, stays off |
| **P6 — dashboard + export** | `/contacts` views, per-job expansion, CSV | Manual: dashboard lists contacts, per-job expand works, CSV opens clean (injection-safe) |
| **P7 — scheduler + StaffSpy** | periodic enrichment + StaffSpy escalation (aggressive extra) | Scheduled job enriches new companies; StaffSpy pulls a capped staff list on a burner account without tripping a ban in a short run |

Phases 1–6 carry **zero account-ban risk** (dorking + GitHub + public pages). StaffSpy/account-burning is deliberately last and isolated in its own extra so the system is fully useful without it.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Port 25 blocked → no SMTP verify** (confirmed) | Architecture already assumes this; holehe + scraped + GitHub + pattern carry confidence. SMTP is opt-in for a future relay host. |
| **SearXNG/Google CAPTCHA under load** | Multi-engine (Google+Bing+DDG+Brave), throttle + jitter, relax our own instance's `limiter.toml`, back off on challenge. |
| **LinkedIn account ban (StaffSpy)** | Burner account, residential IP, `max_results≤25`, jittered pacing, hard-stop on Challenge; isolated to the last phase + optional extra. |
| **Catch-all domains** | Can't confirm individual mailboxes (and can't even probe without port 25); cap confidence, never label "verified", prefer scraped aliases. |
| **Gmail/M365 MX lie** | Even with SMTP they're unreliable; don't architect around SMTP at all. |
| **Free proxies are dead** | Skip pools for v1; rely on residential IP + pacing; ship the single-proxy setting for future use. |
| **Holehe/theHarvester source rot** | They decay; keep them as *signals* not gates, cache results, fail soft. |
| **Legal/ToS + CAN-SPAM/GDPR for outreach** | We only *find + store + export*; sending is the user's manual action. Document that LinkedIn scraping violates LinkedIn ToS and that outreach must follow CAN-SPAM/GDPR (B2B, opt-out, accurate headers). |
| **CSV injection / PII at rest** | Reuse existing `_csv_safe`; note the SQLite now holds PII — consider gitignore + optional at-rest care. |

---

## 13. Realistic expectations

- **Engineers at companies with a public GitHub org:** ~70–85% get a real/high-confidence email (direct harvest + verified pattern).
- **Recruiters via dorking + pattern (no SMTP):** name+title reliably; email lands mostly **"probable"** (pattern-inferred) rather than "verified," since we can't RCPT-confirm from this host.
- **Catch-all / Gmail-backed company domains:** email is a best-guess, label **"guessed"** — still useful, clearly marked.
- **Recruiting aliases (`careers@`, `university@`):** often the best actual outreach target and frequently scrapeable at high confidence.
- **Blended:** expect a usable, clearly-labeled contact (personal or alias) for the **majority** of enriched companies, with honest confidence labels so you know which to trust — at **$0**, reusing infra (SearXNG, CloakBrowser, llama.cpp, residential IP) you already run.

---

## 14. Open decisions before build

1. **GitHub PAT** — OK to create a free personal access token for the 60→5000 req/hr bump? (Strongly recommended; it's free and the biggest single yield lever.)
2. **Burner LinkedIn account** — do you have / want to create a throwaway account for StaffSpy (Phase 7)? Not needed for Phases 1–6.
3. **Enrichment gating** — enrich **only companies behind notifiable/high-fit jobs** (recommended, cheaper) or **every** discovered company?
4. **llama.cpp endpoint** — confirm the local OpenAI-compatible URL/port so the `LocalBackend` can target it (the box runs `llama-server`; was on `:8770` before we stopped it — restart for classification).
```
