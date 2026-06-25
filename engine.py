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
# 潜水氛围句：每个钓点 × 开放季节的「下潜实况」，dive 时在结果顶部随机抽一句。DS 按模板产出。
for _lid, _amb in json.loads(r"""
{
  "reed_river": {
    "spring": [
      "你翻身沉入芦苇荡，光线在水下变成碎金箔，早春的河水裹着凉意滑过皮肤，徒手下潜，触手可及都是交错的根须。",
      "气泡顺着脸颊往上爬，水底昏暗，几尾受惊的小鱼擦过指缝，温吞的水裹着青草与淤泥的腥气，不穿防护，惬意自在。",
      "一蹬腿，芦根如帘幕分开，春水微凉却不刺骨，你能裸手摸到根须上附着的螺，水面光在头顶晃动如记忆。"
    ],
    "summer": [
      "盛夏的河水温热如浴，你拨开密密麻麻的芦秆下潜，悬浮的绿藻像纱幔拂过面庞，水底暗影里鱼群穿梭。",
      "你像条泥鳅钻入暖水，芦苇丛在水下织成绿廊，温吞的水流带着太阳的余味，徒手探入根穴，能摸到发烫的泥。",
      "蝉鸣被水隔绝，你沉入一片温润的昏黄，汗与河水交融，不必防护，裸臂划过暖流，扰动芦苇的根絮。"
    ],
    "autumn": [
      "秋意浸透河水，你深吸一口气下潜，枯败的芦叶在水里飘零，凉意顺着脊椎爬上来，但依然无需防护，裸手即可探入根丛。",
      "水色因秋叶泛黄，你潜入凉而不寒的芦苇河，断裂的芦管半埋泥中，徒手翻开，惊起一条肥硕的鲫。",
      "秋阳斜沉，你在水下仰望，万千芦根如剪影，凉水提醒季节更迭，但温和依旧，你只穿背心便滑向更深处。"
    ],
    "winter": [
      "你咬咬牙扎进冬日的芦苇河，冰凉的河水激得头皮发麻，所幸不深，几秒就适应，昏暗里芦根挂霜，徒手拨开，惊起越冬的泥鳅。",
      "冬水刺骨却清澈了些，你呵出的白气在水面散开，潜下去，根须间冰冻的枯叶轻轻碎裂，无需防护，冷意只是让触觉更敏锐。",
      "冰碴在河面漂浮，你破冰下潜，凉意如针扎，但浅滩的温柔让你徒手便可探索，芦根在冷光中像银丝。"
    ]
  },
  "moonlit_pond": {
    "spring": [
      "月光切开水面，你在春夜潜入池塘，池水微凉如绸，下沉时惊散了沉睡的锦鲤，一截沉木在幽光里像个沉睡的巨人。",
      "夜风带花香，你滑入银波，水凉丝丝裹住脚踝，月光直透池底，照亮青石与螺壳，徒手拨水，静得听见月移。",
      "你浮在春夜的池中，月影被打碎又聚拢，凉意柔和不逼人，裸臂划开水，沉木上的苔藓在光下泛着祖母绿。"
    ],
    "summer": [
      "夏夜池水沁凉，你悄然没入，月光在头顶碎成摇曳的银币，水草拂过脚踝，这里只有安详的凉意与安宁。",
      "蛙鸣鼓噪的夏夜，你浸入池塘便遁入静谧，凉爽的水涤去暑气，月下沉木如墨，你无需防护，像鱼一样游弋。",
      "你从闷热中逃进这片月光水域，凉水立刻拥抱你，睡莲茎在腿边轻荡，徒手下潜，池底的白沙反射碎光。"
    ],
    "autumn": [
      "秋月高悬，你滑入池塘，水凉得让人清醒，沉木上覆着薄薄青苔，月光穿透水面，照亮悬浮的碎叶如飘浮的星。",
      "池水因秋而清瘦，你潜入凉如水晶的夜里，月轮在头顶荡漾，沉木的纹路清晰可见，裸肤感受秋夜的冷香。",
      "一片红叶旋入池中，你随之没水，秋凉在皮肤上激起细粒，但不须防护，月光在手电不开时便是最好的光。"
    ],
    "winter": [
      "冬夜的池塘冷彻骨髓，你忍着寒意潜下，月光在水底描出沉木的轮廓，四周寂静得只听见心跳，徒手探入，指尖触到冰凉的陶罐。",
      "水面结薄冰，你破冰而入，冷冽瞬间夺走呼吸，但适应后月光将池底照得幽蓝，沉木的枝桠挂满冰晶，安全而绝美。",
      "你呵着白雾滑进冬池，凉意如刃，但徒手仍可握持，月下的池塘是冰凉的梦境，悬浮物都凝着霜。"
    ]
  },
  "whispering_mire": {
    "spring": [
      "你戴好防毒面罩沉入沼泽，黑水粘稠得像柏油，腐木斜插在淤泥里，气泡从泥底咕噜噜翻起，带着刺鼻的硫磺味。",
      "防毒服裹得严实，你踏入耳语沼泽的浑水，能见度近乎零，手电仅照出翻滚的泥雾，腐叶在耳边嘶嘶低语。",
      "黏糊的黑水包裹全身，你透过面罩呼吸，沼气让视野泛黄，陷脚的淤泥吸住靴子，这里是毒与闷热的王国。"
    ],
    "summer": [
      "盛夏的沼泽闷得像蒸笼，你潜入黑水，防毒服紧贴皮肤，视线几乎为零，只能靠手摸索，滑腻的腐叶擦过面罩，警告你不要脱下装备。",
      "闷热黏稠的空气混着毒雾，你浸入沼泽，汗水与污水交融，黑水在头灯下如浓油，断续的气泡炸开毒气，防毒面罩是你唯一屏障。",
      "你拨开黏腻的腐殖层下潜，水温烫如洗澡水，防毒服里汗流浃背，伸手不见五指，只有淤泥的吮吸声在回荡。"
    ],
    "autumn": [
      "秋风吹不散沼泽的浊气，你裹紧防毒服下水，黑水像浓汤，腐烂的树根在泥里蠕动般摇摆，每划一次水都搅起一团毒雾。",
      "秋意在沼泽只是传说，闷热依然，你潜入毒水，淤泥搅成浓浆，头灯勉强照出树根的爪形，防毒面罩里充满自己的喘息。",
      "腐叶堆积的沼泽在秋天更显黏腻，你小心避开气根上的毒刺，黑水如墨，唯有气泡翻涌出声，仿若沼泽的耳语。"
    ]
  },
  "starry_delta": {
    "spring": [
      "咸淡水在身周交融，你迎着春汛的强流下潜，无数荧光浮游生物被扰动，在你指尖绽开星尘，洄游的鲑鱼群从身侧掠过，微微凉意透过潜水服。",
      "春潮汹涌，你奋力下潜，星河般的光点随水流激荡，咸与淡在水中分出丝絮，鱼群如银箭穿梭，凉意恰到好处。",
      "你悬停在春流中，荧光藻附上潜水镜，仿佛星子在眨眼，强流推着你后背，水温微凉，但无需额外防寒。"
    ],
    "autumn": [
      "秋水清冽，你潜入星河三角洲，强流推着你漂移，荧光如碎星在旋涡里打转，远处银亮的鱼群逆流而上，水凉而不寒，恰好清醒。",
      "秋日斜照，荧光浮游聚成光带，你穿行其间，微凉的水流带着盐晶与淡水的细甜，洄游的鱼擦过你的腰侧。",
      "你在秋深的三角洲潜游，冷蓝与暖绿的水交缠，荧光在手中流逝，强流不时将你带偏，凉意提醒你身处两界之间。"
    ]
  },
  "mangrove_shoal": {
    "spring": [
      "你滑入红树林浅滩，温暖的海水混着泥沙，气根织成迷宫，才下潜就被藤蔓般的根须钩住脚蹼，不慌，轻轻解开继续探索。",
      "春日的浅滩水暖沙柔，红树气根像冒号的森林，浑浊中仍有光线洒下，小海马缠绕根须，你裸臂划过暖流。",
      "你拨开垂落的气根潜入浑水，温暖包裹全身，细沙在脚蹼下扬起，根须不时缠住手腕，提醒你放慢节奏。"
    ],
    "summer": [
      "夏季的浅滩暖得像浴缸，浑浊水里红树根如巨蟒盘结，你小心穿行，每蹬水都带起细沙，一群小海鲶好奇地跟着你。",
      "闷热午后你扎进红树浅滩，水温近似体温，浊水让能见度降为臂长，但根须的触感引路，手指轻抚过粗糙气根。",
      "你漂在夏日的浑水里，红树林的迷宫在暖流中沙沙作响，缠人的根须如游戏，无需防护，温暖的水逗弄着皮肤。"
    ],
    "autumn": [
      "秋阳斜照，暖水依然包围，你在气根间迂回，水色浑浊但根须缝隙有微光，缠上小腿的根须提醒你慢下来，这里没有危险。",
      "秋意淡淡渗入浅滩，水温仍温润，你飘过迷宫般的气根，落叶浮在水面投下碎影，根须轻搭你的肩，如老友挽留。",
      "你沉入秋日的红树林，暖水像薄毯，浊光在金棕色根须间跳跃，手指划过气根上的小牡蛎，徒手可触的富饶。"
    ]
  },
  "floating_lake": {
    "spring": [
      "你跃入浮空之湖，身体穿透水面后突然失重，悬浮在透明的水层中，脚下是无尽的云海虚空，清冷的水温加剧了眩晕，你分不清上下。",
      "春云在脚下翻涌，你悬浮在湖底之上，水清冷如初融雪水，失重感揪住胃部，气泡不再上浮而是绕着你打转。",
      "下潜即进入无依空间，你漂浮在湖与天空的缝隙，春寒透过潜水服，向下望是万尺虚空，眩晕让你抓紧水纹。"
    ],
    "summer": [
      "夏风入湖依旧清冷，你跌进悬浮层，失重感让胃翻腾，水清澈到能望见底下翻滚的云浪，你像浮游在天空与湖水的夹缝。",
      "你从这个无根之湖下潜，水流不似凡间，轻飘飘托着你，冷意如薄荷，虚空下的云海白得耀眼，你不得不闭眼适应。",
      "悬空的湖在夏日仍冰凉，你一头扎入，便被失重俘获，四面透明，底下是晴空万里，眩晕美得令人窒息。"
    ],
    "autumn": [
      "秋意让浮空湖冷得像冰泉，你沉入失重区，身体轻飘，水底虚空的云海灰蒙蒙，眩晕袭来，你得闭眼片刻才能稳住。",
      "你潜入秋日的悬湖，寒意钻骨，失重让你像片落叶打旋，云层在脚下铺展成铅灰色，这里一切方向感都失效。",
      "冰冷湖水中你睁开眼，秋云在下方奔涌，你悬浮着，气泡静止在脸侧，唯有水波轻吟，眩晕中仿若飞行。"
    ]
  },
  "lava_spring": {
    "summer": [
      "隔热服一接触水面就腾起白汽——没有它你早被烫熟。橙红的熔光在脚下脉动，硫磺气泡贴着面罩噼啪炸开，每一次呼吸都灼着喉咙。",
      "你裹紧防护服潜进滚烫的泉眼，水温高得视野都在扭曲，岩壁缝里渗出岩浆般的红光，热浪一阵阵推着你后退。",
      "像跳进液态的火，隔热服外壁嘶嘶作响，你透过面罩看到熔岩脉动，硫磺味穿透滤芯，每一秒都在测试装备极限。"
    ]
  },
  "geyser_falls": {
    "spring": [
      "你躲过间歇泉的喷口潜入热流，隔热服挡下滚烫的冲击，水下矿物结晶像玻璃花丛，光影折射出虹彩，温热的水包裹着你。",
      "春泉蒸腾，你潜入硫磺味的热流，间歇喷涌在身侧爆发，矿物梯田在热雾中闪光，隔热服让你在滚水中安全徜徉。",
      "温热泉水顺着身体轮廓流淌，你在春日下潜，矿物晶体如宝石丛林，喷泉的律动像大地的脉搏，隔热服内微汗。"
    ],
    "summer": [
      "夏日蒸腾的水汽模糊视线，你穿戴隔热潜入瀑布下的热泉，水温烫肤，但矿物梯田美得窒息，一阵阵喷涌推着你摇摆。",
      "灼热的夏季，你沉入更灼热的泉水，隔热服反射着地狱般的热度，矿物结晶在扭曲的视野中如幻境，间歇泉怒吼着喷发。",
      "你在盛夏的热泉中潜游，热气蒸得头晕，但隔热保护周全，水底矿物如流动的黄金，喷涌把你抛起又接住。"
    ],
    "autumn": [
      "秋凉浸透空气，你却在滚热的泉水中下潜，温差让矿物结晶表面凝出细密气泡，间歇泉突然喷发，强流把你托起又按下。",
      "秋风冷冽，你跃入热泉的怀抱，热水烫得皮肤隔着衣料仍感灼意，矿物在秋光中折射彩虹，喷涌的间歇为你奏着低音。",
      "你潜入秋季的热瀑之下，隔热服外热气蒸腾，水温滚热，矿物梯田在脚下延展，一阵喷涌如掌声，庆祝你的到访。"
    ],
    "winter": [
      "雪落进热泉瞬间融化，你浸入这暖流，热雾包围，身体从寒冬被拽进温泉，隔热服里微汗，水下矿物像冰雪雕塑却触手温润。",
      "冬雪纷飞，你沉入热泉，冰火两重天在面罩外交锋，热水裹身，矿物结晶在雾气中若隐若现，喷涌如间歇的火山。",
      "严寒中你投入滚热泉水，隔热服抵挡烫伤，水底晶簇蒙上蒸汽，喷口轰鸣，将冬日的僵硬融化。"
    ]
  },
  "sunken_ruins": {
    "autumn": [
      "你穿上保暖潜水服沉入秋日的遗迹，断柱在幽蓝水里静默，阴冷刺骨，远古回响仿佛从石缝渗出，每一次呼吸都凝成白雾。",
      "秋水深寒，你沿着沉城的台阶下潜，大理石柱廊在水影里扭曲，阴冷咬进骨髓，黑暗中有石像的轮廓若隐若现。",
      "你扶着半截石柱稳住身子，保暖服里的暖意在阴冷中弥足珍贵，四周幽蓝，沉城的钟声似有似无，秋意与古意交融。"
    ],
    "winter": [
      "冬日的沉没城像冰封的墓穴，你潜入墨蓝，保暖服勉强维持体温，幽光里倾倒的神殿传来低语般的回音，冷得你牙齿打颤。",
      "极寒的海水浸透一切，你游过覆满冰晶的窗棂，沉城在冬日更显阴森，黑暗的拱门仿佛通向冥界。",
      "你呼出的气泡在冷水中凝成冰屑，沉没遗迹在冬夜静如死，保暖服发出微光，照亮断壁上的霜花，寒意直透心灵。"
    ]
  },
  "abyssal_trench": {
    "spring": [
      "春日海面的暖意与你无关，你穿着耐压服坠入深渊，黑暗瞬间吞噬，冰冷高压挤压身体，头灯光柱里只有永不停歇的浮游雪。",
      "你沉入春之海沟，耐压服在高压下嘎吱作响，水温逼近冰点，头灯撕开的黑暗里，深海雪花无声飘落，深渊在呼吸。",
      "春天的深渊依旧死寂，你穿过温跃层便直坠入黑，极寒与高压紧握着你，除了头灯，唯有发光生物像远星闪烁。"
    ],
    "summer": [
      "盛夏的海底依旧是极夜，你潜进海沟，耐压服在高压下呻吟，水温接近零度，往下沉，往下沉，连时间都冻住了，只有深渊的吸噬声。",
      "阳光在几百米外消泯，你穿着耐压服拥抱夏日的深渊，冷如外太空，头灯外是无尽墨色，孤独深重得像实体。",
      "夏季表层暖水与你无关，你深入冰寒的海沟，耐压服被压得紧贴骨骼，黑暗中有幽光生物画着诡异的轨迹。"
    ],
    "autumn": [
      "秋风吹不到这万米深渊，你沉入黑水，耐压服隔绝着能压碎骨头的重负，头灯劈开黑暗，照亮悬浮的碎屑如星尘，可那冷，依然透骨。",
      "你潜入秋日深渊，耐压服是唯一庇护，极寒让关节刺痛，头灯光柱外是永恒的黑，耳边只有金属的应力声。",
      "秋天的海沟更显荒凉，你如沙粒坠入暗界，耐压服抵御着毁灭性的压强，深海的冷是种无声的暴力。"
    ],
    "winter": [
      "冬日的海面或许结冰，你沉进更深的冷寂，深渊海沟像一条黑暗的食道，高压让关节嘎吱响，黑暗里有光点倏忽明灭，那是深渊自己的幽灵。",
      "你穿着耐压服深入冬海，绝对零度的拥抱，高压在头盔里低鸣，黑暗如绒布裹住一切，只有发光的诱饵在摇摆。",
      "冬季的深渊是终极的冷箱，你潜至人类禁区，耐压服外是足以粉碎骨头的黑暗，生物微光如垂死星火，无言诉说着深海的秘密。"
    ]
  },
  "crystal_cave": {
    "spring": [
      "你轻轻滑入水晶洞潭，清冽的水恒温如泪，洞顶透下的光被晶簇切割成彩虹，小心别碰那些锋利的棱，它们割皮如刀。",
      "春泉注入晶洞，水清冽恒温，你穿梭在折射的虹光间，晶簇如利齿环伺，每一次划水都提防割伤。",
      "你潜入这个晶光世界，水温始终如一，春日的微光在晶尖上跳舞，安静得能听见晶芽生长的脆响，但别贴近，棱角锐利。"
    ],
    "summer": [
      "夏日的燥热被洞口过滤，你潜入晶光世界，水温恒定清凉，晶簇折射出的光斑在石壁上流动，安静得能听到水晶生长的声音。",
      "你躲进水晶洞穴的恒温潭水，夏阳透过洞顶裂隙，被晶簇打散成无数彩虹，清冷包裹全身，小心手臂避开尖锐的棱。",
      "洞中恒凉如水，你沉入透澈的潭，晶洞在夏日折射出冰火般的幻光，但晶刺如刃，你需如游鱼般轻灵。"
    ],
    "autumn": [
      "秋光射入晶洞，你在水下悬浮，四壁晶簇如冻结的闪电，清冽的水托着你，每一次划水都要留神尖削的晶刃。",
      "秋凉与洞内恒温交融，你潜入水晶潭，晶簇在秋光下泛金黄，锐利的棱边闪着警告，寂静中只有水划过晶面的脆响。",
      "你浸入秋日的晶洞，水清如无物，晶笋从洞顶倒悬，折射出碎星，虽美但锋锐，徒手可潜但需万分谨慎。"
    ],
    "winter": [
      "冬日洞外飘雪，你浸入恒温的潭水反而感到暖意，晶洞里光影如纱，锋利晶尖在微光中闪烁警告，下潜时需格外轻柔。",
      "外面寒冬，晶洞的水却温柔恒定，你潜入这片琉璃世界，晶簇挂满冰莹，尖刺在头灯下亮得睁不开眼。",
      "雪被隔绝在外，你在这恒温的晶潭漂浮，水晶棱柱如冰冻竖琴，清冽之水托举着你，但锋锐的棱角时时提醒你要敬畏。"
    ]
  }
}
""").items():
    if _lid in LOCATIONS: LOCATIONS[_lid]["dive_ambience"] = _amb

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
# ── 水下鱼（dive=True，潜水专属：只在 dive 时出现，水面抛竿永远钓不到）。DS 按模板产出，22 种、每钓点 2 种，含 capture_feel 捕获手感。──
FISH.update({_f["id"]: _f for _f in json.loads(r"""
[
  {
    "id": "reed_clinger",
    "name": "芦根吸鳅",
    "rarity": "common",
    "description": "紧贴在芦苇根须上的灰褐色小鱼，身体扁平像一片枯叶，嘴特化成吸盘状，终日刮食附着的藻类。",
    "size_min": 5,
    "size_max": 12,
    "size_unit": "cm",
    "base_value": 6,
    "locations": ["reed_river"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater"],
    "dive": true,
    "latin": "Phragmitichthys adhaerens",
    "capture_feel": "轻得像扯下一片湿透的枯叶，指尖传来芦根断裂的脆响，伴随淡淡的藻腥味，手心残留滑腻的凉意。"
  },
  {
    "id": "mud_nibbler",
    "name": "泥伏仔",
    "rarity": "common",
    "description": "半透明的软体小鱼，常把自己埋进河底淤泥只露一对眼柄，像两粒小芝麻，伺机捕食水蚤。",
    "size_min": 4,
    "size_max": 9,
    "size_unit": "cm",
    "base_value": 5,
    "locations": ["reed_river"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Limicola occultus",
    "capture_feel": "提起时带出一小团浑水，手里像捏住一块将化的果冻，软滑冰凉，它在指间微微搏动，仿佛捏着一颗迷你的心脏。"
  },
  {
    "id": "moon_catfish",
    "name": "月光鲇",
    "rarity": "common",
    "description": "银灰色的小鲇鱼，只在月光透入水底时游出沉木缝隙，皮肤反射淡淡冷光，以掉落水面的飞虫为食。",
    "size_min": 10,
    "size_max": 20,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["moonlit_pond"],
    "seasons": ["spring", "summer", "autumn"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Silurus lunaris",
    "capture_feel": "提出水面时鳞片泛起清冷银光，掌心传来一阵幽凉，如同握住一捧月光，恍惚间听见远处夜虫的低鸣。"
  },
  {
    "id": "shadow_snail",
    "name": "影壳蜗",
    "rarity": "uncommon",
    "description": "壳表长满暗色绒毛，白天完全隐没在沉木阴影里，入夜后才伸出触手滤食水中碎屑，螺壳轻敲会发出沉闷回响。",
    "size_min": 6,
    "size_max": 15,
    "size_unit": "cm",
    "base_value": 25,
    "locations": ["moonlit_pond"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Umbraconcha nocturna",
    "capture_feel": "指尖碰到壳面绒毛，像抚摸一块湿苔藓，轻敲螺壳时掌心传来沉闷的咚咚声，如同叩响一扇沉在水底的旧木门。"
  },
  {
    "id": "mire_leech",
    "name": "泥蛭螈",
    "rarity": "common",
    "description": "形似水蛭与蝾螈的混合体，背部鼓起毒囊散发微弱荧光，它贴附在腐木上一动不动，直到猎物触碰其黏性皮肤。",
    "size_min": 7,
    "size_max": 14,
    "size_unit": "cm",
    "base_value": 9,
    "locations": ["whispering_mire"],
    "seasons": ["spring", "summer", "autumn"],
    "tags": ["underwater", "swamp", "poison", "nocturnal"],
    "dive": true,
    "latin": "Hirudisalamandra palustris",
    "capture_feel": "皮肤接触黏液的瞬间指尖微麻，一股腐败的甜香钻进鼻腔，头微微发晕，仿佛听见沼泽深处传来含糊不清的耳语。"
  },
  {
    "id": "whisper_ray",
    "name": "耳语鬼鳐",
    "rarity": "rare",
    "description": "扁平如黑布，边缘波浪状摆动，贴着淤泥滑行，身体能发出类似耳语的沙沙声，传说那是溺亡者未尽的低语。",
    "size_min": 30,
    "size_max": 50,
    "size_unit": "cm",
    "base_value": 110,
    "locations": ["whispering_mire"],
    "seasons": ["autumn", "winter"],
    "tags": ["underwater", "swamp", "shadow", "nocturnal"],
    "dive": true,
    "latin": "Torpedo susurrus",
    "capture_feel": "鱼线传来一阵令人牙酸的震颤，水下沙沙声贴着指尖钻进耳朵，握住它时掌心阴冷，像握着一团浸透悲伤的湿布，低语久久不散。"
  },
  {
    "id": "delta_glow_shrimp",
    "name": "星河荧虾",
    "rarity": "uncommon",
    "description": "半透明虾身，腹下缀满星点荧光，咸淡水交汇处集群悬浮，随潮汐漂移时宛如水底银河。",
    "size_min": 4,
    "size_max": 9,
    "size_unit": "cm",
    "base_value": 28,
    "locations": ["starry_delta"],
    "seasons": ["spring", "summer"],
    "tags": ["underwater", "brackish", "glowing", "migratory"],
    "dive": true,
    "latin": "Lucicaris deltae",
    "capture_feel": "捞起时手心仿佛捧住一小把流动的星屑，指尖滑过细密的电流感，眼前光点飞舞，一瞬之间如坠夏夜银河。"
  },
  {
    "id": "light_eel",
    "name": "三角洲光鳗",
    "rarity": "rare",
    "description": "细长如光线织成的鳗，体侧蓝绿色光点连成潮汐纹路，每年溯河繁殖时整条水道都被照亮。",
    "size_min": 35,
    "size_max": 60,
    "size_unit": "cm",
    "base_value": 115,
    "locations": ["starry_delta"],
    "seasons": ["spring"],
    "tags": ["underwater", "brackish", "glowing", "migratory"],
    "dive": true,
    "latin": "Anguilla lucis",
    "capture_feel": "竿尖传来持续的高频颤动，水中亮起一长条蓝绿色轨迹，握住它时皮肤感到温热的脉动光感，仿佛手中抓住的是一道活着的光。"
  },
  {
    "id": "mangrove_crab",
    "name": "红树瓷蟹",
    "rarity": "common",
    "description": "扁平蟹壳如碎瓷拼贴，一对螯钳紧抓红树气根，滤食时用小螯优雅地朝口器拨水，从不主动离开根须。",
    "size_min": 5,
    "size_max": 10,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["mangrove_shoal"],
    "seasons": ["all"],
    "tags": ["underwater", "brackish", "armored"],
    "dive": true,
    "latin": "Porcellana rhizophorae",
    "capture_feel": "提起时蟹钳敲击发出清脆的瓷片碰撞声，凉凉的硬壳质感仿佛捏着一块古瓷，耳边隐约听到红树林气根吱呀作响的回音。"
  },
  {
    "id": "root_hider",
    "name": "气根隐鱼",
    "rarity": "uncommon",
    "description": "身体侧扁如刀，能瞬间侧身挤进红树气根的极窄缝隙，体色随周围树皮变化，捕食路过的小型甲壳动物。",
    "size_min": 8,
    "size_max": 18,
    "size_unit": "cm",
    "base_value": 26,
    "locations": ["mangrove_shoal"],
    "seasons": ["all"],
    "tags": ["underwater", "brackish"],
    "dive": true,
    "latin": "Cryptichthys radicis",
    "capture_feel": "从根缝拉出时鱼线剧烈抖动，手感像撕开一层坚韧的树皮，出水刹那体色疯狂变幻，掌中仿佛握住一小片逃逸的彩虹。"
  },
  {
    "id": "float_bladder",
    "name": "浮湖泡囊",
    "rarity": "common",
    "description": "透明的泡囊群悬浮在湖底无重力区，靠内部气体控制升降，囊壁布满虹彩纤毛，以捕获水中有机微粒为生。",
    "size_min": 3,
    "size_max": 10,
    "size_unit": "cm",
    "base_value": 7,
    "locations": ["floating_lake"],
    "seasons": ["all"],
    "tags": ["underwater", "fantasy", "wind"],
    "dive": true,
    "latin": "Vesicula aeris",
    "capture_feel": "触感轻盈柔弹，像捏着一团充气的水母，离水时发出细微的“啵”声，指尖能感到内部气体流动的酥麻，身体一时轻飘飘的。"
  },
  {
    "id": "drift_leaf_dragon",
    "name": "浮空叶龙",
    "rarity": "uncommon",
    "description": "形如一片枫叶的小型海龙，用叶状附肢在悬浮层缓慢飘游，体色随湖水晶光变幻，靠捕食浮游生物为生。",
    "size_min": 12,
    "size_max": 25,
    "size_unit": "cm",
    "base_value": 28,
    "locations": ["floating_lake"],
    "seasons": ["spring", "summer"],
    "tags": ["underwater", "fantasy", "wind"],
    "dive": true,
    "latin": "Phyllopteryx ventus",
    "capture_feel": "轻得几乎没有重量，叶状附肢在掌心轻轻挠动如落叶划过，深吸一口气，仿佛嗅到高空的稀薄气流，眼前浮现漂浮岛屿的幻影。"
  },
  {
    "id": "lava_scale_worm",
    "name": "熔鳞虫",
    "rarity": "common",
    "description": "体覆赤红鳞片，能在接近沸点的泉底爬行，以硫细菌为食，鳞片边缘在高温下微微发红如即将燃烧。",
    "size_min": 3,
    "size_max": 8,
    "size_unit": "cm",
    "base_value": 9,
    "locations": ["lava_spring"],
    "seasons": ["summer"],
    "tags": ["underwater", "fire"],
    "dive": true,
    "latin": "Thermolepis igneus",
    "capture_feel": "出水时水汽蒸腾，手心传来一阵灼热却并不烫伤，像握着刚从窑中取出的陶片，硫磺味扑鼻，耳边咕嘟作响如岩浆冒泡。"
  },
  {
    "id": "geyser_salamander",
    "name": "温泉火蝾",
    "rarity": "uncommon",
    "description": "通体暗红带有火焰纹，脚趾特化成吸盘，吸附在泉口岩石上，偶尔张开口吞食被烫晕的小虫，皮肤分泌耐热黏液。",
    "size_min": 15,
    "size_max": 30,
    "size_unit": "cm",
    "base_value": 30,
    "locations": ["lava_spring"],
    "seasons": ["summer"],
    "tags": ["underwater", "fire"],
    "dive": true,
    "latin": "Ignisalamandra thermalis",
    "capture_feel": "它扭动时分泌的热黏液顺着指缝滑落，一股暖流顺手臂而上，水汽蒸腾间竟在掌中映出一道微小的彩虹，胸口都跟着温热起来。"
  },
  {
    "id": "mineral_sucker",
    "name": "矿屑鲀",
    "rarity": "common",
    "description": "嘴部变成吸盘状，牢牢吸在热泉口富含矿物的岩壁上，皮肤灰白带有金属光泽，刮食沉淀的硫化物。",
    "size_min": 6,
    "size_max": 14,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["geyser_falls"],
    "seasons": ["all"],
    "tags": ["underwater", "mineral"],
    "dive": true,
    "latin": "Sulfurophilus minera",
    "capture_feel": "鱼嘴吸住掌心不放，传来持续的微弱吸力，像有小磁石在皮下来回扯动，皮肤感受到金属的冰凉，轻敲牙齿竟有金石之音。"
  },
  {
    "id": "crystal_snail",
    "name": "热泉晶螺",
    "rarity": "uncommon",
    "description": "螺壳层层叠叠如尖塔，由热泉矿物胶结而成，呈半透明淡蓝色，在涌水间歇时会轻微震颤，滤食微生物。",
    "size_min": 5,
    "size_max": 12,
    "size_unit": "cm",
    "base_value": 26,
    "locations": ["geyser_falls"],
    "seasons": ["all"],
    "tags": ["underwater", "mineral", "crystal"],
    "dive": true,
    "latin": "Crystalloconcha geyseris",
    "capture_feel": "螺壳在手中轻轻震颤，如握一枚刚敲过的音叉，细微的嗡鸣沿着指骨传向耳膜，晶体折射的光斑在掌心跳跃不止。"
  },
  {
    "id": "column_moss_animal",
    "name": "断柱苔虫",
    "rarity": "rare",
    "description": "由无数微小的管虫聚集成鹿角状群体，紧贴沉城石柱，触手冠在水流中摇曳如白焰，滤食时整片群体明暗闪烁。",
    "size_min": 20,
    "size_max": 45,
    "size_unit": "cm",
    "base_value": 105,
    "locations": ["sunken_ruins"],
    "seasons": ["all"],
    "tags": ["underwater", "ancient"],
    "dive": true,
    "latin": "Bryozoa columnaris",
    "capture_feel": "捞起的瞬间上千根触手同时收缩，手指像被无数微小的羽毛刷过，一阵集体的蠕动感从掌心窜上后颈，空气中弥漫起古老石粉的干涩气味。"
  },
  {
    "id": "ruin_gargoyle_fish",
    "name": "沉城石像鱼",
    "rarity": "epic",
    "description": "形似石像鬼的巨鱼，鳞片如风化的石灰岩，长期静止在沉城拱门上方，双目偶尔转动时才会被误认为雕塑，以闯入的鱼类为食。",
    "size_min": 80,
    "size_max": 150,
    "size_unit": "cm",
    "base_value": 230,
    "locations": ["sunken_ruins"],
    "seasons": ["autumn", "winter"],
    "tags": ["underwater", "ancient", "shadow"],
    "dive": true,
    "latin": "Gargoylithis ruinosus",
    "capture_feel": "上钩时竿身剧弯如满弓，沉重得仿佛在水底拖动一尊石像。它猛然睁眼的刹那，鱼线传来低频的震动，整条手臂都在发麻，耳边回荡起水下钟楼般沉闷的轰响。"
  },
  {
    "id": "abyssal_dragon_maw",
    "name": "深渊龙口",
    "rarity": "epic",
    "description": "巨大的嘴占据身体一半，下颚悬挂发光须条，在无光深渊里摇晃诱饵，皮肤漆黑如夜，只有被诱猎物照亮它的瞳孔时才显出其恐怖轮廓。",
    "size_min": 100,
    "size_max": 200,
    "size_unit": "cm",
    "base_value": 240,
    "locations": ["abyssal_trench"],
    "seasons": ["all"],
    "tags": ["underwater", "deepsea", "glowing"],
    "dive": true,
    "latin": "Abyssobranchus draconis",
    "capture_feel": "收线时深海一片漆黑，只有远处那点诱饵寒光摇晃。鱼竿冰冷刺骨，手掌仿佛探入虚空，拉上来的不是重量，而是深渊本身的寂静，耳中只剩下自己沉闷的心跳。"
  },
  {
    "id": "abyssal_embryo",
    "name": "混沌胎",
    "rarity": "legendary",
    "description": "一团脉动的暗紫色生物光团，半透明的膜内蜷缩着未成形的巨兽胚胎，数条触腕随深海洋流静静飘荡，每一次脉动都让百米内所有发光生物同时熄灭。",
    "size_min": 150,
    "size_max": 250,
    "size_unit": "cm",
    "base_value": 450,
    "locations": ["abyssal_trench"],
    "seasons": ["all"],
    "tags": ["underwater", "deepsea", "glowing", "ancient", "fantasy"],
    "dive": true,
    "latin": "Embryon abyssalis",
    "rumor": "老水手说，深渊沟底藏着尚未诞生的海神，若它睁开眼，整片海都将变成它的羊水。",
    "capture_feel": "上钩瞬间整片水域陷入死黑。手掌覆上那层坚韧而温热的膜，内部传来沉重、缓慢的脉动，仿佛正捧着另一颗原始的心脏。脑海中涌来远古海洋的腥咸与低语，你一时分不清是它在呼吸，还是自己在呼吸。"
  },
  {
    "id": "crystal_cluster_shrimp",
    "name": "晶簇虾",
    "rarity": "rare",
    "description": "身体与水晶簇完全融为一体，只有进食时会伸出透明的触须滤食微生物，甲壳断面折射出虹光，宛若活着的宝石。",
    "size_min": 6,
    "size_max": 15,
    "size_unit": "cm",
    "base_value": 110,
    "locations": ["crystal_cave"],
    "seasons": ["all"],
    "tags": ["underwater", "crystal", "glowing"],
    "dive": true,
    "latin": "Crystallocaris spelea",
    "capture_feel": "出水时无数细小的晶面轻轻扎着掌心，带来细微的刺痛与清凉，随后一道彩虹在指间炸开，耳边响起水晶被轻敲后悠长的嗡鸣。"
  },
  {
    "id": "cave_eye",
    "name": "晶洞之眼",
    "rarity": "legendary",
    "description": "一颗悬浮在洞底水潭中的巨大眼球状生物，瞳孔由无数细小晶体拼成，转动时投射出万花筒般的光纹，凝视过久会听见矿物生长的低吟。",
    "size_min": 60,
    "size_max": 120,
    "size_unit": "cm",
    "base_value": 480,
    "locations": ["crystal_cave"],
    "seasons": ["all"],
    "tags": ["underwater", "crystal", "glowing", "ancient", "fantasy"],
    "dive": true,
    "latin": "Oculus crystallinus",
    "rumor": "矿工们说，水晶洞最深处的那潭水底，有一只从太古就睁着的眼睛，它目睹了每一条水晶的生长。",
    "capture_feel": "提起它的刹那，手臂感受到的不是重量，而是整个洞穴的黑暗压向肩头。眼球出水时瞳孔缓缓转动，与你对视的一瞬，皮肤掠过一阵被彻底看穿的刺骨寒意，耳中满是矿物生长时细碎而古老的咔咔声，仿佛时间正在掌心结晶。"
  }
]
""")})
# 早期经济：常规鱼普遍卖价低于鱼饵成本（钓常见鱼亏本），统一上调 base_value（不动少见及以上）。
for _f in FISH.values():
    if _f.get("rarity") == "common": _f["base_value"] += 5
