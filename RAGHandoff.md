# RAG Handoff (Ollama + pgvector chatbot)

Continues Ethan's handoff for the `rag` branch. This covers what was finished on top of
`origin/rag` (commit `8dbbf06`), what was verified, and what is still open.

## Branch

- Work is on local branch **`feature/rag-finish`**, created from `origin/rag`.
- **Not committed or pushed yet.** Changed files:
  - `docker-compose.yml`: GPU syntax (see below)
  - `aria_project/aria/settings.py`: `ARIA_RAG_MIN_SIMILARITY`
  - `aria_project/chatbot/views.py`: retrieval refactor, relevance threshold, refusal text, prompt
  - `aria_project/chatbot/tests/` (new): `__init__.py`, `test_stream.py`
  - `rag/README.md`: API docs, refusal rules, GPU driver and port notes
- Next step: commit, push, and open a PR into `master`. Don't merge directly.

## What the feature is (unchanged from Ethan's design)

- Ollama runs as a Compose service with a persistent `ollama-data` volume on `127.0.0.1:11434`.
- Chat model: `qwen3:4b-instruct` (`num_ctx` 4096, thinking off, temperature 0.2, at most 512 tokens).
- Embeddings: `all-minilm:l6-v2` (384 dimensions), used for both indexing and queries.
- Vectors live in PostgreSQL/pgvector table `rag_document_chunks` (`db` image `pgvector/pgvector:pg18-trixie`).
  The table is created by `rag/ingest_documents.py`, not by a Django migration.
- Endpoint: `POST /api/chat/stream/` with body `{"message": "..."}`. It returns server-sent events:
  `sources`, then repeated `token`, then `done` (or `error`).
- Documents are in `rag/documents/{shared,customer,support}/`. Customers retrieve `shared` and `customer`.
  Staff and admin also retrieve `support`.

## Done in this session

### Environment setup (dev laptop)

- Docker Desktop (WSL 2) was already installed. The RTX 3060 (6 GB) is visible inside the Ollama container.
- Created `.env` from `.env.example` (git-ignored).
- **Port change:** host port 5433 was already used by another local Postgres container (`aria-phase3-pg`),
  so `.env` sets `DB_DOCKER_PORT=5434` and `DB_PORT=5434`. On a machine where 5433 is free, keep the defaults.
- Pulled `qwen3:4b-instruct` (2.5 GB) and `all-minilm:l6-v2` (45 MB) into the Ollama volume.
- Created `rag/venv` (git-ignored) with `rag/requirements.txt`. Python 3.10 on the host is fine for the
  indexer. Django itself needs Python 3.12 or later, so it runs in Docker.
- Re-indexed: **25 chunks from 10 documents**, all 384 dimensions (shared 13, customer 3, support 9).
  Ethan's old 11 Sentence Transformers vectors don't exist on this machine.
- Ran migrations and `create_default_accounts` in the compose DB.

### Code changes

1. **Compose GPU syntax:** replaced `gpus: all` with
   `deploy.resources.reservations.devices` (`driver: nvidia`, `count: all`, `capabilities: [gpu]`).
   `gpus:` requires Compose 2.30 or later. The long form works on every version (this laptop has 2.24).
2. **Invariant 6 fix (refuse when there is no relevant source):** previously the bot refused only when
   retrieval returned zero rows. Top-K vector search always returns rows, so it effectively never refused.
   - Added the setting `ARIA_RAG_MIN_SIMILARITY` (default **0.35**, overridable by env var). Chunks below it
     are dropped. If none remain, the endpoint streams the refusal and **does not call the model**.
   - Calibration (top-1 cosine similarity, customer scope):
     - In-scope questions (returns, shipping, order status, gear care, privacy, tracking, cancel,
       wetsuit refunds) scored **0.40 to 0.69**.
     - Off-topic questions (capital of France, Python code, World Cup, lasagna, stock tip, weather,
       bitcoin, joke) scored **0.02 to 0.32**.
   - Re-run this calibration if the embedding model, chunk size, or documents change. CLAUDE.md requires
     before/after checks for retrieval changes.
3. **Refusal text** now offers a human: *"I couldn't find that in Aria's policy documents, so I won't
   guess. Please contact our support team and a staff member will help you."* The final event of a
   refusal is `done` with `{"refused": true}`.
4. **System prompt** now tells the model to suggest contacting support when the excerpts don't answer
   the question. It also says it cannot place, change, cancel, or refund orders and must never claim an
   action (invariant 5).
5. **Retrieval refactor** for testability, in `chatbot/views.py`:
   - `allowed_source_prefixes(account)`: the role-to-folder mapping, enforced server-side.
   - `_embed_question(question)`: calls Ollama `/api/embed` and checks for 384 dimensions.
   - `_search_chunks(embedding, prefixes, limit)`: the pgvector SQL.
   - `_retrieve_sources(question, account)`: applies the threshold, then drops any chunk outside the
     allowed prefixes as a second safeguard.
6. **Error handling:** any `OSError` (connection refused/reset, timeout, `URLError`, `HTTPError`) now
   becomes a 503 before streaming starts, or an `error` event during streaming. Previously only listed
   subclasses were caught.

