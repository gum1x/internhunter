# InternHunter Contact-Finding Upgrade — Build Plan

## North-star objective

Maximize the count of emails that legitimately carry the **`verified`** label (real per-mailbox confirmation), and feed that verifier with more people and more candidate emails. The single biggest lever is **closing the Google Workspace per-mailbox gap**: M365 is the only provider with a true RCPT-equivalent today, yet Google Workspace is the majority of our startup-skewed target population. Everything else is secondary to that.

---

## Decisions & constraints

- **Stack / ground truth (verified against the live repo):** Python 3.12, SQLite, FastAPI, dnspython, httpx. Orchestrator `internhunter/contacts/runner.py::_enrich_company` runs people -> corpus -> pattern-lock -> per-person find/verify -> score -> upsert. Scoring is a pure additive dataclass `score.EmailSignals` + `score_email` (labels: verified >=85, probable 55-84, guessed <55). `verify_m365.py::m365_resolve` is the resolve template every new verifier copies.
- **$0 / self-hosted / keyless** — no Hunter/Apollo/ZeroBounce/GHunt-paid. Burner identities (already accepted for StaffSpy burner LinkedIn and the M365 enumeration) are in-scope but must be opt-in flags, off by default, isolated.
- **Port 25 is blocked** — all verification is HTTPS/DNS. `verify_smtp.py` stays wired-but-off (`smtp_verify_host=""`).
- **Honesty rule (non-negotiable):** `verified` == a mailbox-keyed positive (M365 GetCredentialType, Google GAIA, holehe, Gravatar/Libravatar, or an observed git commit). Provider + pattern alone never yields `verified`.
- **Live DB confirmed:** all tables incl. `officer_leads` now exist (empty in snapshot). `companies` already has the columns `is_catch_all`, `linkedin_url`, `github_org`, `email_pattern`, `email_pattern_conf` — **defined but never written** today.
- **Confirmed bug to fix first (cheap, high yield):** `finder.py:84-89` — when `locked_template` is set, `votes` stays `0`, so a real one-email company lock scores as `pattern_votes=0` -> "guessed". This silently suppresses the whole "one verified email locks the company" feature.

---

## Workstream V — VERIFICATION (the priority: more emails reach `verified`)

### V0. Fix the locked-template scoring bug + provider-conditioned priors (S, do first)
- **Net-new:** `finder.py` discards the vote count for locked templates (latent bug, not a feature). Priors are size-only.
- **How it raises verified:** A `lock_from_verified` lock comes from a *real* on-domain email; passing `pattern_votes>=2` (or a new `template_locked: bool` worth +38) lifts every teammate to "probable" and puts the per-person verifier on the **right** address, so M365/Google hits land instead of probing a wrong localpart. Provider-conditioned priors (`{first}.{last}` for M365, `{first}` then `{f}{last}` for Google) raise first-try `m365_resolve`/`google_resolve` hit-rate.
- **Where:** `finder.py:84-101` (pass real votes / add signal); `score.py` EmailSignals (`template_locked` field + one branch); `priors.py::default_template` becomes a function of `(headcount_band, provider)`. Also replace `_headcount_band(target.job_count)` (internship-req count -> always "tiny") in `runner.py:113-122` with `github_org` member count or total job count.
- **Effort:** S.

### V1. Google Workspace per-mailbox verifier — `verify_google.py` (L, THE priority)
- **Net-new:** The build has **zero** Google coverage. Research confirms every keyless Google vector is dead in 2026 (`gxlu` -> 204 for all; signin/recovery -> BotGuard+reCAPTCHA; CalDAV free/busy unsupported). The **only** surviving mechanism is GHunt-style **authenticated** People-PA GAIA resolution: `POST people-pa.clients6.google.com/.../rpc` with a `just_gaia_id` template using burner Google session cookies (`__Secure-1PSID`/`__Secure-3PSID`) -> a 21-digit GAIA ID == the Google identity exists, for `@gmail.com` **and** Workspace custom domains. It also returns a profile display name (feeds identity triangulation, V4).
- **How it raises verified:** Gives the ~50%-of-targets Google population the same identity-level mailbox oracle M365 enjoys. Recruiters/HR on Google domains (no GitHub/Gravatar) currently top out at "guessed/probable"; this converts them to `verified`.
- **Where:** new `email/verify_google.py` exposing `google_confirms(email)->bool|None` and `google_resolve(name,domain)->str|None` mirroring `verify_m365.py` exactly. In `runner.py`: add a `provider=="google"` fast-path twin of the M365 block at `runner.py:289-309` (gated by new `settings.google_verify`, off by default), and a `provider=="google"` branch in `_verify_email`. Reuse the existing `mailbox_confirmed` signal + score override (no new score branch needed). Burner cookies stored in a session file like `staffspy_session`; fail-soft (return `None`) and cache per domain.
- **Effort:** L. **This is the single most important deliverable.**