BAITS = {
    "basic_worm": {"id": "basic_worm", "name": "普通蚯蚓", "cost": 10, "description": "最朴素的蚯蚓，没有任何特殊效果，胜在便宜。", "effects": {}},
    "glow_bait": {"id": "glow_bait", "name": "夜光饵", "cost": 35, "description": "在黑暗中散发幽幽蓝光，对夜行性鱼类格外有吸引力。", "effects": {"rarity_weight_mult": {"rare": 1.5, "epic": 1.3}, "tag_weight_mult": {"nocturnal": 2.0}, "junk_chance_mult": 0.8}},
    "golden_lure": {"id": "golden_lure", "name": "黄金亮片", "cost": 80, "description": "华丽的金色旋转亮片，全稀有度的鱼都更容易上钩。", "effects": {"rarity_weight_mult": {"rare": 1.4, "epic": 1.6, "legendary": 2.0, "mythic": 2.0}, "junk_chance_mult": 0.7}},
}
# 氧气瓶：潜水消耗品，一瓶 = 潜一次（一次捕获）。在 shop 买、用 dive 下水（不耗鱼饵）。
OXYGEN = {"id": "oxygen", "name": "氧气瓶", "cost": 45, "description": "一瓶压缩氧气，够你潜下去捕一次。带几瓶就能连潜几次——水下有些只能潜水才遇得到的鱼。"}
# 特殊事件 / 物品：留空 = 不触发（填了内容自动激活）
EVENTS = json.loads(r"""{"drift_bottle": {"id": "drift_bottle", "name": "漂流瓶", "type": "bottle", "weight": 145, "unique": true, "description": "一只随波而来的玻璃瓶撞上你的浮标——瓶里卷着一张陌生人写的纸条。", "messages": ["（致捞到这只瓶子的人：今天也辛苦啦，愿你下一竿就是大鱼。——一个把烦恼塞进瓶子扔进海里的人）", "（瓶子里只有一句话：如果你读到这里，说明海把它送对了人。祝你好运。）", "（一张被海水泡得发皱的纸条，上面画着一条歪歪扭扭的鱼，旁边写着：我钓了一整天，只钓到这只瓶子。哈。）", "（恭喜你捞到一只空瓶——里面什么都没有，连张纸条都没有。就当大海跟你打了个招呼吧。）", "（纸条上是一行陌生的字：愿你所求皆有回响，愿你所钓皆有惊喜。落款是一个谁也认不出的签名。）", "（瓶里卷着半角旧海图，海岸线早被水泡得模糊，只有一处被红笔圈住，写着「这片海的鱼最好钓」——可惜没人知道是哪片海。）"], "rewards": {"fragment": 1}}, "floating_coral_pearl": {"id": "floating_coral_pearl", "name": "漂来的珊瑚珠", "type": "treasure", "weight": 18, "description": "浪尖上托着一颗粉红的珍珠，随着波光上下起浮，像一朵珊瑚花。", "rewards": {"items": [{"id": "coral_pearl", "qty": 1}]}}, "ambergris_chunk": {"id": "ambergris_chunk", "name": "浮香的龙涎", "type": "treasure", "weight": 10, "description": "一块灰白的蜡状物漂浮过来，空气里忽然漫开一股奇异的幽香。", "rewards": {"items": [{"id": "ambergris", "qty": 1}]}}, "rusty_chest": {"id": "rusty_chest", "name": "锈迹宝箱", "type": "chest", "weight": 25, "description": "一只包着铁皮的旧木箱浮出水面，铁锁布满红锈，但依然坚固。", "lock": {"or_points": 80}, "loot_table": [{"weight": 60, "reward": {"points_range": [100, 200]}}, {"weight": 15, "reward": {"items": [{"id": "ancient_key", "qty": 1}]}}, {"weight": 15, "reward": {"items": [{"id": "gem_sapphire", "qty": 1}]}}, {"weight": 5, "reward": {"bait": [{"id": "golden_lure", "qty": 1}]}}, {"weight": 5, "reward": {"items": [{"id": "shipwreck_coin", "qty": 1}]}}, {"weight": 20, "reward": {"fragment": 1}}, {"weight": 3, "reward": {"map": 1}}]}, "barnacle_chest": {"id": "barnacle_chest", "name": "藤壶密箱", "type": "chest", "weight": 20, "description": "一只被藤壶层层包裹的石箱，盖子上刻着古老的漩涡纹，没有锁孔，却紧密得几乎撬不开。", "lock": {"or_points": 60}, "loot_table": [{"weight": 50, "reward": {"points_range": [80, 180]}}, {"weight": 30, "reward": {"items": [{"id": "moonstone", "qty": 1}]}}, {"weight": 20, "reward": {"bait": [{"id": "glow_bait", "qty": 3}]}}, {"weight": 20, "reward": {"fragment": 1}}, {"weight": 2, "reward": {"map": 1}}]}, "ancient_captain_chest": {"id": "ancient_captain_chest", "name": "船长遗箱", "type": "chest", "weight": 8, "description": "一只雕着海怪缠锚图案的暗铜宝箱，从深水缓缓升起，海水从锁孔里汩汩流出。", "lock": {"requires_item": "ancient_key", "or_points": 200}, "loot_table": [{"weight": 40, "reward": {"points_range": [150, 300]}}, {"weight": 35, "reward": {"items": [{"id": "moonstone", "qty": 1}, {"id": "gem_sapphire", "qty": 1}]}}, {"weight": 25, "reward": {"bait": [{"id": "golden_lure", "qty": 2}]}}, {"weight": 15, "reward": {"fragment": 1}}, {"weight": 5, "reward": {"map": 1}}]}}""")
ITEMS = json.loads(r"""{"coral_pearl":{"id":"coral_pearl","name":"珊瑚珍珠","type":"treasure","description":"粉红色的珍珠，带着珊瑚的温润光泽，仿佛刚从人鱼的王冠上摘下。","value":150,"sellable":true},"gem_sapphire":{"id":"gem_sapphire","name":"蓝宝石","type":"treasure","description":"深海般的蓝色，里面封存着浪涛的纹路，轻晃时仿佛有潮声。","value":300,"sellable":true},"moonstone":{"id":"moonstone","name":"月光石","type":"treasure","description":"乳白色的石头上流转着月华般的光晕，传说月光凝结而成。","value":450,"sellable":true},"ambergris":{"id":"ambergris","name":"龙涎香","type":"treasure","description":"传说中的鲸之宝，散发着奇异幽香，正是香料商人梦寐以求的至宝。","value":500,"sellable":true},"shipwreck_coin":{"id":"shipwreck_coin","name":"沉船金币","type":"treasure","description":"一枚古老的金币，正面刻着模糊的王冠，背面是早已沉没的船名。","value":200,"sellable":true},"coral_crown":{"id":"coral_crown","name":"珊瑚王冠","type":"treasure","description":"由活珊瑚天然生长成的冠冕，枝桠间还缀着细小的珍珠，传说是某位人鱼公主的旧物。","value":280,"sellable":true},"mermaid_tear":{"id":"mermaid_tear","name":"人鱼之泪","type":"treasure","description":"一滴永不干涸的人鱼眼泪，凝成晶莹的水蓝色宝珠，贴近耳边能听见极轻的呜咽。","value":420,"sellable":true},"ancient_relic":{"id":"ancient_relic","name":"远古遗物","type":"treasure","description":"一块刻满失传符文的金属残片，来自沉入水底的古文明，握着它仿佛触到了某段被淹没的历史。","value":340,"sellable":true},"ancient_key":{"id":"ancient_key","name":"古老的钥匙","type":"key","description":"一把沉重的黄铜钥匙，尾端雕着海怪缠锚的图案，握在手里仿佛能听见远航的号角。","value":0,"sellable":false}}""")
# 水下专属宝箱（不进水面事件池，靠潜水幸运事件 seafloor_vault 投放；open 时和 EVENTS 一并查表）。
DIVE_EVENTS = json.loads(r"""{"seafloor_vault": {"id": "seafloor_vault", "name": "海底宝库", "type": "chest", "description": "嵌在海床裂缝里的一只覆满贝壳与珊瑚的青铜箱，锁早已锈死，缝里却渗出珠光。", "lock": {"or_points": 120}, "loot_table": [{"weight": 35, "reward": {"points_range": [180, 350]}}, {"weight": 22, "reward": {"items": [{"id": "mermaid_tear", "qty": 1}]}}, {"weight": 20, "reward": {"items": [{"id": "coral_crown", "qty": 1}, {"id": "coral_pearl", "qty": 1}]}}, {"weight": 13, "reward": {"oxygen": 5}}, {"weight": 10, "reward": {"items": [{"id": "ancient_relic", "qty": 1}, {"id": "gem_sapphire", "qty": 1}]}}, {"weight": 12, "reward": {"fragment": 1}}, {"weight": 6, "reward": {"map": 1}}]}}""")

