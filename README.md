# Solar Lead Pre-Qualifier

A single-process FastAPI app that scores worldwide addresses for solar sales viability, using
free/low-cost geospatial data (Nominatim, OpenStreetMap Overpass, PVGIS, Copernicus Sentinel-2,
ETH Global Canopy Height) plus an LLM-generated narrative. Serves both the HTML form and the JSON
API from the same process -- see `solar-lead-mvp-blueprint.md` in the repo root for the full
15-stage pipeline design.

## Module map

`app.py` only wires up FastAPI routes; the pipeline logic is split across:

| Module | Responsibility |
|---|---|
| `config.py` | Environment variables and app-wide constants |
| `models.py` | Pydantic request models |
| `countries.py` | Country list for the address form |
| `geocoding.py` | Nominatim structured (worldwide) geocoding |
| `osm.py` | Overpass building-footprint existence and adjacency checks |
| `pvgis.py` | PVGIS tilt/azimuth and regional irradiance |
| `ndvi.py` | Copernicus auth and Sentinel-2 NDVI |
| `canopy.py` | ETH canopy-height tiles and shaded-hours estimate |
| `scoring.py` | Deterministic HIGH/MEDIUM/LOW composite scoring |
| `narrative.py` | Narrative prompt + provider-agnostic generation |
| `llm/` | Narrative provider selection and clients (Anthropic, Gemini) |
| `pdf.py` | Results PDF rendering |
| `pipeline.py` | Orchestrates the above into `submit_addresses()` |

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
copy .env.example .env       # Windows; `cp` on macOS/Linux
```

Fill in `.env`:

| Variable | Required | Notes |
|---|---|---|
| `COPERNICUS_CLIENT_ID` / `COPERNICUS_CLIENT_SECRET` | Optional | Sentinel-2 NDVI. Without it, NDVI is skipped gracefully (`ndvi_unavailable: true`). |
| `ANTHROPIC_API_KEY` | Optional | LLM narrative via Claude. Used whenever set -- this is the local dev default. |
| `GEMINI_API_KEY` | Optional | LLM narrative via Gemini (has a free tier). Used only when `ANTHROPIC_API_KEY` is unset -- this is what a Render deployment should rely on. |
| `GEMINI_MODEL` | Optional | Gemini model id. Defaults to `gemini-3.6-flash`. |
| `NOMINATIM_CONTACT_EMAIL` | Recommended | Nominatim's usage policy asks for a real contact point in the User-Agent header. |

None of these are required to run the app -- every external dependency degrades gracefully and is
flagged on the record rather than failing the request. If neither `ANTHROPIC_API_KEY` nor
`GEMINI_API_KEY` is set, `narrative` is `null`.

### LLM provider: Anthropic locally, Gemini on Render

The app picks a narrative provider by which key is present, so no code change is needed between
environments:

- **Local dev**: set `ANTHROPIC_API_KEY` in `.env` -> Claude is used.
- **Render** (or anywhere cost-sensitive): set `GEMINI_API_KEY` and leave `ANTHROPIC_API_KEY`
  unset in the environment -> Gemini's free tier is used instead.
- To test the Gemini path locally, comment out `ANTHROPIC_API_KEY` in `.env` while leaving
  `GEMINI_API_KEY` set -- the app falls through to Gemini exactly as it would on Render.

## Run

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 for the form, or POST to `/api/addresses` with:

```json
{
  "addresses": [
    {
      "street_address": "55 Currie St",
      "city": "Adelaide",
      "state_region": "SA",
      "postal_code": "5000",
      "country": "Australia"
    }
  ]
}
```

`GET /health` returns `{"status": "ok"}` for uptime checks.

## Tests

```bash
pytest test_scoring.py -v
```

Covers `score_address()`, the pure composite-scoring function -- no network calls.

## Deployment (Render free web service tier)

Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`. Set the environment variables above
in Render's dashboard rather than committing `.env`. The free tier spins down after 15 minutes
idle; expect ~1 minute cold start on the next request.

Set `GEMINI_API_KEY` on Render and do **not** set `ANTHROPIC_API_KEY` there, so narratives use
Gemini's free tier instead of the paid Anthropic API (see "LLM provider" above).

## Known limits

See `solar-lead-mvp-blueprint.md` -> "Known failure modes" for the full list (canopy-height data is
a single 2020 snapshot, sequential per-address API calls don't scale past demo batches, etc). All
output is explicitly labeled an estimate, not a guaranteed return figure.
