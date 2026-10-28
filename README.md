# Hearth

**A taste-aware care coordinator for older adults.** Not a chatbot: a web app for staff and families, and an MCP tool any agent can call.

Care homes and families plan meals, music sessions, film nights and outings for
people whose tastes are easy to guess wrong. Hearth builds each resident's plan
from [Qloo](https://qloo.com)'s taste graph, checks every pick against that
person's confirmed favourites, and shows the evidence. Care needs (soft food,
step-free access, mild films...) are handled by Hearth's own rules, labelled
**"Hearth rule, not Qloo"**, because a taste graph does not know them.

## The web app

Hearth is used through a web app, not a chat box. Open it and choose
**Explore a sample care home** (Maple House: four residents with different
tastes and care needs, resolved live from Qloo by name) or **Set up your own**
(name, favourites picked from Qloo photo cards, care needs as toggles).

| Screen | What it does |
| --- | --- |
| Residents | A shelf of taste cards: photos of each resident's favourites, the genres they share, care-need badges. A three-step tour on first visit to the sample home. |
| Resident | Taste card, care needs, what they enjoyed / didn't, and this week at a glance. |
| Weekly plan | Seven-day board: two lunch themes, a music session, film night and an outing. Each pick has a verdict stamp, evidence on tap ("Qloo links this most to ...", shared genre tags, Hearth care rules), **Swap**, and **Enjoyed / Didn't enjoy** (feeds `/feedback` and re-plans). Prints as three A4 sheets: schedule, menu card, playlist. |
| Group activity | Choose residents and an activity; get the best shared pick, a fit row per person, an alternative for anyone left out, and the options set aside by care rules. |
| Taste check | Paste any list (from staff, family or an AI). Each idea gets Good / Weak / Poor fit, Can't verify, or Confirm which one, with evidence and a better swap. A "Without Qloo vs with Qloo" panel is marked coming soon (no LLM chosen yet). |
| Privacy | What is stored and what isn't; remove a resident or erase the whole home. |

Every value shown is labelled by source: **Qloo taste** or **Hearth care rule**.
Each browser keeps its own care home (a random id in localStorage, sent as
`X-Hearth-Home`); there are no accounts.

### Build and run (one process)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cd web && npm ci && npm run build && cd ..   # writes web/dist (gitignored)
HEARTH_MOCK=1 uvicorn hearth.api:app         # http://127.0.0.1:8000  (offline, invented data)
QLOO_API_KEY=... uvicorn hearth.api:app      # live Qloo
```

FastAPI serves the built app at `/` and the JSON API under `/api`
(`/docs` for OpenAPI). For frontend work run `npm run dev` in `web/` (Vite on
:5173, proxying `/api` to :8000).

`scripts/screenshots.py BASE_URL OUT_DIR` walks every screen with Playwright
(output is gitignored).

## Use Hearth from any agent (MCP)

Hearth is also an agent tool. The API serves a [Model Context Protocol](https://modelcontextprotocol.io)
server at **`POST /mcp`** (Streamable HTTP, stateless, no auth, rate limited like the API), so Claude,
Cursor, an OpenAI Agents SDK app or a care provider's own assistant can check its ideas before it
recommends anything to an older person.

```json
{ "mcpServers": { "hearth": { "url": "https://hearth.158-180-57-167.sslip.io/mcp" } } }
```

| Tool | What the agent gets |
| --- | --- |
| `check_picks` | The person's favourites (by name) + needs + the agent's ideas -> a verdict per idea (good / weak / poor, `cannot_verify`, `ambiguous`), Qloo evidence, care-rule results and a better swap. |
| `plan_week` | Favourites + needs (+ town) -> the weekly plan with evidence. |
| `group_pick` | Several people -> the best shared film / artist / outing, fit per person, alternatives, exclusions. |
| `find_entity` | Resolve a name to a Qloo entity (or say it can't). |

The agent describes people by favourite names; Hearth resolves them on Qloo, and nothing sent to
`/mcp` is stored. Without Qloo every tool fails: there is no taste to measure against.

Quick check from a shell:

```bash
curl -s https://hearth.158-180-57-167.sslip.io/mcp -H 'content-type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_picks","arguments":{
  "favourites":[{"name":"Frank Sinatra","domain":"artist"},{"name":"Casablanca","domain":"movie"}],
  "needs":["mild_content"],
  "candidates":[{"name":"Roman Holiday","domain":"movie"},{"name":"Fast & Furious 9","domain":"movie"}]}}}'