### Tests added (`aria_project/chatbot/tests/test_stream.py`, 13 tests, all pass)

- Anonymous request returns 401. GET returns 405. Bad JSON, an empty message, or one over 1000 characters
  returns 400.
- A request without a CSRF token returns 403 (enforced CSRF client).
- Ollama unreachable returns 503.
- Role scoping: customers get no `support/` prefix, staff and admin do. Rows from a leaked support
  document are dropped for customers.
- Refusal: an empty index or below-threshold matches produce the refusal events, and the model is never
  called.
- The happy path streams `sources`, `token`, `token`, `done` with citations. A model failure produces an
  `error` event.
- **Real pgvector SQL tests:** they create `rag_document_chunks` in the test DB, then check that a customer
  never gets support chunks and staff do. They skip automatically if the `vector` extension isn't
  installed (for example, a CI image based on plain `postgres:18`).

Full suite: **208 tests. Only 2 fail, and both failures were already on the `rag` branch** (see Open items).
Command used (repo root, Git Bash):

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v "$(pwd -W)/aria_project:/app" django python manage.py test
```

### Live smoke test (real Ollama, Django on port 8001, session login + CSRF header)

| Who | Question | Result |
|---|---|---|
| customer | When should a refund be escalated or flagged as a duplicate? | Sources: shared only. Model said it couldn't find it. **Support doc not exposed.** |
| staff | same | Sources include `support: Refund decision guide`. Answered from it. |
| customer | How long do I have to return an item? | "30 calendar days after delivery [Returns and refunds]" |
| customer | What is the capital of France? | Instant refusal + support handoff, `refused: true`, model not called |
| customer | Can you cancel my order for me? | Declined, pointed to support. No action. |

- SSE streams correctly through the Django dev server (`runserver`) in the container.
- An anonymous POST without a CSRF token gets **403 rather than 401**, because Django's CSRF middleware
  runs first. With a CSRF token it gets 401, which the unit tests cover. Both responses are safe.

## Not done / open items

1. **GPU not used on this laptop.** Ollama logs `NVIDIA driver too old: driver=546, required 550 or newer`
   and falls back to CPU. Latency: the first answer took about 97 s (cold load), later ones 9 to 44 s.
   Fix: update the NVIDIA driver to 550 or newer (NVIDIA App or nvidia.com, may need a reboot), then run
   `docker compose restart ollama`. Confirm with `docker compose exec ollama ollama ps`: the `PROCESSOR`
   column should show `GPU`.
2. **No frontend.** Nothing in the site uses `/api/chat/stream/` yet. A chat page or widget needs:
   - login gating
   - reading `csrftoken` and sending `X-CSRFToken`
   - reading the stream with `fetch()` plus `ReadableStream`. `EventSource` can't POST.
   - showing `sources` as citations, and handling `refused` and `error`
3. **Order records are not a RAG source yet.** CLAUDE.md lists policy docs plus order records, scoped to
   the asking user's identity and role. Only policy docs are wired. Order access must be read-only, and
   customers may see only their own orders (filter by `account=current_account(request)`). Never include
   card data or fraud/risk scores in customer answers.
4. **Fixed question set for retrieval/prompt changes:** CLAUDE.md requires before/after checks on a fixed
   question set that includes out-of-scope refusals. The 16 calibration questions above are a start but
   aren't saved as a script or fixture yet.
5. **Pre-existing test failures (not RAG):** two tests in `products/tests.py` call
   `call_command('sample_data')`, but the command is now `create_sample_data`. Fix the tests or the
   command name.
6. **Chat transcripts are not stored.** That's fine for now. If they're added, the 90-day retention and
   anonymization rule applies.
7. **`rag_document_chunks` is not a Django model or migration.** CLAUDE.md says schema changes go through
   migrations, but the table is created by the indexer script. Consider a migration
   (`CREATE EXTENSION vector` plus the table, unmanaged model) so the schema is tracked.
8. **CLAUDE.md is stale:** it says Postgres runs on the host and that compose has no DB service. Compose
   now runs `db` (pgvector) and `ollama`. It also lists the `sample_data` command and the `.env` location
   as `aria_project/aria/.env`, but settings read `.env` at the repo root.
9. **Docker housekeeping on the dev laptop (not repo):** an old `aria-database-and-rag-django-1` container
   (about 4 weeks old) holds port 8000, so the compose `django` service will clash with it. Stop it before
   running `docker compose up django`.

## Quick start on a fresh machine

```powershell
git checkout feature/rag-finish        # or the PR branch once pushed
copy .env.example .env                 # change DB_DOCKER_PORT/DB_PORT if 5433 is taken
docker compose up -d db ollama
docker compose exec ollama ollama pull qwen3:4b-instruct
docker compose exec ollama ollama pull all-minilm:l6-v2
python -m venv rag/venv; rag/venv/Scripts/python -m pip install -r rag/requirements.txt
rag/venv/Scripts/python rag/ingest_documents.py      # expect "Indexed 25 chunks from 10 documents"
docker compose run --rm django python manage.py migrate
docker compose up --build django
```

Do not copy `.env`, `pgdata/`, Docker volumes, `rag/venv`, or Ollama models between machines.
