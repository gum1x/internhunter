# Deploying InternHunter as an always-on internship-landing system

This walks a fresh machine (home server, Raspberry Pi, cheap VPS) from zero to a system
that polls sources on a schedule, pushes Telegram alerts for new matching postings
within minutes, records every alert in the pipeline tracker, and flags warm-intro
opportunities from your network.

## 1. Install

```bash
git clone <your fork> internhunter && cd internhunter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ".[match]" for embedding fit scores (recommended)
internhunter init-db
```

## 2. Create the Telegram bot (one time, ~2 minutes)

1. In Telegram, message **@BotFather** → `/newbot` → pick a name → copy the token.
2. Send your new bot any message (bots can't DM you first).
3. Get your chat id: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser
   and read `"chat":{"id": ...}` from the reply. For a channel instead of a DM, add the
   bot as an admin and use the channel's `-100...` id.
4. Put both in the environment — never in a committed file:

```bash
cp .env.example .env
# edit .env:
#   INTERNHUNTER_TELEGRAM_BOT_TOKEN=123456:ABC...
#   INTERNHUNTER_TELEGRAM_CHAT_ID=123456789
```

Verify live before scheduling anything:

```bash
internhunter poll --ats ashby --board polymarket   # pull something real
internhunter notify --dry-run                      # see what would alert
internhunter notify --channel telegram             # should buzz your phone
```

## 3. Tune the two files that are yours to edit

- **`internhunter/config/targets.yaml`** — target firms, include/exclude keywords,
  locations, remote policy, funding stages. Adding a firm here makes its postings alert
  (and score-boosts nothing else — it's a filter, not a ranker). Edits apply on the next
  run; no restart needed.
- **`internhunter/config/connections.yaml`** — your network graph. Fill in real names
  and contacts; any posting at a firm listed here alerts as 🤝 *warm intro* with a draft
  ask you can copy (`internhunter tracker intro <id>`).

Also set `internhunter/config/profile.yaml` (skills/interests) and drop a `resume.pdf`
in the repo root if you want LLM deep-scoring to use it.

## 4. Run it on a schedule

The scheduler polls Tier-A boards every 30 min, runs the alert pass every
`INTERNHUNTER_NOTIFY_INTERVAL_MIN` (default 30 — a new posting alerts within
one poll + one notify cycle), discovery daily, and scoring every 6 h.

### Option A — systemd (recommended on a Linux box)

`/etc/systemd/system/internhunter.service`:

```ini
[Unit]
Description=InternHunter scheduler
After=network-online.target

[Service]
WorkingDirectory=/home/you/internhunter
ExecStart=/home/you/internhunter/.venv/bin/internhunter schedule
Restart=on-failure
User=you

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now internhunter
journalctl -u internhunter -f        # watch it work
```

### Option B — Docker

```bash
cp .env.example .env   # fill in the Telegram vars
docker compose up -d --build
```

### Option C — cron (if you'd rather not keep a process alive)

```cron
*/30 * * * *  cd /home/you/internhunter && .venv/bin/internhunter poll --ats greenhouse,lever,ashby >> poll.log 2>&1
*/30 * * * *  cd /home/you/internhunter && .venv/bin/internhunter notify >> notify.log 2>&1
0 3 * * *     cd /home/you/internhunter && .venv/bin/internhunter discover-all >> discover.log 2>&1
```

## 4b. Dossiers & outreach drafts

Fill in **`internhunter/config/pitch.yaml`** (your positioning, proof points, and
per-tag "why I fit" lines — drafts are assembled only from these claims plus verified
dossier facts), then:

```bash
internhunter dossier build            # researches every target firm; incremental
internhunter dossier list             # confidence + contact per firm
internhunter tracker draft <id>       # send-ready outreach for a tracked posting
```

The scheduler rebuilds stale/missing dossiers daily (`INTERNHUNTER_DOSSIER_*` vars),
including firms that entered the tracker but aren't in targets.yaml. Set
`{{proof_link}}` per message (or keep one canonical proof URL handy). To get *named*
contacts into dossiers, run the contacts pipeline first for the firms you care about:
`internhunter find-contacts --company <slug>` then
`internhunter dossier build --company <slug> --force`.

## 5. Working the pipeline

Every alerted posting lands in the tracker at stage **found** automatically. Advance it
as you go — nothing falls through the cracks:

```bash
internhunter tracker summary                   # counts per stage
internhunter tracker list --stage found -v     # what needs action
internhunter tracker intro 12                  # draft warm-intro ask for row 12
internhunter tracker set 12 referral-requested # found -> applied -> referral-requested
internhunter tracker set 12 interview          #   -> interview -> offer | rejected
internhunter tracker export --out pipeline.csv # one exportable view
internhunter serve                             # same tracker in the web dashboard
```

## 6. Startup-specific sources

On by default: YC company list (`discover --method yc`), Y Combinator **Work at a
Startup**, VC portfolio crawls (a16z, Sequoia, General Catalyst, Accel, Founders Fund,
Greylock, Bessemer, Index, Kleiner Perkins, First Round), HN *Who is hiring*, and the
Greenhouse frontier (catches brand-new startup boards within ~an hour). All feed the
same alert pipeline.

**Wellfound** is opt-in (`INTERNHUNTER_ENABLE_WELLFOUND=true` +
`INTERNHUNTER_WELLFOUND_COMPANIES=slug1,slug2`): Wellfound has no official feed, its
ToS restricts crawling, and a DataDome bot-wall usually blocks plain clients — the
ingestor only reads robots-allowed company job pages for slugs you list, and fails
soft. Don't rely on it; the channels above cover the same early-stage ground.

## 7. Troubleshooting

- **No alerts arriving** — `internhunter notify --dry-run` shows what the filter layer
  selects. 0 alerts usually means `targets.yaml` keywords are too narrow or nothing new
  was found in the last `NOTIFY_LOOKBACK_HOURS`. A jammed send shows an error line
  (`telegram ... HTTP 401` = bad token; `400` = bad chat id).
- **Too many alerts** — tighten `keywords.include`, add excludes, set
  `INTERNHUNTER_NOTIFY_REQUIRE_TARGET_MATCH=true`, or raise `NOTIFY_MIN_FIT`.
- **First run on an old database** — only postings first seen inside the lookback
  window alert, so you'll never get thousands of historical pings.
- **A send failed mid-run** — unaffected jobs still deliver; failed ones stay unmarked
  and retry on the next cycle. At most `NOTIFY_MAX_PER_RUN` alerts go out per cycle;
  the overflow is held, best-scored first.
