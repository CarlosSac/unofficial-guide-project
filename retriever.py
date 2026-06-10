"""Embedding and retrieval for The Unofficial Guide (Milestone 4).

Pipeline stage (see planning.md architecture diagram):
    chunks.json -> Embedding (all-MiniLM-L6-v2) -> Vector Store (ChromaDB) -> Retrieval (top-k)

embed_and_store() loads the chunks produced by ingest.py, embeds them with
all-MiniLM-L6-v2, and stores them in a persistent ChromaDB collection along with
their metadata. retrieve() embeds a query and returns the top-k most similar chunks.

    python retriever.py            # (re)build the index, then run the test queries
"""

import json
from pathlib import Path

import config

_BASE = Path(__file__).parent
_model = None  # SentenceTransformer is loaded once and reused


def get_model():
    """Load the embedding model once (downloads ~80MB on first run, then cached)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def get_collection():
    """Open (or create) the persistent ChromaDB collection."""
    import chromadb

    # PersistentClient writes the index to disk so it survives between runs.
    client = chromadb.PersistentClient(path=str(_BASE / config.CHROMA_PATH))
    # cosine space suits normalized sentence-transformer embeddings (default is L2).
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def embed_and_store() -> int:
    """Embed every chunk and (re)build the ChromaDB collection. Returns the count."""
    import chromadb

    chunks = json.loads((_BASE / config.CHUNKS_FILE).read_text(encoding="utf-8"))
    if not chunks:
        raise SystemExit("No chunks found. Run the ingestion pipeline first.")

    # Rebuild from scratch so re-runs do not duplicate or leave stale vectors.
    client = chromadb.PersistentClient(path=str(_BASE / config.CHROMA_PATH))
    try:
        client.delete_collection(name=config.COLLECTION_NAME)
    except Exception:
        pass  # collection did not exist yet
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    ids = [c["id"] for c in chunks]
    documents = [c["text"] for c in chunks]
    # ChromaDB rejects None metadata values, so drop empty keys per chunk.
    metadatas = [
        {k: v for k, v in c["metadata"].items() if v is not None}
        for c in chunks
    ]

    # Encode all chunk texts to vectors, then hand them to Chroma with the text + metadata.
    embeddings = get_model().encode(documents, show_progress_bar=True).tolist()
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

    return collection.count()


def retrieve(query: str, k: int = config.TOP_K) -> list[dict]:
    """Return the k chunks most semantically similar to the query."""
    query_embedding = get_model().encode([query]).tolist()
    results = get_collection().query(query_embeddings=query_embedding, n_results=k)

    # query() returns nested lists (one inner list per query); we sent one query, so use [0].
    chunks = []
    for text, metadata, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        chunks.append({"text": text, "metadata": metadata, "distance": distance})
    return chunks


# Test queries: the 5 evaluation questions from planning.md.
TEST_QUERIES = [
    "What are the prerequisites and co-requisites for APCT 232 Computer Science II?",
    "Which textbook is used for APCT 110/111 Introduction to Programming and who coordinates it?",
    "What lab software or simulator is used in the networking course CYSE 210?",
    "Which course covers reverse engineering and malware analysis?",
    "What do students say about Dr. Li Chen's teaching and project expectations?",
]


def main() -> None:
    count = embed_and_store()
    print(f"\nIndexed {count} chunks into ChromaDB collection '{config.COLLECTION_NAME}'.\n")

    for query in TEST_QUERIES:
        print(f"Q: {query}")
        for chunk in retrieve(query):
            meta = chunk["metadata"]
            preview = chunk["text"][:90].replace("\n", " ")
            print(f"  ({chunk['distance']:.3f}) [{meta.get('source')}] {preview}...")
        print()


if __name__ == "__main__":
    main()
