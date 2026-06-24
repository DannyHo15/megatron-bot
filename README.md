# KB Sync Bot

Daily job: scrape Zendesk help-center docs → OpenAI Vector Store (delta only) → Assistant cites sources.

## Setup

1. `pip install -r requirements.txt`
2. `cp .env.sample .env` and fill `OPENAI_API_KEY`, `VECTOR_STORE_ID`.
3. (first time only) `python scripts/bootstrap_store.py` to create the vector store; paste the ID into `.env` and into the Playground Assistant's File Search.

## Run

```bash
python main.py
# or
docker build -t kb-sync . && docker run --rm --env-file .env kb-sync
```

Each run prints `RESULT: {added, updated, skipped, removed} | chunks_embedded=N` and exits 0 on success.
Observed on the demo store: first run `{added: 401}` in ~80 min, delta runs `{skipped: 401}` in ~12 s.

## Delta strategy

The vector store *is* the state store: every uploaded file carries `attributes = {article_id, hash, url}`. At the start of each run, `load_remote_state()` lists those files and rebuilds the delta map — so the container is fully stateless and the daily job stays correct across runs, even on ephemeral DigitalOcean workers.

The decision key is SHA-256 of the cleaned markdown. `edited_at` from Zendesk is unreliable as a skip filter (we observed `edited_at=2021` for articles with `updated_at=2026`), so it's stored only for reference.

## Chunking

Default OpenAI static chunking: `max_chunk_size_tokens=800`, `chunk_overlap_tokens=400`. The same constants live in `src/vector_store.py` so the upload settings and the estimate stay in sync.

`chunks_embedded` in the log is an estimate, not a queried value — `vector_stores.files.content()` returns the full file as one entry, not per-chunk. Formula: `1 + ceil((tokens - 800) / 400)` for files larger than one chunk, with `tokens ≈ chars / 4`. On the 401-article demo set this gives ~1129 chunks total (avg 2.8/file, max 83 on the largest article).

## Daily job logs

DigitalOcean App Platform → Scheduled Job → runtime logs. Link: `<paste DO logs URL after deploy>`.

## Sanity check

Playground question: "How do I add a YouTube video?" — the Assistant replies with answer + `Article URL:` citations.

![answer](docs/playground-answer.png)

## Tests

`pytest -q` — covers slug, markdown cleaning (script/nav decompose), delta classification, chunk estimate.
