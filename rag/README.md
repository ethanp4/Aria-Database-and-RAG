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

Docker Desktop on Windows needs its WSL 2 backend and NVIDIA GPU passthrough enabled for Ollama to use the GPU.

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

The authenticated `POST /api/chat/stream/` endpoint accepts `{"message":"..."}` and returns server-sent events: a `sources` event, streamed `token` events, then `done`. Customer accounts can retrieve shared and customer documents. Staff and admin accounts can also retrieve support documents.
