#!/usr/bin/env python3

import argparse
import contextlib
import dataclasses
import glob
import struct
import sys
import time
from typing import List, Optional

try:
    import serial
except ImportError as exc:
    print(
        "pyserial is required. Install it with: pip3 install pyserial",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


FRAME_HEADER = 0x55
NODE_FRAME2_MARK = 0x04
TAG_FRAME0_MARK = 0x01
TAG_FRAME0_SIZE = 127
TAG_FRAME0_SIZE_FALLBACK = 128

ROLE_NAMES = {
    0: "UNKNOWN",
    1: "ANCHOR",
    2: "TAG",
    3: "CONSOLE",
}

TAG_FRAME0_SAMPLE = bytes.fromhex(
    "55 01 01 02 8e 0a 00 a5 ff ff e8 03 00 da ff ff fa ff ff 00 00 00 "
    "35 0c 00 a3 15 00 cd 1a 00 4c 12 00 00 00 00 00 00 00 00 00 00 00 00 "
    "27 ac e2 3c a2 7d 0b 3c d2 70 3b bd cf a5 80 3e 3e fc 1b 41 1f a1 26 bd "
    "26 5d 57 41 bd 80 57 41 3f 63 57 41 71 38 f5 25 44 fa 8a 22 28 bf 5a b7 "
    "00 be 20 4f 3d bf 1c 0b 52 3d f4 26 3d 40 0c ae 00 00 cb 17 01 00 f0 "
    "0b 10 ff 54 13 1d 48 00 00 bc fd"
)

NODE_FRAME2_SAMPLE = bytes.fromhex(
    "55 04 ac 00 02 01 ba 66 1d 00 06 09 ff de 0a 00 df ff ff e8 03 00 fa ff ff "
    "1a 00 00 00 00 00 c0 12 00 00 00 00 00 00 00 27 ac e2 3c 56 ed 1c 3c d2 70 "
    "3b bd 32 57 66 3e 3b cb 1b 41 93 70 61 bd 25 b2 6b 41 a1 22 6c 41 da da 6b "
    "41 6d 23 e9 23 70 dd db f7 30 3f 5f d6 31 3f ba 81 1e 3e 47 69 e2 bd 91 9b "
    "40 40 c5 23 00 00 40 40 5c d5 1c 00 00 00 1d 00 6d 13 04 01 00 6b 0c 00 b1 "
    "9f a6 66 1d 00 16 45 01 01 ac 15 00 b4 a1 a6 66 1d 00 d3 01 01 02 48 1a 00 "
    "ca 9f a6 66 1d 00 38 ba 01 03 2b 12 00 c6 a0 a6 66 1d 00 64 40 25"
)


@dataclasses.dataclass
class UwbSample:
    frame_name: str
    role: int
    node_id: int
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    system_time_ms: Optional[int]
    local_time_ms: Optional[int]
    voltage_v: Optional[float]
    eop_x: Optional[float]
    eop_y: Optional[float]
    eop_z: Optional[float]
    valid_node_quantity: Optional[int]
    position_valid: bool


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read Nooploop LinkTrack UWB coordinates from a serial port."
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyACM0",
        help="Serial port path, default: /dev/ttyACM0",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=921600,
        help="Baud rate, default: 921600",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.2,
        help="Serial read timeout seconds, default: 0.2",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="Minimum print interval in seconds, default: 0.2",
    )
    parser.add_argument(
        "--protocol",
        choices=("auto", "node_frame2", "tag_frame0"),
        default="auto",
        help="Expected output protocol, default: auto",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after the first valid coordinate frame",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run parser self-test against sample frames from the official manual",
    )
    return parser.parse_args()


def role_name(role: int) -> str:
    return ROLE_NAMES.get(role, f"ROLE_{role}")


def open_serial_port(port: str, baud: int, timeout: float):
    return serial.Serial(
        port=port,
        baudrate=baud,
        timeout=timeout,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )


def checksum_ok(frame: bytes) -> bool:
    return (sum(frame[:-1]) & 0xFF) == frame[-1]


def read_uint16_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def read_uint32_le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_int24_le(data: bytes, offset: int) -> int:
    value = data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)
    if value & 0x800000:
        value -= 1 << 24
    return value


def approx_equal(value: float, expected: float, tol: float = 1e-6) -> bool:
    return abs(value - expected) <= tol


