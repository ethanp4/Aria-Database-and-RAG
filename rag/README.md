# Local RAG service

The Django app retrieves document chunks from PostgreSQL with pgvector and streams grounded answers from Ollama. The source documents are under `documents/`.

## Start the services

From the repository root, start PostgreSQL and Ollama:

```powershell
docker compose up db ollama -d
```

Pull the chat and embedding models into Ollama's persistent volume:

```powershell
docker compose exec ollama ollama pull qwen3:4b-instruct
docker compose exec ollama ollama pull all-minilm:l6-v2
```

Docker Desktop on Windows needs its WSL 2 backend and NVIDIA GPU passthrough enabled for Ollama to use the GPU. The current Ollama image also needs **NVIDIA driver 550 or newer**; with an older driver it logs `NVIDIA driver too old` and silently falls back to CPU (works, but the first answer can take over a minute). Check with `docker compose exec ollama ollama ps` while a response is generating: the `PROCESSOR` column should say `GPU`.

If port 5433 is already taken on your machine, set `DB_DOCKER_PORT` and `DB_PORT` in `.env` to a free port (e.g. 5434); the indexer and `runserver` read `DB_PORT`.

## Index the documents

Create or activate a Python environment, then install the indexer's dependencies:

```powershell
python -m pip install -r rag/requirements.txt
python rag/ingest_documents.py
```

The indexer uses the Ollama `all-minilm:l6-v2` model and writes 384-dimensional embeddings to `rag_document_chunks`. Re-run it after editing documents; it updates changed chunks and removes stale ones.

## Start Django

```powershell
docker compose up --build django
```

## API

`POST /api/chat/stream/` accepts `{"message":"..."}` (max 1000 characters) and returns server-sent events:

1. `sources`: `{"sources": [{"title", "heading", "path"}, ...]}` (the citations)
2. `token`: `{"text": "..."}`, repeated as the model streams
3. `done` (`{"refused": true}` when no relevant source was found) or `error`

- Requires a logged-in session (401 otherwise). It is a session-authenticated POST, so the browser must send the `X-CSRFToken` header (value from the `csrftoken` cookie), or Django returns 403.
- Customer accounts retrieve `shared/` and `customer/` documents only. Staff and admin can also retrieve `support/` documents. Scoping is enforced server-side in `chatbot/views.py` (`allowed_source_prefixes`).
- **Refusal (invariant 6):** chunks with cosine similarity below `ARIA_RAG_MIN_SIMILARITY` (default 0.35) are discarded. If none remain, the endpoint refuses and points the user to the support team without calling the model. The 0.35 default was calibrated on `all-minilm:l6-v2`: in-scope questions scored ≥ 0.40, off-topic ones ≤ 0.32. Re-check it if you change the embedding model, chunking, or documents.
- The chatbot is read-only. It has no write access and cannot place, cancel, or refund orders.

Tests: `python manage.py test chatbot` (Ollama is mocked; the pgvector search tests run when the extension is available).
