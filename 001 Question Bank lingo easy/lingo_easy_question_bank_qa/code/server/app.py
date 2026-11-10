"""
FastAPI app.   Run from the project root:

    pip install -r requirements.txt
    uvicorn server.app:app --reload
    -> http://127.0.0.1:8000

Thin wrapper only: all logic lives in server/api.py (tested without FastAPI).
"""
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .api import ApiError, Settings, bank_stats, health, start_exam, submit_exam

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
settings = Settings.from_env()
app = FastAPI(title="Lingo Easy placement test (prototype)")


class StartRequest(BaseModel):
    mode: Optional[str] = None
    level: Optional[str] = None
    listening: Optional[int] = None
    reading: Optional[int] = None


class SubmitRequest(BaseModel):
    answers: Dict[str, Optional[str]]


def _run(fn, *args):
    try:
        return fn(*args)
    except ApiError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@app.get("/")
def index():
    return FileResponse(FRONTEND)


@app.get("/api/health")
def api_health():
    return health(settings)


@app.get("/api/bank/stats")
def api_bank_stats():
    return bank_stats(settings)


@app.post("/api/exam/start")
def api_start(req: Optional[StartRequest] = None):
    payload = req.dict() if req is not None else {}
    return _run(start_exam, payload, settings)


@app.post("/api/exam/{exam_id}/submit")
def api_submit(exam_id: str, req: SubmitRequest):
    return _run(submit_exam, exam_id, {"answers": req.answers}, settings)
