"""
main.py
=======
体感游戏厅入口。

运行
    python main.py                  # 全屏启动，进入游戏大厅
    python main.py --windowed       # 窗口模式
    python main.py --game mario     # 直接进某个游戏
    python main.py --no-cam         # 不用摄像头（鼠标模拟手部 + 键盘）
    python main.py --list           # 列出全部游戏

大厅操作
    头部左右切卡片 · 抬头进入（唯一的进入方式，不靠停留计时）
    键盘：←→↑↓ 移动 / 回车进入 / 数字键快速选 / TAB 换游戏
    游戏内：ESC 返回大厅　R 重开　C 校准　P 暂停　H 摄像头预览　F11 全屏
"""
from __future__ import annotations

import argparse
import os
import sys

# 以 .app 启动时 stdout 被重定向到日志文件，默认块缓冲会让日志严重滞后，
# 改成行缓冲便于实时排查摄像头/后端问题。
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import config as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="体感游戏厅 · Motion Arcade")
    ap.add_argument("--vision", default="auto",
                    choices=["auto", "apple", "mediapipe", "onnx", "opencv"],
                    help="视觉后端：auto 按平台自动选（macOS→apple，Win/Linux→mediapipe）")
    ap.add_argument("--cam", type=int, default=C.CAM_INDEX, help="摄像头索引")
    ap.add_argument("--no-cam", action="store_true", help="不使用摄像头")
    ap.add_argument("--windowed", action="store_true", help="窗口模式启动（默认全屏）")
    ap.add_argument("--game", default="menu", help="启动后直接进入的游戏 key")
    ap.add_argument("--list", action="store_true", help="列出全部游戏后退出")
    ap.add_argument("--list-backends", action="store_true",
                    help="列出视觉后端在当前机器的可用性后退出")
    ap.add_argument("--probe-secs", type=int, default=20, help="诊断模式跑多少秒")
    ap.add_argument("--probe", action="store_true",
                    help="诊断模式：跑 20 秒并把各后端可用性、检测率、耗时写入日志")
    args = ap.parse_args()

    import games  # noqa: F401  导入即完成注册
    from core import base as B
    from core.vision import describe, preferred_order

    if args.list_backends:
        print("=== 视觉后端可用性 ===")
        print(describe())
        print(f"=== 本平台优先级：{preferred_order()} ===")
        return 0

    if args.list:
        print(f"共 {len(B.all_games())} 款游戏：\n")
        print(f"{'key':<12}{'名称':<18}{'分类':<14}{'难度':<6}玩法")
        for c in B.all_games():
            print(f"{c.KEY:<12}{c.TITLE:<18}{c.CATEGORY:<14}{'★' * c.DIFFICULTY:<6}{c.HOW}")
        return 0

    print("=== 视觉后端可用性 ===")
    print(describe())
    print(f"=== 本平台优先级：{preferred_order()} ===")

    if args.probe:
        return run_probe(args)

    from core.shell import Shell
    shell = Shell(vision=args.vision, cam_index=args.cam, no_cam=args.no_cam,
                  windowed=args.windowed, start_game=args.game)
    shell.run()
    return 0


def probe_synthetic() -> int:
    """
    合成序列自检：不需要摄像头就能验证 HOLD / LOST 两条路径。

    实机跑的时候镜头前可能一直没人（那样只会走 LOST 分支，HOLD 根本没被触发），
    所以这里用一段脚本化的检测序列把两种情况都覆盖掉：
        稳定识别 → 丢 3 帧（应冻结）→ 回来 → 丢很久（应立即归零）
    """
    from core.inputs import FaceState, HeadController

    head = HeadController(C)
    dt = 1.0 / 30.0

    def face(cx=0.5, cy=0.45):
        return FaceState(found=True, cx=cx, cy=cy)

    for _ in range(C.CALIB_FRAMES + 2):
        head.update(face(), dt)
    for _ in range(40):
        head.update(face(0.72), dt)                 # 推到满速右移
    held = head.axis

    ok_hold = True
    for _ in range(3):
        head.update(FaceState(found=False), dt)
        ok_hold &= abs(head.axis - held) < 1e-12
    ok_hold &= head.tracking

    head.update(face(0.72), dt)                     # 检测回来
    for _ in range(3):
        head.update(face(0.72), dt)
    ok_resume = head.axis > held - 0.05

    for _ in range(30):                             # 长时间丢失
        head.update(FaceState(found=False), dt)
    ok_zero = (head.axis == 0.0 and head.jump is False and head.up == 0.0
               and not head.tracking)

    print("[probe] 合成序列自检（不需要摄像头）")
    print(f"        丢 3 帧冻结，输出 {held:.3f} → 不变　　{'通过' if ok_hold else '不通过'}")
    print(f"        检测恢复后继续跟随　　　　　　　{'通过' if ok_resume else '不通过'}")
    print(f"        长时间丢失后立即归零　　　　　　{'通过' if ok_zero else '不通过'}")
    return 0 if (ok_hold and ok_resume and ok_zero) else 1


