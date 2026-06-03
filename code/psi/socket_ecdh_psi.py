# 说明：该文件实现Socket ECDH PSI工程通信版本。

import os
import struct
import time

import pandas as pd

from psi.ecdh_psi import (
    _rand_nonzero_scalar,
    _uids_to_serialized_points,
    blind_serialized_points,
)


# 单帧payload最大长度，不含4字节长度前缀；用于防止异常长度导致内存占用过大。
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024

# secp256k1压缩点编码长度为33字节。
POINT_SIZE = 33

# 协议消息类型。
MSG_A_TO_B = 1
MSG_B_TO_A = 2


def _frame_bytes(payload: bytes) -> bytes:
    """
    按Socket工程通信版本的帧格式封装payload。

    帧格式：
    4字节payload长度 || payload
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload必须为bytes类型")

    payload_len = len(payload)

    if payload_len <= 0 or payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"帧payload长度非法:{payload_len}，上限为{MAX_PAYLOAD_BYTES}")

    return struct.pack("!I", payload_len) + bytes(payload)


def _unframe_bytes(frame: bytes) -> bytes:
    """
    按Socket工程通信版本的帧格式解析payload。
    """
    if len(frame) < 4:
        raise ValueError("帧长度不足，无法读取payload长度字段")

    payload_len = struct.unpack("!I", frame[:4])[0]
    if payload_len <= 0 or payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"非法帧长度字段:{payload_len}")

    if len(frame) != 4 + payload_len:
        raise ValueError("帧长度与payload长度字段不一致")

    return frame[4:]


def _encode_points(points: list[bytes]) -> bytes:
    """
    编码点列表。

    格式：
    4字节点数量 || 点1 || 点2 || ...
    """
    for point in points:
        if len(point) != POINT_SIZE:
            raise ValueError(f"点编码长度异常，预期{POINT_SIZE}字节，实际{len(point)}字节")

    return struct.pack("!I", len(points)) + b"".join(points)


def _decode_points(payload: bytes, offset: int = 0) -> tuple[list[bytes], int]:
    """
    从payload中解码点列表。

    返回：
    1.点列表；
    2.解码结束后的offset。
    """
    if len(payload) < offset + 4:
        raise ValueError("payload长度不足，无法读取点数量")

    count = struct.unpack("!I", payload[offset: offset + 4])[0]
    offset += 4

    data_len = count * POINT_SIZE

    if len(payload) < offset + data_len:
        raise ValueError("payload长度不足，无法读取点数据")

    data = payload[offset: offset + data_len]
    points = [data[i: i + POINT_SIZE] for i in range(0, data_len, POINT_SIZE)]

    return points, offset + data_len


def _encode_msg_a_to_b(blinded_a: list[bytes]) -> bytes:
    """
    编码A方发送给B方的消息。

    格式：
    1字节消息类型 || A方第一轮盲化点列表
    """
    return bytes([MSG_A_TO_B]) + _encode_points(blinded_a)


def _decode_msg_a_to_b(payload: bytes) -> list[bytes]:
    """
    解码A方发送给B方的消息。
    """
    if not payload or payload[0] != MSG_A_TO_B:
        raise ValueError("消息类型错误，预期A->B")

    points, offset = _decode_points(payload, 1)

    if offset != len(payload):
        raise ValueError("A->B消息存在多余字节")

    return points


def _encode_msg_b_to_a(double_blinded_a: list[bytes], blinded_b: list[bytes]) -> bytes:
    """
    编码B方发送给A方的消息。

    格式：
    1字节消息类型 || A方双重盲化点列表 || B方第一轮盲化点列表
    """
    return bytes([MSG_B_TO_A]) + _encode_points(double_blinded_a) + _encode_points(blinded_b)


def _decode_msg_b_to_a(payload: bytes) -> tuple[list[bytes], list[bytes]]:
    """
    解码B方发送给A方的消息。
    """
    if not payload or payload[0] != MSG_B_TO_A:
        raise ValueError("消息类型错误，预期B->A")

    points_a, offset = _decode_points(payload, 1)
    points_b, offset = _decode_points(payload, offset)

    if offset != len(payload):
        raise ValueError("B->A消息存在多余字节")

    return points_a, points_b


def socket_ecdh_psi(
    path_a: str,
    path_b: str,
    host: str = "127.0.0.1",
    port: int | None = None,
    return_stats: bool = False,
):
    """
    Socket ECDH PSI两方求交流程。

    说明：
    本函数是ECDH PSI的单进程工程封装版本，用于在同一线程口径下观察
    消息帧封装、序列化、解码校验和通信量统计带来的协议开销。
    """
    del host, port

    df_a = pd.read_csv(path_a)
    df_b = pd.read_csv(path_b)

    if "user_id" not in df_a.columns or "user_id" not in df_b.columns:
        raise KeyError("输入CSV必须包含user_id字段")

    ids_a = [str(uid).strip() for uid in df_a["user_id"]]
    ids_b = [str(uid).strip() for uid in df_b["user_id"]]

    scalar_a = _rand_nonzero_scalar()
    scalar_b = _rand_nonzero_scalar()

    protocol_start = time.perf_counter()

    t_map_start = time.perf_counter()
    points_a = _uids_to_serialized_points(ids_a)
    points_b = _uids_to_serialized_points(ids_b)
    phase_map_ms = (time.perf_counter() - t_map_start) * 1000

    t_blind_a_start = time.perf_counter()
    blinded_a = blind_serialized_points(points_a, scalar_a)
    phase_blind_a_ms = (time.perf_counter() - t_blind_a_start) * 1000

    payload_a = _encode_msg_a_to_b(blinded_a)
    frame_a_to_b = _frame_bytes(payload_a)
    payload_a_received = _unframe_bytes(frame_a_to_b)
    blinded_a_received = _decode_msg_a_to_b(payload_a_received)

    t_blind_b_start = time.perf_counter()
    double_blinded_a = blind_serialized_points(blinded_a_received, scalar_b)
    blinded_b = blind_serialized_points(points_b, scalar_b)
    phase_blind_b_ms = (time.perf_counter() - t_blind_b_start) * 1000

    payload_b = _encode_msg_b_to_a(double_blinded_a, blinded_b)
    frame_b_to_a = _frame_bytes(payload_b)
    payload_b_received = _unframe_bytes(frame_b_to_a)
    double_blinded_a_received, blinded_b_received = _decode_msg_b_to_a(payload_b_received)

    t_blind_back_start = time.perf_counter()
    double_blinded_b = blind_serialized_points(blinded_b_received, scalar_a)
    phase_blind_back_ms = (time.perf_counter() - t_blind_back_start) * 1000
    phase_blind_ms = phase_blind_a_ms + phase_blind_b_ms + phase_blind_back_ms

    t_compare_start = time.perf_counter()
    set_b = set(double_blinded_b)
    intersection_ids = [
        ids_a[idx]
        for idx, point in enumerate(double_blinded_a_received)
        if point in set_b
    ]
    phase_compare_ms = (time.perf_counter() - t_compare_start) * 1000

    elapsed = time.perf_counter() - protocol_start

    # 统计A、B两端发送与接收字节数之和，保持原benchmark口径。
    wire_bytes = len(frame_a_to_b) + len(frame_b_to_a)
    comm_bytes = 2 * wire_bytes

    stats = {
        "comm_bytes": float(comm_bytes),
        "phase_map_ms": phase_map_ms,
        "phase_blind_ms": phase_blind_ms,
        "phase_blind_a_ms": phase_blind_a_ms,
        "phase_blind_b_ms": phase_blind_b_ms,
        "phase_blind_back_ms": phase_blind_back_ms,
        "phase_compare_ms": phase_compare_ms,
    }

    print("=== Socket ECDH PSI协议结果 ===")
    print(f"机构A数据量：{len(ids_a)}条")
    print(f"机构B数据量：{len(ids_b)}条")
    print(f"交集大小：{len(intersection_ids)}个共同用户")
    print(f"耗时：{elapsed * 1000:.2f}ms")
    print(f"通信统计量：{comm_bytes / 1024:.2f}KB")
    print("说明：本方法在ECDH PSI基础上加入Socket消息帧封装，用于观察工程封装开销")

    if return_stats:
        return intersection_ids, elapsed, stats

    return intersection_ids, elapsed


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "..", "data")

    intersection, _ = socket_ecdh_psi(
        os.path.join(data_dir, "party_A.csv"),
        os.path.join(data_dir, "party_B.csv"),
    )

    print(f"交集用户ID：{intersection}")
