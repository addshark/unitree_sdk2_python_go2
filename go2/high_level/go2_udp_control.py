import argparse
import ipaddress
import json
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Tuple

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_
from unitree_sdk2py.go2.sport.sport_client import SportClient


DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 8082
DEFAULT_STATUS_PORT = 8083
DEFAULT_STATUS_INTERVAL = 0.2
LINEAR_SPEED = 0.3
YAW_SPEED = 0.5
STAND_MOVE_DELAY = 3.0


@dataclass(frozen=True)
class Action:
    id: int
    name: str
    description: str
    aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalAddress:
    interface: str
    address: str
    prefix: int
    broadcast: str


ACTIONS = [
    Action(0, "damp", "阻尼模式，电机进入阻尼，不主动保持运动"),
    Action(1, "stand_up", "站立"),
    Action(23, "stand_move", "组合动作：先站立，再进入 free walk"),
    Action(2, "stand_down", "趴下/卧倒"),
    Action(3, "move forward", "前进"),
    Action(20, "move backward", "后退"),
    Action(4, "move left", "左移", ("move lateral",)),
    Action(21, "move right", "右移"),
    Action(5, "rotate left", "左转", ("move rotate",)),
    Action(22, "rotate right", "右转"),
    Action(6, "stop_move", "停止速度运动"),
    Action(7, "hand stand", "倒立动作，风险较高"),
    Action(9, "balanced stand", "平衡站立"),
    Action(10, "recovery", "摔倒恢复/恢复站立"),
    Action(11, "left flip", "左翻，风险高"),
    Action(12, "back flip", "后空翻，风险高"),
    Action(13, "free walk", "自由行走/特殊步态"),
    Action(14, "free bound", "bounding 跳跃步态开关"),
    Action(15, "free avoid", "自由避障模式开关"),
    Action(17, "walk upright", "直立行走动作开关"),
    Action(18, "cross step", "交叉步动作开关"),
    Action(19, "free jump", "跳跃动作开关"),
]

ACTION_BY_ID: Dict[int, Action] = {action.id: action for action in ACTIONS}
ACTION_BY_NAME: Dict[str, Action] = {}
STOP_ACTION_IDS = {0, 6}


