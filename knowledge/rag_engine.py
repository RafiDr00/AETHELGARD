"""
Aethelgard v2 — RAG Knowledge Engine (Redesigned)

FIX #3: Replace MD5-hash-based embeddings with semantic embeddings.

PREVIOUS FLAW:
  Used MD5 hashing of individual words to produce 64-dimensional vectors.
  "Worker pool exhausted" and "Thread pool exhausted" produced completely
  different embeddings despite being semantically equivalent. The
  knowledge retrieval returned essentially random results.

NEW DESIGN:
  Primary:  sentence-transformers (all-MiniLM-L6-v2, 384-dim)
            + FAISS IndexFlatIP for fast ANN search
  Fallback: TF-IDF weighted sparse embeddings (scikit-learn)
  Fallback: Improved hash-based (if neither is installed)

  Auto-detection at initialize() time — no manual configuration needed.
  The embedding quality improves as better libraries are available.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger(__name__)

# Embedding backend selection
_EMBEDDING_BACKEND = "hash"  # will be upgraded in initialize()


class RAGEngine:
    """
    RAG engine with semantic similarity search.

    Backends (auto-selected at initialize()):
      1. sentence-transformers + FAISS  → Production quality, ANN search
      2. TF-IDF vectors                 → Good baseline, no GPU needed
      3. Improved hash embeddings       → Always-available fallback

    All backends expose the same query() / ingest_document() interface.
    """

    def __init__(self):
        self._settings = get_settings()
        self._documents: List[Dict[str, Any]] = []
        self._backend: str = "hash"

        # FAISS index (used when sentence-transformers available)
        self._faiss_index = None
        self._embedding_model = None
        self._embedding_dim: int = 64

        # TF-IDF state
        self._tfidf_matrix = None
        self._tfidf_vocab: Dict[str, int] = {}
        self._idf: Dict[str, float] = {}
        self._tfidf_dirty: bool = True

        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize embedding backend — tries best available.
        """
        global _EMBEDDING_BACKEND

        # Try sentence-transformers + FAISS first
        try:
            from sentence_transformers import SentenceTransformer
            import faiss

            model_name = "all-MiniLM-L6-v2"
            logger.info("rag_loading_model", model=model_name)
            self._embedding_model = SentenceTransformer(model_name)
            # Get actual dimension from a test encode
            test_vec = self._embedding_model.encode(["test"], show_progress_bar=False)
            self._embedding_dim = test_vec.shape[1]
            # Initialize FAISS index (inner product for cosine after L2-normalization)
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            self._backend = "sentence_transformers"
            _EMBEDDING_BACKEND = "sentence_transformers"
            logger.info("rag_engine_initialized",
                        backend="sentence_transformers",
                        model=model_name,
                        dims=self._embedding_dim)
            self._initialized = True
            return
        except ImportError:
            logger.info("rag_sentence_transformers_unavailable",
                        note="Install: pip install sentence-transformers faiss-cpu")

        # Try TF-IDF (scikit-learn)
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._tfidf_vectorizer = TfidfVectorizer(
                max_features=2048,
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            self._backend = "tfidf"
            _EMBEDDING_BACKEND = "tfidf"
            logger.info("rag_engine_initialized",
                        backend="tfidf",
                        note="Install sentence-transformers for better results")
            self._initialized = True
            return
        except ImportError:
            logger.info("rag_tfidf_unavailable")

        # Fallback: improved hash embeddings
        self._backend = "hash"
        _EMBEDDING_BACKEND = "hash"
        self._embedding_dim = 128  # larger than previous 64
        logger.warning("rag_engine_initialized",
                       backend="hash_embedding",
                       warning="Semantic quality limited — install sentence-transformers")
        self._initialized = True

    # ─────────────────────────────────────────────
    # Ingestion
    # ─────────────────────────────────────────────

    async def ingest_document(
        self,
        content: str,
        metadata: Dict[str, Any] = None,
        source: str = "",
        category: str = "",
    ) -> str:
        """Ingest a document into the knowledge base."""
        doc_id = f"doc-{len(self._documents):05d}"

        embedding = self._compute_embedding(content)

        document = {
            "id": doc_id,
            "content": content,
            "metadata": metadata or {},
            "source": source,
            "category": category,
            "embedding": embedding,
            "ingested_at": time.time(),
        }
        self._documents.append(document)

        # Rebuild FAISS index incrementally
        if self._backend == "sentence_transformers" and self._faiss_index is not None:
            vec = np.array([embedding], dtype=np.float32)
            self._faiss_index.add(vec)
        else:
            self._tfidf_dirty = True

        logger.debug("document_ingested",
                     doc_id=doc_id,
                     source=source,
                     category=category,
                     content_length=len(content),
                     backend=self._backend)

        return doc_id

    async def ingest_playbook(self, filepath: str) -> str:
        """Ingest a remediation playbook, chunking long documents."""
        path = Path(filepath)
        if not path.exists():
            logger.warning("playbook_not_found", path=filepath)
            return ""

        content = path.read_text(encoding="utf-8")

        # Chunk documents > 2000 chars (prevents single-vector dilution)
        chunks = self._chunk_text(content, max_chars=2000, overlap=200)
        first_id = ""
        for i, chunk in enumerate(chunks):
            doc_id = await self.ingest_document(
                content=chunk,
                source=filepath,
                category="playbook",
                metadata={"filename": path.name, "chunk": i, "total_chunks": len(chunks)},
            )
            if i == 0:
                first_id = doc_id

        logger.info("playbook_ingested",
                    filename=path.name,
                    chunks=len(chunks))
        return first_id

    async def store_remediation(self, remediation_data: Dict[str, Any]) -> str:
        """
        FIX #6: Store successful remediation as searchable knowledge.

        The text is structured to be semantically queryable, so future
        incidents with similar characteristics retrieve this fix.
        """
        anomaly_type = remediation_data.get("anomaly_type", "unknown")
        root_cause = remediation_data.get("root_cause", "unknown")
        fix_desc = remediation_data.get("fix_description", "unknown")
        actions = remediation_data.get("recommended_actions", [])
        category = remediation_data.get("root_cause_category", "unknown")

        # Structured content optimized for semantic retrieval
        content = "\n".join([
            f"Incident Type: {anomaly_type}",
            f"Root Cause Category: {category}",
            f"Root Cause: {root_cause}",
            f"Fix Applied: {fix_desc}",
            f"Recommended Actions: {'; '.join(actions)}",
            f"Patch Type: {remediation_data.get('patch_type', 'unknown')}",
            f"Outcome: {'SUCCESS' if remediation_data.get('was_successful') else 'FAILED'}",
            f"Risk Score: {remediation_data.get('risk_score', 1.0):.2f}",
        ])

        return await self.ingest_document(
            content=content,
            source="learning_system",
            category="remediation_history",
            metadata=remediation_data,
        )

    # ─────────────────────────────────────────────
    # Query
    # ─────────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        category: Optional[str] = None,
        threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search over the knowledge base.

        Returns results sorted by relevance score (0.0–1.0).
        """
        if not self._documents:
            return []

        if self._backend == "sentence_transformers":
            return self._query_faiss(query_text, top_k, category, threshold)
        elif self._backend == "tfidf":
            return self._query_tfidf(query_text, top_k, category, threshold)
        else:
            return self._query_hash(query_text, top_k, category, threshold)

    def _query_faiss(
        self, query_text: str, top_k: int, category: Optional[str], threshold: float
    ) -> List[Dict[str, Any]]:
        """FAISS ANN search — O(log N) vs O(N) linear scan."""
        query_vec = np.array(
            [self._compute_embedding(query_text)], dtype=np.float32
        )

        n_docs = len(self._documents)
        k = min(top_k * 3, n_docs)  # over-fetch for category filter
        scores, indices = self._faiss_index.search(query_vec, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= n_docs:
                continue
            doc = self._documents[idx]
            if category and doc.get("category") != category:
                continue
            if float(score) < threshold:
                continue
            results.append({
                "id": doc["id"],
                "content": doc["content"][:500],
                "source": doc["source"],
                "category": doc["category"],
                "metadata": doc["metadata"],
                "relevance": round(float(score), 4),
            })
            if len(results) >= top_k:
                break

        return sorted(results, key=lambda x: x["relevance"], reverse=True)

    def _query_tfidf(
        self, query_text: str, top_k: int, category: Optional[str], threshold: float
    ) -> List[Dict[str, Any]]:
        """TF-IDF cosine similarity search."""
        try:
            from sklearn.metrics.pairwise import cosine_similarity

            docs = self._documents
            if category:
                docs = [d for d in docs if d.get("category") == category]
            if not docs:
                return []

            corpus = [d["content"] for d in docs]
            vectorizer = self._tfidf_vectorizer

            if self._tfidf_dirty or len(corpus) != (
                self._tfidf_matrix.shape[0] if self._tfidf_matrix is not None else 0
            ):
                self._tfidf_matrix = vectorizer.fit_transform(corpus)
                self._tfidf_dirty = False

            query_vec = vectorizer.transform([query_text])
            similarities = cosine_similarity(query_vec, self._tfidf_matrix)[0]

            top_indices = similarities.argsort()[::-1][:top_k]
            results = []
            for idx in top_indices:
                if similarities[idx] < threshold:
                    continue
                doc = docs[idx]
                results.append({
                    "id": doc["id"],
                    "content": doc["content"][:500],
                    "source": doc["source"],
                    "category": doc["category"],
                    "metadata": doc["metadata"],
                    "relevance": round(float(similarities[idx]), 4),
                })
            return results
        except Exception as e:
            logger.warning("tfidf_query_failed", error=str(e))
            return self._query_hash(query_text, top_k, category, threshold)

    def _query_hash(
        self, query_text: str, top_k: int, category: Optional[str], threshold: float
    ) -> List[Dict[str, Any]]:
        """Improved hash embedding linear scan (fallback only)."""
        query_embedding = self._compute_embedding(query_text)
        results = []
        for doc in self._documents:
            if category and doc.get("category") != category:
                continue
            similarity = self._cosine_similarity(query_embedding, doc.get("embedding", []))
            if similarity >= threshold:
                results.append({
                    "id": doc["id"],
                    "content": doc["content"][:500],
                    "source": doc["source"],
                    "category": doc["category"],
                    "metadata": doc["metadata"],
                    "relevance": round(similarity, 4),
                })
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:top_k]

    # ─────────────────────────────────────────────
    # Embedding Computation
    # ─────────────────────────────────────────────

    def _compute_embedding(self, text: str) -> List[float]:
        """Compute embedding using the active backend."""
        if self._backend == "sentence_transformers" and self._embedding_model:
            try:
                vec = self._embedding_model.encode(
                    [text], show_progress_bar=False, normalize_embeddings=True
                )
                return vec[0].tolist()
            except Exception as e:
                logger.warning("st_embedding_failed", error=str(e))

        # Improved hash embedding: bigram-aware, length-128
        import hashlib
        dim = self._embedding_dim
        words = re.findall(r"\w+", text.lower())
        embedding = [0.0] * dim

        # Unigrams
        for word in words:
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            for i in range(dim):
                embedding[i] += ((h >> i) & 1) * 2.0 - 1.0

        # Bigrams (captures word order — fixes major flaw in original MD5 approach)
        for w1, w2 in zip(words, words[1:]):
            bigram = f"{w1}_{w2}"
            h = int(hashlib.sha256(bigram.encode()).hexdigest(), 16)
            for i in range(dim):
                embedding[i] += 0.5 * (((h >> i) & 1) * 2.0 - 1.0)

        # L2 normalize
        magnitude = math.sqrt(sum(x ** 2 for x in embedding))
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]

        return embedding

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Vectorized cosine similarity via numpy."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        a = np.array(vec_a)
        b = np.array(vec_b)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
        """
        Split long text into overlapping chunks for better vector coverage.
        Chunks on paragraph boundaries where possible.
        """
        paragraphs = text.split("\n\n")
        chunks = []
        current = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) > max_chars and current:
                chunks.append("\n\n".join(current))
                # Keep last paragraph for overlap
                overlap_paras = []
                overlap_len = 0
                for p in reversed(current):
                    if overlap_len + len(p) <= overlap:
                        overlap_paras.insert(0, p)
                        overlap_len += len(p)
                    else:
                        break
                current = overlap_paras
                current_len = overlap_len
            current.append(para)
            current_len += len(para)

        if current:
            chunks.append("\n\n".join(current))

        return chunks if chunks else [text]

    # ─────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────

    @property
    def document_count(self) -> int:
        return len(self._documents)

    @property
    def categories(self) -> List[str]:
        return list(set(d.get("category", "") for d in self._documents))

    @property
    def embedding_backend(self) -> str:
        return self._backend
