# Go2 高层运动控制动作表

运行目录：

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 go2/high_level/go2_sport_client.py eth0
```

进入程序后输入 `list` 查看动作列表，输入动作 id 或动作名称执行。

## Move 速度方向

`SportClient.Move(vx, vy, vyaw)` 是速度控制：

| 参数 | 正数 | 负数 | 示例单位 |
| --- | --- | --- | --- |
| `vx` | 前进 | 后退 | m/s |
| `vy` | 左移 | 右移 | m/s |
| `vyaw` | 左转 | 右转 | rad/s |

当前示例默认线速度 `0.3`，转向角速度 `0.5`。第一次测试建议空旷环境、低速、随时准备急停。

## 动作对应表

| id | 输入名称 | SDK 调用 | 含义 |
| --- | --- | --- | --- |
| 0 | `damp` | `Damp()` | 阻尼模式，电机进入阻尼，不主动保持运动 |
| 1 | `stand_up` | `StandUp()` | 站立 |
| 23 | `stand_move` | `StandUp()` -> `EconomicGait()` | 组合动作：先站立，再进入经济步态 |
| 24 | `static walk` | `StaticWalk()` | 静态行走步态 |
| 25 | `trot run` | `TrotRun()` | 小跑/常规 trot 步态 |
| 26 | `economic gait` | `EconomicGait()` | 经济步态 |
| 27 | `classic walk` | `ClassicWalk(True/False)` | 经典常规步态开关 |
| 2 | `stand_down` | `StandDown()` | 趴下/卧倒 |
| 3 | `move forward` | `Move(+0.3, 0, 0)` | 前进 |
| 20 | `move backward` | `Move(-0.3, 0, 0)` | 后退 |
| 4 | `move left` | `Move(0, +0.3, 0)` | 左移，兼容旧输入 `move lateral` |
| 21 | `move right` | `Move(0, -0.3, 0)` | 右移 |
| 5 | `rotate left` | `Move(0, 0, +0.5)` | 左转，兼容旧输入 `move rotate` |
| 22 | `rotate right` | `Move(0, 0, -0.5)` | 右转 |
| 6 | `stop_move` | `StopMove()` | 停止速度运动 |
| 7 | `hand stand` | `HandStand(True/False)` | 倒立动作，风险较高 |
| 9 | `balanced stand` | `BalanceStand()` | 平衡站立 |
| 10 | `recovery` | `RecoveryStand()` | 摔倒恢复/恢复站立 |
| 11 | `left flip` | `LeftFlip()` | 左翻，风险高 |
| 12 | `back flip` | `BackFlip()` | 后空翻，风险高 |
| 13 | `free walk` | `FreeWalk()` | 自由行走/特殊步态 |
| 14 | `free bound` | `FreeBound(True/False)` | bounding 跳跃步态开关 |
| 15 | `free avoid` | `FreeAvoid(True/False)` | 自由避障模式开关 |
| 17 | `walk upright` | `WalkUpright(True/False)` | 直立行走动作开关 |
| 18 | `cross step` | `CrossStep(True/False)` | 交叉步动作开关 |
| 19 | `free jump` | `FreeJump(True/False)` | 跳跃动作开关 |
| 30 | `recordlocation` | 读取当前 UWB 坐标并保存 | 记录回位置目标点 |
| 31 | `goback` | 持续读取 UWB 并闭环移动 | 回到记录位置 |
| 32 | `record_direction` | 读取当前 IMU yaw 并保存 | 记录目标方向 |
| 33 | `back_direction` | 持续读取 IMU 并闭环转向 | 回到记录方向 |
| 34 | `return_pose` | 持续读取 UWB + IMU 并闭环移动/转向 | 同时回到记录位置和方向 |

## 常用测试顺序

```text
1   stand_up
9   balanced stand
3   move forward
6   stop_move
20  move backward
6   stop_move
21  move right
6   stop_move
22  rotate right
6   stop_move
2   stand_down
```

特殊动作如倒立、翻滚、跳跃类动作需要确保机器狗周围完全空旷，并确认电量和地面条件。

## UDP 局域网控制

UDP 接收程序：

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 go2/high_level/go2_udp_control.py eth0
```

这里的 `eth0` 是连接 Go2 的 DDS 网卡，不是其他电脑发送 UDP 时一定要用的目标 IP。

默认监听：

```text
0.0.0.0:8082
```

`0.0.0.0` 表示本机所有网卡都会接收 UDP。局域网内其他电脑要发到“这台控制板在同一个局域网里的 IP”，例如你当前测试到的：

```text
192.168.2.11:8082
```

不要从普通局域网电脑发到 `192.168.123.182:8082`，这个地址通常是 `eth0` 上连接 Go2 的机器人网段，其他电脑不在这个网段就到不了。程序启动时会打印可用目标地址，例如：

```text
External devices should send UDP to one of these local addresses:
  eth0: 192.168.123.182:8082
  wlan0: 192.168.2.11:8082
```

如果发送电脑在 Wi-Fi/普通局域网里，就使用 `wlan0` 对应的 `192.168.2.11:8082`。

也可以指定端口：