def numeric_or_none(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def list_values(values: Iterable, cast: Callable) -> list:
    return [cast(value) for value in values]


class RobotStateCache:
    def __init__(self):
        self._lock = threading.Lock()
        self.low_state: Optional[LowState_] = None
        self.low_state_time: Optional[float] = None
        self.sport_state: Optional[SportModeState_] = None
        self.sport_state_time: Optional[float] = None
        self.last_action: Optional[dict] = None

    def update_low_state(self, msg: LowState_) -> None:
        with self._lock:
            self.low_state = msg
            self.low_state_time = time.time()

    def update_sport_state(self, msg: SportModeState_) -> None:
        with self._lock:
            self.sport_state = msg
            self.sport_state_time = time.time()

    def update_last_action(self, action: Action, ret: Optional[int], status: str) -> None:
        with self._lock:
            self.last_action = {
                "id": action.id,
                "name": action.name,
                "ret": ret,
                "status": status,
                "time": time.time(),
            }

    def snapshot(self) -> dict:
        with self._lock:
            low_state = self.low_state
            low_state_time = self.low_state_time
            sport_state = self.sport_state
            sport_state_time = self.sport_state_time
            last_action = dict(self.last_action) if self.last_action else None

        battery = None
        if low_state is not None:
            bms_state = low_state.bms_state
            battery = {
                "soc": int_or_none(getattr(bms_state, "soc", None)),
                "voltage": numeric_or_none(getattr(low_state, "power_v", None)),
                "current": numeric_or_none(getattr(low_state, "power_a", None)),
                "bms_current": int_or_none(getattr(bms_state, "current", None)),
                "status": int_or_none(getattr(bms_state, "status", None)),
                "cycle": int_or_none(getattr(bms_state, "cycle", None)),
            }

        sport = None
        if sport_state is not None:
            sport = {
                "mode": int_or_none(getattr(sport_state, "mode", None)),
                "gait_type": int_or_none(getattr(sport_state, "gait_type", None)),
                "progress": numeric_or_none(getattr(sport_state, "progress", None)),
                "body_height": numeric_or_none(getattr(sport_state, "body_height", None)),
                "position": list_values(getattr(sport_state, "position", []), float),
                "velocity": list_values(getattr(sport_state, "velocity", []), float),
                "yaw_speed": numeric_or_none(getattr(sport_state, "yaw_speed", None)),
                "range_obstacle": list_values(getattr(sport_state, "range_obstacle", []), float),
                "foot_force": list_values(getattr(sport_state, "foot_force", []), int),
            }

        return {
            "battery": battery,
            "sport": sport,
            "low_state_age": None if low_state_time is None else time.time() - low_state_time,
            "sport_state_age": None if sport_state_time is None else time.time() - sport_state_time,
            "last_action": last_action,
        }


def normalize_command(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("-", " ").replace("_", " ")
    return " ".join(value.split())


for _action in ACTIONS:
    ACTION_BY_NAME[normalize_command(_action.name)] = _action
    for _alias in _action.aliases:
        ACTION_BY_NAME[normalize_command(_alias)] = _action


def action_table_text() -> str:
    lines = ["Go2 UDP actions:"]
    for action in ACTIONS:
        lines.append(f"{action.id}: {action.name} - {action.description}")
    return "\n".join(lines)


def command_from_packet(packet: bytes) -> str:
    text = packet.decode("utf-8", errors="ignore").strip().strip("\x00")
    if not text:
        raise ValueError("empty command")

    if text[0] in "{[":
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("id", "cmd", "command", "action", "name"):
                if key in data:
                    return str(data[key]).strip()
        raise ValueError("json command must contain id/cmd/command/action/name")

    return text


def resolve_action(command: str) -> Optional[Action]:
    command = command.strip()
    if not command:
        return None

    try:
        return ACTION_BY_ID[int(command)]
    except (KeyError, ValueError):
        pass

    return ACTION_BY_NAME.get(normalize_command(command))


def interruptible_sleep(seconds: float, stop_event: threading.Event) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return False
        time.sleep(min(0.1, deadline - time.monotonic()))
    return True


def run_timed_switch(
    name: str,
    enable: Callable[[bool], int],
    seconds: float,
    stop_event: threading.Event,
) -> int:
    ret = enable(True)
    print(f"{name}(True) ret: {ret}")
    completed = interruptible_sleep(seconds, stop_event)
    ret = enable(False)
    print(f"{name}(False) ret: {ret}")
    if not completed:
        print(f"{name} interrupted by stop/damp command")
    return ret


def run_stand_move(client: SportClient, stop_event: threading.Event) -> int:
    ret = client.StandUp()
    print(f"StandUp ret: {ret}")
    completed = interruptible_sleep(STAND_MOVE_DELAY, stop_event)
    if not completed:
        print("stand_move interrupted before FreeWalk")
        return ret

    ret = client.FreeWalk()
    print(f"FreeWalk ret: {ret}")
    return ret


def execute_action(
    client: SportClient,
    action: Action,
    stop_event: threading.Event,
    state_cache: RobotStateCache,
) -> None:
    print(f"Executing id={action.id}, name={action.name}")
    ret = None

    if action.id == 0:
        ret = client.Damp()
    elif action.id == 1:
        ret = client.StandUp()
    elif action.id == 23:
        ret = run_stand_move(client, stop_event)
    elif action.id == 2:
        ret = client.StandDown()
    elif action.id == 3:
        ret = client.Move(LINEAR_SPEED, 0, 0)
    elif action.id == 20:
        ret = client.Move(-LINEAR_SPEED, 0, 0)
    elif action.id == 4:
        ret = client.Move(0, LINEAR_SPEED, 0)
    elif action.id == 21:
        ret = client.Move(0, -LINEAR_SPEED, 0)
    elif action.id == 5:
        ret = client.Move(0, 0, YAW_SPEED)
    elif action.id == 22:
        ret = client.Move(0, 0, -YAW_SPEED)
    elif action.id == 6:
        ret = client.StopMove()
    elif action.id == 7:
        ret = run_timed_switch("HandStand", client.HandStand, 4.0, stop_event)
    elif action.id == 9:
        ret = client.BalanceStand()
    elif action.id == 10:
        ret = client.RecoveryStand()
    elif action.id == 11:
        ret = client.LeftFlip()
    elif action.id == 12:
        ret = client.BackFlip()
    elif action.id == 13:
        ret = client.FreeWalk()
    elif action.id == 14:
        ret = run_timed_switch("FreeBound", client.FreeBound, 2.0, stop_event)
    elif action.id == 15:
        ret = run_timed_switch("FreeAvoid", client.FreeAvoid, 2.0, stop_event)
    elif action.id == 17:
        ret = run_timed_switch("WalkUpright", client.WalkUpright, 4.0, stop_event)
    elif action.id == 18:
        ret = run_timed_switch("CrossStep", client.CrossStep, 4.0, stop_event)
    elif action.id == 19:
        ret = run_timed_switch("FreeJump", client.FreeJump, 4.0, stop_event)
    else:
        raise ValueError(f"unsupported action id: {action.id}")

    state_cache.update_last_action(action, ret, "done")
    print(f"Done id={action.id}, name={action.name}, ret={ret}")
    if action.id in STOP_ACTION_IDS:
        stop_event.clear()


def action_worker(
    client: SportClient,
    actions: "queue.Queue[Action]",
    stop_event: threading.Event,
    state_cache: RobotStateCache,
) -> None:
    while True:
        action = actions.get()
        try:
            state_cache.update_last_action(action, None, "executing")
            execute_action(client, action, stop_event, state_cache)
        except Exception as exc:
            state_cache.update_last_action(action, None, f"failed: {exc}")
            print(f"Action failed id={action.id}, name={action.name}: {exc}", file=sys.stderr)
        finally:
            actions.task_done()


def clear_pending_actions(actions: "queue.Queue[Action]") -> None:
    while True:
        try:
            actions.get_nowait()
            actions.task_done()
        except queue.Empty:
            return


def local_ipv4_addresses() -> Tuple[LocalAddress, ...]:
    addresses = []
    try:
        output = subprocess.check_output(
            ["ip", "-brief", "-4", "addr"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ()

    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        interface = parts[0]
        for item in parts[2:]:
            if "/" in item:
                try:
                    ip_interface = ipaddress.ip_interface(item)
                except ValueError:
                    break
                addresses.append(
                    LocalAddress(
                        interface=interface,
                        address=str(ip_interface.ip),
                        prefix=ip_interface.network.prefixlen,
                        broadcast=str(ip_interface.network.broadcast_address),
                    )
                )
                break
    return tuple(addresses)


def lan_addresses(dds_interface: str) -> Tuple[LocalAddress, ...]:
    addresses = []
    for item in local_ipv4_addresses():
        if item.interface == "lo" or item.address.startswith("127."):
            continue
        if item.interface == dds_interface:
            continue
        if item.interface.startswith(("docker", "br-", "veth")):
            continue
        addresses.append(item)
    return tuple(addresses)


def interface_ip(name: str) -> Optional[str]:
    for item in local_ipv4_addresses():
        if item.interface == name:
            return item.address
    return None


def print_udp_targets(bind_address: str, port: int) -> None:
    addresses = local_ipv4_addresses()
    if bind_address != DEFAULT_BIND:
        print(f"External UDP target: {bind_address}:{port}")
        return

    if not addresses:
        print(f"Listening on all local IPv4 addresses, UDP port {port}")
        return

    print("External devices should send UDP to one of these local addresses:")
    for item in addresses:
        print(f"  {item.interface}: {item.address}:{port}")
    print("Use the LAN/Wi-Fi address for computers on the same LAN; eth0 192.168.123.x is usually the Go2 DDS network.")


def status_broadcast_targets(args: argparse.Namespace) -> Tuple[str, ...]:
    if args.broadcast_host:
        return tuple(args.broadcast_host)

    targets = [item.broadcast for item in lan_addresses(args.interface)]
    if not targets:
        targets = [DEFAULT_BIND.replace("0.0.0.0", "255.255.255.255")]
    return tuple(dict.fromkeys(targets))


def build_status_payload(
    args: argparse.Namespace,
    state_cache: RobotStateCache,
    actions: "queue.Queue[Action]",
) -> bytes:
    state = state_cache.snapshot()
    battery = state.get("battery") or {}
    payload = {
        "wlan0_ip": interface_ip("wlan0"),
        "battery_soc": battery.get("soc"),
        "sport": state.get("sport"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def status_broadcast_worker(
    args: argparse.Namespace,
    state_cache: RobotStateCache,
    actions: "queue.Queue[Action]",
) -> None:
    targets = status_broadcast_targets(args)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print(f"Broadcasting status every {args.status_interval:.3f}s to UDP port {args.status_port}:")
    for target in targets:
        print(f"  {target}:{args.status_port}")

    while True:
        payload = build_status_payload(args, state_cache, actions)
        for target in targets:
            try:
                sock.sendto(payload, (target, args.status_port))
            except OSError as exc:
                print(f"Status broadcast failed to {target}:{args.status_port}: {exc}", file=sys.stderr)
        time.sleep(args.status_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive UDP commands and control Unitree Go2 SportClient.")
    parser.add_argument("interface", help="DDS network interface connected to Go2, for example eth0")
    parser.add_argument("--bind", default=DEFAULT_BIND, help=f"UDP bind address, default {DEFAULT_BIND}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"UDP listen port, default {DEFAULT_PORT}")
    parser.add_argument("--status-port", type=int, default=DEFAULT_STATUS_PORT, help=f"UDP status broadcast port, default {DEFAULT_STATUS_PORT}")
    parser.add_argument("--status-interval", type=float, default=DEFAULT_STATUS_INTERVAL, help=f"Status broadcast interval seconds, default {DEFAULT_STATUS_INTERVAL}")
    parser.add_argument("--broadcast-host", action="append", help="Status broadcast host. Can be repeated. Default: auto LAN broadcast address.")
    parser.add_argument("--timeout", type=float, default=10.0, help="SportClient RPC timeout seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("WARNING: UDP commands will control the robot. Keep the area clear and keep an emergency stop ready.")
    print(f"DDS interface: {args.interface}")
    ChannelFactoryInitialize(0, args.interface)

    state_cache = RobotStateCache()
    lowstate_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
    lowstate_subscriber.Init(state_cache.update_low_state, 10)
    sportstate_subscriber = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sportstate_subscriber.Init(state_cache.update_sport_state, 10)

    client = SportClient()
    client.SetTimeout(args.timeout)
    client.Init()

    stop_event = threading.Event()
    actions: "queue.Queue[Action]" = queue.Queue(maxsize=50)
    worker = threading.Thread(target=action_worker, args=(client, actions, stop_event, state_cache), daemon=True)
    worker.start()
    broadcaster = threading.Thread(target=status_broadcast_worker, args=(args, state_cache, actions), daemon=True)
    broadcaster.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    print(f"Listening UDP on {args.bind}:{args.port}")
    print_udp_targets(args.bind, args.port)
    print("Send action id/name, or 'list'. JSON is also accepted: {\"id\": 3} or {\"cmd\": \"move forward\"}.")

    while True:
        packet, address = sock.recvfrom(4096)
        try:
            command = command_from_packet(packet)
            if normalize_command(command) in {"list", "help"}:
                sock.sendto(action_table_text().encode("utf-8"), address)
                continue

            action = resolve_action(command)
            if action is None:
                response = f"ERROR unknown command: {command}"
                print(f"{address[0]}:{address[1]} -> {response}")
                sock.sendto(response.encode("utf-8"), address)
                continue

            if action.id in STOP_ACTION_IDS:
                stop_event.set()
                clear_pending_actions(actions)

            actions.put_nowait(action)
            response = f"OK queued id={action.id}, name={action.name}"
            print(f"{address[0]}:{address[1]} -> {response}")
            sock.sendto(response.encode("utf-8"), address)
        except queue.Full:
            response = "ERROR action queue full"
            print(f"{address[0]}:{address[1]} -> {response}")
            sock.sendto(response.encode("utf-8"), address)
        except Exception as exc:
            response = f"ERROR {exc}"
            print(f"{address[0]}:{address[1]} -> {response}")
            sock.sendto(response.encode("utf-8"), address)


if __name__ == "__main__":
    raise SystemExit(main())
