def format_vector_literal(embedding: list[float]) -> str:
    """Render pgvector's text input format, e.g. "[0.1,0.2,0.3]".

    Passed as a plain string query parameter and cast with `CAST(... AS
    vector)` in SQL, so this doesn't need asyncpg's pgvector codec
    registered on the connection — see jarvis_shared.db.make_engine's
    register_vector_codec, which backend deliberately leaves off so its DB
    connection doesn't hard-depend on the vector extension existing. Shared
    by app/rag.py (file_chunks) and app/memory.py (memories) — both query
    pgvector columns the same way.
    """
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"
