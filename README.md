# Hearth

**A taste-aware care coordinator for older adults.** Not a chatbot.

Care homes and families plan meals, music sessions, film nights and outings for
people whose tastes are easy to guess wrong. Hearth builds each resident's plan
from [Qloo](https://qloo.com)'s taste graph, checks every pick against that
person's confirmed favourites, and shows the evidence. Care needs (soft food,
step-free access, mild films...) are handled by Hearth's own rules, labelled
**"Hearth rule, not Qloo"**, because a taste graph does not know them.

## What it does

| Job | How |
| --- | --- |
| **Taste checker** (`POST /verify`) | Any list of picks (from staff, family, or an LLM) in -> each resolved to a Qloo entity (ambiguous names come back for confirmation; no match = `cannot_verify`), scored for fit, verdict `good` / `weak` / `poor`, evidence (Qloo affinity, shared tags), and a better-fitting swap that also passes the person's care rules. |
| **Weekly plan** (`GET /residents/{id}/plan`) | Two meal themes (cuisine signal from Qloo, dishes from Hearth's menu library filtered by diet/texture), a music session, a film night, and an outing. Deterministic. |
| **Group pick** (`POST /group-pick`) | One film/outing for several residents, maximising fit across them. Names who is left out and gives each an alternative. Options that fail anyone's care rule are excluded and reported. |
| **Feedback** (`POST /feedback`) | Staff mark *enjoyed* / *didn't*; weights change which favourites are sent to Qloo as signals, and disliked items are never suggested again. |

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
HEARTH_MOCK=1 uvicorn hearth.api:app --reload   # http://127.0.0.1:8000/docs
pytest -q
```

Mock mode serves Qloo-shaped responses from `hearth/qloo/fixtures/synthetic_catalog.json`.
**Everything in it is invented** (names, IDs, addresses, numbers). The mock
affinity is a toy tag-overlap formula, not a model of Qloo.

### Try it

```bash
# 1. look up a favourite so staff can confirm the right entity
curl "localhost:8000/resolve?name=The%20Marlow%20Sisters&domain=artist"

# 2. create a resident from confirmed IDs + needs
curl -X POST localhost:8000/residents -H 'content-type: application/json' -d '{
  "name": "Ada",
  "entities": [{"id": "mock-artist-001", "name": "The Marlow Sisters", "type": "artist"}],
  "needs": ["soft_food", "mild_content", "wheelchair_access"]}'

# 3. check some picks
curl -X POST localhost:8000/verify -H 'content-type: application/json' -d '{
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
  feedback.py        enjoyed/didn't -> profile weights
  storage.py         SQLite
  api.py             FastAPI routes
  llm.py             LLM provider Protocol (no provider wired)
  data/dishes.json   Hearth's starter menu library
```

## Data and privacy

- Per resident Hearth stores a display name, care needs, confirmed Qloo
  entity/tag IDs and feedback weights. No dates of birth, rooms, medical
  records or free-text notes.
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
