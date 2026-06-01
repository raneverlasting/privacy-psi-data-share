import argparse
import os
import sys

# 把项目根目录加入路径，保证从任意入口运行时都能导入项目模块。
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from aggregation.secure_agg import secure_aggregation, secure_aggregation_additive
from baseline.hash_psi import hash_psi
from data.generate_data import generate_pair_data
from psi.dh_psi import dh_psi
from psi.ecdh_psi import ecdh_psi
from psi.socket_ecdh_psi import socket_ecdh_psi


def _validate_same_intersection(name_a: str, inter_a: list, name_b: str, inter_b: list) -> None:
    """
    校验两种PSI方法得到的交集集合是否一致。

    该函数用于主流程验收，不参与协议计算本身。
    """
    sa = set(map(str, inter_a))
    sb = set(map(str, inter_b))

    if sa != sb:
        only_a = sorted(list(sa - sb))[:5]
        only_b = sorted(list(sb - sa))[:5]
        raise ValueError(
            f"{name_a}与{name_b}交集结果不一致："
            f"{name_a}-only示例={only_a}，{name_b}-only示例={only_b}"
        )


def _validate_expected_intersection(method_name: str, inter: list, expected_intersection: list) -> None:
    """
    校验某个PSI方法输出的交集规模是否与数据生成阶段预设交集规模一致。
    """
    expected_size = len(expected_intersection)
    actual_size = len(inter)

    if actual_size != expected_size:
        raise ValueError(
            f"{method_name}输出交集规模与预设不一致："
            f"actual={actual_size}, expected={expected_size}"
        )


def _format_ms(seconds: float | None) -> str:
    """把秒转换成毫秒字符串。"""
    if seconds is None:
        return "-"
    return f"{seconds * 1000:.2f}"


