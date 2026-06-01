import os
import secrets

import numpy as np
import pandas as pd


def _additive_two_party_scalar(va: int, vb: int) -> int:
    """
    两方标量掩码合成流程。

    与论文公式保持一致：
    m = v_A + r
    t = m + v_B
    v = t - r = v_A + v_B

    说明：
    本函数在单进程中演示两方掩码合成的计算关系；
    分布式部署时，m、t 可分别作为协议消息在双方之间传递。
    """
    va = int(va)
    vb = int(vb)

    r = secrets.randbelow(1 << 128)

    m = va + r
    t = m + vb
    v = t - r

    return int(v)


def _additive_two_party_vec(v_a: np.ndarray, v_b: np.ndarray) -> np.ndarray:
    """
    两方向量掩码合成流程。

    对统计向量逐维执行：
    m = v_A + r
    t = m + v_B
    v = t - r
    """
    if v_a.shape != v_b.shape:
        raise ValueError("v_a 与 v_b 的向量维度必须一致")

    va = v_a.astype(np.int64)
    vb = v_b.astype(np.int64)

    r = np.array(
        [secrets.randbelow(1 << 31) for _ in range(va.size)],
        dtype=np.int64,
    )

    m = va + r
    t = m + vb
    v = t - r

    return v.astype(np.int64)


def _normalize_intersection_ids(intersection_ids: list) -> list[str]:
    """统一交集 uid 格式，并保持原有顺序去重。"""
    seen = set()
    out = []
    for uid in intersection_ids:
        s = str(uid).strip()
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def secure_aggregation_additive(
    path_a: str,
    path_b: str,
    intersection_ids: list,
    score_col: str = "risk_score",
    fraud_col: str = "fraud_count",
):
    """
    交集上的可加统计与两方掩码合成。

    统计内容：
    1. 交集规模；
    2. 两方风险评分总和；
    3. 两方欺诈次数总和；
    4. 两方风险评分分桶计数。

    注意：
    本函数只处理计数、求和、分桶计数等可加统计。
    max、排序、Top-k、逐用户比较等非线性统计不属于该函数的安全聚合范围。
    """
    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入 CSV 必须包含 user_id 字段")

    ids = _normalize_intersection_ids(intersection_ids)
    uid_set = set(ids)

    df_a["user_id"] = df_a["user_id"].astype(str).str.strip()
    df_b["user_id"] = df_b["user_id"].astype(str).str.strip()

    inter_a = df_a[df_a["user_id"].isin(uid_set)].copy()
    inter_b = df_b[df_b["user_id"].isin(uid_set)].copy()

    n = len(ids)

    sum_score_a = int(inter_a[score_col].sum()) if score_col in inter_a.columns else 0
    sum_score_b = int(inter_b[score_col].sum()) if score_col in inter_b.columns else 0

    sum_fraud_a = int(inter_a[fraud_col].sum()) if fraud_col in inter_a.columns else 0
    sum_fraud_b = int(inter_b[fraud_col].sum()) if fraud_col in inter_b.columns else 0

    bins = [0, 40, 70, 100]
    labels = ["低(0-40)", "中(40-70)", "高(70-100)"]

    def bucket_counts(df: pd.DataFrame) -> np.ndarray:
        if score_col not in df.columns or len(df) == 0:
            return np.zeros(3, dtype=np.int64)

        s = pd.cut(
            df[score_col],
            bins=bins,
            labels=labels,
            include_lowest=True,
        )
        vc = s.value_counts().reindex(labels, fill_value=0)
        return np.array([int(vc[label]) for label in labels], dtype=np.int64)

    bc_a = bucket_counts(inter_a)
    bc_b = bucket_counts(inter_b)

    # 标量可加统计。
    total_sum_score = _additive_two_party_scalar(sum_score_a, sum_score_b)
    total_fraud = _additive_two_party_scalar(sum_fraud_a, sum_fraud_b)

    # 分桶计数向量。
    total_bucket = _additive_two_party_vec(bc_a, bc_b)

    # 两方都有交集记录时，风险评分记录数为 2*n。
    mean_over_records = (total_sum_score / (2 * n)) if n > 0 else 0.0

    print("=== 安全聚合（两方加法掩码，可加统计量）===")
    print(f"交集用户数（去重）：{n}")
    print(f"A 方交集记录数：{len(inter_a)}")
    print(f"B 方交集记录数：{len(inter_b)}")
    print(f"风险评分总和（两方记录相加）：{total_sum_score}")
    print(f"平均风险评分（两方记录均值）：{mean_over_records:.4f}")
    print(f"欺诈次数总和（两方相加）：{total_fraud}")
    print("综合评分区间人数（两方分桶计数相加）：")
    for lab, c in zip(labels, total_bucket.tolist()):
        print(f"   {lab}：{int(c)} 人次")
    print("\n说明：本函数只覆盖可加统计；max、排序、Top-k 等非线性任务未纳入本流程。")

    return {
        "intersection_size": n,
        "sum_risk_score_two_party": total_sum_score,
        "mean_risk_score_over_records": mean_over_records,
        "sum_fraud_count_two_party": total_fraud,
        "bucket_labels": labels,
        "bucket_counts_two_party": total_bucket.tolist(),
    }


