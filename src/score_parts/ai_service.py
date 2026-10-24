"""Optional trial service. Keeps API keys server-side and never saves page images."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class PageRequest(BaseModel):
    title: str = Field(max_length=200)
    part: str = Field(max_length=200)
    page: int = Field(ge=1, le=1000)
    image_base64: str = Field(max_length=8_000_000)


app = FastAPI(title="Score Parts AI Trial", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _reserve(token: str) -> None:
    allowed = {item.strip() for item in os.environ.get("SCORE_PARTS_TRIAL_TOKENS", "").split(",") if item.strip()}
    if token not in allowed:
        raise HTTPException(401, "Invalid trial token")
    token = hashlib.sha256(token.encode("utf-8")).hexdigest()
    limit = int(os.environ.get("SCORE_PARTS_TRIAL_LIMIT", "30"))
    database = Path(os.environ.get("SCORE_PARTS_USAGE_DB", "trial_usage.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS usage (token TEXT PRIMARY KEY, used INTEGER NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            used = connection.execute("SELECT used FROM usage WHERE token=?", (token,)).fetchone()
            if used and used[0] >= limit:
                raise HTTPException(429, "Trial page limit reached")
            connection.execute("INSERT INTO usage(token, used) VALUES (?, 1) ON CONFLICT(token) DO UPDATE SET used=used+1", (token,))


def _refund(token: str) -> None:
    token = hashlib.sha256(token.encode("utf-8")).hexdigest()
    database = Path(os.environ.get("SCORE_PARTS_USAGE_DB", "trial_usage.sqlite3"))
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("UPDATE usage SET used=MAX(used-1, 0) WHERE token=?", (token,))


def _ask_model(title: str, part: str, page: int, image_b64: str) -> list[dict]:
    from openai import OpenAI

    model = os.environ.get("OPENAI_MODEL")
    if not model or not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Server model and API key are not configured")
    instruction = (
        "You review a printed music part page for layout issues only. "
        "Do not claim notes are wrong, do not suggest changing pitches or rhythms, and do not invent missing context. "
        "Return only JSON: {\"findings\":[{\"code\":string,\"severity\":\"review\"|\"warning\","
        "\"message\":string,\"evidence\":string}]}. "
        "Use an empty list when no visible issue exists. Describe precise visible evidence. "
        f"Score: {title}; instrument: {part}; page: {page}."
    )
    response = OpenAI(timeout=60.0, max_retries=1).responses.create(model=model, input=[{
        "role": "user", "content": [
            {"type": "input_text", "text": instruction},
            {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
        ],
    }])
    raw = response.output_text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        raise ValueError("Model response is not a findings object")
    return parsed["findings"][:20]


@app.post("/v1/check-page")
def check_page(payload: PageRequest, authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Trial token required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        image = base64.b64decode(payload.image_base64, validate=True)
    except ValueError as error:
        raise HTTPException(400, "Invalid image encoding") from error
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > 4_000_000:
        raise HTTPException(400, "A PNG page under 4 MB is required")
    _reserve(token)
    try:
        suggestions = _ask_model(payload.title, payload.part, payload.page, payload.image_base64)
    except Exception as error:
        _refund(token)
        raise HTTPException(502, "AI review is temporarily unavailable") from error
    clean = []
    for item in suggestions:
        if isinstance(item, dict):
            clean.append({
                "code": str(item.get("code", "ai_review"))[:80],
                "severity": item.get("severity") if item.get("severity") in {"review", "warning"} else "review",
                "message": str(item.get("message", "Please review this page"))[:500],
                "evidence": str(item.get("evidence", ""))[:500],
            })
    return {"findings": clean}
