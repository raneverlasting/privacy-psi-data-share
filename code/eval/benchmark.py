from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

# 使用非交互后端，避免在无GUI环境运行benchmark时卡住
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 尽量支持中文显示；Windows下优先使用Microsoft YaHei/SimHei
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


# ============================================================
# 路径与模块导入
# ============================================================

EVAL_DIR = Path(__file__).resolve().parent
ROOT_DIR = EVAL_DIR.parent
DATA_DIR = ROOT_DIR / "data"

sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(EVAL_DIR))

from data.generate_data import generate_pair_data
from baseline.hash_psi import hash_psi
from psi.dh_psi import MOD as DH_MOD
from psi.dh_psi import dh_psi
from psi.ecdh_psi import ecdh_psi
from psi.socket_ecdh_psi import socket_ecdh_psi
from stats_schema import CANON_STAT_KEYS, normalize_psi_stats


# ============================================================
# 方法名与论文展示名
# ============================================================

# 代码输出统一使用这4个规范方法名。
METHOD_HASH = "hash_baseline"
METHOD_DH = "dh"
METHOD_ECDH = "ecdh"
METHOD_SOCKET_ECDH = "socket_ecdh"

METHODS_BASE = [METHOD_HASH, METHOD_DH, METHOD_ECDH]
METHODS_WITH_SOCKET = METHODS_BASE + [METHOD_SOCKET_ECDH]

METHOD_DISPLAY: dict[str, str] = {
    METHOD_HASH: "哈希基线",
    METHOD_DH: "DH PSI",
    METHOD_ECDH: "ECDH PSI",
    METHOD_SOCKET_ECDH: "Socket ECDH PSI",
}

HASH_DIGEST_BYTES = 32
DH_ELEMENT_BYTES = (DH_MOD.bit_length() + 7) // 8
ECDH_POINT_BYTES = 33

# 兼容旧版benchmark_summary.csv或旧代码中使用的方法名。
METHOD_ALIASES: dict[str, str] = {
    "hash": METHOD_HASH,
    "hash_baseline": METHOD_HASH,
    "ecdh_sim": METHOD_DH,
    "dh_sim": METHOD_DH,
    "simulated_dh": METHOD_DH,
    "dh": METHOD_DH,
    "ecdh": METHOD_ECDH,
    "socket_ecdh": METHOD_SOCKET_ECDH,
}


# ============================================================
# 基础工具函数
# ============================================================

def _normalize_method_name(method: str) -> str:
    """将历史方法名统一为论文和CSV使用的规范方法名。"""
    key = str(method).strip()
    return METHOD_ALIASES.get(key, key)


def _method_label(method: str) -> str:
    """图例、论文表格中的显示名称。"""
    method = _normalize_method_name(method)
    return METHOD_DISPLAY.get(method, method)


def _dep_versions() -> dict[str, str]:
    """记录依赖版本，便于论文中说明实验可复现性。"""
    names = ["pandas", "numpy", "matplotlib", "coincurve"]
    out: dict[str, str] = {}

    for name in names:
        try:
            out[name] = importlib.metadata.version(name)
        except Exception:
            out[name] = "unknown"

    return out


