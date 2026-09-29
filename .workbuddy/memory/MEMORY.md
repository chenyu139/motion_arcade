# Motion Arcade 项目长期记忆

## 仓库与远程
- 本地路径：`/Users/chenyu/workspace/motion_arcade`
- Git 远程：`origin` = `git@github.com:chenyu139/motion_arcade.git`（SSH）
  - 2026-09-28 首次推送 `main` → `origin/main`，已建立上游跟踪。之后直接 `git push`/`git pull`。
  - 本机**未安装 gh CLI**，远程操作走 `git` + SSH；首次连 GitHub 需 `StrictHostKeyChecking=accept-new` 接受 host key。
- 主分支：`main`（与远程同名）。
- 项目性质：摄像头体感游戏厅，18 款四川文旅主题游戏（原 20 款已下架 2 款），**独立项目，不嵌入四川观察客户端**（2026-09-29 用户明确纠正："说了1000遍不嵌进川观"）。

## 关键工程约定（详见 README.md）
- **不入库**：MediaPipe 的 `.task` 模型、 `screenshots/`、`MotionArcade.app/`、`.git` 已从 207MB 瘦身到 ~9MB。
- **入库**：`face_detection_yunet_2023mar.onnx`、`haarcascade_frontalface_default.xml`、`assets/sprites/`（素材站真实精灵 + AI 生成精灵，缺图自动回退矢量画法）、`assets/bg/`（bevouliin 等素材站卡通背景）。
- 只改 `.py` 时**不用重跑** `packaging/build_app.sh`（`.app` 只封印启动器，Python 在包外）。
- 视觉后端多实现：`apple`/`mediapipe`/`onnx`/`opencv`，统一规范 COCO-17 + 手部 21 点；macOS 本机 MediaPipe 1.x 硬崩（SIGABRT），人脸走 YuNet、手部走肤色轮廓。
- 测试：`tools/test_input.py`(25) / `test_head.py`(71) / `test_games.py`(6) / `test_feedback.py`(15)；真机诊断 `main.py --probe`。

## 美术素材来源偏好（2026-09-29 用户明确指示，反复强调）
- 用户要求**从素材站下载真实素材**（OpenGameArt / bevouliin 等），**不考虑版权风险**，**不要用 AI 生成替代**。
- 动机：用户认为 AI 生成及程序绘制的素材"太难看"，要商业级别真实素材。
- 边界：四川主题专属素材（熊猫 / 川剧脸谱 / 三星堆 / 盖碗茶 / 火锅）素材站无对应，仍由 AI 生成兜底。
- 系统已支持"同名 PNG 覆盖即生效"，换素材零代码成本（`assets/sprites/`、`assets/bg/`）。
- 沙箱网络限制：仅 OpenGameArt 可稳定直连抓取；Kenney 下载收口到 itch.io、Wikimedia/Openverse 被封、Pixabay 需 key。
