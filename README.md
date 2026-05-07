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

### Go2 UDP 控制

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 go2/high_level/go2_udp_control.py eth0
```

### IMU 单独查看

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/read_imu_angles.py --port /dev/ttyUSB0 --baud 115200
```

### UWB 单独查看

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/read_uwb_coords.py --port /dev/ttyACM0 --baud 921600
```

### IMU + UWB 综合面板

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/sensor_panel.py
```

## 文档

- Go2 控制说明：`go2/README.md`
