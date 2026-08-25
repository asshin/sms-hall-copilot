from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.catalog import load_catalog, load_users
from app.config import STATIC_DIR
from app.config_assist import draft_config
from app.engine import handle_mo
from app.eval_runner import run_eval
from app.session import store
from app.tools import reset_runtime

app = FastAPI(title="HarborTel SMS Hall Copilot", version="0.1.0")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class SmsIn(BaseModel):
    msisdn: str
    text: str


class ConfigIn(BaseModel):
    requirement: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/sms")
def sms(body: SmsIn) -> dict:
    result = handle_mo(body.msisdn.strip(), body.text)
    return {
        "replies": result.replies,
        "session_state": result.session_state,
        "trace": result.trace.model_dump(),
    }


@app.post("/api/reset")
def reset(msisdn: str | None = None) -> dict:
    reset_runtime()
    store.reset(msisdn)
    return {"ok": True}


@app.post("/api/eval")
def eval_api() -> dict:
    return run_eval()


@app.post("/api/config")
def config_api(body: ConfigIn) -> dict:
    return draft_config(body.requirement)


@app.get("/api/meta")
def meta() -> dict:
    cat = load_catalog()
    return {
        "operator": cat["operator"],
        "shortcode": cat["shortcode"],
        "disclaimer": cat["disclaimer"],
        "users": [
            {
                "msisdn": u["msisdn"],
                "plan": u["plan"],
                "lang": u["lang"],
                "hint": f"{u['plan']} / {u['lang']}",
            }
            for u in load_users().values()
        ],
    }
