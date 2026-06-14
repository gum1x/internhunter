## InternHunter Multi-Channel Contacts — Buildable Plan

**Status:** BUILT (Phases 0–5) — ContactChannel table, free already-fetched channels (Gravatar/GitHub socials + resolved login), cross-channel corroboration scoring, union-find identity merge, npm/PyPI + social-dork harvesters, and the multi-channel dashboard/CSV. Deferred: C5/C6/C8/C9 (extra personal-email sources). 305 tests passing.


Goal: turn each contact from one guessed email into a **multi-channel contact card** (work email, personal email, LinkedIn, X/Twitter, GitHub, Mastodon, Bluesky, personal site) sourced from more methods, each at higher confidence, with cross-platform identity corroboration raising confidence. $0 / self-hosted / keyless, port 25 blocked, Python 3.12 / SQLite / FastAPI. **Phone is out of scope.**

All four reports converge on the same blocker and the same fix, so the design is settled: **a normalized `ContactChannel` child table is the storage model** (not a JSON blob), and **cross-platform corroboration raises email confidence by feeding two new fields into the existing `score_email`**. The rest is harvesters and surfacing.

---

### 1. Decisions & Constraints

- **Storage = new `ContactChannel` table (decided, not JSON).** Justification grounded in `core/db.py`: `init_db` (line 300-307) runs `_migrate` then `Base.metadata.create_all`, and `create_all` auto-creates brand-new tables (proven by `Sighting`/`OfficerLead`) — so a new table costs **zero migration code**. A JSON `channels` column on `contacts` would need a new `_ADDED_COLUMNS["contacts"]` entry (which today does not exist) AND a backfill, AND would be un-indexable for the channel-dedup query "have I seen this X handle at this company". A table gives per-channel `confidence`/`label`/`verified`/`source` as first-class columns — exactly the shape `score_email` already consumes per email.
- **Keep `Contact.email`/`email_status`/`email_source`/`confidence`/`label` as a denormalized "best work email" anchor.** Do not rip it out. It keeps `_find_existing_contact`, `_fetch_contacts`, templates, CSV, and `select_companies` working untouched. Populate it from the highest-confidence `kind='work_email'` channel. This is the surgical path (per CLAUDE.md): the channel table is purely additive.
- **Reuse, do not re-implement:** `score_email`/`EmailSignals` (per-email, reused per email-typed channel); `_name_matches` (runner.py:126-134, the only corroboration gate, reused per channel); `dedup_key()` (types.py:45-50, unchanged); `match/embed.py` `Encoder`+`cosine_matrix` (MiniLM, used today only by `semantic_dedup.py`) as a **tiebreaker only**; `upsert_officer_leads` (db.py:509-522) as the idempotent-upsert template.
- **Confirmed dead-ends (do NOT build, verified live in research):** Proton `/pks/lookup` returns valid keys for fake addresses (not an oracle); consumer Outlook/Hotmail `GetCredentialType` returns NotExist for real accounts; Gmail has no free HTTPS existence check. Personal-mailbox "verification" is **provenance-based only** (came from a real commit/maintainer record), plus holehe/Gravatar as corroboration.
- **Channel `kind` enum (fixed set):** `work_email, personal_email, linkedin, x, mastodon, bluesky, github, site`. No reddit/twitch/youtube/instagram/keybase as first-class kinds — store them in `evidence` if seen, but don't surface (low outreach value).

---

### 2. DATA-MODEL CHANGE (the precondition for everything)

**New table in `core/db.py`** (placed next to `Contact`, auto-created by `create_all`):