def build_parser() -> argparse.ArgumentParser:
    """
    构造命令行参数解析器。
    """
    parser = argparse.ArgumentParser(
        description="面向跨机构金融风控的隐私保护数据共享原型系统（PSI+交集统计）"
    )

    parser.add_argument(
        "--total-ids",
        type=int,
        default=1000,
        help="两方各自数据规模，默认1000",
    )

    parser.add_argument(
        "--intersection-ratio",
        type=float,
        default=0.004,
        help="交集比例，默认0.004",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="随机种子，默认2026",
    )

    parser.add_argument(
        "--skip-socket",
        action="store_true",
        help="跳过Socket ECDH PSI工程通信版本",
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="关闭不同PSI方法交集一致性校验，默认开启校验",
    )

    parser.add_argument(
        "--skip-plain-agg",
        action="store_true",
        help="跳过明文统计演示，仅运行可加统计掩码合成流程",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print("=" * 68)
    print("  面向跨机构金融风控的隐私保护数据共享原型系统")
    print("  流程：数据生成→PSI隐私对齐→交集统计→结果汇总")
    print("=" * 68)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    path_a = os.path.join(data_dir, "party_A.csv")
    path_b = os.path.join(data_dir, "party_B.csv")

    # ────────────────────────────────────────
    # 第一步：生成模拟数据
    # ────────────────────────────────────────
    print("\n【第一步】生成两方模拟数据")
    print("-" * 50)

    _, _, expected_intersection = generate_pair_data(
        total_ids=args.total_ids,
        intersection_ratio=args.intersection_ratio,
        seed=args.seed,
        party_a_name="A",
        party_b_name="B",
    )

    print(f"单方数据规模：{args.total_ids}")
    print(f"预设交集比例：{args.intersection_ratio}")
    print(f"预设交集规模：{len(expected_intersection)}")

    # ────────────────────────────────────────
    # 第二步：哈希基线方案
    # ────────────────────────────────────────
    print("\n【第二步】运行哈希基线方案（不安全，仅作性能对照）")
    print("-" * 50)

    hash_intersection, t_hash = hash_psi(path_a, path_b)

    # ────────────────────────────────────────
    # 第三步：DH PSI
    # ────────────────────────────────────────
    print("\n【第三步】运行DH PSI（大整数模幂对照方案）")
    print("-" * 50)

    dh_intersection, t_dh = dh_psi(path_a, path_b)

    # ────────────────────────────────────────
    # 第四步：ECDH PSI
    # ────────────────────────────────────────
    print("\n【第四步】运行ECDH PSI（主要求交路线）")
    print("-" * 50)

    ecdh_intersection, t_ecdh = ecdh_psi(path_a, path_b)

    # ────────────────────────────────────────
    # 第五步：Socket ECDH PSI
    # ────────────────────────────────────────
    socket_intersection = None
    t_socket = None

    if not args.skip_socket:
        print("\n【第五步】运行Socket ECDH PSI（工程通信版本）")
        print("-" * 50)

        socket_intersection, t_socket = socket_ecdh_psi(path_a, path_b)
    else:
        print("\n【第五步】Socket ECDH PSI：已跳过")
        print("-" * 50)

    # ────────────────────────────────────────
    # 第六步：一致性校验
    # ────────────────────────────────────────
    if not args.no_validate:
        print("\n【第六步】交集结果一致性校验")
        print("-" * 50)

        _validate_expected_intersection("哈希基线", hash_intersection, expected_intersection)
        _validate_expected_intersection("DH PSI", dh_intersection, expected_intersection)
        _validate_expected_intersection("ECDH PSI", ecdh_intersection, expected_intersection)

        _validate_same_intersection("哈希基线", hash_intersection, "DH PSI", dh_intersection)
        _validate_same_intersection("哈希基线", hash_intersection, "ECDH PSI", ecdh_intersection)

        if socket_intersection is not None:
            _validate_expected_intersection("Socket ECDH PSI", socket_intersection, expected_intersection)
            _validate_same_intersection("哈希基线", hash_intersection, "Socket ECDH PSI", socket_intersection)

        print("一致性校验通过：各PSI方法输出交集规模和交集集合一致。")
    else:
        print("\n【第六步】交集结果一致性校验：已关闭")

    # ────────────────────────────────────────
    # 第七步：交集上的联合统计与可加统计聚合
    # ────────────────────────────────────────
    print("\n【第七步】在交集结果上进行联合统计与可加统计聚合")
    print("-" * 50)

    print("\n（1）可加统计掩码合成流程")
    _ = secure_aggregation_additive(path_a, path_b, ecdh_intersection)

    if not args.skip_plain_agg:
        print("\n（2）明文统计演示流程")
        print("说明：该流程用于展示交集统计口径，非安全聚合主流程。")
        _ = secure_aggregation(path_a, path_b, ecdh_intersection)
    else:
        print("\n（2）明文统计演示流程：已跳过")

    # ────────────────────────────────────────
    # 第八步：方案对比总结
    # ────────────────────────────────────────
    print("\n【第八步】方案对比总结")
    print("-" * 68)
    print(f"{'方案':<22} {'交集大小':<12} {'耗时/ms':<14} {'说明'}")
    print("-" * 68)
    print(f"{'哈希基线':<22} {len(hash_intersection):<12} {_format_ms(t_hash):<14} 不安全性能基线")
    print(f"{'DH PSI':<22} {len(dh_intersection):<12} {_format_ms(t_dh):<14} 大整数模幂对照方案")
    print(f"{'ECDH PSI':<22} {len(ecdh_intersection):<12} {_format_ms(t_ecdh):<14} 主要求交路线")

    if socket_intersection is None:
        print(f"{'Socket ECDH PSI':<22} {'-':<12} {'-':<14} 已跳过")
    else:
        print(
            f"{'Socket ECDH PSI':<22} "
            f"{len(socket_intersection):<12} "
            f"{_format_ms(t_socket):<14} "
            f"工程通信版本"
        )

    print("\n结论：该原型以PSI完成跨机构高风险用户标识的隐私对齐，")
    print("      并在交集对象上输出约定范围内的统计结果，")
    print("      用于支撑论文中的方案设计、工程实现和实验评测。")

    print("\n" + "=" * 68)
    print("  原型系统运行完毕")
    print("=" * 68)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
