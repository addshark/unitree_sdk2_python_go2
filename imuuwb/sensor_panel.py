#!/usr/bin/env python3

import argparse
import contextlib
import glob
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import serial

import read_imu_angles
import read_uwb_coords


@dataclass
class StreamState:
    kind: str
    port: Optional[str] = None
    baud: Optional[int] = None
    status: str = "waiting"
    error: Optional[str] = None
    total_bytes: int = 0
    last_update: Optional[float] = None
    preview: bytes = b""
    imu_sample: Optional[read_imu_angles.ImuSample] = None
    uwb_sample: Optional[read_uwb_coords.UwbSample] = None
    stop_event: threading.Event = field(default_factory=threading.Event)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Show a real-time IMU + UWB terminal panel."
    )
    parser.add_argument(
        "--imu-port",
        default="auto",
        help="IMU serial port, or auto. Default: auto",
    )
    parser.add_argument(
        "--uwb-port",
        default="auto",
        help="UWB serial port, or auto. Default: auto",
    )
    parser.add_argument(
        "--imu-baud",
        type=int,
        default=115200,
        help="IMU baud rate, default: 115200",
    )
    parser.add_argument(
        "--uwb-baud",
        type=int,
        default=921600,
        help="UWB baud rate, default: 921600",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=0.2,
        help="Panel refresh interval in seconds, default: 0.2",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=1.5,
        help="Auto-detect probe timeout in seconds, default: 1.5",
    )
    return parser.parse_args()


def candidate_ports():
    return sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))


def shorten_port(port: Optional[str]) -> str:
    if not port:
        return "-"
    return os.path.basename(port)


def detect_imu_port(ports, baud: int, timeout: float):
    for port in ports:
        try:
            ser = serial.Serial(port, baudrate=baud, timeout=0.2)
        except serial.SerialException:
            continue

        buffer = bytearray()
        start = time.time()
        try:
            while time.time() - start < timeout:
                chunk = ser.read(4096)
                if chunk:
                    buffer.extend(chunk)
                while True:
                    frame = read_imu_angles.extract_frame(buffer)
                    if frame is None:
                        break
                    if frame[1] != read_imu_angles.ANGLE_FRAME_TYPE:
                        continue
                    sample = read_imu_angles.parse_angle_frame(frame)
                    return port, sample
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                ser.close()
    return None, None


def detect_uwb_port(ports, baud: int, timeout: float):
    for port in ports:
        try:
            ser = serial.Serial(port, baudrate=baud, timeout=0.2)
        except serial.SerialException:
            continue

        buffer = bytearray()
        start = time.time()
        try:
            while time.time() - start < timeout:
                chunk = ser.read(4096)
                if chunk:
                    buffer.extend(chunk)
                while True:
                    frame = read_uwb_coords.extract_frame(buffer, "auto")
                    if frame is None:
                        break
                    sample = read_uwb_coords.parse_frame(frame)
                    return port, sample
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                ser.close()
    return None, None


def imu_reader(state: StreamState):
    if not state.port or state.baud is None:
        state.status = "not_found"
        state.error = "IMU port not found"
        return

    state.status = "opening"
    try:
        ser = serial.Serial(state.port, baudrate=state.baud, timeout=0.2)
    except serial.SerialException as exc:
        state.status = "open_fail"
        state.error = str(exc)
        return

    state.status = "streaming"
    buffer = bytearray()

    try:
        while not state.stop_event.is_set():
            chunk = ser.read(4096)
            if chunk:
                state.total_bytes += len(chunk)
                if len(state.preview) < 64:
                    state.preview += chunk[: 64 - len(state.preview)]
                buffer.extend(chunk)

            while True:
                frame = read_imu_angles.extract_frame(buffer)
                if frame is None:
                    break
                if frame[1] != read_imu_angles.ANGLE_FRAME_TYPE:
                    continue
                state.imu_sample = read_imu_angles.parse_angle_frame(frame)
                state.last_update = state.imu_sample.timestamp
                state.status = "streaming"
                state.error = None
    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
    finally:
        with contextlib.suppress(Exception):
            ser.close()


def uwb_reader(state: StreamState):
    if not state.port or state.baud is None:
        state.status = "not_found"
        state.error = "UWB port not found"
        return

    state.status = "opening"
    try:
        ser = serial.Serial(state.port, baudrate=state.baud, timeout=0.2)
    except serial.SerialException as exc:
        state.status = "open_fail"
        state.error = str(exc)
        return

    state.status = "streaming"
    buffer = bytearray()

    try:
        while not state.stop_event.is_set():
            chunk = ser.read(4096)
            if chunk:
                state.total_bytes += len(chunk)
                if len(state.preview) < 64:
                    state.preview += chunk[: 64 - len(state.preview)]
                buffer.extend(chunk)

            while True:
                frame = read_uwb_coords.extract_frame(buffer, "auto")
                if frame is None:
                    break
                state.uwb_sample = read_uwb_coords.parse_frame(frame)
                state.last_update = time.time()
                state.status = "streaming"
                state.error = None
    except Exception as exc:
        state.status = "error"
        state.error = str(exc)
    finally:
        with contextlib.suppress(Exception):
            ser.close()


