# 文字钓鱼游戏引擎（Python）—— 确定性、单文件、给 AI 玩家用。
# 对外只用两个接口：cmd("指令") 返回结果文字；new_game(seed) 重开一局。
# 同 seed + 同指令序列 → 逐位可复现（mulberry32 PRNG，状态存同目录 fishing_save.json）。
# 想让 AI 不剧透盲玩：用打包版 fishing.py（引擎藏进 blob，AI 只调 cmd()）。
import json, os, re

# ── 确定性 PRNG（mulberry32，与 JS/TS 同源）──
def _imul(a, b):
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF

class _Rng:
    def __init__(self, state, calls=0):
        self.state = state & 0xFFFFFFFF
        self.calls = calls
    def random(self):
        self.calls += 1
        a = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        self.state = a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    def rint(self, a, b):
        return a + int(self.random() * (b - a + 1))

_DEFAULT_SEED = 0x9e3779b9

RARITY = {
    "common": {"label": "常见", "tag": "C", "weight": 1000, "discovery_bonus": 20},
    "uncommon": {"label": "少见", "tag": "U", "weight": 350, "discovery_bonus": 20},
    "rare": {"label": "稀有", "tag": "R", "weight": 90, "discovery_bonus": 20},
    "epic": {"label": "史诗", "tag": "E", "weight": 22, "discovery_bonus": 20},
    "legendary": {"label": "传说", "tag": "L", "weight": 5, "discovery_bonus": 20},
    "mythic": {"label": "神话", "tag": "M", "weight": 1, "discovery_bonus": 20},
}
SEASONS = {
    "spring": {"id": "spring", "name": "春", "order": 0, "description": "水暖花开，鱼群活跃。", "tag_weight_mult": {"freshwater": 1.15}},
    "summer": {"id": "summer", "name": "夏", "order": 1, "description": "烈日当头，火元素的水域沸腾。", "tag_weight_mult": {"fire": 1.5}},
    "autumn": {"id": "autumn", "name": "秋", "order": 2, "description": "水温转凉，洄游的鱼群增多。", "tag_weight_mult": {"nocturnal": 1.2}},
    "winter": {"id": "winter", "name": "冬", "order": 3, "description": "万物沉静，深海的霜冷生物浮现。", "tag_weight_mult": {"deepsea": 1.3}},
}
LOCATIONS = {
    "mangrove_shoal": {"id":"mangrove_shoal","name":"红树林浅滩","description":"盘根错节的红树根扎进咸淡交界的浅水，退潮时露出满地跳动的小生物，气根迷宫里藏着伏击的眼睛。","junk_chance_base":0.1,"tag_weight_mult":{"brackish":1.5,"armored":1.3},"unlock_cost":320,"available_seasons":["spring","summer","autumn"],"ambience":["气生根之间响起弹涂鱼跳跃的啪啪声，像小孩在泥里拍巴掌。","退潮了，树根上的藤壶闭合时发出细碎的嗒嗒声，连成一片。","招潮蟹举着大螯从洞里探身，突然被一道水波吓了回去。","红树林深处传来啄木鸟般笃笃的敲击声，那是虾蛄在攻击猎物。","淤泥土腥味混着海水咸味，被烈日蒸成一层黏在皮肤上的膜。","不知哪片叶子上，一只树蛙开始断断续续地叫，像在调试生锈的乐器。"],"character":"根丛里咬口又凶又贼，能拉上几条硬货，但真正称王的家伙从不搁浅在这种咸淡交界的迷宫里。"},
    "whispering_mire": {"id":"whispering_mire","name":"耳语沼泽","description":"终年浮着薄雾的沼泽，腐木与水汽间似有低语，越往深处水色越黑，脚下的泥不时咕嘟冒泡。","junk_chance_base":0.11,"tag_weight_mult":{"swamp":1.6,"nocturnal":1.3,"poison":1.4},"unlock_cost":200,"available_seasons":["spring","summer","autumn"],"ambience":["雾霭深处飘来模糊的低语，刚凝神去听，就变成了风刮过树洞的呜呜声。","沼气泡在泥面上炸开，带出一股腐甜的沼气，随即被湿冷吞没。","枝头挂下的松萝轻拂水面，像老人用指尖反复写着同一个字。","一只陷入泥潭的小兽发出最后的咕噜声，之后沼泽陷入长久的沉默。","水面突然出现一条笔直的水线，朝你脚边延伸，随即消失得不留痕迹。"],"character":"黑水底下藏着沉甸甸的咬口，手感像拖一袋湿泥，只是那低语从不许诺什么惊世巨物。"},
    "starry_delta": {"id":"starry_delta","name":"星河三角洲","description":"大河入海的扇形浅滩，洄游季一到，亿万带荧光的鱼群涌入，整片水面像把银河倒扣在脚下。","junk_chance_base":0.09,"tag_weight_mult":{"brackish":1.3,"glowing":1.4,"migratory":1.6},"unlock_cost":480,"available_seasons":["spring","autumn"],"ambience":["无数河流在此交汇，水面倒映星空，分不清哪里是水，哪里是银河。","夜鸟贴着水面飞过，翅膀尖点起一串发光的浮游生物。","远处的船灯像一颗悬停的红色星辰，不时被涌浪轻轻托起。","淡水与海水交接处发出细密的噼啵声，像冰层正在生长。","一条鱼跃出水面，在空中翻了个身，落回时溅起的水珠映着星光，宛如碎钻。"],"character":"洄游季的潮头才卷得来这些流光溢彩的猛兽，季节一过，整片浅滩空得像被偷走了魂。"},
    "sunken_ruins": {"id":"sunken_ruins","name":"沉没遗迹","description":"沉入海底的古城，断柱与残塔在幽蓝水光里若隐若现，退潮时才浮出水面，海藻间漂着说不清的低响。","junk_chance_base":0.08,"tag_weight_mult":{"deepsea":1.4,"ancient":1.7,"glowing":1.3},"unlock_cost":650,"available_seasons":["autumn","winter"],"ambience":["坍塌的拱门在水下透出模糊的影子，气泡从石缝里鱼贯而出，叮叮当当。","水草缠绕着倾颓的柱身，随暗流来回摆动，像在给残垣梳理头发。","钟楼的铜顶倒在沙地上，水流穿过它变形的腔体，发出深沉的瓮声。","一个陶罐在石阶上缓缓滚动，停下，又滚动，仿佛被看不见的手推着。","阳光透过水面在断壁上投下破碎的光斑，那些影子缓缓蠕动，像要拼回原来的壁画。"],"character":"断柱间的阴影咬钩极沉，像在和沉没的历史拔河——分量十足，却还够不上传说之名。"},
    "geyser_falls": {"id":"geyser_falls","name":"间歇泉瀑布","description":"层层热泉自岩壁喷涌而下汇成温瀑，蒸汽终年不散，再冷的天这里也暖意融融。","junk_chance_base":0.1,"tag_weight_mult":{"fire":1.4,"mineral":1.6},"unlock_cost":400,"available_seasons":["spring","summer","autumn","winter"],"ambience":["间歇泉喷发前，大地深处传来一阵闷雷般的低吼，脚下的岩石都在颤抖。","滚水柱冲天而起，嘶嘶声震耳欲聋，随即被风撕成滚烫的雨点。","蒸汽散去时，空中悬着一道短暂的彩虹，水珠不断击穿它，又迅速重建。","彩色矿物质在水流下结成梯田般的台阶，每走一步都嘎吱作响。","沸水汇入寒潭的锋面上，冷热交激，发出瓷器开片般的脆响。"],"character":"温水里养出的全是暴脾气，上钩像拽着一团火，虽不算传说，也够你在篝火边吹上几年的。"},
    "crystal_cave": {"id":"crystal_cave","name":"水晶洞","description":"洞壁缀满巨大的六棱晶柱，每一束微光都被折射成漫天碎虹，洞中恒温，听得见水滴坠落的回响。","junk_chance_base":0.07,"tag_weight_mult":{"crystal":1.7,"glowing":1.4},"unlock_cost":800,"available_seasons":["spring","summer","autumn","winter"],"ambience":["水滴从钟乳石尖坠落，打在洞底水潭上，回声在穹顶反复折叠。","晶簇内部偶尔爆出一声微响，那是矿物正在生长，释放被囚了万年的应力。","空气中的矿物味冰凉而清冽，深吸一口，仿佛能尝到石头的味道。","脚下的晶砂被踩得沙沙响，每粒碎屑都在黑暗中发出微弱的蓝绿色荧光。","洞深处传来蝙蝠翅膀扑棱的细碎声，随后又归于完全的寂静。","水潭表面纹丝不动，却不时冒出一个乒乓球大小的气泡，浮到水面即无声破裂。"],"character":"晶光把水底照得太透，敢在这儿巡游的大货都不怕被看穿——咬钩那一下，值回你掏的每一分钱。"},

    "moonlit_pond": {"id": "moonlit_pond", "name": "月光池塘", "description": "一汪静谧的池水，倒映着永远停在黄昏的天空。水面偶有涟漪，像有什么在月色下游动。", "junk_chance_base": 0.10, "tag_weight_mult": {"freshwater": 1.2, "nocturnal": 1.5}, "unlock_cost": 0, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["夜鹭从柳树阴影里无声滑出，翅膀扇灭了几只萤火虫。","水面上的月影被什么东西顶了一下，碎成银亮的圈，又慢慢合拢。","芦苇深处传来拖长的咕咕声，像谁在水下打了个嗝。","一片浮萍突然沉了下去，过了很久才浮上来，已经翻了个面。","潮湿的石头上，青蛙刚叫了半声就咽了回去。"],"character":"表面温吞得像睡着了，可常夜钓的人会压低声音告诉你，底下偶尔游过不该属于这片小水的巨影。"},
    "reed_river": {"id": "reed_river", "name": "芦苇河", "description": "两岸芦苇沙沙作响，水流缓慢清澈，是练手的好去处。", "junk_chance_base": 0.12, "tag_weight_mult": {"freshwater": 1.3}, "unlock_cost": 0, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["风梳过芦苇荡，千万根杆子互相摩擦，发出干涩的沙沙声。","一只秧鸡在水边快速奔跑，脚步声像在敲小鼓。","水流忽然变急，打着旋绕过一丛菖蒲，卷走了几片枯叶。","远处传来鸬鹚拍水的扑通声，紧接着是它不满的嘶哑叫喊。","竹筏的残骸搁浅在泥滩上，覆满绿藻的绳子还在随水流漂动。"],"character":"水浅流缓，练手正好，但老钓客都门儿清——这儿捞不出让人心跳加速的货。"},
    "abyssal_trench": {"id": "abyssal_trench", "name": "深渊海沟", "description": "深不见底的幽蓝海沟，越往下越冷，有微光在黑暗里游弋。", "junk_chance_base": 0.08, "tag_weight_mult": {"deepsea": 1.5, "glowing": 1.4}, "unlock_cost": 300, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["无光的深水中，只有压力在耳膜上缓慢地收紧拳头。","远处传来鲸类低沉的呜咽，被海水拉长成一条颤抖的线。","发光的磷虾群突然炸开，像深空里爆破的星团，又立刻被黑暗吞没。","脚下的海床传来地层深处的震动，像巨大的心脏在泥下跳动。","一个气球状的东西擦过你的腿，凉丝丝的，分不清是水母还是别的什么。","铁链和锚缆的闷响从上方很远的地方传来，仿佛另一世界的钟声。"],"character":"越往下放线，心跳越重——冷透骨髓的黑暗里，藏着那种一生或许只咬一次的传说。"},
    "floating_lake": {"id": "floating_lake", "name": "浮空之湖", "description": "悬在云端的一汪湖水，风从下方穿过，湖面像一面倒扣的镜子。", "junk_chance_base": 0.09, "tag_weight_mult": {"fantasy": 1.4, "wind": 1.5}, "unlock_cost": 600, "available_seasons": ["spring", "summer", "autumn"],"ambience":["水流从浮岛的边缘坠落，在半空中散成银色的薄雾，被风撕成长条。","云层在下方翻涌，偶尔裂开一道缝，露出底下针尖大小的海。","悬空的根系垂入虚空，滴水声从极深的地方传上来，晚了整整一拍。","一只鸟从岛上起飞，它扇动翅膀的声音消失得特别快，像被真空吞掉了。","浮岛与浮岛之间，彩虹色的薄膜一明一灭，空气里有极淡的臭氧味。"],"character":"悬在天上的水不认常理，传说级的巨影在这里不是念想，是老钓手反复擦拭的勋章。"},
    "lava_spring": {"id": "lava_spring", "name": "熔岩温泉", "description": "翻涌着橙红气泡的温泉，水里游着不怕烫的奇异生物。仅夏季开放。", "junk_chance_base": 0.10, "tag_weight_mult": {"fire": 1.6}, "unlock_cost": 550, "available_seasons": ["summer"],"ambience":["水面咕嘟嘟翻起稠密的气泡，破裂时溅出硫磺味的热汽。","一块刚凝固的黑色玄武岩被水波推着，慢慢沉进了滚烫的泉眼。","橘红色的光纹在水底忽明忽暗，像呼吸，又像在讲故事。","池边的硅华吱嘎作响，内部传来细密的崩裂声，新的裂隙正在生长。","偶尔有滚烫的泥浆从深处翻上来，拖着一缕白烟，像水下的火龙翻了个身。"],"character":"只有盛夏的几个月烫得刚好能下竿，那种浑身冒火的烈性子错过此刻，就得再等一年。"},
}
FISH = {
    "mud_carp": {"id":"mud_carp","name":"泥鲤","rarity":"common","description":"一身粗粝的褐色鳞片，终日拱食河底淤泥，出水时甩你半脸泥点子。","size_min":10,"size_max":35,"size_unit":"cm","base_value":6,"locations":["moonlit_pond","reed_river","whispering_mire","starry_delta"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater"],"latin":"Cyprinus limosus"},
    "ghost_shrimp": {"id":"ghost_shrimp","name":"幽灵虾","rarity":"common","description":"透明的身子只剩两粒黑眼珠像浮空的芝麻，成群漂过时，仿佛水下起了一阵玻璃雨。","size_min":3,"size_max":12,"size_unit":"cm","base_value":5,"locations":["moonlit_pond","reed_river","mangrove_shoal","whispering_mire","starry_delta"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater","nocturnal"],"latin":"Palaemon spectra"},
    "flicker_minnow": {"id":"flicker_minnow","name":"荧鳞鲦","rarity":"common","description":"体侧一道荧蓝细线如同划着的火柴，暗处成群游动时，能照亮半张脸。","size_min":4,"size_max":14,"size_unit":"cm","base_value":4,"locations":["moonlit_pond","reed_river"],"seasons":["spring","summer","autumn"],"tags":["freshwater","nocturnal"],"latin":"Leucaspius micans"},
    "angler_fry": {"id":"angler_fry","name":"灯鮟鱇","rarity":"common","description":"小如拇指的深海鮟鱇，额顶灯笼在无边黑暗中连成一串坠向海底的星链。","size_min":4,"size_max":18,"size_unit":"cm","base_value":7,"locations":["abyssal_trench","sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","glowing"],"latin":"Antennarius lumen"},
    "sky_skipper": {"id":"sky_skipper","name":"跃空鱼","rarity":"common","description":"胸鳍拉成薄膜翼，能掠出水面滑翔数米，溅起的水雾里总挂着一小截虹。","size_min":8,"size_max":22,"size_unit":"cm","base_value":7,"locations":["floating_lake","starry_delta"],"seasons":["spring","summer","autumn"],"tags":["fantasy","wind"],"latin":"Exocoetus aetherius"},
    "frost_drifter": {"id":"frost_drifter","name":"霜漂鱼","rarity":"common","description":"身体像一片薄冰，体内氦气与寒气让它悬在水层中，阳光穿透时棱镜光碎成十几片。","size_min":6,"size_max":20,"size_unit":"cm","base_value":6,"locations":["floating_lake","starry_delta"],"seasons":["autumn"],"tags":["fantasy","wind"],"latin":"Coregonus glacies"},
    "scorched_tetra": {"id":"scorched_tetra","name":"焦鳞灯鱼","rarity":"common","description":"赤褐色的鳞片布满灼痕，在沸水里悠然自得，仿佛刚出炉的火炭块。","size_min":5,"size_max":15,"size_unit":"cm","base_value":8,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn","winter"],"tags":["fire"],"latin":"Hyphessobrycon cineris"},
    "shard_fish": {"id":"shard_fish","name":"晶片鱼","rarity":"common","description":"身躯如同碎裂的水晶，折射出成千上万道细虹，游动时整个洞穴都在闪光。","size_min":7,"size_max":18,"size_unit":"cm","base_value":7,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","glowing"],"latin":"Vitreochromis aculeus"},
    "jelly_phantom": {"id":"jelly_phantom","name":"幻水母","rarity":"common","description":"半透明的伞帽悬浮着，触手拖曳星尘般的微光，穿过它能看到对岸扭曲的影子。","size_min":8,"size_max":25,"size_unit":"cm","base_value":6,"locations":["floating_lake","crystal_cave"],"seasons":["spring","summer"],"tags":["fantasy","glowing"],"latin":"Cnidaria umbra"},
    "winter_cinder": {"id":"winter_cinder","name":"冬烬鱼","rarity":"common","description":"灰白色的鳞片下隐约透着将熄的火光，只在寒冬温泉的石缝里成群打转。","size_min":5,"size_max":14,"size_unit":"cm","base_value":6,"locations":["lava_spring","geyser_falls"],"seasons":["winter"],"tags":["fire"],"latin":"Salvelinus favilla"},
    "silver_pike": {"id":"silver_pike","name":"银梭鱼","rarity":"uncommon","description":"细长如标枪的掠食者，鳞片是冷冽的银色，出水时甩起一串水珠。","size_min":20,"size_max":55,"size_unit":"cm","base_value":26,"locations":["moonlit_pond","reed_river"],"seasons":["spring","autumn"],"tags":["freshwater"],"latin":"Esox argyronotus"},
    "dusk_eel": {"id":"dusk_eel","name":"暮色鳗","rarity":"uncommon","description":"暗紫色的细鳗只在黄昏从泥洞里探出，像一条会流动的影子。","size_min":25,"size_max":60,"size_unit":"cm","base_value":24,"locations":["moonlit_pond","reed_river","mangrove_shoal","whispering_mire"],"seasons":["spring","autumn"],"tags":["freshwater","nocturnal"],"latin":"Anguilla crepusculum"},
    "copper_bream": {"id":"copper_bream","name":"铜鲂","rarity":"uncommon","description":"宽扁的身体覆着一层铜绿般的鳞，在水草间折射出锈迹似的光晕。","size_min":18,"size_max":45,"size_unit":"cm","base_value":22,"locations":["moonlit_pond","reed_river","whispering_mire"],"seasons":["summer","autumn"],"tags":["freshwater","armored"],"latin":"Abramis cupreus"},
    "cinder_loach": {"id":"cinder_loach","name":"余烬泥鳅","rarity":"uncommon","description":"暗红色的泥鳅在热沙里钻进钻出，体表不时爆出细小的火星，烫得鱼线微微发颤。","size_min":10,"size_max":28,"size_unit":"cm","base_value":28,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn"],"tags":["fire"],"latin":"Barbatula favilla"},
    "deep_sculpin": {"id":"deep_sculpin","name":"深岩杜父鱼","rarity":"uncommon","description":"长着骨质甲板的怪鱼，趴在海底淤泥里像一块会呼吸的石头，专等粗心的猎物。","size_min":15,"size_max":40,"size_unit":"cm","base_value":30,"locations":["abyssal_trench","sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","armored"],"latin":"Cottus abyssorum"},
    "mangrove_snapper": {"id":"mangrove_snapper","name":"红树鲷","rarity":"uncommon","description":"披着青褐色装甲的鲷鱼，在红树气根迷宫间伏击，一双眼珠有潜望镜的冷静。","size_min":20,"size_max":50,"size_unit":"cm","base_value":25,"locations":["mangrove_shoal"],"seasons":["spring","summer","autumn"],"tags":["brackish","armored"],"latin":"Lutjanus rhizophorus"},
    "winter_betta": {"id":"winter_betta","name":"雪华斗鱼","rarity":"uncommon","description":"尾鳍绽开如一朵完整的雪花，在冰水里游动时，周遭会凝结出一圈细碎冰晶。","size_min":12,"size_max":30,"size_unit":"cm","base_value":27,"locations":["moonlit_pond","reed_river","floating_lake","starry_delta"],"seasons":["winter"],"tags":["freshwater","fantasy"],"latin":"Betta glacies"},
    "zephyr_dancer": {"id":"zephyr_dancer","name":"流风舞者","rarity":"uncommon","description":"迅捷如风的蓝翼飞鱼，跃出水面时拖着一缕缕棉花糖般的云丝，落水无声。","size_min":15,"size_max":40,"size_unit":"cm","base_value":24,"locations":["floating_lake","starry_delta"],"seasons":["spring","summer","autumn"],"tags":["wind","fantasy"],"latin":"Danio zephyrus"},
    "geyser_wyrm": {"id":"geyser_wyrm","name":"间歇泉龙","rarity":"uncommon","description":"一条无目的白蛇，平日休眠在间歇泉管道深处，只在冰封时被热水冲上地表。","size_min":30,"size_max":80,"size_unit":"cm","base_value":29,"locations":["lava_spring","geyser_falls"],"seasons":["winter"],"tags":["fire","fantasy"],"latin":"Thermophis geysiris"},
    "crystal_angler": {"id":"crystal_angler","name":"晶刺鮟鱇","rarity":"rare","description":"额前悬着一枚六棱晶石的深海怪鱼，光芒能穿透洞穴的永夜，诱使猎物自投罗网。","size_min":15,"size_max":45,"size_unit":"cm","base_value":100,"locations":["crystal_cave","abyssal_trench"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","glowing","crystal"],"latin":"Cryptopsaras crystallus"},
    "stormray": {"id":"stormray","name":"风暴鳐","rarity":"rare","description":"翼展布满电弧纹的银色鳐鱼，跃出水面时能引下一道微型闪电，劈开一瞬的白昼。","size_min":40,"size_max":80,"size_unit":"cm","base_value":110,"locations":["floating_lake","starry_delta"],"seasons":["spring","autumn"],"tags":["fantasy","wind","electric"],"latin":"Dasyatis tempestas"},
    "magma_salamander": {"id":"magma_salamander","name":"岩浆蝾螈","rarity":"rare","description":"皮肤流淌着熔岩脉络的两栖生物，踏过之处水温骤升，连鱼线都开始发烫。","size_min":25,"size_max":55,"size_unit":"cm","base_value":120,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn"],"tags":["fire","fantasy"],"latin":"Ambystoma magmaticum"},
    "void_jellyfish": {"id":"void_jellyfish","name":"虚空水母","rarity":"epic","description":"指尖穿过它的边缘时什么都碰不到，只感到一股彻骨的虚无爬上小臂，连水声都像被吸走了。","size_min":50,"size_max":90,"size_unit":"cm","base_value":200,"locations":["abyssal_trench","sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","glowing","shadow"],"latin":"Umbraxerxes voidus"},
    "cloud_serpent": {"id":"cloud_serpent","name":"云鳞蛟","rarity":"epic","description":"握住它的一刻，掌心仿佛拢住了高空的风，冰凉而不可遏制的升力让手臂微微发颤，耳畔尽是流云摩擦的呜咽。","size_min":60,"size_max":130,"size_unit":"cm","base_value":220,"locations":["floating_lake","starry_delta"],"seasons":["spring"],"tags":["fantasy","wind","migratory"],"latin":"Nephropterus nubigena"},
    "ember_barb": {"id":"ember_barb","name":"烬棘鱼","rarity":"epic","description":"鳞片烫得几乎握不住，空气中弥漫着焦枯的甜味，像刚刚熄灭的森林大火，鱼身轻震时带起火星迸溅的噼啪声。","size_min":35,"size_max":65,"size_unit":"cm","base_value":180,"locations":["lava_spring","geyser_falls"],"seasons":["summer"],"tags":["fire","armored"],"latin":"Barbus pruna"},
    "moon_phoenix_fish": {"id":"moon_phoenix_fish","name":"月凰鱼","rarity":"legendary","description":"手指刚触到它的冰晶鳍，月光就从你的掌纹里倾泻而出，你听见一声不属于水面的清啸，整个人被提成一缕冷焰，在满月的冰原上无声燃烧——直到它从掌心滑脱，你才落回自己的骨头里。","size_min":50,"size_max":90,"size_unit":"cm","base_value":450,"locations":["moonlit_pond"],"seasons":["winter"],"tags":["freshwater","nocturnal","fantasy"],"latin":"Lunapterus phoeniceus","rumor":"满月夜钓起月凰鱼的人，会听见亡者在水中合唱，一曲终了，鱼便化为月光散去。"},
    "starwhale": {"id":"starwhale","name":"星鲸","rarity":"legendary","description":"指尖碰到那片半透明深蓝的瞬间，脚下的堤岸便褪成了深空，你正悬浮在缓缓旋转的银河上，它体内的星辉穿过你的胸膛，让你听见自己血管里响起了古老的鲸歌，直到它一摆尾，世界才'咔'地落回原地。","size_min":200,"size_max":450,"size_unit":"cm","base_value":480,"locations":["abyssal_trench","floating_lake"],"seasons":["winter"],"tags":["deepsea","fantasy","glowing"],"latin":"Cetus astralis","rumor":"老捕鲸人说，星鲸的胃里装着一片完整的星空，剖开时流星会像雨一样落进海里。"},
    "time_eater": {"id":"time_eater","name":"时噬鱼","rarity":"mythic","description":"将它托出水面的那一刻，所有声音都被它体内的表盘裂缝一口吞尽，你看见刚才的自己正站在钓点上朝你望来，而四周的虫鸣与风被拧成可见的细丝，正被它一点点吸进破裂的钟面里，直到它微微颤动，时间才轰然倒灌，你的心跳重新响起。","size_min":1,"size_max":999,"size_unit":"cm","base_value":1000,"locations":["all"],"seasons":["all"],"tags":["fantasy","shadow","deepsea"],"individual_weight":0.3,"latin":"Chronoichthys devorans","rumor":"钓到时噬鱼的那一刻，你突然记不起昨天中午吃了什么，只觉得鱼竿一沉，三年便过去了。"},
    "bog_creeper": {"id":"bog_creeper","name":"沼行鱼","rarity":"common","description":"身体摊平如一片腐烂的阔叶，能在淤泥上匍匐爬行，受惊时蜷成枯球顺水滚走。","size_min":8,"size_max":22,"size_unit":"cm","base_value":7,"locations":["whispering_mire"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater","swamp","nocturnal"],"latin":"Misgurnus palustris"},
    "bloat_toadfish": {"id":"bloat_toadfish","name":"鼓蟾鱼","rarity":"uncommon","description":"鳃囊鼓胀如毒囊，布满暗紫色疣突，一离水就发出沉闷的咕哝声，吐出苦腥的雾气。","size_min":15,"size_max":38,"size_unit":"cm","base_value":27,"locations":["whispering_mire"],"seasons":["spring","summer","autumn"],"tags":["freshwater","swamp","poison"],"latin":"Opsanus tumidus"},
    "wraithwood_fish": {"id":"wraithwood_fish","name":"朽木灵鱼","rarity":"rare","description":"半透明的身体内裹着枯木的纹理，游动时拖曳几缕黑烟，眼窝里飘着两团幽冥的磷火。","size_min":25,"size_max":55,"size_unit":"cm","base_value":105,"locations":["whispering_mire"],"seasons":["spring","autumn"],"tags":["freshwater","swamp","nocturnal","poison"],"latin":"Xylopsychus umbra"},
    "star_sand_darter": {"id":"star_sand_darter","name":"星沙镖鲈","rarity":"common","description":"体侧嵌满荧蓝光点，每年随潮水涌入三角洲时，整片浅滩像倒悬的银河在脚下奔流。","size_min":6,"size_max":16,"size_unit":"cm","base_value":7,"locations":["starry_delta"],"seasons":["spring","autumn"],"tags":["brackish","glowing","migratory"],"latin":"Ammocrypta siderea"},
    "tidal_trout": {"id":"tidal_trout","name":"潮信鳟","rarity":"uncommon","description":"鳞片泛着潮汐的银蓝光泽，只在朔望大潮时成群溯河，鳃盖开合间隐约传来海浪的节奏。","size_min":30,"size_max":60,"size_unit":"cm","base_value":26,"locations":["starry_delta"],"seasons":["spring","autumn"],"tags":["brackish","migratory","fantasy"],"latin":"Salmo aestuarium"},
    "star_barge_whisker": {"id":"star_barge_whisker","name":"星舟巨鲶","rarity":"epic","description":"沉重的身躯压得钓竿呻吟，皮肤粗糙如冷却的熔岩，凑近能闻到铁锈和遥远星尘的干涩气味，它喉间发出的次声波让水面跳起细密的水珠。","size_min":120,"size_max":220,"size_unit":"cm","base_value":220,"locations":["starry_delta"],"seasons":["spring"],"tags":["brackish","fantasy","glowing","migratory"],"latin":"Astroglanis grandis"},
    "urn_hermit": {"id":"urn_hermit","name":"瓮居蟹","rarity":"common","description":"寄居在碎裂的双耳陶瓮里，在沉船残骸间横行时，瓮中偶尔传出远古的低语与隐隐的钟鸣。","size_min":5,"size_max":15,"size_unit":"cm","base_value":6,"locations":["sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","ancient"],"latin":"Coenobita urna"},
    "rune_cod": {"id":"rune_cod","name":"铭文鳕","rarity":"uncommon","description":"侧线刻满失传的上古符文，游过覆满海藻的石柱时，那些文字会短暂地亮起琥珀色光芒。","size_min":30,"size_max":65,"size_unit":"cm","base_value":28,"locations":["sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","ancient","glowing"],"latin":"Gadus runicus"},
    "sunken_wraith": {"id":"sunken_wraith","name":"沉城幽魂鱼","rarity":"epic","description":"触感滑腻而冰冷，散发出一股潮湿石灰与朽木的霉息，贴近耳朵时能听见水下钟楼残破的钟声在空腔里回荡。","size_min":70,"size_max":130,"size_unit":"cm","base_value":230,"locations":["sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","ancient","glowing","shadow"],"latin":"Phantomoichthys submergus"},
    "sulfur_killie": {"id":"sulfur_killie","name":"硫华鳉","rarity":"common","description":"在滚烫的硫磺泉中游弋的鳉鱼，鳞片析出明黄的硫磺结晶，捞起晒干后划一根火柴就能点燃。","size_min":4,"size_max":12,"size_unit":"cm","base_value":8,"locations":["geyser_falls"],"seasons":["summer","autumn"],"tags":["fire","mineral"],"latin":"Fundulus sulpureus"},
    "steam_ray": {"id":"steam_ray","name":"蒸汽鳐","rarity":"uncommon","description":"从热瀑顶端一跃而下的扁鱼，喷气孔排出咻咻白烟，恍若一台微型蒸汽机车划破水幕。","size_min":35,"size_max":70,"size_unit":"cm","base_value":29,"locations":["geyser_falls"],"seasons":["spring","summer"],"tags":["fire","mineral"],"latin":"Rajella vaporis"},
    "magma_peacock_bass": {"id":"magma_peacock_bass","name":"熔岩孔雀鲷","rarity":"rare","description":"体侧矿脉交错，遇热会绽开孔雀尾屏般的虹彩，只在蒸汽最浓处露面，宛如打翻了一盒熔化的宝石。","size_min":28,"size_max":52,"size_unit":"cm","base_value":110,"locations":["geyser_falls"],"seasons":["summer"],"tags":["fire","mineral","fantasy"],"latin":"Cichla ignis"},
    "mudskipper_perch": {"id":"mudskipper_perch","name":"泥蟹攀鲈","rarity":"common","description":"用强壮的胸鳍在泥滩上匍匐爬行，甲壳上糊满贝壳碎屑与枯叶，像一团会移动的垃圾堆。","size_min":12,"size_max":28,"size_unit":"cm","base_value":6,"locations":["mangrove_shoal"],"seasons":["spring","summer","autumn"],"tags":["brackish","armored"],"latin":"Periophthalmus lutarius"},
    "root_dragon": {"id":"root_dragon","name":"气根龙","rarity":"rare","description":"伪装成红树气根的细长鱼，能在空气中呼吸数小时，暴风雨后会扭动着攀上矮枝，等待下一场潮水。","size_min":40,"size_max":75,"size_unit":"cm","base_value":95,"locations":["mangrove_shoal"],"seasons":["spring","summer"],"tags":["brackish","fantasy"],"latin":"Rhizophydra pneumatophora"},
    "prism_lanternfish": {"id":"prism_lanternfish","name":"棱镜灯鱼","rarity":"uncommon","description":"身体由无数微小水晶碎片聚合而成，游动时像一枚迪斯科球，在洞壁上泼洒旋转的虹光。","size_min":10,"size_max":25,"size_unit":"cm","base_value":28,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","glowing"],"latin":"Myctophum prismaticum"},
    "shard_shrimp": {"id":"shard_shrimp","name":"碎晶虾","rarity":"uncommon","description":"披着透明水晶甲壳的虾，双螯如同两柄玻璃匕首，敲击岩壁时会奏出风铃般的清脆音符。","size_min":12,"size_max":30,"size_unit":"cm","base_value":30,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","armored"],"latin":"Caridina vitreus"},
    "crystal_leviathan": {"id":"crystal_leviathan","name":"洞天晶龙","rarity":"legendary","description":"握住一片晶柱鳞片的刹那，四周的水体突然凝固成无数面棱镜，每一面都囚着一座正在旋转的陌生星空，你看见自己的倒影被拆分进千百个不同的星系里，同时听见水晶岩洞深处传来一声悠长的吐息，直到它游走，所有镜面才碎成无声的荧光。","size_min":150,"size_max":280,"size_unit":"cm","base_value":480,"locations":["crystal_cave"],"seasons":["winter"],"tags":["crystal","glowing","fantasy"],"individual_weight":0.6,"latin":"Crystallosaurus antricola","rumor":"洞天晶龙是千万年钟乳石的集体梦境，一旦被带离洞穴，原地的石头将失去光泽，变成普通的石灰岩。"},

    "crucian": {"id": "crucian", "name": "鲫鱼", "rarity": "common", "description": "最常见的练手鱼，银灰色，憨头憨脑地咬钩。", "size_min": 8, "size_max": 25, "size_unit": "cm", "base_value": 6, "locations": ["moonlit_pond", "reed_river"], "seasons": ["all"], "tags": ["freshwater"],"latin":"Carassius carassius"},
    "silver_dace": {"id": "silver_dace", "name": "银鲦", "rarity": "common", "description": "成群结队的小银鱼，阳光下鳞片闪成一片碎光。", "size_min": 6, "size_max": 18, "size_unit": "cm", "base_value": 5, "locations": ["reed_river"], "seasons": ["all"], "tags": ["freshwater"],"latin":"Rhinichthys argenteus"},
    "reed_perch": {"id": "reed_perch", "name": "芦苇鲈", "rarity": "uncommon", "description": "潜伏在芦苇丛里的伏击手，背鳍带着锯齿状的纹路。", "size_min": 15, "size_max": 40, "size_unit": "cm", "base_value": 22, "locations": ["reed_river", "moonlit_pond"], "seasons": ["spring", "summer"], "tags": ["freshwater"],"latin":"Perca arundinis"},
    "glow_jelly": {"id": "glow_jelly", "name": "光水母", "rarity": "uncommon", "description": "半透明的伞状身体里悬着一点幽蓝的光，随水流一缩一放。", "size_min": 10, "size_max": 35, "size_unit": "cm", "base_value": 28, "locations": ["abyssal_trench"], "seasons": ["all"], "tags": ["deepsea", "glowing", "nocturnal"],"latin":"Pelagia lucida"},
    "moonscale_carp": {"id": "moonscale_carp", "name": "月鳞鲤", "rarity": "rare", "description": "鳞片在夜色中泛着银白冷光，仿佛吞下了一小片月亮。据说它只会咬住倒映在水面的满月。", "size_min": 20, "size_max": 60, "size_unit": "cm", "base_value": 80, "locations": ["moonlit_pond"], "seasons": ["autumn", "winter"], "tags": ["freshwater", "nocturnal"],"latin":"Cyprinus lunaris"},
    "ember_carp": {"id": "ember_carp", "name": "熔岩鲤", "rarity": "rare", "description": "通体橙红，鳞缝里透出岩浆般的光，离水后仍微微发烫。", "size_min": 18, "size_max": 55, "size_unit": "cm", "base_value": 110, "locations": ["lava_spring"], "seasons": ["summer"], "tags": ["fire"],"latin":"Cyprinus pruna"},
    "windveil_ray": {"id": "windveil_ray", "name": "风纱鳐", "rarity": "epic", "description": "轻得几乎不存在，出水后若不立即捧住，便如薄纱般被风撕走，只留一缕薄荷和雨前空气的清凉在指尖。", "size_min": 25, "size_max": 70, "size_unit": "cm", "base_value": 180, "locations": ["floating_lake"], "seasons": ["spring", "summer", "autumn"], "tags": ["fantasy", "wind"],"latin":"Velumventus aura"},
    "frostfin_eel": {"id": "frostfin_eel", "name": "霜鳍鳗", "rarity": "epic", "description": "握在手里凉得发疼，鳍尖的霜化在掌心，像攥着一把不肯停的冬天，松开后还能听见冰裂的细响在骨头里回荡。", "size_min": 30, "size_max": 90, "size_unit": "cm", "base_value": 220, "locations": ["abyssal_trench"], "seasons": ["winter"], "tags": ["deepsea", "glowing"],"latin":"Conger gelidus"},
    "clockwork_koi": {"id": "clockwork_koi", "name": "发条锦鲤", "rarity": "legendary", "description": "手指覆上它打磨般的黄铜鳞片时，耳中的滴答声猛地扩成一座看不见的钟楼，无数透明的齿轮从你眼前啮合着升起，日与夜在你皮肤上像翻书一样快速明灭，你闻到了时间本身的气味——旧铜、干涸的机油和亿万个正午的暴晒，直到它一甩尾，你才从时间的齿缝里跌回岸边。", "size_min": 30, "size_max": 80, "size_unit": "cm", "base_value": 400, "locations": ["floating_lake"], "seasons": ["all"], "tags": ["fantasy"],"latin":"Machina cyprinus","rumor":"发条锦鲤体内的齿轮日夜不停，有钟表匠从它鳃盖里听出了某座早已沉没的城市敲响的午时钟声。"},
    "the_first_drop": {"id": "the_first_drop", "name": "「第一滴水」", "rarity": "mythic", "description": "你小心翼翼地捧起这尾近乎不存在的水影，指尖却触到了一片混沌的冰凉，耳中猛然炸开天地初分时的第一声雷鸣，无数道原始的雨丝自虚空垂落，在你眼前汇成海洋、冲积出河床，直到它轻轻滑回水中，这场只有你目睹的创世暴雨才骤然停歇。", "size_min": 1, "size_max": 30, "size_unit": "cm", "base_value": 1000, "locations": ["all"], "seasons": ["all"], "individual_weight": 1.0, "tags": ["fantasy"],"latin":"Primastilla primordialis","rumor":"「第一滴水」是海洋的第一粒种子，握在手里时能听见世界诞生时的第一声雷，在掌心嗡嗡作响。"},
}
BAITS = {
    "basic_worm": {"id": "basic_worm", "name": "普通蚯蚓", "cost": 10, "description": "最朴素的蚯蚓，没有任何特殊效果，胜在便宜。", "effects": {}},
    "glow_bait": {"id": "glow_bait", "name": "夜光饵", "cost": 35, "description": "在黑暗中散发幽幽蓝光，对夜行性鱼类格外有吸引力。", "effects": {"rarity_weight_mult": {"rare": 1.5, "epic": 1.3}, "tag_weight_mult": {"nocturnal": 2.0}, "junk_chance_mult": 0.8}},
    "golden_lure": {"id": "golden_lure", "name": "黄金亮片", "cost": 80, "description": "华丽的金色旋转亮片，全稀有度的鱼都更容易上钩。", "effects": {"rarity_weight_mult": {"rare": 1.4, "epic": 1.6, "legendary": 2.0, "mythic": 2.0}, "junk_chance_mult": 0.7}},
}
# 特殊事件 / 物品：留空 = 不触发（填了内容自动激活）
EVENTS = json.loads(r"""{"drift_bottle":{"id":"drift_bottle","name":"漂流瓶","type":"bottle","weight":145,"unique":true,"description":"一只随波而来的玻璃瓶撞上你的浮标——瓶里卷着一张陌生人写的纸条。","messages":["（致捞到这只瓶子的人：今天也辛苦啦，愿你下一竿就是大鱼。——一个把烦恼塞进瓶子扔进海里的人）","（瓶子里只有一句话：如果你读到这里，说明海把它送对了人。祝你好运。）","（一张被海水泡得发皱的纸条，上面画着一条歪歪扭扭的鱼，旁边写着：我钓了一整天，只钓到这只瓶子。哈。）","（恭喜你捞到一只空瓶——里面什么都没有，连张纸条都没有。就当大海跟你打了个招呼吧。）","（纸条上是一行陌生的字：愿你所求皆有回响，愿你所钓皆有惊喜。落款是一个谁也认不出的签名。）","（瓶里卷着半角旧海图，海岸线早被水泡得模糊，只有一处被红笔圈住，写着「这片海的鱼最好钓」——可惜没人知道是哪片海。）"],"rewards":{}},"floating_coral_pearl":{"id":"floating_coral_pearl","name":"漂来的珊瑚珠","type":"treasure","weight":18,"description":"浪尖上托着一颗粉红的珍珠，随着波光上下起浮，像一朵珊瑚花。","rewards":{"items":[{"id":"coral_pearl","qty":1}]}},"ambergris_chunk":{"id":"ambergris_chunk","name":"浮香的龙涎","type":"treasure","weight":10,"description":"一块灰白的蜡状物漂浮过来，空气里忽然漫开一股奇异的幽香。","rewards":{"items":[{"id":"ambergris","qty":1}]}},"rusty_chest":{"id":"rusty_chest","name":"锈迹宝箱","type":"chest","weight":25,"description":"一只包着铁皮的旧木箱浮出水面，铁锁布满红锈，但依然坚固。","lock":{"or_points":80},"loot_table":[{"weight":60,"reward":{"points_range":[100,200]}},{"weight":15,"reward":{"items":[{"id":"ancient_key","qty":1}]}},{"weight":15,"reward":{"items":[{"id":"gem_sapphire","qty":1}]}},{"weight":5,"reward":{"bait":[{"id":"golden_lure","qty":1}]}},{"weight":5,"reward":{"items":[{"id":"shipwreck_coin","qty":1}]}}]},"barnacle_chest":{"id":"barnacle_chest","name":"藤壶密箱","type":"chest","weight":20,"description":"一只被藤壶层层包裹的石箱，盖子上刻着古老的漩涡纹，没有锁孔，却紧密得几乎撬不开。","lock":{"or_points":60},"loot_table":[{"weight":50,"reward":{"points_range":[80,180]}},{"weight":30,"reward":{"items":[{"id":"moonstone","qty":1}]}},{"weight":20,"reward":{"bait":[{"id":"glow_bait","qty":3}]}}]},"ancient_captain_chest":{"id":"ancient_captain_chest","name":"船长遗箱","type":"chest","weight":8,"description":"一只雕着海怪缠锚图案的暗铜宝箱，从深水缓缓升起，海水从锁孔里汩汩流出。","lock":{"requires_item":"ancient_key","or_points":200},"loot_table":[{"weight":40,"reward":{"points_range":[150,300]}},{"weight":35,"reward":{"items":[{"id":"moonstone","qty":1},{"id":"gem_sapphire","qty":1}]}},{"weight":25,"reward":{"bait":[{"id":"golden_lure","qty":2}]}}]}}""")
ITEMS = json.loads(r"""{"coral_pearl":{"id":"coral_pearl","name":"珊瑚珍珠","type":"treasure","description":"粉红色的珍珠，带着珊瑚的温润光泽，仿佛刚从人鱼的王冠上摘下。","value":150,"sellable":true},"gem_sapphire":{"id":"gem_sapphire","name":"蓝宝石","type":"treasure","description":"深海般的蓝色，里面封存着浪涛的纹路，轻晃时仿佛有潮声。","value":300,"sellable":true},"moonstone":{"id":"moonstone","name":"月光石","type":"treasure","description":"乳白色的石头上流转着月华般的光晕，传说月光凝结而成。","value":450,"sellable":true},"ambergris":{"id":"ambergris","name":"龙涎香","type":"treasure","description":"传说中的鲸之宝，散发着奇异幽香，正是香料商人梦寐以求的至宝。","value":500,"sellable":true},"shipwreck_coin":{"id":"shipwreck_coin","name":"沉船金币","type":"treasure","description":"一枚古老的金币，正面刻着模糊的王冠，背面是早已沉没的船名。","value":200,"sellable":true},"ancient_key":{"id":"ancient_key","name":"古老的钥匙","type":"key","description":"一把沉重的黄铜钥匙，尾端雕着海怪缠锚的图案，握在手里仿佛能听见远航的号角。","value":0,"sellable":false}}""")

_SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".", "fishing_save.json")
_IO_WARN = ""   # 存档读/写出问题时的一次性提示；cmd() 会把它贴在输出末尾，不再静默吞掉

def _new_state(seed=_DEFAULT_SEED):
    seed = int(seed) & 0xFFFFFFFF
    return {"version": 1, "seed": seed, "rngState": seed, "rngCalls": 0, "turn": 0,
            "season_id": "spring", "season_length": 20, "season_started_turn": 0,
            "points": 200, "location_id": "moonlit_pond", "unlocked_locations": ["moonlit_pond", "reed_river"],
            "bait_inventory": {"basic_worm": 5}, "catch_inventory": [], "items": {}, "pending_chests": [], "seen_letters": {},
            "encyclopedia": {}, "stats": {"total_casts": 0, "total_caught": 0, "total_chests": 0}, "local_dry": 0}

S = None
def _load():
    global S, _IO_WARN
    if S is not None:
        return S
    if os.path.exists(_SAVE):
        try:
            with open(_SAVE, "r", encoding="utf-8") as f:
                S = json.load(f)
        except Exception as e:
            # 存档存在却读不出/损坏：别静默丢档——备份一份再开新局，并提示玩家
            try: os.replace(_SAVE, _SAVE + ".corrupt")
            except Exception: pass
            S = _new_state()
            _IO_WARN = "⚠️ 存档读取失败（%s）：已把坏档备份为 %s，并开了一局新的。" % (e, os.path.basename(_SAVE) + ".corrupt")
    else:
        S = _new_state()   # 首次运行，找不到存档是正常的，不提示
    S.setdefault("items", {}); S.setdefault("pending_chests", []); S.setdefault("seen_letters", {}); S.setdefault("local_dry", 0)
    S.setdefault("stats", {}).setdefault("total_chests", 0)
    S["stats"].setdefault("total_casts", 0); S["stats"].setdefault("total_caught", 0)
    return S
def _save():
    global _IO_WARN
    try:
        with open(_SAVE, "w", encoding="utf-8") as f:
            json.dump(S, f, ensure_ascii=False)
    except Exception as e:
        # 写不进去（目录只读/没权限/磁盘满）：别让玩家以为存上了
        _IO_WARN = "⚠️ 存档写入失败（%s）：本局进度可能不会被保存，检查一下目录权限/磁盘空间。" % e

def _eligible(f, loc_id, sea_id):
    lo = "all" in f["locations"] or loc_id in f["locations"]
    so = "all" in f["seasons"] or sea_id in f["seasons"]
    return lo and so
def _eff_weight(f, loc_id, sea_id, bait_id):
    loc, sea, bait = LOCATIONS[loc_id], SEASONS[sea_id], BAITS[bait_id]
    w = RARITY[f["rarity"]]["weight"] * f.get("individual_weight", 1.0)
    for tag in f.get("tags", []):
        w *= loc.get("tag_weight_mult", {}).get(tag, 1.0)
        w *= sea.get("tag_weight_mult", {}).get(tag, 1.0)
        w *= bait["effects"].get("tag_weight_mult", {}).get(tag, 1.0)
    w *= bait["effects"].get("rarity_weight_mult", {}).get(f["rarity"], 1.0)
    return w
def _wpick(rng, items, weights):
    total = sum(weights); r = rng.random() * total; up = 0.0
    for it, w in zip(items, weights):
        up += w
        if r <= up:
            return it
    return items[-1]
def _roll_size(rng, f):
    a, b = f["size_min"], f["size_max"]
    base = a + (b - a) * (rng.random() + rng.random()) / 2
    if rng.random() < 0.03:
        base = b - (b - base) * rng.random() * 0.3
    return round(base, 1)
def _value(f, size):
    mid = (f["size_min"] + f["size_max"]) / 2
    return max(1, round(f["base_value"] * (size / mid) ** 1.5))
def _upd_enc(f, size, value):
    first = f["id"] not in S["encyclopedia"]
    if first:
        S["encyclopedia"][f["id"]] = {"discovered": True, "first_caught_turn": S["turn"], "count": 0, "max_size": 0, "total_value_earned": 0}
    e = S["encyclopedia"][f["id"]]
    e["count"] += 1; e["max_size"] = max(e["max_size"], size); e["total_value_earned"] += value
    return first
def _adv_season():
    if S["turn"] - S["season_started_turn"] >= S["season_length"]:
        ordered = sorted(SEASONS.values(), key=lambda x: x["order"])
        cur = SEASONS[S["season_id"]]["order"]
        nxt = ordered[(cur + 1) % len(ordered)]
        old = SEASONS[S["season_id"]]["name"]
        S["season_id"] = nxt["id"]; S["season_started_turn"] = S["turn"]; S["local_dry"] = 0
        return "🍃 %s季结束，已进入%s季——某些鱼群离开了这片水域，也有新的鱼群正等着被发现。\n" % (old, nxt["name"])
    return ""

# ── 特殊事件 / 物品 ──
def _pick_by_weight(rng, arr):
    total = sum(x["weight"] for x in arr); r = rng.random() * total; up = 0.0
    for it in arr:
        up += it["weight"]
        if r <= up:
            return it
    return arr[-1]
def _grant_rewards(rng, rw):
    parts = []
    if not rw: return parts
    if rw.get("points_range"):
        p = rng.rint(rw["points_range"][0], rw["points_range"][1]); S["points"] += p; parts.append("+%d点" % p)
    for b in rw.get("bait", []):
        S["bait_inventory"][b["id"]] = S["bait_inventory"].get(b["id"], 0) + b["qty"]; parts.append("%s×%d" % (BAITS.get(b["id"], {}).get("name", b["id"]), b["qty"]))
    for it in rw.get("items", []):
        S["items"][it["id"]] = S["items"].get(it["id"], 0) + it["qty"]; parts.append("%s×%d" % (ITEMS.get(it["id"], {}).get("name", it["id"]), it["qty"]))
    return parts
def _letter_exhausted(e):
    return bool(e.get("unique")) and len(S["seen_letters"].get(e["id"], [])) >= len(e.get("messages", []))
def _resolve_event(rng):
    lst = [e for e in EVENTS.values() if e["type"] != "junk" and not _letter_exhausted(e)]
    if not lst: return "水面晃了晃，又归于平静。\n%s" % _footer()
    ev = _pick_by_weight(rng, lst)
    if ev["type"] == "chest":
        S["stats"]["total_chests"] += 1
        uid = "ch_%03d" % S["stats"]["total_chests"]
        S["pending_chests"].append({"chest_uid": uid, "event_id": ev["id"]})
        return "📦 %s！%s\n（用 open %s 打开）\n%s" % (ev["name"], ev["description"], uid, _footer())
    if ev["type"] == "bottle" and ev.get("unique") and ev.get("messages"):
        seen = S["seen_letters"].setdefault(ev["id"], [])
        avail = [i for i in range(len(ev["messages"])) if i not in seen]
        idx = avail[rng.rint(0, len(avail) - 1)]
        seen.append(idx)
        parts = _grant_rewards(rng, ev.get("rewards"))
        return "📜 %s！%s\n%s\n★ 收到新的一封！（已收集 %d/%d，用 encyclopedia 回看）%s\n%s" % (ev["name"], ev["description"], ev["messages"][idx], len(seen), len(ev["messages"]), ("\n获得 " + "、".join(parts)) if parts else "", _footer())
    msg = ""
    if ev["type"] == "bottle" and ev.get("messages"):
        msg = "\n" + ev["messages"][rng.rint(0, len(ev["messages"]) - 1)]
    parts = _grant_rewards(rng, ev.get("rewards"))
    icon = "📜" if ev["type"] == "bottle" else "✨"
    return "%s %s！%s%s%s\n%s" % (icon, ev["name"], ev["description"], msg, ("\n获得 " + "、".join(parts)) if parts else "", _footer())
def _c_open(uid):
    idx = next((i for i, c in enumerate(S["pending_chests"]) if c["chest_uid"] == uid), -1)
    if idx < 0: return "没有这个待开的宝箱：%s。（inventory 里看待开宝箱）" % uid
    ev = EVENTS.get(S["pending_chests"][idx]["event_id"])
    if not ev:
        S["pending_chests"].pop(idx); return "宝箱 %s 数据缺失，已丢弃。" % uid
    rng = _Rng(S["rngState"], S["rngCalls"])
    lock = ev.get("lock")
    if lock:
        if lock.get("requires_item") and S["items"].get(lock["requires_item"], 0) > 0:
            S["items"][lock["requires_item"]] = S["items"].get(lock["requires_item"], 0) - 1
        elif lock.get("or_points") is not None and S["points"] >= lock["or_points"]:
            S["points"] -= lock["or_points"]
        else:
            need = " 或 ".join([x for x in [(ITEMS.get(lock["requires_item"], {}).get("name", lock["requires_item"]) if lock.get("requires_item") else ""), ("%d点" % lock["or_points"]) if lock.get("or_points") is not None else ""] if x])
            return "%s 打不开：需要 %s（都不够）。宝箱先留着。" % (uid, need)
    S["pending_chests"].pop(idx)
    parts = _grant_rewards(rng, _pick_by_weight(rng, ev["loot_table"])["reward"]) if ev.get("loot_table") else _grant_rewards(rng, ev.get("rewards"))
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    return "🗝 打开了 %s！%s\n%s" % (ev["name"], ("获得 " + "、".join(parts)) if parts else "里面空空如也…", _footer())

_JUNK = ["一只灌满水的破靴子", "半截生锈的罐头", "一团缠死的旧鱼线", "一块被水磨圆的碎瓷片", "邻居家漂走的塑料小鸭"]
def _rar(k): return RARITY[k]["label"] + " " + RARITY[k]["tag"]
def _sloc(): return LOCATIONS[S["location_id"]]["name"] + " · " + SEASONS[S["season_id"]]["name"]
def _footer(): return "点数 %d ｜ %s ｜ 回合 %d ｜ 图鉴 %d/%d" % (S["points"], _sloc(), S["turn"], len(S["encyclopedia"]), len(FISH))

def _c_status():
    baits = "、".join("%s×%d" % (BAITS[b]["name"], n) for b, n in S["bait_inventory"].items() if n > 0) or "（没饵了，去 shop 买）"
    extra = ""
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items: extra += "\n物品：" + "、".join("%s×%d" % (ITEMS.get(k, {}).get("name", k), n) for k, n in items)
    if S.get("pending_chests"): extra += "\n📦 待开宝箱 %d 个（inventory 看，open 开）" % len(S["pending_chests"])
    return "【状态】%s\n鱼饵：%s\n未卖渔获：%d 条 ｜ 总抛竿 %d%s" % (_footer(), baits, len(S["catch_inventory"]), S["stats"]["total_casts"], extra)
def _c_shop():
    lines = ["%s　%s　%d点　%s" % (b["id"], b["name"], b["cost"], ("（有偏好加成，见 look）" if (b["effects"].get("tag_weight_mult") or b["effects"].get("rarity_weight_mult")) else "无特殊效果")) for b in BAITS.values()]
    return "【商店】（buy <鱼饵id> [数量]）\n" + "\n".join(lines) + \
        "\n老板搓了搓手：「好饵能让这片水里本来就有的鱼更肯上钩、更容易出稀有货——可它变不出新鱼种。想钓没见过的鱼，得换个水域、换个季节去寻。」"
def _c_buy(bait_id, qty):
    b = BAITS.get(bait_id)
    if not b: return "没有这种鱼饵：%s。用 shop 看货架。" % bait_id
    qty = max(1, int(qty)); cost = b["cost"] * qty
    if S["points"] < cost: return "点数不够：%s×%d 需 %d 点，你只有 %d。" % (b["name"], qty, cost, S["points"])
    S["points"] -= cost; S["bait_inventory"][bait_id] = S["bait_inventory"].get(bait_id, 0) + qty
    return "买了 %s×%d，花 %d 点。剩 %d 点，现有 %s×%d。" % (b["name"], qty, cost, S["points"], b["name"], S["bait_inventory"][bait_id])
def _goto_list():
    def rank(l):
        return 0 if l["id"] == S["location_id"] else (1 if l["id"] in S["unlocked_locations"] else 2)
    entries = sorted(LOCATIONS.values(), key=lambda l: (rank(l), l["unlock_cost"]))
    lines = []
    for l in entries:
        cur = l["id"] == S["location_id"]; unlocked = l["id"] in S["unlocked_locations"]
        mark = "✦" if cur else ("·" if unlocked else "🔒")
        st = "【当前】" if cur else ("已解锁" if unlocked else "%d点解锁" % l["unlock_cost"])
        sea = "本季有鱼" if S["season_id"] in l["available_seasons"] else "本季冷清"
        lines.append("  %s %s　%s　—— %s · %s" % (mark, l["name"], l["id"], st, sea))
    return "【钓点】（goto <地点id> 前往；🔒 的需花点数解锁）\n%s\n（你有 %d 点）" % ("\n".join(lines), S["points"])
def _c_goto(loc_id):
    if not loc_id: return _goto_list()   # 不带参数 = 列出所有钓点
    loc = LOCATIONS.get(loc_id)
    if not loc: return "没有这个地点：%s。（goto 不带地点可看钓点清单）" % loc_id
    if loc_id not in S["unlocked_locations"]:
        if S["points"] < loc["unlock_cost"]: return "%s 还没解锁，需 %d 点，你只有 %d。" % (loc["name"], loc["unlock_cost"], S["points"])
        S["points"] -= loc["unlock_cost"]; S["unlocked_locations"].append(loc_id)
    S["location_id"] = loc_id; S["local_dry"] = 0
    off = "（注意：本季节这里没什么鱼）" if S["season_id"] not in loc["available_seasons"] else ""
    char = ("\n" + loc["character"]) if loc.get("character") else ""
    return "来到【%s】。%s%s%s\n%s" % (loc["name"], loc["description"], char, off, _footer())
def _c_inv():
    out = []
    if S["catch_inventory"]:
        out.append("🐟 渔获：\n" + "\n".join("  %s　%s　%scm　%d点" % (c["instance_id"], FISH.get(c["fish_id"], {}).get("name", c["fish_id"]), c["size"], c["value"]) for c in S["catch_inventory"]))
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items:
        out.append("🎁 物品：\n" + "\n".join("  %s　%s×%d%s" % (k, ITEMS.get(k, {}).get("name", k), n, ("（可 sell item %s）" % k) if ITEMS.get(k, {}).get("sellable") else "") for k, n in items))
    if S.get("pending_chests"):
        out.append("📦 待开宝箱：\n" + "\n".join("  %s（open %s）" % (c["chest_uid"], c["chest_uid"]) for c in S["pending_chests"]))
    if not out: return "渔篓空空。去 cast 抛几竿吧。"
    return "【渔篓】（sell <实例id>/sell all/sell species <鱼id>/sell item <物品id>）\n" + "\n".join(out)
def _c_sell(target):
    target = (target or "").strip()
    m = re.match(r"^item[:\s]+(.+)$", target)
    if m:
        iid = m.group(1).strip(); it = ITEMS.get(iid)
        if not it: return "没有这种物品：%s" % iid
        if not it.get("sellable"): return "%s 不能卖。" % it["name"]
        have = S["items"].get(iid, 0)
        if have <= 0: return "你没有 %s。" % it["name"]
        gain = it["value"] * have; S["points"] += gain; S["items"][iid] = 0
        return "卖了 %s×%d，得 %d 点。现有 %d 点。" % (it["name"], have, gain, S["points"])
    sm = re.match(r"^species[:\s]+(.+)$", target)
    if target == "all":
        sold = S["catch_inventory"]; S["catch_inventory"] = []
    elif sm:
        fid = sm.group(1).strip(); sold = [c for c in S["catch_inventory"] if c["fish_id"] == fid]; S["catch_inventory"] = [c for c in S["catch_inventory"] if c["fish_id"] != fid]
    else:
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == target), None)
        if not c: return "渔篓里没有这条：%s" % target
        sold = [c]; S["catch_inventory"] = [x for x in S["catch_inventory"] if x["instance_id"] != target]
    if not sold: return "没有可卖的（%s）。" % target
    gain = sum(c["value"] for c in sold); S["points"] += gain
    return "卖了 %d 条，得 %d 点。现有 %d 点。（图鉴记录保留）" % (len(sold), gain, S["points"])
def _c_enc():
    total = len(FISH); got = len(S["encyclopedia"]); by = {}
    for f in FISH.values():
        cur = by.get(f["rarity"], [0, 0]); cur[1] += 1
        if f["id"] in S["encyclopedia"]: cur[0] += 1
        by[f["rarity"]] = cur
    rl = "　".join("%s %d/%d" % (RARITY[k]["label"], by[k][0], by[k][1]) for k in RARITY if k in by)
    lines = []
    for f in FISH.values():
        e = S["encyclopedia"].get(f["id"])
        lines.append(("✔ %s（%s）×%d 最大%scm" % (f["name"], _rar(f["rarity"]), e["count"], e["max_size"])) if e else ("· ？？？（%s）未发现" % _rar(f["rarity"])))
    lb = ""
    for ev in EVENTS.values():
        if ev.get("unique") and ev.get("messages"):
            seen = sorted(S["seen_letters"].get(ev["id"], []))
            lb += "\n\n📜 %s %d/%d" % (ev["name"], len(seen), len(ev["messages"]))
            lb += ("\n" + "\n".join("  · %s" % ev["messages"][i] for i in seen)) if seen else "\n  （还没收到任何一封）"
    return "【图鉴】%d/%d　%s\n%s%s" % (got, total, rl, "\n".join(lines), lb)
def _by_id_or_name(table, q):
    if q in table: return table[q]
    for v in table.values():
        if v.get("name") == q: return v
    return None
def _c_look(oid):
    f = _by_id_or_name(FISH, oid)
    if f:
        if f["id"] not in S["encyclopedia"]:
            return "？？？（%s）—— 你还没见过它，得亲手钓上来才会在图鉴里显形。" % _rar(f["rarity"])
        locs = "任意水域" if "all" in f["locations"] else "、".join(LOCATIONS.get(l, {}).get("name", l) for l in f["locations"])
        seas = "全年" if "all" in f["seasons"] else "、".join(SEASONS.get(x, {}).get("name", x) for x in f["seasons"])
        latin = (" (%s)" % f["latin"]) if f.get("latin") else ""; rumor = ("\n📜 传闻：%s" % f["rumor"]) if f.get("rumor") else ""
        return "%s%s（%s）\n%s%s\n体型 %s-%s%s ｜ 基础价值 %s ｜ 出没：%s · %s" % (f["name"], latin, _rar(f["rarity"]), f["description"], rumor, f["size_min"], f["size_max"], f["size_unit"], f["base_value"], locs, seas)
    l = _by_id_or_name(LOCATIONS, oid)
    if l: return "%s\n%s\n开放季节：%s　解锁 %d 点" % (l["name"], l["description"], "、".join(SEASONS[x]["name"] for x in l["available_seasons"]), l["unlock_cost"])
    b = _by_id_or_name(BAITS, oid)
    if b: return "%s（%d点）\n%s" % (b["name"], b["cost"], b["description"])
    it = _by_id_or_name(ITEMS, oid)
    if it: return "%s%s\n%s" % (it["name"], ("（财宝，售价 %d 点）" % it["value"]) if it.get("sellable") else "（功能物品，不可卖）", it["description"])
    x = _by_id_or_name(SEASONS, oid)
    if x: return "%s\n%s" % (x["name"], x["description"])
    return "没有这个对象：%s" % oid
_BITE_SOFT = ["浮标轻轻一沉——", "水面咕咚一声，浮标没了影——", "线微微一紧，有动静——"]
_BITE_HARD = ["线猛地绷紧，差点脱手——！", "竿梢狠狠一弯，水花炸开——！", "一股大力往下死拽，险些握不住——！"]
def _bite_line(rng, rarity):
    pool = _BITE_HARD if rarity in ("rare", "epic", "legendary", "mythic") else _BITE_SOFT
    return pool[rng.rint(0, len(pool) - 1)]
def _format_catch(f, size, value, inst, first):
    u = f["size_unit"]; latin = (" (%s)" % f["latin"]) if f.get("latin") else ""; rumor = ("\n   📜 传闻：%s" % f["rumor"]) if f.get("rumor") else ""; r = f["rarity"]
    nm = "　★新发现" if first else ""
    if r == "rare":
        return "✦ 稀有 ── %s%s%s\n   %s%s · 价值 %d 点　[%s]\n   %s%s" % (f["name"], latin, nm, size, u, value, inst, f["description"], rumor)
    if r == "epic":
        return "✦✦ 史诗上钩 ── %s%s%s\n   %s%s · 价值 %d 点　[%s]\n   %s%s" % (f["name"], latin, nm, size, u, value, inst, f["description"], rumor)
    if r == "legendary":
        return "👑 ─── 传 说 ─── 👑\n   %s%s\n   %s%s · 价值 %d 点　[%s]\n   %s%s%s" % (f["name"], latin, size, u, value, inst, f["description"], rumor, ("\n   ★ 图鉴新发现" if first else ""))
    if r == "mythic":
        return "✧ ───────────── ✧\n      ❖  神 话  ❖\n   %s%s\n   %s\n   %s%s · 价值 %d 点　[%s]%s%s\n✧ ───────────── ✧" % (f["name"], latin, f["description"], size, u, value, inst, rumor, ("\n   ★ 图鉴新发现" if first else ""))
    line = "· %s%s %s%s +%d　[%s]" % (f["name"], ("（少见）" if r == "uncommon" else ""), size, u, value, inst)
    if first: line += "\n   ★图鉴新发现：%s" % f["description"]
    return line
def _ambience(loc, rng):
    amb = loc.get("ambience")
    if amb and rng.random() < 0.35:
        return "\n（%s）" % amb[rng.rint(0, len(amb) - 1)]
    return ""
# ⑤ 本地点当季「非传说」鱼是否已集齐（传说/神话可遇不可求，不算进墙）
def _local_practical_cleared():
    elig = [f for f in FISH.values() if _eligible(f, S["location_id"], S["season_id"]) and f["rarity"] not in ("legendary", "mythic")]
    return bool(elig) and all(f["id"] in S["encyclopedia"] for f in elig)
# 世界内提示（不用 rng，保持三端确定性一致）
def _secret_hint():
    d = S.get("local_dry", 0)
    if d >= 8 and d % 8 == 0 and _local_practical_cleared():
        return "\n（你开始怀疑，这片水域当季或许已经没有更多秘密了——也许该 goto 换个地方，或等季节流转，去别处寻新鱼群。）"
    return ""
# 单步抛竿：返回 dict（text + 结构化结果）。rng 由调用方管理生命周期，确保连钓与单竿 rng 一致。
def _cast_step(rng, bait_id):
    inv = S["bait_inventory"]
    if not bait_id:
        avail = [b for b in inv if inv[b] > 0]
        if not avail: return {"text": "没有鱼饵了！去 shop 买点饵再来。（没扣回合）", "consumed": False, "kind": "no_bait", "season_changed": False}
        bait_id = sorted(avail, key=lambda b: BAITS[b]["cost"])[0]
    if bait_id not in BAITS: return {"text": "没有这种鱼饵：%s" % bait_id, "consumed": False, "kind": "bad_bait", "season_changed": False}
    if inv.get(bait_id, 0) <= 0: return {"text": "%s 用光了。换一种或去 shop 买。（没扣回合）" % BAITS[bait_id]["name"], "consumed": False, "kind": "no_bait", "season_changed": False}
    inv[bait_id] -= 1
    bait = BAITS[bait_id]
    S["turn"] += 1; S["stats"]["total_casts"] += 1
    season_msg = _adv_season(); season_changed = season_msg != ""
    loc = LOCATIONS[S["location_id"]]
    event_chance = (loc.get("event_chance_base", 0.05) + bait["effects"].get("event_chance_add", 0)) if EVENTS else 0
    if event_chance > 0 and rng.random() < event_chance:
        S["local_dry"] = S.get("local_dry", 0) + 1
        return {"text": season_msg + _resolve_event(rng) + _secret_hint(), "consumed": True, "kind": "event", "season_changed": season_changed}
    junk_chance = loc["junk_chance_base"] * bait["effects"].get("junk_chance_mult", 1.0)
    if rng.random() < junk_chance:
        S["local_dry"] = S.get("local_dry", 0) + 1
        return {"text": season_msg + "🪣 %s。空军一竿。\n%s%s%s" % (_JUNK[rng.rint(0, len(_JUNK) - 1)], _footer(), _ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "junk", "season_changed": season_changed}
    pool = [f for f in FISH.values() if _eligible(f, S["location_id"], S["season_id"])]
    if not pool:
        S["local_dry"] = S.get("local_dry", 0) + 1
        return {"text": season_msg + "浮标纹丝不动……这片水域这个季节什么都没咬钩。\n%s%s%s" % (_footer(), _ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "empty", "season_changed": season_changed}
    weights = [_eff_weight(f, S["location_id"], S["season_id"], bait_id) for f in pool]
    f = _wpick(rng, pool, weights); size = _roll_size(rng, f); value = _value(f, size)
    inst = "c_%03d" % (S["stats"]["total_caught"] + 1)
    S["catch_inventory"].append({"instance_id": inst, "fish_id": f["id"], "size": size, "value": value})
    S["stats"]["total_caught"] += 1; first = _upd_enc(f, size, value)
    bonus = RARITY[f["rarity"]]["discovery_bonus"] if first else 0
    if bonus: S["points"] += bonus
    S["local_dry"] = 0 if first else S.get("local_dry", 0) + 1
    bite = _bite_line(rng, f["rarity"])
    bonus_line = ("\n🎉 图鉴新发现！首次收录奖励 +%d 点" % bonus) if bonus else ""
    return {"text": season_msg + "%s\n%s%s\n%s%s%s" % (bite, _format_catch(f, size, value, inst, first), bonus_line, _footer(), _ambience(loc, rng), _secret_hint()),
            "consumed": True, "kind": "fish", "fish_name": f["name"], "rarity": f["rarity"], "first": first, "season_changed": season_changed}

def _c_cast(bait_id):
    rng = _Rng(S["rngState"], S["rngCalls"])
    out = _cast_step(rng, bait_id)["text"]
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    return out

_RARITY_RANK = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "mythic": 5}
def _cast_many(bait_id, times, stop_on):
    times = max(1, min(20, int(times)))
    if times == 1 and not stop_on: return _c_cast(bait_id)
    rng = _Rng(S["rngState"], S["rngCalls"])
    stop = set(stop_on or [])
    highlights = []; caught = {}; caught_n = 0; new_n = 0; junk_n = 0; empty_n = 0; done = 0
    stop_reason = "钓满 %d 竿" % times
    for _ in range(times):
        r = _cast_step(rng, bait_id)
        if not r["consumed"]:
            highlights.append(r["text"]); stop_reason = "没饵了"; break
        done += 1
        rank = _RARITY_RANK.get(r.get("rarity", ""), 0)
        if r.get("first") or rank >= 2 or r["kind"] == "event" or r["season_changed"]:
            highlights.append(r["text"])
        if r["kind"] == "fish":
            caught[r["fish_name"]] = caught.get(r["fish_name"], 0) + 1; caught_n += 1
            if r["first"]: new_n += 1
        elif r["kind"] == "junk": junk_n += 1
        elif r["kind"] == "empty": empty_n += 1
        if ("new" in stop and r.get("first")) or ("rare" in stop and rank >= 2) or ("event" in stop and r["kind"] == "event"):
            stop_reason = "钓到新种" if ("new" in stop and r.get("first")) else ("钓到稀有+" if ("rare" in stop and rank >= 2) else "遇到事件")
            break
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    haul = "、".join("%s×%d" % (n, c) for n, c in caught.items()) or "空军"
    tail = "🐟 上钩 %d 条%s：%s" % (caught_n, ("（新种 %d）" % new_n) if new_n else "", haul)
    if junk_n: tail += "　🪣 杂物 %d 竿" % junk_n
    if empty_n: tail += "　🌀 空竿 %d" % empty_n
    body = ("\n———\n".join(highlights) + "\n\n") if highlights else ""
    return "🎣 连钓 %d 竿 · 停因：%s\n%s—— 收获 ——\n%s\n%s" % (done, stop_reason, body, tail, _footer())

_HELP = """文字钓鱼游戏（你是玩家）。用点数买鱼饵→抛竿→按稀有度概率钓鱼→卖鱼换点数→集齐图鉴。
指令（传给 cmd()，大小写不敏感）：
  cmd('status')               看点数/地点/季节/鱼饵/图鉴进度
  cmd('shop')                 看可买鱼饵
  cmd('buy <饵id> [数量]')     买饵，如 cmd('buy glow_bait 2')
  cmd('cast [饵id]')          抛竿一次（不填=用最便宜可用饵）；核心动作
  cmd('cast [饵id] N')        一次连钓 N 竿（1~20），只回一个汇总，省来回
  cmd('cast N stop=rare')     连钓时遇到 新种(new)/稀有(rare)/事件(event) 就提前停（可逗号多选）
  cmd('goto')                 不带参数 = 列出所有钓点（价格/本季是否有鱼）
  cmd('goto <地点id>')         前往该地点（未解锁则花点数解锁）
  cmd('inventory')            看渔篓 + 物品 + 待开宝箱
  cmd('sell <实例id>') | cmd('sell all') | cmd('sell species <鱼id>') | cmd('sell item <物品id>')   卖鱼/卖财宝换点数
  cmd('open <宝箱uid>')        打开钓上来的宝箱（需钥匙或点数）
  cmd('encyclopedia')         看图鉴收集进度
  cmd('look <id或中文名>')     细看鱼/地点/鱼饵/季节/物品（如 cmd('look 月鳞鲤')；没钓到的鱼显示 ？？？）
抛竿偶尔会遇到漂流瓶/宝箱/宝物等惊喜事件。
目标：用有限点数把图鉴里的鱼尽量集满（有的鱼只在特定地点+季节出现）。一开始你并不知道有哪些鱼——靠抛竿去发现。"""

def _drain_warn(out):
    """把待提示的存档读写问题贴到输出末尾，并清空（一次性）。保证任何返回都带上 IO 提示。"""
    global _IO_WARN
    if _IO_WARN:
        out = out + "\n" + _IO_WARN
        _IO_WARN = ""
    return out

def cmd(line=""):
    """游戏的唯一入口：传一条文字指令，返回结果文字。任何输入都只返回字符串、不抛异常。"""
    _load()
    line = (line or "").strip()
    if not line:
        return _drain_warn(_HELP)
    parts = line.split()
    c = parts[0].lower(); a = parts[1:]
    try:
        if c in ("help", "h"): out = _HELP
        elif c in ("status", "s"): out = _c_status()
        elif c == "shop": out = _c_shop()
        elif c == "buy":
            if len(a) > 1 and not a[1].lstrip("+").isdigit():
                return _drain_warn("数量得是个数字，例：buy basic_worm 2。")
            out = _c_buy(a[0] if a else "", int(a[1]) if len(a) > 1 else 1)
        elif c in ("cast", "c"):
            cb = next((t for t in a if t in BAITS), None)
            ct = next((int(t) for t in a if t.isdigit()), 1)
            cs = next((t[5:].split(",") for t in a if t.startswith("stop=")), None)
            out = _cast_many(cb, ct, cs)
        elif c == "open": out = _c_open(a[0] if a else "")
        elif c in ("goto", "go"): out = _c_goto(a[0] if a else "")
        elif c in ("inventory", "inv", "i"): out = _c_inv()
        elif c == "sell": out = _c_sell(" ".join(a))
        elif c in ("encyclopedia", "enc", "e"): out = _c_enc()
        elif c in ("look", "l"): out = _c_look(a[0] if a else "")
        else: return _drain_warn("未知指令「%s」。调 cmd('help') 看词表。" % c)
    except Exception as e:
        # 公开 API 兜底：任何意外（含格式错）都返回友好文字，绝不向调用方抛栈
        return _drain_warn("这条指令没读懂（%s）。看 cmd('help')，例：buy basic_worm 2 / cast 10 stop=rare。" % e)
    _save()
    return _drain_warn(out)

def new_game(seed=_DEFAULT_SEED):
    """重开一局（可指定种子，同种子+同指令完全可复现）。"""
    global S
    S = _new_state(seed); _save()
    return "已重开新局（种子 %d）。调 cmd('help') 看规则，cmd('cast') 开钓。" % S["seed"]
