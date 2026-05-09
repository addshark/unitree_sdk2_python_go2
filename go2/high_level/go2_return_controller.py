import contextlib
import glob
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import serial


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from imuuwb import read_imu_angles, read_uwb_coords


def candidate_ports() -> Tuple[str, ...]:
    ports = []
    ports.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    ports.extend(sorted(glob.glob("/dev/ttyACM*")))
    ports.extend(sorted(glob.glob("/dev/ttyUSB*")))
    ports.extend(sorted(glob.glob("/dev/ttyCH343USB*")))
    return tuple(dict.fromkeys(ports))


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


def close_serial_port(ser: Optional[serial.Serial]) -> None:
    if ser is None:
        return
    with contextlib.suppress(Exception):
        ser.close()


def interruptible_sleep(seconds: float, stop_event: threading.Event) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return False
        time.sleep(min(0.05, deadline - time.monotonic()))
    return True


def normalize_angle_deg(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class RecordedLocation:
    x: float
    y: float
    z: float
    recorded_at: float


@dataclass(frozen=True)
class RecordedDirection:
    yaw_deg: float
    recorded_at: float


@dataclass(frozen=True)
class ReturnTuning:
    control_interval: float = 0.2
    sensor_stale_timeout: float = 1.0
    sensor_wait_timeout: float = 2.0
    position_tolerance: float = 0.15
    yaw_tolerance_deg: float = 5.0
    position_kp: float = 0.8
    yaw_kp: float = 1.5
    max_linear_speed: float = 0.5
    max_lateral_speed: float = 0.20
    max_yaw_speed: float = 0.50
    min_linear_speed: float = 0.06
    min_yaw_speed: float = 0.12
    goback_timeout: float = 30.0
    back_direction_timeout: float = 15.0


class SensorHub:
    def __init__(
        self,
        imu_port: str,
        imu_baud: int,
        uwb_port: str,
        uwb_baud: int,
        serial_timeout: float,
        tuning: ReturnTuning,
    ):
        self.imu_port_request = imu_port
        self.imu_baud = imu_baud
        self.uwb_port_request = uwb_port
        self.uwb_baud = uwb_baud
        self.serial_timeout = serial_timeout
        self.tuning = tuning

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._imu_thread = threading.Thread(target=self._imu_loop, daemon=True)
        self._uwb_thread = threading.Thread(target=self._uwb_loop, daemon=True)

        self.imu_port_actual: Optional[str] = None
        self.uwb_port_actual: Optional[str] = None
        self.imu_status = "init"
        self.uwb_status = "init"
        self.imu_error: Optional[str] = None
        self.uwb_error: Optional[str] = None
        self.latest_imu: Optional[read_imu_angles.ImuSample] = None
        self.latest_uwb: Optional[read_uwb_coords.UwbSample] = None
        self.latest_uwb_received_at: Optional[float] = None
        self.recorded_location: Optional[RecordedLocation] = None
        self.recorded_direction: Optional[RecordedDirection] = None

    def start(self) -> None:
        self._imu_thread.start()
        self._uwb_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._imu_thread.join(timeout=2.0)
        self._uwb_thread.join(timeout=2.0)

    def _set_imu_status(self, status: str, error: Optional[str] = None, port: Optional[str] = None) -> None:
        with self._lock:
            self.imu_status = status
            self.imu_error = error
            if port is not None:
                self.imu_port_actual = port

    def _set_uwb_status(self, status: str, error: Optional[str] = None, port: Optional[str] = None) -> None:
        with self._lock:
            self.uwb_status = status
            self.uwb_error = error
            if port is not None:
                self.uwb_port_actual = port

    def _update_imu_sample(self, port: str, sample: read_imu_angles.ImuSample) -> None:
        with self._lock:
            self.latest_imu = sample
            self.imu_port_actual = port
            self.imu_status = "streaming"
            self.imu_error = None

    def _update_uwb_sample(self, port: str, sample: read_uwb_coords.UwbSample) -> None:
        with self._lock:
            self.latest_uwb = sample
            self.latest_uwb_received_at = time.time()
            self.uwb_port_actual = port
            self.uwb_status = "streaming"
            self.uwb_error = None

    def _resolve_requested_port(self, requested: str) -> Tuple[str, ...]:
        if requested != "auto":
            return (requested,)
        return candidate_ports()

    def _imu_loop(self) -> None:
        while not self._stop_event.is_set():
            ports = self._resolve_requested_port(self.imu_port_request)
            if not ports:
                self._set_imu_status("not_found", "no serial ports")
                self._stop_event.wait(1.0)
                continue

            connected = False
            for port in ports:
                if self._stop_event.is_set():
                    return
                if self._stream_imu_port(port):
                    connected = True
                    break
            if not connected:
                self._stop_event.wait(0.8)

    def _stream_imu_port(self, port: str) -> bool:
        try:
            ser = open_serial_port(port, self.imu_baud, self.serial_timeout)
        except serial.SerialException as exc:
            self._set_imu_status("open_fail", str(exc), port)
            return False

        self._set_imu_status("opened", None, port)
        print(f"IMU sensor connected on {port} @ {self.imu_baud}")
        buffer = bytearray()
        had_frame = False
        probe_deadline = None
        last_frame_time = time.monotonic()
        if self.imu_port_request == "auto":
            probe_deadline = time.monotonic() + self.tuning.sensor_wait_timeout
        try:
            while not self._stop_event.is_set():
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
                    self._update_imu_sample(port, sample)
                    had_frame = True
                    last_frame_time = time.monotonic()
                if probe_deadline is not None and not had_frame and time.monotonic() >= probe_deadline:
                    self._set_imu_status("probe_no_frame", f"no IMU frames on {port}", port)
                    break
                if had_frame and time.monotonic() - last_frame_time > self.tuning.sensor_stale_timeout:
                    raise RuntimeError(f"no fresh IMU frames on {port}, reconnecting")
        except Exception as exc:
            self._set_imu_status("error", str(exc), port)
            print(f"IMU sensor stream lost on {port}: {exc}")
        finally:
            close_serial_port(ser)
        return had_frame

    def _uwb_loop(self) -> None:
        while not self._stop_event.is_set():
            ports = self._resolve_requested_port(self.uwb_port_request)
            if not ports:
                self._set_uwb_status("not_found", "no serial ports")
                self._stop_event.wait(1.0)
                continue

            connected = False
            for port in ports:
                if self._stop_event.is_set():
                    return
                if self._stream_uwb_port(port):
                    connected = True
                    break
            if not connected:
                self._stop_event.wait(0.8)

    def _stream_uwb_port(self, port: str) -> bool:
        try:
            ser = open_serial_port(port, self.uwb_baud, self.serial_timeout)
        except serial.SerialException as exc:
            self._set_uwb_status("open_fail", str(exc), port)
            return False

        self._set_uwb_status("opened", None, port)
        print(f"UWB sensor connected on {port} @ {self.uwb_baud}")
        buffer = bytearray()
        had_frame = False
        probe_deadline = None
        last_frame_time = time.monotonic()
        if self.uwb_port_request == "auto":
            probe_deadline = time.monotonic() + self.tuning.sensor_wait_timeout
        try:
            while not self._stop_event.is_set():
                chunk = ser.read(4096)
                if chunk:
                    buffer.extend(chunk)
                while True:
                    frame = read_uwb_coords.extract_frame(buffer, "auto")
                    if frame is None:
                        break
                    sample = read_uwb_coords.parse_frame(frame)
                    self._update_uwb_sample(port, sample)
                    had_frame = True
                    last_frame_time = time.monotonic()
                if probe_deadline is not None and not had_frame and time.monotonic() >= probe_deadline:
                    self._set_uwb_status("probe_no_frame", f"no UWB frames on {port}", port)
                    break
                if had_frame and time.monotonic() - last_frame_time > self.tuning.sensor_stale_timeout:
                    raise RuntimeError(f"no fresh UWB frames on {port}, reconnecting")
        except Exception as exc:
            self._set_uwb_status("error", str(exc), port)
            print(f"UWB sensor stream lost on {port}: {exc}")
        finally:
            close_serial_port(ser)
        return had_frame

    def _fresh_imu(self) -> Optional[read_imu_angles.ImuSample]:
        with self._lock:
            sample = self.latest_imu
        if sample is None:
            return None
        if time.time() - sample.timestamp > self.tuning.sensor_stale_timeout:
            return None
        return sample

    def _fresh_uwb(self) -> Optional[read_uwb_coords.UwbSample]:
        with self._lock:
            sample = self.latest_uwb
            received_at = self.latest_uwb_received_at
        if sample is None:
            return None
        if received_at is None:
            return None
        if time.time() - received_at > self.tuning.sensor_stale_timeout:
            return None
        return sample

    def get_latest_imu(self, wait_timeout: Optional[float] = None) -> read_imu_angles.ImuSample:
        deadline = time.monotonic() + (wait_timeout or self.tuning.sensor_wait_timeout)
        while time.monotonic() < deadline:
            sample = self._fresh_imu()
            if sample is not None:
                return sample
            time.sleep(0.05)
        raise RuntimeError(f"IMU data unavailable; status={self.imu_status}, error={self.imu_error}")

    def get_latest_uwb(self, wait_timeout: Optional[float] = None) -> read_uwb_coords.UwbSample:
        deadline = time.monotonic() + (wait_timeout or self.tuning.sensor_wait_timeout)
        while time.monotonic() < deadline:
            sample = self._fresh_uwb()
            if sample is not None:
                return sample
            time.sleep(0.05)
        raise RuntimeError(f"UWB data unavailable; status={self.uwb_status}, error={self.uwb_error}")

    def get_latest_valid_uwb(self, wait_timeout: Optional[float] = None) -> read_uwb_coords.UwbSample:
        deadline = time.monotonic() + (wait_timeout or self.tuning.sensor_wait_timeout)
        last_sample: Optional[read_uwb_coords.UwbSample] = None
        while time.monotonic() < deadline:
            sample = self._fresh_uwb()
            if sample is not None:
                last_sample = sample
                if sample.position_valid:
                    return sample
            time.sleep(0.05)
        if last_sample is not None:
            raise RuntimeError(
                "UWB position invalid; "
                f"pos=({last_sample.x:.3f},{last_sample.y:.3f},{last_sample.z:.3f}) "
                f"eop=({last_sample.eop_x},{last_sample.eop_y},{last_sample.eop_z}) "
                f"anchors={last_sample.valid_node_quantity}"
            )
        raise RuntimeError(f"UWB data unavailable; status={self.uwb_status}, error={self.uwb_error}")

    def record_location_now(self) -> RecordedLocation:
        sample = self.get_latest_valid_uwb()
        record = RecordedLocation(x=sample.x, y=sample.y, z=sample.z, recorded_at=time.time())
        with self._lock:
            self.recorded_location = record
        print(
            "Recorded UWB location: "
            f"x={record.x:.3f} m, y={record.y:.3f} m, z={record.z:.3f} m"
        )
        return record

    def record_direction_now(self) -> RecordedDirection:
        sample = self.get_latest_imu()
        record = RecordedDirection(yaw_deg=normalize_angle_deg(sample.yaw_deg), recorded_at=time.time())
        with self._lock:
            self.recorded_direction = record
        print(f"Recorded IMU yaw: {record.yaw_deg:.3f} deg")
        return record

    def get_recorded_location(self) -> RecordedLocation:
        with self._lock:
            record = self.recorded_location
        if record is None:
            raise RuntimeError("location not recorded; send recordlocation first")
        return record

    def get_recorded_direction(self) -> RecordedDirection:
        with self._lock:
            record = self.recorded_direction
        if record is None:
            raise RuntimeError("direction not recorded; send record_direction first")
        return record

    def debug_summary(self) -> str:
        with self._lock:
            imu_port = self.imu_port_actual
            uwb_port = self.uwb_port_actual
            imu_status = self.imu_status
            uwb_status = self.uwb_status
            latest_imu = self.latest_imu
            latest_uwb = self.latest_uwb
            recorded_location = self.recorded_location
            recorded_direction = self.recorded_direction

        imu_text = "none"
        if latest_imu is not None:
            imu_text = (
                f"yaw={latest_imu.yaw_deg:.2f} deg "
                f"(roll={latest_imu.roll_deg:.2f}, pitch={latest_imu.pitch_deg:.2f})"
            )

        uwb_text = "none"
        if latest_uwb is not None:
            uwb_text = (
                f"x={latest_uwb.x:.3f}, y={latest_uwb.y:.3f}, z={latest_uwb.z:.3f}, "
                f"status={read_uwb_coords.position_status_text(latest_uwb)}"
            )

        location_text = "none"
        if recorded_location is not None:
            location_text = (
                f"x={recorded_location.x:.3f}, y={recorded_location.y:.3f}, z={recorded_location.z:.3f}"
            )

        direction_text = "none"
        if recorded_direction is not None:
            direction_text = f"yaw={recorded_direction.yaw_deg:.3f} deg"

        return (
            f"IMU[{imu_status} port={imu_port}] {imu_text}; "
            f"UWB[{uwb_status} port={uwb_port}] {uwb_text}; "
            f"recorded_location={location_text}; "
            f"recorded_direction={direction_text}"
        )


class ReturnController:
    def __init__(self, sensor_hub: SensorHub, tuning: ReturnTuning):
        self.sensor_hub = sensor_hub
        self.tuning = tuning

    def record_location(self) -> RecordedLocation:
        return self.sensor_hub.record_location_now()

    def record_direction(self) -> RecordedDirection:
        return self.sensor_hub.record_direction_now()

    def _stop_and_restore_economic_gait(self, client, action_name: str) -> None:
        try:
            stop_ret = client.Move(0.0, 0.0, 0.0)
            print(f"{action_name} zero Move ret: {stop_ret}")
        except Exception as exc:
            print(f"{action_name} zero Move error: {exc}")

        try:
            gait_ret = client.EconomicGait()
            print(f"{action_name} EconomicGait ret: {gait_ret}")
        except Exception as exc:
            print(f"{action_name} EconomicGait error: {exc}")

    def _position_command(
        self,
        target: RecordedLocation,
        current,
    ) -> Tuple[float, float, float, float, float, float, float, bool]:
        dx_world = target.x - current.x
        dy_world = target.y - current.y
        distance = math.hypot(dx_world, dy_world)
        forward_delta = dy_world
        lateral_delta = -dx_world

        if distance <= self.tuning.position_tolerance:
            return dx_world, dy_world, forward_delta, lateral_delta, distance, 0.0, 0.0, True

        vx = (
            math.copysign(self.tuning.max_linear_speed, forward_delta)
            if abs(forward_delta) > self.tuning.position_tolerance
            else 0.0
        )
        vy = (
            math.copysign(self.tuning.max_lateral_speed, lateral_delta)
            if abs(lateral_delta) > self.tuning.position_tolerance
            else 0.0
        )

        speed_norm = math.hypot(vx, vy)
        if speed_norm > self.tuning.max_linear_speed:
            scale = self.tuning.max_linear_speed / speed_norm
            vx *= scale
            vy *= scale

        return dx_world, dy_world, forward_delta, lateral_delta, distance, vx, vy, False

    def _yaw_command(self, target_yaw_deg: float, current_yaw_deg: float) -> Tuple[float, float, bool]:
        yaw_error_deg = normalize_angle_deg(target_yaw_deg - current_yaw_deg)
        if abs(yaw_error_deg) <= self.tuning.yaw_tolerance_deg:
            return yaw_error_deg, 0.0, True
        return yaw_error_deg, math.copysign(self.tuning.max_yaw_speed, yaw_error_deg), False

    def goback(self, client, stop_event: threading.Event) -> int:
        target = self.sensor_hub.get_recorded_location()
        deadline = time.monotonic() + self.tuning.goback_timeout
        last_ret = 0
        print(
            "goback start: "
            f"target=({target.x:.3f}, {target.y:.3f}, {target.z:.3f}), "
            f"tolerance={self.tuning.position_tolerance:.3f} m"
        )

        try:
            while time.monotonic() < deadline:
                if stop_event.is_set():
                    print("goback interrupted by stop/damp command")
                    break

                current = self.sensor_hub.get_latest_valid_uwb(wait_timeout=0.5)
                (
                    dx_world,
                    dy_world,
                    forward_delta,
                    lateral_delta,
                    distance,
                    vx,
                    vy,
                    position_reached,
                ) = self._position_command(target, current)
                if position_reached:
                    print(
                        "goback reached target: "
                        f"current=({current.x:.3f}, {current.y:.3f}), "
                        f"remaining={distance:.3f} m"
                    )
                    break

                last_ret = client.Move(vx, vy, 0.0)
                print(
                    "goback step: "
                    f"current=({current.x:.3f}, {current.y:.3f}) "
                    f"target=({target.x:.3f}, {target.y:.3f}) "
                    f"uwb_delta=({dx_world:.3f}, {dy_world:.3f}) "
                    f"cmd_delta=(forward={forward_delta:.3f}, lateral={lateral_delta:.3f}) "
                    f"distance={distance:.3f} "
                    f"cmd=(vx={vx:.3f}, vy={vy:.3f}) ret={last_ret}"
                )

                if not interruptible_sleep(self.tuning.control_interval, stop_event):
                    print("goback interrupted during control interval")
                    break
            else:
                raise RuntimeError(
                    f"goback timed out after {self.tuning.goback_timeout:.1f}s"
                )
        finally:
            self._stop_and_restore_economic_gait(client, "goback")

        return last_ret

    def back_direction(self, client, stop_event: threading.Event) -> int:
        target = self.sensor_hub.get_recorded_direction()
        deadline = time.monotonic() + self.tuning.back_direction_timeout
        last_ret = 0
        print(
            "back_direction start: "
            f"target_yaw={target.yaw_deg:.3f} deg, "
            f"tolerance={self.tuning.yaw_tolerance_deg:.3f} deg"
        )

        try:
            while time.monotonic() < deadline:
                if stop_event.is_set():
                    print("back_direction interrupted by stop/damp command")
                    break

                current = self.sensor_hub.get_latest_imu(wait_timeout=0.5)
                yaw_error_deg, yaw_rate, yaw_reached = self._yaw_command(target.yaw_deg, current.yaw_deg)
                if yaw_reached:
                    print(
                        "back_direction reached target: "
                        f"current_yaw={current.yaw_deg:.3f} deg, "
                        f"error={yaw_error_deg:.3f} deg"
                    )
                    break

                last_ret = client.Move(0.0, 0.0, yaw_rate)
                print(
                    "back_direction step: "
                    f"current_yaw={current.yaw_deg:.3f} deg "
                    f"target_yaw={target.yaw_deg:.3f} deg "
                    f"error={yaw_error_deg:.3f} deg "
                    f"cmd_yaw_rate={yaw_rate:.3f} rad/s ret={last_ret}"
                )

                if not interruptible_sleep(self.tuning.control_interval, stop_event):
                    print("back_direction interrupted during control interval")
                    break
            else:
                raise RuntimeError(
                    f"back_direction timed out after {self.tuning.back_direction_timeout:.1f}s"
                )
        finally:
            self._stop_and_restore_economic_gait(client, "back_direction")

        return last_ret

    def return_pose(self, client, stop_event: threading.Event) -> int:
        location_target = self.sensor_hub.get_recorded_location()
        direction_target = self.sensor_hub.get_recorded_direction()
        deadline = time.monotonic() + max(
            self.tuning.goback_timeout,
            self.tuning.back_direction_timeout,
        )
        last_ret = 0
        print(
            "return_pose start: "
            f"target=({location_target.x:.3f}, {location_target.y:.3f}, {location_target.z:.3f}), "
            f"target_yaw={direction_target.yaw_deg:.3f} deg, "
            f"pos_tol={self.tuning.position_tolerance:.3f} m, "
            f"yaw_tol={self.tuning.yaw_tolerance_deg:.3f} deg"
        )

        try:
            while time.monotonic() < deadline:
                if stop_event.is_set():
                    print("return_pose interrupted by stop/damp command")
                    break

                current_uwb = self.sensor_hub.get_latest_valid_uwb(wait_timeout=0.5)
                current_imu = self.sensor_hub.get_latest_imu(wait_timeout=0.5)
                (
                    dx_world,
                    dy_world,
                    forward_delta,
                    lateral_delta,
                    distance,
                    vx,
                    vy,
                    position_reached,
                ) = self._position_command(location_target, current_uwb)
                yaw_error_deg, yaw_rate, yaw_reached = self._yaw_command(
                    direction_target.yaw_deg,
                    current_imu.yaw_deg,
                )

                if position_reached and yaw_reached:
                    print(
                        "return_pose reached target: "
                        f"current=({current_uwb.x:.3f}, {current_uwb.y:.3f}) "
                        f"current_yaw={current_imu.yaw_deg:.3f} deg "
                        f"remaining={distance:.3f} m "
                        f"yaw_error={yaw_error_deg:.3f} deg"
                    )
                    break

                last_ret = client.Move(vx, vy, yaw_rate)
                print(
                    "return_pose step: "
                    f"current=({current_uwb.x:.3f}, {current_uwb.y:.3f}) "
                    f"target=({location_target.x:.3f}, {location_target.y:.3f}) "
                    f"current_yaw={current_imu.yaw_deg:.3f} deg "
                    f"target_yaw={direction_target.yaw_deg:.3f} deg "
                    f"uwb_delta=({dx_world:.3f}, {dy_world:.3f}) "
                    f"cmd_delta=(forward={forward_delta:.3f}, lateral={lateral_delta:.3f}) "
                    f"distance={distance:.3f} "
                    f"yaw_error={yaw_error_deg:.3f} deg "
                    f"cmd=(vx={vx:.3f}, vy={vy:.3f}, vyaw={yaw_rate:.3f}) ret={last_ret}"
                )

                if not interruptible_sleep(self.tuning.control_interval, stop_event):
                    print("return_pose interrupted during control interval")
                    break
            else:
                raise RuntimeError(
                    "return_pose timed out after "
                    f"{max(self.tuning.goback_timeout, self.tuning.back_direction_timeout):.1f}s"
                )
        finally:
            self._stop_and_restore_economic_gait(client, "return_pose")

        return last_ret