### V2. De-cloak provider via SPF / Autodiscover so verifiers fire on gateway-fronted domains (M, high)
- **Net-new:** `classify_provider` keys **only** off the MX host (`domain.py:68-77`), so Mimecast (`*.mimecast.com`), Proofpoint (`*.pphosted.com`), Barracuda, Cisco/IronPort, and vanity MX all return `"other"` -> the M365 (and new Google) verifier is **skipped on domains it would work on**.
- **How it raises verified:** Each recovered gateway-fronted tenant becomes eligible for an identity-level `verified` instead of an indirect guess. Mimecast/Proofpoint front a large share of real M365/Google tenants.
- **Where:** extend `domain.py::classify_provider` — when MX is `other`/known-gateway, resolve the domain's SPF TXT (`include:spf.protection.outlook.com` -> microsoft; `include:_spf.google.com` -> google) and/or the `autodiscover.<domain>` CNAME (-> `autodiscover.outlook.com` = microsoft). One cached DNS lookup. Prefer the authoritative include; treat ambiguous multi-include as `unknown` (no false routing). Pure DNS, no account risk.
- **Effort:** M.

### V3. Expand the wired holehe module set (S, high ROI — do early)
- **Net-new:** `verify_holehe.py::_MODULES` wires only 5 of ~120 modules (github, twitter, instagram, spotify, pinterest — consumer/rotting). The integration already exists.
- **How it raises verified:** A holehe `exists==True` is an address-keyed registration confirmation = honest verified/probable signal. Adding work-relevant still-leaky sites (atlassian, gitlab, zoom, adobe, docker, zoho) crosses more professional emails over the confirmation threshold.
- **Where:** grow the `_MODULES` tuple only; keep the existing async short-circuit-on-first-hit. Prune rotted modules periodically (note: GitHub/GitLab/Slack now return generic reset responses — do not rely on them).
- **Effort:** S.

### V4. Identity triangulation: confirm the mailbox belongs to THIS person + verify scraped emails (M, medium)
- **Net-new:** No verifier cross-checks the returned profile **name** against the discovered person. Scraped emails are explicitly excluded from verification (`runner.py:129` early-returns on `email_status=="scraped"`).
- **How it raises verified:** When a verifier returns a profile name (new Google GAIA, Gravatar `displayName`, GitHub commit-search `login`->name), a conservative normalized-token match against `DiscoveredPerson.full_name` upgrades "this mailbox exists" to "this is the right person" — a strong bonus. Removing the scraped early-return lets published personal emails run through M365/Google/GitHub and reach `verified` instead of being capped at "probable".
- **Where:** add `identity_confirmed: bool` to `EmailSignals` + a `score.py` branch; populate from `_verify_email`. Delete the `result.email_status == "scraped"` guard at `runner.py:129`. Require a conservative fuzzy match (nicknames/maiden names) to avoid false-confirms.
- **Effort:** M.

### V5. Provider-based catch-all detection -> honest labeling (S, medium)
- **Net-new:** `is_catch_all` is a defined `companies` column that is **never written**; `find_email` is always called with `catch_all=False` (`runner.py:316`), so the entire catch-all branch of the rubric (`score.py:67`) is dead code.
- **How it sharpens verified:** Probe a guaranteed-fake localpart (`zz9q7r-nonexistent@domain`) through the active per-mailbox checker. If the fake "exists" -> set `is_catch_all=True`, persist, pass `catch_all=True` (cap labels honestly). If the fake is rejected -> domain confirmed non-catch-all, a single real hit is decisive. Also codify the explicit rule: if the ONLY positive signal is "MX resolves / pattern matches", cap at probable/guessed with a `catch_all_undetectable_no_smtp` flag — never `verified` off provider+pattern alone. Mailbox-keyed positives still override the cap (already in `score.py:58-61`).
- **Where:** pre-loop probe in `_enrich_company`; write `Company.is_catch_all`; pass into `find_email`; small labeling guard in `finder.py`. Note: M365 GetCredentialType reflects directory identity not SMTP routing, so validate the fake-probe interpretation per provider.
- **Effort:** S.

