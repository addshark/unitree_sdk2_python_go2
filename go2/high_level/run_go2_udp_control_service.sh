#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
DDS_INTERFACE="${DDS_INTERFACE:-eth0}"
UDP_BIND="${UDP_BIND:-0.0.0.0}"
UDP_PORT="${UDP_PORT:-8082}"
UDP_STATUS_PORT="${UDP_STATUS_PORT:-8083}"
UDP_STATUS_INTERVAL="${UDP_STATUS_INTERVAL:-0.2}"
SPORT_TIMEOUT="${SPORT_TIMEOUT:-10.0}"
IMU_PORT="${IMU_PORT:-auto}"
IMU_BAUD="${IMU_BAUD:-115200}"
UWB_PORT="${UWB_PORT:-auto}"
UWB_BAUD="${UWB_BAUD:-921600}"
SENSOR_SERIAL_TIMEOUT="${SENSOR_SERIAL_TIMEOUT:-0.2}"
SENSOR_STALE_TIMEOUT="${SENSOR_STALE_TIMEOUT:-1.0}"
SENSOR_WAIT_TIMEOUT="${SENSOR_WAIT_TIMEOUT:-2.0}"
GOBACK_POSITION_TOLERANCE="${GOBACK_POSITION_TOLERANCE:-0.15}"
BACK_DIRECTION_TOLERANCE="${BACK_DIRECTION_TOLERANCE:-5.0}"
GOBACK_MAX_SPEED="${GOBACK_MAX_SPEED:-0.4}"
GOBACK_MAX_LATERAL_SPEED="${GOBACK_MAX_LATERAL_SPEED:-0.35}"
BACK_DIRECTION_MAX_YAW_SPEED="${BACK_DIRECTION_MAX_YAW_SPEED:-0.70}"
GOBACK_TIMEOUT="${GOBACK_TIMEOUT:-30.0}"
BACK_DIRECTION_TIMEOUT="${BACK_DIRECTION_TIMEOUT:-15.0}"
RETURN_CONTROL_INTERVAL="${RETURN_CONTROL_INTERVAL:-0.2}"

cmd=(
  "${PYTHON_BIN}"
  "${SCRIPT_DIR}/go2_udp_control.py"
  "${DDS_INTERFACE}"
  --bind "${UDP_BIND}"
  --port "${UDP_PORT}"
  --status-port "${UDP_STATUS_PORT}"
  --status-interval "${UDP_STATUS_INTERVAL}"
  --timeout "${SPORT_TIMEOUT}"
  --imu-port "${IMU_PORT}"
  --imu-baud "${IMU_BAUD}"
  --uwb-port "${UWB_PORT}"
  --uwb-baud "${UWB_BAUD}"
  --sensor-serial-timeout "${SENSOR_SERIAL_TIMEOUT}"
  --sensor-stale-timeout "${SENSOR_STALE_TIMEOUT}"
  --sensor-wait-timeout "${SENSOR_WAIT_TIMEOUT}"
  --goback-position-tolerance "${GOBACK_POSITION_TOLERANCE}"
  --back-direction-tolerance "${BACK_DIRECTION_TOLERANCE}"
  --goback-max-speed "${GOBACK_MAX_SPEED}"
  --goback-max-lateral-speed "${GOBACK_MAX_LATERAL_SPEED}"
  --back-direction-max-yaw-speed "${BACK_DIRECTION_MAX_YAW_SPEED}"
  --goback-timeout "${GOBACK_TIMEOUT}"
  --back-direction-timeout "${BACK_DIRECTION_TIMEOUT}"
  --return-control-interval "${RETURN_CONTROL_INTERVAL}"
)

if [[ -n "${BROADCAST_HOSTS:-}" ]]; then
  IFS=', ' read -r -a hosts <<< "${BROADCAST_HOSTS}"
  for host in "${hosts[@]}"; do
    [[ -n "${host}" ]] || continue
    cmd+=(--broadcast-host "${host}")
  done
fi

cd "${REPO_ROOT}"
exec "${cmd[@]}"