def age_text(ts: Optional[float]) -> str:
    if ts is None:
        return "-"
    age_ms = max(0.0, (time.time() - ts) * 1000.0)
    return f"{age_ms:6.0f} ms"


def preview_text(data: bytes) -> str:
    if not data:
        return "-"
    snippet = data[:24]
    return snippet.hex(" ")


def render_panel(imu_state: StreamState, uwb_state: StreamState):
    lines = []
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines.append("IMU + UWB Sensor Panel")
    lines.append(f"time      : {now}")
    lines.append("")

    lines.append("IMU")
    lines.append(f"  port    : {shorten_port(imu_state.port)}")
    lines.append(f"  baud    : {imu_state.baud or '-'}")
    lines.append(f"  status  : {imu_state.status}")
    lines.append(f"  bytes   : {imu_state.total_bytes}")
    lines.append(f"  age     : {age_text(imu_state.last_update)}")
    if imu_state.imu_sample:
        lines.append(
            "  angle   : "
            f"roll={imu_state.imu_sample.roll_deg:8.3f} deg  "
            f"pitch={imu_state.imu_sample.pitch_deg:8.3f} deg  "
            f"yaw={imu_state.imu_sample.yaw_deg:8.3f} deg"
        )
    else:
        lines.append("  angle   : -")
    if imu_state.error:
        lines.append(f"  error   : {imu_state.error}")
    lines.append(f"  preview : {preview_text(imu_state.preview)}")
    lines.append("")

    lines.append("UWB")
    lines.append(f"  port    : {shorten_port(uwb_state.port)}")
    lines.append(f"  baud    : {uwb_state.baud or '-'}")
    lines.append(f"  status  : {uwb_state.status}")
    lines.append(f"  bytes   : {uwb_state.total_bytes}")
    lines.append(f"  age     : {age_text(uwb_state.last_update)}")
    if uwb_state.uwb_sample:
        sample = uwb_state.uwb_sample
        lines.append(
            "  pos     : "
            f"x={sample.x:7.3f} m  y={sample.y:7.3f} m  z={sample.z:7.3f} m"
        )
        lines.append(
            "  vel     : "
            f"vx={sample.vx:7.4f} m/s  vy={sample.vy:7.4f} m/s  vz={sample.vz:7.4f} m/s"
        )
        lines.append(
            "  meta    : "
            f"{sample.frame_name}  "
            f"{read_uwb_coords.role_name(sample.role)}{sample.node_id}  "
            f"voltage={sample.voltage_v:.3f} V"
        )
        if sample.eop_x is not None and sample.eop_y is not None and sample.eop_z is not None:
            lines.append(
                "  eop     : "
                f"x={sample.eop_x:.2f} m  y={sample.eop_y:.2f} m  z={sample.eop_z:.2f} m"
            )
    else:
        lines.append("  pos     : -")
        lines.append("  vel     : -")
        lines.append("  meta    : -")
    if uwb_state.error:
        lines.append(f"  error   : {uwb_state.error}")
    lines.append(f"  preview : {preview_text(uwb_state.preview)}")
    lines.append("")
    lines.append("Press Ctrl+C to exit.")
    return "\n".join(lines)


def main():
    args = parse_args()
    ports = candidate_ports()

    imu_port = args.imu_port
    uwb_port = args.uwb_port
    imu_probe = None
    uwb_probe = None

    if imu_port == "auto":
        imu_port, imu_probe = detect_imu_port(ports, args.imu_baud, args.probe_timeout)
    if uwb_port == "auto":
        remaining = [port for port in ports if port != imu_port]
        uwb_port, uwb_probe = detect_uwb_port(remaining, args.uwb_baud, args.probe_timeout)

    imu_state = StreamState(kind="imu", port=imu_port, baud=args.imu_baud)
    uwb_state = StreamState(kind="uwb", port=uwb_port, baud=args.uwb_baud)
    if imu_probe is not None:
        imu_state.imu_sample = imu_probe
        imu_state.last_update = imu_probe.timestamp
    if uwb_probe is not None:
        uwb_state.uwb_sample = uwb_probe
        uwb_state.last_update = time.time()

    imu_thread = threading.Thread(target=imu_reader, args=(imu_state,), daemon=True)
    uwb_thread = threading.Thread(target=uwb_reader, args=(uwb_state,), daemon=True)
    imu_thread.start()
    uwb_thread.start()

    try:
        while True:
            print("\x1b[2J\x1b[H" + render_panel(imu_state, uwb_state), end="", flush=True)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        return 0
    finally:
        imu_state.stop_event.set()
        uwb_state.stop_event.set()
        imu_thread.join(timeout=1.0)
        uwb_thread.join(timeout=1.0)
        print()


if __name__ == "__main__":
    raise SystemExit(main())