### V6 (deferred / optional). Microsoft Teams active-user upgrade, Libravatar, ProtonMail
- **Teams enum** (TeamsEnum/TeamsUserEnum) upgrades an M365 "AAD object exists" to "active Teams user" — stronger signal, but needs a burner M365 bearer/skype token; defer behind a flag. **Libravatar** is a ~20-line `verify_gravatar.py` twin (`seccdn.libravatar.org/avatar/<hash>?d=404`) — tiny adoption, near-zero false positives if `d=404` enforced; cheap to add when convenient. **ProtonMail** availability check covers Proton *public* domains only (not Business custom domains) — low professional value, defer.
- **Effort:** M / S / S respectively. All low-priority.

---

## Workstream F — find more candidate emails / corpus (feeds the verifier)

The ranking rule: a candidate only becomes `verified` if an oracle fires, so corpus sources that are **confirmed-by-construction** (came from a git commit / registration) rank highest, then sources that yield a NAME at an M365/Google domain.

### F1. GitHub `.patch` + REST `contributors?anon=1` full-history commit-email mining (M, HIGH — top F item)
- **Net-new:** `github_people.py` reads only `commit.author.email` on top-5 repos + 30 events/member. Untapped: append `.patch` to any commit/PR URL -> raw `From: Name <email>` headers en masse (not Search-API rate-limited); `GET /repos/{org}/{repo}/contributors?anon=1` -> whole-history committer set (non-anon logins for employees who hide org membership + anonymous `{name,email}` records = bulk `@domain` emails); `Co-authored-by:` trailer mining.
- **How it raises verified:** Every email came **from a commit** -> set `github_account_confirmed=True` **by construction** without spending a `github_confirms` search call (saves the 10/min budget). Any `@companydomain` hit **locks the format** via `lock_from_verified`, promoting name-only teammates to M365/Google-confirmable. This is the **only** confirmation path on Google-MX companies.
- **Where:** extend `people/github_people.py`; feed pairs into `harvest.py` corpus; in `runner._verify_email` mark patch/registry-sourced emails confirmed without the search call. Filter `users.noreply.github.com`. Cap pages; hard-cache per repo.
- **Effort:** M.

### F2. Package-registry author/maintainer emails (M, high — tech companies)
- **Net-new:** No registry source exists. Keyless JSON, all GitHub/Gravatar-confirmable: PyPI `pypi.org/pypi/{pkg}/json` (`author_email`/`maintainer_email`), npm `registry.npmjs.org/{pkg}` (`maintainers[]`/`_npmUser`), crates.io owners (GitHub logins), RubyGems owners, Maven POM `<developers>`.
- **How it raises verified:** Registration emails (real mailboxes); `@companydomain` ones lock the format; personal ones are Gravatar/holehe-confirmable. Maintainer handle -> repo -> org membership also discovers PEOPLE.
- **Where:** new harvester beside `email/harvest.py`; map company->packages via org repo manifests to avoid personal side-projects.
- **Effort:** M.

### F3. CODEOWNERS / .mailmap / manifest author harvest (M, high)
- **Net-new:** No source reads repo-internal ownership files. Raw-fetch `.github/CODEOWNERS`, `.mailmap`, `MAINTAINERS`, `AUTHORS` + manifests.
- **How it raises verified:** `.mailmap` is a canonical `Name <email>` table (verified-grade emails + identity keys); CODEOWNERS maps the actual lead ICs/eng-managers worth contacting (logins feed the existing bridge).
- **Where:** `people/github_people.py` + `harvest.py`.
- **Effort:** M.

### F4. Smarter format inference from fewer samples (S, high — pairs with V0)
- **Net-new:** `infer_pattern` force-picks one template; `permute.py` lacks particles/suffixes/middle-name/CJK ordering.
- **How it raises verified:** When votes split, keep **top-2 templates** and let `m365_confirms`/`google_confirms` disambiguate per-person -> converts ambiguous "probable" into "verified". Particle/suffix/middle-name variants fix M365/Google brute-force misses.
- **Where:** `email/infer.py` (top-2), `email/permute.py` (`name_part_variants` extensions).
- **Effort:** S.

### F5 (lower). Mailing-list From-headers, DNS SOA RNAME / RDAP seeds, Wayback mailto recovery
- OSS-heavy companies: `lore.kernel.org`/public-inbox `/raw`, `lists.apache.org` Ponymail JSON -> `From:` headers (confirmable, format-lock). DNS **SOA RNAME** decodes a hostmaster email in one existing dnspython lookup (mostly role accounts, but one lock cascades). Wayback CDX `{domain}/*` filtered to team/contact pages recovers scrubbed `mailto:`. All low-yield; build only if F1-F3 saturate.
- **Effort:** S-M each. Lower priority.

---

## Workstream P — more people (feeds the funnel)

