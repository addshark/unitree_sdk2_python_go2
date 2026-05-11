#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO_URL="https://github.com/addshark/unitree_sdk2_python_go2.git"
DEFAULT_CYCLONEDDS_URL="https://github.com/eclipse-cyclonedds/cyclonedds.git"
DEFAULT_CYCLONEDDS_BRANCH="releases/0.10.x"

usage() {
  cat <<'EOF'
Usage:
  bash deploy_from_github.sh [options]

Options:
  --repo-url URL                    GitHub repository URL
  --branch NAME                     Git branch or tag to deploy
  --target-dir PATH                 Deploy target directory
  --service-user USER               User that runs the UDP systemd service
  --dds-interface NAME              DDS network interface, default eth0
  --imu-port PORT                   IMU serial port, default auto
  --uwb-port PORT                   UWB serial port, default auto
  --udp-port PORT                   UDP command port, default 8082
  --status-port PORT                UDP status broadcast port, default 8083
  --command-dedupe-window SECONDS   UDP same-action dedupe window, default 0.12
  --goback-max-speed VALUE          Goback forward/back speed
  --goback-max-lateral-speed VALUE  Goback lateral speed
  --back-direction-max-yaw-speed V  Back-direction yaw speed
  --skip-service                    Skip systemd service install/enable
  -h, --help                        Show this help

Examples:
  bash deploy_from_github.sh
  bash deploy_from_github.sh --branch main --dds-interface eth0
  bash deploy_from_github.sh --imu-port /dev/ttyUSB0 --uwb-port /dev/ttyACM0
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

current_user="${SUDO_USER:-${USER}}"
service_user="${current_user}"
repo_url="${DEFAULT_REPO_URL}"
branch=""
target_dir=""
dds_interface="eth0"
imu_port="auto"
imu_baud="115200"
uwb_port="auto"
uwb_baud="921600"
udp_bind="0.0.0.0"
udp_port="8082"
status_port="8083"
status_interval="0.2"
command_dedupe_window="0.12"
sport_timeout="10.0"
sensor_serial_timeout="0.2"
sensor_stale_timeout="1.0"
sensor_wait_timeout="2.0"
goback_position_tolerance="0.15"
back_direction_tolerance="5.0"
goback_max_speed="0.4"
goback_max_lateral_speed="0.35"
back_direction_max_yaw_speed="0.70"
goback_timeout="30.0"
back_direction_timeout="15.0"
return_control_interval="0.2"
broadcast_hosts=""
skip_service=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      repo_url="$2"
      shift 2
      ;;
    --branch)
      branch="$2"
      shift 2
      ;;
    --target-dir)
      target_dir="$2"
      shift 2
      ;;
    --service-user)
      service_user="$2"
      shift 2
      ;;
    --dds-interface)
      dds_interface="$2"
      shift 2
      ;;
    --imu-port)
      imu_port="$2"
      shift 2
      ;;
    --imu-baud)
      imu_baud="$2"
      shift 2
      ;;
    --uwb-port)
      uwb_port="$2"
      shift 2
      ;;
    --uwb-baud)
      uwb_baud="$2"
      shift 2
      ;;
    --udp-bind)
      udp_bind="$2"
      shift 2
      ;;
    --udp-port)
      udp_port="$2"
      shift 2
      ;;
    --status-port)
      status_port="$2"
      shift 2
      ;;
    --status-interval)
      status_interval="$2"
      shift 2
      ;;
    --command-dedupe-window)
      command_dedupe_window="$2"
      shift 2
      ;;
    --sport-timeout)
      sport_timeout="$2"
      shift 2
      ;;
    --sensor-serial-timeout)
      sensor_serial_timeout="$2"
      shift 2
      ;;
    --sensor-stale-timeout)
      sensor_stale_timeout="$2"
      shift 2
      ;;
    --sensor-wait-timeout)
      sensor_wait_timeout="$2"
      shift 2
      ;;
    --goback-position-tolerance)
      goback_position_tolerance="$2"
      shift 2
      ;;
    --back-direction-tolerance)
      back_direction_tolerance="$2"
      shift 2
      ;;
    --goback-max-speed)
      goback_max_speed="$2"
      shift 2
      ;;
    --goback-max-lateral-speed)
      goback_max_lateral_speed="$2"
      shift 2
      ;;
    --back-direction-max-yaw-speed)
      back_direction_max_yaw_speed="$2"
      shift 2
      ;;
    --goback-timeout)
      goback_timeout="$2"
      shift 2
      ;;
    --back-direction-timeout)
      back_direction_timeout="$2"
      shift 2
      ;;
    --return-control-interval)
      return_control_interval="$2"
      shift 2
      ;;
    --broadcast-hosts)
      broadcast_hosts="$2"
      shift 2
      ;;
    --skip-service)
      skip_service=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

id -u "${service_user}" >/dev/null 2>&1 || die "service user does not exist: ${service_user}"

if [[ -z "${target_dir}" ]]; then
  target_dir="/home/${service_user}/unitree_sdk2_python_go2"
fi

venv_dir="${target_dir}/.venv"
venv_python="${venv_dir}/bin/python"
cyclonedds_root="${target_dir}/.deps/cyclonedds"
cyclonedds_src="${cyclonedds_root}/src"
cyclonedds_build="${cyclonedds_root}/build"
cyclonedds_install="${cyclonedds_root}/install"

require_command git
require_command python3
require_command sudo

sudo -v

