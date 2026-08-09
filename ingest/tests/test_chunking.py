import pytest

from app.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("", chunk_size_chars=10, chunk_overlap_chars=2) == []


def test_text_shorter_than_one_chunk_returns_single_chunk():
    assert chunk_text("hello", chunk_size_chars=10, chunk_overlap_chars=2) == ["hello"]


def test_exact_boundaries_with_overlap():
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, chunk_size_chars=4, chunk_overlap_chars=1)  # step=3
    assert chunks == ["abcd", "defg", "ghij"]


def test_last_chunk_is_shorter_when_it_does_not_divide_evenly():
    text = "abcdefgh"  # 8 chars
    chunks = chunk_text(text, chunk_size_chars=5, chunk_overlap_chars=0)
    assert chunks == ["abcde", "fgh"]


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("abcdef", chunk_size_chars=5, chunk_overlap_chars=5)
