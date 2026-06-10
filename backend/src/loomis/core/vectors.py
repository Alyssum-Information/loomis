"""Voiceprint vector primitives: serialization + cosine math (stdlib only).

Embeddings are plain float tuples stored as ``float32`` BLOBs in the
``voiceprints`` table (docs/05-data-model-and-storage.md §4.6). Kept numpy-free
so the base install stays light; the heavy embedding engines live in
``loomis.pipeline.speakerid``.
"""

from __future__ import annotations

import math
from array import array

Vector = tuple[float, ...]


def vec_to_blob(vec: Vector) -> bytes:
    return array("f", vec).tobytes()


def blob_to_vec(blob: bytes) -> Vector:
    a = array("f")
    a.frombytes(blob)
    return tuple(a)


def l2_normalize(vec: Vector) -> Vector:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return tuple(v / norm for v in vec)


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity. Inputs need not be normalized; guards zero vectors."""
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def centroid(vecs: list[Vector]) -> Vector:
    """Mean of a speaker's voiceprints, L2-normalized (the comparison key, feature 04 §5)."""
    if not vecs:
        return ()
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            acc[i] += v[i]
    n = float(len(vecs))
    return l2_normalize(tuple(x / n for x in acc))
