# Farsi Medical Transcriber

GitHub Pages frontend with a private FastAPI backend. Persian and English medical terms, speaker diarization, editable timestamped sentences, segment playback, raw transcript and JSON export. Transcripts are drafts requiring review; logprob flags are heuristics.

## Publish the frontend

In repository **Settings → Pages**, select **Deploy from a branch**, **main**, **/docs**, then Save.
Expected URL: https://rhadadi.github.io/transcript/
Only `docs/` is published. Never add API keys or recordings to this repository.

## Start your backend

On your own server:

```sh
cp .env.example .env
```

Set `ELEVENLABS_API_KEY` to a replacement key, and `APP_ACCESS_TOKEN` to a separate long random token (generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). Leave `ALLOWED_ORIGINS=https://rhadadi.github.io` for Pages. Then:

```sh
docker compose up --build -d
```

Or install requirements and run `uvicorn app:app --host 0.0.0.0 --port 8000`. Put the server behind HTTPS (a reverse proxy or your existing HTTPS tunnel). Allow large request bodies and at least 10-minute request timeouts in the proxy. Do not expose an unprotected upload endpoint; transcription requires the app access token. CORS alone is not authentication.

Open the Pages site, enter the HTTPS backend URL and the **app access token**, then Connect. The ElevenLabs key stays only on the server. The app token stays in tab memory; only the backend URL is saved in browser storage. Audio goes from browser to backend to ElevenLabs, never through GitHub Pages. Playback uses a local browser URL.

For local use, open http://localhost:8000 and enter the app token. Uploaded content is read up to the configured size limit; upload framework temporary files may be used. No recording or transcript is intentionally retained by the app. Provider retention is separate.

## Status

Primary ASR: `scribe_v2_medical`; default language `fas`; blank language enables auto-detection. Optional speaker count and keyterms. Independent second ASR and reconciliation are not implemented yet. Real provider transcription must be tested with a new key and representative recording.

Tests: `python3 -m unittest discover -s tests` (requires requirements installed).