```

## What it does

| Job | How |
| --- | --- |
| **Taste checker** (`POST /api/verify`) | Any list of picks (from staff, family, or an LLM) in -> each resolved to a Qloo entity (ambiguous names come back for confirmation; no match = `cannot_verify`), scored for fit, verdict `good` / `weak` / `poor`, evidence (Qloo affinity, shared tags), and a better-fitting swap that also passes the person's care rules. |
| **Weekly plan** (`GET /api/residents/{id}/plan`) | Two meal themes (cuisine signal from Qloo, dishes from Hearth's menu library filtered by diet/texture), a music session, a film night, and an outing. Deterministic. |
| **Group pick** (`POST /api/group-pick`) | One film/outing for several residents, maximising fit across them. Names who is left out and gives each an alternative. Options that fail anyone's care rule are excluded and reported. |
| **Film & TV era** (`PUT /api/residents/{id}/era`) | Qloo's film picks lean modern (Annie Hall for a 1940s-50s fan). Each resident has an era: by default the newest favourite film/TV release year + 10, or a year staff set, or no limit (setup and resident screens). Film/TV picks, swaps and group suggestions come from Qloo insights with `filter.release_year.max`; residents with *Gentle films* also get `filter.content_rating=G,PG,GP,TV-G,TV-PG,TV-Y,TV-Y7,Approved,Passed`. Verdicts are still measured against the unfiltered best, so calibrated thresholds hold. Evidence says **"Era: Hearth setting"**; a checked title released after the era is flagged and gets an in-era swap. |
| **Feedback** (`POST /api/feedback`) | Staff mark *enjoyed* / *didn't*; weights change which favourites are sent to Qloo as signals, and disliked items are never suggested again. |

### How a verdict is made

1. `/search` resolves the name within the requested entity type.
   Several exact-name matches resolve to the far better-known one when it leads
   by >= 0.30 popularity (many titles have zero-popularity duplicates);
   otherwise they come back for confirmation.
2. `/v2/insights` with the profile's confirmed entity IDs/tags as signals and
   `filter.results.entities=<all candidates in that domain>` gives each
   candidate's affinity in **one call per domain**, with
   `feature.explainability=true` showing which favourite drives each score.
3. The same signals without that filter give the best Qloo can offer this
   person in that domain (for places, within `place_location`).
   **Relative fit = candidate / best.**
4. Verdicts (Hearth thresholds, calibrated against the live API with four
   older-adult personas, Oct 2026):

   | Type | good | weak | absolute floors | status |
   | --- | --- | --- | --- | --- |
   | artist, movie | rel >= 0.94 and affinity >= 0.85 | rel >= 0.84 | affinity < 0.78 is always poor | calibrated |
   | place | rel >= 0.95 | rel >= 0.90 | none | provisional |
   | other types | rel >= 0.94 | rel >= 0.84 | none | uncalibrated (flagged in evidence) |

   A pick that is already a confirmed favourite is `good` without scoring
   (Qloo never returns signal entities as results).
5. Swap = the highest-ranked live Qloo entity above the candidate that passes
   the person's care rules, with the reason (the favourite Qloo links it to,
   shared tags).

## Run it (mock mode, no key needed)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
HEARTH_MOCK=1 uvicorn hearth.api:app --reload   # http://127.0.0.1:8000/docs (API under /api)
pytest -q
```

Mock mode serves Qloo-shaped responses from `hearth/qloo/fixtures/synthetic_catalog.json`.
**Everything in it is invented** (names, IDs, addresses, numbers). The mock
affinity is a toy tag-overlap formula, not a model of Qloo.

### Try it