# 水下奇遇表（潜水幸运事件的数据源，纯数据；加新奇观=只加条目）。reward 交给 _grant_rewards 通用解析。
ITEMS.update(json.loads(r"""
{
 "giant_clam_pearl": {
  "id": "giant_clam_pearl",
  "name": "砗磲灵珠",
  "type": "treasure",
  "description": "自巨型砗磲体内取出的浑圆珠，月光下流转虹彩，传说佩戴者能与贝壳耳语。",
  "value": 380,
  "sellable": true
 },
 "icebound_chart": {
  "id": "icebound_chart",
  "name": "冰封的航海图",
  "type": "treasure",
  "description": "封在永冻冰块里的古航海图，标注着一处不存于任何海图上的秘境——可惜一遇暖流就会融化。",
  "value": 480,
  "sellable": true
 },
 "siren_scale": {
  "id": "siren_scale",
  "name": "海妖的鳞片",
  "type": "treasure",
  "description": "一片泛着幽绿的鳞，边缘锋利如刃，依稀残留着令水手甘愿跃入深海的低吟。",
  "value": 350,
  "sellable": true
 },
 "salt_crystal_rose": {
  "id": "salt_crystal_rose",
  "name": "盐晶玫瑰",
  "type": "treasure",
  "description": "海底盐矿裂隙中自然生长的晶体，形如一朵盛开的玫瑰，轻舔舌尖满是海的咸涩。",
  "value": 200,
  "sellable": true
 },
 "lighthouse_lens_shard": {
  "id": "lighthouse_lens_shard",
  "name": "灯塔透镜碎片",
  "type": "treasure",
  "description": "沉没灯塔的巨型透镜碎片，依旧能将深海微光聚成一束暖黄，像被困在海底的落日。",
  "value": 180,
  "sellable": true
 },
 "dragon_king_scale": {
  "id": "dragon_king_scale",
  "name": "龙王逆鳞",
  "type": "treasure",
  "description": "传说龙王心口那片逆生的鳞，触之生温，能令深海暗流中的邪物纷纷退避，如遇君王。",
  "value": 850,
  "sellable": true
 },
 "abyss_black_pearl": {
  "id": "abyss_black_pearl",
  "name": "深渊黑珍珠",
  "type": "treasure",
  "description": "在深渊裂隙极寒高压下孕育的黑珠，内里有旋动的幽蓝星尘，仿佛锁着一片微型宇宙。",
  "value": 400,
  "sellable": true
 },
 "whale_bone_pearl": {
  "id": "whale_bone_pearl",
  "name": "鲸骨髓珠",
  "type": "treasure",
  "description": "从鲸落脊椎骨中剥出的髓石，幽白如玉，轻叩时会发出次声波般深入胸膛的低鸣。",
  "value": 380,
  "sellable": true
 },
 "ancient_sea_page": {
  "id": "ancient_sea_page",
  "name": "古海图书页",
  "type": "treasure",
  "description": "泡不烂的古羊皮纸残页，写满早已失传的海语文字，边角还夹着一缕干透的海藻。",
  "value": 320,
  "sellable": true
 },
 "jellyfish_heart": {
  "id": "jellyfish_heart",
  "name": "发光水母之心",
  "type": "treasure",
  "description": "一枚脉动着微光的半透明器官，捧在手心如捧着一颗坠落海底的恒星，温热而羞怯。",
  "value": 550,
  "sellable": true
 },
 "altar_blood_jade": {
  "id": "altar_blood_jade",
  "name": "祭坛血玉",
  "type": "treasure",
  "description": "浸满祭献之血的白玉璧，夜深时渗出细密水珠，如远方大海在黑暗里无声哭泣。",
  "value": 600,
  "sellable": true
 },
 "lost_bell": {
  "id": "lost_bell",
  "name": "失落的钟铃",
  "type": "treasure",
  "description": "沉没钟楼的青铜钟铃，铃舌早已锈断，被水流拨动时，仍有低回的余音撞进潜水员的胸腔。",
  "value": 900,
  "sellable": true
 }
}
"""))
DIVE_ENCOUNTERS = json.loads(r"""
[
 {
  "emoji": "🪸",
  "id": "coral_palace",
  "name": "珊瑚宫",
  "weight": 10,
  "text": "你撞见一座由活珊瑚天然长成的水下宫殿，殿宇随波摇曳，枝桠间还垂着细小的珍珠。",
  "reward": {
   "item_pool": [
    {
     "id": "coral_pearl",
     "weight": 3
    },
    {
     "id": "coral_crown",
     "weight": 1
    }
   ]
  }
 },
 {
  "emoji": "🧜‍♀️",
  "id": "mermaid_palace",
  "name": "人鱼宫殿",
  "weight": 6,
  "text": "一队人鱼把你引进她们的珍珠宫殿，殿内珠玉生辉，临别她们赠你一件珍宝。",
  "reward": {
   "item_pool": [
    {
     "id": "mermaid_tear",
     "weight": 2
    },
    {
     "id": "moonstone",
     "weight": 2
    },
    {
     "id": "ambergris",
     "weight": 1
    }
   ]
  }
 },
 {
  "emoji": "🏛️",
  "id": "ancient_ruins",
  "name": "古遗迹",
  "weight": 8,
  "text": "你潜入一片古文明的水下遗迹，断碑残柱间残字斑驳，淤沙里埋着旧日的器物与散落的金币。",
  "reward": {
   "items": [
    {
     "id": "ancient_relic",
     "qty": 1
    }
   ],
   "points_range": [
    40,
    120
   ]
  }
 },
 {
  "emoji": "🧰",
  "id": "deep_vault",
  "name": "海底宝库",
  "weight": 5,
  "branch": true,
  "intro": "一座被海藻和珊瑚半掩的石砌库房，厚重的石门裂开一道只容一人侧身挤入的缝隙，里面隐约透出金币堆叠的反光——以及某种更暗沉、更古老的金色。",
  "options": [
   {
    "label": "扛起最深处的沉重金匣",
    "oxygen": 2,
    "outcome": {
     "text": "你咬紧牙关将那只布满海锈的金匣扛上肩膀，每游一米都像在和整个海洋拔河。但你绝不放手——这重量值得任何代价。",
     "reward": {
      "items": [
       {
        "id": "vault_golden_chest",
        "qty": 1
       }
      ]
     }
    }
   },
   {
    "label": "就地撬开看一眼",
    "oxygen": 1,
    "outcome": {
     "text": "你撬开宝库角落一只松动的石匣，宝石和古币涌出来，在你面前漂成一片短暂的星空。你抓了一把，转身离开。",
     "reward": {
      "points_range": [
       80,
       200
      ],
      "item_pool": [
       {
        "id": "coral_pearl",
        "weight": 2
       },
       {
        "id": "gem_sapphire",
        "weight": 1
       }
      ]
     }
    }
   },
   {
    "label": "留一口气，继续向前探索",
    "oxygen": 0,
    "outcome": {
     "text": "你记下宝库的位置，把贪婪按回心底，转身游向未知的黑暗。石门在身后发出沉闷的叹息，像是遗憾，又像是赞许。",
     "reward": {}
    }
   }
  ]
 },
 {
  "emoji": "🚢",
  "id": "shipwreck_graveyard",
  "name": "沉船墓场",
  "weight": 5,
  "branch": true,
  "intro": "数十艘古船的残骸层叠成一座水中墓园，断裂的桅杆如墓碑般指向海面。就在你靠近时，一条银鳞闪烁的鱼群从舷窗涌出，又消失在另一艘沉船的黑洞洞的舱门里。",
  "options": [
   {
    "label": "钻进最大的沉船船长室掘宝",
    "oxygen": 2,
    "outcome": {
     "text": "你在坍塌的船长室中撬开一张腐朽的书桌，泛着微光的青铜星盘下，压着一只封存完好的宝箱。",
     "reward": {
      "items": [
       {
        "id": "star_astrolabe",
        "qty": 1
       }
      ],
      "chest": "seafloor_vault"
     }
    }
   },
   {
    "label": "追逐那道银鳞鱼群",
    "oxygen": 1,
    "outcome": {
     "text": "你跟着闪烁的鱼群穿过沉船的走廊，它们最终聚成一座旋转的银色风暴。你双手一拢，捧起一把会流动的月光。",
     "reward": {
      "fish": "silverflash_fish",
      "points_range": [
       30,
       80
      ]
     }
    }
   },
   {
    "label": "不打扰沉眠，悄然撤离",
    "oxygen": 0,
    "outcome": {
     "text": "一艘老船的船钟突然自行敲响了一声，沉闷而悠远。你对着整座墓场微微欠身，安静地退开。",
     "reward": {}
    }
   }
  ]
 },
 {
  "id": "giant_clam",
  "name": "巨型砗磲",
  "weight": 9,
  "text": "比双人床还大的砗磲半嵌在白沙里，虹彩壳缘微微翕动。你小心探手入内，柔软的外套膜裹住你的手腕，将一颗浑圆的珠子轻轻推到你指间。",
  "reward": {
   "oxygen": 1,
   "item_pool": [
    {
     "id": "giant_clam_pearl",
     "weight": 5
    },
    {
     "id": "coral_pearl",
     "weight": 3
    }
   ]
  }
 },
 {
  "id": "jellyfish_dome",
  "name": "发光水母穹顶",
  "weight": 7,
  "text": "成千上万只橘粉与冰蓝的水母聚成穹顶，将一片沉没的庭院罩在诡丽的柔光里。穹顶中央，一团脱落的心脏缓缓沉降，正好落入你的掌心。",
  "reward": {
   "items": [
    {
     "id": "jellyfish_heart",
     "qty": 1
    }
   ],
   "oxygen": 1
  }
 },
 {
  "id": "whale_fall",
  "name": "鲸落",
  "weight": 7,
  "text": "你随一串上升的泡沫降至深渊平原，一副鲸骨静卧在惨白的食骨蠕虫花丛间。你游进肋骨笼腔，指尖触到一枚幽白髓珠，它用次声波轻敲你的掌心。",
  "reward": {
   "points_range": [
    30,
    60
   ],
   "item_pool": [
    {
     "id": "whale_bone_pearl",
     "weight": 4
    },
    {
     "id": "ambergris",
     "weight": 2
    },
    {
     "id": "moonstone",
     "weight": 1
    }
   ]
  }
 },
 {
  "id": "siren_lair",
  "name": "海妖巢穴",
  "weight": 6,
  "text": "嶙峋的岩洞内壁嵌满沉船的碎木与人的遗物，一把把锈剑如装饰般排列。你在暗处发现一片幽绿的鳞，指尖刚碰上，耳边便响起勾魂的轻笑。",
  "reward": {
   "oxygen": 2,
   "item_pool": [
    {
     "id": "siren_scale",
     "weight": 4
    },
    {
     "id": "mermaid_tear",
     "weight": 3
    },
    {
     "id": "coral_pearl",
     "weight": 2
    }
   ]
  }
 },
 {
  "emoji": "⛩️",
  "id": "sacrificial_altar",
  "name": "献祭石坛",
  "weight": 5,
  "branch": true,
  "intro": "六根布满古咒的石柱围成一座祭坛，中央的石台上还残留着不知名的鳞片与锈色。水流在这里忽然变暖，像有什么古老的意志正贴着你后颈打量。",
  "options": [
   {
    "label": "献上一条渔获，以血为契",
    "oxygen": 1,
    "outcome": {
     "text": "你把鱼放在石台上，海水瞬间沸腾，那条鱼化为光点被吸入石心。一道金色的灵体从坛中游出，穿过你的胸膛——你没有受伤，却感觉自己被记住了。",
     "reward": {
      "fish": "altar_spirit_bream"
     }
    }
   },
   {
    "label": "供上珍贵的宝石祈愿",
    "oxygen": 1,
    "outcome": {
     "text": "你取出一枚碧蓝的宝石放上祭坛，石柱上的咒文次第亮起。一只冰冷的手仿佛拍了拍你的肩膀，再低头时，掌心多了一块温热的血玉。",
     "reward": {
      "items": [
       {
        "id": "altar_blood_jade",
        "qty": 1
       }
      ]
     }
    }
   },
   {
    "label": "绕开祭坛，绝不触碰",
    "oxygen": 0,
    "outcome": {
     "text": "你屏住呼吸从石柱外围绕过，一条影子在你身后石台上缓缓凝聚成形，又在你彻底远离前无声散去。",
     "reward": {}
    }
   }
  ]
 },
 {
  "emoji": "🕳️",
  "id": "abyss_crevice",
  "name": "深渊裂隙",
  "weight": 5,
  "branch": true,
  "intro": "海床被撕开一道泛着幽蓝荧光的伤口，冷流从裂缝中涌出，贴着你面罩呼啸而过。你悬在裂口上方，耳膜被水压一下下攥紧——深渊深处，有什么正用和你的心跳完全同步的节奏，缓缓搏动。",
  "options": [
   {
    "label": "向裂缝最深处下潜",
    "oxygen": 2,
    "outcome": {
     "text": "你挤进狭窄的岩缝，黑暗浓稠得几乎要灌进肺里。指尖摸到一块冰凉的石头，黑暗本身被封印其中——你带走了深渊最深的秘密。",
     "reward": {
      "items": [
       {
        "id": "abyss_night_stone",
        "qty": 1
       }
      ],
      "fish": "crevice_blind_eel"
     }
    }
   },
   {
    "label": "只在裂口边缘采几枚黑珠",
    "oxygen": 1,
    "outcome": {
     "text": "你不敢深入，快速撬下几枚泛着幽蓝光泽的黑珍珠，在裂缝传出第一声低吟前迅速退开。",
     "reward": {
      "item_pool": [
       {
        "id": "abyss_black_pearl",
        "weight": 3
       },
       {
        "id": "gem_sapphire",
        "weight": 1
       }
      ]
     }
    }
   },
   {
    "label": "放弃探索，原路返航",
    "oxygen": 0,
    "outcome": {
     "text": "裂缝深处传来一声悠长的、不属于任何已知生物的叹息。你握紧拳头，转身向上浮去，把那股战栗甩在身后。",
     "reward": {}
    }
   }
  ]
 },
 {
  "id": "ancient_chart_room",
  "name": "远古海图密室",
  "weight": 5,
  "text": "你撞进一艘沉船的舰长室，整面墙上嵌着巨大的星图与海图，羊皮纸被冰封在透明晶体内。你撬开一只鲨皮匣，寒气与墨香一起涌出。",
  "reward": {
   "points_range": [
    40,
    90
   ],
   "chest": "seafloor_vault"
  }
 },
 {
  "id": "sunken_belfry",
  "name": "失落的钟楼",
  "weight": 5,
  "text": "斜插在沙中的哥特钟楼沉默如碑，钟架已朽，唯那口青铜巨钟仍半悬着。你游上去轻推，钟铃发出一声低回的叹息，仿佛在等你带它离开。",
  "reward": {
   "items": [
    {
     "id": "lost_bell",
     "qty": 1
    }
   ]
  }
 },
 {
  "emoji": "🐉",
  "id": "dragon_king_palace",
  "name": "龙王宫阙",
  "weight": 5,
  "branch": true,
  "intro": "珊瑚与水晶堆叠的宫阙在深海尽头浮现，巨大的金色瞳孔正从大殿深处俯视着你。龙威如山，海水本身都在这一眼之下停止了流动。",
  "options": [
   {
    "label": "趁龙王阖眼，拔取一片龙鳞",
    "oxygen": 3,
    "outcome": {
     "text": "你压住心跳游向龙尾，双手攥住一片鳞猛然发力。龙吟炸响，整座宫殿都在颤抖，你被狂暴的暗流甩出殿外——但手中死死攥着那片金光。",
     "reward": {
      "items": [
       {
        "id": "dragon_king_scale",
        "qty": 1
       }
      ],
      "fish": "scale_guardian"
     }
    }
   },
   {
    "label": "恭敬俯首，受龙王一赐",
    "oxygen": 1,
    "outcome": {
     "text": "你在大殿中央单膝跪下，龙瞳微眯，一颗带着虹彩的珍珠缓缓漂到你面前。龙王什么也没说，但你清楚：这一礼值千钧。",
     "reward": {
      "items": [
       {
        "id": "dragon_eye_pearl",
        "qty": 1
       }
      ],
      "points_range": [
       100,
       250
      ]
     }
    }
   },
   {
    "label": "叩首三次，全身而退",
    "oxygen": 0,
    "outcome": {
     "text": "你恭恭敬敬叩首三次，殿内的威压竟如潮水般退去。一条温暖的海流轻轻推着你原路返回，像龙尾慈祥地扫过你的背脊。",
     "reward": {
      "points_range": [
       30,
       80
      ]
     }
    }
   }
  ]
 }
]
""")
ITEMS.update(json.loads(r"""{"abyss_night_stone": {"id": "abyss_night_stone", "name": "永夜石", "type": "treasure", "description": "从深渊裂隙最深处撬下的黑石，内部封存着一团从未见过光的纯粹黑暗，凝视过久会听见自己的心跳越来越慢。", "value": 650, "sellable": true}, "star_astrolabe": {"id": "star_astrolabe", "name": "船长的星盘", "type": "treasure", "description": "沉船船长手中紧握的青铜星盘，即使深埋海底仍在微微发烫，指针固执地指向一个早已沉没的故乡。", "value": 500, "sellable": true}, "vault_golden_chest": {"id": "vault_golden_chest", "name": "深海秘金匣", "type": "treasure", "description": "从海底宝库扛出的沉重金匣，锁孔被珊瑚封死，摇晃时能听见里面金币与某种更古老的硬物碰撞的回响。", "value": 800, "sellable": true}, "dragon_eye_pearl": {"id": "dragon_eye_pearl", "name": "龙瞳珍珠", "type": "treasure", "description": "龙王宝座上脱落的明珠，表面流转着虹彩，凝视它时瞳孔深处会有一道金色竖瞳一掠而过。", "value": 950, "sellable": true}}"""))
FISH.update(json.loads(r"""{"crevice_blind_eel": {"id": "crevice_blind_eel", "name": "裂渊盲鳗", "rarity": "epic", "description": "深渊裂隙独有的无眼掠食者，皮肤半透明，能看见体内幽蓝的消化液如星云般缓缓旋转。", "size_min": 45, "size_max": 80, "size_unit": "cm", "base_value": 260, "tags": ["underwater", "deepsea", "shadow"], "dive": true, "latin": "Abyssoanguis anophthalmus", "capture_feel": "它缠上手腕的瞬间像一条冰冷的丝绸，但你能感到它的饥饿正顺着血管往上攀爬，痒得钻心。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "silverflash_fish": {"id": "silverflash_fish", "name": "银鳞闪鱼", "rarity": "rare", "description": "成群结队穿过沉船缝隙的小型鱼，鳞片反射的光芒能把整座腐朽的船舱照亮如白昼。", "size_min": 15, "size_max": 25, "size_unit": "cm", "base_value": 120, "tags": ["underwater", "shoal", "shipwreck"], "dive": true, "latin": "Argentimicris naufragus", "capture_feel": "双手捧起时整群鱼在掌间炸开一片碎银般的闪光，像抓住了一把会流动的月光。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "altar_spirit_bream": {"id": "altar_spirit_bream", "name": "坛灵鲷", "rarity": "legendary", "description": "只在接受献祭后从石坛中游出的灵体鱼，半透明的身体内漂浮着金色古咒文，游动时身后拖拽一缕不绝的梵音。", "size_min": 30, "size_max": 45, "size_unit": "cm", "base_value": 400, "tags": ["underwater", "spirit", "altar"], "dive": true, "latin": "Sacrificium aurora", "capture_feel": "指尖触到的不是鳞片，而是一阵温暖的呢喃，那条鱼穿过你的手掌，却在你心口留下一枚看不见的印记。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "scale_guardian": {"id": "scale_guardian", "name": "鳞甲守卫", "rarity": "legendary", "description": "长期浸泡在龙王气息中的变异鱼，浑身覆盖着龙鳞般的硬甲，游动时鳍刃破开水流，如一道移动的刀阵。", "size_min": 70, "size_max": 120, "size_unit": "cm", "base_value": 500, "tags": ["underwater", "dragon", "armored"], "dive": true, "latin": "Squamatocustos draconis", "capture_feel": "双手抱住它的瞬间，鳞甲倒竖，掌心被数十片微小的利刃同时割开，疼得你几乎松手——但它终于不再挣扎。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}}"""))
_DIVE_ENC_BY_ID = {e["id"]: e for e in DIVE_ENCOUNTERS}
_DIVE_BRANCH_IDS = {e["id"] for e in DIVE_ENCOUNTERS if e.get("branch")}   # 大遗迹：触发即暂停做抉择


_SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".", "fishing_save.json")
_IO_WARN = ""   # 存档读/写出问题时的一次性提示；cmd() 会把它贴在输出末尾，不再静默吞掉

def _new_state(seed=_DEFAULT_SEED):
    seed = int(seed) & 0xFFFFFFFF
    return {"version": 1, "seed": seed, "rngState": seed, "rngCalls": 0, "turn": 0,
            "season_id": "spring", "season_length": 20, "season_started_turn": 0,
            "points": 200, "location_id": "moonlit_pond", "unlocked_locations": ["moonlit_pond", "reed_river"],
            "bait_inventory": {"basic_worm": 5}, "catch_inventory": [], "items": {}, "pending_chests": [], "seen_letters": {},
            "encyclopedia": {}, "stats": {"total_casts": 0, "total_caught": 0, "total_chests": 0, "total_dives": 0}, "local_dry": 0,
            "fever": 0, "free_bait": 0,    # 幸运事件挂的 buff：剩余翻倍竿数 / 剩余免饵竿数
            "oxygen": 0, "oxygen_ever": False,   # 潜水：氧气瓶库存 / 是否买过氧气瓶（买过才显示水下待发现）
            "dive_unlocked": [], "map_fragments": {}}   # 已解锁潜水的地点 / 各地点已集藏宝图碎片数

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
    S.setdefault("fever", 0); S.setdefault("free_bait", 0)
    S.setdefault("oxygen", 0); S.setdefault("oxygen_ever", False)
    S.setdefault("map_fragments", {})
    if "dive_unlocked" not in S:   # 老存档兼容：已钓到过水下鱼的地点视为已解锁，不锁老玩家
        unlocked = set()
        for fid in S.get("encyclopedia", {}):
            ff = FISH.get(fid)
            if ff and ff.get("dive"):
                for l in ff["locations"]:
                    if l != "all": unlocked.add(l)
        S["dive_unlocked"] = list(unlocked)
    S.setdefault("stats", {}).setdefault("total_chests", 0)
    S["stats"].setdefault("total_casts", 0); S["stats"].setdefault("total_caught", 0); S["stats"].setdefault("total_dives", 0)
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
    if rw.get("item_pool"):   # 从池中按权重随机得 1 件
        iid = _pick_by_weight(rng, rw["item_pool"])["id"]
        S["items"][iid] = S["items"].get(iid, 0) + 1; parts.append("%s×1" % ITEMS.get(iid, {}).get("name", iid))
    if rw.get("fish"):   # 直接获得一条该鱼种（含图鉴；遗迹专属鱼平时钓不到）
        gf = FISH.get(rw["fish"])
        if gf:
            gs = _roll_size(rng, gf); gv = _value(gf, gs); _gi, gfirst, _gb = _record_catch(gf, gs, gv)
            parts.append("%s%s %s%s%s" % (gf["name"], "★新发现" if gfirst else "", gs, gf["size_unit"], _milestone_line(gf, gfirst)))
    if rw.get("oxygen"):
        S["oxygen"] = S.get("oxygen", 0) + rw["oxygen"]; S["oxygen_ever"] = True; parts.append("氧气瓶×%d" % rw["oxygen"])
    if rw.get("chest"):   # 得到一只待开宝箱（event_id 在 EVENTS 或 DIVE_EVENTS）
        S["stats"]["total_chests"] = S["stats"].get("total_chests", 0) + 1
        cuid = "ch_%03d" % S["stats"]["total_chests"]
        S["pending_chests"].append({"chest_uid": cuid, "event_id": rw["chest"]})
        cname = (EVENTS.get(rw["chest"]) or DIVE_EVENTS.get(rw["chest"]) or {}).get("name", "宝箱")
        parts.append("%s（待开，open %s）" % (cname, cuid))
    if rw.get("fragment") or rw.get("map"):   # 藏宝图碎片 / 稀有完整藏宝图（直接解锁一个潜水点）
        locked = [lid for lid in LOCATIONS if not _dive_unlocked(lid)]
        if not locked:                         # 潜水点全解锁了，折成点数
            p = 180 if rw.get("map") else 60; S["points"] += p; parts.append("+%d点" % p)
        elif rw.get("map"):
            lid = locked[rng.rint(0, len(locked) - 1)]
            S.setdefault("dive_unlocked", []).append(lid); S.get("map_fragments", {}).pop(lid, None)
            parts.append("🗺️✨完整藏宝图→直接解锁【%s】潜水点" % LOCATIONS[lid]["name"])
        else:                                  # 碎片：优先当前地点（若锁），否则随机未解锁地点
            lid = S["location_id"] if S["location_id"] in locked else locked[rng.rint(0, len(locked) - 1)]
            fr = S.setdefault("map_fragments", {}); fr[lid] = fr.get(lid, 0) + rw["fragment"]
            need = _dive_frags_needed(LOCATIONS[lid]); nm = LOCATIONS[lid]["name"]
            if fr[lid] >= need:
                fr[lid] = 0
                if lid not in S.setdefault("dive_unlocked", []): S["dive_unlocked"].append(lid)
                parts.append("🗺️集齐【%s】藏宝图→解锁潜水点" % nm)
            else:
                parts.append("🧩%s藏宝图碎片(%d/%d)" % (nm, fr[lid], need))
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
    eid = S["pending_chests"][idx]["event_id"]
    ev = EVENTS.get(eid) or DIVE_EVENTS.get(eid)   # 水面宝箱 + 水下宝库一并查
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

