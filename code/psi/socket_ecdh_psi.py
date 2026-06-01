# 说明：该文件实现Socket ECDH PSI工程通信版本。

import os
import socket
import struct
import time
from multiprocessing import Process, Queue
from queue import Empty

import pandas as pd

from psi.ecdh_psi import (
    _rand_nonzero_scalar,
    blind_serialized_points,
    uids_to_blinded_serialized_points,
)


# 单帧payload最大长度，不含4字节长度前缀；用于防止异常长度导致内存占用过大。
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024

# Socket连接、接收和子进程等待的基础超时时间。
SOCKET_TIMEOUT_SEC = 120

# secp256k1压缩点编码长度为33字节。
POINT_SIZE = 33

# 协议消息类型。
MSG_A_TO_B = 1
MSG_B_TO_A = 2


def _send_frame(conn: socket.socket, payload: bytes) -> int:
    """
    发送一帧数据。

    帧格式：
    4字节payload长度 || payload

    返回值为本次发送的总字节数，包含4字节长度前缀。
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload必须为bytes类型")

    payload_len = len(payload)

    if payload_len <= 0 or payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"帧payload长度非法:{payload_len}，上限为{MAX_PAYLOAD_BYTES}")

    conn.sendall(struct.pack("!I", payload_len))
    conn.sendall(payload)

    return 4 + payload_len


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    """
    精确接收指定长度的数据。

    TCP是字节流协议，单次recv不保证返回完整payload；
    因此需要循环接收，直到达到指定长度。
    """
    if size <= 0:
        raise ValueError("接收长度必须为正整数")

    chunks: list[bytes] = []
    remaining = size

    while remaining > 0:
        chunk = conn.recv(min(remaining, 65536))

        if not chunk:
            raise ConnectionError("Socket连接中断，数据接收不完整")

        chunks.append(chunk)
        remaining -= len(chunk)

    return b"".join(chunks)


def _recv_frame(conn: socket.socket) -> bytes:
    """
    接收一帧数据。

    先读取4字节长度字段，再按长度读取payload。
    """
    header = _recv_exact(conn, 4)
    payload_len = struct.unpack("!I", header)[0]

    if payload_len <= 0 or payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"非法帧长度字段:{payload_len}")

    return _recv_exact(conn, payload_len)


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


def _pick_free_port(host: str) -> int:
    """
    自动选择一个空闲端口。

    用于本地双进程实验，避免固定端口被占用。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _party_a_server(path_a: str, host: str, port: int, queue: Queue) -> None:
    """
    A方进程。

    A方负责：
    1.读取A方数据；
    2.对A方uid执行曲线点映射和第一轮盲化；
    3.通过Socket发送A方第一轮盲化结果；
    4.接收B方返回消息；
    5.完成B方点的回传盲化并比较双重盲化集合。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((host, port))
            server.listen(1)
            server.settimeout(SOCKET_TIMEOUT_SEC)

            df_a = pd.read_csv(path_a)

            if "user_id" not in df_a.columns:
                raise KeyError("A方输入CSV必须包含user_id字段")

            ids_a = [str(uid).strip() for uid in df_a["user_id"]]
            scalar_a = _rand_nonzero_scalar()

            t_blind_a_start = time.perf_counter()
            blinded_a = uids_to_blinded_serialized_points(ids_a, scalar_a)
            phase_blind_a_ms = (time.perf_counter() - t_blind_a_start) * 1000

            conn, _ = server.accept()
            conn.settimeout(SOCKET_TIMEOUT_SEC)

            with conn:
                protocol_start = time.perf_counter()
                tx_bytes = 0
                rx_bytes = 0

                payload_a = _encode_msg_a_to_b(blinded_a)
                tx_bytes += _send_frame(conn, payload_a)

                payload_b = _recv_frame(conn)
                rx_bytes += 4 + len(payload_b)

                double_blinded_a, blinded_b = _decode_msg_b_to_a(payload_b)

                t_blind_back_start = time.perf_counter()
                double_blinded_b = blind_serialized_points(blinded_b, scalar_a)
                phase_blind_back_ms = (time.perf_counter() - t_blind_back_start) * 1000

                t_compare_start = time.perf_counter()
                set_b = set(double_blinded_b)
                intersection_ids = [
                    ids_a[idx]
                    for idx, point in enumerate(double_blinded_a)
                    if point in set_b
                ]
                phase_compare_ms = (time.perf_counter() - t_compare_start) * 1000

                queue.put(
                    {
                        "ok": True,
                        "intersection_ids": intersection_ids,
                        "elapsed": time.perf_counter() - protocol_start,
                        "size_a": len(ids_a),
                        "comm_tx_bytes": tx_bytes,
                        "comm_rx_bytes": rx_bytes,
                        "phase_blind_a_ms": phase_blind_a_ms,
                        "phase_blind_back_ms": phase_blind_back_ms,
                        "phase_compare_ms": phase_compare_ms,
                    }
                )

    except Exception as exc:
        queue.put({"ok": False, "error": f"A方进程异常:{exc}"})


def _party_b_client(path_b: str, host: str, port: int, queue: Queue) -> None:
    """
    B方进程。

    B方负责：
    1.连接A方Socket服务；
    2.接收A方第一轮盲化结果；
    3.对A方结果执行第二轮盲化；
    4.对B方uid执行曲线点映射和第一轮盲化；
    5.将两部分结果发回A方。
    """
    try:
        df_b = pd.read_csv(path_b)

        if "user_id" not in df_b.columns:
            raise KeyError("B方输入CSV必须包含user_id字段")

        ids_b = [str(uid).strip() for uid in df_b["user_id"]]
        scalar_b = _rand_nonzero_scalar()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            for _ in range(30):
                try:
                    client.connect((host, port))
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise ConnectionError("B方连接A方失败")

            client.settimeout(SOCKET_TIMEOUT_SEC)

            tx_bytes = 0
            rx_bytes = 0

            payload_a = _recv_frame(client)
            rx_bytes += 4 + len(payload_a)

            blinded_a = _decode_msg_a_to_b(payload_a)

            t_blind_b_start = time.perf_counter()
            double_blinded_a = blind_serialized_points(blinded_a, scalar_b)
            blinded_b = uids_to_blinded_serialized_points(ids_b, scalar_b)
            phase_blind_b_ms = (time.perf_counter() - t_blind_b_start) * 1000

            payload_b = _encode_msg_b_to_a(double_blinded_a, blinded_b)
            tx_bytes += _send_frame(client, payload_b)

        queue.put(
            {
                "ok": True,
                "size_b": len(ids_b),
                "comm_tx_bytes": tx_bytes,
                "comm_rx_bytes": rx_bytes,
                "phase_blind_b_ms": phase_blind_b_ms,
            }
        )

    except Exception as exc:
        queue.put({"ok": False, "error": f"B方进程异常:{exc}"})


def _terminate_if_alive(proc: Process, name: str) -> None:
    """
    若子进程超时仍未退出，则终止进程并抛出异常。
    """
    if proc.is_alive():
        proc.terminate()
        proc.join()
        raise TimeoutError(f"{name}超时未退出")


def _get_queue_result(queue: Queue, party_name: str) -> dict:
    """
    从子进程结果队列中读取结果。
    """
    try:
        return queue.get(timeout=2)
    except Empty:
        return {"ok": False, "error": f"{party_name}无返回"}


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
    本函数是ECDH PSI的工程通信版本，用于观察Socket通信、消息帧封装、
    序列化、接收校验和进程调度带来的端到端开销。
    """
    if port is None:
        port = _pick_free_port(host)

    queue_a = Queue()
    queue_b = Queue()

    proc_a = Process(target=_party_a_server, args=(path_a, host, port, queue_a), daemon=True)
    proc_b = Process(target=_party_b_client, args=(path_b, host, port, queue_b), daemon=True)

    proc_a.start()
    proc_b.start()

    proc_a.join(SOCKET_TIMEOUT_SEC + 10)
    proc_b.join(SOCKET_TIMEOUT_SEC + 10)

    _terminate_if_alive(proc_a, "A方进程")
    _terminate_if_alive(proc_b, "B方进程")

    result_a = _get_queue_result(queue_a, "A方进程")
    result_b = _get_queue_result(queue_b, "B方进程")

    if not result_a.get("ok"):
        raise RuntimeError(result_a.get("error", "A方执行失败"))

    if not result_b.get("ok"):
        raise RuntimeError(result_b.get("error", "B方执行失败"))

    intersection_ids = result_a["intersection_ids"]
    elapsed = result_a["elapsed"]
    size_a = result_a["size_a"]
    size_b = result_b["size_b"]

    # 保持原有benchmark口径：统计A/B两端发送与接收字节数合计。
    comm_bytes = (
        result_a.get("comm_tx_bytes", 0)
        + result_a.get("comm_rx_bytes", 0)
        + result_b.get("comm_tx_bytes", 0)
        + result_b.get("comm_rx_bytes", 0)
    )

    stats = {
        "comm_bytes": float(comm_bytes),
        "phase_map_ms": 0.0,
        "phase_blind_ms": 0.0,
        "phase_blind_a_ms": float(result_a.get("phase_blind_a_ms", 0.0)),
        "phase_blind_b_ms": float(result_b.get("phase_blind_b_ms", 0.0)),
        "phase_blind_back_ms": float(result_a.get("phase_blind_back_ms", 0.0)),
        "phase_compare_ms": float(result_a.get("phase_compare_ms", 0.0)),
    }

    print("=== Socket ECDH PSI协议结果 ===")
    print(f"机构A数据量：{size_a}条")
    print(f"机构B数据量：{size_b}条")
    print(f"交集大小：{len(intersection_ids)}个共同用户")
    print(f"耗时：{elapsed * 1000:.2f}ms")
    print(f"通信统计量：{comm_bytes / 1024:.2f}KB")
    print("说明：本方法在ECDH PSI基础上加入Socket通信封装，用于观察端到端工程开销")

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
