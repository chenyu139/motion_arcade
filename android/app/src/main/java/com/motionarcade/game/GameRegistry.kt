package com.motionarcade.game

import com.motionarcade.game.games.DrumGame
import com.motionarcade.game.games.FootballGame
import com.motionarcade.game.games.HotpotGame
import com.motionarcade.game.games.MaskGame
import com.motionarcade.game.games.PandaRollGame
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

    /**
     * 精选 7 款：只保留「交互好 + 四川文化特色鲜明」的双达标作品。
     * 选品标准：动词来自文化动作本身（变脸=扫脸、鼓点=下砸、火锅=低头捞），
     * 主题本身就是四川符号（川剧 / 火锅 / 熊猫·三星堆 / 川超川网 / 川果）。
     */
    private val games: List<BaseGame> by lazy {
        listOf(
            MaskGame(sprites),
            DrumGame(),
            HotpotGame(sprites, bg),
            FootballGame(sprites),
            TennisGame(sprites),
            PandaRollGame(sprites),
            SliceGame(sprites, bg),
        )
    }

    val entries: List<BaseGame> get() = games

    fun byKey(key: String): BaseGame? = games.find { it.key == key }

    fun indexOf(key: String): Int = games.indexOfFirst { it.key == key }

    /** 预热这些游戏会用到的精灵，避免第一次切进去时卡一帧。 */
    fun preload() {
        sprites.preload(
            listOf("panda_curl", "sanxingdui", "bronze", "bronze_tree",
                "fruit", "kiwi", "peach", "watermelon", "loquat", "pepper",
                "football", "tennis_ball",
                "mask_red", "mask_gold", "mask_green", "mask_black", "mask_blue")
        )
    }
}
