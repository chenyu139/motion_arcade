#!/usr/bin/env python3
"""
生成素材抠底 —— 把 AI 生成的浅色背景转成透明 PNG 精灵。

为什么不是简单阈值
------------------
生成图里的背景是近白色（222~255），但**主体内部也有大量近白色**：
熊猫的白毛、盖碗的青白瓷、脸谱的白色纹样。直接按"亮 = 背景"抠，
这些部位会被一起抠穿，出现一个个空洞。

流程：
  1. 从画布四边估背景色，用**低分辨率 inpaint 插值出背景色场**
     （有些图背景是渐变的，单个常数色抠不干净）
  2. 距离够近的算"疑似背景"，再做连通域分析 ——
     **只有与画布边缘相连的那一片才是真背景**
     这是整个抠底的关键：主体内部的白毛颜色和背景一样，但被粗描边封闭、
     与画布边缘不连通，因此会被正确保留（实测内部空洞率 0.00%）
  3. 二值前景 + 只在轮廓处羽化 1~2px
     —— 一开始我用"距离越近越透明"的宽软过渡，结果 AI 背景自带的细噪点
        把整片背景拉成 20~40% 不透明度的灰雾（主体边缘外一圈脏边）。
        二值化 + 局部羽化才是对的。
  4. 反混合去掉白边，否则精灵贴到深色游戏背景上会有一圈白晕
  5. 按 alpha 包围盒裁剪 + 留边 + 降采样

用法
----
    python tools/matte.py                 # 处理 _raw/ 下全部
    python tools/matte.py panda_hero      # 只处理指定素材
    python tools/matte.py --sheet         # 额外生成一张检查图
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "assets", "sprites", "_raw")
OUT = os.path.join(ROOT, "assets", "sprites")


# --------------------------------------------------------------------------- #
def _border_band(rgb: np.ndarray, k: int) -> np.ndarray:
    """取画布最外 k 圈像素，用来估计背景色。"""
    k = max(2, k)
    return np.concatenate([
        rgb[:k].reshape(-1, 3), rgb[-k:].reshape(-1, 3),
        rgb[:, :k].reshape(-1, 3), rgb[:, -k:].reshape(-1, 3),
    ])


def _background_field(rgb: np.ndarray, tol: float, coarse: int = 224) -> np.ndarray:
    """
    估计"背景色场" B(x, y)，而不是单一背景色。

    做法：先在低分辨率上找出与边缘连通的那片背景，其余区域用 inpaint 填掉，
    得到一张平滑的背景色图，再放大回原尺寸做逐像素比较。

    这个估计在"主体内部"并不准 —— 但不要紧：那里算出的距离只会偏大 →
    判为主体 → 保留。失败方向是安全的。
    """
    h, w = rgb.shape[:2]
    sc = coarse / max(h, w)
    small = cv2.resize(rgb, (max(8, int(w * sc)), max(8, int(h * sc))),
                       interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    bg0 = np.median(_border_band(small, max(2, int(min(sh, sw) * 0.05))), axis=0)
    d = np.linalg.norm(small - bg0[None, None, :], axis=2)
    suspect = (d < tol).astype(np.uint8)
    n, lab = cv2.connectedComponents(suspect, connectivity=4)
    if n <= 1:
        raise RuntimeError("没能分出背景连通域（图可能没有统一底色）")
    bids = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bids = bids[bids != 0]
    if bids.size == 0:
        raise RuntimeError("背景没有与画布边缘连通")
    hole = (~np.isin(lab, bids)).astype(np.uint8)          # 1 = 主体（待填）
    bg_small = cv2.inpaint(small.astype(np.uint8), hole, 12, cv2.INPAINT_TELEA)
    return cv2.resize(bg_small.astype(np.float32), (w, h),
                      interpolation=cv2.INTER_LINEAR)


def _keep_main(fore: np.ndarray, keep_ratio: float = 0.04) -> np.ndarray:
    """
    只保留足够大的前景连通块，滤掉背景上残留的孤立噪点/水印残影。
    比最大块小 keep_ratio 倍以下的一律丢掉。
    """
    m = fore.astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 2:
        return fore
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = int(areas.max())
    keep = [i + 1 for i, a in enumerate(areas) if a >= max(64, big * keep_ratio)]
    return np.isin(lab, keep)


# --------------------------------------------------------------------------- #
def matte_one(
    path: str,
    tol: float = 34.0,
    feather: float = 0.75,
    pad: int = 8,
    decontaminate: bool = True,
    despeckle: bool = True,
) -> Tuple[Image.Image, dict]:
    """抠一张图，返回 (RGBA 图, 统计信息)。"""
    im = Image.open(path).convert("RGB")
    rgb = np.asarray(im).astype(np.float32)
    h, w = rgb.shape[:2]

    bgfield = _background_field(rgb, tol)
    bg = np.median(_border_band(rgb, int(min(h, w) * 0.025)), axis=0)
    dist = np.linalg.norm(rgb - bgfield, axis=2)

    # ---- 1) 背景连通域（只有与画布边缘相连的才算背景）----
    suspect = (dist < tol).astype(np.uint8)
    n, lab = cv2.connectedComponents(suspect, connectivity=4)
    if n <= 1:
        raise RuntimeError("没能分出背景连通域（图可能没有统一底色）")
    bids = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bids = bids[bids != 0]
    if bids.size == 0:
        raise RuntimeError("背景没有与画布边缘连通")
    fore = ~np.isin(lab, bids)

    # ---- 2) 滤掉孤立的噪点块 ----
    if despeckle:
        fore = _keep_main(fore)

    # ---- 3) 二值前景 + 只在轮廓附近羽化 ----
    a = fore.astype(np.float32) * 255.0
    if feather > 0:
        k = 3 if feather <= 1.0 else 5
        a = cv2.GaussianBlur(a, (k, k), feather)
        a = np.clip(a, 0.0, 255.0)
    a = np.where(a < 8.0, 0.0, a)          # 清掉极低透明度的残雾

    alpha = a / 255.0

    # ---- 4) 去白边：把背景色的贡献从半透明像素里减掉 ----
    #     用逐像素的背景色场而非单一色，否则渐变背景会留下有色轮廓
    out = rgb
    if decontaminate:
        aa = np.clip(alpha, 1e-3, 1.0)[..., None]
        fg = (rgb - bgfield * (1.0 - aa)) / aa
        m = (alpha < 0.99)[..., None]
        out = np.where(m, np.clip(fg, 0, 255), rgb)

    rgba = np.dstack([out, a]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")

    # ---- 5) 裁到内容包围盒（按阈值裁，别被 1% 的残雾撑满整幅）----
    am = np.asarray(img.getchannel("A"))
    ys, xs = np.where(am > 16)
    if ys.size:
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        img = img.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(w, x1 + pad), min(h, y1 + pad)))

    # 质检指标：实心比例 + 半透明比例（半透明过多说明边缘/背景有问题）
    info = {
        "bg": tuple(int(v) for v in bg),
        "size": img.size,
        "opaque_ratio": float((am > 200).mean()),
        "semi_ratio": float(((am > 16) & (am < 240)).mean()),
    }
    return img, info


# --------------------------------------------------------------------------- #
def contact_sheet(names: List[str], out_path: str, cell: int = 300) -> None:
    """把抠好的精灵拼成检查图：深色底与棋盘底交替，两种底都能看出问题。"""
    rows = (len(names) + 4) // 5
    sheet = Image.new("RGB", (cell * 5, cell * rows), (18, 22, 40))
    chk = Image.new("RGB", (cell, cell), (60, 64, 78))
    for y in range(0, cell, 16):
        for x in range(0, cell, 16):
            if (x // 16 + y // 16) % 2:
                chk.paste((96, 100, 116), (x, y, x + 16, y + 16))

    for i, nm in enumerate(names):
        p = os.path.join(OUT, f"{nm}.png")
        if not os.path.exists(p):
            continue
        sp = Image.open(p).convert("RGBA")
        sc = min((cell - 24) / sp.width, (cell - 24) / sp.height)
        sp = sp.resize((max(1, int(sp.width * sc)), max(1, int(sp.height * sc))),
                       Image.LANCZOS)
        r, c = divmod(i, 5)
        ox, oy = c * cell, r * cell
        if i % 2:
            sheet.paste(chk, (ox, oy))
        sheet.paste(sp, (ox + (cell - sp.width) // 2, oy + (cell - sp.height) // 2), sp)
    sheet.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成素材抠底")
    ap.add_argument("names", nargs="*", help="只处理这些素材（默认全部）")
    ap.add_argument("--tol", type=float, default=34.0, help="背景色容差")
    ap.add_argument("--max", type=int, default=600,
                    help="输出最长边上限（游戏里最大用到 ~400px，留 1.5 倍余量）")
    ap.add_argument("--sheet", action="store_true", help="生成检查图")
    ap.add_argument("--sheet-out", default="/tmp/matte_sheet.png")
    args = ap.parse_args()

    if not os.path.isdir(RAW):
        print(f"没有 {RAW}")
        return 1

    # 原图是 RGB（无透明通道），仓库里以 JPEG 存证即可：11MB → 2MB，
    # 而抠底只需要颜色信息，质量几乎无差别。
    exts = (".png", ".jpg", ".jpeg")
    files = sorted(f for f in os.listdir(RAW) if f.lower().endswith(exts))
    if args.names:
        def stem(f: str) -> str:
            s = os.path.splitext(f)[0]
            return s[4:] if s.startswith("src_") else s
        files = [f for f in files if stem(f) in args.names]
    if not files:
        print("没有匹配的素材")
        return 1

    ok_names = []
    for f in files:
        s = os.path.splitext(f)[0]
        name = s[4:] if s.startswith("src_") else s
        try:
            img, info = matte_one(os.path.join(RAW, f), tol=args.tol)
        except Exception as e:                                   # noqa: BLE001
            print(f"  ✗ {name:16s} {type(e).__name__}: {e}")
            continue
        if args.max and max(img.size) > args.max:
            sc = args.max / max(img.size)
            img = img.resize((max(1, round(img.width * sc)),
                              max(1, round(img.height * sc))), Image.LANCZOS)
        dst = os.path.join(OUT, f"{name}.png")
        img.save(dst, optimize=True)
        ok_names.append(name)
        print(f"  ✓ {name:16s} → {img.width}×{img.height}  实心 {info['opaque_ratio']:.0%}"
              f"  半透明 {info['semi_ratio']:.1%}  {os.path.getsize(dst)//1024}KB")

    print(f"完成 {len(ok_names)}/{len(files)}")
    if args.sheet and ok_names:
        contact_sheet(ok_names, args.sheet_out)
        print(f"检查图：{args.sheet_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
