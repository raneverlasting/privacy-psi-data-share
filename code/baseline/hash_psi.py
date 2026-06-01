import hashlib
import os
import time

import pandas as pd


def normalize_uid(user_id: str) -> str:
    """统一 uid 字符串格式，避免空白字符或类型差异影响求交结果。"""
    return str(user_id).strip()


def hash_id(user_id: str) -> str:
    """对单个 ID 进行 SHA-256 哈希。"""
    uid = normalize_uid(user_id)
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def hash_psi(path_a: str, path_b: str):
    """
    基于哈希的朴素 PSI 基线方案。

    注意：
    本函数仅作为性能基线，用于体现“直接哈希求交”的速度上界；
    对手机号、证件号、银行卡号等可枚举标识，普通哈希容易受到离线字典攻击，
    因此不能把该方法表述为严格意义上的隐私保护 PSI 协议。
    """
    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入 CSV 必须包含 user_id 字段")

    ids_a = [normalize_uid(uid) for uid in df_a["user_id"]]
    ids_b = [normalize_uid(uid) for uid in df_b["user_id"]]

    start_time = time.time()

    # 使用 dict 保留 A 方原始顺序，便于输出稳定、复现实验结果。
    hashed_a = {}
    for uid in ids_a:
        hashed_a[hash_id(uid)] = uid

    hashed_b = {}
    for uid in ids_b:
        hashed_b[hash_id(uid)] = uid

    common_hashes = set(hashed_a.keys()) & set(hashed_b.keys())

    # 按 A 方顺序返回交集 uid，避免 set 遍历顺序导致每次输出顺序不同。
    intersection_ids = [
        uid for uid in ids_a
        if hash_id(uid) in common_hashes
    ]

    elapsed = time.time() - start_time

    print("=== 哈希基线方案结果 ===")
    print(f"机构A数据量：{len(df_a)} 条")
    print(f"机构B数据量：{len(df_b)} 条")
    print(f"交集大小：{len(intersection_ids)} 个共同用户")
    print(f"耗时：{elapsed * 1000:.2f} ms")
    print("\n[警告] 哈希基线仅用于性能对照，不满足严格隐私保护要求")

    return intersection_ids, elapsed


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "..", "data")

    intersection, t = hash_psi(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
    )
    print(f"\n交集用户ID：{intersection}")