def infer_position_valid(
    x: float,
    y: float,
    z: float,
    vx: float,
    vy: float,
    vz: float,
    eop_x: Optional[float],
    eop_y: Optional[float],
    eop_z: Optional[float],
) -> bool:
    # Official Nooploop manual notes that Pos defaults to 1 when location is invalid.
    if (
        approx_equal(x, 1.0)
        and approx_equal(y, 1.0)
        and approx_equal(z, 1.0)
        and approx_equal(vx, 0.0)
        and approx_equal(vy, 0.0)
        and approx_equal(vz, 0.0)
        and eop_x is not None
        and eop_y is not None
        and eop_z is not None
        and approx_equal(eop_x, 2.55, 0.01)
        and approx_equal(eop_y, 2.55, 0.01)
        and approx_equal(eop_z, 2.55, 0.01)
    ):
        return False
    return True


def position_status_text(sample: UwbSample) -> str:
    return "valid" if sample.position_valid else "invalid_default"


def parse_tag_frame0(frame: bytes) -> UwbSample:
    if len(frame) not in (TAG_FRAME0_SIZE, TAG_FRAME0_SIZE_FALLBACK):
        raise ValueError(f"unexpected Tag_Frame0 size: {len(frame)}")
    if frame[0] != FRAME_HEADER or frame[1] != TAG_FRAME0_MARK:
        raise ValueError("not a Tag_Frame0 frame")
    if not checksum_ok(frame):
        raise ValueError("Tag_Frame0 checksum mismatch")

    node_id = frame[2]
    role = frame[3]
    x = read_int24_le(frame, 4) / 1000.0
    y = read_int24_le(frame, 7) / 1000.0
    z = read_int24_le(frame, 10) / 1000.0
    vx = read_int24_le(frame, 13) / 10000.0
    vy = read_int24_le(frame, 16) / 10000.0
    vz = read_int24_le(frame, 19) / 10000.0

    if len(frame) == TAG_FRAME0_SIZE:
        local_time_offset = 107
        system_time_offset = 111
        eop_offset = 116
        voltage_offset = 119
    else:
        local_time_offset = 108
        system_time_offset = 112
        eop_offset = 117
        voltage_offset = 120

    local_time_ms = read_uint32_le(frame, local_time_offset)
    system_time_ms = read_uint32_le(frame, system_time_offset)
    eop_x = frame[eop_offset] / 100.0
    eop_y = frame[eop_offset + 1] / 100.0
    eop_z = frame[eop_offset + 2] / 100.0
    voltage_v = read_uint16_le(frame, voltage_offset) / 1000.0
    position_valid = infer_position_valid(x, y, z, vx, vy, vz, eop_x, eop_y, eop_z)

    return UwbSample(
        frame_name="Tag_Frame0",
        role=role,
        node_id=node_id,
        x=x,
        y=y,
        z=z,
        vx=vx,
        vy=vy,
        vz=vz,
        system_time_ms=system_time_ms,
        local_time_ms=local_time_ms,
        voltage_v=voltage_v,
        eop_x=eop_x,
        eop_y=eop_y,
        eop_z=eop_z,
        valid_node_quantity=None,
        position_valid=position_valid,
    )


def parse_node_frame2(frame: bytes) -> UwbSample:
    if len(frame) < 114:
        raise ValueError(f"Node_Frame2 too short: {len(frame)}")
    if frame[0] != FRAME_HEADER or frame[1] != NODE_FRAME2_MARK:
        raise ValueError("not a Node_Frame2 frame")
    if read_uint16_le(frame, 2) != len(frame):
        raise ValueError("Node_Frame2 length mismatch")
    if not checksum_ok(frame):
        raise ValueError("Node_Frame2 checksum mismatch")

    role = frame[4]
    node_id = frame[5]
    system_time_ms = read_uint32_le(frame, 6)
    eop_x = frame[10] / 100.0
    eop_y = frame[11] / 100.0
    eop_z = frame[12] / 100.0
    x = read_int24_le(frame, 13) / 1000.0
    y = read_int24_le(frame, 16) / 1000.0
    z = read_int24_le(frame, 19) / 1000.0
    vx = read_int24_le(frame, 22) / 10000.0
    vy = read_int24_le(frame, 25) / 10000.0
    vz = read_int24_le(frame, 28) / 10000.0
    local_time_ms = read_uint32_le(frame, 102)
    voltage_v = read_uint16_le(frame, 116) / 1000.0
    valid_node_quantity = frame[118] if len(frame) > 118 else None
    position_valid = infer_position_valid(x, y, z, vx, vy, vz, eop_x, eop_y, eop_z)

    return UwbSample(
        frame_name="Node_Frame2",
        role=role,
        node_id=node_id,
        x=x,
        y=y,
        z=z,
        vx=vx,
        vy=vy,
        vz=vz,
        system_time_ms=system_time_ms,
        local_time_ms=local_time_ms,
        voltage_v=voltage_v,
        eop_x=eop_x,
        eop_y=eop_y,
        eop_z=eop_z,
        valid_node_quantity=valid_node_quantity,
        position_valid=position_valid,
    )


