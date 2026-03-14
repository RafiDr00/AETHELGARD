"""Quick semantic embedding smoke-test."""
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

print("Loading all-MiniLM-L6-v2 ...")
model = SentenceTransformer("all-MiniLM-L6-v2")

docs = [
    "worker pool exhaustion async workers saturated",
    "thread pool saturated connection limit reached",
    "cpu saturation compute bound high utilisation",
    "memory leak gradual exhaustion gc pressure",
    "database bottleneck slow queries connection pool",
    "dependency failure upstream service errors circuit breaker",
]
labels = [d[:35] for d in docs]

vecs = model.encode(docs, show_progress_bar=False, normalize_embeddings=True).astype(np.float32)
print(f"Embedding dim : {vecs.shape[1]}")
print(f"Documents     : {len(docs)}")

index = faiss.IndexFlatIP(vecs.shape[1])
index.add(vecs)

queries = [
    "async workers exhausted latency spike",
    "memory growing slowly pod restart",
    "upstream dependency returning 503 errors",
]

print()
for q in queries:
    qv = model.encode([q], normalize_embeddings=True).astype(np.float32)
    scores, ids = index.search(qv, 3)
    print(f'Query: "{q}"')
    for score, idx in zip(scores[0], ids[0]):
        print(f"  {score:.4f}  {labels[idx]}")
    print()

print("sentence-transformers + FAISS: READY")
