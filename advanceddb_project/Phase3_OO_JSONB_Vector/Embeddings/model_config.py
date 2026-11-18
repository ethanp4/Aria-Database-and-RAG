"""Shared embedding-model settings for clean_reviews.py, embed_reviews.py and evaluate.py.

The model is downloaded once from Hugging Face into Embeddings/model_cache/ (gitignored) and then
runs locally on the CPU. No paid embedding service and no API key are involved.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
# Pinned Hugging Face commit so everyone embeds with exactly the same weights and tokenizer.
MODEL_REVISION = os.environ.get('ARIA_MODEL_REVISION', '1110a243fdf4706b3f48f1d95db1a4f5529b4d41')
DIMENSIONS = 384
MAX_SEQ_TOKENS = 256            # sentence-transformers truncates input after 256 word pieces
CONTENT_TOKENS = MAX_SEQ_TOKENS - 2   # minus the [CLS] and [SEP] special tokens
WINDOW_STRIDE = 192             # long reviews: 254-token windows starting every 192 tokens (62 overlap)
CACHE_DIR = HERE / 'model_cache'


def embed_text(title, body):
    """The exact string that gets embedded for a review (title carries meaning too)."""
    return f'{title}. {body}'


def load_model():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, cache_folder=str(CACHE_DIR), device='cpu')
    dim = getattr(model, 'get_embedding_dimension', None) or model.get_sentence_embedding_dimension
    assert dim() == DIMENSIONS
    model.max_seq_length = MAX_SEQ_TOKENS
    return model


def load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(MODEL_NAME, revision=MODEL_REVISION, cache_dir=str(CACHE_DIR))
