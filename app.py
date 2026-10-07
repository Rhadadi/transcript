import math
import os
import re
import secrets
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))

app = FastAPI(title="Farsi Medical Transcriber", version="0.1.0")
ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN", "")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "https://rhadadi.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization"])
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "elevenlabs_configured": bool(ELEVENLABS_API_KEY),
        "model": "scribe_v2_medical",
    }


def parse_keyterms(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parts = re.split(r"[,\n;]+", raw)
    cleaned: list[str] = []
    seen = set()
    for part in parts:
        term = " ".join(part.strip().split())
        if not term:
            continue
        if len(term) > 49:
            term = term[:49].rstrip()
        if term.lower() not in seen:
            seen.add(term.lower())
            cleaned.append(term)
        if len(cleaned) >= 1000:
            break
    return cleaned


def smart_join(chunks: list[str]) -> str:
    text = ""
    punctuation_no_leading_space = set(".,!?؟،؛:;)]}٪%»…")
    no_space_after = set("([{«")
    for raw in chunks:
        token = str(raw or "")
        if not token:
            continue
        if token.isspace():
            if text and not text.endswith(" "):
                text += " "
            continue
        if not text:
            text = token
        elif token[0] in punctuation_no_leading_space or text[-1] in no_space_after:
            text += token
        elif text.endswith((" ", "\n")):
            text += token
        else:
            text += " " + token
    return re.sub(r"[ \t]+", " ", text).strip()


def segment_transcript(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create readable speaker/sentence segments without rewriting ASR text.

    Flush on speaker change, clear sentence-ending punctuation, long pause,
    or overly long segment. Confidence is a heuristic based on mean logprob,
    never presented as a calibrated probability.
    """
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    sentence_end = re.compile(r"[.!?؟]+[\"'»)]*$")

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = smart_join(current["tokens"])
        if text:
            lps = current["logprobs"]
            avg_lp = sum(lps) / len(lps) if lps else None
            min_lp = min(lps) if lps else None
            segments.append(
                {
                    "speaker_id": current["speaker_id"],
                    "start": current["start"],
                    "end": current["end"],
                    "text": text,
                    "avg_logprob": round(avg_lp, 3) if avg_lp is not None else None,
                    "min_logprob": round(min_lp, 3) if min_lp is not None else None,
                    "needs_review": bool(
                        (avg_lp is not None and avg_lp < -0.9)
                        or (min_lp is not None and min_lp < -2.0)
                    ),
                }
            )
        current = None

    last_speaker = "speaker_unknown"
    last_end: float | None = None

    for item in words or []:
        token = item.get("text", "")
        item_type = item.get("type", "word")
        speaker = item.get("speaker_id") or last_speaker
        start = item.get("start")
        end = item.get("end")
        logprob = item.get("logprob")

        # Non-verbal audio events are omitted from the readable transcript,
        # but remain available in raw_json returned to the browser.
        if item_type == "audio_event":
            continue

        if current is not None:
            speaker_changed = speaker != current["speaker_id"]
            pause = (
                isinstance(start, (int, float))
                and isinstance(last_end, (int, float))
                and start - last_end > 1.8
            )
            too_long = (
                isinstance(end, (int, float))
                and isinstance(current["start"], (int, float))
                and end - current["start"] > 28
            )
            if speaker_changed or pause or too_long:
                flush()

        if current is None:
            current = {
                "speaker_id": speaker,
                "start": start if isinstance(start, (int, float)) else 0.0,
                "end": end if isinstance(end, (int, float)) else 0.0,
                "tokens": [],
                "logprobs": [],
            }

        current["tokens"].append(token)
        if isinstance(end, (int, float)):
            current["end"] = end
            last_end = end
        if isinstance(logprob, (int, float)) and math.isfinite(logprob):
            current["logprobs"].append(logprob)

        last_speaker = speaker

        candidate = smart_join(current["tokens"])
        if sentence_end.search(candidate) and len(candidate) >= 4:
            flush()

    flush()
    return segments


@app.post("/api/transcribe")
async def transcribe(
    authorization: str | None = Header(None),
    file: UploadFile = File(...),
    language_code: str = Form("fas"),
    num_speakers: str = Form(""),
    keyterms: str = Form(""),
    tag_audio_events: bool = Form(False),
):
    if not ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="APP_ACCESS_TOKEN is not configured on the server.")
    if not secrets.compare_digest(authorization or "", "Bearer " + ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Incorrect app access token.")
    if not ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ELEVENLABS_API_KEY is not configured on the server.",
        )

    content = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds this server's {MAX_UPLOAD_MB} MB upload limit.",
        )

    terms = parse_keyterms(keyterms)

    # Multipart form. Repeated keyterms fields are used for an array parameter.
    form_fields: list[tuple[str, str]] = [
        ("model_id", "scribe_v2_medical"),
        
        ("diarize", "true"),
        ("timestamps_granularity", "word"),
        ("tag_audio_events", "true" if tag_audio_events else "false"),
    ]

    if language_code.strip() and language_code != "auto":
        form_fields.append(("language_code", language_code.strip()))

    if num_speakers.strip():
        try:
            n = int(num_speakers)
            if not 1 <= n <= 32:
                raise ValueError
            form_fields.append(("num_speakers", str(n)))
        except ValueError:
            raise HTTPException(status_code=400, detail="Number of speakers must be 1-32.")

    for term in terms:
        form_fields.append(("keyterms", term))

    files = {
        "file": (
            file.filename or "audio.m4a",
            content,
            file.content_type or "application/octet-stream",
        )
    }
    headers = {"xi-api-key": ELEVENLABS_API_KEY}

    timeout = httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                ELEVENLABS_STT_URL,
                headers=headers,
                files=[(key, (None, value)) for key, value in form_fields] + list(files.items()),
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"ElevenLabs connection failed: {exc}")

    if response.status_code >= 400:
        try:
            upstream = response.json()
        except Exception:
            upstream = response.text[:2000]
        raise HTTPException(
            status_code=502,
            detail={"elevenlabs_status": response.status_code, "elevenlabs_error": upstream},
        )

    data = response.json()
    words = data.get("words") or []
    segments = segment_transcript(words)

    speakers = []
    seen_speakers = set()
    for seg in segments:
        sid = seg["speaker_id"]
        if sid not in seen_speakers:
            seen_speakers.add(sid)
            speakers.append(sid)

    return {
        "model": "scribe_v2_medical",
        "language_code": data.get("language_code"),
        "language_probability": data.get("language_probability"),
        "text": data.get("text", ""),
        "segments": segments,
        "speakers": speakers,
        "keyterms_used": terms,
        "raw_json": data,
    }
