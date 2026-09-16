"""solar_lead_mvp — single FastAPI process serving both the HTML form and JSON API.

This module wires up routes only; the actual pipeline logic lives in the
sibling modules (geocoding, osm, pvgis, ndvi, canopy, scoring, narrative,
llm/, pdf, pipeline) -- see README.md for the module map.

Start command (Render free web service tier):
    uvicorn app:app --host 0.0.0.0 --port $PORT

Local dev equivalent:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from address_validation import compare_address
from config import MAX_FORM_ROWS, NOMINATIM_USER_AGENT
from countries import COUNTRIES
from geocoding import geocode_address
from models import AddressEntry, AddressesIn, RecordCorrection
from pdf import build_results_pdf
from pipeline import ADDRESS_RECORDS, recompute_record, submit_addresses

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"max_form_rows": MAX_FORM_ROWS, "countries": COUNTRIES}
    )


@app.post("/")
async def submit_form(request: Request):
    form = await request.form()
    entries = [
        {
            "street_address": form.get(f"street_address_{i}") or "",
            "city": form.get(f"city_{i}") or "",
            "state_region": form.get(f"state_region_{i}") or "",
            "postal_code": form.get(f"postal_code_{i}") or "",
            "country": form.get(f"country_{i}") or "",
            "planned_demolition_rebuild": form.get(f"demolition_{i}") is not None,
        }
        for i in range(MAX_FORM_ROWS)
    ]
    records = await run_in_threadpool(submit_addresses, entries)
    record_ids_csv = ",".join(r["id"] for r in records)
    return templates.TemplateResponse(
        request, "results.html", {"records": records, "record_ids_csv": record_ids_csv}
    )


@app.post("/api/addresses")
def submit_json(payload: AddressesIn):
    entries = [e.model_dump() for e in payload.addresses]
    return submit_addresses(entries)


def _validate_address(entry: dict) -> dict:
    """One cheap geocode lookup (no Overpass/PVGIS/NDVI/canopy) so the caller
    can confirm/correct an address before the full pipeline runs on it."""
    with httpx.Client(headers={"User-Agent": NOMINATIM_USER_AGENT}, timeout=25.0) as client:
        geocode_result = geocode_address(
            client,
            entry["street_address"],
            entry.get("city", ""),
            entry.get("state_region", ""),
            entry.get("postal_code", ""),
            entry.get("country", ""),
        )
    return compare_address(entry, geocode_result)


@app.post("/api/addresses/validate")
async def validate_address(payload: AddressEntry):
    return await run_in_threadpool(_validate_address, payload.model_dump())


@app.post("/api/addresses/{record_id}/recompute")
async def recompute(record_id: str, corrections: RecordCorrection):
    if record_id not in ADDRESS_RECORDS:
        raise HTTPException(status_code=404, detail="Record not found")
    return await run_in_threadpool(recompute_record, record_id, corrections.model_dump())


@app.get("/download-pdf")
def download_pdf(ids: str = ""):
    record_ids = [i for i in ids.split(",") if i]
    records = [ADDRESS_RECORDS[i] for i in record_ids if i in ADDRESS_RECORDS]
    if not records:
        raise HTTPException(status_code=404, detail="No matching records found")

    pdf_bytes = build_results_pdf(records)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="solar_lead_results.pdf"'},
    )