```bash
python3 go2/high_level/go2_udp_control.py eth0 --port 8082
```

## 开机自启

仓库里已经提供了 `systemd` 服务模板、启动脚本和安装脚本：

```bash
cd /home/unitree/unitree_sdk2_python_go2
bash go2/high_level/install_go2_udp_control_service.sh
```

安装脚本会：

- 把服务文件安装到 `/etc/systemd/system/go2-udp-control.service`
- 把示例配置复制到 `/etc/default/go2-udp-control`
- 执行 `systemctl enable --now go2-udp-control.service`

常用命令：

```bash
sudo systemctl status go2-udp-control.service
sudo systemctl restart go2-udp-control.service
sudo systemctl stop go2-udp-control.service
sudo journalctl -u go2-udp-control.service -f  看日志
```

配置文件：

```bash
sudo nano /etc/default/go2-udp-control
```

这里可以直接改：

- `DDS_INTERFACE`
- `IMU_PORT` / `UWB_PORT`
- `UDP_PORT` / `UDP_STATUS_PORT`
- `GOBACK_MAX_SPEED`
- `GOBACK_MAX_LATERAL_SPEED`
- `BACK_DIRECTION_MAX_YAW_SPEED`

如果是新机器从 GitHub 一键部署，直接运行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/addshark/unitree_sdk2_python_go2/main/deploy_from_github.sh)
```

如果网络变了，用下面命令重新确认本机 IP：

```bash
ip -brief addr
```

局域网内其他设备可以向 `192.168.2.11:8082` 发送 UDP 文本指令。程序支持三种格式：

```text
3
move forward
{"id": 3}
{"cmd": "move forward"}
```

发送示例：

```bash
echo -n "2" | nc -u -w1 192.168.2.11 8082
echo -n "3" | nc -u -w1 192.168.2.11 8082
echo -n "6" | nc -u -w1 192.168.2.11 8082
echo -n "20" | nc -u -w1 192.168.2.11 8082
echo -n "rotate right" | nc -u -w1 192.168.2.11 8082
```

没有 `nc` 时可以用 Python 发送：

```bash
python3 -c 'import socket; sock=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sock.sendto(b"3", ("192.168.2.11", 8082))'
```

UDP 程序收到 `list` 或 `help` 会返回动作列表：

```bash
echo -n "list" | nc -u -w1 192.168.2.11 8082
```

UDP 动作对应表和上面的高层动作表一致。收到 `stop_move`/`6` 或 `damp`/`0` 时，程序会清空尚未执行的排队动作，并中断正在计时的开关类动作，也会中断 `goback` / `back_direction` / `return_pose` 这类闭环动作。

UDP 接收程序额外增加了一个组合动作、四个常规步态动作和五个基于传感器的闭环命令：

| id | 输入名称 | 执行顺序 | 含义 |
| --- | --- | --- | --- |
| 23 | `stand_move` | `StandUp()` -> 等待约 `3s` -> `EconomicGait()` | 先站立，再进入经济步态 |
| 24 | `static walk` | `StaticWalk()` | 静态行走步态 |
| 25 | `trot run` | `TrotRun()` | 小跑/常规 trot 步态 |
| 26 | `economic gait` | `EconomicGait()` | 经济步态 |
| 27 | `classic walk` | `ClassicWalk(True)` -> 等待约 `4s` -> `ClassicWalk(False)` | 经典常规步态开关 |
| 30 | `recordlocation` | 读取当前 UWB `x/y/z` 并记录 | 记住当前位置 |
| 31 | `goback` | 不断读取当前 UWB 坐标，计算和记录点的差值，调用 `Move(vx, vy, 0)` 闭环回到目标位置 | 回位置 |
| 32 | `record_direction` | 读取当前 IMU `yaw` 并记录 | 记住当前朝向 |
| 33 | `back_direction` | 不断读取 IMU `yaw`，计算和记录朝向的误差，调用 `Move(0, 0, vyaw)` 闭环转回目标方向 | 回方向 |
| 34 | `return_pose` | 同时读取当前 UWB + IMU，计算位置误差和方向误差，调用 `Move(vx, vy, vyaw)` 同时调整 | 同时回位置和回方向 |

这些命令只在 `go2_udp_control.py` 里有，终端交互脚本 `go2_sport_client.py` 里没有这些 id。

发送示例：

```bash
echo -n "23" | nc -u -w1 192.168.2.11 8082
echo -n "stand_move" | nc -u -w1 192.168.2.11 8082
echo -n '{"cmd":"stand_move"}' | nc -u -w1 192.168.2.11 8082
echo -n "static walk" | nc -u -w1 192.168.2.11 8082
echo -n "trot run" | nc -u -w1 192.168.2.11 8082
echo -n "economic gait" | nc -u -w1 192.168.2.11 8082
echo -n "classic walk" | nc -u -w1 192.168.2.11 8082
echo -n "recordlocation" | nc -u -w1 192.168.2.11 8082
echo -n "goback" | nc -u -w1 192.168.2.11 8082
echo -n "record_direction" | nc -u -w1 192.168.2.11 8082
echo -n "back_direction" | nc -u -w1 192.168.2.11 8082
echo -n "return_pose" | nc -u -w1 192.168.2.11 8082
```

推荐使用顺序：

```text
1. recordlocation
2. record_direction
3. 机器人离开当前点
4. return_pose
5. 如果只想分开调位置/方向，再用 goback / back_direction
```

注意：`recordlocation`、`goback`、`return_pose` 依赖 UWB 的有效定位结果。如果 UWB 面板里长期显示 `x=1.000 y=1.000 z=1.000`，并且 `fix=invalid_default`、`eop` 接近 `2.55/2.55/2.55`，程序会拒绝录点和回位置，因为这类值通常只是设备的无效默认值，不是真实坐标。

优化说明：

- `goback` 不是简单按固定时间前进/后退，而是一直读取当前 UWB 坐标做闭环控制。
- `goback` 现在不再使用 IMU `yaw` 做世界坐标/机体坐标转换，而是直接按固定平面约定控制：UWB `+Y` 视为机器狗正前方，UWB `+X` 视为机器狗右侧，因此控制映射为 `vx <- dy`、`vy <- -dx`。
- `goback` 当前采用固定速度闭环：只根据目标点在前/后/左/右哪一侧决定移动方向；只要误差超过容差，就按设定的固定速度移动，进入容差后停止。
- `back_direction` 当前采用固定角速度闭环：只根据当前朝向在目标方向左侧还是右侧决定转向；只要误差超过容差，就按设定的固定角速度转动，进入容差后停止。
- `return_pose` 会在同一个闭环里同时计算 `vx`、`vy`、`vyaw`，也就是边回位置边回方向，同时调整。
- `goback`、`back_direction`、`return_pose` 结束时会先执行一次 `Move(0, 0, 0)` 清零速度，再切回 `EconomicGait()`，不再调用 `StopMove()`。
- `back_direction` 单独负责把朝向转回记录角度，这样位置控制和方向控制不会互相打架。
- 这三个闭环动作都会在终端打印调试信息，方便看记录值、当前位置、误差和当前控制输出。

如果 IMU/UWB 端口不是自动探测到的那一组，可以手动指定：

```bash
python3 go2/high_level/go2_udp_control.py eth0 \
  --imu-port /dev/ttyUSB0 \
  --uwb-port /dev/ttyACM0