def run_probe(args) -> int:
    """
    诊断模式：真机跑 N 秒，打印检测统计与**输入状态机的实际行为**。

    之所以要这么个模式：真机画面截不到图（沙箱通常没有屏幕录制权限），
    只能靠日志判断方案到底行不行。

    除了检测率与各环节耗时，这里还会**逐帧跑一遍三个控制器**，并统计
    「判定为未识别、却仍有非零输出」的帧数 —— 这个数必须是 0，
    也就是"没有识别到头的时候别乱动"在真机上的直接证据。
    """
    import time
    from core.inputs import BodyController, HandController, HeadController
    from core.tracker import MotionTracker

    print()
    synth = probe_synthetic()

    tr = MotionTracker(args.cam, prefer=None if args.vision == "auto" else args.vision)
    if not tr.ok:
        print(f"[probe] 摄像头不可用：{tr.err}")
        return 1
    print(f"[probe] 视觉后端 {tr.hand_name}　人脸后端 {tr.backend_name}")
    print(f"[probe] 识别状态机：HOLD_AFTER={C.HOLD_AFTER}s　"
          f"LOST_PAUSE_AFTER={C.LOST_PAUSE_AFTER}s　"
          f"跑 {args.probe_secs}s，请自然坐好、中途可以故意转头离开")

    head, hand, body = HeadController(C), HandController(C), BodyController(C)
    stat = {"n": 0, "track": 0, "hold": 0, "lost": 0, "viol": 0}
    # 抖动统计：这两组数才是"头没动却在乱选"的直接证据。
    #  · 大厅阈值穿越次数：静止时它必须是 0
    #  · 各路信号的峰峰值：能直接看出噪声有多大
    stats = {"yaw_raw": [], "yaw_sig": [], "axis": [], "cross": 0, "on": False}
    dt = 1.0 / 60.0
    t0 = time.time()
    last = t0
    try:
        while time.time() - t0 < args.probe_secs:
            time.sleep(dt)
            _f, st, hands = tr.get()
            vf = tr.get_vision()
            head.update(st, dt)
            hand.update(hands, dt)
            body.update(vf.pose, dt)
            inp = head.game_input()
            inp = hand.apply(inp, hands)
            inp = body.apply(inp, vf.pose)

            # 与 shell._track_state 同一套判定
            if head.lost_t <= 0.0:
                state = "track"
            elif head.lost_t <= C.HOLD_AFTER:
                state = "hold"
            else:
                state = "lost"
            stat["n"] += 1
            stat[state] += 1
            d = head._debug
            stats["yaw_raw"].append(d.get("yaw_raw", 0.0))
            stats["yaw_sig"].append(d.get("yaw_sig", 0.0))
            stats["axis"].append(inp.axis)
            now_on = abs(inp.axis) > C.MENU_SWITCH_TH
            if now_on and not stats["on"]:
                stats["cross"] += 1
            stats["on"] = now_on
            # 关键断言：判定为"未识别"时，头部来源的输出必须严格为 0
            if state == "lost" and (inp.axis != 0.0 or inp.jump or inp.up != 0.0):
                stat["viol"] += 1

            now = time.time()
            if now - last >= 1.0:
                last = now
                p = vf.pose
                print(f"[probe] t={now - t0:4.1f}s  cam {tr.fps:4.1f}fps  "
                      f"脸{'✓' if st.found else '·'}  "
                      f"人体{'✓' if p.found else '·'}({p.coverage():2d}点)  "
                      f"手{len(vf.hands)}  face {tr.timings['face']:4.1f}ms "
                      f"vision {tr.timings['vision']:5.1f}ms")
                print(f"          状态 {state:5s}  axis{inp.axis:+.2f}  "
                      f"动作{'开' if inp.action else '关'}  "
                      f"found={'是' if inp.found else '否'}  "
                      f"| 举{inp_dbg(p)}")
                # 头部各路信号：摇头/抬头"没反应"还是"太灵"，看这行最直接。
                # · 平移 / 摇头 两路都该能单独把 axis 推上去（融合后取强者）
                # · 俯仰是动作键的唯一来源；位移再大也不该触发动作键
                d = head._debug
                if d:
                    print(f"          脸宽{d.get('face_w', 0):.3f} "
                          f"姿态{'✓' if d.get('pose_ok') else '✗'} | "
                          f"平移{d.get('a_move', 0):+.2f} "
                          f"摇头{d.get('a_yaw', 0):+.2f}(yaw{d.get('yaw', 0):+.2f}) | "
                          f"俯仰{d.get('b_pitch', 0):+.2f} "
                          f"位移{d.get('b_move', 0):+.2f} "
                          f"抬起{d.get('lift', 0):+.2f} 键值{d.get('jump_sig', 0):+.2f}")
    except KeyboardInterrupt:
        pass
    finally:
        tr.close()

    n = max(1, stat["n"])
    print("\n[probe] 小结（共 %d 帧）" % stat["n"])
    print(f"        识别中 {stat['track']:5d} 帧 {stat['track'] / n:6.1%}")
    print(f"        短暂丢帧 {stat['hold']:3d} 帧 {stat['hold'] / n:6.1%}  ← 输入冻结，无可见变化")
    print(f"        未识别 {stat['lost']:5d} 帧 {stat['lost'] / n:6.1%}  ← 输入归零")
    verdict = "通过" if stat["viol"] == 0 and synth == 0 else \
        f"不通过（未识别期间非零输出 {stat['viol']} 帧）"
    print(f"        未识别期间仍有非零输出的帧数：{stat['viol']}　→ {verdict}")
    # 基线可信度：摇头/抬头准不准，一半取决于校准时的中性位是否合理。
    # 脸宽太小说明坐得太远（检测噪声会被放大），关键点不可信则姿态路径会退化。
    def _pp(key):
        v = stats[key]
        return (max(v) - min(v)) if v else 0.0

    n = max(1, len(stats["axis"]))
    print(f"        抖动统计：大厅阈值穿越 {stats['cross']} 次"
          f"（静止时应为 0）"
          f"　轴量峰峰 {_pp('axis'):.3f}")
    print(f"        摇头原始读数峰峰 {_pp('yaw_raw'):.3f}"
          f"　低通后峰峰 {_pp('yaw_sig'):.3f}"
          f"　→ 低通把它压掉了 "
          f"{max(0.0, (1 - _pp('yaw_sig') / max(1e-6, _pp('yaw_raw')))) * 100:.0f}%")
    if stats["cross"] > 2:
        print(f"        ⚠ 静止时轴量多次越过大厅阈值（{stats['cross']} 次）："
              "如果此时头没动，说明还有抖动没压住，请把这段日志发我。")
    fw = head.nw
    print(f"        中性位基线：脸宽 {fw:.3f}"
          f"（{'偏小，建议坐近一点' if fw < 0.09 else '正常'}）"
          f"　yaw {head.nyaw:+.2f}　pitch {head.npitch:+.2f}")
    if abs(head.nyaw) > 0.35 or abs(head.npitch) > 0.35:
        print("        ⚠ 校准时的朝向偏离很大：说明校准时头是歪着/低着的。"
              "按 C 重新校准，采集时正对摄像头、头摆正。")
    if stat["hold"] == 0 and stat["track"] > 0:
        print("        （本次没有出现短暂丢帧，属于理想情况；HOLD 的防抖逻辑见 tools/test_input.py）")
    return 0


def inp_dbg(p) -> str:
    if not p.found:
        return "-"
    parts = []
    if p.lower_body_visible():
        parts.append(f"蹲{p.crouch:.1f}")
    parts.append(f"臂L{p.arm_raised('left'):.1f}/R{p.arm_raised('right'):.1f}")
    parts.append(f"举{p.hands_up()}")
    return " ".join(parts)


def _install_crash_log() -> None:
    """
    把未捕获异常写进日志。

    `.app` 没有终端，一旦主循环里抛异常，进程会静默退出 —— 现象就是
    "用着用着窗口没了"，而 run.log 里什么线索都没有。装了钩子之后，
    至少能看到类型与堆栈（真机上踩过一次，排查花了不少时间）。
    """
    import traceback

    def hook(t, v, tb):
        try:
            print("\n[FATAL] 未捕获异常 —— 请把下面这段发给开发者：", file=sys.stderr)
            traceback.print_exception(t, v, tb)
            sys.stderr.flush()
        except Exception:                                            # noqa: BLE001
            pass
    sys.excepthook = hook


if __name__ == "__main__":
    _install_crash_log()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:                                            # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        raise SystemExit(1)
