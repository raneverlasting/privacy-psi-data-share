# 说明：该文件实现ECDH PSI主要求交路线。

import hashlib
import os
import secrets
import time

import pandas as pd
from coincurve import PublicKey


# secp256k1曲线阶n。
ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def normalize_uid(uid: str) -> str:
    """统一uid字符串格式。"""
    return str(uid).strip()


def _hash_to_scalar(uid: str) -> int:
    """
    Hash-to-Scalar：h=int(SHA256(uid)) mod n，映射到[1,n-1]。

    说明：
    本函数不是IRTF意义下的Hash-to-Curve，而是工程原型中的Hash-to-Scalar过程。
    后续通过Q(u)=h(u)P构造曲线点，其中P表示椭圆曲线基点。
    """
    uid = normalize_uid(uid)
    digest = hashlib.sha256(uid.encode("utf-8")).digest()
    h = int.from_bytes(digest, byteorder="big") % ORDER
    if h == 0:
        h = 1
    return h


def _rand_nonzero_scalar() -> int:
    """
    生成非零盲化标量。

    返回值均匀取自[1,n-1]，使用secrets生成随机数。
    """
    return secrets.randbelow(ORDER - 1) + 1


def _int_to_scalar_bytes(v: int) -> bytes:
    """
    将标量整数转换为32字节大端表示。

    coincurve的点乘接口需要固定长度标量字节串。
    """
    v = int(v)
    if not (1 <= v < ORDER):
        raise ValueError("标量必须位于[1,n-1]区间内")
    return v.to_bytes(32, byteorder="big")


def _blind_serialized_points(serialized_points: list[bytes], scalar: int) -> list[bytes]:
    """
    对已经序列化的曲线点执行标量乘法盲化。

    输入点为压缩编码形式，输出也保持压缩编码形式。
    """
    scalar_bytes = _int_to_scalar_bytes(scalar)
    blinded = []

    for point_bytes in serialized_points:
        blinded_point = PublicKey(point_bytes).multiply(scalar_bytes)
        blinded.append(blinded_point.format(compressed=True))

    return blinded


def _uids_to_serialized_points(uids: list[str]) -> list[bytes]:
    """
    将uid列表映射为曲线点列表。

    映射关系为：
    h(u)=HashToScalar(u)
    Q(u)=h(u)P

    其中P表示椭圆曲线基点，Q(u)使用压缩点编码保存。
    """
    out = []

    for uid in uids:
        scalar = _hash_to_scalar(uid)
        scalar_bytes = _int_to_scalar_bytes(scalar)
        point = PublicKey.from_valid_secret(scalar_bytes).format(compressed=True)
        out.append(point)

    return out


def ecdh_psi(path_a: str, path_b: str, return_stats: bool = False):
    """
    ECDH PSI两方求交流程。

    协议流程：
    1.A、B分别将uid映射为曲线点Q(u)=h(u)P；
    2.A使用标量a对Q(x)盲化，得到A_1(x)=aQ(x)；
    3.B使用标量b对Q(y)盲化，得到B_1(y)=bQ(y)；
    4.B对A_1(x)再次盲化，得到B_2(x)=bA_1(x)=abQ(x)；
    5.A对B_1(y)再次盲化，得到A_2(y)=aB_1(y)=abQ(y)；
    6.比较双重盲化结果，得到交集。
    """
    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入CSV必须包含user_id字段")

    ids_a = [normalize_uid(uid) for uid in df_a["user_id"]]
    ids_b = [normalize_uid(uid) for uid in df_b["user_id"]]

    start_time = time.time()

    a = _rand_nonzero_scalar()
    b = _rand_nonzero_scalar()

    # 第一阶段：Hash-to-Scalar后构造曲线点Q(u)=h(u)P。
    t_map = time.time()
    points_a = _uids_to_serialized_points(ids_a)
    points_b = _uids_to_serialized_points(ids_b)
    map_ms = (time.time() - t_map) * 1000

    # 第二阶段：两方分别完成第一轮和第二轮盲化。
    t_blind_a = time.time()
    blinded_a = _blind_serialized_points(points_a, a)
    phase_blind_a_ms = (time.time() - t_blind_a) * 1000

    t_blind_b = time.time()
    double_blinded_a = _blind_serialized_points(blinded_a, b)
    blinded_b = _blind_serialized_points(points_b, b)
    phase_blind_b_ms = (time.time() - t_blind_b) * 1000

    t_blind_back = time.time()
    double_blinded_b = _blind_serialized_points(blinded_b, a)
    phase_blind_back_ms = (time.time() - t_blind_back) * 1000

    blind_ms = phase_blind_a_ms + phase_blind_b_ms + phase_blind_back_ms

    # 第三阶段：比较双重盲化结果。
    t_compare = time.time()
    set_b = set(double_blinded_b)
    intersection_ids = []

    for idx, point_bytes in enumerate(double_blinded_a):
        if point_bytes in set_b:
            intersection_ids.append(ids_a[idx])

    compare_ms = (time.time() - t_compare) * 1000

    elapsed = time.time() - start_time

    stats = {
        "comm_bytes": 0.0,
        "phase_map_ms": map_ms,
        "phase_blind_ms": blind_ms,
        "phase_blind_a_ms": phase_blind_a_ms,
        "phase_blind_b_ms": phase_blind_b_ms,
        "phase_blind_back_ms": phase_blind_back_ms,
        "phase_compare_ms": compare_ms,
    }

    print("=== ECDH PSI协议结果 ===")
    print(f"机构A数据量：{len(ids_a)}条")
    print(f"机构B数据量：{len(ids_b)}条")
    print(f"交集大小：{len(intersection_ids)}个共同用户")
    print(f"耗时：{elapsed * 1000:.2f}ms")
    print("说明：本方法基于椭圆曲线点乘实现双盲化，是本文主要求交路线")
    print(
        f"分阶段耗时：映射={map_ms:.2f}ms，A侧盲化={phase_blind_a_ms:.2f}ms，"
        f"B侧处理={phase_blind_b_ms:.2f}ms，回传盲化={phase_blind_back_ms:.2f}ms，"
        f"比较={compare_ms:.2f}ms"
    )

    if return_stats:
        return intersection_ids, elapsed, stats
    return intersection_ids, elapsed


def blind_serialized_points(serialized_points: list[bytes], scalar: int) -> list[bytes]:
    """
    对外暴露的点盲化函数。

    Socket ECDH PSI版本会复用该函数。
    """
    return _blind_serialized_points(serialized_points, scalar)


def uids_to_blinded_serialized_points(uids: list[str], scalar: int) -> list[bytes]:
    """
    将uid列表映射为曲线点后立即进行标量盲化。

    Socket ECDH PSI版本会复用该函数。
    """
    points = _uids_to_serialized_points(uids)
    return _blind_serialized_points(points, scalar)


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "..", "data")

    intersection, _ = ecdh_psi(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
    )

    print(f"\n交集用户ID：{intersection}")