def find_candidate_ports() -> List[str]:
    candidates = []
    candidates.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    candidates.extend(sorted(glob.glob("/dev/ttyACM*")))
    candidates.extend(sorted(glob.glob("/dev/ttyUSB*")))
    candidates.extend(sorted(glob.glob("/dev/ttyCH343USB*")))
    return list(dict.fromkeys(candidates))


def format_sample(sample: UwbSample, port: str) -> str:
    timestamp = time.strftime("%H:%M:%S")
    fields = [
        f"[{timestamp}]",
        port,
        sample.frame_name,
        f"{role_name(sample.role)}{sample.node_id}",
        f"x={sample.x:7.3f}m",
        f"y={sample.y:7.3f}m",
        f"z={sample.z:7.3f}m",
        f"vx={sample.vx:7.4f}m/s",
        f"vy={sample.vy:7.4f}m/s",
        f"vz={sample.vz:7.4f}m/s",
    ]
    if sample.voltage_v is not None:
        fields.append(f"voltage={sample.voltage_v:.3f}V")
    if sample.valid_node_quantity is not None:
        fields.append(f"anchors={sample.valid_node_quantity}")
    fields.append(f"pos_status={position_status_text(sample)}")
    if sample.eop_x is not None and sample.eop_y is not None and sample.eop_z is not None:
        fields.append(
            f"eop=({sample.eop_x:.2f},{sample.eop_y:.2f},{sample.eop_z:.2f})m"
        )
    if sample.system_time_ms is not None:
        fields.append(f"sys={sample.system_time_ms}ms")
    return "  ".join(fields)


def preview_bytes(data: bytes, limit: int = 48) -> str:
    snippet = data[:limit]
    hex_part = snippet.hex(" ")
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in snippet)
    if len(data) > limit:
        hex_part += " ..."
        ascii_part += "..."
    return f"hex=[{hex_part}] ascii=[{ascii_part}]"


def looks_like_nmea(data: bytes) -> bool:
    stripped = data.lstrip()
    if stripped.startswith((b"$GP", b"$GN", b"$GNGGA", b"$GNRMC", b"$GNGSA")):
        return True
    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return len(data) > 0 and printable / len(data) > 0.85 and b"," in data


def extract_frame(buffer: bytearray, protocol: str) -> Optional[bytes]:
    while buffer:
        if buffer[0] != FRAME_HEADER:
            del buffer[0]
            continue

        if len(buffer) < 2:
            return None

        mark = buffer[1]
        if protocol == "node_frame2" and mark != NODE_FRAME2_MARK:
            del buffer[0]
            continue
        if protocol == "tag_frame0" and mark != TAG_FRAME0_MARK:
            del buffer[0]
            continue

        if mark == NODE_FRAME2_MARK:
            if len(buffer) < 4:
                return None
            frame_len = read_uint16_le(buffer, 2)
            if frame_len < 16 or frame_len > 4096:
                del buffer[0]
                continue
            if len(buffer) < frame_len:
                return None
            frame = bytes(buffer[:frame_len])
            if not checksum_ok(frame):
                del buffer[0]
                continue
            del buffer[:frame_len]
            return frame

        if mark == TAG_FRAME0_MARK:
            for frame_len in (TAG_FRAME0_SIZE, TAG_FRAME0_SIZE_FALLBACK):
                if len(buffer) < frame_len:
                    continue
                frame = bytes(buffer[:frame_len])
                if checksum_ok(frame):
                    del buffer[:frame_len]
                    return frame
            if len(buffer) < TAG_FRAME0_SIZE:
                return None
            del buffer[0]
            continue

        del buffer[0]

    return None


