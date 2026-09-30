package com.motionarcade.game

import com.motionarcade.game.games.DrumGame
import com.motionarcade.game.games.FootballGame
import com.motionarcade.game.games.HoopGame
import com.motionarcade.game.games.HotpotGame
import com.motionarcade.game.games.MaskGame
import com.motionarcade.game.games.MarioGame
import com.motionarcade.game.games.PandaRollGame
import com.motionarcade.game.games.SkiGame
import com.motionarcade.game.games.SliceGame
import com.motionarcade.game.games.TennisGame
import com.motionarcade.render.BackgroundManager
import com.motionarcade.render.SpriteManager

/**
 * 游戏注册表。
 *
 * 新增游戏的步骤（与 Python 端 `games/__init__.py` 的约定一致）：
 *   1. 在 game/games/ 下新建类，继承 [BaseGame]，填元信息；
 *   2. 在 [games] 列表里加一行 —— 菜单与输入通道自动生效。
 *
 * 这里**预先实例化**而不是按需反射创建：菜单需要读每款的元信息
 * （标题/分类/难度），而这些是实例上的 open 属性；5 个实例的内存开销可以忽略。
 */
class GameRegistry(
    private val sprites: SpriteManager,
    private val bg: BackgroundManager,
) {

    /** 已迁移 10 款：头控 6 款 + 头手分工 1 款 + 手控 3 款（含两款文化动词游戏）。 */
    private val games: List<BaseGame> by lazy {
        listOf(
            MarioGame(sprites, bg),
            FootballGame(sprites),
            TennisGame(sprites),
            PandaRollGame(sprites),
            HotpotGame(sprites, bg),
            SkiGame(sprites, bg),
            MaskGame(sprites),
            DrumGame(),
            SliceGame(sprites, bg),
            HoopGame(sprites, bg),
        )
    }

    val entries: List<BaseGame> get() = games

    fun byKey(key: String): BaseGame? = games.find { it.key == key }

    fun indexOf(key: String): Int = games.indexOfFirst { it.key == key }

    /** 预热这些游戏会用到的精灵，避免第一次切进去时卡一帧。 */
    fun preload() {
        sprites.preload(
            listOf("panda_hero", "panda_curl", "coin", "enemy", "basketball",
                "fruit", "kiwi", "peach", "watermelon", "loquat", "pepper",
                "sanxingdui", "bronze", "bronze_tree", "football", "tennis_ball",
                "mask_red", "mask_gold", "mask_green", "mask_black", "mask_blue")
        )
    }
}
