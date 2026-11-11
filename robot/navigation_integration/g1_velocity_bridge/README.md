# G1 导航速度桥

接收现有完整安全链之后的 `/cmd_vel_preview`，通过 Unitree SDK2 的 G1 `LocoClient::SetVelocity` 接到原厂运动控制器。SDK 使用 PC2 的 `eth0`，SSH 可使用无线 IP。没有改动 FAST-LIO、ICP、规划算法或原速度闸门。

此桥直接使用 SDK2，检查每次速度调用的返回值。PC2 的 FastDDS 环境中，直接发布旧 ROS `unitree_api/Request` 的只读查询没有得到回执；SDK2 本机调用查询正常，故没有直接复用旧 `ws_slam` 的消息转发节点。旧桥的 `wz_sign=-1` 配合旧里程计的 z 四元数反号；当前 `nav_adapter` 使用直立坐标，默认 `yaw_sign=+1`。2026-10-07 的低速实机试验已记录正转向命令对应正里程计转角，完整结果见本地诊断记录。

SDK 配套 `libddscxx` 必须和同目录 `libddsc` 一起使用；ROS 环境原先把同名 DDS 库覆盖，导致 SDK 初始化崩溃。此桥通过自己的 RPATH 固定配套库，并使用 FastDDS 处理 ROS 消息，不改全局库或其他节点。

当前默认多航点逻辑（2026-10-17）是连续通过：接收原子 `/nav3d/mission`（nav_msgs/Path），
整条任务仅授权一次；中间进入0.6m范围只更新通过进度，不重开Goal、不等待站稳/朝向/音频。
最后一个点才通过 `/nav3d/goal_reached` 撤销任务授权并停车。
标准 `/nav3d/plan` 必须与当前请求的frame和时间戳完全匹配，旧空路径不会误撤销当前授权。
取消、完成或重新enable后，旧任务/旧Goal不能重新激活。原有健康、超时、FSM和限速保护继续生效。
下方终点转向说明属于保留的旧显式align模式；默认连续任务及普通单点Goal不走该分支。

终点转向（2026-10-16）：仅在 `aligning_goal_yaw` 阶段，从 `/nav/cmd_vel_raw` 取最新角速度，跳过角速度平滑爬升，前进强制为零。仍要求完整速度链输出新鲜、导航健康、新目标已获确认路径、原厂状态允许，以及原始指令未超过0.3秒；角速度仍受桥上限限制。等待、障碍、完成、失败等控制器状态直接归零。正常沿路径行走继续使用 `/cmd_vel_preview` 的平滑速度。现配置转向请求固定0.8rad/s，最终容差20°；已经开始转向时在15°内收零，留5°回摆余量，新目标原本在20°内则不启动转向。

转向号按机器标定：统一导航和独立桥均支持 `yaw_sign:=±1.0`，默认读取
`G1_YAW_SIGN`（未设置时为 +1.0）。2026-10-16 的联合实机记录确认：
SDK 负号对应原厂 IMU 和 FAST-LIO yaw 同时减小，正号对应同时增加；当前 PC2
使用 `G1_YAW_SIGN=+1.0`，撤回此前根据分离快照做出的负号判断。转向响应和
停转阈值仍需按原厂模式实测。`/nav/hardware_cmd_vel`
显示应用正负号之后的 SDK 指令，不是 ROS 导航约定下的期望角速度。

旧显式align模式的终点转向幅度为0.8rad/s。速度与健康订阅使用最新样本、best-effort QoS，保留
0.3 秒失效停车；桥状态附带 `cmd_age`、`health_age` 便于查超时。

## 已有导航保持运行时

```bash
bash /home/unitree/nav_ws/start_nav_velocity_bridge.sh \
  dry_run:=false prepare_walkrun_on_enable:=false
```

独立桥启动后默认禁止运动，仅查询原厂状态；统一导航自动待命，仍需新的 Goal 和确认路径。默认保留遥控器选择的原厂步态，放行 FSM 500、501、802 和现场确认的越障 812；其他状态阻止速度。`prepare_walkrun_on_enable=true` 仅允许在 SDK StandUp（FSM 4）且新 Goal、路径、健康数据有效时接入 WALKRUN，不能覆盖已选择的步态或未知状态。后台自定义 `g1_ctrl` 如果开始运行，桥拒绝原厂运动并关闭输出。

现场机器人站稳、通道已确认、操作者能随时停车后，再明确启用：

```bash
source /home/unitree/nav_ws/localization_env.sh
ros2 service call /nav/enable_motion std_srvs/srv/SetBool '{data: true}'
```

启用会清掉旧目标状态，等待新的多航点任务或RViz单点Goal。桥会核对转换到map的 `/nav3d/goal` 和同时间戳 `/nav3d/plan`，再等待新路径后的速度。不会执行启用之前的旧任务。

当前限制：用户于2026-10-08要求前进上限1.0 m/s、角速度上限0.8 rad/s。跟踪器、速度平滑器、闸门和SDK桥均使用对应上限；平滑器后退上限保持0.10 m/s，无侧向速度。命令或导航健康消息超过0.30秒即停；SDK单次速度有效期0.50秒。原厂状态查询交替执行，每轮只查询一次，避免连续两次RPC阻塞速度刷新。当前启动配置的 `trial_seconds`、`travel_limit`、`turn_limit` 均为0，不按单目标时长、累计行程或累计转角关闭输出。

设置上述三个预算参数为正值可以恢复相应试验保护；不传配置直接运行可执行文件时仍使用原短距离默认值。取消预算不代表完整实体跟踪或平台越障已验证。SDK 返回成功只表示接受命令，不能代替对实际运动的观察。

## 停车和查看状态

```bash
ros2 service call /nav/enable_motion std_srvs/srv/SetBool '{data: false}'
ros2 topic echo /nav/bridge_status
ros2 topic echo /nav/hardware_cmd_vel
```

`/nav/hardware_cmd_vel` 为限速后实际尝试发送的机体速度监视话题；在 dry run 中仅表示拟发送值。状态包含 live/dry_run、等待/禁用/超时原因、原厂 FSM 与上次 SDK 速度回执。没有自动重试控制权切换。

2026-10-19：SDK返回3104表示回执超时，进入最多10秒的 `sdk_timeout_recovering`，不立即取消任务。恢复期间只发零速，每隔至少0.5秒重试；连续3次零速成功且跨度至少1秒、重新查询的原厂FSM/模式有效、定位健康/路径/速度输入新鲜，才恢复。恢复当轮仍为零，并要求下一条新速度和新原始转角，不能重放故障前残留。控制器暂停转向无进展计时，任务节点保留当前站点并显示“SDK通信恢复中”。恢复成功后继续原任务，无需重新开始。

零速也超时时可以继续零速探测，但10秒仍未满足条件、非3104错误、60秒内第四次超时事件会停用并取消任务。取消、手动禁用、新任务与旧路径的授权检查仍生效；显式重新启用只恢复待命，要求新任务，不能复活已取消任务。失联时有限指令有效期兜底，未加长SDK单次0.2秒RPC等待或0.5秒运动有效期。恢复逻辑经隔离软件测试验证，故障后的实机恢复行走尚未验证。

源构建：`colcon build --packages-select g1_velocity_bridge`。复用 PC2 `/home/unitree/unitree_sdk2`，可用 CMake 参数 `-DUNITREE_SDK2_ROOT=/路径` 指定同架构 SDK。孤立 ROS 域测试必须使用 `dry_run=true`；SDK 自身使用机器人 DDS 域 0，不能仅凭 ROS 域隔离推断硬件隔离。