def parse_frame(frame: bytes) -> UwbSample:
    if len(frame) >= 2 and frame[1] == NODE_FRAME2_MARK:
        return parse_node_frame2(frame)
    if len(frame) >= 2 and frame[1] == TAG_FRAME0_MARK:
        return parse_tag_frame0(frame)
    raise ValueError("unsupported frame type")


def self_test() -> int:
    tag_sample = parse_tag_frame0(TAG_FRAME0_SAMPLE)
    node_sample = parse_node_frame2(NODE_FRAME2_SAMPLE)

    assert tag_sample.node_id == 1
    assert abs(tag_sample.x - 2.702) < 1e-6
    assert abs(tag_sample.y - (-0.091)) < 1e-6
    assert abs(tag_sample.z - 1.0) < 1e-6
    assert abs(tag_sample.voltage_v - 4.948) < 1e-6
    assert tag_sample.position_valid is True

    assert abs(node_sample.x - 2.782) < 1e-6
    assert abs(node_sample.y - (-0.033)) < 1e-6
    assert abs(node_sample.z - 1.0) < 1e-6
    assert abs(node_sample.voltage_v - 4.973) < 1e-6
    assert node_sample.valid_node_quantity == 4
    assert node_sample.position_valid is True

    print("Tag_Frame0 sample:", format_sample(tag_sample, "sample"))
    print("Node_Frame2 sample:", format_sample(node_sample, "sample"))
    print("Self-test passed.")
    return 0


def main():
    args = parse_args()

    if args.self_test:
        return self_test()

    if args.port == "auto":
        candidates = find_candidate_ports()
        if not candidates:
            print(
                "No /dev/ttyACM*, /dev/ttyUSB*, or /dev/ttyCH343USB* serial ports found.",
                file=sys.stderr,
            )
            return 1
        print("Candidate ports:", ", ".join(candidates))
        print("Auto mode is listing ports only. Choose one with --port.")
        return 0

    try:
        ser = open_serial_port(args.port, args.baud, args.timeout)
    except serial.SerialException as exc:
        print(f"Failed to open {args.port}: {exc}", file=sys.stderr)
        return 1

    print(f"Reading UWB coordinates from {args.port} @ {args.baud}")
    print("Expecting Nooploop LinkTrack Tag_Frame0 or Node_Frame2. Press Ctrl+C to stop.")

    buffer = bytearray()
    last_print_time = 0.0
    last_warn_time = time.monotonic()
    had_frame = False
    total_bytes = 0
    raw_preview = bytearray()

    try:
        while True:
            chunk = ser.read(4096)
            if chunk:
                total_bytes += len(chunk)
                if len(raw_preview) < 96:
                    remaining = 96 - len(raw_preview)
                    raw_preview.extend(chunk[:remaining])
                buffer.extend(chunk)

            printed = False
            while True:
                frame = extract_frame(buffer, args.protocol)
                if frame is None:
                    break

                sample = parse_frame(frame)
                now = time.monotonic()
                had_frame = True

                if args.once or args.interval <= 0 or (now - last_print_time) >= args.interval:
                    print("\r" + format_sample(sample, args.port), end="", flush=True)
                    last_print_time = now
                    printed = True

                if args.once:
                    print()
                    return 0

            if had_frame:
                if printed:
                    last_warn_time = time.monotonic()
                continue

            now = time.monotonic()
            if now - last_warn_time >= 3.0:
                if total_bytes == 0:
                    print(
                        "\nNo serial bytes received yet from this port. "
                        "This is usually a wrong port, no serial output, or T0 is not streaming.",
                        flush=True,
                    )
                else:
                    preview = preview_bytes(bytes(raw_preview))
                    if looks_like_nmea(bytes(raw_preview)):
                        print(
                            "\nReceived serial data, but it looks like ASCII/NMEA rather than "
                            "Nooploop Tag_Frame0/Node_Frame2. "
                            "Change T0 Protocol in NAssistant or extend the parser. "
                            + preview,
                            flush=True,
                        )
                    else:
                        print(
                            "\nReceived serial data, but it does not match Nooploop "
                            "Tag_Frame0/Node_Frame2. "
                            "Check T0 Protocol/Baudrate in NAssistant. "
                            + preview,
                            flush=True,
                        )
                last_warn_time = now
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        with contextlib.suppress(Exception, KeyboardInterrupt):
            ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