The lens: a source is only as good as the **handle** it yields. Handle-yielding sources (commit email, GitHub login, package email, personal domain/Twitter) are verification-enabling; name-only sources become verifiable only via company pattern-lock or the M365/Google resolver.

### P1. Cross-source identity resolution + pattern-lock propagation (M, high)
- **Net-new:** `runner._dedupe` is exact-key only (`linkedin_url > gh:login > name:lower`) and never merges a name-only LinkedIn record with a login-bearing GitHub record, nor propagates a company's lock across sources.
- **How it raises verified:** Union-find over strong identifiers (email, github_login, linkedin_url, gravatar-hash, twitter/bluesky handle, personal domain); block by `normalized(last_name)+company` and fuzzy-merge with RapidFuzz, using the repo's **unused `semantic_dedup.py` MiniLM** embedding as tie-breaker (require >=2 corroborating signals — over-merge guard). Once ANY entity at a company yields a `verified` email, propagate the locked template to every name-only entity there and re-score. This is literally how "one verified email locks the company" should cascade.
- **Where:** new dedup/resolution layer in `runner.py`; reuse `semantic_dedup.py`.
- **Effort:** M.

### P2. Early-career recruiter targeting (S, high — most on-target contact)
- **Net-new:** One early-careers dork line + SmartRecruiters `creator` only.
- **How it raises verified:** Yields the NAMED university/campus recruiter whose `@company` email is M365/corpus-confirmable — the highest-value internship contact, not a generic alias.
- **Where:** widen the title lexicon (Campus/University/Early Talent/Early Careers/Emerging Talent/New Grad/Intern Program Manager) in `searxng_people.py` dorks + the LLM classifier; extend `ats_raw.py` regex beyond SmartRecruiters `creator` to Greenhouse `recruiter`/`coordinator`, Ashby, Lever hiring-team fields already in `Job.raw` (zero new HTTP); add `.edu`/MLH/Devpost sponsor-page dorks.
- **Effort:** S.

### P3. GitHub GraphQL batched member enrichment (M, high)
- **Net-new:** `github_people` is REST-only; never reads `socialAccounts`/`websiteUrl`/`twitterUsername`.
- **How it raises verified:** One GraphQL query/100 members returns `login,name,email,websiteUrl,twitterUsername,socialAccounts` — fewer requests AND surfaces personal-domain/Twitter handles that enable Gravatar/holehe/M365-on-personal-domain. Public `email` when present is direct.
- **Where:** `people/github_people.py` (GraphQL path; budget 5000 pts/hr).
- **Effort:** M.

### P4. Route untapped DB people through a verifier-first path (M, medium)
- **Net-new:** `OfficerLead`s (Form-D execs at tiny just-funded startups) and names mined from `Job.raw`/`description_text` go straight to pattern-guess (`ats_raw.py:84-92`).
- **How it raises verified:** Tiny clean tenants are exactly where M365/Google per-mailbox checks are most reliable and the exec == hiring manager. Run `m365_resolve`/`google_resolve` FIRST for these zero-email leads. Also broaden description mining (`mailto:`, "apply to X@", "reach out to <Name>", embedded `/in/` URLs).
- **Where:** `runner._discover_people` routing + `ats_raw.py` regex.
- **Effort:** M.

### P5 (lower). Sessionize/Sched/MLH speaker dorks, GitLab groups, Bluesky/Mastodon, Wellfound dork, Handshake employer pages
- Speaker/hackathon dorks (handles), GitLab public-member API mirror, keyless Bluesky/Mastodon company-affiliation search, Wellfound dork (the build has TheOrg/RocketReach/SignalHire but not Wellfound), and Handshake employer/career-fair recruiter extraction (uniquely available — user is a student). Mostly coverage/medium-low verifiability. Build opportunistically.
- **Effort:** S-M each.

---

## Phased rollout (each phase independently verifiable)

**Phase 0 — Correctness (S, days):** V0 (locked-template votes fix + provider priors + real headcount), F4 top-2 inference. *Verify:* unit test — a `lock_from_verified` company scores teammates as "probable" not "guessed"; provider-conditioned prior returns `{first}.{last}` for microsoft, `{first}` for google small-org; a vote-split company keeps 2 templates.

**Phase 1 — Google gap + provider de-cloak (L):** V1 `verify_google.py` (+ `google_verify` flag), V2 SPF/Autodiscover de-cloak, V3 holehe expansion. *Verify:* `google_confirms` returns True for a known-good Workspace address and None for a fake; a Mimecast-fronted M365 domain now classifies `microsoft`; holehe fires on an atlassian-registered address. End-to-end: count of `verified` contacts on a Google-MX fixture company goes from 0 to >0.

