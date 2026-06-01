import os

import numpy as np
import pandas as pd


def _normalize_ids(ids: list[str]) -> list[str]:
    """统一把 uid 转成去除首尾空白的字符串，避免 CSV 读写后口径不一致。"""
    return [str(x).strip() for x in ids]


def _build_party_df(ids: list[str], rng: np.random.Generator) -> pd.DataFrame:
    """
    构造单方模拟数据。

    user_id：参与 PSI 求交的唯一标识字段；
    risk_level / risk_score / fraud_count / risk_bucket：仅用于交集后的本地统计。
    """
    ids = _normalize_ids(ids)
    total_ids = len(ids)

    risk_levels = rng.choice([1, 2, 3], size=total_ids, p=[0.5, 0.3, 0.2])

    fraud_counts = np.where(
        risk_levels == 3,
        rng.integers(3, 10, total_ids),
        np.where(
            risk_levels == 2,
            rng.integers(1, 4, total_ids),
            rng.integers(0, 2, total_ids),
        ),
    )

    base_scores = {1: (10, 40), 2: (40, 70), 3: (70, 100)}
    scores = np.array(
        [rng.integers(base_scores[int(lvl)][0], base_scores[int(lvl)][1]) for lvl in risk_levels],
        dtype=np.int64,
    )

    # 与论文中的 risk_bucket 字段对应：按照 risk_score 区间映射得到风险分桶。
    risk_bucket = np.where(
        scores < 40,
        "low",
        np.where(scores < 70, "mid", "high"),
    )

    return pd.DataFrame(
        {
            "user_id": ids,
            "risk_level": risk_levels,
            "fraud_count": fraud_counts,
            "risk_score": scores,
            "risk_bucket": risk_bucket,
        }
    )


def _sample_user_ids(total_ids: int, id_pool_size: int, rng: np.random.Generator) -> list[str]:
    if total_ids <= 0:
        raise ValueError("total_ids 必须为正整数")
    if id_pool_size < total_ids:
        raise ValueError("id_pool_size 不能小于 total_ids")

    picked = rng.choice(np.arange(1, id_pool_size + 1), size=total_ids, replace=False)
    return [f"USER_{int(i):06d}" for i in picked]


def generate_party_data(
    party_name: str,
    total_ids: int,
    seed: int | None = None,
    id_pool_size: int = 200000,
    user_ids: list[str] | None = None,
    save: bool = True,
    output_path: str | None = None,
):
    """
    生成单方模拟数据（兼容旧接口）。

    字段说明：
    - user_id：参与 PSI 求交；
    - risk_score / fraud_count / risk_bucket：用于交集上的本地统计；
    - risk_level：保留原有字段，兼容 secure_aggregation 明文演示函数。
    """
    rng = np.random.default_rng(seed)

    ids = user_ids if user_ids is not None else _sample_user_ids(total_ids, id_pool_size, rng)
    ids = _normalize_ids(ids)

    if len(ids) != total_ids:
        raise ValueError(f"user_ids 数量应为 total_ids={total_ids}，实际为 {len(ids)}")
    if len(set(ids)) != len(ids):
        raise ValueError("user_ids 中存在重复 uid，无法保证实验数据口径")

    df = _build_party_df(ids, rng)

    if save:
        if output_path is None:
            output_path = os.path.join(os.path.dirname(__file__), f"party_{party_name}.csv")
        df.to_csv(output_path, index=False)
        print(f"{party_name}方数据生成完成：{len(df)} 条记录 -> {output_path}")

    return df


def generate_pair_data(
    total_ids: int,
    intersection_ratio: float = 0.01,
    seed: int = 42,
    id_pool_size: int | None = None,
    party_a_name: str = "A",
    party_b_name: str = "B",
):
    """
    联合生成两方数据，可控制交集比例，适用于大规模实验。

    与论文算法 3-1 对应：
    intersection_size = floor(total_ids × intersection_ratio)
    X = I ∪ U_A
    Y = I ∪ U_B
    """
    if total_ids <= 0:
        raise ValueError("total_ids 必须为正整数")
    if not (0 <= intersection_ratio <= 1):
        raise ValueError("intersection_ratio 必须在 [0, 1] 区间内")

    # 与论文公式保持一致：floor(total_ids × r)。
    intersection_size = int(np.floor(total_ids * intersection_ratio))

    unique_a_size = total_ids - intersection_size
    unique_b_size = total_ids - intersection_size

    # 需要同时容纳：公共交集 I、A 方独有 U_A、B 方独有 U_B。
    min_pool = intersection_size + unique_a_size + unique_b_size

    if id_pool_size is None:
        id_pool_size = max(200000, min_pool * 2)
    if id_pool_size < min_pool:
        raise ValueError("id_pool_size 过小，无法满足给定规模与交集比例")

    rng_global = np.random.default_rng(seed)

    sampled = rng_global.choice(np.arange(1, id_pool_size + 1), size=min_pool, replace=False)
    sampled_ids = [f"USER_{int(i):06d}" for i in sampled]

    shared_ids = sampled_ids[:intersection_size]
    unique_a_ids = sampled_ids[intersection_size : intersection_size + unique_a_size]
    unique_b_ids = sampled_ids[intersection_size + unique_a_size :]

    # 构造 X = I ∪ U_A，Y = I ∪ U_B。
    ids_a = shared_ids + unique_a_ids
    ids_b = shared_ids + unique_b_ids

    rng_global.shuffle(ids_a)
    rng_global.shuffle(ids_b)

    path_a = os.path.join(os.path.dirname(__file__), f"party_{party_a_name}.csv")
    path_b = os.path.join(os.path.dirname(__file__), f"party_{party_b_name}.csv")

    df_a = generate_party_data(
        party_a_name,
        total_ids=total_ids,
        seed=seed + 1,
        user_ids=ids_a,
        save=True,
        output_path=path_a,
    )
    df_b = generate_party_data(
        party_b_name,
        total_ids=total_ids,
        seed=seed + 2,
        user_ids=ids_b,
        save=True,
        output_path=path_b,
    )

    # 显式一致性校验：支撑论文中的“可控交集比例”和“系统一致性校验”。
    set_a = set(df_a["user_id"].astype(str))
    set_b = set(df_b["user_id"].astype(str))
    actual_intersection = set_a & set_b

    assert len(df_a) == total_ids, "A 方数据规模不等于 total_ids"
    assert len(df_b) == total_ids, "B 方数据规模不等于 total_ids"
    assert len(set_a) == total_ids, "A 方 user_id 存在重复"
    assert len(set_b) == total_ids, "B 方 user_id 存在重复"
    assert len(actual_intersection) == intersection_size, (
        f"实际交集规模 {len(actual_intersection)} 与预设交集规模 {intersection_size} 不一致"
    )

    # 返回 shared_ids，保持旧 benchmark.py 的 expected_intersection 口径不变。
    return df_a, df_b, shared_ids


if __name__ == "__main__":
    df_a, df_b, expected = generate_pair_data(
        total_ids=1000,
        intersection_ratio=0.004,
        seed=2026,
        party_a_name="A",
        party_b_name="B",
    )

    print("\n--- 机构A 数据预览 ---")
    print(df_a.head())
    print("\n--- 机构B 数据预览 ---")
    print(df_b.head())

    intersection = set(df_a["user_id"].astype(str)) & set(df_b["user_id"].astype(str))
    print(f"\n理论交集大小：{len(intersection)} 个共同用户")
    print(f"预期交集大小：{len(expected)}")