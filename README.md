# unitree_sdk2_python_go2

这个仓库当前只保留两部分内容：

- `go2/`
  - Go2 高层/底层示例
  - UDP 局域网控制
  - UDP 状态广播
  - 动作说明文档
- `imuuwb/`
  - `read_imu_angles.py`
  - `read_uwb_coords.py`
  - `sensor_panel.py`

## 目录说明

```text
go2/      Go2 运动控制与说明
imuuwb/   IMU / UWB 读取与综合显示
```

## 常用命令

## 一键部署到新机器

如果新机器能访问 GitHub，可以直接运行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/addshark/unitree_sdk2_python_go2/main/deploy_from_github.sh)
```

这个脚本会自动完成：

- 安装系统依赖
- 从 GitHub 克隆 `unitree_sdk2_python_go2`
- 创建 `.venv`
- 编译安装 `CycloneDDS`
- 安装 Python 依赖
- 安装并启用 `go2-udp-control.service` 开机自启

如果需要指定串口或速度参数，也可以这样：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/addshark/unitree_sdk2_python_go2/main/deploy_from_github.sh) -- \
  --dds-interface eth0 \
  --imu-port /dev/ttyUSB0 \
  --uwb-port /dev/ttyACM0 \
  --goback-max-speed 0.4 \
  --goback-max-lateral-speed 0.35 \
  --back-direction-max-yaw-speed 0.70
```

### Go2 UDP 控制

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 go2/high_level/go2_udp_control.py eth0
```

如果这个仓库是通过 `deploy_from_github.sh` 部署出来的，依赖默认安装在仓库内的 `.venv`，手动运行时要优先使用：

```bash
cd /home/unitree/unitree_sdk2_python_go2
.venv/bin/python go2/high_level/go2_udp_control.py eth0
```

### IMU 单独查看

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/read_imu_angles.py --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 --baud 115200
```

### UWB 单独查看

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/read_uwb_coords.py --port /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B53035556-if00 --baud 921600
```

如果输出长期固定为 `x=1.000 y=1.000 z=1.000`，同时 `eop` 也是 `2.55/2.55/2.55`，程序现在会把它标成 `pos_status=invalid_default`。这表示串口帧存在，但当前定位结果无效，不能拿来做 `recordlocation` 或 `goback`。

### IMU + UWB 综合面板

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/sensor_panel.py
```

默认端口是：

- IMU: `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- UWB: `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B53035556-if00`

只看 UWB：

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/sensor_panel.py --imu-port off
```

只看 IMU：

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/sensor_panel.py --uwb-port off
```

注意：`go2/high_level/go2_udp_control.py`、`imuuwb/sensor_panel.py`、`imuuwb/read_imu_angles.py`、`imuuwb/read_uwb_coords.py` 不能同时读取同一个串口。

## 文档

- Go2 控制说明：`go2/README.md`