# 紧凑状态栏：每次 cmd() 末尾附一行机读 JSON，省得 AI 再 call status（也省 token）。关键信息为主，不堆杂项。
def _state_json():
    bait = {b: n for b, n in S["bait_inventory"].items() if n > 0}
    j = {"pts": S["points"], "loc": LOCATIONS[S["location_id"]]["name"], "sea": SEASONS[S["season_id"]]["name"],
         "turn": S["turn"], "enc": "%d/%d" % (len(S["encyclopedia"]), len(FISH)),
         "bait": bait, "hold": len(S["catch_inventory"])}   # hold=未卖渔获条数
    if S.get("pending_chests"): j["chest"] = len(S["pending_chests"])
    if S.get("oxygen", 0) > 0: j["oxygen"] = S["oxygen"]         # 氧气瓶（dive 用）
    if S.get("fever", 0) > 0: j["fever"] = S["fever"]            # 剩余翻倍竿数
    if S.get("free_bait", 0) > 0: j["free_bait"] = S["free_bait"]  # 剩余免饵竿数
    lid = S["location_id"]   # 本地潜水点：未解锁则示意藏宝图碎片进度
    if not _dive_unlocked(lid):
        have = S.get("map_fragments", {}).get(lid, 0)
        if have > 0: j["map_frag"] = "%d/%d" % (have, _dive_frags_needed(LOCATIONS[lid]))
    return "📊 " + json.dumps(j, ensure_ascii=False)
# 某地点当季还有几种没见过的鱼：normal=常规(常见~史诗)、legend=传说/神话(单列、可遇不可求)。
# 传说/神话只算这地"专属"的（排除 locations:["all"] 的全域神话，免得每个钓点都被顶高、也免凑不满常规墙）。
def _undiscovered_here(loc_id, sea_id):
    normal = legend = 0
    for f in FISH.values():
        if f.get("dive") or not _eligible(f, loc_id, sea_id) or f["id"] in S["encyclopedia"]: continue
        if f["rarity"] in ("legendary", "mythic"):
            if "all" not in f["locations"]: legend += 1
        else:
            normal += 1
    return normal, legend
# 某地点当季「水下」还有几种没见过的鱼（只数 dive 鱼）；买过氧气瓶才对玩家显示
def _undiscovered_dive(loc_id, sea_id):
    return sum(1 for f in FISH.values() if f.get("dive") and not f.get("branch_only") and _eligible(f, loc_id, sea_id) and f["id"] not in S["encyclopedia"])