echo "==> Installing apt packages"
sudo apt-get update
sudo apt-get install -y \
  git \
  python3 \
  python3-pip \
  python3-venv \
  python3-dev \
  build-essential \
  cmake \
  pkg-config \
  libssl-dev

echo "==> Deploy target: ${target_dir}"
mkdir -p "$(dirname "${target_dir}")"

if [[ -d "${target_dir}/.git" ]]; then
  echo "==> Updating existing repository"
  git -C "${target_dir}" fetch --tags origin
  if [[ -n "${branch}" ]]; then
    git -C "${target_dir}" checkout "${branch}"
    git -C "${target_dir}" pull --ff-only origin "${branch}"
  else
    git -C "${target_dir}" pull --ff-only
  fi
elif [[ -e "${target_dir}" ]]; then
  die "target exists but is not a git repository: ${target_dir}"
else
  echo "==> Cloning repository from ${repo_url}"
  clone_args=()
  if [[ -n "${branch}" ]]; then
    clone_args+=(--branch "${branch}")
  fi
  git clone "${clone_args[@]}" "${repo_url}" "${target_dir}"
fi

chmod +x \
  "${target_dir}/deploy_from_github.sh" \
  "${target_dir}/go2/high_level/run_go2_udp_control_service.sh" \
  "${target_dir}/go2/high_level/install_go2_udp_control_service.sh"

echo "==> Creating Python virtual environment"
python3 -m venv "${venv_dir}"
"${venv_python}" -m pip install --upgrade pip setuptools wheel

echo "==> Building CycloneDDS"
mkdir -p "${cyclonedds_root}"
if [[ -d "${cyclonedds_src}/.git" ]]; then
  git -C "${cyclonedds_src}" fetch origin "${DEFAULT_CYCLONEDDS_BRANCH}"
  git -C "${cyclonedds_src}" checkout "${DEFAULT_CYCLONEDDS_BRANCH}"
  git -C "${cyclonedds_src}" pull --ff-only origin "${DEFAULT_CYCLONEDDS_BRANCH}"
else
  rm -rf "${cyclonedds_src}"
  git clone --branch "${DEFAULT_CYCLONEDDS_BRANCH}" --depth 1 "${DEFAULT_CYCLONEDDS_URL}" "${cyclonedds_src}"
fi

cmake -S "${cyclonedds_src}" -B "${cyclonedds_build}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${cyclonedds_install}" \
  -DBUILD_EXAMPLES=OFF
cmake --build "${cyclonedds_build}" --target install -j"$(nproc)"

echo "==> Installing Python dependencies"
export CYCLONEDDS_HOME="${cyclonedds_install}"
export CMAKE_PREFIX_PATH="${cyclonedds_install}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
export LD_LIBRARY_PATH="${cyclonedds_install}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
"${venv_python}" -m pip install -e "${target_dir}"

if [[ "${skip_service}" -eq 0 ]]; then
  echo "==> Writing service environment"
  env_tmp="$(mktemp)"
  cat > "${env_tmp}" <<EOF
PYTHON_BIN=${venv_python}
CYCLONEDDS_HOME=${cyclonedds_install}
DDS_INTERFACE=${dds_interface}
UDP_BIND=${udp_bind}
UDP_PORT=${udp_port}
UDP_STATUS_PORT=${status_port}
UDP_STATUS_INTERVAL=${status_interval}
UDP_COMMAND_DEDUPE_WINDOW=${command_dedupe_window}
SPORT_TIMEOUT=${sport_timeout}
IMU_PORT=${imu_port}
IMU_BAUD=${imu_baud}
UWB_PORT=${uwb_port}
UWB_BAUD=${uwb_baud}
SENSOR_SERIAL_TIMEOUT=${sensor_serial_timeout}
SENSOR_STALE_TIMEOUT=${sensor_stale_timeout}
SENSOR_WAIT_TIMEOUT=${sensor_wait_timeout}
GOBACK_POSITION_TOLERANCE=${goback_position_tolerance}
BACK_DIRECTION_TOLERANCE=${back_direction_tolerance}
GOBACK_MAX_SPEED=${goback_max_speed}
GOBACK_MAX_LATERAL_SPEED=${goback_max_lateral_speed}
BACK_DIRECTION_MAX_YAW_SPEED=${back_direction_max_yaw_speed}
GOBACK_TIMEOUT=${goback_timeout}
BACK_DIRECTION_TIMEOUT=${back_direction_timeout}
RETURN_CONTROL_INTERVAL=${return_control_interval}
EOF
  if [[ -n "${broadcast_hosts}" ]]; then
    printf 'BROADCAST_HOSTS=%s\n' "${broadcast_hosts}" >> "${env_tmp}"
  fi
  sudo install -m 644 "${env_tmp}" /etc/default/go2-udp-control
  rm -f "${env_tmp}"

  echo "==> Installing and enabling UDP systemd service"
  (
    cd "${target_dir}"
    SERVICE_USER="${service_user}" bash go2/high_level/install_go2_udp_control_service.sh
  )
fi

echo
echo "Deployment complete."
echo "Repository: ${target_dir}"
echo "Virtualenv python: ${venv_python}"
echo "Manual run: cd ${target_dir} && ${venv_python} go2/high_level/go2_udp_control.py ${dds_interface}"
if [[ "${skip_service}" -eq 0 ]]; then
  echo "Service: go2-udp-control.service"
  echo "Logs: sudo journalctl -u go2-udp-control.service -f"
  echo "Config: /etc/default/go2-udp-control"
fi
