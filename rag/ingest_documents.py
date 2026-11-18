import hashlib
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg2
from dotenv import load_dotenv


DOCUMENTS_DIR = Path(__file__).parent / "documents"
PROJECT_ROOT = Path(__file__).parent.parent
EMBEDDING_MODEL = "all-minilm:l6-v2"
EMBEDDING_DIMENSIONS = 384
MAX_CHUNK_WORDS = 150


def split_document(text):
  sections = []
  current_heading = ""
  current_lines = []

  for line in text.splitlines():
    heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
    if heading_match:
      if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
      current_heading = heading_match.group(2).strip()
      current_lines = []
    else:
      current_lines.append(line)

  if current_lines:
    sections.append((current_heading, "\n".join(current_lines).strip()))

  chunks = []
  chunk_headings = []
  chunk_parts = []
  chunk_word_count = 0

  for heading, section_text in sections:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section_text) if paragraph.strip()]
    for paragraph in paragraphs:
      words = paragraph.split()
      paragraph_parts = [
        " ".join(words[start:start + MAX_CHUNK_WORDS])
        for start in range(0, len(words), MAX_CHUNK_WORDS)
      ]

      for paragraph_part in paragraph_parts:
        part_word_count = len(paragraph_part.split())
        if chunk_parts and chunk_word_count + part_word_count > MAX_CHUNK_WORDS:
          chunks.append((" / ".join(chunk_headings), "\n\n".join(chunk_parts)))
          chunk_headings = []
          chunk_parts = []
          chunk_word_count = 0

        if heading and heading not in chunk_headings:
          chunk_headings.append(heading)
          chunk_parts.append(f"## {heading}\n{paragraph_part}")
        else:
          chunk_parts.append(paragraph_part)
        chunk_word_count += part_word_count

  if chunk_parts:
    chunks.append((" / ".join(chunk_headings), "\n\n".join(chunk_parts)))

  return chunks


def main():
  load_dotenv(PROJECT_ROOT / ".env")
  ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
  documents = sorted(DOCUMENTS_DIR.rglob("*.md"))
  if not documents:
    raise SystemExit(f"No Markdown documents found in {DOCUMENTS_DIR}")

  rows = []
  chunk_counts = {}
  for document_path in documents:
    source_path = document_path.relative_to(PROJECT_ROOT).as_posix()
    text = document_path.read_text(encoding="utf-8")
    title_match = re.search(r"(?m)^#\s+(.+?)\s*#*\s*$", text)
    title = title_match.group(1).strip() if title_match else document_path.stem.replace("-", " ").title()
    document_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for chunk_index, (heading, content) in enumerate(split_document(text)):
      if content:
        rows.append((source_path, chunk_index, title, heading, content, document_hash))
        chunk_counts[source_path] = chunk_index + 1

  if not rows:
    raise SystemExit("The Markdown files contain no indexable text")

  embedding_request = Request(
    f"{ollama_base_url}/api/embed",
    data=json.dumps({
      "model": EMBEDDING_MODEL,
      "input": [f"{row[2]}\n{row[3]}\n{row[4]}" for row in rows],
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  with urlopen(embedding_request, timeout=120) as response:
    embeddings = json.loads(response.read().decode("utf-8"))["embeddings"]
  if len(embeddings) != len(rows):
    raise ValueError(f"Expected {len(rows)} embeddings, got {len(embeddings)}")
  if any(len(embedding) != EMBEDDING_DIMENSIONS for embedding in embeddings):
    raise ValueError(f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings")

  connection = psycopg2.connect(
    dbname=os.getenv("DB_NAME", "aria"),
    user=os.getenv("DB_USER", "aria"),
    password=os.getenv("DB_PASSWORD", "pass"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5433"),
  )
  try:
    with connection:
      with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute("""
          CREATE TABLE IF NOT EXISTS rag_document_chunks (
            source_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            heading TEXT NOT NULL,
            content TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            embedding VECTOR(384) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (source_path, chunk_index)
          )
        """)

        current_paths = sorted({row[0] for row in rows})
        cursor.execute(
          "DELETE FROM rag_document_chunks WHERE source_path LIKE 'rag/documents/%%' AND source_path <> ALL(%s)",
          (current_paths,),
        )
        for source_path, chunk_count in chunk_counts.items():
          cursor.execute(
            "DELETE FROM rag_document_chunks WHERE source_path = %s AND chunk_index >= %s",
            (source_path, chunk_count),
          )

        for row, embedding in zip(rows, embeddings, strict=True):
          source_path, chunk_index, title, heading, content, document_hash = row
          cursor.execute("""
            INSERT INTO rag_document_chunks
              (source_path, chunk_index, title, heading, content, document_hash, embedding, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (source_path, chunk_index) DO UPDATE SET
              title = EXCLUDED.title,
              heading = EXCLUDED.heading,
              content = EXCLUDED.content,
              document_hash = EXCLUDED.document_hash,
              embedding = EXCLUDED.embedding,
              updated_at = now()
          """, (
            source_path,
            chunk_index,
            title,
            heading,
            content,
            document_hash,
            json.dumps(embedding),
          ))
  finally:
    connection.close()

  print(f"Indexed {len(rows)} chunks from {len(documents)} documents into rag_document_chunks")


if __name__ == "__main__":
  main()
