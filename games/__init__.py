"""
games
=====
游戏大厅的全部小游戏。导入本包即完成注册（各模块用 @register 装饰器登记）。

当前共 20 款，按输入通道分三类：
  头部控制      mario / football / tennis / panda_roll / hotpot / mask
                ski / climb / lantern / dino / drum / fishing
  手部控制      handcatch / balloon / slice / shoot / hoop / puzzle
  头部 + 手部   duel / keeper

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

# ---- 头部 + 手部 ----
from . import duel         # noqa: F401
from . import keeper       # noqa: F401

__all__ = [
    "mario", "football", "tennis", "panda_roll", "hotpot", "mask",
    "ski", "climb", "lantern", "dino", "drum", "fishing",
    "handcatch", "balloon", "slice", "shoot", "hoop", "puzzle",
    "duel", "keeper",
]
