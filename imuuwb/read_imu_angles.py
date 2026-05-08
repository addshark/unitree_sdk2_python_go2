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
FRAME_SIZE = 11
ANGLE_FRAME_TYPE = 0x53


@dataclasses.dataclass
class ImuSample:
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    timestamp: float


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read JY901-style IMU Euler angles from a serial port."
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyUSB0",
        help="Serial port path, default: /dev/ttyUSB0",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Baud rate, default: 115200",
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
        default=0.1,
        help="Minimum print interval in seconds, default: 0.1",
    )
    return parser.parse_args()


def checksum_ok(frame: bytes) -> bool:
    return (sum(frame[:10]) & 0xFF) == frame[10]


def extract_frame(buffer: bytearray) -> Optional[bytes]:
    while buffer:
        if buffer[0] != FRAME_HEADER:
            del buffer[0]
            continue

        if len(buffer) < FRAME_SIZE:
            return None

        frame = bytes(buffer[:FRAME_SIZE])
        if not checksum_ok(frame):
            del buffer[0]
            continue

        del buffer[:FRAME_SIZE]
        return frame

    return None


def parse_euler_degrees(frame: bytes):
    values = struct.unpack("<hhhh", frame[2:10])
    roll = values[0] / 32768.0 * 180.0
    pitch = values[1] / 32768.0 * 180.0
    yaw = values[2] / 32768.0 * 180.0
    return roll, pitch, yaw


def parse_angle_frame(frame: bytes) -> ImuSample:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"unexpected IMU frame size: {len(frame)}")
    if frame[0] != FRAME_HEADER or frame[1] != ANGLE_FRAME_TYPE:
        raise ValueError("not an IMU angle frame")
    if not checksum_ok(frame):
        raise ValueError("IMU checksum mismatch")

    roll, pitch, yaw = parse_euler_degrees(frame)
    return ImuSample(
        roll_deg=roll,
        pitch_deg=pitch,
        yaw_deg=yaw,
        timestamp=time.time(),
    )


def find_candidate_ports() -> List[str]:
    candidates = []
    candidates.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    candidates.extend(sorted(glob.glob("/dev/ttyACM*")))
    candidates.extend(sorted(glob.glob("/dev/ttyUSB*")))
    candidates.extend(sorted(glob.glob("/dev/ttyCH343USB*")))
    return list(dict.fromkeys(candidates))


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


def format_sample(sample: ImuSample, port: str) -> str:
    timestamp = time.strftime("%H:%M:%S", time.localtime(sample.timestamp))
    return (
        f"[{timestamp}] {port} "
        f"roll={sample.roll_deg:8.3f} deg  "
        f"pitch={sample.pitch_deg:8.3f} deg  "
        f"yaw={sample.yaw_deg:8.3f} deg"
    )


def main():
    args = parse_args()

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

    print(f"Reading IMU angles from {args.port} @ {args.baud}")

    buffer = bytearray()
    total_bytes = 0
    last_print_time = 0.0
    last_warn_time = time.monotonic()

    try:
        while True:
            chunk = ser.read(4096)
            if chunk:
                total_bytes += len(chunk)
                buffer.extend(chunk)

            while True:
                frame = extract_frame(buffer)
                if frame is None:
                    break
                if frame[1] != ANGLE_FRAME_TYPE:
                    continue

                sample = parse_angle_frame(frame)
                now = time.monotonic()
                if args.interval <= 0 or (now - last_print_time) >= args.interval:
                    print("\r" + format_sample(sample, args.port), end="", flush=True)
                    last_print_time = now
                    last_warn_time = now

            now = time.monotonic()
            if now - last_warn_time >= 3.0 and total_bytes == 0:
                print(
                    "\nNo serial bytes received yet from this port.",
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
