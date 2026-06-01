from __future__ import annotations

from typing import Any


CANON_STAT_KEYS = [
    "comm_bytes",
    "phase_map_ms",
    "phase_blind_ms",
    "phase_blind_a_ms",
    "phase_blind_b_ms",
    "phase_blind_back_ms",
    "phase_compare_ms",
]


METHODS_WITHOUT_PHASE_STATS = {
    "hash",
    "hash_baseline",
    "ecdh_sim",
    "dh_sim",
    "simulated_dh",
    "dh",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """将统计字段转换为float；无法转换时返回默认值。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_psi_stats(stats: dict | None, method: str | None = None) -> dict[str, float]:
    """
    统一不同PSI方法返回的统计字段。

    对没有分阶段统计的方法，如哈希基线和DH PSI，各阶段字段显式写为0，
    避免CSV中出现空值；通信量字段可由benchmark按协议口径另行填充。
    对ECDH PSI和Socket ECDH PSI，如果底层实现没有返回某个阶段字段，也统一补0。
    """
    method_key = (method or "").strip().lower()
    out = {key: 0.0 for key in CANON_STAT_KEYS}

    if method_key in METHODS_WITHOUT_PHASE_STATS:
        return out

    if not stats:
        return out

    for key in CANON_STAT_KEYS:
        out[key] = _to_float(stats.get(key), default=0.0)

    return out
