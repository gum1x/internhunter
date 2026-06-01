# InternHunter — Implementation Plan

> Open-source, self-hosted **internship discovery engine** that polls company ATS boards directly across **19 platforms in 3 tiers**, maintains a self-growing registry of boards, and surfaces rare/fresh internships nobody else finds.

**Status:** PLAN ONLY — no code until approved.
**Target host:** macOS (your env) + Linux via Docker. Python 3.12, async-first.
**License:** MIT.

---

## 0. Decisions locked in from clarification

| Topic | Decision |
|---|---|
| OS / runtime | macOS native + Docker (you're on darwin; the Windows/WSL2 question is moot). |
| Sectors | **Wide net** — software/dev, startups, VC, finance/fintech, marketing, general tech. `config/sectors.yaml` ships broad and editable; sector is a *filter/label*, never a hard gate. |
| Resume tailoring | **Deferred.** `resume/` module is scaffolded + interface-stubbed in Phase 6 but not implemented. Phase 6 ships LLM scoring + notifications + scheduler + docker + CI + README. |
| LLM backend | **Both, default headless.** `claude -p` headless by default; auto-switch to Anthropic API when `ANTHROPIC_API_KEY` is present. |
| This deliverable | This plan document only. |

**Still needs a yes/no before Phase 6:** is `claude login` done on this machine? (Not blocking Phases 1–5.)

---

## 1. Guiding principles

1. **Free + keyless first.** No paid APIs, no LinkedIn/Indeed. Optional free keys (USAJOBS, GitHub) clearly flagged and off by default.
2. **Feeds over rendering.** Tier A = JSON, zero browser. Tier B = httpx HTML, browser only on bot-block. Tier C = stealth browser. Target ≥85% of job volume browser-free.
3. **Polite by default.** Honor `robots.txt` + crawl-delay, per-host rate limits, exponential backoff on 429/403, on-disk HTTP cache, conditional requests (ETag/If-Modified-Since).
4. **Everything incremental + resumable.** Discovery checkpoints; polling diffs against last snapshot; nothing re-scored without a content change.
5. **Typed + tested.** Pydantic models everywhere, full type hints, every poller/parser tested against a saved sample payload (no live network in CI).
6. **Truthful by construction.** When resume tailoring lands, the builder can only reorder/reword real base-resume content; fabrication is blocked in code + validated.

---

## 2. Phased milestones

Each phase ends with a **demoable result** and a green test suite. Phases 1–5 require no LLM and no paid anything.

### Phase 1 — Foundation + first real jobs (the spine)
**Goal:** `internhunter poll` pulls live internships from Greenhouse/Lever/Ashby into SQLite and shows them in a dashboard.
- `core/models.py` — `NormalizedJob`, enums, pydantic settings.
- `core/db.py` — SQLAlchemy engine, session, schema, migrations (Alembic-lite or `create_all` + versioned migration dir).
- `core/fetch.py` — async httpx client: shared session, semaphore, retry/backoff, on-disk cache, robots/crawl-delay gate.
- `core/normalize.py` — helpers: location parsing, remote detection, salary parse, html→text, posted-date parse.
- `sources/base.py` — `Source` ABC + `BoardRef` + registry decorator.
- `sources/tier_a/{greenhouse,lever,ashby}.py` — 3 pollers.
- `registry/boards.jsonl` — ~150 hand-seeded known-good boards (startups/VC/tech) across the 3 ATSs.
- `core/internship_filter.py` — title/level classifier (regex + keywords).
- `web/app.py` — FastAPI + one HTMX page: sortable/filterable table, stat bar, CSV export.
- `cli.py` — `poll`, `serve`, `db init`, `registry stats`.
- Tests: poller parsers against saved fixtures; internship classifier; normalize helpers.
- **Verify:** `internhunter db init && internhunter poll --ats greenhouse,lever,ashby && internhunter serve` → live intern roles visible, sortable by freshness.

### Phase 2 — Rest of Tier A + the discovery engine (registry explodes)
**Goal:** registry grows itself from tens of thousands of boards with zero manual curation.
- `sources/tier_a/{workable,smartrecruiters,recruitee,personio}.py`.
- `discovery/base.py` — `Discoverer` ABC + `DiscoveredBoard`.
- `discovery/common_crawl.py` — query CC index (CDX API) per platform URL pattern; parse token/slug; checkpoint offsets; resumable.
- `discovery/sitemap_detect.py` + `discovery/ats_fingerprints.py` — given any `careers.*`/`jobs.*` domain → fetch robots/sitemap/page source → detect ATS via fingerprint → extract token. One `Detector` per ATS.
- `discovery/merge.py` — dedupe by `(ats, token)`, merge into registry + `boards` table, reliability bookkeeping, auto-retire on repeated 404.
- `cli.py` — `discover --method common_crawl|sitemap`, `detect <url>`.
- Tests: CC response parsing; each fingerprint detector + token extractor; merge/dedupe.
- **Verify:** `internhunter discover --method common_crawl --ats greenhouse --limit 500` adds hundreds of new boards; `detect https://careers.somecorp.com` prints `(ats, token)`.

### Phase 3 — Tier B pollers + dedup + internship intelligence
**Goal:** broaden coverage to public-page ATSs; collapse duplicate roles; sharpen intern detection.
- `sources/tier_b/{breezyhr,jazzhr,jobvite,bamboohr,rippling,dover,zohorecruit,gem}.py` (httpx-first; browser-fallback hook, browser itself lands Phase 5).
- `core/dedupe.py` — exact (URL hash) + fuzzy (`company_slug`, `title_norm`, `location_norm`) + slot for semantic near-dup (wired in Phase 4).
- Deadline extraction (regex over structured fields + JD text); "rolling" badge.
- Tests: each Tier B parser against fixtures; dedupe correctness; deadline regex.
- **Verify:** dual-posted roles collapse to one canonical row; deadlines render in dashboard.

### Phase 4 — Local matching + rarity/freshness + more discovery
**Goal:** rank every job by fit locally (no quota), score discovery/rarity, add two more free discoverers.
- `match/embed.py` — `sentence-transformers` (default `all-MiniLM-L6-v2`, CPU-ok), cached embeddings.
- `match/prefilter.py` — cosine rank profile↔JD across all jobs.
- `match/rarity.py` — freshness boost + rarity (small/rare boards up, multi-aggregator down) → **discovery score**.
- `core/dedupe.py` — enable semantic near-dup collapse via embeddings.
- `discovery/searxng.py` — self-hosted SearXNG metasearch (`site:applytojob.com intern` etc.).
- `discovery/hackernews.py` — HN "Who is Hiring" via Algolia API → company → resolve to board.
- `config/profile.yaml` — your skills/interests for the embedding profile.
- Tests: rarity/freshness scoring math; SearXNG + HN parsing against fixtures; semantic dedupe threshold.
- **Verify:** dashboard sortable by fit and by discovery score; SearXNG/HN add startup boards.

### Phase 5 — Tier C via stealth browser
**Goal:** cover enterprise/anti-bot ATSs.
- `core/browser.py` — `BrowserFactory`: one flag toggles plain Playwright ↔ CloakBrowser. (Install Playwright **system deps only**; CloakBrowser auto-downloads patched Chromium — do **not** `playwright install chromium`.)
- `sources/tier_c/{workday,icims,oracle_cloud,adp,ultipro,paylocity}.py` — probe XML/JSON endpoints first (iCIMS, UltiPro), browser fallback; Workday POSTs to `cxs` endpoint.
- Per-ATS slow/careful rate schedule.
- Tests: Workday cxs payload parse; iCIMS/UltiPro XML parse; fingerprint detectors for Tier C.
- **Verify:** `internhunter poll --ats workday --board <tenant/site>` returns intern roles via browser path.

### Phase 6 — LLM deep-scoring + notify + schedule + ship
**Goal:** top-K deep scoring, alerts, automation, and a 10k-star-quality repo.
- `llm/client.py` — headless `claude -p ... --output-format json` default; API path when key present; batching + on-disk cache by job hash.
- `llm/score.py` — top-K → 0–100 fit, matched/missing requirements, 1–2 line rationale; `scores` table.
- `resume/` — **stub only** (interfaces + ATS-format notes + truthfulness-guardrail contract), implementation deferred per your call.
- `notify/{discord,ntfy,email,feed}.py` — fire on new high-fit + deadline-approaching.
- `scheduler.py` — APScheduler per-ATS cadence (Tier A frequent, Tier C slow); "run now" CLI + endpoint.
- `docker-compose.yml` (app + SearXNG), `pyproject.toml` pinned, `.env.example`, GitHub Actions CI (ruff + mypy + pytest + registry validation), `.claude/skills/*`, README (thesis, 60-sec quickstart, coverage table, architecture diagram, contributing guide).
- **Verify:** `docker compose up` → scheduled discovery+polling, Discord ping on a new high-fit intern.

---

## 3. Repo layout (final target)

```
internhunter/
  config/        profile.yaml  sectors.yaml  settings.py  (resume.base.* deferred)
  registry/      boards.jsonl                 # committed, community-contributable
  discovery/     base.py  common_crawl.py  sitemap_detect.py  ats_fingerprints.py
                 searxng.py  hackernews.py  merge.py
  sources/
    base.py                                   # Source ABC, BoardRef, SOURCE_REGISTRY
    tier_a/      greenhouse.py lever.py ashby.py workable.py
                 smartrecruiters.py recruitee.py personio.py
    tier_b/      breezyhr.py jazzhr.py jobvite.py bamboohr.py
                 rippling.py dover.py zohorecruit.py gem.py
    tier_c/      workday.py icims.py oracle_cloud.py adp.py ultipro.py paylocity.py
  core/          models.py db.py fetch.py normalize.py dedupe.py
                 internship_filter.py browser.py
  match/         embed.py prefilter.py rarity.py
  llm/           client.py score.py            # tailor.py stubbed
  resume/        builder.py keywords.py gap_analysis.py   # stubs in Phase 6
  notify/        base.py discord.py ntfy.py email.py feed.py
  web/           app.py templates/ static/
  scheduler.py  cli.py
  .claude/skills/{add-ats,add-discoverer,contribute-boards,score-jobs,tailor-resume}/SKILL.md
  tests/         fixtures/  test_*.py
  migrations/    0001_init.py ...
  docker-compose.yml  pyproject.toml  .env.example  README.md  LICENSE
  .github/workflows/ci.yml
```

---

## 4. Core interfaces

### 4.1 `Source` (every poller implements this)

```python
# sources/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

class Tier(str, Enum):
    A = "A"   # keyless JSON
    B = "B"   # public HTML, light scrape
    C = "C"   # stealth browser

@dataclass(frozen=True)
class BoardRef:
    ats: str            # "greenhouse", "lever", ...
    token: str          # board token / company slug / tenant-site
    company: str | None = None
    extra: dict | None = None   # e.g. workday {dc, site}, smartrecruiters region

class Source(ABC):
    ats: str                      # canonical id, matches BoardRef.ats
    tier: Tier
    needs_browser: bool = False   # Tier C True; Tier B may flip on bot-block

    @abstractmethod
    def board_url(self, ref: BoardRef) -> str: ...
    """Human-facing board URL (for dashboard links)."""

    @abstractmethod
    async def fetch(self, ref: BoardRef, ctx: "FetchContext") -> AsyncIterator["RawPosting"]: ...
    """Yield raw postings for one board. Handles pagination internally."""

    @abstractmethod
    def normalize(self, raw: "RawPosting", ref: BoardRef) -> "NormalizedJob": ...
    """Map a raw posting to the normalized schema."""

    async def poll(self, ref: BoardRef, ctx: "FetchContext") -> list["NormalizedJob"]:
        """Default: fetch → normalize → return. Override only if needed."""
        return [self.normalize(r, ref) async for r in self.fetch(ref, ctx)]
```

`FetchContext` carries the shared httpx client (or browser factory), the cache, the rate-limiter, and a logger — injected so pollers are testable with a fake context against fixtures.

`SOURCE_REGISTRY: dict[str, Source]` is populated by a `@register_source` decorator so `cli`/scheduler resolve `ats → Source` dynamically. **This is the extension point the `add-ats` skill targets.**

### 4.2 `Discoverer` (every board-discovery method implements this)

```python
# discovery/base.py
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

@dataclass
class DiscoveredBoard:
    ats: str
    token: str
    company: str | None = None
    source_method: str = ""       # "common_crawl", "sitemap", "searxng", "hackernews"
    confidence: float = 1.0       # detectors below 1.0 get a verification poll
    extra: dict | None = None

class Discoverer(ABC):
    method: str
    supported_ats: list[str]      # which ATSs this method can find ("*" = any)

    @abstractmethod
    async def discover(self, ctx: "DiscoveryContext") -> AsyncIterator[DiscoveredBoard]: ...

    def checkpoint(self) -> dict: ...      # resumable state (e.g. CC offset)
    def restore(self, state: dict) -> None: ...
```

Discovered boards flow into `discovery/merge.py` → dedupe by `(ats, token)` → upsert into `boards` table + append to `registry/boards.jsonl`. Low-confidence finds get one verification poll before activation. **This is the extension point the `add-discoverer` skill targets.**

---

## 5. `NormalizedJob` schema (all fields)

```python
# core/models.py
class NormalizedJob(BaseModel):
    # identity / provenance
    job_uid: str            # stable hash: sha1(ats|token|source_job_id or canonical_url)
    ats: str
    board_token: str
    source_job_id: str | None
    canonical_url: HttpUrl  # public apply/JD URL
    url_hash: str           # sha1(canonical_url) — exact-dedupe key

    # company
    company: str | None
    company_slug: str       # normalized for fuzzy dedupe
    company_domain: str | None

    # role
    title: str
    title_normalized: str
    department: str | None
    employment_type: str | None          # full-time/intern/contract/co-op
    is_internship: bool
    internship_kind: str | None          # intern|co-op|summer-analyst|new-grad|apprentice|rotational
    level_tags: list[str]                # ["intern","summer","2026"]

    # location
    location_raw: str | None
    location_normalized: str | None
    country: str | None
    region: str | None                   # state/province
    city: str | None
    is_remote: bool
    remote_scope: str | None             # global|country|hybrid

    # content
    description_text: str                # html→text
    description_html: str | None
    requirements: list[str]              # extracted bullets (best-effort)

    # comp (when present)
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None            # year|month|hour

    # dates
    posted_at: datetime | None
    updated_at: datetime | None
    deadline_at: datetime | None
    is_rolling: bool                     # no deadline / "rolling basis"

    # discovery / scoring (filled by pipeline, not pollers)
    sectors: list[str]                   # labels from sectors.yaml
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen_elsewhere: int            # for rarity penalty
    rarity_score: float | None
    freshness_score: float | None
    discovery_score: float | None        # headline sort key
    embedding_id: int | None

    # raw
    raw: dict                            # original payload, for re-normalization
```

---

## 6. DB schema (SQLite + SQLAlchemy)

**`boards`** — the registry, mirrored from `boards.jsonl`
| col | type | notes |
|---|---|---|
| id | INTEGER PK | |
| ats | TEXT | |
| token | TEXT | |
| company | TEXT | |
| tier | TEXT | A/B/C |
| tags | JSON | sectors, source method |
| board_url | TEXT | |
| first_seen | DATETIME | |
| last_polled | DATETIME | |
| last_active | DATETIME | last poll that returned ≥1 job |
| total_jobs_seen | INTEGER | |
| consecutive_failures | INTEGER | retire threshold |
| reliability_score | REAL | 0–1, decays on failure |
| status | TEXT | active/retired/unverified |
| | | **UNIQUE(ats, token)** |

**`jobs`** — one row per canonical posting (full `NormalizedJob`)
- All scalar fields from §5 as columns; `requirements`/`level_tags`/`sectors`/`raw` as JSON.
- `board_id` FK → boards.id. Indexes: `url_hash` (unique), `(company_slug, title_normalized, location_normalized)`, `posted_at`, `deadline_at`, `is_internship`, `discovery_score`.

**`scores`** — LLM deep-scoring (Phase 6)
| col | type |
|---|---|
| id | INTEGER PK |
| job_uid | TEXT FK→jobs.job_uid |
| fit_score | INTEGER (0–100) |
| matched | JSON (requirements met) |
| missing | JSON (gaps) |
| rationale | TEXT |
| model | TEXT |
| scored_at | DATETIME |
| input_hash | TEXT (cache key) |
| | UNIQUE(job_uid, input_hash) |

**`applications`** — user pipeline tracking
| col | type |
|---|---|
| id | INTEGER PK |
| job_uid | TEXT FK |
| status | TEXT ∈ new/saved/applied/ignored/rejected/interview |
| resume_path | TEXT (null until tailoring) |
| notes | TEXT |
| updated_at | DATETIME |

**`discovery_runs`** — observability + resume
| col | type |
|---|---|
| id | INTEGER PK |
| method | TEXT |
| ats | TEXT |
| started_at / finished_at | DATETIME |
| boards_found / boards_new | INTEGER |
| checkpoint | JSON (resumable state) |
| status | TEXT (running/ok/failed) |

**`embeddings`** (Phase 4) — `id`, `job_uid`, `vector` (BLOB), `model`, `dim`.

---

## 7. ATS coverage table (platform → tier → endpoint → discovery pattern)

> Endpoints below are the build targets; each is **verified live during its phase** and pinned with a saved fixture. ⚠ = shakier, expect to confirm exact path at build.

### Tier A — keyless JSON
| Platform | Endpoint | Discovery URL pattern |
|---|---|---|
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `boards.greenhouse.io/{token}` |
| Lever | `GET api.lever.co/v0/postings/{token}?mode=json` | `jobs.lever.co/{token}` |
| Ashby | `GET api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | `jobs.ashbyhq.com/{token}` |
| Workable ⚠ | `GET apply.workable.com/api/v1/widget/accounts/{account}` or `{account}.workable.com/api/v3/jobs` | `{account}.workable.com/jobs` |
| SmartRecruiters | `GET api.smartrecruiters.com/v1/companies/{token}/postings` | `careers.smartrecruiters.com/{token}` |
| Recruitee | `GET {company}.recruitee.com/api/offers/` | `{company}.recruitee.com` |
| Personio | `GET {company}.jobs.personio.de/xml` (XML feed) | `{company}.jobs.personio.de` |

### Tier B — public HTML, httpx-first
| Platform | Endpoint / page | Discovery URL pattern |
|---|---|---|
| BreezyHR | `{company}.breezy.hr/json` (public position JSON) / `/p/` pages | `{company}.breezy.hr` |
| JazzHR | `{company}.applytojob.com/apply` (structured HTML) | `{company}.applytojob.com` |
| Jobvite | `jobs.jobvite.com/careers/{company}` (HTML) | `jobs.jobvite.com/careers/{company}` |
| BambooHR | `{company}.bamboohr.com/careers/list` (JSON) / `/jobs/` | `{company}.bamboohr.com/jobs` |
| Rippling ⚠ | `{company}.rippling-ats.com/jobs` or embed on `careers.*` | detect Rippling embed |
| Dover ⚠ | `app.dover.io/api/careers/{id}` + `jobs.dover.com/companies/{company}` | `jobs.dover.com/companies/{company}` |
| Zoho Recruit | `{company}.zohorecruit.com/jobs/Careers` (HTML) | `{company}.zohorecruit.com` |
| Gem ⚠ | detect `gem.com` embed on `careers.*` → parse underlying JSON feed | embed detection |

### Tier C — stealth browser (CloakBrowser)
| Platform | Endpoint / pattern | Discovery URL pattern |
|---|---|---|
| Workday | `POST {tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` body `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"intern"}` | `*.myworkdayjobs.com` |
| iCIMS ⚠ | probe XML feed first → `careers.icims.com/jobs/{clientId}/jobs` browser fallback | `careers.icims.com/jobs/{clientId}` |
| Oracle Cloud | `{tenant}.fa.oraclecloud.com/hcmUI/CandidateExperience/` (heavy JS) | `*.fa.oraclecloud.com` |
| ADP | `jobs.adp.com/company/{company}` (anti-bot) | `jobs.adp.com/company/{company}` |
| UltiPro/UKG ⚠ | probe `recruiting.ultipro.com/{short}/JobBoard/{id}/Jobs.xml` → browser fallback | `recruiting.ultipro.com/{short}` |
| Paylocity ⚠ | `{co}.paylocity.com/recruiting/jobs/` (GUID feed owned by company) | `*.paylocity.com/recruiting` |

---

## 8. Cross-cutting engineering

- **HTTP layer:** one `httpx.AsyncClient`, `asyncio.Semaphore` global + per-host; token-bucket honoring crawl-delay; retry w/ jittered backoff on 429/403/5xx; on-disk response cache (hishel or hand-rolled) with ETag/Last-Modified.
- **Incrementality:** per board, diff this poll's `url_hash` set vs last; only new/changed jobs upserted; `last_active` updated; stale jobs marked gone (not deleted).
- **Failure isolation:** one board's exception never aborts a run — logged, `consecutive_failures++`, board retired after N (config).
- **Logging:** loguru, structured, per-run id.
- **Config:** pydantic-settings; `.env` for secrets/keys; `config/*.yaml` for profile/sectors/settings.
- **Internship classifier:** regex + keyword list (`intern, internship, co-op, summer analyst, university program, campus, early career, new grad, apprentice, rotational`) → `is_internship`, `internship_kind`, `level_tags`. Tunable, tested.
- **Testing:** pytest + respx (mock httpx) + saved fixtures under `tests/fixtures/<ats>/`. CI never hits the network.

---

## 9. Claude Code skills (`.claude/skills/`)
`add-ats`, `add-discoverer`, `contribute-boards`, `score-jobs`, `tailor-resume` — each a `SKILL.md` describing the extension contract (Source/Discoverer interface, fixture requirement, registry validation), so the repo is contributor-friendly out of the box.

---

## 10. Open questions / risks

1. **`claude login` status** — confirm before Phase 6 (default LLM path). Non-blocking until then.
2. **Endpoint drift (the ⚠ rows)** — Workable, Gem, Dover, Rippling, iCIMS, UltiPro, Paylocity have the least-stable public surfaces. Plan allocates a verification step per poller; some Tier B/C may degrade to browser-only or get marked "best-effort."
3. **Common Crawl volume vs politeness** — CC index is free but huge; need sane per-platform `--limit` defaults and offset checkpointing so a discovery run is bounded and resumable. Default conservative.
4. **CloakBrowser dependency** — third-party, ~200MB patched Chromium auto-download, not in CI. Tier C tests run against saved payloads only; live browser paths are manual/local.
5. **Semantic dedupe threshold** — collapsing "same role across boards" risks merging distinct roles; start conservative (high cosine threshold), expose as config, keep both URLs on the canonical row.
6. **SearXNG in docker** — adds a service; ensure it works keyless and rate-limited; document the compose dependency.
7. **Scale claim (50k+ boards on one PC)** — SQLite is fine for this; polling 50k boards is a scheduling/throughput problem, not storage. Per-ATS cadence + incremental diffing keep a full sweep bounded; document realistic sweep times.
8. **Sector labeling** — you want a wide net; sectors are soft labels (keyword + embedding tags), never hard filters, so nothing gets dropped for being "off-sector."

---

## 11. What I need from you to proceed
- ✅ Sectors (wide net) — captured.
- ✅ Resume tailoring deferred — captured.
- ✅ LLM both/default-headless — captured.
- ⬜ **Approve this plan**, and tell me the **first build scope** (recommend: Phase 1 only → real jobs in the dashboard fastest, then review).
- ⬜ (Before Phase 6) confirm `claude login` is done.
```
