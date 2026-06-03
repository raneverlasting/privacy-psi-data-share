from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


EVAL_DIR = Path(__file__).resolve().parent
ROOT_DIR = EVAL_DIR.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(EVAL_DIR))

from data.generate_data import generate_pair_data
from psi.ecdh_psi import ecdh_psi
from psi.socket_ecdh_psi import socket_ecdh_psi
from stats_schema import normalize_psi_stats


METHODS = [
    ("ECDH PSI", "ecdh", ecdh_psi),
    ("Socket ECDH PSI", "socket_ecdh", socket_ecdh_psi),
]

POINT_BYTES = 33


def _estimate_ecdh_comm_bytes(total_ids: int) -> float:
    """ECDH PSI逻辑通信量估算，采用A、B两端发送与接收字节数之和。"""
    wire_bytes = (2 * total_ids + total_ids) * POINT_BYTES
    return float(2 * wire_bytes)


def _parse_int_list(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def run_reproduction(
    sizes: list[int],
    ratio: float,
    repeats: int,
    seed: int,
    out_detail: Path,
    out_average: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []

    for total_ids in sizes:
        for run_idx in range(repeats):
            run_seed = seed + total_ids * 13 + int(ratio * 10000) * 17 + run_idx
            df_a, df_b, expected = generate_pair_data(
                total_ids=total_ids,
                intersection_ratio=ratio,
                seed=run_seed,
                party_a_name="reproduce_A",
                party_b_name="reproduce_B",
            )

            path_a = EVAL_DIR / f"reproduce_A_{total_ids}_{run_idx}.csv"
            path_b = EVAL_DIR / f"reproduce_B_{total_ids}_{run_idx}.csv"
            df_a.to_csv(path_a, index=False)
            df_b.to_csv(path_b, index=False)

            expected_size = len(expected)

            for display, method, fn in METHODS:
                result = fn(str(path_a), str(path_b), return_stats=True)
                intersection_ids, elapsed_seconds, raw_stats = result
                stats = normalize_psi_stats(raw_stats, method=method)
                comm_bytes = stats["comm_bytes"]
                if method == "ecdh" and comm_bytes == 0.0:
                    comm_bytes = _estimate_ecdh_comm_bytes(total_ids)

                actual_size = len(intersection_ids)
                is_correct = actual_size == expected_size

                rows.append(
                    {
                        "方法": display,
                        "数据规模/条": total_ids,
                        "交集比例": ratio,
                        "运行轮次": run_idx,
                        "交集规模/条": actual_size,
                        "协议耗时/ms": elapsed_seconds * 1000.0,
                        "通信量/byte": comm_bytes,
                        "校验结果": "通过" if is_correct else "未通过",
                    }
                )

                flag = "OK" if is_correct else "WARN"
                print(
                    f"[{flag}] total_ids={total_ids:<5} ratio={ratio:<4} "
                    f"run={run_idx:<2} method={method:<11} "
                    f"intersection={actual_size}/{expected_size} "
                    f"protocol_ms={elapsed_seconds * 1000.0:.2f} "
                    f"comm_bytes={comm_bytes:.0f}"
                )

            path_a.unlink(missing_ok=True)
            path_b.unlink(missing_ok=True)

    detail = pd.DataFrame(rows)
    detail["协议耗时/ms"] = detail["协议耗时/ms"].round(2)
    detail["通信量/byte"] = detail["通信量/byte"].round(0).astype(int)

    average = (
        detail.groupby(["方法", "数据规模/条", "交集比例"], as_index=False)
        .agg(
            **{
                "交集规模/条": ("交集规模/条", "mean"),
                "协议耗时/ms": ("协议耗时/ms", "mean"),
                "通信量/byte": ("通信量/byte", "mean"),
                "校验结果": ("校验结果", lambda s: "通过" if (s == "通过").all() else "未通过"),
            }
        )
        .sort_values(["数据规模/条", "方法"])
    )
    average["交集规模/条"] = average["交集规模/条"].round(0).astype(int)
    average["协议耗时/ms"] = average["协议耗时/ms"].round(2)
    average["通信量/byte"] = average["通信量/byte"].round(0).astype(int)

    out_detail.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_detail, index=False, encoding="utf-8-sig")
    average.to_csv(out_average, index=False, encoding="utf-8-sig")

    print(f"\n明细结果:{out_detail}")
    print(f"均值结果:{out_average}")

    return detail, average


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="复现ECDH PSI和Socket ECDH PSI两组实验数据")
    parser.add_argument("--sizes", default="1000,5000", help="数据规模列表，默认1000,5000")
    parser.add_argument("--ratio", type=float, default=0.01, help="交集比例，默认0.01")
    parser.add_argument("--repeats", type=int, default=5, help="每组重复次数，默认5")
    parser.add_argument("--seed", type=int, default=2026, help="基础随机种子，默认2026")
    parser.add_argument(
        "--out-detail",
        default=str(EVAL_DIR / "reproduce_ecdh_socket.csv"),
        help="明细CSV输出路径",
    )
    parser.add_argument(
        "--out-average",
        default=str(EVAL_DIR / "reproduce_ecdh_socket_average.csv"),
        help="均值CSV输出路径",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    run_reproduction(
        sizes=_parse_int_list(args.sizes),
        ratio=args.ratio,
        repeats=args.repeats,
        seed=args.seed,
        out_detail=Path(args.out_detail),
        out_average=Path(args.out_average),
    )