```python
class ContactChannel(Base):
    __tablename__ = "contact_channels"
    __table_args__ = (
        UniqueConstraint("contact_id", "kind", "value_norm",
                         name="uq_channel_contact_kind_value"),
        Index("ix_channel_kind_valuenorm", "kind", "value_norm"),
    )
    id:          Mapped[int]  = mapped_column(Integer, primary_key=True)
    contact_id:  Mapped[int]  = mapped_column(ForeignKey("contacts.id"), index=True)
    kind:        Mapped[str]  = mapped_column(String)   # enum above
    value:       Mapped[str]  = mapped_column(String)   # display form
    value_norm:  Mapped[str]  = mapped_column(String)   # lower, trailing-slash-stripped
    source:      Mapped[str | None] = mapped_column(String, nullable=True)
    status:      Mapped[str]  = mapped_column(String, default="guessed")
    confidence:  Mapped[float | None] = mapped_column(Float, nullable=True)
    label:       Mapped[str | None] = mapped_column(String, nullable=True)
    verified:    Mapped[bool] = mapped_column(Boolean, default=False)
    evidence:    Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at:  Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

**Migration notes:**
- New table ⇒ **no `_ADDED_COLUMNS` entry needed**; `create_all` makes it. Add a `tests/test_migration.py` case that opens a pre-change DB and asserts `contact_channels` appears (mirrors the existing `Sighting` assertion).
- **Latent bug to flag (do not fix unless asked):** `_ADDED_COLUMNS` has no `companies` entries for `is_catch_all`/`linkedin_url`/`github_org` — they exist only on freshly-created DBs. We avoid this trap entirely by using a new table instead of new `contacts` columns.

**`DiscoveredPerson` gets one new field** (`contacts/types.py`):
```python
channels: list[dict] = field(default_factory=list)   # {kind, value, source, confidence, status}
```
`dedup_key()` is unchanged (still linkedin→`gh:login`→`name:`), so dedup is unaffected. `_dedupe` (runner.py:46-54) is changed to **union the `channels` lists** (and keep merging `known_email`) instead of keeping only the first.

**New idempotent upsert** in `core/db.py`, modeled on `upsert_officer_leads`:
```python
def upsert_channels(session, contact_id: int, channels: list[ContactChannel]) -> int
```
keyed on `(contact_id, kind, value_norm)`; updates `confidence`/`label`/`verified`/`last_seen_at` if higher-confidence, inserts otherwise.

**Runner emission** (`_enrich_company`, runner.py:349-371): after building each `Contact`, write the best email to `Contact.email` (unchanged) and write **all remaining emails + social URLs** as `ContactChannel` rows. `upsert_contacts` must return the persisted `contact.id` so channels attach.

---

### 3. Workstream C — More CHANNELS / sources per person

Each item: net-new vs ALREADY-BUILT, channels added, confidence effect, effort. **Ordered by payoff.** Items below the cut line are dropped.

| # | Method (file) | Channels | Why net-new | Confidence effect | Effort |
|---|---|---|---|---|---|
| C1 | **Consume Gravatar `social_urls`** already fetched & discarded. `runner.py:191-196` reads only `.found`/`.display_name`; route `grav.social_urls` into channels, classify by host (x.com/twitter→x, github.com→github, mastodon→mastodon, bsky→bluesky, else→site), gate by `_name_matches`. **Also read `entry["verified_accounts"]`** (cryptographically owner-verified) in `verify_gravatar.py`, not just legacy `accounts`. | x, github, mastodon, bluesky, site | holehe only tests existence; this extracts+persists the handles, which are dropped today. `verified_accounts` is never read at all. | Arrives attached to a confirmed mailbox ⇒ identity-corroborated by construction; each channel high-confidence. | **S** |
| C2 | **GitHub `GET /users/{login}/social_accounts`** (keyless REST) in `people/github_people.py`. One call per discovered login → `[{provider,url}]`: twitter→x, mastodon, bluesky, linkedin, plus profile `blog`→site (blog is already in `raw`, currently dropped). | x, mastodon, bluesky, linkedin, site, github | ALREADY-BUILT mines GitHub for member/commit emails; it never reads social accounts. Single highest-yield keyless source. | Self-declared on the person's canonical GitHub identity ⇒ high base (~85-90); each is an independent corroboration edge. | **S/M** |
| C3 | **Capture resolved GitHub login from `github_confirms`.** runner.py:180 discards `_login`. Persist `login` as a `github` channel + `github.com/{login}` as a `site` channel when an email→commit→account match resolves. | github, site | ALREADY-BUILT runs the verifier but throws the login away. | email→commit→account is near-proof of identity; channel is verified and corroborates the person behind a guessed email. | **S** |
| C4 | **npm + PyPI maintainer-email harvester** — new `contacts/email/registries.py`. From a github_login's owned repos that are packages, `GET registry.npmjs.org/<pkg>` → `maintainers[].email`, `GET pypi.org/pypi/<pkg>/json` → `info.author_email`. Verified live: chalk→sindresorhus@gmail.com, requests→me@kennethreitz.org. Filter role accounts via `is_role_account`. | personal_email (sometimes 2nd work email) | ALREADY-BUILT mines commit emails only; registry maintainer emails are untouched and skew personal. | Self-published by maintainer = real+used; attribution hard via repo==person's repo. | **S** |
| C5 | **Capture ALL emails per github_login (drop @domain filter)** in `github_people._events_email` + commit loop, optionally via `/commit/<sha>.patch` `From:` header (no token, no Search-API quota). Classify work (@company) / work-alt (@sub.company) / personal (gmail/proton/own-domain). | personal_email, 2nd/alt work email | Current code filters to `@domain` and keeps only the first — discards the personal email that is the whole point. | Same login authored both ⇒ **hard same-person link** between work and personal email (strongest attribution). | **S** |
| C6 | **Self-hosted-forge commit miner** — new `contacts/email/forge_commits.py`. Mirror the GitHub miner against Gitea/Forgejo/Codeberg API `GET /api/v1/repos/<o>/<r>/commits` → `commit.author.email`, **unmasked** (no noreply). | personal_email, 2nd work email | ALREADY-BUILT is GitHub-only and @domain-filtered; these forges leak personal emails directly. | From real commits = confirmed-used by construction. | **M** |
| C7 | **Per-platform SearXNG dorks** in `people/searxng_people._DORKS`. Add templates: `site:x.com`/`site:twitter.com`, `site:bsky.app`, `site:github.com`, `site:about.me`, `site:linktr.ee`, mastodon patterns — reusing `_search_url` + `ctx.get_json` + `parse_result`. Emit `channels` on `DiscoveredPerson` keyed to the same `dedup_key`. | x, bluesky, github, mastodon, site | ALREADY-BUILT dorks target only linkedin.com/in/ + recruiter directories. | A public page containing person+company passes `_name_matches` ⇒ probable/verified, no login/ban risk. | **M** |
| C8 | **Personal-site / about.me / Linktree mailto+link follower** — new `contacts/email/personal_site.py`. From the GitHub `blog` / LinkedIn-linked site, fetch it + `/about` `/contact` `/links`, run `harvest.extract_emails` **without the domain filter**, parse `__NEXT_DATA__` (about.me/Linktree) for the full link set. | personal_email, x, site | `harvest_site_emails` is company-domain-only; this follows the PERSON's own site. | Reached via a link the person controls ⇒ chain-of-custody attribution. | **S/M** |
| C9 | **Bluesky keyless resolver** — new `contacts/email/resolve_bluesky.py`. `public.api.bsky.app`: `resolveHandle`→DID, `getProfile`→displayName, `searchActors`→candidates. A **custom-domain handle** (`alice.acmecorp.com`) self-proves company affiliation via DNS. | bluesky (+ company-affiliation edge) | No atproto code in repo. | Custom-domain handle = free self-proving corporate-affiliation cross-link. | **S** |

**Cut from Workstream C (low payoff):** Keybase lookup (frozen post-Zoom, near-zero recall — keep only as an optional corroboration probe, not a harvester), WebFinger/Mastodon resolver as a standalone (Mastodon handles arrive via C1/C2/C8 already; resolving is only needed to confirm), mailing-list From-header miner (heavy, narrow OSS-only audience), crates.io/ORCID pivots (long-tail), Maigret/WhatsMyName username fan-out (large dependency, mostly existence-only — reconsider only if recall is poor after C1-C9).

---

### 4. Workstream I — Cross-platform IDENTITY resolution + corroboration

Goal: fuse "one person reached N ways" into one record, and make agreeing channels **raise email confidence**.

- **I1 — Union-find dedup** (new `contacts/dedup.py`), replacing the dict-merge `_dedupe` and extending `_find_existing_contact`. Disjoint-set **scoped within `company_slug`** (bounds blast radius). **Strong edges that merge:** shared case-insensitive `github_login`; same normalized `linkedin_url`; exact `email`; identical *verified* channel `(kind, value_norm)` (e.g. same Bluesky DID). This transitively unifies a person found by LinkedIn in source A + GitHub in source B + email in source C — which the current first-key dict-merge cannot do. **Anti-merge guard:** name equality is NOT a strong identifier (two "John Smith"s); block any union when records carry *conflicting* non-null strong identifiers (different github_logins / different verified emails). Effort **M**.
- **I2 — MiniLM tiebreaker only.** Reuse `match/embed.py` `Encoder`+`cosine_matrix` (same primitives + same company-block scoping as `semantic_dedup.py`) **only** to adjudicate name-collision candidates that lack strong identifiers: high cosine (≥~0.9) on `"{name}. {title}"` raises confidence they're one person; low keeps them apart. Embeddings **never create a merge alone**. Effort **S** (wiring only).
- **I3 — Corroboration edges from declarative/crypto sources.** Gravatar `verified_accounts`, GitHub `social_accounts` self-declaration, Bluesky custom-domain handle, and bidirectional `rel=me` (only if C8 is built) are all high-trust edges; one-way `rel=me` is a candidate, not a confirmation. Each edge that passes `_name_matches` increments the person's corroboration count.

---

### 5. Workstream S — Scoring (per-channel + person-level)

Extends the existing verified/probable/guessed ladder; **does not replace `score_email`**.

- **S1 — Per-channel confidence.** Email channels: reuse `score_email`/`EmailSignals` verbatim. Non-email channels: a small rubric in `contacts/score.py` (`score_channel(kind, source, corroborators) -> (float, label)`), same labels:
  - `github` from a resolved login = 90 (canonical) → verified.
  - `x`/`mastodon`/`bluesky`/`linkedin`/`site` from GitHub `social_accounts` or Gravatar `verified_accounts` = 85 (self-declared on a confirmed anchor).
  - same from a blind SearXNG name-search = 50 → promote only on corroboration.
  - Bluesky DID resolving from the person's own/company domain = 95.
- **S2 — Cross-channel corroboration feeds back into the email score (the core "raises confidence" mechanism).** Add two fields to `EmailSignals`:
  ```python
  cross_channel_corroborated: bool = False
  corroborating_channels: int = 0
  ```
  In `score_email`, after the existing blocks:
  ```python
  if signals.cross_channel_corroborated:
      score += min(15.0, 5.0 * signals.corroborating_channels)
  ```
  This is the natural extension of the existing `identity_confirmed` bump (lines 65-66): a person confirmed on GitHub + site + Gravatar lifts their *inferred* work email from guessed → probable. Also **generalize `identity_confirmed`**: set it `True` whenever the person reaches ≥2 independent agreeing channels (today it's set only from a single Gravatar name-match at runner.py:196-198). An M365 mailbox-confirmed email then reaches the 88 "definitive" path when the person is independently corroborated.
- **S3 — Person-level `identity_confidence` (0-100), surfaced not averaged.** Ladder from independent name-consistent channels: 1 strong=40, 2=70, 3+=90, 3+ with a structurally-verified channel=95. Surface two numbers per card — `identity_confidence` (is this the right real person) and `best_reachability` (max channel confidence). Never average a verified email with three guessed handles into one mushy score.

---

### 6. Workstream UI — Dashboard + CSV multi-channel card

- **U1 — Channel chips.** `_fetch_contacts` (web/app.py:253-282) eager-loads `ContactChannel` (a `selectinload` or a second query keyed by `contact_id`). `_contacts_table.html` + `_job_contacts.html` render the person once with a row of channel chips: icon + `badge badge-{{label}}` (reuse existing CSS), colored by each channel's own confidence. Show an `identity_confidence` check when ≥70. **Quick win:** `github_login` is already on the row but never displayed.
- **U2 — Best-channel highlight.** `recommended_channel` = argmax over `confidence * kind_priority`, where kind-priority for cold internship outreach is `work_email > recruiting-alias > linkedin > personal_email > x/bluesky/mastodon > github/site` (the channel analog of the existing `ROLE_PRIORITY`). Bold it first in the card.
- **U3 — CSV.** Extend `contacts_export` (web/app.py:446-480): keep the existing 9 columns for backward compat; ADD `best_channel`, `best_channel_value`, `identity_confidence`, and one `GROUP_CONCAT` column per kind (`personal_email`, `x`, `bluesky`, `mastodon`, `github`, `site`). One row per person (users mail-merge per person). Reuse `_csv_safe`.
- **U4 — Filter.** Add `channel=` query param to `/contacts` ("has X", "has any social", "verified person only") via `Contact.id.in_(select(ContactChannel.contact_id).where(...))`.

---

### 7. Phased Rollout (each phase independently verifiable)

**Phase 0 — Data model (1 PR, blocks all).** `ContactChannel` table + `upsert_channels` + `DiscoveredPerson.channels` field + `_dedupe` union of channels. Verify: migration test asserts table appears on an old DB; unit test round-trips a contact with 3 channels through `upsert_channels` (idempotent: re-run inserts 0).

**Phase 1 — Free already-fetched channels (1 PR, highest ROI).** C1 (Gravatar social_urls + verified_accounts), C2 (GitHub social_accounts), C3 (resolved login). Verify: unit test feeds a fake Gravatar/GitHub response → asserts N channels persisted with correct kinds + identity gate; one live smoke test against a known org member.

**Phase 2 — Scoring + corroboration (1 PR).** S1/S2/S3 + I3 wiring. Verify: `test_score.py` — a person with 3 agreeing channels lifts an inferred email from guessed→probable; `identity_confirmed` fires on 2 channels; M365-confirmed + corroborated → verified.

**Phase 3 — Identity union-find (1 PR).** I1 + I2. Verify: `test_dedup.py` — person via LinkedIn(A)+GitHub(B)+email(C) collapses to one record; two "John Smith"s with conflicting logins stay separate; MiniLM only adjudicates the no-strong-id case.

**Phase 4 — New harvesters (2 PRs).** C4/C5 (registries + all-emails-per-login) then C6/C7/C8/C9 (forges, dorks, personal site, Bluesky). Verify per-source: a live fetch returns ≥1 channel and `is_role_account` filters role inboxes; personal emails carry `status` reflecting provenance-only verification.

**Phase 5 — UI + CSV (1 PR).** U1-U4. Verify: render snapshot shows chips + recommended channel bolded; CSV has new columns and one row per person; `channel=x` filter returns only X-bearing contacts.

---

### 8. Deliberately NOT doing (anti-over-engineering)

- **No JSON `channels` blob on `Contact`** — un-indexable for channel-dedup, needs an `_ADDED_COLUMNS` entry + backfill the table avoids.
- **No Proton `/pks` verify, no consumer-Outlook/Gmail direct verify** — confirmed non-functional in 2026; personal-mailbox confidence is provenance + holehe/Gravatar only.
- **No Keybase harvester, no Maigret/WhatsMyName/Sherlock username fan-out, no mailing-list miner, no crates.io/ORCID pivots** — low recall or large deps; revisit only if C1-C9 leave recall short.
- **No phone channel** — explicitly out of scope.
- **No reddit/twitch/youtube/instagram as first-class kinds** — low outreach value; stash in `evidence` if seen.
- **No `recordlinkage`/`dedupe` library** — a ~60-LOC union-find + the already-present MiniLM is the right size.
- **No removal of `Contact.email`** — it stays as the denormalized best-work-email anchor for backward compat.
- **No cross-company merging** in union-find — scope strictly within `company_slug`.