def write_run_meta(out_dir: Path, meta: dict[str, Any]) -> None:
    """写入实验运行元数据。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "run_meta.json"

    with p.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _parse_int_list(csv_text: str) -> list[int]:
    items: list[int] = []
    for x in (csv_text or "").split(","):
        x = x.strip()
        if x:
            items.append(int(x))
    return items


def _parse_float_list(csv_text: str) -> list[float]:
    items: list[float] = []
    for x in (csv_text or "").split(","):
        x = x.strip()
        if x:
            items.append(float(x))
    return items


def _safe_len(obj: Any) -> int:
    """兼容set/list/tuple等对象，避免返回类型不确定时报错。"""
    try:
        return len(obj)
    except Exception:
        return 0


def _parse_bool_series(series: pd.Series) -> pd.Series:
    """
    稳健解析布尔列。

    直接astype(bool)会把非空字符串"False"也转成True。
    该函数用于兼容旧CSV中可能出现的True/False字符串、0/1数字等情况。
    """
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).astype(int).astype(bool)

    true_values = {"true", "1", "yes", "y", "ok", "通过"}
    false_values = {"false", "0", "no", "n", "warn", "未通过", ""}

    def convert(value: Any) -> bool:
        if value is None:
            return False
        text = str(value).strip().lower()
        if text in true_values:
            return True
        if text in false_values:
            return False
        return False

    return series.map(convert)


def _run_one_method(method: str, path_a: str, path_b: str):
    """按规范方法名调用不同PSI实现。"""
    method = _normalize_method_name(method)

    if method == METHOD_HASH:
        return hash_psi(path_a, path_b)

    if method == METHOD_DH:
        return dh_psi(path_a, path_b)

    if method == METHOD_ECDH:
        return ecdh_psi(path_a, path_b, return_stats=True)

    if method == METHOD_SOCKET_ECDH:
        return socket_ecdh_psi(path_a, path_b, return_stats=True)

    raise ValueError(f"未知方法:{method}")


def _extract_method_result(result: Any) -> tuple[Any, float, dict[str, Any]]:
    """
    兼容不同PSI函数返回格式：
    1.(intersection_ids, elapsed_seconds)
    2.(intersection_ids, elapsed_seconds, raw_stats)
    """
    if not isinstance(result, tuple):
        raise TypeError(f"方法返回值应为tuple，实际为:{type(result)}")

    if len(result) == 2:
        intersection_ids, elapsed_seconds = result
        raw_stats: dict[str, Any] = {}
        return intersection_ids, float(elapsed_seconds), raw_stats

    if len(result) == 3:
        intersection_ids, elapsed_seconds, raw_stats = result
        if raw_stats is None:
            raw_stats = {}
        return intersection_ids, float(elapsed_seconds), dict(raw_stats)

    raise ValueError(f"方法返回tuple长度异常:{len(result)}")


def _move_generated_bench_files(data_dir: Path, tmp_a: Path, tmp_b: Path) -> None:
    """
    generate_pair_data(party_a_name='bench_A', party_b_name='bench_B')
    按当前项目习惯会生成：
    data/party_bench_A.csv
    data/party_bench_B.csv

    这里统一改名为：
    data/bench_A.csv
    data/bench_B.csv
    """
    src_a = data_dir / "party_bench_A.csv"
    src_b = data_dir / "party_bench_B.csv"

    if src_a.exists():
        os.replace(src_a, tmp_a)
    elif not tmp_a.exists():
        raise FileNotFoundError(f"未找到A方benchmark输入文件:{src_a}或{tmp_a}")

    if src_b.exists():
        os.replace(src_b, tmp_b)
    elif not tmp_b.exists():
        raise FileNotFoundError(f"未找到B方benchmark输入文件:{src_b}或{tmp_b}")


def _ensure_numeric_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """确保数值列存在，缺失列补0，缺失值补0。"""
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def _round_float_columns(df: pd.DataFrame, digits: int = 2) -> pd.DataFrame:
    """导出论文表格前对浮点列做统一保留小数处理。"""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(digits)
    return out


def _sort_by_method_order(df: pd.DataFrame) -> pd.DataFrame:
    """按论文中推荐的顺序排序：哈希基线、DH PSI、ECDH PSI、Socket ECDH PSI。"""
    order = {
        METHOD_HASH: 0,
        METHOD_DH: 1,
        METHOD_ECDH: 2,
        METHOD_SOCKET_ECDH: 3,
    }

    out = df.copy()
    out["_method_order"] = out["method"].map(order).fillna(99).astype(int)
    out = out.sort_values(["total_ids", "intersection_ratio", "_method_order"])
    out = out.drop(columns="_method_order")
    return out


def _estimate_protocol_comm_bytes(method: str, size_a: int, size_b: int) -> float:
    """
    估算非Socket方法的逻辑通信量。

    benchmark中的comm_bytes统一采用A、B两端发送与接收字节数之和。
    Socket ECDH PSI使用实际Socket收发统计；单进程方法没有真实网络收发，
    因此按协议中需要交换的数据项大小进行估算。
    """
    method = _normalize_method_name(method)

    if method == METHOD_HASH:
        wire_bytes = size_b * HASH_DIGEST_BYTES
    elif method == METHOD_DH:
        wire_bytes = (2 * size_a + size_b) * DH_ELEMENT_BYTES
    elif method == METHOD_ECDH:
        wire_bytes = (2 * size_a + size_b) * ECDH_POINT_BYTES
    else:
        wire_bytes = 0

    return float(2 * wire_bytes)


def _default_comm_sizes(sizes: list[int]) -> list[int]:
    """为Socket通信量图生成更密集的数据规模采样点。"""
    clean_sizes = sorted({int(size) for size in sizes if int(size) > 0})
    if len(clean_sizes) <= 1:
        return clean_sizes

    start = clean_sizes[0]
    end = clean_sizes[-1]
    step = 500
    values = list(range(start, end + 1, step))
    if values[-1] != end:
        values.append(end)
    return values


def _run_socket_comm_detail(
    comm_sizes: list[int],
    base_ratio: float,
    repeats: int,
    seed: int,
    tmp_a: Path,
    tmp_b: Path,
) -> pd.DataFrame:
    """单独运行Socket ECDH PSI通信量采样，不混入主summary和论文表格。"""
    rows: list[dict[str, Any]] = []

    if not comm_sizes:
        return pd.DataFrame(rows)

    print("\n=== Socket ECDH PSI通信量采样开始 ===")
    print(f"通信量采样规模comm_sizes:{comm_sizes}")
    print(f"通信量采样交集比例:{base_ratio}")

    for total_ids in comm_sizes:
        for run_idx in range(repeats):
            run_seed = seed + total_ids * 19 + int(base_ratio * 10000) * 23 + run_idx

            _, _, expected = generate_pair_data(
                total_ids=total_ids,
                intersection_ratio=base_ratio,
                seed=run_seed,
                party_a_name="bench_A",
                party_b_name="bench_B",
            )

            _move_generated_bench_files(DATA_DIR, tmp_a, tmp_b)
            expected_intersection_size = _safe_len(expected)

            begin = time.perf_counter()
            result = socket_ecdh_psi(str(tmp_a), str(tmp_b), return_stats=True)
            intersection_ids, elapsed_seconds, raw_stats = _extract_method_result(result)
            norm = normalize_psi_stats(raw_stats, method=METHOD_SOCKET_ECDH)
            end_to_end_elapsed_ms = (time.perf_counter() - begin) * 1000.0

            actual_intersection_size = _safe_len(intersection_ids)
            is_correct = actual_intersection_size == expected_intersection_size

            row: dict[str, Any] = {
                "total_ids": total_ids,
                "intersection_ratio": base_ratio,
                "run_idx": run_idx,
                "seed": run_seed,
                "method": METHOD_SOCKET_ECDH,
                "method_display": _method_label(METHOD_SOCKET_ECDH),
                "expected_intersection_size": expected_intersection_size,
                "actual_intersection_size": actual_intersection_size,
                "is_correct": is_correct,
                "protocol_elapsed_ms": elapsed_seconds * 1000.0,
                "end_to_end_elapsed_ms": end_to_end_elapsed_ms,
            }
            row.update(norm)
            rows.append(row)

            flag = "OK" if is_correct else "WARN"
            print(
                f"[{flag}] comm total_ids={total_ids:<7} run={run_idx:<3} "
                f"intersection={actual_intersection_size:<6}/{expected_intersection_size:<6} "
                f"comm_bytes={norm['comm_bytes']:.0f}"
            )

    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail

    detail = _ensure_numeric_columns(detail, [*CANON_STAT_KEYS])
    summary = build_summary(detail)
    summary = summary[summary["method"] == METHOD_SOCKET_ECDH].copy()
    summary = summary.sort_values("total_ids")
    return summary


# ============================================================
# 命令行参数
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PSI性能评测：输出benchmark_detail.csv、benchmark_summary.csv、run_meta.json、论文表格和论文图表"
    )

    p.add_argument(
        "--sizes",
        type=str,
        default="1000,5000",
        help="数据规模列表，逗号分隔，例如1000,5000,10000",
    )

    p.add_argument(
        "--ratios",
        type=str,
        default="0.01,0.1",
        help="交集比例列表，逗号分隔，例如0.01,0.05,0.1",
    )

    p.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="每组参数重复次数，用于计算均值和标准差",
    )

    p.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="基础随机种子",
    )

    p.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="输出目录，默认eval/目录",
    )

    p.add_argument(
        "--include-socket",
        dest="include_socket",
        action="store_true",
        default=True,
        help="包含Socket ECDH PSI方法，默认包含",
    )

    p.add_argument(
        "--no-socket",
        dest="include_socket",
        action="store_false",
        help="不运行Socket ECDH PSI方法",
    )

    p.add_argument(
        "--comm-sizes",
        type=str,
        default=None,
        help="Socket通信量图专用数据规模列表，默认在最小和最大sizes之间每500条取一点",
    )

    return p


# ============================================================
# 汇总与论文表格函数
# ============================================================

def build_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    """
    根据benchmark_detail.csv对应的明细数据构造summary。

    字段命名规则：
    1.输入条件使用total_ids、intersection_ratio。
    2.方法使用method和method_display。
    3.正确性使用expected_intersection_size、actual_intersection_size_mean、correct_rate。
    4.均值字段统一采用xxx_mean，标准差字段统一采用xxx_std。
    """
    df = detail_df.copy()

    if "size" in df.columns and "total_ids" not in df.columns:
        df["total_ids"] = df["size"]

    if "method" in df.columns:
        df["method"] = df["method"].map(_normalize_method_name)
    else:
        raise KeyError("benchmark_detail缺少method字段")

    df["method_display"] = df["method"].map(_method_label)

    # 兼容旧字段名。
    if "expected_intersection" in df.columns and "expected_intersection_size" not in df.columns:
        df["expected_intersection_size"] = df["expected_intersection"]

    if "actual_intersection" in df.columns and "actual_intersection_size" not in df.columns:
        df["actual_intersection_size"] = df["actual_intersection"]

    numeric_cols = [
        "total_ids",
        "intersection_ratio",
        "expected_intersection_size",
        "actual_intersection_size",
        "protocol_elapsed_ms",
        "end_to_end_elapsed_ms",
        *CANON_STAT_KEYS,
    ]

    df = _ensure_numeric_columns(df, numeric_cols)

    if "is_correct" not in df.columns:
        df["is_correct"] = df["actual_intersection_size"] == df["expected_intersection_size"]
    else:
        df["is_correct"] = _parse_bool_series(df["is_correct"])

    summary = (
        df.groupby(["total_ids", "intersection_ratio", "method", "method_display"], as_index=False)
        .agg(
            expected_intersection_size=("expected_intersection_size", "first"),
            actual_intersection_size_mean=("actual_intersection_size", "mean"),
            protocol_elapsed_ms_mean=("protocol_elapsed_ms", "mean"),
            protocol_elapsed_ms_std=("protocol_elapsed_ms", "std"),
            end_to_end_elapsed_ms_mean=("end_to_end_elapsed_ms", "mean"),
            end_to_end_elapsed_ms_std=("end_to_end_elapsed_ms", "std"),
            comm_bytes_mean=("comm_bytes", "mean"),
            phase_map_ms_mean=("phase_map_ms", "mean"),
            phase_blind_ms_mean=("phase_blind_ms", "mean"),
            phase_blind_a_ms_mean=("phase_blind_a_ms", "mean"),
            phase_blind_b_ms_mean=("phase_blind_b_ms", "mean"),
            phase_blind_back_ms_mean=("phase_blind_back_ms", "mean"),
            phase_compare_ms_mean=("phase_compare_ms", "mean"),
            correct_runs=("is_correct", "sum"),
            total_runs=("is_correct", "count"),
            correct_rate=("is_correct", "mean"),
        )
    )

    numeric_summary_cols = [
        "expected_intersection_size",
        "actual_intersection_size_mean",
        "protocol_elapsed_ms_mean",
        "protocol_elapsed_ms_std",
        "end_to_end_elapsed_ms_mean",
        "end_to_end_elapsed_ms_std",
        "comm_bytes_mean",
        "phase_map_ms_mean",
        "phase_blind_ms_mean",
        "phase_blind_a_ms_mean",
        "phase_blind_b_ms_mean",
        "phase_blind_back_ms_mean",
        "phase_compare_ms_mean",
        "correct_runs",
        "total_runs",
        "correct_rate",
    ]

    summary = _ensure_numeric_columns(summary, numeric_summary_cols)
    summary["protocol_elapsed_ms_std"] = summary["protocol_elapsed_ms_std"].fillna(0.0)
    summary["end_to_end_elapsed_ms_std"] = summary["end_to_end_elapsed_ms_std"].fillna(0.0)
    summary["is_correct"] = summary["correct_runs"] == summary["total_runs"]

    summary = _sort_by_method_order(summary)
    return summary


def build_paper_table(summary: pd.DataFrame) -> pd.DataFrame:
    """
    生成论文表4.1推荐使用的精简表格。

    注意：
    - 该表只保留论文正文需要解释的字段。
    - 分阶段耗时字段不进入表4.1，应放在4.3.4分阶段耗时分析中。
    """
    required_cols = [
        "method_display",
        "total_ids",
        "intersection_ratio",
        "expected_intersection_size",
        "actual_intersection_size_mean",
        "protocol_elapsed_ms_mean",
        "end_to_end_elapsed_ms_mean",
        "comm_bytes_mean",
        "is_correct",
    ]

    missing = [col for col in required_cols if col not in summary.columns]
    if missing:
        raise KeyError(f"summary缺少生成论文表格所需字段:{missing}")

    table = summary[required_cols].copy()

    table = table.rename(
        columns={
            "method_display": "方法",
            "total_ids": "数据规模/条",
            "intersection_ratio": "交集比例",
            "expected_intersection_size": "期望交集规模/条",
            "actual_intersection_size_mean": "实际交集规模/条",
            "protocol_elapsed_ms_mean": "协议耗时/ms",
            "end_to_end_elapsed_ms_mean": "端到端耗时/ms",
            "comm_bytes_mean": "通信量/byte",
            "is_correct": "校验结果",
        }
    )

    table["实际交集规模/条"] = table["实际交集规模/条"].round(0).astype(int)
    table["期望交集规模/条"] = table["期望交集规模/条"].round(0).astype(int)
    table["通信量/byte"] = table["通信量/byte"].round(0).astype(int)
    table["校验结果"] = table["校验结果"].map({True: "通过", False: "未通过"}).fillna("未通过")
    table = _round_float_columns(table, digits=2)

    return table


# ============================================================
# 绘图函数
# ============================================================

def _save_grouped_bar_by_total_ids(
    summary: pd.DataFrame,
    methods: list[str],
    base_ratio: float,
    out_path: Path,
) -> None:
    fig_df = summary[summary["intersection_ratio"] == base_ratio].copy()

    total_ids = sorted(fig_df["total_ids"].dropna().astype(int).unique().tolist())
    x = np.arange(len(total_ids))
    bar_width = 0.8 / max(len(methods), 1)

    plt.figure(figsize=(10, 5.5))

    for idx, method in enumerate(methods):
        method = _normalize_method_name(method)
        d = fig_df[fig_df["method"] == method].sort_values("total_ids")
        if d.empty:
            continue

        values_by_size = dict(zip(d["total_ids"].astype(int), d["protocol_elapsed_ms_mean"]))
        values = [float(values_by_size.get(size, 0.0)) for size in total_ids]
        offset = (idx - (len(methods) - 1) / 2) * bar_width
        bars = plt.bar(
            x + offset,
            values,
            width=bar_width,
            label=_method_label(method),
        )
        plt.bar_label(bars, fmt="%.0f", padding=2, fontsize=7)

    plt.xticks(x, [str(size) for size in total_ids])
    plt.xlabel("数据规模（条）")
    plt.ylabel("协议耗时均值（ms）")
    plt.title(f"不同数据规模下各方法协议耗时对比（交集比例={base_ratio}）")
    plt.grid(True, axis="y", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def _save_grouped_bar_by_ratio(
    summary: pd.DataFrame,
    methods: list[str],
    base_total_ids: int,
    out_path: Path,
) -> None:
    fig_df = summary[summary["total_ids"] == base_total_ids].copy()

    ratios = sorted(fig_df["intersection_ratio"].dropna().astype(float).unique().tolist())
    x = np.arange(len(ratios))
    bar_width = 0.8 / max(len(methods), 1)

    plt.figure(figsize=(10, 5.5))

    for idx, method in enumerate(methods):
        method = _normalize_method_name(method)
        d = fig_df[fig_df["method"] == method].sort_values("intersection_ratio")
        if d.empty:
            continue

        values_by_ratio = dict(zip(d["intersection_ratio"].astype(float), d["protocol_elapsed_ms_mean"]))
        values = [float(values_by_ratio.get(ratio, 0.0)) for ratio in ratios]
        offset = (idx - (len(methods) - 1) / 2) * bar_width
        bars = plt.bar(
            x + offset,
            values,
            width=bar_width,
            label=_method_label(method),
        )
        plt.bar_label(bars, fmt="%.0f", padding=2, fontsize=7)

    plt.xticks(x, [str(ratio) for ratio in ratios])
    plt.xlabel("交集比例")
    plt.ylabel("协议耗时均值（ms）")
    plt.title(f"不同交集比例下各方法协议耗时对比（数据规模={base_total_ids}）")
    plt.grid(True, axis="y", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def _save_comm_bytes_plot(
    summary: pd.DataFrame,
    base_ratio: float,
    out_path: Path,
    comm_detail: pd.DataFrame | None = None,
) -> bool:
    if comm_detail is not None and not comm_detail.empty:
        fig_df = comm_detail.copy()
    else:
        fig_df = summary[
            (summary["intersection_ratio"] == base_ratio)
            & (summary["method"] == METHOD_SOCKET_ECDH)
        ].copy()

    if fig_df.empty:
        return False

    if "comm_bytes" in fig_df.columns and "comm_bytes_mean" not in fig_df.columns:
        fig_df["comm_bytes_mean"] = fig_df["comm_bytes"]

    fig_df = fig_df.sort_values("total_ids")

    plt.figure(figsize=(10, 5.5))
    plt.plot(
        fig_df["total_ids"],
        fig_df["comm_bytes_mean"],
        marker="^",
        linewidth=1.8,
        label=_method_label(METHOD_SOCKET_ECDH),
    )

    plt.xlabel("数据规模（条）")
    plt.ylabel("通信量均值（byte）")
    plt.title(f"Socket ECDH PSI通信量随数据规模变化（交集比例={base_ratio}）")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()

    return True


def _save_phase_breakdown_plot(
    summary: pd.DataFrame,
    method: str,
    base_ratio: float,
    out_path: Path,
) -> bool:
    """
    生成分阶段耗时堆叠图。

    使用np.arange(len(d))作为分类位置，再把total_ids设置为刻度标签，
    避免以1000、5000等大数值直接作为柱状图坐标时柱体过窄。
    """
    method = _normalize_method_name(method)
    d = summary[
        (summary["intersection_ratio"] == base_ratio)
        & (summary["method"] == method)
    ].copy()

    if d.empty:
        return False

    d = d.sort_values("total_ids")

    if method == METHOD_ECDH:
        phase_cols = [
            ("phase_map_ms_mean", "映射"),
            ("phase_blind_ms_mean", "盲化"),
            ("phase_compare_ms_mean", "比较"),
        ]
        title = f"ECDH PSI分阶段耗时结构（交集比例={base_ratio}）"

    elif method == METHOD_SOCKET_ECDH:
        phase_cols = [
            ("phase_blind_a_ms_mean", "A侧盲化"),
            ("phase_blind_b_ms_mean", "B侧处理"),
            ("phase_blind_back_ms_mean", "回传盲化"),
            ("phase_compare_ms_mean", "比较"),
        ]
        title = f"Socket ECDH PSI分阶段耗时结构（交集比例={base_ratio}）"

    else:
        return False

    for col, _ in phase_cols:
        if col not in d.columns:
            d[col] = 0.0
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)

    x = np.arange(len(d))
    labels = d["total_ids"].astype(str).tolist()

    bottoms = np.zeros(len(d), dtype=float)

    plt.figure(figsize=(10, 5.5))

    for col, label in phase_cols:
        values = d[col].to_numpy(dtype=float)
        plt.bar(
            x,
            values,
            bottom=bottoms,
            width=0.55,
            label=label,
        )
        bottoms += values

    for xi, total in zip(x, bottoms):
        if total > 0:
            plt.text(
                xi,
                total,
                f"{total:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    plt.xticks(x, labels)
    plt.xlabel("数据规模（条）")
    plt.ylabel("分阶段耗时均值（ms）")
    plt.title(title)
    plt.grid(True, axis="y", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()

    return True


def generate_plots(
    summary: pd.DataFrame,
    total_ids_list: list[int],
    intersection_ratios: list[float],
    methods: list[str],
    out_dir: Path,
    comm_detail: pd.DataFrame | None = None,
) -> dict[str, str]:
    """生成论文所需实验图。"""
    out_paths: dict[str, str] = {}

    if not total_ids_list:
        raise ValueError("total_ids_list不能为空")
    if not intersection_ratios:
        raise ValueError("intersection_ratios不能为空")

    base_ratio = intersection_ratios[0]
    base_total_ids = total_ids_list[-1]

    fig1 = out_dir / "benchmark_by_size.png"
    _save_grouped_bar_by_total_ids(summary, methods, base_ratio, fig1)
    out_paths["benchmark_by_size"] = str(fig1)

    # 兼容原目录里已有benchmark_result.png的论文插图路径。
    fig1_alias = out_dir / "benchmark_result.png"
    try:
        shutil.copyfile(fig1, fig1_alias)
        out_paths["benchmark_result"] = str(fig1_alias)
    except Exception:
        pass

    fig2 = out_dir / "benchmark_by_ratio.png"
    _save_grouped_bar_by_ratio(summary, methods, base_total_ids, fig2)
    out_paths["benchmark_by_ratio"] = str(fig2)

    fig3 = out_dir / "benchmark_comm_bytes_by_size.png"
    if METHOD_SOCKET_ECDH in methods:
        ok = _save_comm_bytes_plot(summary, base_ratio, fig3, comm_detail=comm_detail)
        if ok:
            out_paths["benchmark_comm_bytes_by_size"] = str(fig3)

    fig4 = out_dir / "benchmark_phase_breakdown_ecdh.png"
    ok = _save_phase_breakdown_plot(summary, METHOD_ECDH, base_ratio, fig4)
    if ok:
        out_paths["benchmark_phase_breakdown_ecdh"] = str(fig4)

    fig5 = out_dir / "benchmark_phase_breakdown_socket_ecdh.png"
    if METHOD_SOCKET_ECDH in methods:
        ok = _save_phase_breakdown_plot(summary, METHOD_SOCKET_ECDH, base_ratio, fig5)
        if ok:
            out_paths["benchmark_phase_breakdown_socket_ecdh"] = str(fig5)

    return out_paths


# ============================================================
# 主benchmark流程
# ============================================================

def run_benchmark(
    sizes: list[int] | None = None,
    intersection_ratios: list[float] | None = None,
    repeats: int = 1,
    include_socket: bool = True,
    seed: int = 2026,
    out_dir: str | None = None,
    comm_sizes: list[int] | None = None,
):
    """
    多维评测：
    1.数据规模total_ids
    2.交集比例intersection_ratio
    3.重复实验repeats
    4.输出detail/summary/paper_table/meta/图表
    """
    if sizes is None:
        sizes = [1000, 5000]
    if intersection_ratios is None:
        intersection_ratios = [0.01, 0.1]

    if repeats <= 0:
        raise ValueError("repeats必须大于0")

    if comm_sizes is None:
        comm_sizes = _default_comm_sizes(sizes)
    else:
        comm_sizes = sorted({int(size) for size in comm_sizes if int(size) > 0})

    out_path = Path(out_dir).resolve() if out_dir else EVAL_DIR
    out_path.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tmp_a = DATA_DIR / "bench_A.csv"
    tmp_b = DATA_DIR / "bench_B.csv"

    methods = METHODS_WITH_SOCKET.copy() if include_socket else METHODS_BASE.copy()

    meta = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version.split()[0],
        "python_full": sys.version,
        "platform": platform.platform(),
        "working_directory": os.getcwd(),
        "project_root": str(ROOT_DIR),
        "eval_dir": str(EVAL_DIR),
        "data_dir": str(DATA_DIR),
        "params": {
            "total_ids_list": sizes,
            "intersection_ratios": intersection_ratios,
            "repeats": repeats,
            "include_socket": include_socket,
            "seed": seed,
            "methods": methods,
            "comm_sizes": comm_sizes if include_socket else [],
            "method_display": METHOD_DISPLAY,
        },
        "field_notes": {
            "total_ids": "输入集合规模，对应论文中的数据规模。",
            "intersection_ratio": "预设交集比例。",
            "expected_intersection_size": "数据生成阶段预设的交集规模。",
            "actual_intersection_size": "PSI方法实际输出的交集规模。",
            "is_correct": "actual_intersection_size是否等于expected_intersection_size。",
            "protocol_elapsed_ms": "方法内部统计的协议核心耗时，单位ms。",
            "end_to_end_elapsed_ms": "从外部调用开始到结束的端到端耗时，单位ms。",
            "comm_bytes": "A、B两端发送与接收字节数之和；hash_baseline、DH PSI和ECDH PSI为协议逻辑通信量估算，Socket ECDH PSI为实际Socket收发统计。",
            "phase_map_ms": "ECDH PSI中标识映射或曲线点构造阶段耗时。",
            "phase_blind_ms": "ECDH PSI中盲化阶段耗时。",
            "phase_blind_a_ms": "Socket ECDH PSI中A侧第一轮盲化相关耗时。",
            "phase_blind_b_ms": "Socket ECDH PSI中B侧第一轮/第二轮处理相关耗时。",
            "phase_blind_back_ms": "Socket ECDH PSI中回传盲化相关耗时。",
            "phase_compare_ms": "集合比较阶段耗时。",
        },
        "dependencies": _dep_versions(),
    }

    write_run_meta(out_path, meta)

    rows: list[dict[str, Any]] = []

    print("=== 性能评测开始 ===")
    print(f"输出目录:{out_path}")
    print(f"数据规模total_ids:{sizes}")
    print(f"交集比例intersection_ratios:{intersection_ratios}")
    print(f"重复次数repeats:{repeats}")
    print(f"随机种子seed:{seed}")
    print(f"方法methods:{methods}\n")

    for total_ids in sizes:
        for ratio in intersection_ratios:
            for run_idx in range(repeats):
                run_seed = seed + total_ids * 13 + int(ratio * 10000) * 17 + run_idx

                _, _, expected = generate_pair_data(
                    total_ids=total_ids,
                    intersection_ratio=ratio,
                    seed=run_seed,
                    party_a_name="bench_A",
                    party_b_name="bench_B",
                )

                _move_generated_bench_files(DATA_DIR, tmp_a, tmp_b)

                expected_intersection_size = _safe_len(expected)

                for method in methods:
                    method = _normalize_method_name(method)
                    begin = time.perf_counter()

                    result = _run_one_method(method, str(tmp_a), str(tmp_b))
                    intersection_ids, elapsed_seconds, raw_stats = _extract_method_result(result)

                    norm = normalize_psi_stats(raw_stats, method=method)
                    if method != METHOD_SOCKET_ECDH and norm["comm_bytes"] == 0.0:
                        norm["comm_bytes"] = _estimate_protocol_comm_bytes(
                            method=method,
                            size_a=total_ids,
                            size_b=total_ids,
                        )
                    end_to_end_elapsed_ms = (time.perf_counter() - begin) * 1000.0

                    actual_intersection_size = _safe_len(intersection_ids)
                    is_correct = actual_intersection_size == expected_intersection_size

                    row: dict[str, Any] = {
                        "total_ids": total_ids,
                        "intersection_ratio": ratio,
                        "run_idx": run_idx,
                        "seed": run_seed,
                        "method": method,
                        "method_display": _method_label(method),
                        "expected_intersection_size": expected_intersection_size,
                        "actual_intersection_size": actual_intersection_size,
                        "is_correct": is_correct,
                        "protocol_elapsed_ms": elapsed_seconds * 1000.0,
                        "end_to_end_elapsed_ms": end_to_end_elapsed_ms,
                    }

                    row.update(norm)
                    rows.append(row)

                    flag = "OK" if is_correct else "WARN"
                    print(
                        f"[{flag}] "
                        f"total_ids={total_ids:<7} ratio={ratio:<6} run={run_idx:<3} "
                        f"method={method:<13} "
                        f"intersection={actual_intersection_size:<6}/{expected_intersection_size:<6} "
                        f"protocol_ms={elapsed_seconds * 1000.0:>10.2f} "
                        f"e2e_ms={end_to_end_elapsed_ms:>10.2f}"
                    )

    detail = pd.DataFrame(rows)

    # 统一补齐数值列，避免某些方法没有stats字段导致后续groupby或画图失败。
    detail_numeric_cols = [*CANON_STAT_KEYS]
    detail = _ensure_numeric_columns(detail, detail_numeric_cols)

    # 规范列顺序，避免CSV字段混乱。
    detail_cols = [
        "total_ids",
        "intersection_ratio",
        "run_idx",
        "seed",
        "method",
        "method_display",
        "expected_intersection_size",
        "actual_intersection_size",
        "is_correct",
        "protocol_elapsed_ms",
        "end_to_end_elapsed_ms",
        *CANON_STAT_KEYS,
    ]
    detail = detail[[col for col in detail_cols if col in detail.columns]]

    detail_csv = out_path / "benchmark_detail.csv"
    detail.to_csv(detail_csv, index=False, encoding="utf-8-sig")

    summary = build_summary(detail)
    summary_csv = out_path / "benchmark_summary.csv"
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    average_csv = ROOT_DIR / "average.csv"
    summary.to_csv(average_csv, index=False, encoding="utf-8-sig")

    paper_table = build_paper_table(summary)
    paper_table_csv = out_path / "benchmark_table4_1.csv"
    paper_table.to_csv(paper_table_csv, index=False, encoding="utf-8-sig")

    comm_detail = pd.DataFrame()
    if include_socket and comm_sizes:
        comm_detail = _run_socket_comm_detail(
            comm_sizes=comm_sizes,
            base_ratio=intersection_ratios[0],
            repeats=repeats,
            seed=seed,
            tmp_a=tmp_a,
            tmp_b=tmp_b,
        )
        if not comm_detail.empty:
            comm_detail_csv = out_path / "benchmark_comm_detail.csv"
            comm_detail.to_csv(comm_detail_csv, index=False, encoding="utf-8-sig")
        else:
            comm_detail_csv = None
    else:
        comm_detail_csv = None

    plot_paths = generate_plots(
        summary=summary,
        total_ids_list=sizes,
        intersection_ratios=intersection_ratios,
        methods=methods,
        out_dir=out_path,
        comm_detail=comm_detail,
    )

    print("\n=== 评测完成 ===")
    print(f"运行元数据:{out_path / 'run_meta.json'}")
    print(f"明细结果:{detail_csv}")
    print(f"汇总结果:{summary_csv}")
    print(f"均值结果:{average_csv}")
    print(f"论文表4.1:{paper_table_csv}")
    if comm_detail_csv is not None:
        print(f"Socket通信量采样:{comm_detail_csv}")

    for name, path in plot_paths.items():
        print(f"图表{name}:{path}")

    wrong = detail[detail["is_correct"] == False]
    if not wrong.empty:
        print("\n[WARN]存在交集规模不一致的实验记录，请检查benchmark_detail.csv:")
        print(
            wrong[
                [
                    "total_ids",
                    "intersection_ratio",
                    "run_idx",
                    "method",
                    "expected_intersection_size",
                    "actual_intersection_size",
                ]
            ].to_string(index=False)
        )

    return detail, summary, paper_table


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    args = build_parser().parse_args()

    run_benchmark(
        sizes=_parse_int_list(args.sizes),
        intersection_ratios=_parse_float_list(args.ratios),
        repeats=args.repeats,
        include_socket=args.include_socket,
        seed=args.seed,
        out_dir=args.out_dir,
        comm_sizes=_parse_int_list(args.comm_sizes) if args.comm_sizes else None,
    )
