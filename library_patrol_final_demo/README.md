# library_patrol_final_demo

这是图书馆巡检机器人“最终视频演示集成层”。

它只负责统一调度 Web 展示、任务工单、语音命令占位、导航 HTTP API 调用、四段视频任务状态机，以及后续视觉 API 接入位置。

本工程不修改导航工程，不修改视觉工程，不启动雷达/摄像头/串口，也不直接控制小车。

## 第一版功能

- Web 控制台：地图、路径、小车位姿、业务点位、摄像头占位、工单状态。
- 导航客户端：通过现有 dashboard HTTP API 调用 `/api/goal` 和 `/api/patrol/start`。
- 四类演示任务：
  - 寻书引导
  - 书架错放巡检
  - 全图遗失物巡检
  - 高危点位检查
- 模拟语音命令：A2、A4、A5、A6。
- 视觉检测 stub：ArUco 图书、遗失物、高危点位。
- START_HOME：启动后尝试从导航 `/api/state` 的机器人当前位姿自动记录；失败时显示“起点未记录”。

## 启动方式

先手动启动导航工程：

```bash
cd ~/Library_Patrol_Project/robot_2k03011/robot_2k0301
BOARD_IP=192.168.43.192 ./scripts/start_navigation.sh
```

另开终端启动最终演示 Web：

```bash
cd ~/Library_Patrol_Project/library_patrol_final_demo
./scripts/start_demo_web.sh
```

浏览器访问：

```text
http://127.0.0.1:8090
```

也可以先只启动本 Web。此时页面会显示导航未连接，按钮可触发任务框架，但真实导航下发会失败并写入工单错误。

## 调试方式

模拟“语音 A2 -> 寻找百年孤独”：

1. 打开 `http://127.0.0.1:8090`。
2. 点击“调试模拟语音”里的“模拟 A2”。
3. 右侧工单应显示“寻书引导”，并记录“正在查找百年孤独”的播报占位。
4. 如果导航已启动，会向导航 dashboard 下发 `LIT_SHELF_A3` 目标点；到达后继续触发图书识别 stub 和找到图书播报。

测试“按钮 -> 书架错放巡检”：

1. 点击“书架错放巡检”。
2. Web 会调用本服务 `/api/demo/mission`。
3. 编排器会向导航 dashboard 调用 `/api/patrol/start`，路线为工科、理科、中间点、文学书架。
4. 到达工科/文学书架时，会写入对应错放工单并触发播报占位。

## 当前 Stub

- `app/voice_ci1302.py`：只支持模拟命令，不打开 `/dev/ttyS1`。
- `app/camera_proxy.py`：只返回“摄像头未启用”的占位 SVG，不连接板端 TCP/JPEG。
- `vision/aruco_book_detector.py`：固定返回《百年孤独》识别结果。
- `vision/lost_item_detector.py`：固定返回钥匙和校园卡。
- `vision/hazard_detector.py`：按 mode 固定返回高危结果。
- `vision/visual_api_client.py`：保留 Qwen-VL 客户端结构，不访问网络。

## 后续接入位置

- 真实语音 CI1302：实现 `app/voice_ci1302.py` 的 `VoiceCi1302Serial`，并在 `paths.json` 中开启 `voice.enabled`。
- 真实摄像头：实现 `app/camera_proxy.py` 的 `BoardJpegStreamClient`，接板端 4 字节长度 + JPEG TCP 流。
- 真实 ArUco 图书识别：把 E08 工程中的识别逻辑迁移到 `vision/aruco_book_detector.py`。
- Qwen-VL 遗失物/危险检测：把 E08 工程中的 API 调用迁移到 `vision/visual_api_client.py`，再由 `lost_item_detector.py` 和 `hazard_detector.py` 调用。
- 新增点位和路线：修改 `config/points.json`、`config/missions.json`。

## 安全边界

- 本工程不会执行 `colcon build`、`cmake`、`make` 或旧工程脚本。
- 本工程不会启动导航，只调用已存在的 dashboard HTTP API。
- 本工程不会写串口、不会连接摄像头、不会直接发布 `/cmd_vel`。