```

常用闭环参数也可以单独调：

```bash
python3 go2/high_level/go2_udp_control.py eth0 \
  --goback-position-tolerance 0.10 \
  --back-direction-tolerance 3.0 \
  --goback-max-speed 0.20 \
  --back-direction-max-yaw-speed 0.40
```

## UDP 状态广播

同一个程序除了接收控制指令，还会每隔 `200ms` 向局域网发送一次 UDP 广播状态。

默认广播端口：

```text
8083
```

默认广播周期：

```text
0.2s
```

运行时不需要额外启动第二个程序，执行下面这条命令后，控制接收和状态广播会同时工作：

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 go2/high_level/go2_udp_control.py eth0
```

如果要改广播端口或周期：

```bash
python3 go2/high_level/go2_udp_control.py eth0 --status-port 8083 --status-interval 0.2
```

程序会自动选择非 Go2 DDS 网卡的局域网广播地址。例如当前机器上，控制电脑通常在 `wlan0` 对应的网段里，程序会向类似下面的地址广播：

```text
192.168.2.255:8083
```

如果你想手动指定广播目标，也可以这样：

```bash
python3 go2/high_level/go2_udp_control.py eth0 --broadcast-host 192.168.2.255
```

广播内容现在只保留三项：`wlan0` 的 IP、电量百分比和高层运动状态。典型字段如下：

```json
{
  "wlan0_ip": "192.168.2.11",
  "battery_soc": 86,
  "sport": {
    "mode": 1,
    "gait_type": 0,
    "progress": 0.0,
    "body_height": 0.0,
    "position": [0.0, 0.0, 0.0],
    "velocity": [0.0, 0.0, 0.0],
    "yaw_speed": 0.0,
    "range_obstacle": [0.0, 0.0, 0.0, 0.0],
    "foot_force": [0, 0, 0, 0]
  }
}
```

字段含义：

- `wlan0_ip`：本机 `wlan0` 网卡的 IP。当前机器通常是 `192.168.2.11`。
- `battery_soc`：电量百分比。
- `sport`：Go2 高层运动状态。

如果 `wlan0` 不存在，或者还没收到 Go2 的状态消息，对应字段会是 `null`。

在另一台电脑上监听广播：

```bash
nc -ul 8083
```

或者用 Python 监听：

```bash
python3 -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("", 8083)); print(s.recvfrom(65535)[0].decode())'
```

## IMU / UWB 面板

```bash
cd /home/unitree/unitree_sdk2_python_go2
python3 imuuwb/sensor_panel.py
```

注意：`go2/high_level/go2_udp_control.py` 自己已经内置 IMU/UWB 读取线程。如果它正在运行，就不要再同时开 `sensor_panel.py`、`read_imu_angles.py` 或 `read_uwb_coords.py` 去读同一个串口，否则会出现串口占用、读数中断或 `multiple access on port` 之类的问题。