**Phase 2 — Identity + catch-all honesty (M):** V4 identity triangulation + scraped-email verification, V5 catch-all detection. *Verify:* a Gravatar/GAIA profile-name match adds `identity_confirmed`; a scraped email now reaches `verified`; `is_catch_all` is written; a fake-localpart "exists" caps labels.

**Phase 3 — Corpus expansion (M):** F1 `.patch`/`contributors?anon`, F2 package registries, F3 CODEOWNERS/.mailmap. *Verify:* a fixture org yields N new `(name,@domain)` pairs marked `github_account_confirmed` without a search call; a registry harvest produces author emails; the larger corpus raises the locked-template rate.

**Phase 4 — People + dedup (M):** P1 identity resolution + lock propagation, P2 recruiter targeting, P3 GraphQL, P4 verifier-first DB leads. *Verify:* a name-only LinkedIn record merges with a login-bearing GitHub record; a recruiter title surfaces a named early-career recruiter; lock propagation re-scores name-only teammates to "probable".

---

## Data-model notes

- **No new columns needed for V1/V2/V5** — `companies.is_catch_all`, `linkedin_url`, `github_org`, `email_pattern(_conf)` already exist; just start **writing** them (idempotent upsert). Begin populating `is_catch_all` (V5) and `email_pattern` (cache the lock across runs to seed `lock_from_verified`).
- **If new scalar columns are ever required:** add `(name, sql_type)` to `_ADDED_COLUMNS["companies"]` in `core/db.py:270-282` (idempotent `_migrate` ALTERs in place). For Job scalar fields also add to `_SCALAR_FIELDS`.
- **New tables auto-create** via `Base.metadata.create_all` — no migration entry needed (e.g. a future `person_identity` union-find table for P1, if persistence is wanted; in-memory is fine for v1).
- **New settings flags** (mirror `m365_verify`): `google_verify: bool = False` (off by default — burner identity), plus a session-file path for Google cookies like `staffspy_session`.
- **New EmailSignals fields:** `template_locked`, `identity_confirmed` — each one bool + one `if` branch in `score_email`. No reused field is repurposed.

---

## External port-25 microservice — VERDICT: DO NOT BUILD (keep wired-but-off)

Confirmed 2026 facts: every truly-free always-on tier blocks outbound 25 (Oracle Free won't exempt free accounts; fly.io/AWS/GCP/Azure/DigitalOcean all block). Only paid Hetzner (~€4/mo) has open 25 — which **breaks the strict $0 constraint** — and even then Gmail/Yahoo/M365 greylist/reject RCPT enumeration from fresh low-rep IPs, catch-all defeats RCPT regardless, and a new IP risks immediate Spamhaus PBL listing. The big providers we most want are **already better confirmed** via the HTTPS stack (M365, Google GAIA). The plumbing (`verify_smtp.py` + `INTERNHUNTER_SMTP_VERIFY_HOST`) already exists, so keeping the *option* costs nothing. Revisit only if true catch-all detection or long-tail self-hosted/cPanel domains with zero HTTPS identity signal ever become the measured bottleneck — then a single ~€4/mo Hetzner RCPT-prober behind an HTTPS endpoint, used sparingly as a last-resort tiebreaker, accepting it breaks $0.

---

## Deliberately NOT doing

- **Keyless Google enumeration** (`gxlu`, signin/recovery lookup, CalDAV free/busy) — all dead/captcha-walled in 2026. The authenticated GAIA path (V1) is the only viable Google check.
- **Generative avatar services** (UI-Avatars, avatarapi, logo+initials) — they render from initials regardless of mailbox existence -> a 200 is meaningless. False-positive trap.
- **OAuth/OIDC `prompt=none` silent-auth enumeration** — IdPs return `interaction_required`/`login_required` regardless of account existence; not a reliable arbitrary-email enumerator. Azure's reliable enumerator (GetCredentialType) is already built.
- **Hand-rolling new password-reset differentials for Slack/Notion/GitHub/GitLab** — they've moved to generic responses to kill enumeration. Just expand the existing holehe module set (V3).
- **GH Archive / BigQuery bulk commit dumps** — emails hashed since 2016-08-11 and BigQuery needs a Google account (borderline-$0). Use live `.patch`/REST (F1).
- **ProtonMail Business / iCloud / Fastmail / Zoho mailbox checks** — no clean keyless endpoint (Proton public-domain check is low-value; defer).
- **`recordlinkage`/`dedupe` heavy libraries** for P1 — a ~60-LOC union-find + RapidFuzz is the simpler fit.
- **Default external SMTP relay** — see verdict above.