def secure_aggregation(path_a: str, path_b: str, intersection_ids: list):
    """
    明文统计演示版：用于展示交集上的统计口径与输出形态。

    注意：
    本函数会在本地明文合并交集记录，包含 max_risk 等非线性统计。
    它不是论文中的安全聚合主流程。
    论文中与两方掩码合成对应的函数是 secure_aggregation_additive。
    """
    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入 CSV 必须包含 user_id 字段")

    ids = _normalize_intersection_ids(intersection_ids)

    df_a["user_id"] = df_a["user_id"].astype(str).str.strip()
    df_b["user_id"] = df_b["user_id"].astype(str).str.strip()

    inter_a = df_a[df_a["user_id"].isin(ids)].copy()
    inter_b = df_b[df_b["user_id"].isin(ids)].copy()

    print("=== 交集统计明文演示结果 ===")
    print(f"\n交集规模：{len(ids)} 个共同用户（交集标识）")

    merged = pd.merge(inter_a, inter_b, on="user_id", suffixes=("_a", "_b"))

    if len(merged) == 0:
        print("\n交集记录为空，无法计算明文统计。")
        return {
            "intersection_size": 0,
            "risk_distribution": {},
            "avg_score": 0.0,
            "total_fraud": 0,
        }

    # 统计1：风险等级分布（示例：取两方风险等级的最大值）。
    merged["max_risk"] = merged[["risk_level_a", "risk_level_b"]].max(axis=1)

    risk_dist = merged["max_risk"].value_counts().sort_index()
    print("\n等级分布（示例：取双方较高等级作为联合口径）：")
    for level, count in risk_dist.items():
        label = {1: "低", 2: "中", 3: "高"}.get(int(level), str(level))
        print(f"   等级{level}（{label}）：{count} 人")

    # 统计2：风险评分均值。
    avg_score_a = inter_a["risk_score"].mean() if "risk_score" in inter_a.columns else 0.0
    avg_score_b = inter_b["risk_score"].mean() if "risk_score" in inter_b.columns else 0.0
    avg_score_combined = merged[["risk_score_a", "risk_score_b"]].mean().mean()

    print("\n分值统计（示例字段：risk_score）：")
    print(f"   A 方交集记录平均值：{avg_score_a:.2f}")
    print(f"   B 方交集记录平均值：{avg_score_b:.2f}")
    print(f"   联合口径平均值：{avg_score_combined:.2f}")

    # 统计3：欺诈次数总和。
    total_fraud_a = inter_a["fraud_count"].sum() if "fraud_count" in inter_a.columns else 0
    total_fraud_b = inter_b["fraud_count"].sum() if "fraud_count" in inter_b.columns else 0

    print("\n次数统计（示例字段：fraud_count）：")
    print(f"   A 方求和：{total_fraud_a}")
    print(f"   B 方求和：{total_fraud_b}")
    print(f"   联合求和：{total_fraud_a + total_fraud_b}")

    # 统计4：分桶统计。
    merged["score_avg"] = (merged["risk_score_a"] + merged["risk_score_b"]) / 2
    bins = [0, 40, 70, 100]
    labels = ["低(0-40)", "中(40-70)", "高(70-100)"]
    merged["score_bucket"] = pd.cut(
        merged["score_avg"],
        bins=bins,
        labels=labels,
        include_lowest=True,
    )
    bucket_dist = merged["score_bucket"].value_counts().sort_index()

    print("\n分桶统计（示例：按联合分值分桶）：")
    for bucket, count in bucket_dist.items():
        print(f"   {bucket}：{count} 人")

    print("\n聚合完成：输出为汇总统计，面向“结果共享”的数据共享形态")

    return {
        "intersection_size": len(ids),
        "risk_distribution": risk_dist.to_dict(),
        "avg_score": avg_score_combined,
        "total_fraud": int(total_fraud_a + total_fraud_b),
    }


if __name__ == "__main__":
    intersection_ids = ["USER_175298", "USER_144251", "USER_168979", "USER_149024"]

    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "..", "data")

    result = secure_aggregation(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
        intersection_ids,
    )

    print("\n--- 可加统计掩码合成演示 ---")
    result_add = secure_aggregation_additive(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
        intersection_ids,
    )