```bash
# 1. look up a favourite so staff can confirm the right entity
curl "localhost:8000/api/resolve?name=The%20Marlow%20Sisters&domain=artist"

# 2. create a resident from confirmed IDs + needs
curl -X POST localhost:8000/api/residents -H 'content-type: application/json' -d '{
  "name": "Ada",
  "entities": [{"id": "mock-artist-001", "name": "The Marlow Sisters", "type": "artist"}],
  "needs": ["soft_food", "mild_content", "wheelchair_access"]}'

# 3. check some picks
curl -X POST localhost:8000/api/verify -H 'content-type: application/json' -d '{
  "resident_id": "<id>",
  "candidates": [{"name": "Dancing on the Pier", "domain": "movie"},
                 {"name": "Midnight in the Cellar", "domain": "movie"},
                 {"name": "Harbour Lights", "domain": "movie"}]}'
```

### Live smoke test

```bash
QLOO_API_KEY=... python scripts/live_smoke.py        # 4 personas, verdict table
python scripts/live_smoke.py --persona swing --no-place
```

Personas are names only; everything is resolved live and cached privately
under `.cache/qloo` (gitignored). About 80 calls on a cold cache, 0 when warm.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `QLOO_API_KEY` | none | Hackathon key, sent as `X-Api-Key`. Required unless mock. |
| `QLOO_BASE_URL` | `https://hackathon.api.qloo.com` | Hackathon keys do not work on `api.qloo.com`. |
| `HEARTH_MOCK` | off | `1` = offline synthetic fixtures. |
| `HEARTH_CACHE_DIR` | `.cache/qloo` | Private response cache (gitignored). |
| `HEARTH_DB` | `hearth.db` | SQLite file (gitignored). |
| `HEARTH_WEB_DIST` | `web/dist` | Built web app served at `/`. |
| `HEARTH_RATE_LIMIT` | `1` | `0` turns the per-IP limits off. |
| `HEARTH_RATE_QLOO` | `30/60` | Requests per seconds, per IP, for routes that may call Qloo (search, resolve, verify, plan, group pick, demo, resident reads). |
| `HEARTH_RATE_CREATE` | `20/3600` | Creating residents / seeding the sample home, per IP. |
| `HEARTH_RATE_API` | `240/60` | Everything else under `/api` (`/api/health` is never limited). |
| `HEARTH_MAX_RESIDENTS_PER_HOME` | `12` | Cap per care home (409 beyond it). |

## Layout

```
hearth/
  qloo/client.py     async GET-only client: /search, /v2/tags, /v2/insights, /v2/analysis/compare
  qloo/params.py     per-filter.type allowed-parameter table (API silently ignores bad params)
  qloo/cache.py      private on-disk cache
  qloo/mock.py       offline stand-in + synthetic fixtures
  verifier/          the taste checker (pure helpers + async steps)
  constraints/       care rules - "Hearth rule, not Qloo"
  planner/           weekly plan + group pick
  era.py             film/TV era + gentle-rating filters for ranked lists ("Era: Hearth setting")
  ratelimit.py       per-IP limits for the public demo
  feedback.py        enjoyed/didn't -> profile weights
  storage.py         SQLite
  api.py             FastAPI routes (/api) + serves web/dist at /
  demo.py            sample home "Maple House" (names only; resolved live at seed time)
  llm.py             LLM provider Protocol (no provider wired)
  data/dishes.json   Hearth's starter menu library
web/                 Vite + React + TypeScript app (plain CSS; fonts self-hosted via @fontsource)
deploy/              VM install (systemd + Caddy), update and health-check scripts
```

### Other API routes used by the app