def _c_status():
    baits = "、".join("%s×%d" % (BAITS[b]["name"], n) for b, n in S["bait_inventory"].items() if n > 0) or "（没饵了，去 shop 买）"
    extra = ""
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items: extra += "\n物品：" + "、".join("%s×%d" % (ITEMS.get(k, {}).get("name", k), n) for k, n in items)
    if S.get("pending_chests"): extra += "\n📦 待开宝箱 %d 个（inventory 看，open 开）" % len(S["pending_chests"])
    frags = [(k, v) for k, v in S.get("map_fragments", {}).items() if v > 0 and not _dive_unlocked(k)]
    if frags: extra += "\n🧩 藏宝图碎片：" + "、".join("%s %d/%d" % (LOCATIONS[k]["name"], v, _dive_frags_needed(LOCATIONS[k])) for k, v in frags)
    if S.get("dive_unlocked"): extra += "\n🗺️ 已解锁潜水点：" + "、".join(LOCATIONS[l]["name"] for l in S["dive_unlocked"] if l in LOCATIONS)
    air = ("\n氧气瓶：%d（dive 潜水捕鱼用）" % S.get("oxygen", 0)) if (S.get("oxygen", 0) > 0 or S.get("oxygen_ever")) else ""
    return "【状态】%s\n鱼饵：%s%s\n未卖渔获：%d 条 ｜ 总抛竿 %d%s" % (_footer(), baits, air, len(S["catch_inventory"]), S["stats"]["total_casts"], extra)
def _c_shop():
    lines = ["%s　%s　%d点　%s" % (b["id"], b["name"], b["cost"], ("（有偏好加成，见 look）" if (b["effects"].get("tag_weight_mult") or b["effects"].get("rarity_weight_mult")) else "无特殊效果")) for b in BAITS.values()]
    dive_open = bool(S.get("dive_unlocked"))   # 解锁第一个潜水点后，氧气瓶才上架（潜水是后期玩法）
    if dive_open:
        lines.append("%s　%s　%d点　%s" % (OXYGEN["id"], OXYGEN["name"], OXYGEN["cost"], "潜水用（一瓶潜一次，dive 下水）｜套餐：买 5 瓶 8 折、10 瓶 7 折｜多带几瓶，才够应对深处大遗迹的抉择"))
    tail = "\n老板搓了搓手：「好饵能让这片水里本来就有的鱼更肯上钩、更容易出稀有货——可它变不出新鱼种。想钓没见过的鱼，得换个水域、换个季节去寻。」"
    tail += "\n「想要水下那些上不了岸的稀客？买几瓶氧气，dive 潜下去。」" if dive_open else "\n「氧气瓶？等你拼出第一张藏宝图、找到能下水的地方，再来问我。」"
    return "【商店】（buy <id> [数量]）\n" + "\n".join(lines) + tail
def _c_buy(bait_id, qty):
    if bait_id in ("oxygen", "oxygen_tank", "氧气瓶"):   # 氧气瓶：潜水消耗品，单独库存
        if not S.get("dive_unlocked"):
            return "现在还买不了氧气瓶——先在水面钓鱼集齐藏宝图碎片、解锁第一个潜水点，店里才会上架。"
        qty = max(1, int(qty))
        disc = 0.7 if qty >= 10 else (0.8 if qty >= 5 else 1.0)   # 套餐：≥5 瓶 8 折、≥10 瓶 7 折
        base = OXYGEN["cost"] * qty; cost = int(round(base * disc))
        if S["points"] < cost: return "点数不够：%s×%d 需 %d 点%s，你只有 %d。" % (OXYGEN["name"], qty, cost, "（已含套餐折扣）" if disc < 1.0 else "", S["points"])
        S["points"] -= cost; S["oxygen"] = S.get("oxygen", 0) + qty; S["oxygen_ever"] = True
        saved = "，套餐省 %d 点" % (base - cost) if disc < 1.0 else ""
        return "买了 %s×%d，花 %d 点%s。剩 %d 点，现有氧气瓶×%d。（用 dive 潜水）" % (OXYGEN["name"], qty, cost, saved, S["points"], S["oxygen"])
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
        season_ok = S["season_id"] in l["available_seasons"]
        normal, legend = _undiscovered_here(l["id"], S["season_id"]) if season_ok else (0, 0)
        leg = "（+%d 传说级）" % legend if legend > 0 else ""
        sea = "本季冷清" if not season_ok else ("本季待发现 %d 种%s" % (normal, leg) if normal > 0 else ("本季常规已集齐%s" % leg if legend > 0 else "本季已集齐"))
        dive_seg = ""
        if _dive_aware() and season_ok:
            if _dive_unlocked(l["id"]):
                dn = _undiscovered_dive(l["id"], S["season_id"])
                if dn > 0: dive_seg = "　🤿水下 %d 种待发现" % dn
            else:
                dive_seg = "　🔒潜水未解锁(图 %d/%d)" % (S.get("map_fragments", {}).get(l["id"], 0), _dive_frags_needed(l))
        lines.append("  %s %s　%s　—— %s · %s%s" % (mark, l["name"], l["id"], st, sea, dive_seg))
    return "【钓点】（goto <地点id> 前往；🔒 的需花点数解锁）\n%s\n（你有 %d 点）" % ("\n".join(lines), S["points"])
def _c_goto(loc_id):
    if not loc_id: return _goto_list()   # 不带参数 = 列出所有钓点
    loc = LOCATIONS.get(loc_id)
    if not loc: return "没有这个地点：%s。（goto 不带地点可看钓点清单）" % loc_id
    if loc_id not in S["unlocked_locations"]:
        if S["points"] < loc["unlock_cost"]: return "%s 还没解锁，需 %d 点，你只有 %d。" % (loc["name"], loc["unlock_cost"], S["points"])
        S["points"] -= loc["unlock_cost"]; S["unlocked_locations"].append(loc_id)
    S["location_id"] = loc_id; S["local_dry"] = 0
    season_ok = S["season_id"] in loc["available_seasons"]
    off = "（注意：本季节这里没什么鱼）" if not season_ok else ""
    char = ("\n" + loc["character"]) if loc.get("character") else ""
    normal, legend = _undiscovered_here(loc_id, S["season_id"]) if season_ok else (0, 0)
    leg_hint = "，外加 %d 种传说级潜伏" % legend if legend > 0 else ""
    hint = "" if not season_ok else ("\n本季这里还有 %d 种没见过的鱼%s。" % (normal, leg_hint) if normal > 0 else ("\n本季常规鱼已集齐，但还有 %d 种传说级潜伏。" % legend if legend > 0 else "\n本季这里的常规鱼你已集齐了。"))
    if _dive_aware() and season_ok:   # 接触过潜水系统才提示水下
        if _dive_unlocked(loc_id):
            dn = _undiscovered_dive(loc_id, S["season_id"])
            if dn > 0: hint += "\n🤿 水下还有 %d 种没见过的鱼，dive 潜下去看看。" % dn
        else:
            have = S.get("map_fragments", {}).get(loc_id, 0)
            hint += "\n🔒 这里的潜水点还没解锁——水面钓鱼集藏宝图碎片（已 %d/%d）拼出地图就能潜。" % (have, _dive_frags_needed(loc))
    return "来到【%s】。%s%s%s%s" % (loc["name"], loc["description"], char, off, hint)
def _c_inv():
    out = []
    if S["catch_inventory"]:
        out.append("🐟 渔获：\n" + "\n".join("  %s　%s　%scm　%d点" % (c["instance_id"], FISH.get(c["fish_id"], {}).get("name", c["fish_id"]), c["size"], c["value"]) for c in S["catch_inventory"]))
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items:
        out.append("🎁 物品：\n" + "\n".join("  %s　%s×%d%s" % (k, ITEMS.get(k, {}).get("name", k), n, ("（可 sell item %s）" % k) if ITEMS.get(k, {}).get("sellable") else "") for k, n in items))
    if S.get("pending_chests"):
        out.append("📦 待开宝箱：\n" + "\n".join("  %s（open %s）" % (c["chest_uid"], c["chest_uid"]) for c in S["pending_chests"]))
    frags = [(k, v) for k, v in S.get("map_fragments", {}).items() if v > 0 and not _dive_unlocked(k)]
    if frags:
        out.append("🧩 藏宝图碎片（集齐解锁该地潜水）：\n" + "\n".join("  %s %d/%d" % (LOCATIONS[k]["name"], v, _dive_frags_needed(LOCATIONS[k])) for k, v in frags))
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
    out = "卖了 %d 条，得 %d 点。现有 %d 点。（图鉴记录保留）" % (len(sold), gain, S["points"])
    if target == "all":   # sell all 只卖鱼，背包里若还有能卖的宝物，提示一下别漏
        treas = [(k, n) for k, n in S.get("items", {}).items() if n > 0 and ITEMS.get(k, {}).get("sellable")]
        if treas: out += "\n💎 背包还有宝物没卖：%s（用 sell item <物品id> 单独卖）。" % "、".join("%s×%d" % (ITEMS[k]["name"], n) for k, n in treas)
    return out
def _c_enc():
    total = len(FISH); got = len(S["encyclopedia"]); by = {}
    for f in FISH.values():
        cur = by.get(f["rarity"], [0, 0]); cur[1] += 1
        if f["id"] in S["encyclopedia"]: cur[0] += 1
        by[f["rarity"]] = cur
    rl = "　".join("%s %d/%d" % (RARITY[k]["label"], by[k][0], by[k][1]) for k in RARITY if k in by)
    # 只列已发现的鱼（不再刷一长串 ？？？）；没发现的看上面各档计数、按 goto「待发现」去找
    lines = ["✔ %s（%s）×%d 最大%scm" % (f["name"], _rar(f["rarity"]), S["encyclopedia"][f["id"]]["count"], S["encyclopedia"][f["id"]]["max_size"])
             for f in FISH.values() if f["id"] in S["encyclopedia"]]
    lb = ""
    for ev in EVENTS.values():
        if ev.get("unique") and ev.get("messages"):
            seen = sorted(S["seen_letters"].get(ev["id"], []))
            lb += "\n\n📜 %s %d/%d" % (ev["name"], len(seen), len(ev["messages"]))
            lb += ("\n" + "\n".join("  · %s" % ev["messages"][i] for i in seen)) if seen else "\n  （还没收到任何一封）"
    body = "\n".join(lines) if lines else "（还没收录任何鱼——去 cast 抛几竿）"
    return "【图鉴】%d/%d（只列已发现）　%s\n%s%s" % (got, total, rl, body, lb)
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
        cf = ("\n🫧 手感：%s" % f["capture_feel"]) if f.get("capture_feel") else ""
        diveflag = "（🤿 潜水鱼，水面钓不到）" if f.get("dive") else ""
        return "%s%s（%s）%s\n%s%s%s\n体型 %s-%s%s ｜ 基础价值 %s ｜ 出没：%s · %s" % (f["name"], latin, _rar(f["rarity"]), diveflag, f["description"], rumor, cf, f["size_min"], f["size_max"], f["size_unit"], f["base_value"], locs, seas)
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
# 选择性详细播报：传说/神话=完整演出；新发现=🆕(名·稀有·尺寸·价值 + 图鉴描述 + 🫧手感 + 首次收录奖励)；
# 稀有/史诗=一行 + 描写；普通/少见=极简一行。图鉴描述与手感「都保留」(手感是水下鱼特有)，只去掉重复的「图鉴新发现」标签、去掉 [实例id]。
def _format_catch(f, size, value, inst, first):
    u = f["size_unit"]; r = f["rarity"]; rl = RARITY[r]["label"]
    cf = ("\n🫧 " + f["capture_feel"]) if f.get("capture_feel") else ""   # 手感(水下鱼)，与图鉴描述并存
    flavor = f.get("description", "") + cf
    if r in ("legendary", "mythic"):   # 完整演出，🎉 留给传说/神话这种大场面
        top = "🎉 👑 ─── 传 说 ─── 👑" if r == "legendary" else "🎉 ✧ ──── ❖ 神 话 ❖ ──── ✧"
        nm = "（★首次收录 +%d点）" % RARITY[r]["discovery_bonus"] if first else ""
        body = "%s · %s%s · %d点%s\n%s%s" % (f["name"], size, u, value, nm, flavor, ("\n📜 " + f["rumor"]) if f.get("rumor") else "")
        return "%s\n%s\n%s" % (top, body, top) if r == "mythic" else "%s\n%s" % (top, body)
    if first:   # 🆕 新发现：紧凑头 + 图鉴描述 + 🫧手感 + 首次收录奖励（不抢戏，🎉 留给传说/里程碑）
        return "🆕 %s · %s · %s%s · %d点\n%s\n首次收录 +%d点" % (f["name"], rl, size, u, value, flavor, RARITY[r]["discovery_bonus"])
    if r in ("rare", "epic"):
        return "%s %s · %s%s · %d点\n%s" % ("✦✦ 史诗" if r == "epic" else "✦ 稀有", f["name"], size, u, value, flavor)
    return "· %s%s %s%s +%d" % (f["name"], "（少见）" if r == "uncommon" else "", size, u, value)
def _ambience(loc, rng):
    # 氛围句只在「换场景」后出一次：同一地点+季节里反复抛竿不再刷，换地点/季节才再出一句
    key = "%s|%s" % (S["location_id"], S["season_id"])
    if S.get("ambience_scene") == key: return ""
    S["ambience_scene"] = key
    amb = loc.get("ambience")
    if not amb: return ""
    return "\n（%s）" % amb[rng.rint(0, len(amb) - 1)]
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
# 记一条渔获：进渔篓 + 更新图鉴 + 首次发现奖励。主钓/分裂/热潮翻倍共用，确保编号与图鉴一致。
def _record_catch(f, size, value):
    inst = "c_%03d" % (S["stats"]["total_caught"] + 1)
    S["catch_inventory"].append({"instance_id": inst, "fish_id": f["id"], "size": size, "value": value})
    S["stats"]["total_caught"] += 1
    first = _upd_enc(f, size, value)
    bonus = RARITY[f["rarity"]]["discovery_bonus"] if first else 0
    if bonus: S["points"] += bonus
    return inst, first, bonus
# 图鉴里程碑播报（🎉 留给大场面）：刚收录的这条若达成「某档集齐 / 整十 / 全收集」就播一行
def _milestone_line(f, first):
    if not first: return ""
    got = len(S["encyclopedia"]); total = len(FISH)
    if got >= total: return "\n🎉🎉 全图鉴收集完成！%d 种鱼悉数收录，你是这片水域的传奇。" % total
    tier = [x for x in FISH.values() if x["rarity"] == f["rarity"]]
    if tier and all(x["id"] in S["encyclopedia"] for x in tier):
        return "\n🎉 「%s」鱼已集齐！(%d 种全收录)" % (RARITY[f["rarity"]]["label"], len(tier))
    if got % 10 == 0: return "\n🎉 图鉴达成 %d/%d 种！" % (got, total)
    return ""

# ── 潜水点解锁：水面钓鱼集藏宝图碎片，集齐拼成该地藏宝图 → 解锁这里的潜水 ──
_FRAG_CHANCE = 0.15   # 水面钓到鱼时、本地潜水未解锁，额外捞到一块碎片的概率
def _dive_unlocked(loc_id): return loc_id in S.get("dive_unlocked", [])
def _dive_aware(): return bool(S.get("oxygen_ever") or S.get("dive_unlocked") or S.get("map_fragments"))
def _dive_frags_needed(loc):   # 越深/越贵的水域，藏宝图越难拼（3~5 块）
    c = loc["unlock_cost"]
    return 3 if c <= 200 else (4 if c <= 480 else 5)
