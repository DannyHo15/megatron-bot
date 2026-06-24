from src.vector_store import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    estimate_chunks,
)


def test_small_file_is_one_chunk():
    assert estimate_chunks("hello world") == 1


def test_just_under_max_is_one_chunk():
    # ~4 chars per token; under the chunk size → one chunk.
    text = "x" * (CHUNK_MAX_TOKENS * 4 - 100)
    assert estimate_chunks(text) == 1


def test_grows_by_one_per_stride():
    stride_chars = (CHUNK_MAX_TOKENS - CHUNK_OVERLAP_TOKENS) * 4
    base = CHUNK_MAX_TOKENS * 4
    assert estimate_chunks("x" * base) == 1
    assert estimate_chunks("x" * (base + stride_chars)) == 2
    assert estimate_chunks("x" * (base + 2 * stride_chars)) == 3
