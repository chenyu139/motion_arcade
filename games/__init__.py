"""
games
=====
游戏大厅的全部小游戏。导入本包即完成注册（各模块用 @register 装饰器登记）。

当前共 18 款，按输入通道分两类：
  头部控制      mario / football / tennis / panda_roll / hotpot / mask
                ski / climb / lantern / dino / drum / fishing
  手部控制      handcatch / balloon / slice / shoot / hoop / puzzle

注：曾有两款「头部 + 手部」双线游戏（duel 双线太极 / keeper 双人守门），
已于 2026-09 下架 —— 同时用头和手操控对普通用户难度过高。
模块文件保留（games/duel.py / games/keeper.py），重新 import 即可恢复。

新增一个游戏的步骤：
  1. 在本目录新建 xxx.py，继承 core.base.BaseGame，加上 @register；
  2. 实现 reset / update(dt, inp) / draw(surf)；
  3. 在下面 import 一行即可出现在大厅里。
"""
from __future__ import annotations

# ---- 头部控制 ----
from . import mario        # noqa: F401
from . import football     # noqa: F401
from . import tennis       # noqa: F401
from . import panda_roll   # noqa: F401
from . import hotpot       # noqa: F401
from . import mask         # noqa: F401
from . import ski          # noqa: F401
from . import climb        # noqa: F401
from . import lantern      # noqa: F401
from . import dino         # noqa: F401
from . import drum         # noqa: F401
from . import fishing      # noqa: F401

# ---- 手部控制 ----
from . import handcatch    # noqa: F401
from . import balloon      # noqa: F401
from . import slice        # noqa: F401
from . import shoot        # noqa: F401
from . import hoop         # noqa: F401
from . import puzzle       # noqa: F401


__all__ = [
    "mario", "football", "tennis", "panda_roll", "hotpot", "mask",
    "ski", "climb", "lantern", "dino", "drum", "fishing",
    "handcatch", "balloon", "slice", "shoot", "hoop", "puzzle",
]
