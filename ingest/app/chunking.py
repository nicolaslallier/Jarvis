def chunk_text(text: str, *, chunk_size_chars: int, chunk_overlap_chars: int) -> list[str]:
    """Naive fixed-size character windows with overlap.

    No sentence/paragraph-awareness and no tokenizer library — deliberately
    minimal until retrieval quality can actually be measured against
    something. Slides forward by ``chunk_size_chars - chunk_overlap_chars``
    each step; the last chunk is shorter if the text doesn't divide evenly.
    """
    if not text:
        return []

    step = chunk_size_chars - chunk_overlap_chars
    if step <= 0:
        raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")

    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size_chars, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        start += step
    return chunks