`GET/PUT/DELETE /api/home` (this browser's home name, town, erase),
`POST /api/demo` (seed Maple House), `GET /api/search` (photo cards for setup),
`GET /api/residents`, `DELETE /api/residents/{id}`, `GET /api/residents/{id}/history`,
`GET /api/residents/{id}/plan?skip=<entity id>&skip_cuisine=<key>` (swaps),
`PUT /api/residents/{id}/era` (`{"era_mode": "auto" | "year" | "off", "era_max_year": 1965}`),
`GET /api/health` (process + database; no Qloo call).

## Deploy on a VM

Target: an Oracle Cloud Always Free Ampere A1 VM (ARM64, 1 OCPU / 6 GB) running Ubuntu
22.04 or 24.04, alongside other services. No Docker. Hearth runs as your user under systemd
(uvicorn on `127.0.0.1:8088`, 2 workers, 1 GB memory cap) behind Caddy, which gets the HTTPS
certificate by itself.

```bash
git clone <this repo> ~/hearth && cd ~/hearth
./deploy/install.sh                       # asks for your Qloo key (hidden); safe to re-run
# optional: HEARTH_DOMAIN=hearth.example.com ./deploy/install.sh
```

`install.sh` installs Python 3.11+ and Node (NodeSource) if missing, builds `web/`, creates `.venv`,
writes `/etc/hearth.env` (mode 640; template in `deploy/hearth.env.example`), installs
`/etc/systemd/system/hearth.service`, installs Caddy from its official apt repo, and writes
`/etc/caddy/Caddyfile.d/hearth.caddy`. Your existing `/etc/caddy/Caddyfile` is kept: an
`import /etc/caddy/Caddyfile.d/*.caddy` line is appended (a backup is saved first; only Caddy's
untouched placeholder is replaced). The hostname is `$HEARTH_DOMAIN` or
`hearth.<public-ip-with-dashes>.sslip.io`. It opens TCP 80/443 in iptables (Oracle's Ubuntu images
reject them by default) and saves the rules with `netfilter-persistent`; with ufw active it adds
ufw rules instead.

**Then open the ports in Oracle Cloud too.** In the console: Networking > Virtual cloud networks >
your VCN > Security Lists > Default Security List > Add Ingress Rules: source `0.0.0.0/0`, TCP,
destination port `80`; and the same for `443` (or on the NSG attached to the VM). Then:

```bash
./deploy/check.sh          # app on 127.0.0.1:8088/api/health, then https://<host>/api/health
./deploy/update.sh         # later: git pull, rebuild, restart, check
sudo systemctl status hearth ; journalctl -u hearth -f
```

Public-demo protection is on by default: per-IP limits (`HEARTH_RATE_*`, counted per worker, so the
ceiling is up to 2x with 2 workers) and at most 12 residents per care home. The database and Qloo
cache live in `/var/lib/hearth`, outside the repo.

## Data and privacy

- Per resident Hearth stores a display name, care needs, confirmed Qloo
  entity/tag IDs (with each favourite film's release year, for the era), the era setting and
  feedback weights. No dates of birth, rooms, medical
  records or free-text notes. `DELETE /api/residents/{id}` removes a resident
  and all their rows.
- Favourite photos are Qloo image URLs looked up at request time and held in
  memory only; they are never written to the database or the repository.
- Qloo responses are cached privately and **never committed**: `.cache/`, `*.db`
  and `.env` are gitignored. Test fixtures are synthetic.
- Care rules are guidance for staff. Unknown facts (e.g. step-free access) are
  shown as "staff to confirm", never assumed. The menu library should be
  reviewed by a dietitian before real use.

## Qloo usage notes

- Endpoints used: `GET /search`, `GET /v2/tags`, `GET /v2/insights`,
  `GET /v2/analysis/compare`. Never `/recs` or `/recommendations` (blocked in the client).
- Entity types: artist, book, brand, destination, movie, person, place, podcast,
  tv_show, video_game. `destination` requires `signal.interests.entities`.

## License

MIT

## Frontend on Vercel (optional)

The API can stay on the VM while the web app is hosted on Vercel:

1. Import this repo in Vercel and set **Root Directory** to `web` (framework: Vite; `web/vercel.json` handles SPA routes).
2. Add the environment variable `VITE_API_BASE=https://<your-api-host>` (no trailing slash), then deploy.
3. The API allows `https://*.vercel.app` origins by default; for a custom domain set `HEARTH_CORS_ORIGINS` in `/etc/hearth.env` and restart.
