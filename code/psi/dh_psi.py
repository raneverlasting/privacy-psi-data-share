# 说明：该文件实现DH PSI大整数模幂Diffie-Hellman双盲化对照方案。

import hashlib
import os
import secrets
import time

import pandas as pd


# 大整数模幂DH PSI使用的模数。
# 这里用于原型实现和对照实验，不作为正式密码工程部署参数。
MOD = 2**521 - 1

# DH PSI中的生成元，用于构造Z(u)=g^{h(u)} mod p。
GENERATOR = 5

# 指数空间。这里使用MOD-1作为简化口径，便于展示DH双盲化交换性。
EXP_MOD = MOD - 1


def normalize_uid(uid: str) -> str:
    """统一uid字符串格式。"""
    return str(uid).strip()


def hash_to_int(uid: str) -> int:
    """
    h(u)=H(u) mod q。

    返回值限定在[1, EXP_MOD-1]，避免指数为0时所有元素退化为1。
    """
    uid = normalize_uid(uid)
    digest_int = int(hashlib.sha256(uid.encode("utf-8")).hexdigest(), 16)
    h = digest_int % EXP_MOD
    if h == 0:
        h = 1
    return h


def uid_to_group_element(uid: str) -> int:
    """
    Z(u)=g^{h(u)} mod p。

    该步骤用于与论文中的DH PSI公式保持一致：
    先把uid映射为群元素Z(u)，再进行双方私钥盲化。
    """
    h = hash_to_int(uid)
    return pow(GENERATOR, h, MOD)


def rand_exponent() -> int:
    """
    生成DH PSI盲化指数。

    返回值限定在[1, EXP_MOD-1]，避免指数为0导致盲化退化。
    """
    return secrets.randbelow(EXP_MOD - 1) + 1


def blind(values: list[int], exponent: int) -> list[int]:
    """
    对群元素列表进行盲化：v^k mod p。

    若v=Z(u)=g^{h(u)}，则v^k=g^{k h(u)}。
    """
    k = int(exponent)
    if k <= 0:
        raise ValueError("盲化指数必须为正整数")
    return [pow(v, k, MOD) for v in values]


def dh_psi(path_a: str, path_b: str):
    """
    DH PSI两方求交流程。

    协议流程：
    1.A、B分别将uid映射为Z(u)=g^{h(u)} mod p；
    2.A使用指数a对Z(x)盲化，得到A_1(x)=Z(x)^a mod p；
    3.B使用指数b对Z(y)盲化，得到B_1(y)=Z(y)^b mod p；
    4.B对A_1(x)再盲化，得到B_2(x)=A_1(x)^b=g^{ab h(x)} mod p；
    5.A对B_1(y)再盲化，得到A_2(y)=B_1(y)^a=g^{ab h(y)} mod p；
    6.比较双重盲化结果，得到交集。
    """
    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入CSV必须包含user_id字段")

    ids_a = [normalize_uid(uid) for uid in df_a["user_id"]]
    ids_b = [normalize_uid(uid) for uid in df_b["user_id"]]

    start_time = time.time()

    a = rand_exponent()
    b = rand_exponent()

    # 第一步：映射到群元素Z(u)=g^{h(u)} mod p。
    group_a = [uid_to_group_element(uid) for uid in ids_a]
    group_b = [uid_to_group_element(uid) for uid in ids_b]

    # 第二步：A、B分别进行第一轮盲化。
    blinded_a = blind(group_a, a)  # A_1(x)=Z(x)^a mod p
    blinded_b = blind(group_b, b)  # B_1(y)=Z(y)^b mod p

    # 第三步：进行第二轮盲化。
    double_blinded_a = blind(blinded_a, b)  # B_2(x)=A_1(x)^b=g^{ab h(x)} mod p
    double_blinded_b = blind(blinded_b, a)  # A_2(y)=B_1(y)^a=g^{ab h(y)} mod p

    # 第四步：比较双重盲化结果。
    set_db = set(double_blinded_b)
    intersection_ids = []
    for i, val in enumerate(double_blinded_a):
        if val in set_db:
            intersection_ids.append(ids_a[i])

    elapsed = time.time() - start_time

    print("=== DH PSI协议结果 ===")
    print(f"机构A数据量：{len(ids_a)}条")
    print(f"机构B数据量：{len(ids_b)}条")
    print(f"交集大小：{len(intersection_ids)}个共同用户")
    print(f"耗时：{elapsed * 1000:.2f}ms")
    print("说明：本方法采用大整数模幂方式展示Diffie-Hellman双盲化思想，作为对照方案")

    return intersection_ids, elapsed


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "..", "data")

    intersection, t = dh_psi(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
    )
    print(f"\n交集用户ID：{intersection}")
