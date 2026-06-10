"""Central configuration for the pipeline (see planning.md)."""

# Chunk source (output of ingest.py)
CHUNKS_FILE = "chunks.json"

# Embedding + vector store (Retrieval Approach section)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "unofficial_guide"
TOP_K = 5

# Generation (Milestone 5)
GROQ_MODEL = "llama-3.3-70b-versatile"