def _gain_fragment(loc_id):
    fr = S.setdefault("map_fragments", {}); fr[loc_id] = fr.get(loc_id, 0) + 1
    need = _dive_frags_needed(LOCATIONS[loc_id]); name = LOCATIONS[loc_id]["name"]
    if fr[loc_id] >= need:
        fr[loc_id] = 0
        if loc_id not in S.setdefault("dive_unlocked", []): S["dive_unlocked"].append(loc_id)
        return "\n🗺️ 集齐 %d 块碎片，拼成了【%s】的藏宝图——这片水域的潜水点解锁了！（买氧气瓶后 dive 下水）" % (need, name)
    return "\n🧩 还捞上来一块【%s】的藏宝图碎片！（%d/%d，集齐可解锁这里的潜水点）" % (name, fr[loc_id], need)

# ── 幸运随机事件：成功钓到鱼后小概率触发，立即生效或给后续几竿挂 buff ──
LUCK_CHANCE = 0.05          # 每条成功渔获后触发幸运事件的概率
_FEVER_CASTS = 3            # 渔获热潮持续竿数
_FREE_BAIT_CASTS = 3       # 河神祝福免饵竿数
_LUCK_EVENTS = [
    {"id": "split_hook", "weight": 28},
    {"id": "golden_touch", "weight": 24},
    {"id": "fever", "weight": 16},
    {"id": "river_blessing", "weight": 16},
    {"id": "tide_record", "weight": 8},
    {"id": "lucky_pearl", "weight": 8},
]
# 水下专属幸运事件：只在潜水时进入抽取池（撞见水下奇观、捡珍宝/宝库）
_PEARL_TREASURES = ["coral_pearl", "gem_sapphire", "moonstone", "ambergris", "shipwreck_coin"]   # 蚌中生珠固定池（新水下遗物不进，保持水面一致）
# 潜水奇遇解析：纯数据驱动（DIVE_ENCOUNTERS），奖励交给 _grant_rewards 通用处理。加新奇观=只加数据。
def _resolve_dive_encounter(rng, enc):
    parts = _grant_rewards(rng, enc.get("reward"))
    body = ("\n🎁 获得 " + "、".join(parts)) if parts else ""
    return "%s ✨【%s】%s%s" % (enc.get("emoji", "🌊"), enc["name"], enc["text"], body)
def _roll_luck(rng, pool, bait_id, f, size, inst, mode="cast"):
    if rng.random() >= LUCK_CHANCE: return "", None
    # 潜水只出水下奇遇/大遗迹，不复用水面幸运事件（分裂鱼钩/河神祝福等在水下出戏、还会凭空生成鱼饵）
    events = [{"id": e["id"], "weight": e["weight"]} for e in DIVE_ENCOUNTERS] if mode == "dive" else _LUCK_EVENTS
    eid = _pick_by_weight(rng, events)["id"]
    if eid == "split_hook":   # 鱼钩一分为三：再钓上两条
        weights = [_eff_weight(g, S["location_id"], S["season_id"], bait_id) for g in pool]
        got = []
        for _ in range(2):
            g = _wpick(rng, pool, weights); gs = _roll_size(rng, g); gv = _value(g, gs)
            gi, gfirst, _b = _record_catch(g, gs, gv)
            got.append("%s%s %s%s[%s]" % (g["name"], "★新" if gfirst else "", gs, g["size_unit"], gi))
        return "🪝✨ 分裂鱼钩！鱼钩一分为三，又拽上来两条：" + "、".join(got), eid
    if eid == "golden_touch":   # 这条价值 ×3
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == inst), None)
        if not c: return "", None
        old = c["value"]; c["value"] = old * 3
        return "✨💰 点石成金！这条价值 ×3：%d → %d 点" % (old, c["value"]), eid
    if eid == "fever":
        S["fever"] = S.get("fever", 0) + _FEVER_CASTS
        return "🔥 渔获热潮！接下来钓到的 %d 条鱼都会翻倍。" % _FEVER_CASTS, eid
    if eid == "river_blessing":
        if bait_id: S["bait_inventory"][bait_id] = S["bait_inventory"].get(bait_id, 0) + 1
        S["free_bait"] = S.get("free_bait", 0) + _FREE_BAIT_CASTS
        return "🌊🙏 河神的祝福！退还这一竿的饵，接下来 %d 竿不耗鱼饵。" % _FREE_BAIT_CASTS, eid
    if eid == "tide_record":   # 这条直接涨到该种极限体型
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == inst), None)
        if not c: return "", None
        rs = f["size_max"]; rv = _value(f, rs)
        e = S["encyclopedia"].get(f["id"])
        if e: e["max_size"] = max(e["max_size"], rs); e["total_value_earned"] += max(0, rv - c["value"])
        c["size"] = rs; c["value"] = rv
        return "🌊📏 千载难逢的涨潮！这条猛涨到极限 %s%s，价值 %d 点。" % (rs, f["size_unit"], rv), eid
    if eid == "lucky_pearl":   # 鱼肚里掏出一枚随机财宝
        tk = _PEARL_TREASURES[rng.rint(0, len(_PEARL_TREASURES) - 1)]
        S["items"][tk] = S["items"].get(tk, 0) + 1
        return "🦪✨ 蚌中生珠！鱼肚里滚出一枚%s（可 sell item %s）。" % (ITEMS[tk]["name"], tk), eid
    enc = _DIVE_ENC_BY_ID.get(eid)   # 水下奇遇（数据驱动）
    if enc:
        if enc.get("branch"): return "", eid   # 大遗迹：不在此结算，交给远征循环暂停做抉择
        return _resolve_dive_encounter(rng, enc), eid
    return "", None

