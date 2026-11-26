"""Agreement statistics for independently completed proposal reviews."""

from __future__ import annotations


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    p_a = sum(a == "act" for a, _ in pairs) / n
    p_b = sum(b == "act" for _, b in pairs) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)