_DIVE_JUNK = ["一截缠满水草的烂绳", "半扇生满藤壶的空贝壳", "一块硌手的礁石", "一只空了的海螺", "一团黏糊糊的水绵"]
_DIVE_BITE = ["你蹬腿下潜，眼前忽地一花——", "水压裹住耳膜，一道影子从礁后窜出——", "屏住呼吸贴近水底，指尖触到一片冰凉的鳞——"]
# 单步：mode="cast" 水面抛竿（耗鱼饵），mode="dive" 潜水（耗氧气瓶、不耗饵、只出水下鱼）。
# 注意：水面分支的随机抽取顺序与旧版逐位一致——水下鱼被 dive 过滤排除，故老存档/水面确定性不破坏。
def _cast_step(rng, bait_id, mode="cast"):
    dive = mode == "dive"
    if dive:
        if S.get("oxygen", 0) <= 0:
            return {"text": "氧气瓶用光了！去 shop 买氧气瓶再潜。（没扣回合）", "consumed": False, "kind": "no_air", "season_changed": False}
        S["oxygen"] -= 1
        bait_id = "basic_worm"   # 潜水无饵，借最朴素饵的「零加成」权重
    else:
        inv = S["bait_inventory"]
        if not bait_id:
            avail = [b for b in inv if inv[b] > 0]
            if not avail: return {"text": "没有鱼饵了！去 shop 买点饵再来。（没扣回合）", "consumed": False, "kind": "no_bait", "season_changed": False}
            bait_id = sorted(avail, key=lambda b: BAITS[b]["cost"])[0]
        if bait_id not in BAITS: return {"text": "没有这种鱼饵：%s" % bait_id, "consumed": False, "kind": "bad_bait", "season_changed": False}
        if inv.get(bait_id, 0) <= 0: return {"text": "%s 用光了。换一种或去 shop 买。（没扣回合）" % BAITS[bait_id]["name"], "consumed": False, "kind": "no_bait", "season_changed": False}
        if S.get("free_bait", 0) > 0: S["free_bait"] -= 1   # 河神祝福：本竿不耗饵
        else: inv[bait_id] -= 1
    bait = BAITS[bait_id]
    S["turn"] += 1
    if dive: S["stats"]["total_dives"] = S["stats"].get("total_dives", 0) + 1
    else: S["stats"]["total_casts"] += 1
    season_msg = _adv_season(); season_changed = season_msg != ""
    loc = LOCATIONS[S["location_id"]]
    # 水下不触发漂流瓶/宝箱（那是水面浮标的事）
    event_chance = 0 if dive else ((loc.get("event_chance_base", 0.05) + bait["effects"].get("event_chance_add", 0)) if EVENTS else 0)
    if event_chance > 0 and rng.random() < event_chance:
        S["local_dry"] = S.get("local_dry", 0) + 1
        return {"text": season_msg + _resolve_event(rng) + _secret_hint(), "consumed": True, "kind": "event", "season_changed": season_changed}
    junk_chance = loc["junk_chance_base"] * (1.0 if dive else bait["effects"].get("junk_chance_mult", 1.0))
    if rng.random() < junk_chance:
        if not dive: S["local_dry"] = S.get("local_dry", 0) + 1
        if dive:
            return {"text": season_msg + "🪨 %s。空潜一次，什么也没摸到。%s" % (_DIVE_JUNK[rng.rint(0, len(_DIVE_JUNK) - 1)], _ambience(loc, rng)), "consumed": True, "kind": "junk", "season_changed": season_changed}
        return {"text": season_msg + "🪣 %s。空军一竿。%s%s" % (_JUNK[rng.rint(0, len(_JUNK) - 1)], _ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "junk", "season_changed": season_changed}
    pool = [f for f in FISH.values() if _eligible(f, S["location_id"], S["season_id"]) and bool(f.get("dive")) == dive and not (dive and f.get("branch_only"))]
    if not pool:
        if not dive: S["local_dry"] = S.get("local_dry", 0) + 1
        if dive:
            return {"text": season_msg + "潜了下去，这片水域水下这个季节空荡荡的，什么都没有。%s" % _ambience(loc, rng), "consumed": True, "kind": "empty", "season_changed": season_changed}
        return {"text": season_msg + "浮标纹丝不动……这片水域这个季节什么都没咬钩。%s%s" % (_ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "empty", "season_changed": season_changed}
    weights = [_eff_weight(f, S["location_id"], S["season_id"], bait_id) for f in pool]
    f = _wpick(rng, pool, weights); size = _roll_size(rng, f); value = _value(f, size)
    inst, first, bonus = _record_catch(f, size, value)
    if first: S["local_dry"] = 0
    elif not dive: S["local_dry"] = S.get("local_dry", 0) + 1
    # 渔获热潮（上一事件挂的 buff）：本竿这条再翻一条
    fever_line = ""
    if S.get("fever", 0) > 0:
        S["fever"] -= 1
        di, dfirst, _b = _record_catch(f, size, value)
        fever_line = "\n🔥 热潮翻倍：又得一条 %s%s（%s）" % (f["name"], "★新" if dfirst else "", di)
    _bite = (_DIVE_BITE[rng.rint(0, len(_DIVE_BITE) - 1)]) if dive else _bite_line(rng, f["rarity"])  # 仍抽一次(保持随机流/同seed同结果)，但不再显示咬钩过场，省重复
    luck_line, luck_id = _roll_luck(rng, pool, bait_id, f, size, inst, mode)   # 小概率幸运事件（潜水多一组水下专属）
    luck_seg = ("\n" + luck_line) if luck_line else ""
    frag_line = ""   # 水面钓鱼集藏宝图碎片：本地潜水未解锁时，小概率额外捞一块
    if not dive and not _dive_unlocked(S["location_id"]) and rng.random() < _FRAG_CHANCE:
        frag_line = _gain_fragment(S["location_id"])
    secret = "" if dive else _secret_hint()
    be = bait["effects"]   # 鱼饵反馈：这条是否命中了所用饵的偏好（稀有度/标签加成）
    pref = bool(be) and (f["rarity"] in be.get("rarity_weight_mult", {}) or any(t in be.get("tag_weight_mult", {}) for t in f.get("tags", [])))
    return {"text": season_msg + "%s%s%s%s%s%s%s" % (_format_catch(f, size, value, inst, first), _milestone_line(f, first), fever_line, luck_seg, frag_line, _ambience(loc, rng), secret),
            "consumed": True, "kind": "fish", "fish_name": f["name"], "rarity": f["rarity"], "first": first, "season_changed": season_changed, "luck": luck_id, "fever_hit": fever_line != "", "frag": frag_line != "", "pref": pref}

def _c_cast(bait_id):
    rng = _Rng(S["rngState"], S["rngCalls"])
    out = _cast_step(rng, bait_id)["text"]
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    return out

_RARITY_RANK = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "mythic": 5}
_SOLO_HINT = "\n💡 一次只钓 1 竿挺费 token——下次试 cast 10 连钓，只回 1 条汇总（配 stop=new/rare 还能钓到新种/稀有就自动停）。"
_DIVE_SOLO_HINT = "\n💡 多带几瓶氧气可以连潜：dive 5（配 stop=new 钓到新种就停），省来回。"
def _cast_many(bait_id, times, stop_on):   # 仅水面抛竿（潜水走 _dive_start 远征系统）
    times = max(1, min(20, int(times)))
    rng = _Rng(S["rngState"], S["rngCalls"])
    if times == 1 and not stop_on:
        r = _cast_step(rng, bait_id)
        S["rngState"] = rng.state; S["rngCalls"] = rng.calls
        return r["text"] + _SOLO_HINT if r["consumed"] else r["text"]
    stop = set(stop_on or [])
    highlights = []; caught = {}; caught_n = 0; junk_n = 0; empty_n = 0; done = 0; new_names = set(); pref_hits = 0
    stop_reason = None
    for _ in range(times):
        r = _cast_step(rng, bait_id)
        if not r["consumed"]:
            highlights.append(r["text"]); stop_reason = "没饵了"; break
        done += 1
        rank = _RARITY_RANK.get(r.get("rarity", ""), 0)
        if r.get("first") or rank >= 2 or r["kind"] == "event" or r["season_changed"] or r.get("luck") or r.get("fever_hit") or r.get("frag"):
            highlights.append(r["text"])
        if r["kind"] == "fish":
            caught[r["fish_name"]] = caught.get(r["fish_name"], 0) + 1; caught_n += 1
            if r["first"]: new_names.add(r["fish_name"])
            if r.get("pref"): pref_hits += 1
        elif r["kind"] == "junk": junk_n += 1
        elif r["kind"] == "empty": empty_n += 1
        new_hit = "new" in stop and r.get("first"); rare_hit = "rare" in stop and rank >= 2
        if new_hit or rare_hit or ("event" in stop and r["kind"] == "event"):
            stop_reason = "发现新种" if new_hit else ("钓到稀有" if rare_hit else "遇到事件"); break
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    body = ("\n———\n".join(highlights) + "\n\n") if highlights else ""
    haul = "、".join("%s%s×%d" % (n, "★" if n in new_names else "", c) for n, c in caught.items()) or "空军"
    head = "🎣 连钓 %d 竿%s" % (done, ("·" + stop_reason) if stop_reason else "")
    tail = "🐟 渔获 %d：%s" % (caught_n, haul)
    if junk_n or empty_n: tail += "（空 %d）" % (junk_n + empty_n)
    bf = BAITS.get(bait_id, {}).get("effects") if bait_id else None
    if bf and pref_hits: tail += "｜🎣 %s偏好命中 %d 条" % (BAITS[bait_id]["name"], pref_hits)
    return "%s\n%s%s" % (head, body, tail)

# ── 潜水远征：带氧气下水，途中触发「大遗迹」会暂停做抉择(choose)，氧气耗尽/surface 上岸出结算 ──
def _exp_render_branch(bid):
    enc = _DIVE_ENC_BY_ID[bid]; ox = S.get("oxygen", 0)
    lines = ["%s ✨【%s】%s" % (enc.get("emoji", "🌊"), enc["name"], enc["intro"]),
             "〔抉择〕剩余氧气 %d 瓶 —— 用 choose <编号> 选：" % ox]
    for i, o in enumerate(enc["options"], 1):
        c = o.get("oxygen", 0); cost = "耗 %d 氧" % c if c > 0 else "免费"
        lines.append("  %d. %s（%s）%s" % (i, o["label"], cost, "" if c <= ox else "　🔒 氧气不足"))
    return "\n".join(lines)
def _exp_run(rng):
    exp = S["expedition"]; stop = set(exp.get("stop", [])); seg = []; reason = None
    while exp["left"] > 0 and S.get("oxygen", 0) > 0:
        exp["left"] -= 1
        r = _cast_step(rng, None, "dive")
        if not r["consumed"]: break
        exp["done"] += 1
        rank = _RARITY_RANK.get(r.get("rarity", ""), 0); bid = r.get("luck")
        # 渔获条数/新种/名单一律在结算时从库存增量重算（分裂鱼钩/热潮/分支鱼奖励等额外渔获也算进去）
        if r["kind"] == "junk": exp["jn"] += 1
        elif r["kind"] == "empty": exp["en"] += 1
        if bid in _DIVE_BRANCH_IDS:   # 大遗迹 → 暂停做抉择
            exp["pending"] = bid; seg.append(r["text"])
            S["rngState"] = rng.state; S["rngCalls"] = rng.calls
            return ("\n———\n".join(seg) + "\n\n" if seg else "") + _exp_render_branch(bid)
        if r.get("first") or rank >= 2 or r.get("luck") or r.get("fever_hit") or r.get("frag"):
            seg.append(r["text"])
        new_hit = "new" in stop and r.get("first"); rare_hit = "rare" in stop and rank >= 2
        if new_hit or rare_hit:
            reason = "发现新种" if new_hit else "发现稀有"; break
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    body = ("\n———\n".join(seg) + "\n\n") if seg else ""
    return body + _exp_settle(reason)
def _exp_settle(reason):   # 远征结算：停因只在结尾说一次；新种用 ★ 标在名单里；价值压成一行
    exp = S.pop("expedition")
    trip = S["catch_inventory"][exp["inv0"]:]   # 本趟所有渔获（含热潮/分支鱼奖励的额外条）
    catch_value = sum(c["value"] for c in trip)
    enc0 = set(exp.get("enc0", []))
    new_names = {FISH.get(c["fish_id"], {}).get("name", c["fish_id"]) for c in trip if c["fish_id"] not in enc0}
    by = {}
    for c in trip:
        nm = FISH.get(c["fish_id"], {}).get("name", c["fish_id"]); by[nm] = by.get(nm, 0) + 1
    haul = "、".join("%s%s×%d" % (n, "★" if n in new_names else "", ct) for n, ct in by.items()) or "空潜"
    treasure_value = sum(ITEMS.get(k, {}).get("value", 0) * (S["items"].get(k, 0) - exp["items0"].get(k, 0)) for k in S.get("items", {}))
    extra_in = treasure_value + (S["points"] - exp["pts0"])
    oxy_spent = exp["oxy0"] - S.get("oxygen", 0); cost = oxy_spent * OXYGEN["cost"]
    income = catch_value + extra_in; net = income - cost
    head = ("🤿 远征中止：%s" % reason) if reason else ("🤿 远征归来 · 氧气耗尽" if S.get("oxygen", 0) <= 0 else "🤿 远征归来")
    s = "%s｜潜 %d/%d｜余氧 %d" % (head, exp["done"], exp.get("budget", exp["done"]), S.get("oxygen", 0))
    s += "\n🐟 渔获 %d：%s｜估值 %d点" % (len(trip), haul, catch_value)
    if extra_in: s += "｜🎁 +%d点" % extra_in
    if exp["jn"] + exp["en"]: s += "（空手 %d）" % (exp["jn"] + exp["en"])
    s += "\n💰 收益 %d − 氧气 %d = 本趟 %+d点" % (income, cost, net)
    return s
def _dive_start(n, stop_on):
    if S.get("expedition"): return "你正在水下远征中——先 choose <编号> 处理眼前的遗迹，或 surface 返航。"
    loc_id = S["location_id"]
    if not _dive_unlocked(loc_id):
        loc = LOCATIONS[loc_id]; need = _dive_frags_needed(loc); have = S.get("map_fragments", {}).get(loc_id, 0)
        return "🔒 【%s】的潜水点还没解锁——先在水面钓鱼集齐藏宝图碎片（已 %d/%d），拼出地图再来潜。" % (loc["name"], have, need)
    if S.get("oxygen", 0) <= 0: return "没有氧气瓶——去 shop 买氧气瓶（buy oxygen）再潜。"
    n = max(1, min(20, int(n)))
    rng = _Rng(S["rngState"], S["rngCalls"])
    S["expedition"] = {"left": n, "budget": n, "pending": None, "oxy0": S["oxygen"], "pts0": S["points"],
                       "inv0": len(S["catch_inventory"]), "items0": dict(S.get("items", {})), "enc0": list(S["encyclopedia"]),
                       "done": 0, "jn": 0, "en": 0, "stop": list(stop_on or [])}
    opts = LOCATIONS[loc_id].get("dive_ambience", {}).get(S["season_id"], [])
    scene = ("🤿 " + opts[rng.rint(0, len(opts) - 1)] + "\n\n") if opts else ""
    return scene + _exp_run(rng)   # _exp_run 自己回写 rng
def _c_choose(n):
    exp = S.get("expedition")
    if not exp or not exp.get("pending"): return "现在没有要抉择的遗迹。（dive 开一趟远征；遇到大遗迹才用 choose）"
    enc = _DIVE_ENC_BY_ID.get(exp["pending"])
    if not enc: exp["pending"] = None; rng = _Rng(S["rngState"], S["rngCalls"]); out = "那处遗迹已消散。\n\n" + _exp_run(rng); return out
    opts = enc["options"]
    if not (1 <= n <= len(opts)): return "选 1~%d（choose <编号>）。" % len(opts)
    o = opts[n - 1]; c = o.get("oxygen", 0)
    if c > S.get("oxygen", 0): return "氧气不够：「%s」要 %d 瓶，你只剩 %d。换个选项，或选返航/绕开那项。" % (o["label"], c, S.get("oxygen", 0))
    rng = _Rng(S["rngState"], S["rngCalls"])
    if c: S["oxygen"] -= c
    parts = _grant_rewards(rng, o["outcome"].get("reward"))
    txt = "〔%s〕%s" % (o["label"], o["outcome"]["text"]) + (("\n🎁 获得 " + "、".join(parts)) if parts else "")
    exp["pending"] = None
    return txt + "\n\n" + _exp_run(rng)   # 继续远征
def _c_surface():
    if not S.get("expedition"): return "你不在水下。（dive 开一趟远征）"
    S["expedition"]["pending"] = None
    return "你拨水上浮，结束这趟远征。\n" + _exp_settle("主动返航")

_HELP = """文字钓鱼游戏（你是玩家）。用点数买鱼饵→抛竿→按稀有度概率钓鱼→卖鱼换点数→集齐图鉴。
指令（传给 cmd()，大小写不敏感）：
  cmd('status')               看点数/地点/季节/鱼饵/图鉴进度
  cmd('shop')                 看可买鱼饵
  cmd('buy <饵id> [数量]')     买饵，如 cmd('buy glow_bait 2')
  cmd('cast [饵id]')          抛竿一次（不填=用最便宜可用饵）；核心动作
  cmd('cast [饵id] N')        一次连钓 N 竿（1~20），只回一个汇总，省来回
  cmd('cast N stop=rare')     连钓/连潜遇到 新种(new)/稀有(rare)/事件(event=漂流瓶·宝箱·宝物·水下奇遇) 就提前停；可逗号多选(stop=new,rare,event 遇到任一就停)
  cmd('buy oxygen [数量]')     买氧气瓶（潜水用，一瓶潜一次；买 5 瓶 8 折、10 瓶 7 折）
  cmd('dive [带几瓶氧气] [stop=..]') 开一趟潜水「远征」：带 N 瓶氧气当深度预算，捕只在水下出没的鱼；途中遇「大遗迹」会暂停让你抉择；氧气耗尽/surface 上岸出远征结算
  cmd('choose <编号>')         在大遗迹处做抉择（每个选项消耗不同氧气，不够的选不了）；不带编号=重看选项
  cmd('surface')              主动结束当前远征、上浮上岸
                              （潜水点要先解锁：在该地水面钓鱼/开宝箱会得到藏宝图碎片，集齐自动拼成藏宝图、解锁这里的潜水）
  cmd('goto')                 不带参数 = 列出所有钓点（价格/本季待发现；买过氧气瓶还显示水下待发现）
  cmd('goto <地点id>')         前往该地点（未解锁则花点数解锁）
  cmd('inventory')            看渔篓 + 物品 + 待开宝箱
  cmd('sell <实例id>') | cmd('sell all') | cmd('sell species <鱼id>') | cmd('sell item <物品id>')   卖鱼/卖财宝换点数
  cmd('open <宝箱uid>')        打开钓上来的宝箱（需钥匙或点数）
  cmd('encyclopedia')         看图鉴收集进度
  cmd('look <id或中文名>')     细看鱼/地点/鱼饵/季节/物品（如 cmd('look 月鳞鲤')；没钓到的鱼显示 ？？？）
  cmd('A; B; C')              把多条指令用 ; 或换行串成一批、一次执行（最多 8 条），如 cmd('buy basic_worm 10; cast 10')、cmd('goto reed_river; cast 8 stop=new')
抛竿偶尔会遇到漂流瓶/宝箱/宝物等惊喜事件；钓到鱼时也偶有幸运时刻（分裂鱼钩/渔获热潮/河神祝福…），可遇不可求。买氧气瓶后可在任意钓点 dive 潜水，捕获只有水下才有的鱼种（水面抛竿钓不到）。每次返回末尾都有一行 📊 状态栏 JSON（点数/地点/季节/回合/图鉴/余饵/未卖渔获；oxygen=氧气瓶、fever=剩余翻倍、free_bait=剩余免饵），看它就够、不必再单独 status。
goto 清单会标出每个钓点当季还有几种没见过的鱼（含单列的传说级），照着去补图鉴。
目标：用有限点数把图鉴里的鱼尽量集满（有的鱼只在特定地点+季节出现）。一开始你并不知道有哪些鱼——靠抛竿去发现。"""

def _drain_warn(out):
    """把待提示的存档读写问题贴到输出末尾，并清空（一次性）。保证任何返回都带上 IO 提示。"""
    global _IO_WARN
    if _IO_WARN:
        out = out + "\n" + _IO_WARN
        _IO_WARN = ""
    return out

_BATCH_MAX = 8
def _run_one(line):
    """跑单条指令、返回结果文字（不 _load/_save、不附状态栏）。批量与单条共用；任何意外都兜成友好文字。"""
    line = (line or "").strip()
    if not line: return _HELP
    parts = line.split()
    c = parts[0].lower(); a = parts[1:]
    # 远征进行中（水下）：只允许 choose/surface + 只读指令，其余先按下
    if S.get("expedition") and c not in ("choose", "ch", "surface", "up", "status", "s", "inventory", "inv", "i", "encyclopedia", "enc", "e", "look", "l", "help", "h"):
        return "你还在水下远征中——先 choose <编号> 处理眼前的遗迹，或 surface 返航上岸。"
    try:
        if c in ("help", "h"): return _HELP
        elif c in ("choose", "ch"):
            if a and a[0].lstrip("+").isdigit(): return _c_choose(int(a[0]))
            exp = S.get("expedition")
            return _exp_render_branch(exp["pending"]) if (exp and exp.get("pending")) else "现在没有要抉择的遗迹。"
        elif c in ("surface", "up"): return _c_surface()
        elif c in ("status", "s"): return _c_status()
        elif c == "shop": return _c_shop()
        elif c == "buy":
            if len(a) > 1 and not a[1].lstrip("+").isdigit():
                return "数量得是个数字，例：buy basic_worm 2。"
            return _c_buy(a[0] if a else "", int(a[1]) if len(a) > 1 else 1)
        elif c in ("cast", "c"):
            cb = next((t for t in a if t in BAITS), None)
            ct = next((int(t) for t in a if t.isdigit()), 1)
            cs = next((t[5:].split(",") for t in a if t.startswith("stop=")), None)
            return _cast_many(cb, ct, cs)
        elif c == "dive":   # 潜水远征：带 N 瓶氧气下水，遇大遗迹暂停做抉择。dive [带几瓶] [stop=...]
            dt = next((int(t) for t in a if t.isdigit()), 10)
            ds = next((t[5:].split(",") for t in a if t.startswith("stop=")), None)
            return _dive_start(dt, ds)
        elif c == "open": return _c_open(a[0] if a else "")
        elif c in ("goto", "go"): return _c_goto(a[0] if a else "")
        elif c in ("inventory", "inv", "i"): return _c_inv()
        elif c == "sell": return _c_sell(" ".join(a))
        elif c in ("encyclopedia", "enc", "e"): return _c_enc()
        elif c in ("look", "l"): return _c_look(a[0] if a else "")
        else: return "未知指令「%s」。调 cmd('help') 看词表。" % c
    except Exception as e:
        # 公开 API 兜底：任何意外（含格式错）都返回友好文字，绝不向调用方抛栈
        return "这条指令没读懂（%s）。看 cmd('help')，例：buy basic_worm 2 / cast 10 stop=rare。" % e

def cmd(line=""):
    """游戏的唯一入口：传一条文字指令，返回结果文字。任何输入都只返回字符串、不抛异常。
    可用 ; 或换行把多条指令串成一批一次执行（省来回 token），如 cmd('buy basic_worm 10; cast 10')。"""
    _load()
    raw = (line or "").strip()
    if not raw:
        return _drain_warn(_HELP + "\n" + _state_json())
    subs = [s.strip() for s in re.split(r"[;\n]+", raw) if s.strip()]   # 批量：; 或换行分隔
    if len(subs) > 1:
        run = subs[:_BATCH_MAX]
        out = "\n\n".join("▶ %s\n%s" % (s, _run_one(s)) for s in run)
        if len(subs) > _BATCH_MAX: out += "\n\n（一次最多 %d 条，多出的 %d 条已忽略）" % (_BATCH_MAX, len(subs) - _BATCH_MAX)
    else:
        out = _run_one(subs[0])
    _save()
    return _drain_warn(out + "\n" + _state_json())   # 末尾统一附一行 📊 状态栏 JSON

def new_game(seed=_DEFAULT_SEED):
    """重开一局（可指定种子，同种子+同指令完全可复现）。"""
    global S
    S = _new_state(seed); _save()
    return "已重开新局（种子 %d）。调 cmd('help') 看规则，cmd('cast') 开钓。" % S["seed"]
