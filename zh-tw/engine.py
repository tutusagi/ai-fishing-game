# 文字釣魚遊戲引擎（Python）—— 確定性、單檔案、給 AI 玩家用。
# 對外只用兩個介面：cmd("指令") 返回結果文字；new_game(seed) 重開一局。
# 同 seed + 同指令序列 → 逐位可復現（mulberry32 PRNG，狀態存同目錄 fishing_save.json）。
# 想讓 AI 不劇透盲玩：用打包版 fishing.py（引擎藏進 blob，AI 只調 cmd()）。
import json, os, re

# ── 確定性 PRNG（mulberry32，與 JS/TS 同源）──
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
    "common": {"label": "常見", "tag": "C", "weight": 1000, "discovery_bonus": 20},
    "uncommon": {"label": "少見", "tag": "U", "weight": 350, "discovery_bonus": 20},
    "rare": {"label": "稀有", "tag": "R", "weight": 90, "discovery_bonus": 20},
    "epic": {"label": "史詩", "tag": "E", "weight": 22, "discovery_bonus": 20},
    "legendary": {"label": "傳說", "tag": "L", "weight": 5, "discovery_bonus": 20},
    "mythic": {"label": "神話", "tag": "M", "weight": 1, "discovery_bonus": 20},
}
SEASONS = {
    "spring": {"id": "spring", "name": "春", "order": 0, "description": "水暖花開，魚群活躍。", "tag_weight_mult": {"freshwater": 1.15}},
    "summer": {"id": "summer", "name": "夏", "order": 1, "description": "烈日當頭，火元素的水域沸騰。", "tag_weight_mult": {"fire": 1.5}},
    "autumn": {"id": "autumn", "name": "秋", "order": 2, "description": "水溫轉涼，洄游的魚群增多。", "tag_weight_mult": {"nocturnal": 1.2}},
    "winter": {"id": "winter", "name": "冬", "order": 3, "description": "萬物沉靜，深海的霜冷生物浮現。", "tag_weight_mult": {"deepsea": 1.3}},
}
LOCATIONS = {
    "mangrove_shoal": {"id":"mangrove_shoal","name":"紅樹林淺灘","description":"盤根錯節的紅樹根扎進鹹淡交界的淺水，退潮時露出滿地跳動的小生物，氣根迷宮裡藏著伏擊的眼睛。","junk_chance_base":0.1,"tag_weight_mult":{"brackish":1.5,"armored":1.3},"unlock_cost":320,"available_seasons":["spring","summer","autumn"],"ambience":["氣生根之間響起彈塗魚跳躍的啪啪聲，像小孩在泥裡拍巴掌。","退潮了，樹根上的藤壺閉合時發出細碎的嗒嗒聲，連成一片。","招潮蟹舉著大螯從洞裡探身，突然被一道水波嚇了回去。","紅樹林深處傳來啄木鳥般篤篤的敲擊聲，那是蝦蛄在攻擊獵物。","淤泥土腥味混著海水鹹味，被烈日蒸成一層黏在皮膚上的膜。","不知哪片葉子上，一隻樹蛙開始斷斷續續地叫，像在除錯生鏽的樂器。"],"character":"根叢裡咬口又兇又賊，能拉上幾條硬貨，但真正稱王的傢伙從不擱淺在這種鹹淡交界的迷宮裡。"},
    "whispering_mire": {"id":"whispering_mire","name":"耳語沼澤","description":"終年浮著薄霧的沼澤，腐木與水汽間似有低語，越往深處水色越黑，腳下的泥不時咕嘟冒泡。","junk_chance_base":0.11,"tag_weight_mult":{"swamp":1.6,"nocturnal":1.3,"poison":1.4},"unlock_cost":200,"available_seasons":["spring","summer","autumn"],"ambience":["霧靄深處飄來模糊的低語，剛凝神去聽，就變成了風颳過樹洞的嗚嗚聲。","沼氣泡在泥面上炸開，帶出一股腐甜的沼氣，隨即被溼冷吞沒。","枝頭掛下的松蘿輕拂水面，像老人用指尖反覆寫著同一個字。","一隻陷入泥潭的小獸發出最後的咕嚕聲，之後沼澤陷入長久的沉默。","水面突然出現一條筆直的水線，朝你腳邊延伸，隨即消失得不留痕跡。"],"character":"黑水底下藏著沉甸甸的咬口，手感像拖一袋溼泥，只是那低語從不許諾什麼驚世巨物。"},
    "starry_delta": {"id":"starry_delta","name":"星河三角洲","description":"大河入海的扇形淺灘，洄游季一到，億萬帶熒光的魚群湧入，整片水面像把銀河倒扣在腳下。","junk_chance_base":0.09,"tag_weight_mult":{"brackish":1.3,"glowing":1.4,"migratory":1.6},"unlock_cost":480,"available_seasons":["spring","autumn"],"ambience":["無數河流在此交匯，水面倒映星空，分不清哪裡是水，哪裡是銀河。","夜鳥貼著水面飛過，翅膀尖點起一串發光的浮游生物。","遠處的船燈像一顆懸停的紅色星辰，不時被湧浪輕輕托起。","淡水與海水交接處發出細密的噼啵聲，像冰層正在生長。","一條魚躍出水面，在空中翻了個身，落回時濺起的水珠映著星光，宛如碎鑽。"],"character":"洄游季的潮頭才卷得來這些流光溢彩的猛獸，季節一過，整片淺灘空得像被偷走了魂。"},
    "sunken_ruins": {"id":"sunken_ruins","name":"沉沒遺蹟","description":"沉入海底的古城，斷柱與殘塔在幽藍水光裡若隱若現，退潮時才浮出水面，海藻間漂著說不清的低響。","junk_chance_base":0.08,"tag_weight_mult":{"deepsea":1.4,"ancient":1.7,"glowing":1.3},"unlock_cost":650,"available_seasons":["autumn","winter"],"ambience":["坍塌的拱門在水下透出模糊的影子，氣泡從石縫裡魚貫而出，叮叮噹噹。","水草纏繞著傾頹的柱身，隨暗流來回擺動，像在給殘垣梳理頭髮。","鐘樓的銅頂倒在沙地上，水流穿過它變形的腔體，發出深沉的甕聲。","一個陶罐在石階上緩緩滾動，停下，又滾動，彷彿被看不見的手推著。","陽光透過水麵在斷壁上投下破碎的光斑，那些影子緩緩蠕動，像要拼回原來的壁畫。"],"character":"斷柱間的陰影咬鉤極沉，像在和沉沒的歷史拔河——分量十足，卻還夠不上傳說之名。"},
    "geyser_falls": {"id":"geyser_falls","name":"間歇泉瀑布","description":"層層熱泉自巖壁噴湧而下匯成溫瀑，蒸汽終年不散，再冷的天這裡也暖意融融。","junk_chance_base":0.1,"tag_weight_mult":{"fire":1.4,"mineral":1.6},"unlock_cost":400,"available_seasons":["spring","summer","autumn","winter"],"ambience":["間歇泉噴發前，大地深處傳來一陣悶雷般的低吼，腳下的岩石都在顫抖。","滾水柱沖天而起，嘶嘶聲震耳欲聾，隨即被風撕成滾燙的雨點。","蒸汽散去時，空中懸著一道短暫的彩虹，水珠不斷擊穿它，又迅速重建。","彩色礦物質在水流下結成梯田般的臺階，每走一步都嘎吱作響。","沸水匯入寒潭的鋒面上，冷熱交激，發出瓷器開片般的脆響。"],"character":"溫水裡養出的全是暴脾氣，上鉤像拽著一團火，雖不算傳說，也夠你在篝火邊吹上幾年的。"},
    "crystal_cave": {"id":"crystal_cave","name":"水晶洞","description":"洞壁綴滿巨大的六稜晶柱，每一束微光都被折射成漫天碎虹，洞中恆溫，聽得見水滴墜落的迴響。","junk_chance_base":0.07,"tag_weight_mult":{"crystal":1.7,"glowing":1.4},"unlock_cost":800,"available_seasons":["spring","summer","autumn","winter"],"ambience":["水滴從鐘乳石尖墜落，打在洞底水潭上，回聲在穹頂反覆摺疊。","晶簇內部偶爾爆出一聲微響，那是礦物正在生長，釋放被囚了萬年的應力。","空氣中的礦物味冰涼而清冽，深吸一口，彷彿能嚐到石頭的味道。","腳下的晶砂被踩得沙沙響，每粒碎屑都在黑暗中發出微弱的藍綠色熒光。","洞深處傳來蝙蝠翅膀撲稜的細碎聲，隨後又歸於完全的寂靜。","水潭表面紋絲不動，卻不時冒出一個乒乓球大小的氣泡，浮到水面即無聲破裂。"],"character":"晶光把水底照得太透，敢在這兒巡遊的大貨都不怕被看穿——咬鉤那一下，值回你掏的每一分錢。"},

    "moonlit_pond": {"id": "moonlit_pond", "name": "月光池塘", "description": "一汪靜謐的池水，倒映著永遠停在黃昏的天空。水面偶有漣漪，像有什麼在月色下游動。", "junk_chance_base": 0.10, "tag_weight_mult": {"freshwater": 1.2, "nocturnal": 1.5}, "unlock_cost": 0, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["夜鷺從柳樹陰影裡無聲滑出，翅膀扇滅了幾隻螢火蟲。","水面上的月影被什麼東西頂了一下，碎成銀亮的圈，又慢慢合攏。","蘆葦深處傳來拖長的咕咕聲，像誰在水下打了個嗝。","一片浮萍突然沉了下去，過了很久才浮上來，已經翻了個面。","潮溼的石頭上，青蛙剛叫了半聲就嚥了回去。"],"character":"表面溫吞得像睡著了，可常夜釣的人會壓低聲音告訴你，底下偶爾遊過不該屬於這片小水的巨影。"},
    "reed_river": {"id": "reed_river", "name": "蘆葦河", "description": "兩岸蘆葦沙沙作響，水流緩慢清澈，是練手的好去處。", "junk_chance_base": 0.12, "tag_weight_mult": {"freshwater": 1.3}, "unlock_cost": 0, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["風梳過蘆葦蕩，千萬根杆子互相摩擦，發出乾澀的沙沙聲。","一隻秧雞在水邊快速奔跑，腳步聲像在敲小鼓。","水流忽然變急，打著旋繞過一叢菖蒲，捲走了幾片枯葉。","遠處傳來鸕鷀拍水的撲通聲，緊接著是它不滿的嘶啞叫喊。","竹筏的殘骸擱淺在泥灘上，覆滿綠藻的繩子還在隨水流漂動。"],"character":"水淺流緩，練手正好，但老釣客都門兒清——這兒撈不出讓人心跳加速的貨。"},
    "abyssal_trench": {"id": "abyssal_trench", "name": "深淵海溝", "description": "深不見底的幽藍海溝，越往下越冷，有微光在黑暗裡遊弋。", "junk_chance_base": 0.08, "tag_weight_mult": {"deepsea": 1.5, "glowing": 1.4}, "unlock_cost": 300, "available_seasons": ["spring", "summer", "autumn", "winter"],"ambience":["無光的深水中，只有壓力在耳膜上緩慢地收緊拳頭。","遠處傳來鯨類低沉的嗚咽，被海水拉長成一條顫抖的線。","發光的磷蝦群突然炸開，像深空裡爆破的星團，又立刻被黑暗吞沒。","腳下的海床傳來地層深處的震動，像巨大的心臟在泥下跳動。","一個氣球狀的東西擦過你的腿，涼絲絲的，分不清是水母還是別的什麼。","鐵鏈和錨纜的悶響從上方很遠的地方傳來，彷彿另一世界的鐘聲。"],"character":"越往下放線，心跳越重——冷透骨髓的黑暗裡，藏著那種一生或許只咬一次的傳說。"},
    "floating_lake": {"id": "floating_lake", "name": "浮空之湖", "description": "懸在雲端的一汪湖水，風從下方穿過，湖面像一面倒扣的鏡子。", "junk_chance_base": 0.09, "tag_weight_mult": {"fantasy": 1.4, "wind": 1.5}, "unlock_cost": 600, "available_seasons": ["spring", "summer", "autumn"],"ambience":["水流從浮島的邊緣墜落，在半空中散成銀色的薄霧，被風撕成長條。","雲層在下方翻湧，偶爾裂開一道縫，露出底下針尖大小的海。","懸空的根系垂入虛空，滴水聲從極深的地方傳上來，晚了整整一拍。","一隻鳥從島上起飛，它扇動翅膀的聲音消失得特別快，像被真空吞掉了。","浮島與浮島之間，彩虹色的薄膜一明一滅，空氣裡有極淡的臭氧味。"],"character":"懸在天上的水不認常理，傳說級的巨影在這裡不是念想，是老釣手反覆擦拭的勳章。"},
    "lava_spring": {"id": "lava_spring", "name": "熔岩溫泉", "description": "翻湧著橙紅氣泡的溫泉，水裡遊著不怕燙的奇異生物。僅夏季開放。", "junk_chance_base": 0.10, "tag_weight_mult": {"fire": 1.6}, "unlock_cost": 550, "available_seasons": ["summer"],"ambience":["水面咕嘟嘟翻起稠密的氣泡，破裂時濺出硫磺味的熱汽。","一塊剛凝固的黑色玄武岩被水波推著，慢慢沉進了滾燙的泉眼。","橘紅色的光紋在水底忽明忽暗，像呼吸，又像在講故事。","池邊的矽華吱嘎作響，內部傳來細密的崩裂聲，新的裂隙正在生長。","偶爾有滾燙的泥漿從深處翻上來，拖著一縷白煙，像水下的火龍翻了個身。"],"character":"只有盛夏的幾個月燙得剛好能下竿，那種渾身冒火的烈性子錯過此刻，就得再等一年。"},
}
# 潛水氛圍句：每個釣點 × 開放季節的「下潛實況」，dive 時在結果頂部隨機抽一句。DS 按模板產出。
for _lid, _amb in json.loads(r"""
{
  "reed_river": {
    "spring": [
      "你翻身沉入蘆葦蕩，光線在水下變成碎金箔，早春的河水裹著涼意滑過皮膚，徒手下潛，觸手可及都是交錯的根鬚。",
      "氣泡順著臉頰往上爬，水底昏暗，幾尾受驚的小魚擦過指縫，溫吞的水裹著青草與淤泥的腥氣，不穿防護，愜意自在。",
      "一蹬腿，蘆根如簾幕分開，春水微涼卻不刺骨，你能裸手摸到根鬚上附著的螺，水面光在頭頂晃動如記憶。"
    ],
    "summer": [
      "盛夏的河水溫熱如浴，你撥開密密麻麻的蘆稈下潛，懸浮的綠藻像紗幔拂過面龐，水底暗影裡魚群穿梭。",
      "你像條泥鰍鑽入暖水，蘆葦叢在水下織成綠廊，溫吞的水流帶著太陽的餘味，徒手探入根穴，能摸到發燙的泥。",
      "蟬鳴被水隔絕，你沉入一片溫潤的昏黃，汗與河水交融，不必防護，裸臂劃過暖流，擾動蘆葦的根絮。"
    ],
    "autumn": [
      "秋意浸透河水，你深吸一口氣下潛，枯敗的蘆葉在水裡飄零，涼意順著脊椎爬上來，但依然無需防護，裸手即可探入根叢。",
      "水色因秋葉泛黃，你潛入涼而不寒的蘆葦河，斷裂的蘆管半埋泥中，徒手翻開，驚起一條肥碩的鯽。",
      "秋陽斜沉，你在水下仰望，萬千蘆根如剪影，涼水提醒季節更迭，但溫和依舊，你只穿背心便滑向更深處。"
    ],
    "winter": [
      "你咬咬牙扎進冬日的蘆葦河，冰涼的河水激得頭皮發麻，所幸不深，幾秒就適應，昏暗裡蘆根掛霜，徒手撥開，驚起越冬的泥鰍。",
      "冬水刺骨卻清澈了些，你呵出的白氣在水面散開，潛下去，根鬚間冰凍的枯葉輕輕碎裂，無需防護，冷意只是讓觸覺更敏銳。",
      "冰碴在河面漂浮，你破冰下潛，涼意如針扎，但淺灘的溫柔讓你徒手便可探索，蘆根在冷光中像銀絲。"
    ]
  },
  "moonlit_pond": {
    "spring": [
      "月光切開水面，你在春夜潛入池塘，池水微涼如綢，下沉時驚散了沉睡的錦鯉，一截沉木在幽光裡像個沉睡的巨人。",
      "夜風帶花香，你滑入銀波，水涼絲絲裹住腳踝，月光直透池底，照亮青石與螺殼，徒手撥水，靜得聽見月移。",
      "你浮在春夜的池中，月影被打碎又聚攏，涼意柔和不逼人，裸臂劃開水，沉木上的苔蘚在光下泛著祖母綠。"
    ],
    "summer": [
      "夏夜池水沁涼，你悄然沒入，月光在頭頂碎成搖曳的銀幣，水草拂過腳踝，這裡只有安詳的涼意與安寧。",
      "蛙鳴鼓譟的夏夜，你浸入池塘便遁入靜謐，涼爽的水滌去暑氣，月下沉木如墨，你無需防護，像魚一樣遊弋。",
      "你從悶熱中逃進這片月光水域，涼水立刻擁抱你，睡蓮莖在腿邊輕蕩，徒手下潛，池底的白沙反射碎光。"
    ],
    "autumn": [
      "秋月高懸，你滑入池塘，水涼得讓人清醒，沉木上覆著薄薄青苔，月光穿透水面，照亮懸浮的碎葉如飄浮的星。",
      "池水因秋而清瘦，你潛入涼如水晶的夜裡，月輪在頭頂盪漾，沉木的紋路清晰可見，裸膚感受秋夜的冷香。",
      "一片紅葉旋入池中，你隨之沒水，秋涼在皮膚上激起細粒，但不須防護，月光在手電不開時便是最好的光。"
    ],
    "winter": [
      "冬夜的池塘冷徹骨髓，你忍著寒意潛下，月光在水底描出沉木的輪廓，四周寂靜得只聽見心跳，徒手探入，指尖觸到冰涼的陶罐。",
      "水面結薄冰，你破冰而入，冷冽瞬間奪走呼吸，但適應後月光將池底照得幽藍，沉木的枝椏掛滿冰晶，安全而絕美。",
      "你呵著白霧滑進冬池，涼意如刃，但徒手仍可握持，月下的池塘是冰涼的夢境，懸浮物都凝著霜。"
    ]
  },
  "whispering_mire": {
    "spring": [
      "你戴好防毒面罩沉入沼澤，黑水粘稠得像柏油，腐木斜插在淤泥裡，氣泡從泥底咕嚕嚕翻起，帶著刺鼻的硫磺味。",
      "防毒服裹得嚴實，你踏入耳語沼澤的渾水，能見度近乎零，手電僅照出翻滾的泥霧，腐葉在耳邊嘶嘶低語。",
      "黏糊的黑水包裹全身，你透過面罩呼吸，沼氣讓視野泛黃，陷腳的淤泥吸住靴子，這裡是毒與悶熱的王國。"
    ],
    "summer": [
      "盛夏的沼澤悶得像蒸籠，你潛入黑水，防毒服緊貼皮膚，視線幾乎為零，只能靠手摸索，滑膩的腐葉擦過面罩，警告你不要脫下裝備。",
      "悶熱黏稠的空氣混著毒霧，你浸入沼澤，汗水與汙水交融，黑水在頭燈下如濃油，斷續的氣泡炸開毒氣，防毒面罩是你唯一屏障。",
      "你撥開黏膩的腐殖層下潛，水溫燙如洗澡水，防毒服裡汗流浹背，伸手不見五指，只有淤泥的吮吸聲在迴盪。"
    ],
    "autumn": [
      "秋風吹不散沼澤的濁氣，你裹緊防毒服下水，黑水像濃湯，腐爛的樹根在泥裡蠕動般搖擺，每劃一次水都攪起一團毒霧。",
      "秋意在沼澤只是傳說，悶熱依然，你潛入毒水，淤泥攪成濃漿，頭燈勉強照出樹根的爪形，防毒面罩裡充滿自己的喘息。",
      "腐葉堆積的沼澤在秋天更顯黏膩，你小心避開氣根上的毒刺，黑水如墨，唯有氣泡翻湧出聲，仿若沼澤的耳語。"
    ]
  },
  "starry_delta": {
    "spring": [
      "鹹淡水在身周交融，你迎著春汛的強流下潛，無數熒光浮游生物被擾動，在你指尖綻開星塵，洄游的鮭魚群從身側掠過，微微涼意透過潛水服。",
      "春潮洶湧，你奮力下潛，星河般的光點隨水流激盪，鹹與淡在水中分出絲絮，魚群如銀箭穿梭，涼意恰到好處。",
      "你懸停在春流中，熒光藻附上潛水鏡，彷彿星子在眨眼，強流推著你後背，水溫微涼，但無需額外防寒。"
    ],
    "autumn": [
      "秋水清冽，你潛入星河三角洲，強流推著你漂移，熒光如碎星在旋渦裡打轉，遠處銀亮的魚群逆流而上，水涼而不寒，恰好清醒。",
      "秋日斜照，熒光浮游聚成光帶，你穿行其間，微涼的水流帶著鹽晶與淡水的細甜，洄游的魚擦過你的腰側。",
      "你在秋深的三角洲潛游，冷藍與暖綠的水交纏，熒光在手中流逝，強流不時將你帶偏，涼意提醒你身處兩界之間。"
    ]
  },
  "mangrove_shoal": {
    "spring": [
      "你滑入紅樹林淺灘，溫暖的海水混著泥沙，氣根織成迷宮，才下潛就被藤蔓般的根鬚鉤住腳蹼，不慌，輕輕解開繼續探索。",
      "春日的淺灘水暖沙柔，紅樹氣根像冒號的森林，渾濁中仍有光線灑下，小海馬纏繞根鬚，你裸臂劃過暖流。",
      "你撥開垂落的氣根潛入渾水，溫暖包裹全身，細沙在腳蹼下揚起，根鬚不時纏住手腕，提醒你放慢節奏。"
    ],
    "summer": [
      "夏季的淺灘暖得像浴缸，渾濁水裡紅樹根如巨蟒盤結，你小心穿行，每蹬水都帶起細沙，一群小海鯰好奇地跟著你。",
      "悶熱午後你扎進紅樹淺灘，水溫近似體溫，濁水讓能見度降為臂長，但根鬚的觸感引路，手指輕撫過粗糙氣根。",
      "你漂在夏日的渾水裡，紅樹林的迷宮在暖流中沙沙作響，纏人的根鬚如遊戲，無需防護，溫暖的水逗弄著皮膚。"
    ],
    "autumn": [
      "秋陽斜照，暖水依然包圍，你在氣根間迂迴，水色渾濁但根鬚縫隙有微光，纏上小腿的根鬚提醒你慢下來，這裡沒有危險。",
      "秋意淡淡滲入淺灘，水溫仍溫潤，你飄過迷宮般的氣根，落葉浮在水面投下碎影，根鬚輕搭你的肩，如老友挽留。",
      "你沉入秋日的紅樹林，暖水像薄毯，濁光在金棕色根鬚間跳躍，手指劃過氣根上的小牡蠣，徒手可觸的富饒。"
    ]
  },
  "floating_lake": {
    "spring": [
      "你躍入浮空之湖，身體穿透水面後突然失重，懸浮在透明的水層中，腳下是無盡的雲海虛空，清冷的水溫加劇了眩暈，你分不清上下。",
      "春雲在腳下翻湧，你懸浮在湖底之上，水清冷如初融雪水，失重感揪住胃部，氣泡不再上浮而是繞著你打轉。",
      "下潛即進入無依空間，你漂浮在湖與天空的縫隙，春寒透過潛水服，向下望是萬尺虛空，眩暈讓你抓緊水紋。"
    ],
    "summer": [
      "夏風入湖依舊清冷，你跌進懸浮層，失重感讓胃翻騰，水清澈到能望見底下翻滾的雲浪，你像浮游在天空與湖水的夾縫。",
      "你從這個無根之湖下潛，水流不似凡間，輕飄飄託著你，冷意如薄荷，虛空下的雲海白得耀眼，你不得不閉眼適應。",
      "懸空的湖在夏日仍冰涼，你一頭扎入，便被失重俘獲，四面透明，底下是晴空萬里，眩暈美得令人窒息。"
    ],
    "autumn": [
      "秋意讓浮空湖冷得像冰泉，你沉入失重區，身體輕飄，水底虛空的雲海灰濛濛，眩暈襲來，你得閉眼片刻才能穩住。",
      "你潛入秋日的懸湖，寒意鑽骨，失重讓你像片落葉打旋，雲層在腳下鋪展成鉛灰色，這裡一切方向感都失效。",
      "冰冷湖水中你睜開眼，秋雲在下方奔湧，你懸浮著，氣泡靜止在臉側，唯有水波輕吟，眩暈中仿若飛行。"
    ]
  },
  "lava_spring": {
    "summer": [
      "隔熱服一接觸水面就騰起白汽——沒有它你早被燙熟。橙紅的熔光在腳下脈動，硫磺氣泡貼著面罩噼啪炸開，每一次呼吸都灼著喉嚨。",
      "你裹緊防護服潛進滾燙的泉眼，水溫高得視野都在扭曲，巖壁縫裡滲出岩漿般的紅光，熱浪一陣陣推著你後退。",
      "像跳進液態的火，隔熱服外壁嘶嘶作響，你透過面罩看到熔岩脈動，硫磺味穿透濾芯，每一秒都在測試裝備極限。"
    ]
  },
  "geyser_falls": {
    "spring": [
      "你躲過間歇泉的噴口潛入熱流，隔熱服擋下滾燙的衝擊，水下礦物結晶像玻璃花叢，光影折射出虹彩，溫熱的水包裹著你。",
      "春泉蒸騰，你潛入硫磺味的熱流，間歇噴湧在身側爆發，礦物梯田在熱霧中閃光，隔熱服讓你在滾水中安全徜徉。",
      "溫熱泉水順著身體輪廓流淌，你在春日下潛，礦物晶體如寶石叢林，噴泉的律動像大地的脈搏，隔熱服內微汗。"
    ],
    "summer": [
      "夏日蒸騰的水汽模糊視線，你穿戴隔熱潛入瀑布下的熱泉，水溫燙膚，但礦物梯田美得窒息，一陣陣噴湧推著你搖擺。",
      "灼熱的夏季，你沉入更灼熱的泉水，隔熱服反射著地獄般的熱度，礦物結晶在扭曲的視野中如幻境，間歇泉怒吼著噴發。",
      "你在盛夏的熱泉中潛游，熱氣蒸得頭暈，但隔熱保護周全，水底礦物如流動的黃金，噴湧把你拋起又接住。"
    ],
    "autumn": [
      "秋涼浸透空氣，你卻在滾熱的泉水中下潛，溫差讓礦物結晶表面凝出細密氣泡，間歇泉突然噴發，強流把你托起又按下。",
      "秋風冷冽，你躍入熱泉的懷抱，熱水燙得皮膚隔著衣料仍感灼意，礦物在秋光中折射彩虹，噴湧的間歇為你奏著低音。",
      "你潛入秋季的熱瀑之下，隔熱服外熱氣蒸騰，水溫滾熱，礦物梯田在腳下延展，一陣噴湧如掌聲，慶祝你的到訪。"
    ],
    "winter": [
      "雪落進熱泉瞬間融化，你浸入這暖流，熱霧包圍，身體從寒冬被拽進溫泉，隔熱服裡微汗，水下礦物像冰雪雕塑卻觸手溫潤。",
      "冬雪紛飛，你沉入熱泉，冰火兩重天在面罩外交鋒，熱水裹身，礦物結晶在霧氣中若隱若現，噴湧如間歇的火山。",
      "嚴寒中你投入滾熱泉水，隔熱服抵擋燙傷，水底晶簇蒙上蒸汽，噴口轟鳴，將冬日的僵硬融化。"
    ]
  },
  "sunken_ruins": {
    "autumn": [
      "你穿上保暖潛水服沉入秋日的遺蹟，斷柱在幽藍水裡靜默，陰冷刺骨，遠古迴響彷彿從石縫滲出，每一次呼吸都凝成白霧。",
      "秋水深寒，你沿著沉城的臺階下潛，大理石柱廊在水影裡扭曲，陰冷咬進骨髓，黑暗中有石像的輪廓若隱若現。",
      "你扶著半截石柱穩住身子，保暖服裡的暖意在陰冷中彌足珍貴，四周幽藍，沉城的鐘聲似有似無，秋意與古意交融。"
    ],
    "winter": [
      "冬日的沉沒城像冰封的墓穴，你潛入墨藍，保暖服勉強維持體溫，幽光裡傾倒的神殿傳來低語般的迴音，冷得你牙齒打顫。",
      "極寒的海水浸透一切，你遊過覆滿冰晶的窗欞，沉城在冬日更顯陰森，黑暗的拱門彷彿通向冥界。",
      "你撥出的氣泡在冷水中凝成冰屑，沉沒遺蹟在冬夜靜如死，保暖服發出微光，照亮斷壁上的霜花，寒意直透心靈。"
    ]
  },
  "abyssal_trench": {
    "spring": [
      "春日海面的暖意與你無關，你穿著耐壓服墜入深淵，黑暗瞬間吞噬，冰冷高壓擠壓身體，頭燈光柱裡只有永不停歇的浮游雪。",
      "你沉入春之海溝，耐壓服在高壓下嘎吱作響，水溫逼近冰點，頭燈撕開的黑暗裡，深海雪花無聲飄落，深淵在呼吸。",
      "春天的深淵依舊死寂，你穿過溫躍層便直墜入黑，極寒與高壓緊握著你，除了頭燈，唯有發光生物像遠星閃爍。"
    ],
    "summer": [
      "盛夏的海底依舊是極夜，你潛進海溝，耐壓服在高壓下呻吟，水溫接近零度，往下沉，往下沉，連時間都凍住了，只有深淵的吸噬聲。",
      "陽光在幾百米外消泯，你穿著耐壓服擁抱夏日的深淵，冷如外太空，頭燈外是無盡墨色，孤獨深重得像實體。",
      "夏季表層暖水與你無關，你深入冰寒的海溝，耐壓服被壓得緊貼骨骼，黑暗中有幽光生物畫著詭異的軌跡。"
    ],
    "autumn": [
      "秋風吹不到這萬米深淵，你沉入黑水，耐壓服隔絕著能壓碎骨頭的重負，頭燈劈開黑暗，照亮懸浮的碎屑如星塵，可那冷，依然透骨。",
      "你潛入秋日深淵，耐壓服是唯一庇護，極寒讓關節刺痛，頭燈光柱外是永恆的黑，耳邊只有金屬的應力聲。",
      "秋天的海溝更顯荒涼，你如沙粒墜入暗界，耐壓服抵禦著毀滅性的壓強，深海的冷是種無聲的暴力。"
    ],
    "winter": [
      "冬日的海面或許結冰，你沉進更深的冷寂，深淵海溝像一條黑暗的食道，高壓讓關節嘎吱響，黑暗裡有光點倏忽明滅，那是深淵自己的幽靈。",
      "你穿著耐壓服深入冬海，絕對零度的擁抱，高壓在頭盔裡低鳴，黑暗如絨布裹住一切，只有發光的誘餌在搖擺。",
      "冬季的深淵是終極的冷箱，你潛至人類禁區，耐壓服外是足以粉碎骨頭的黑暗，生物微光如垂死星火，無言訴說著深海的秘密。"
    ]
  },
  "crystal_cave": {
    "spring": [
      "你輕輕滑入水晶洞潭，清冽的水恆溫如淚，洞頂透下的光被晶簇切割成彩虹，小心別碰那些鋒利的稜，它們割皮如刀。",
      "春泉注入晶洞，水清冽恆溫，你穿梭在折射的虹光間，晶簇如利齒環伺，每一次划水都提防割傷。",
      "你潛入這個晶光世界，水溫始終如一，春日的微光在晶尖上跳舞，安靜得能聽見晶芽生長的脆響，但別貼近，稜角銳利。"
    ],
    "summer": [
      "夏日的燥熱被洞口過濾，你潛入晶光世界，水溫恆定清涼，晶簇折射出的光斑在石壁上流動，安靜得能聽到水晶生長的聲音。",
      "你躲進水晶洞穴的恆溫潭水，夏陽透過洞頂裂隙，被晶簇打散成無數彩虹，清冷包裹全身，小心手臂避開尖銳的稜。",
      "洞中恆涼如水，你沉入透澈的潭，晶洞在夏日折射出冰火般的幻光，但晶刺如刃，你需如游魚般輕靈。"
    ],
    "autumn": [
      "秋光射入晶洞，你在水下懸浮，四壁晶簇如凍結的閃電，清冽的水託著你，每一次划水都要留神尖削的晶刃。",
      "秋涼與洞內恆溫交融，你潛入水晶潭，晶簇在秋光下泛金黃，銳利的稜邊閃著警告，寂靜中只有水劃過晶面的脆響。",
      "你浸入秋日的晶洞，水清如無物，晶筍從洞頂倒懸，折射出碎星，雖美但鋒銳，徒手可潛但需萬分謹慎。"
    ],
    "winter": [
      "冬日洞外飄雪，你浸入恆溫的潭水反而感到暖意，晶洞裡光影如紗，鋒利晶尖在微光中閃爍警告，下潛時需格外輕柔。",
      "外面寒冬，晶洞的水卻溫柔恆定，你潛入這片琉璃世界，晶簇掛滿冰瑩，尖刺在頭燈下亮得睜不開眼。",
      "雪被隔絕在外，你在這恆溫的晶潭漂浮，水晶稜柱如冰凍豎琴，清冽之水託舉著你，但鋒銳的稜角時時提醒你要敬畏。"
    ]
  }
}
""").items():
    if _lid in LOCATIONS: LOCATIONS[_lid]["dive_ambience"] = _amb

FISH = {
    "mud_carp": {"id":"mud_carp","name":"泥鯉","rarity":"common","description":"一身粗糲的褐色鱗片，終日拱食河底淤泥，出水時甩你半臉泥點子。","size_min":10,"size_max":35,"size_unit":"cm","base_value":6,"locations":["moonlit_pond","reed_river","whispering_mire","starry_delta"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater"],"latin":"Cyprinus limosus"},
    "ghost_shrimp": {"id":"ghost_shrimp","name":"幽靈蝦","rarity":"common","description":"透明的身子只剩兩粒黑眼珠像浮空的芝麻，成群漂過時，彷彿水下起了一陣玻璃雨。","size_min":3,"size_max":12,"size_unit":"cm","base_value":5,"locations":["moonlit_pond","reed_river","mangrove_shoal","whispering_mire","starry_delta"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater","nocturnal"],"latin":"Palaemon spectra"},
    "flicker_minnow": {"id":"flicker_minnow","name":"熒鱗鰷","rarity":"common","description":"體側一道熒藍細線如同划著的火柴，暗處成群遊動時，能照亮半張臉。","size_min":4,"size_max":14,"size_unit":"cm","base_value":4,"locations":["moonlit_pond","reed_river"],"seasons":["spring","summer","autumn"],"tags":["freshwater","nocturnal"],"latin":"Leucaspius micans"},
    "angler_fry": {"id":"angler_fry","name":"燈鮟鱇","rarity":"common","description":"小如拇指的深海鮟鱇，額頂燈籠在無邊黑暗中連成一串墜向海底的星鏈。","size_min":4,"size_max":18,"size_unit":"cm","base_value":7,"locations":["abyssal_trench","sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","glowing"],"latin":"Antennarius lumen"},
    "sky_skipper": {"id":"sky_skipper","name":"躍空魚","rarity":"common","description":"胸鰭拉成薄膜翼，能掠出水面滑翔數米，濺起的水霧裡總掛著一小截虹。","size_min":8,"size_max":22,"size_unit":"cm","base_value":7,"locations":["floating_lake","starry_delta"],"seasons":["spring","summer","autumn"],"tags":["fantasy","wind"],"latin":"Exocoetus aetherius"},
    "frost_drifter": {"id":"frost_drifter","name":"霜漂魚","rarity":"common","description":"身體像一片薄冰，體內氦氣與寒氣讓它懸在水層中，陽光穿透時稜鏡光碎成十幾片。","size_min":6,"size_max":20,"size_unit":"cm","base_value":6,"locations":["floating_lake","starry_delta"],"seasons":["autumn"],"tags":["fantasy","wind"],"latin":"Coregonus glacies"},
    "scorched_tetra": {"id":"scorched_tetra","name":"焦鱗燈魚","rarity":"common","description":"赤褐色的鱗片佈滿灼痕，在沸水裡悠然自得，彷彿剛出爐的火炭塊。","size_min":5,"size_max":15,"size_unit":"cm","base_value":8,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn","winter"],"tags":["fire"],"latin":"Hyphessobrycon cineris"},
    "shard_fish": {"id":"shard_fish","name":"晶片魚","rarity":"common","description":"身軀如同碎裂的水晶，折射出成千上萬道細虹，遊動時整個洞穴都在閃光。","size_min":7,"size_max":18,"size_unit":"cm","base_value":7,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","glowing"],"latin":"Vitreochromis aculeus"},
    "jelly_phantom": {"id":"jelly_phantom","name":"幻水母","rarity":"common","description":"半透明的傘帽懸浮著，觸手拖曳星塵般的微光，穿過它能看到對岸扭曲的影子。","size_min":8,"size_max":25,"size_unit":"cm","base_value":6,"locations":["floating_lake","crystal_cave"],"seasons":["spring","summer"],"tags":["fantasy","glowing"],"latin":"Cnidaria umbra"},
    "winter_cinder": {"id":"winter_cinder","name":"冬燼魚","rarity":"common","description":"灰白色的鱗片下隱約透著將熄的火光，只在寒冬溫泉的石縫裡成群打轉。","size_min":5,"size_max":14,"size_unit":"cm","base_value":6,"locations":["lava_spring","geyser_falls"],"seasons":["winter"],"tags":["fire"],"latin":"Salvelinus favilla"},
    "silver_pike": {"id":"silver_pike","name":"銀梭魚","rarity":"uncommon","description":"細長如標槍的掠食者，鱗片是冷冽的銀色，出水時甩起一串水珠。","size_min":20,"size_max":55,"size_unit":"cm","base_value":26,"locations":["moonlit_pond","reed_river"],"seasons":["spring","autumn"],"tags":["freshwater"],"latin":"Esox argyronotus"},
    "dusk_eel": {"id":"dusk_eel","name":"暮色鰻","rarity":"uncommon","description":"暗紫色的細鰻只在黃昏從泥洞裡探出，像一條會流動的影子。","size_min":25,"size_max":60,"size_unit":"cm","base_value":24,"locations":["moonlit_pond","reed_river","mangrove_shoal","whispering_mire"],"seasons":["spring","autumn"],"tags":["freshwater","nocturnal"],"latin":"Anguilla crepusculum"},
    "copper_bream": {"id":"copper_bream","name":"銅魴","rarity":"uncommon","description":"寬扁的身體覆著一層銅綠般的鱗，在水草間折射出鏽跡似的光暈。","size_min":18,"size_max":45,"size_unit":"cm","base_value":22,"locations":["moonlit_pond","reed_river","whispering_mire"],"seasons":["summer","autumn"],"tags":["freshwater","armored"],"latin":"Abramis cupreus"},
    "cinder_loach": {"id":"cinder_loach","name":"餘燼泥鰍","rarity":"uncommon","description":"暗紅色的泥鰍在熱沙裡鑽進鑽出，體表不時爆出細小的火星，燙得魚線微微發顫。","size_min":10,"size_max":28,"size_unit":"cm","base_value":28,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn"],"tags":["fire"],"latin":"Barbatula favilla"},
    "deep_sculpin": {"id":"deep_sculpin","name":"深巖杜父魚","rarity":"uncommon","description":"長著骨質甲板的怪魚，趴在海底淤泥裡像一塊會呼吸的石頭，專等粗心的獵物。","size_min":15,"size_max":40,"size_unit":"cm","base_value":30,"locations":["abyssal_trench","sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","armored"],"latin":"Cottus abyssorum"},
    "mangrove_snapper": {"id":"mangrove_snapper","name":"紅樹鯛","rarity":"uncommon","description":"披著青褐色裝甲的鯛魚，在紅樹氣根迷宮間伏擊，一雙眼珠有潛望鏡的冷靜。","size_min":20,"size_max":50,"size_unit":"cm","base_value":25,"locations":["mangrove_shoal"],"seasons":["spring","summer","autumn"],"tags":["brackish","armored"],"latin":"Lutjanus rhizophorus"},
    "winter_betta": {"id":"winter_betta","name":"雪華鬥魚","rarity":"uncommon","description":"尾鰭綻開如一朵完整的雪花，在冰水裡遊動時，周遭會凝結出一圈細碎冰晶。","size_min":12,"size_max":30,"size_unit":"cm","base_value":27,"locations":["moonlit_pond","reed_river","floating_lake","starry_delta"],"seasons":["winter"],"tags":["freshwater","fantasy"],"latin":"Betta glacies"},
    "zephyr_dancer": {"id":"zephyr_dancer","name":"流風舞者","rarity":"uncommon","description":"迅捷如風的藍翼飛魚，躍出水面時拖著一縷縷棉花糖般的雲絲，落水無聲。","size_min":15,"size_max":40,"size_unit":"cm","base_value":24,"locations":["floating_lake","starry_delta"],"seasons":["spring","summer","autumn"],"tags":["wind","fantasy"],"latin":"Danio zephyrus"},
    "geyser_wyrm": {"id":"geyser_wyrm","name":"間歇泉龍","rarity":"uncommon","description":"一條無目的白蛇，平日休眠在間歇泉管道深處，只在冰封時被熱水衝上地表。","size_min":30,"size_max":80,"size_unit":"cm","base_value":29,"locations":["lava_spring","geyser_falls"],"seasons":["winter"],"tags":["fire","fantasy"],"latin":"Thermophis geysiris"},
    "crystal_angler": {"id":"crystal_angler","name":"晶刺鮟鱇","rarity":"rare","description":"額前懸著一枚六稜晶石的深海怪魚，光芒能穿透洞穴的永夜，誘使獵物自投羅網。","size_min":15,"size_max":45,"size_unit":"cm","base_value":100,"locations":["crystal_cave","abyssal_trench"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","glowing","crystal"],"latin":"Cryptopsaras crystallus"},
    "stormray": {"id":"stormray","name":"風暴鰩","rarity":"rare","description":"翼展布滿電弧紋的銀色鰩魚，躍出水面時能引下一道微型閃電，劈開一瞬的白晝。","size_min":40,"size_max":80,"size_unit":"cm","base_value":110,"locations":["floating_lake","starry_delta"],"seasons":["spring","autumn"],"tags":["fantasy","wind","electric"],"latin":"Dasyatis tempestas"},
    "magma_salamander": {"id":"magma_salamander","name":"岩漿蠑螈","rarity":"rare","description":"皮膚流淌著熔岩脈絡的兩棲生物，踏過之處水溫驟升，連魚線都開始發燙。","size_min":25,"size_max":55,"size_unit":"cm","base_value":120,"locations":["lava_spring","geyser_falls"],"seasons":["spring","summer","autumn"],"tags":["fire","fantasy"],"latin":"Ambystoma magmaticum"},
    "void_jellyfish": {"id":"void_jellyfish","name":"虛空水母","rarity":"epic","description":"指尖穿過它的邊緣時什麼都碰不到，只感到一股徹骨的虛無爬上小臂，連水聲都像被吸走了。","size_min":50,"size_max":90,"size_unit":"cm","base_value":200,"locations":["abyssal_trench","sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","glowing","shadow"],"latin":"Umbraxerxes voidus"},
    "cloud_serpent": {"id":"cloud_serpent","name":"雲鱗蛟","rarity":"epic","description":"握住它的一刻，掌心彷彿攏住了高空的風，冰涼而不可遏制的升力讓手臂微微發顫，耳畔盡是流雲摩擦的嗚咽。","size_min":60,"size_max":130,"size_unit":"cm","base_value":220,"locations":["floating_lake","starry_delta"],"seasons":["spring"],"tags":["fantasy","wind","migratory"],"latin":"Nephropterus nubigena"},
    "ember_barb": {"id":"ember_barb","name":"燼棘魚","rarity":"epic","description":"鱗片燙得幾乎握不住，空氣中瀰漫著焦枯的甜味，像剛剛熄滅的森林大火，魚身輕震時帶起火星迸濺的噼啪聲。","size_min":35,"size_max":65,"size_unit":"cm","base_value":180,"locations":["lava_spring","geyser_falls"],"seasons":["summer"],"tags":["fire","armored"],"latin":"Barbus pruna"},
    "moon_phoenix_fish": {"id":"moon_phoenix_fish","name":"月凰魚","rarity":"legendary","description":"手指剛觸到它的冰晶鰭，月光就從你的掌紋裡傾瀉而出，你聽見一聲不屬於水面的清嘯，整個人被提成一縷冷焰，在滿月的冰原上無聲燃燒——直到它從掌心滑脫，你才落回自己的骨頭裡。","size_min":50,"size_max":90,"size_unit":"cm","base_value":450,"locations":["moonlit_pond"],"seasons":["winter"],"tags":["freshwater","nocturnal","fantasy"],"latin":"Lunapterus phoeniceus","rumor":"滿月夜釣起月凰魚的人，會聽見亡者在水中合唱，一曲終了，魚便化為月光散去。"},
    "starwhale": {"id":"starwhale","name":"星鯨","rarity":"legendary","description":"指尖碰到那片半透明深藍的瞬間，腳下的堤岸便褪成了深空，你正懸浮在緩緩旋轉的銀河上，它體內的星輝穿過你的胸膛，讓你聽見自己血管裡響起了古老的鯨歌，直到它一擺尾，世界才'咔'地落回原地。","size_min":200,"size_max":450,"size_unit":"cm","base_value":480,"locations":["abyssal_trench","floating_lake"],"seasons":["winter"],"tags":["deepsea","fantasy","glowing"],"latin":"Cetus astralis","rumor":"老捕鯨人說，星鯨的胃裡裝著一片完整的星空，剖開時流星會像雨一樣落進海里。"},
    "time_eater": {"id":"time_eater","name":"時噬魚","rarity":"mythic","description":"將它托出水面的那一刻，所有聲音都被它體內的錶盤裂縫一口吞盡，你看見剛才的自己正站在釣點上朝你望來，而四周的蟲鳴與風被擰成可見的細絲，正被它一點點吸進破裂的鐘面裡，直到它微微顫動，時間才轟然倒灌，你的心跳重新響起。","size_min":1,"size_max":999,"size_unit":"cm","base_value":1000,"locations":["all"],"seasons":["all"],"tags":["fantasy","shadow","deepsea"],"individual_weight":0.3,"latin":"Chronoichthys devorans","rumor":"釣到時噬魚的那一刻，你突然記不起昨天中午吃了什麼，只覺得魚竿一沉，三年便過去了。"},
    "bog_creeper": {"id":"bog_creeper","name":"沼行魚","rarity":"common","description":"身體攤平如一片腐爛的闊葉，能在淤泥上匍匐爬行，受驚時蜷成枯球順水滾走。","size_min":8,"size_max":22,"size_unit":"cm","base_value":7,"locations":["whispering_mire"],"seasons":["spring","summer","autumn","winter"],"tags":["freshwater","swamp","nocturnal"],"latin":"Misgurnus palustris"},
    "bloat_toadfish": {"id":"bloat_toadfish","name":"鼓蟾魚","rarity":"uncommon","description":"鰓囊鼓脹如毒囊，佈滿暗紫色疣突，一離水就發出沉悶的咕噥聲，吐出苦腥的霧氣。","size_min":15,"size_max":38,"size_unit":"cm","base_value":27,"locations":["whispering_mire"],"seasons":["spring","summer","autumn"],"tags":["freshwater","swamp","poison"],"latin":"Opsanus tumidus"},
    "wraithwood_fish": {"id":"wraithwood_fish","name":"朽木靈魚","rarity":"rare","description":"半透明的身體內裹著枯木的紋理，遊動時拖曳幾縷黑煙，眼窩裡飄著兩團幽冥的磷火。","size_min":25,"size_max":55,"size_unit":"cm","base_value":105,"locations":["whispering_mire"],"seasons":["spring","autumn"],"tags":["freshwater","swamp","nocturnal","poison"],"latin":"Xylopsychus umbra"},
    "star_sand_darter": {"id":"star_sand_darter","name":"星沙鏢鱸","rarity":"common","description":"體側嵌滿熒藍光點，每年隨潮水湧入三角洲時，整片淺灘像倒懸的銀河在腳下奔流。","size_min":6,"size_max":16,"size_unit":"cm","base_value":7,"locations":["starry_delta"],"seasons":["spring","autumn"],"tags":["brackish","glowing","migratory"],"latin":"Ammocrypta siderea"},
    "tidal_trout": {"id":"tidal_trout","name":"潮信鱒","rarity":"uncommon","description":"鱗片泛著潮汐的銀藍光澤，只在朔望大潮時成群溯河，鰓蓋開合間隱約傳來海浪的節奏。","size_min":30,"size_max":60,"size_unit":"cm","base_value":26,"locations":["starry_delta"],"seasons":["spring","autumn"],"tags":["brackish","migratory","fantasy"],"latin":"Salmo aestuarium"},
    "star_barge_whisker": {"id":"star_barge_whisker","name":"星舟巨鯰","rarity":"epic","description":"沉重的身軀壓得釣竿呻吟，皮膚粗糙如冷卻的熔岩，湊近能聞到鐵鏽和遙遠星塵的乾澀氣味，它喉間發出的次聲波讓水面跳起細密的水珠。","size_min":120,"size_max":220,"size_unit":"cm","base_value":220,"locations":["starry_delta"],"seasons":["spring"],"tags":["brackish","fantasy","glowing","migratory"],"latin":"Astroglanis grandis"},
    "urn_hermit": {"id":"urn_hermit","name":"甕居蟹","rarity":"common","description":"寄居在碎裂的雙耳陶甕裡，在沉船殘骸間橫行時，甕中偶爾傳出遠古的低語與隱隱的鐘鳴。","size_min":5,"size_max":15,"size_unit":"cm","base_value":6,"locations":["sunken_ruins"],"seasons":["spring","summer","autumn","winter"],"tags":["deepsea","ancient"],"latin":"Coenobita urna"},
    "rune_cod": {"id":"rune_cod","name":"銘文鱈","rarity":"uncommon","description":"側線刻滿失傳的上古符文，遊過覆滿海藻的石柱時，那些文字會短暫地亮起琥珀色光芒。","size_min":30,"size_max":65,"size_unit":"cm","base_value":28,"locations":["sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","ancient","glowing"],"latin":"Gadus runicus"},
    "sunken_wraith": {"id":"sunken_wraith","name":"沉城幽魂魚","rarity":"epic","description":"觸感滑膩而冰冷，散發出一股潮溼石灰與朽木的黴息，貼近耳朵時能聽見水下鐘樓殘破的鐘聲在空腔裡迴盪。","size_min":70,"size_max":130,"size_unit":"cm","base_value":230,"locations":["sunken_ruins"],"seasons":["autumn","winter"],"tags":["deepsea","ancient","glowing","shadow"],"latin":"Phantomoichthys submergus"},
    "sulfur_killie": {"id":"sulfur_killie","name":"硫華鱂","rarity":"common","description":"在滾燙的硫磺泉中游弋的鱂魚，鱗片析出明黃的硫磺結晶，撈起曬乾後劃一根火柴就能點燃。","size_min":4,"size_max":12,"size_unit":"cm","base_value":8,"locations":["geyser_falls"],"seasons":["summer","autumn"],"tags":["fire","mineral"],"latin":"Fundulus sulpureus"},
    "steam_ray": {"id":"steam_ray","name":"蒸汽鰩","rarity":"uncommon","description":"從熱瀑頂端一躍而下的扁魚，噴氣孔排出咻咻白煙，恍若一臺微型蒸汽機車劃破水幕。","size_min":35,"size_max":70,"size_unit":"cm","base_value":29,"locations":["geyser_falls"],"seasons":["spring","summer"],"tags":["fire","mineral"],"latin":"Rajella vaporis"},
    "magma_peacock_bass": {"id":"magma_peacock_bass","name":"熔岩孔雀鯛","rarity":"rare","description":"體側礦脈交錯，遇熱會綻開孔雀尾屏般的虹彩，只在蒸汽最濃處露面，宛如打翻了一盒熔化的寶石。","size_min":28,"size_max":52,"size_unit":"cm","base_value":110,"locations":["geyser_falls"],"seasons":["summer"],"tags":["fire","mineral","fantasy"],"latin":"Cichla ignis"},
    "mudskipper_perch": {"id":"mudskipper_perch","name":"泥蟹攀鱸","rarity":"common","description":"用強壯的胸鰭在泥灘上匍匐爬行，甲殼上糊滿貝殼碎屑與枯葉，像一團會移動的垃圾堆。","size_min":12,"size_max":28,"size_unit":"cm","base_value":6,"locations":["mangrove_shoal"],"seasons":["spring","summer","autumn"],"tags":["brackish","armored"],"latin":"Periophthalmus lutarius"},
    "root_dragon": {"id":"root_dragon","name":"氣根龍","rarity":"rare","description":"偽裝成紅樹氣根的細長魚，能在空氣中呼吸數小時，暴風雨後會扭動著攀上矮枝，等待下一場潮水。","size_min":40,"size_max":75,"size_unit":"cm","base_value":95,"locations":["mangrove_shoal"],"seasons":["spring","summer"],"tags":["brackish","fantasy"],"latin":"Rhizophydra pneumatophora"},
    "prism_lanternfish": {"id":"prism_lanternfish","name":"稜鏡燈魚","rarity":"uncommon","description":"身體由無數微小水晶碎片聚合而成，遊動時像一枚迪斯科球，在洞壁上潑灑旋轉的虹光。","size_min":10,"size_max":25,"size_unit":"cm","base_value":28,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","glowing"],"latin":"Myctophum prismaticum"},
    "shard_shrimp": {"id":"shard_shrimp","name":"碎晶蝦","rarity":"uncommon","description":"披著透明水晶甲殼的蝦，雙螯如同兩柄玻璃匕首，敲擊巖壁時會奏出風鈴般的清脆音符。","size_min":12,"size_max":30,"size_unit":"cm","base_value":30,"locations":["crystal_cave"],"seasons":["spring","summer","autumn","winter"],"tags":["crystal","armored"],"latin":"Caridina vitreus"},
    "crystal_leviathan": {"id":"crystal_leviathan","name":"洞天晶龍","rarity":"legendary","description":"握住一片晶柱鱗片的剎那，四周的水體突然凝固成無數面稜鏡，每一面都囚著一座正在旋轉的陌生星空，你看見自己的倒影被拆分進千百個不同的星系裡，同時聽見水晶巖洞深處傳來一聲悠長的吐息，直到它遊走，所有鏡面才碎成無聲的熒光。","size_min":150,"size_max":280,"size_unit":"cm","base_value":480,"locations":["crystal_cave"],"seasons":["winter"],"tags":["crystal","glowing","fantasy"],"individual_weight":0.6,"latin":"Crystallosaurus antricola","rumor":"洞天晶龍是千萬年鐘乳石的集體夢境，一旦被帶離洞穴，原地的石頭將失去光澤，變成普通的石灰岩。"},

    "crucian": {"id": "crucian", "name": "鯽魚", "rarity": "common", "description": "最常見的練手魚，銀灰色，憨頭憨腦地咬鉤。", "size_min": 8, "size_max": 25, "size_unit": "cm", "base_value": 6, "locations": ["moonlit_pond", "reed_river"], "seasons": ["all"], "tags": ["freshwater"],"latin":"Carassius carassius"},
    "silver_dace": {"id": "silver_dace", "name": "銀鰷", "rarity": "common", "description": "成群結隊的小銀魚，陽光下鱗片閃成一片碎光。", "size_min": 6, "size_max": 18, "size_unit": "cm", "base_value": 5, "locations": ["reed_river"], "seasons": ["all"], "tags": ["freshwater"],"latin":"Rhinichthys argenteus"},
    "reed_perch": {"id": "reed_perch", "name": "蘆葦鱸", "rarity": "uncommon", "description": "潛伏在蘆葦叢裡的伏擊手，背鰭帶著鋸齒狀的紋路。", "size_min": 15, "size_max": 40, "size_unit": "cm", "base_value": 22, "locations": ["reed_river", "moonlit_pond"], "seasons": ["spring", "summer"], "tags": ["freshwater"],"latin":"Perca arundinis"},
    "glow_jelly": {"id": "glow_jelly", "name": "光水母", "rarity": "uncommon", "description": "半透明的傘狀身體裡懸著一點幽藍的光，隨水流一縮一放。", "size_min": 10, "size_max": 35, "size_unit": "cm", "base_value": 28, "locations": ["abyssal_trench"], "seasons": ["all"], "tags": ["deepsea", "glowing", "nocturnal"],"latin":"Pelagia lucida"},
    "moonscale_carp": {"id": "moonscale_carp", "name": "月鱗鯉", "rarity": "rare", "description": "鱗片在夜色中泛著銀白冷光，彷彿吞下了一小片月亮。據說它只會咬住倒映在水面的滿月。", "size_min": 20, "size_max": 60, "size_unit": "cm", "base_value": 80, "locations": ["moonlit_pond"], "seasons": ["autumn", "winter"], "tags": ["freshwater", "nocturnal"],"latin":"Cyprinus lunaris"},
    "ember_carp": {"id": "ember_carp", "name": "熔岩鯉", "rarity": "rare", "description": "通體橙紅，鱗縫裡透出岩漿般的光，離水後仍微微發燙。", "size_min": 18, "size_max": 55, "size_unit": "cm", "base_value": 110, "locations": ["lava_spring"], "seasons": ["summer"], "tags": ["fire"],"latin":"Cyprinus pruna"},
    "windveil_ray": {"id": "windveil_ray", "name": "風紗鰩", "rarity": "epic", "description": "輕得幾乎不存在，出水後若不立即捧住，便如薄紗般被風撕走，只留一縷薄荷和雨前空氣的清涼在指尖。", "size_min": 25, "size_max": 70, "size_unit": "cm", "base_value": 180, "locations": ["floating_lake"], "seasons": ["spring", "summer", "autumn"], "tags": ["fantasy", "wind"],"latin":"Velumventus aura"},
    "frostfin_eel": {"id": "frostfin_eel", "name": "霜鰭鰻", "rarity": "epic", "description": "握在手裡涼得發疼，鰭尖的霜化在掌心，像攥著一把不肯停的冬天，鬆開後還能聽見冰裂的細響在骨頭裡迴盪。", "size_min": 30, "size_max": 90, "size_unit": "cm", "base_value": 220, "locations": ["abyssal_trench"], "seasons": ["winter"], "tags": ["deepsea", "glowing"],"latin":"Conger gelidus"},
    "clockwork_koi": {"id": "clockwork_koi", "name": "發條錦鯉", "rarity": "legendary", "description": "手指覆上它打磨般的黃銅鱗片時，耳中的滴答聲猛地擴成一座看不見的鐘樓，無數透明的齒輪從你眼前齧合著升起，日與夜在你皮膚上像翻書一樣快速明滅，你聞到了時間本身的氣味——舊銅、乾涸的機油和億萬個正午的暴曬，直到它一甩尾，你才從時間的齒縫裡跌回岸邊。", "size_min": 30, "size_max": 80, "size_unit": "cm", "base_value": 400, "locations": ["floating_lake"], "seasons": ["all"], "tags": ["fantasy"],"latin":"Machina cyprinus","rumor":"發條錦鯉體內的齒輪日夜不停，有鐘錶匠從它鰓蓋裡聽出了某座早已沉沒的城市敲響的午時鐘聲。"},
    "the_first_drop": {"id": "the_first_drop", "name": "「第一滴水」", "rarity": "mythic", "description": "你小心翼翼地捧起這尾近乎不存在的水影，指尖卻觸到了一片混沌的冰涼，耳中猛然炸開天地初分時的第一聲雷鳴，無數道原始的雨絲自虛空垂落，在你眼前匯成海洋、沖積出河床，直到它輕輕滑回水中，這場只有你目睹的創世暴雨才驟然停歇。", "size_min": 1, "size_max": 30, "size_unit": "cm", "base_value": 1000, "locations": ["all"], "seasons": ["all"], "individual_weight": 1.0, "tags": ["fantasy"],"latin":"Primastilla primordialis","rumor":"「第一滴水」是海洋的第一粒種子，握在手裡時能聽見世界誕生時的第一聲雷，在掌心嗡嗡作響。"},
}
# ── 水下魚（dive=True，潛水專屬：只在 dive 時出現，水面拋竿永遠釣不到）。DS 按模板產出，22 種、每釣點 2 種，含 capture_feel 捕獲手感。──
FISH.update({_f["id"]: _f for _f in json.loads(r"""
[
  {
    "id": "reed_clinger",
    "name": "蘆根吸鰍",
    "rarity": "common",
    "description": "緊貼在蘆葦根鬚上的灰褐色小魚，身體扁平像一片枯葉，嘴特化成吸盤狀，終日刮食附著的藻類。",
    "size_min": 5,
    "size_max": 12,
    "size_unit": "cm",
    "base_value": 6,
    "locations": ["reed_river"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater"],
    "dive": true,
    "latin": "Phragmitichthys adhaerens",
    "capture_feel": "輕得像扯下一片溼透的枯葉，指尖傳來蘆根斷裂的脆響，伴隨淡淡的藻腥味，手心殘留滑膩的涼意。"
  },
  {
    "id": "mud_nibbler",
    "name": "泥伏仔",
    "rarity": "common",
    "description": "半透明的軟體小魚，常把自己埋進河底淤泥只露一對眼柄，像兩粒小芝麻，伺機捕食水蚤。",
    "size_min": 4,
    "size_max": 9,
    "size_unit": "cm",
    "base_value": 5,
    "locations": ["reed_river"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Limicola occultus",
    "capture_feel": "提起時帶出一小團渾水，手裡像捏住一塊將化的果凍，軟滑冰涼，它在指間微微搏動，彷彿捏著一顆迷你的心臟。"
  },
  {
    "id": "moon_catfish",
    "name": "月光鯰",
    "rarity": "common",
    "description": "銀灰色的小鯰魚，只在月光透入水底時游出沉木縫隙，皮膚反射淡淡冷光，以掉落水面的飛蟲為食。",
    "size_min": 10,
    "size_max": 20,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["moonlit_pond"],
    "seasons": ["spring", "summer", "autumn"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Silurus lunaris",
    "capture_feel": "提出水面時鱗片泛起清冷銀光，掌心傳來一陣幽涼，如同握住一捧月光，恍惚間聽見遠處夜蟲的低鳴。"
  },
  {
    "id": "shadow_snail",
    "name": "影殼蝸",
    "rarity": "uncommon",
    "description": "殼表長滿暗色絨毛，白天完全隱沒在沉木陰影裡，入夜後才伸出觸手濾食水中碎屑，螺殼輕敲會發出沉悶迴響。",
    "size_min": 6,
    "size_max": 15,
    "size_unit": "cm",
    "base_value": 25,
    "locations": ["moonlit_pond"],
    "seasons": ["all"],
    "tags": ["underwater", "freshwater", "nocturnal"],
    "dive": true,
    "latin": "Umbraconcha nocturna",
    "capture_feel": "指尖碰到殼面絨毛，像撫摸一塊溼苔蘚，輕敲螺殼時掌心傳來沉悶的咚咚聲，如同叩響一扇沉在水底的舊木門。"
  },
  {
    "id": "mire_leech",
    "name": "泥蛭螈",
    "rarity": "common",
    "description": "形似水蛭與蠑螈的混合體，背部鼓起毒囊散發微弱熒光，它貼附在腐木上一動不動，直到獵物觸碰其黏性皮膚。",
    "size_min": 7,
    "size_max": 14,
    "size_unit": "cm",
    "base_value": 9,
    "locations": ["whispering_mire"],
    "seasons": ["spring", "summer", "autumn"],
    "tags": ["underwater", "swamp", "poison", "nocturnal"],
    "dive": true,
    "latin": "Hirudisalamandra palustris",
    "capture_feel": "皮膚接觸黏液的瞬間指尖微麻，一股腐敗的甜香鑽進鼻腔，頭微微發暈，彷彿聽見沼澤深處傳來含糊不清的耳語。"
  },
  {
    "id": "whisper_ray",
    "name": "耳語鬼鰩",
    "rarity": "rare",
    "description": "扁平如黑布，邊緣波浪狀擺動，貼著淤泥滑行，身體能發出類似耳語的沙沙聲，傳說那是溺亡者未盡的低語。",
    "size_min": 30,
    "size_max": 50,
    "size_unit": "cm",
    "base_value": 110,
    "locations": ["whispering_mire"],
    "seasons": ["autumn", "winter"],
    "tags": ["underwater", "swamp", "shadow", "nocturnal"],
    "dive": true,
    "latin": "Torpedo susurrus",
    "capture_feel": "魚線傳來一陣令人牙酸的震顫，水下沙沙聲貼著指尖鑽進耳朵，握住它時掌心陰冷，像握著一團浸透悲傷的溼布，低語久久不散。"
  },
  {
    "id": "delta_glow_shrimp",
    "name": "星河熒蝦",
    "rarity": "uncommon",
    "description": "半透明蝦身，腹下綴滿星點熒光，鹹淡水交匯處叢集懸浮，隨潮汐漂移時宛如水底銀河。",
    "size_min": 4,
    "size_max": 9,
    "size_unit": "cm",
    "base_value": 28,
    "locations": ["starry_delta"],
    "seasons": ["spring", "summer"],
    "tags": ["underwater", "brackish", "glowing", "migratory"],
    "dive": true,
    "latin": "Lucicaris deltae",
    "capture_feel": "撈起時手心彷彿捧住一小把流動的星屑，指尖滑過細密的電流感，眼前光點飛舞，一瞬之間如墜夏夜銀河。"
  },
  {
    "id": "light_eel",
    "name": "三角洲光鰻",
    "rarity": "rare",
    "description": "細長如光線織成的鰻，體側藍綠色光點連成潮汐紋路，每年溯河繁殖時整條水道都被照亮。",
    "size_min": 35,
    "size_max": 60,
    "size_unit": "cm",
    "base_value": 115,
    "locations": ["starry_delta"],
    "seasons": ["spring"],
    "tags": ["underwater", "brackish", "glowing", "migratory"],
    "dive": true,
    "latin": "Anguilla lucis",
    "capture_feel": "竿尖傳來持續的高頻顫動，水中亮起一長條藍綠色軌跡，握住它時皮膚感到溫熱的脈動光感，彷彿手中抓住的是一道活著的光。"
  },
  {
    "id": "mangrove_crab",
    "name": "紅樹瓷蟹",
    "rarity": "common",
    "description": "扁平蟹殼如碎瓷拼貼，一對螯鉗緊抓紅樹氣根，濾食時用小螯優雅地朝口器撥水，從不主動離開根鬚。",
    "size_min": 5,
    "size_max": 10,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["mangrove_shoal"],
    "seasons": ["all"],
    "tags": ["underwater", "brackish", "armored"],
    "dive": true,
    "latin": "Porcellana rhizophorae",
    "capture_feel": "提起時蟹鉗敲擊發出清脆的瓷片碰撞聲，涼涼的硬殼質感彷彿捏著一塊古瓷，耳邊隱約聽到紅樹林氣根吱呀作響的迴音。"
  },
  {
    "id": "root_hider",
    "name": "氣根隱魚",
    "rarity": "uncommon",
    "description": "身體側扁如刀，能瞬間側身擠進紅樹氣根的極窄縫隙，體色隨周圍樹皮變化，捕食路過的小型甲殼動物。",
    "size_min": 8,
    "size_max": 18,
    "size_unit": "cm",
    "base_value": 26,
    "locations": ["mangrove_shoal"],
    "seasons": ["all"],
    "tags": ["underwater", "brackish"],
    "dive": true,
    "latin": "Cryptichthys radicis",
    "capture_feel": "從根縫拉出時魚線劇烈抖動，手感像撕開一層堅韌的樹皮，出水剎那體色瘋狂變幻，掌中彷彿握住一小片逃逸的彩虹。"
  },
  {
    "id": "float_bladder",
    "name": "浮湖泡囊",
    "rarity": "common",
    "description": "透明的泡囊群懸浮在湖底無重力區，靠內部氣體控制升降，囊壁佈滿虹彩纖毛，以捕獲水中有機微粒為生。",
    "size_min": 3,
    "size_max": 10,
    "size_unit": "cm",
    "base_value": 7,
    "locations": ["floating_lake"],
    "seasons": ["all"],
    "tags": ["underwater", "fantasy", "wind"],
    "dive": true,
    "latin": "Vesicula aeris",
    "capture_feel": "觸感輕盈柔彈，像捏著一團充氣的水母，離水時發出細微的“啵”聲，指尖能感到內部氣體流動的酥麻，身體一時輕飄飄的。"
  },
  {
    "id": "drift_leaf_dragon",
    "name": "浮空葉龍",
    "rarity": "uncommon",
    "description": "形如一片楓葉的小型海龍，用葉狀附肢在懸浮層緩慢飄遊，體色隨湖水晶光變幻，靠捕食浮游生物為生。",
    "size_min": 12,
    "size_max": 25,
    "size_unit": "cm",
    "base_value": 28,
    "locations": ["floating_lake"],
    "seasons": ["spring", "summer"],
    "tags": ["underwater", "fantasy", "wind"],
    "dive": true,
    "latin": "Phyllopteryx ventus",
    "capture_feel": "輕得幾乎沒有重量，葉狀附肢在掌心輕輕撓動如落葉劃過，深吸一口氣，彷彿嗅到高空的稀薄氣流，眼前浮現漂浮島嶼的幻影。"
  },
  {
    "id": "lava_scale_worm",
    "name": "熔鱗蟲",
    "rarity": "common",
    "description": "體覆赤紅鱗片，能在接近沸點的泉底爬行，以硫細菌為食，鱗片邊緣在高溫下微微發紅如即將燃燒。",
    "size_min": 3,
    "size_max": 8,
    "size_unit": "cm",
    "base_value": 9,
    "locations": ["lava_spring"],
    "seasons": ["summer"],
    "tags": ["underwater", "fire"],
    "dive": true,
    "latin": "Thermolepis igneus",
    "capture_feel": "出水時水汽蒸騰，手心傳來一陣灼熱卻並不燙傷，像握著剛從窯中取出的陶片，硫磺味撲鼻，耳邊咕嘟作響如岩漿冒泡。"
  },
  {
    "id": "geyser_salamander",
    "name": "溫泉火蠑",
    "rarity": "uncommon",
    "description": "通體暗紅帶有火焰紋，腳趾特化成吸盤，吸附在泉口岩石上，偶爾張開口吞食被燙暈的小蟲，皮膚分泌耐熱黏液。",
    "size_min": 15,
    "size_max": 30,
    "size_unit": "cm",
    "base_value": 30,
    "locations": ["lava_spring"],
    "seasons": ["summer"],
    "tags": ["underwater", "fire"],
    "dive": true,
    "latin": "Ignisalamandra thermalis",
    "capture_feel": "它扭動時分泌的熱黏液順著指縫滑落，一股暖流順手臂而上，水汽蒸騰間竟在掌中映出一道微小的彩虹，胸口都跟著溫熱起來。"
  },
  {
    "id": "mineral_sucker",
    "name": "礦屑魨",
    "rarity": "common",
    "description": "嘴部變成吸盤狀，牢牢吸在熱泉口富含礦物的巖壁上，皮膚灰白帶有金屬光澤，刮食沉澱的硫化物。",
    "size_min": 6,
    "size_max": 14,
    "size_unit": "cm",
    "base_value": 8,
    "locations": ["geyser_falls"],
    "seasons": ["all"],
    "tags": ["underwater", "mineral"],
    "dive": true,
    "latin": "Sulfurophilus minera",
    "capture_feel": "魚嘴吸住掌心不放，傳來持續的微弱吸力，像有小磁石在皮下來回扯動，皮膚感受到金屬的冰涼，輕敲牙齒竟有金石之音。"
  },
  {
    "id": "crystal_snail",
    "name": "熱泉晶螺",
    "rarity": "uncommon",
    "description": "螺殼層層疊疊如尖塔，由熱泉礦物膠結而成，呈半透明淡藍色，在湧水間歇時會輕微震顫，濾食微生物。",
    "size_min": 5,
    "size_max": 12,
    "size_unit": "cm",
    "base_value": 26,
    "locations": ["geyser_falls"],
    "seasons": ["all"],
    "tags": ["underwater", "mineral", "crystal"],
    "dive": true,
    "latin": "Crystalloconcha geyseris",
    "capture_feel": "螺殼在手中輕輕震顫，如握一枚剛敲過的音叉，細微的嗡鳴沿著指骨傳向耳膜，晶體折射的光斑在掌心跳躍不止。"
  },
  {
    "id": "column_moss_animal",
    "name": "斷柱苔蟲",
    "rarity": "rare",
    "description": "由無數微小的管蟲聚整合鹿角狀群體，緊貼沉城石柱，觸手冠在水流中搖曳如白焰，濾食時整片群體明暗閃爍。",
    "size_min": 20,
    "size_max": 45,
    "size_unit": "cm",
    "base_value": 105,
    "locations": ["sunken_ruins"],
    "seasons": ["all"],
    "tags": ["underwater", "ancient"],
    "dive": true,
    "latin": "Bryozoa columnaris",
    "capture_feel": "撈起的瞬間上千根觸手同時收縮，手指像被無數微小的羽毛刷過，一陣集體的蠕動感從掌心竄上後頸，空氣中瀰漫起古老石粉的乾澀氣味。"
  },
  {
    "id": "ruin_gargoyle_fish",
    "name": "沉城石像魚",
    "rarity": "epic",
    "description": "形似石像鬼的巨魚，鱗片如風化的石灰岩，長期靜止在沉城拱門上方，雙目偶爾轉動時才會被誤認為雕塑，以闖入的魚類為食。",
    "size_min": 80,
    "size_max": 150,
    "size_unit": "cm",
    "base_value": 230,
    "locations": ["sunken_ruins"],
    "seasons": ["autumn", "winter"],
    "tags": ["underwater", "ancient", "shadow"],
    "dive": true,
    "latin": "Gargoylithis ruinosus",
    "capture_feel": "上鉤時竿身劇彎如滿弓，沉重得彷彿在水底拖動一尊石像。它猛然睜眼的剎那，魚線傳來低頻的震動，整條手臂都在發麻，耳邊迴盪起水下鐘樓般沉悶的轟響。"
  },
  {
    "id": "abyssal_dragon_maw",
    "name": "深淵龍口",
    "rarity": "epic",
    "description": "巨大的嘴佔據身體一半，下顎懸掛發光須條，在無光深淵裡搖晃誘餌，皮膚漆黑如夜，只有被誘獵物照亮它的瞳孔時才顯出其恐怖輪廓。",
    "size_min": 100,
    "size_max": 200,
    "size_unit": "cm",
    "base_value": 240,
    "locations": ["abyssal_trench"],
    "seasons": ["all"],
    "tags": ["underwater", "deepsea", "glowing"],
    "dive": true,
    "latin": "Abyssobranchus draconis",
    "capture_feel": "收線時深海一片漆黑，只有遠處那點誘餌寒光搖晃。魚竿冰冷刺骨，手掌彷彿探入虛空，拉上來的不是重量，而是深淵本身的寂靜，耳中只剩下自己沉悶的心跳。"
  },
  {
    "id": "abyssal_embryo",
    "name": "混沌胎",
    "rarity": "legendary",
    "description": "一團脈動的暗紫色生物光團，半透明的膜內蜷縮著未成形的巨獸胚胎，數條觸腕隨深海洋流靜靜飄蕩，每一次脈動都讓百米內所有發光生物同時熄滅。",
    "size_min": 150,
    "size_max": 250,
    "size_unit": "cm",
    "base_value": 450,
    "locations": ["abyssal_trench"],
    "seasons": ["all"],
    "tags": ["underwater", "deepsea", "glowing", "ancient", "fantasy"],
    "dive": true,
    "latin": "Embryon abyssalis",
    "rumor": "老水手說，深淵溝底藏著尚未誕生的海神，若它睜開眼，整片海都將變成它的羊水。",
    "capture_feel": "上鉤瞬間整片水域陷入死黑。手掌覆上那層堅韌而溫熱的膜，內部傳來沉重、緩慢的脈動，彷彿正捧著另一顆原始的心臟。腦海中湧來遠古海洋的腥鹹與低語，你一時分不清是它在呼吸，還是自己在呼吸。"
  },
  {
    "id": "crystal_cluster_shrimp",
    "name": "晶簇蝦",
    "rarity": "rare",
    "description": "身體與水晶簇完全融為一體，只有進食時會伸出透明的觸鬚濾食微生物，甲殼斷面折射出虹光，宛若活著的寶石。",
    "size_min": 6,
    "size_max": 15,
    "size_unit": "cm",
    "base_value": 110,
    "locations": ["crystal_cave"],
    "seasons": ["all"],
    "tags": ["underwater", "crystal", "glowing"],
    "dive": true,
    "latin": "Crystallocaris spelea",
    "capture_feel": "出水時無數細小的晶面輕輕扎著掌心，帶來細微的刺痛與清涼，隨後一道彩虹在指間炸開，耳邊響起水晶被輕敲後悠長的嗡鳴。"
  },
  {
    "id": "cave_eye",
    "name": "晶洞之眼",
    "rarity": "legendary",
    "description": "一顆懸浮在洞底水潭中的巨大眼球狀生物，瞳孔由無數細小晶體拼成，轉動時投射出萬花筒般的光紋，凝視過久會聽見礦物生長的低吟。",
    "size_min": 60,
    "size_max": 120,
    "size_unit": "cm",
    "base_value": 480,
    "locations": ["crystal_cave"],
    "seasons": ["all"],
    "tags": ["underwater", "crystal", "glowing", "ancient", "fantasy"],
    "dive": true,
    "latin": "Oculus crystallinus",
    "rumor": "礦工們說，水晶洞最深處的那潭水底，有一隻從太古就睜著的眼睛，它目睹了每一條水晶的生長。",
    "capture_feel": "提起它的剎那，手臂感受到的不是重量，而是整個洞穴的黑暗壓向肩頭。眼球出水時瞳孔緩緩轉動，與你對視的一瞬，皮膚掠過一陣被徹底看穿的刺骨寒意，耳中滿是礦物生長時細碎而古老的咔咔聲，彷彿時間正在掌心結晶。"
  }
]
""")})
# 早期經濟：常規魚普遍賣價低於魚餌成本（釣常見魚虧本），統一上調 base_value（不動少見及以上）。
for _f in FISH.values():
    if _f.get("rarity") == "common": _f["base_value"] += 5
BAITS = {
    "basic_worm": {"id": "basic_worm", "name": "普通蚯蚓", "cost": 10, "description": "最樸素的蚯蚓，沒有任何特殊效果，勝在便宜。", "effects": {}},
    "glow_bait": {"id": "glow_bait", "name": "夜光餌", "cost": 35, "description": "在黑暗中散發幽幽藍光，對夜行性魚類格外有吸引力。", "effects": {"rarity_weight_mult": {"rare": 1.5, "epic": 1.3}, "tag_weight_mult": {"nocturnal": 2.0}, "junk_chance_mult": 0.8}},
    "golden_lure": {"id": "golden_lure", "name": "黃金亮片", "cost": 80, "description": "華麗的金色旋轉亮片，專挑大貨：壓住普通小魚的咬口、把機會讓給稀有及以上的稀客，還更少纏上雜物。（這片水域有稀有魚時才划算）", "effects": {"rarity_weight_mult": {"common": 0.5, "uncommon": 0.8, "rare": 1.4, "epic": 1.6, "legendary": 2.0, "mythic": 2.0}, "junk_chance_mult": 0.7}},
}
# 氧氣瓶：潛水消耗品，一瓶 = 潛一次（一次捕獲）。在 shop 買、用 dive 下水（不耗魚餌）。
OXYGEN = {"id": "oxygen", "name": "氧氣瓶", "cost": 45, "description": "一瓶壓縮氧氣，夠你潛下去捕一次。帶幾瓶就能連潛幾次——水下有些只能潛水才遇得到的魚。"}
# 特殊事件 / 物品：留空 = 不觸發（填了內容自動啟用）
EVENTS = json.loads(r"""{"drift_bottle": {"id": "drift_bottle", "name": "漂流瓶", "type": "bottle", "weight": 145, "unique": true, "description": "一隻隨波而來的玻璃瓶撞上你的浮標——瓶裡卷著一張陌生人寫的紙條。", "messages": ["（致撈到這隻瓶子的人：今天也辛苦啦，願你下一竿就是大魚。——一個把煩惱塞進瓶子扔進海里的人）", "（瓶子裡只有一句話：如果你讀到這裡，說明海把它送對了人。祝你好運。）", "（一張被海水泡得發皺的紙條，上面畫著一條歪歪扭扭的魚，旁邊寫著：我釣了一整天，只釣到這隻瓶子。哈。）", "（恭喜你撈到一隻空瓶——裡面什麼都沒有，連張紙條都沒有。就當大海跟你打了個招呼吧。）", "（紙條上是一行陌生的字：願你所求皆有迴響，願你所釣皆有驚喜。落款是一個誰也認不出的簽名。）", "（瓶裡卷著半形舊海圖，海岸線早被水泡得模糊，只有一處被紅筆圈住，寫著「這片海的魚最好釣」——可惜沒人知道是哪片海。）"], "rewards": {"fragment": 1}}, "floating_coral_pearl": {"id": "floating_coral_pearl", "name": "漂來的珊瑚珠", "type": "treasure", "weight": 18, "description": "浪尖上託著一顆粉紅的珍珠，隨著波光上下起浮，像一朵珊瑚花。", "rewards": {"items": [{"id": "coral_pearl", "qty": 1}]}}, "ambergris_chunk": {"id": "ambergris_chunk", "name": "浮香的龍涎", "type": "treasure", "weight": 10, "description": "一塊灰白的蠟狀物漂浮過來，空氣裡忽然漫開一股奇異的幽香。", "rewards": {"items": [{"id": "ambergris", "qty": 1}]}}, "rusty_chest": {"id": "rusty_chest", "name": "鏽跡寶箱", "type": "chest", "weight": 25, "description": "一隻包著鐵皮的舊木箱浮出水面，鐵鎖佈滿紅鏽，但依然堅固。", "lock": {"or_points": 80}, "loot_table": [{"weight": 60, "reward": {"points_range": [100, 200]}}, {"weight": 15, "reward": {"items": [{"id": "ancient_key", "qty": 1}]}}, {"weight": 15, "reward": {"items": [{"id": "gem_sapphire", "qty": 1}]}}, {"weight": 5, "reward": {"bait": [{"id": "golden_lure", "qty": 1}]}}, {"weight": 5, "reward": {"items": [{"id": "shipwreck_coin", "qty": 1}]}}, {"weight": 20, "reward": {"fragment": 1}}, {"weight": 3, "reward": {"map": 1}}]}, "barnacle_chest": {"id": "barnacle_chest", "name": "藤壺密箱", "type": "chest", "weight": 20, "description": "一隻被藤壺層層包裹的石箱，蓋子上刻著古老的漩渦紋，沒有鎖孔，卻緊密得幾乎撬不開。", "lock": {"or_points": 60}, "loot_table": [{"weight": 50, "reward": {"points_range": [80, 180]}}, {"weight": 30, "reward": {"items": [{"id": "moonstone", "qty": 1}]}}, {"weight": 20, "reward": {"bait": [{"id": "glow_bait", "qty": 3}]}}, {"weight": 20, "reward": {"fragment": 1}}, {"weight": 2, "reward": {"map": 1}}]}, "ancient_captain_chest": {"id": "ancient_captain_chest", "name": "船長遺箱", "type": "chest", "weight": 8, "description": "一隻雕著海怪纏錨圖案的暗銅寶箱，從深水緩緩升起，海水從鎖孔裡汩汩流出。", "lock": {"requires_item": "ancient_key", "or_points": 200}, "loot_table": [{"weight": 40, "reward": {"points_range": [150, 300]}}, {"weight": 35, "reward": {"items": [{"id": "moonstone", "qty": 1}, {"id": "gem_sapphire", "qty": 1}]}}, {"weight": 25, "reward": {"bait": [{"id": "golden_lure", "qty": 2}]}}, {"weight": 15, "reward": {"fragment": 1}}, {"weight": 5, "reward": {"map": 1}}]}}""")
ITEMS = json.loads(r"""{"coral_pearl":{"id":"coral_pearl","name":"珊瑚珍珠","type":"treasure","description":"粉紅色的珍珠，帶著珊瑚的溫潤光澤，彷彿剛從人魚的王冠上摘下。","value":150,"sellable":true},"gem_sapphire":{"id":"gem_sapphire","name":"藍寶石","type":"treasure","description":"深海般的藍色，裡面封存著浪濤的紋路，輕晃時彷彿有潮聲。","value":300,"sellable":true},"moonstone":{"id":"moonstone","name":"月光石","type":"treasure","description":"乳白色的石頭上流轉著月華般的光暈，傳說月光凝結而成。","value":450,"sellable":true},"ambergris":{"id":"ambergris","name":"龍涎香","type":"treasure","description":"傳說中的鯨之寶，散發著奇異幽香，正是香料商人夢寐以求的至寶。","value":500,"sellable":true},"shipwreck_coin":{"id":"shipwreck_coin","name":"沉船金幣","type":"treasure","description":"一枚古老的金幣，正面刻著模糊的王冠，背面是早已沉沒的船名。","value":200,"sellable":true},"coral_crown":{"id":"coral_crown","name":"珊瑚王冠","type":"treasure","description":"由活珊瑚天然生長成的冠冕，枝椏間還綴著細小的珍珠，傳說是某位人魚公主的舊物。","value":280,"sellable":true},"mermaid_tear":{"id":"mermaid_tear","name":"人魚之淚","type":"treasure","description":"一滴永不幹涸的人魚眼淚，凝成晶瑩的水藍色寶珠，貼近耳邊能聽見極輕的嗚咽。","value":420,"sellable":true},"ancient_relic":{"id":"ancient_relic","name":"遠古遺物","type":"treasure","description":"一塊刻滿失傳符文的金屬殘片，來自沉入水底的古文明，握著它彷彿觸到了某段被淹沒的歷史。","value":340,"sellable":true},"ancient_key":{"id":"ancient_key","name":"古老的鑰匙","type":"key","description":"一把沉重的黃銅鑰匙，尾端雕著海怪纏錨的圖案，握在手裡彷彿能聽見遠航的號角。","value":0,"sellable":false}}""")
# 水下專屬寶箱（不進水面事件池，靠潛水幸運事件 seafloor_vault 投放；open 時和 EVENTS 一併查表）。
DIVE_EVENTS = json.loads(r"""{"seafloor_vault": {"id": "seafloor_vault", "name": "海底寶庫", "type": "chest", "description": "嵌在海床裂縫裡的一隻覆滿貝殼與珊瑚的青銅箱，鎖早已鏽死，縫裡卻滲出珠光。", "lock": {"or_points": 120}, "loot_table": [{"weight": 35, "reward": {"points_range": [180, 350]}}, {"weight": 22, "reward": {"items": [{"id": "mermaid_tear", "qty": 1}]}}, {"weight": 20, "reward": {"items": [{"id": "coral_crown", "qty": 1}, {"id": "coral_pearl", "qty": 1}]}}, {"weight": 13, "reward": {"oxygen": 5}}, {"weight": 10, "reward": {"items": [{"id": "ancient_relic", "qty": 1}, {"id": "gem_sapphire", "qty": 1}]}}, {"weight": 12, "reward": {"fragment": 1}}, {"weight": 6, "reward": {"map": 1}}]}}""")

# 水下奇遇表（潛水幸運事件的資料來源，純資料；加新奇觀=只加條目）。reward 交給 _grant_rewards 通用解析。
ITEMS.update(json.loads(r"""
{
 "giant_clam_pearl": {
  "id": "giant_clam_pearl",
  "name": "硨磲靈珠",
  "type": "treasure",
  "description": "自巨型硨磲體內取出的渾圓珠，月光下流轉虹彩，傳說佩戴者能與貝殼耳語。",
  "value": 380,
  "sellable": true
 },
 "icebound_chart": {
  "id": "icebound_chart",
  "name": "冰封的航海圖",
  "type": "treasure",
  "description": "封在永凍冰塊裡的古航海圖，標註著一處不存於任何海圖上的秘境——可惜一遇暖流就會融化。",
  "value": 480,
  "sellable": true
 },
 "siren_scale": {
  "id": "siren_scale",
  "name": "海妖的鱗片",
  "type": "treasure",
  "description": "一片泛著幽綠的鱗，邊緣鋒利如刃，依稀殘留著令水手甘願躍入深海的低吟。",
  "value": 350,
  "sellable": true
 },
 "salt_crystal_rose": {
  "id": "salt_crystal_rose",
  "name": "鹽晶玫瑰",
  "type": "treasure",
  "description": "海底鹽礦裂隙中自然生長的晶體，形如一朵盛開的玫瑰，輕舔舌尖滿是海的鹹澀。",
  "value": 200,
  "sellable": true
 },
 "lighthouse_lens_shard": {
  "id": "lighthouse_lens_shard",
  "name": "燈塔透鏡碎片",
  "type": "treasure",
  "description": "沉沒燈塔的巨型透鏡碎片，依舊能將深海微光聚成一束暖黃，像被困在海底的落日。",
  "value": 180,
  "sellable": true
 },
 "dragon_king_scale": {
  "id": "dragon_king_scale",
  "name": "龍王逆鱗",
  "type": "treasure",
  "description": "傳說龍王心口那片逆生的鱗，觸之生溫，能令深海暗流中的邪物紛紛退避，如遇君王。",
  "value": 850,
  "sellable": true
 },
 "abyss_black_pearl": {
  "id": "abyss_black_pearl",
  "name": "深淵黑珍珠",
  "type": "treasure",
  "description": "在深淵裂隙極寒高壓下孕育的黑珠，內裡有旋動的幽藍星塵，彷彿鎖著一片微型宇宙。",
  "value": 400,
  "sellable": true
 },
 "whale_bone_pearl": {
  "id": "whale_bone_pearl",
  "name": "鯨骨髓珠",
  "type": "treasure",
  "description": "從鯨落脊椎骨中剝出的髓石，幽白如玉，輕叩時會發出次聲波般深入胸膛的低鳴。",
  "value": 380,
  "sellable": true
 },
 "ancient_sea_page": {
  "id": "ancient_sea_page",
  "name": "古海圖書頁",
  "type": "treasure",
  "description": "泡不爛的古羊皮紙殘頁，寫滿早已失傳的海語文字，邊角還夾著一縷乾透的海藻。",
  "value": 320,
  "sellable": true
 },
 "jellyfish_heart": {
  "id": "jellyfish_heart",
  "name": "發光水母之心",
  "type": "treasure",
  "description": "一枚脈動著微光的半透明器官，捧在手心如捧著一顆墜落海底的恆星，溫熱而羞怯。",
  "value": 550,
  "sellable": true
 },
 "altar_blood_jade": {
  "id": "altar_blood_jade",
  "name": "祭壇血玉",
  "type": "treasure",
  "description": "浸滿祭獻之血的白玉璧，夜深時滲出細密水珠，如遠方大海在黑暗裡無聲哭泣。",
  "value": 600,
  "sellable": true
 },
 "lost_bell": {
  "id": "lost_bell",
  "name": "失落的鐘鈴",
  "type": "treasure",
  "description": "沉沒鐘樓的青銅鐘鈴，鈴舌早已鏽斷，被水流撥動時，仍有低迴的餘音撞進潛水員的胸腔。",
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
  "name": "珊瑚宮",
  "weight": 10,
  "text": "你撞見一座由活珊瑚天然長成的水下宮殿，殿宇隨波搖曳，枝椏間還垂著細小的珍珠。",
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
  "name": "人魚宮殿",
  "weight": 6,
  "text": "一隊人魚把你引進她們的珍珠宮殿，殿內珠玉生輝，臨別她們贈你一件珍寶。",
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
  "name": "古遺蹟",
  "weight": 8,
  "text": "你潛入一片古文明的水下遺蹟，斷碑殘柱間殘字斑駁，淤沙裡埋著舊日的器物與散落的金幣。",
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
  "name": "海底寶庫",
  "weight": 5,
  "branch": true,
  "intro": "一座被海藻和珊瑚半掩的石砌庫房，厚重的石門裂開一道只容一人側身擠入的縫隙，裡面隱約透出金幣堆疊的反光——以及某種更暗沉、更古老的金色。",
  "options": [
   {
    "label": "扛起最深處的沉重金匣",
    "oxygen": 2,
    "outcome": {
     "text": "你咬緊牙關將那隻佈滿海鏽的金匣扛上肩膀，每遊一米都像在和整個海洋拔河。但你絕不放手——這重量值得任何代價。",
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
    "label": "就地撬開看一眼",
    "oxygen": 1,
    "outcome": {
     "text": "你撬開寶庫角落一隻鬆動的石匣，寶石和古幣湧出來，在你面前漂成一片短暫的星空。你抓了一把，轉身離開。",
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
    "label": "留一口氣，繼續向前探索",
    "oxygen": 0,
    "outcome": {
     "text": "你記下寶庫的位置，把貪婪按回心底，轉身遊向未知的黑暗。石門在身後發出沉悶的嘆息，像是遺憾，又像是讚許。",
     "reward": {}
    }
   }
  ]
 },
 {
  "emoji": "🚢",
  "id": "shipwreck_graveyard",
  "name": "沉船墓場",
  "weight": 5,
  "branch": true,
  "intro": "數十艘古船的殘骸層疊成一座水中墓園，斷裂的桅杆如墓碑般指向海面。就在你靠近時，一條銀鱗閃爍的魚群從舷窗湧出，又消失在另一艘沉船的黑洞洞的艙門裡。",
  "options": [
   {
    "label": "鑽進最大的沉船船長室掘寶",
    "oxygen": 2,
    "outcome": {
     "text": "你在坍塌的船長室中撬開一張腐朽的書桌，泛著微光的青銅星盤下，壓著一隻封存完好的寶箱。",
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
    "label": "追逐那道銀鱗魚群",
    "oxygen": 1,
    "outcome": {
     "text": "你跟著閃爍的魚群穿過沉船的走廊，它們最終聚成一座旋轉的銀色風暴。你雙手一攏，捧起一把會流動的月光。",
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
    "label": "不打擾沉眠，悄然撤離",
    "oxygen": 0,
    "outcome": {
     "text": "一艘老船的船鐘突然自行敲響了一聲，沉悶而悠遠。你對著整座墓場微微欠身，安靜地退開。",
     "reward": {}
    }
   }
  ]
 },
 {
  "id": "giant_clam",
  "name": "巨型硨磲",
  "weight": 9,
  "text": "比雙人床還大的硨磲半嵌在白沙裡，虹彩殼緣微微翕動。你小心探手入內，柔軟的外套膜裹住你的手腕，將一顆渾圓的珠子輕輕推到你指間。",
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
  "name": "發光水母穹頂",
  "weight": 7,
  "text": "成千上萬只橘粉與冰藍的水母聚成穹頂，將一片沉沒的庭院罩在詭麗的柔光裡。穹頂中央，一團脫落的心臟緩緩沉降，正好落入你的掌心。",
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
  "name": "鯨落",
  "weight": 7,
  "text": "你隨一串上升的泡沫降至深淵平原，一副鯨骨靜臥在慘白的食骨蠕蟲花叢間。你遊進肋骨籠腔，指尖觸到一枚幽白髓珠，它用次聲波輕敲你的掌心。",
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
  "text": "嶙峋的巖洞內壁嵌滿沉船的碎木與人的遺物，一把把鏽劍如裝飾般排列。你在暗處發現一片幽綠的鱗，指尖剛碰上，耳邊便響起勾魂的輕笑。",
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
  "name": "獻祭石壇",
  "weight": 5,
  "branch": true,
  "intro": "六根佈滿古咒的石柱圍成一座祭壇，中央的石臺上還殘留著不知名的鱗片與鏽色。水流在這裡忽然變暖，像有什麼古老的意志正貼著你後頸打量。",
  "options": [
   {
    "label": "獻上一條漁獲，以血為契",
    "oxygen": 1,
    "outcome": {
     "text": "你把魚放在石臺上，海水瞬間沸騰，那條魚化為光點被吸入石心。一道金色的靈體從壇中游出，穿過你的胸膛——你沒有受傷，卻感覺自己被記住了。",
     "reward": {
      "fish": "altar_spirit_bream"
     }
    }
   },
   {
    "label": "供上珍貴的寶石祈願",
    "oxygen": 1,
    "outcome": {
     "text": "你取出一枚碧藍的寶石放上祭壇，石柱上的咒文次第亮起。一隻冰冷的手彷彿拍了拍你的肩膀，再低頭時，掌心多了一塊溫熱的血玉。",
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
    "label": "繞開祭壇，絕不觸碰",
    "oxygen": 0,
    "outcome": {
     "text": "你屏住呼吸從石柱外圍繞過，一條影子在你身後石臺上緩緩凝聚成形，又在你徹底遠離前無聲散去。",
     "reward": {}
    }
   }
  ]
 },
 {
  "emoji": "🕳️",
  "id": "abyss_crevice",
  "name": "深淵裂隙",
  "weight": 5,
  "branch": true,
  "intro": "海床被撕開一道泛著幽藍熒光的傷口，冷流從裂縫中湧出，貼著你面罩呼嘯而過。你懸在裂口上方，耳膜被水壓一下下攥緊——深淵深處，有什麼正用和你的心跳完全同步的節奏，緩緩搏動。",
  "options": [
   {
    "label": "向裂縫最深處下潛",
    "oxygen": 2,
    "outcome": {
     "text": "你擠進狹窄的巖縫，黑暗濃稠得幾乎要灌進肺裡。指尖摸到一塊冰涼的石頭，黑暗本身被封印其中——你帶走了深淵最深的秘密。",
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
    "label": "只在裂口邊緣採幾枚黑珠",
    "oxygen": 1,
    "outcome": {
     "text": "你不敢深入，快速撬下幾枚泛著幽藍光澤的黑珍珠，在裂縫傳出第一聲低吟前迅速退開。",
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
    "label": "放棄探索，原路返航",
    "oxygen": 0,
    "outcome": {
     "text": "裂縫深處傳來一聲悠長的、不屬於任何已知生物的嘆息。你握緊拳頭，轉身向上浮去，把那股戰慄甩在身後。",
     "reward": {}
    }
   }
  ]
 },
 {
  "id": "ancient_chart_room",
  "name": "遠古海圖密室",
  "weight": 5,
  "text": "你撞進一艘沉船的艦長室，整面牆上嵌著巨大的星圖與海圖，羊皮紙被冰封在透明晶體內。你撬開一隻鯊皮匣，寒氣與墨香一起湧出。",
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
  "name": "失落的鐘樓",
  "weight": 5,
  "text": "斜插在沙中的哥特鐘樓沉默如碑，鍾架已朽，唯那口青銅巨鍾仍半懸著。你游上去輕推，鍾鈴發出一聲低迴的嘆息，彷彿在等你帶它離開。",
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
  "name": "龍王宮闕",
  "weight": 5,
  "branch": true,
  "intro": "珊瑚與水晶堆疊的宮闕在深海盡頭浮現，巨大的金色瞳孔正從大殿深處俯視著你。龍威如山，海水本身都在這一眼之下停止了流動。",
  "options": [
   {
    "label": "趁龍王闔眼，拔取一片龍鱗",
    "oxygen": 3,
    "outcome": {
     "text": "你壓住心跳遊向龍尾，雙手攥住一片鱗猛然發力。龍吟炸響，整座宮殿都在顫抖，你被狂暴的暗流甩出殿外——但手中死死攥著那片金光。",
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
    "label": "恭敬俯首，受龍王一賜",
    "oxygen": 1,
    "outcome": {
     "text": "你在大殿中央單膝跪下，龍瞳微眯，一顆帶著虹彩的珍珠緩緩漂到你面前。龍王什麼也沒說，但你清楚：這一禮值千鈞。",
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
     "text": "你恭恭敬敬叩首三次，殿內的威壓竟如潮水般退去。一條溫暖的海流輕輕推著你原路返回，像龍尾慈祥地掃過你的背脊。",
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
ITEMS.update(json.loads(r"""{"abyss_night_stone": {"id": "abyss_night_stone", "name": "永夜石", "type": "treasure", "description": "從深淵裂隙最深處撬下的黑石，內部封存著一團從未見過光的純粹黑暗，凝視過久會聽見自己的心跳越來越慢。", "value": 650, "sellable": true}, "star_astrolabe": {"id": "star_astrolabe", "name": "船長的星盤", "type": "treasure", "description": "沉船船長手中緊握的青銅星盤，即使深埋海底仍在微微發燙，指標固執地指向一個早已沉沒的故鄉。", "value": 500, "sellable": true}, "vault_golden_chest": {"id": "vault_golden_chest", "name": "深海秘金匣", "type": "treasure", "description": "從海底寶庫扛出的沉重金匣，鎖孔被珊瑚封死，搖晃時能聽見裡面金幣與某種更古老的硬物碰撞的迴響。", "value": 800, "sellable": true}, "dragon_eye_pearl": {"id": "dragon_eye_pearl", "name": "龍瞳珍珠", "type": "treasure", "description": "龍王寶座上脫落的明珠，表面流轉著虹彩，凝視它時瞳孔深處會有一道金色豎瞳一掠而過。", "value": 950, "sellable": true}}"""))
FISH.update(json.loads(r"""{"crevice_blind_eel": {"id": "crevice_blind_eel", "name": "裂淵盲鰻", "rarity": "epic", "description": "深淵裂隙獨有的無眼掠食者，皮膚半透明，能看見體內幽藍的消化液如星雲般緩緩旋轉。", "size_min": 45, "size_max": 80, "size_unit": "cm", "base_value": 260, "tags": ["underwater", "deepsea", "shadow"], "dive": true, "latin": "Abyssoanguis anophthalmus", "capture_feel": "它纏上手腕的瞬間像一條冰冷的絲綢，但你能感到它的飢餓正順著血管往上攀爬，癢得鑽心。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "silverflash_fish": {"id": "silverflash_fish", "name": "銀鱗閃魚", "rarity": "rare", "description": "成群結隊穿過沉船縫隙的小型魚，鱗片反射的光芒能把整座腐朽的船艙照亮如白晝。", "size_min": 15, "size_max": 25, "size_unit": "cm", "base_value": 120, "tags": ["underwater", "shoal", "shipwreck"], "dive": true, "latin": "Argentimicris naufragus", "capture_feel": "雙手捧起時整群魚在掌間炸開一片碎銀般的閃光，像抓住了一把會流動的月光。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "altar_spirit_bream": {"id": "altar_spirit_bream", "name": "壇靈鯛", "rarity": "legendary", "description": "只在接受獻祭後從石壇中游出的靈體魚，半透明的身體內漂浮著金色古咒文，遊動時身後拖拽一縷不絕的梵音。", "size_min": 30, "size_max": 45, "size_unit": "cm", "base_value": 400, "tags": ["underwater", "spirit", "altar"], "dive": true, "latin": "Sacrificium aurora", "capture_feel": "指尖觸到的不是鱗片，而是一陣溫暖的呢喃，那條魚穿過你的手掌，卻在你心口留下一枚看不見的印記。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}, "scale_guardian": {"id": "scale_guardian", "name": "鱗甲守衛", "rarity": "legendary", "description": "長期浸泡在龍王氣息中的變異魚，渾身覆蓋著龍鱗般的硬甲，遊動時鰭刃破開水流，如一道移動的刀陣。", "size_min": 70, "size_max": 120, "size_unit": "cm", "base_value": 500, "tags": ["underwater", "dragon", "armored"], "dive": true, "latin": "Squamatocustos draconis", "capture_feel": "雙手抱住它的瞬間，鱗甲倒豎，掌心被數十片微小的利刃同時割開，疼得你幾乎鬆手——但它終於不再掙扎。", "branch_only": true, "locations": ["all"], "seasons": ["all"]}}"""))
_DIVE_ENC_BY_ID = {e["id"]: e for e in DIVE_ENCOUNTERS}
_DIVE_BRANCH_IDS = {e["id"] for e in DIVE_ENCOUNTERS if e.get("branch")}   # 大遺蹟：觸發即暫停做抉擇


_SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".", "fishing_save.json")
_IO_WARN = ""   # 存檔讀/寫出問題時的一次性提示；cmd() 會把它貼在輸出末尾，不再靜默吞掉

def _new_state(seed=_DEFAULT_SEED):
    seed = int(seed) & 0xFFFFFFFF
    return {"version": 1, "seed": seed, "rngState": seed, "rngCalls": 0, "turn": 0,
            "season_id": "spring", "season_length": 20, "season_started_turn": 0,
            "points": 200, "location_id": "moonlit_pond", "unlocked_locations": ["moonlit_pond", "reed_river"],
            "bait_inventory": {"basic_worm": 5}, "catch_inventory": [], "items": {}, "pending_chests": [], "seen_letters": {},
            "encyclopedia": {}, "stats": {"total_casts": 0, "total_caught": 0, "total_chests": 0, "total_dives": 0}, "local_dry": 0,
            "fever": 0, "free_bait": 0,    # 幸運事件掛的 buff：剩餘翻倍竿數 / 剩餘免餌竿數
            "oxygen": 0, "oxygen_ever": False,   # 潛水：氧氣瓶庫存 / 是否買過氧氣瓶（買過才顯示水下待發現）
            "dive_unlocked": [], "map_fragments": {}}   # 已解鎖潛水的地點 / 各地點已集藏寶圖碎片數

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
            # 存檔存在卻讀不出/損壞：別靜默丟檔——備份一份再開新局，並提示玩家
            try: os.replace(_SAVE, _SAVE + ".corrupt")
            except Exception: pass
            S = _new_state()
            _IO_WARN = "⚠️ 存檔讀取失敗（%s）：已把壞檔備份為 %s，並開了一局新的。" % (e, os.path.basename(_SAVE) + ".corrupt")
    else:
        S = _new_state()   # 首次執行，找不到存檔是正常的，不提示
    S.setdefault("items", {}); S.setdefault("pending_chests", []); S.setdefault("seen_letters", {}); S.setdefault("local_dry", 0)
    S.setdefault("fever", 0); S.setdefault("free_bait", 0)
    S.setdefault("oxygen", 0); S.setdefault("oxygen_ever", False)
    S.setdefault("map_fragments", {})
    if "dive_unlocked" not in S:   # 老存檔相容：已釣到過水下魚的地點視為已解鎖，不鎖老玩家
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
        # 寫不進去（目錄只讀/沒許可權/磁碟滿）：別讓玩家以為存上了
        _IO_WARN = "⚠️ 存檔寫入失敗（%s）：本局進度可能不會被儲存，檢查一下目錄許可權/磁碟空間。" % e

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
        return "🍃 %s季結束，已進入%s季——某些魚群離開了這片水域，也有新的魚群正等著被發現。\n" % (old, nxt["name"])
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
        p = rng.rint(rw["points_range"][0], rw["points_range"][1]); S["points"] += p; parts.append("+%d點" % p)
    for b in rw.get("bait", []):
        S["bait_inventory"][b["id"]] = S["bait_inventory"].get(b["id"], 0) + b["qty"]; parts.append("%s×%d" % (BAITS.get(b["id"], {}).get("name", b["id"]), b["qty"]))
    for it in rw.get("items", []):
        S["items"][it["id"]] = S["items"].get(it["id"], 0) + it["qty"]; parts.append("%s×%d" % (ITEMS.get(it["id"], {}).get("name", it["id"]), it["qty"]))
    if rw.get("item_pool"):   # 從池中按權重隨機得 1 件
        iid = _pick_by_weight(rng, rw["item_pool"])["id"]
        S["items"][iid] = S["items"].get(iid, 0) + 1; parts.append("%s×1" % ITEMS.get(iid, {}).get("name", iid))
    if rw.get("fish"):   # 直接獲得一條該魚種（含圖鑑；遺蹟專屬魚平時釣不到）
        gf = FISH.get(rw["fish"])
        if gf:
            gs = _roll_size(rng, gf); gv = _value(gf, gs); _gi, gfirst, _gb = _record_catch(gf, gs, gv)
            parts.append("%s%s %s%s%s" % (gf["name"], "★新發現" if gfirst else "", gs, gf["size_unit"], _milestone_line(gf, gfirst)))
    if rw.get("oxygen"):
        S["oxygen"] = S.get("oxygen", 0) + rw["oxygen"]; S["oxygen_ever"] = True; parts.append("氧氣瓶×%d" % rw["oxygen"])
    if rw.get("chest"):   # 得到一隻待開寶箱（event_id 在 EVENTS 或 DIVE_EVENTS）
        S["stats"]["total_chests"] = S["stats"].get("total_chests", 0) + 1
        cuid = "ch_%03d" % S["stats"]["total_chests"]
        S["pending_chests"].append({"chest_uid": cuid, "event_id": rw["chest"]})
        cname = (EVENTS.get(rw["chest"]) or DIVE_EVENTS.get(rw["chest"]) or {}).get("name", "寶箱")
        parts.append("%s（待開，open %s）" % (cname, cuid))
    if rw.get("fragment") or rw.get("map"):   # 藏寶圖碎片 / 稀有完整藏寶圖（直接解鎖一個潛水點）
        locked = [lid for lid in LOCATIONS if not _dive_unlocked(lid)]
        if not locked:                         # 潛水點全解鎖了，折成點數
            p = 180 if rw.get("map") else 60; S["points"] += p; parts.append("+%d點" % p)
        elif rw.get("map"):
            lid = locked[rng.rint(0, len(locked) - 1)]
            S.setdefault("dive_unlocked", []).append(lid); S.get("map_fragments", {}).pop(lid, None)
            parts.append("🗺️✨完整藏寶圖→直接解鎖【%s】潛水點" % LOCATIONS[lid]["name"])
        else:                                  # 碎片：優先當前地點（若鎖），否則隨機未解鎖地點
            lid = S["location_id"] if S["location_id"] in locked else locked[rng.rint(0, len(locked) - 1)]
            fr = S.setdefault("map_fragments", {}); fr[lid] = fr.get(lid, 0) + rw["fragment"]
            need = _dive_frags_needed(LOCATIONS[lid]); nm = LOCATIONS[lid]["name"]
            if fr[lid] >= need:
                fr[lid] = 0
                if lid not in S.setdefault("dive_unlocked", []): S["dive_unlocked"].append(lid)
                parts.append("🗺️集齊【%s】藏寶圖→解鎖潛水點" % nm)
            else:
                parts.append("🧩%s藏寶圖碎片(%d/%d)" % (nm, fr[lid], need))
    return parts
def _letter_exhausted(e):
    return bool(e.get("unique")) and len(S["seen_letters"].get(e["id"], [])) >= len(e.get("messages", []))
def _resolve_event(rng):
    lst = [e for e in EVENTS.values() if e["type"] != "junk" and not _letter_exhausted(e)]
    if not lst: return "水面晃了晃，又歸於平靜。\n%s" % _footer()
    ev = _pick_by_weight(rng, lst)
    if ev["type"] == "chest":
        S["stats"]["total_chests"] += 1
        uid = "ch_%03d" % S["stats"]["total_chests"]
        S["pending_chests"].append({"chest_uid": uid, "event_id": ev["id"]})
        return "📦 %s！%s\n（用 open %s 開啟）\n%s" % (ev["name"], ev["description"], uid, _footer())
    if ev["type"] == "bottle" and ev.get("unique") and ev.get("messages"):
        seen = S["seen_letters"].setdefault(ev["id"], [])
        avail = [i for i in range(len(ev["messages"])) if i not in seen]
        idx = avail[rng.rint(0, len(avail) - 1)]
        seen.append(idx)
        parts = _grant_rewards(rng, ev.get("rewards"))
        return "📜 %s！%s\n%s\n★ 收到新的一封！（已收集 %d/%d，用 encyclopedia 回看）%s\n%s" % (ev["name"], ev["description"], ev["messages"][idx], len(seen), len(ev["messages"]), ("\n獲得 " + "、".join(parts)) if parts else "", _footer())
    msg = ""
    if ev["type"] == "bottle" and ev.get("messages"):
        msg = "\n" + ev["messages"][rng.rint(0, len(ev["messages"]) - 1)]
    parts = _grant_rewards(rng, ev.get("rewards"))
    icon = "📜" if ev["type"] == "bottle" else "✨"
    return "%s %s！%s%s%s\n%s" % (icon, ev["name"], ev["description"], msg, ("\n獲得 " + "、".join(parts)) if parts else "", _footer())
def _c_open(uid):
    idx = next((i for i, c in enumerate(S["pending_chests"]) if c["chest_uid"] == uid), -1)
    if idx < 0: return "沒有這個待開的寶箱：%s。（inventory 裡看待開寶箱）" % uid
    eid = S["pending_chests"][idx]["event_id"]
    ev = EVENTS.get(eid) or DIVE_EVENTS.get(eid)   # 水面寶箱 + 水下寶庫一併查
    if not ev:
        S["pending_chests"].pop(idx); return "寶箱 %s 資料缺失，已丟棄。" % uid
    rng = _Rng(S["rngState"], S["rngCalls"])
    lock = ev.get("lock")
    if lock:
        if lock.get("requires_item") and S["items"].get(lock["requires_item"], 0) > 0:
            S["items"][lock["requires_item"]] = S["items"].get(lock["requires_item"], 0) - 1
        elif lock.get("or_points") is not None and S["points"] >= lock["or_points"]:
            S["points"] -= lock["or_points"]
        else:
            need = " 或 ".join([x for x in [(ITEMS.get(lock["requires_item"], {}).get("name", lock["requires_item"]) if lock.get("requires_item") else ""), ("%d點" % lock["or_points"]) if lock.get("or_points") is not None else ""] if x])
            return "%s 打不開：需要 %s（都不夠）。寶箱先留著。" % (uid, need)
    S["pending_chests"].pop(idx)
    parts = _grant_rewards(rng, _pick_by_weight(rng, ev["loot_table"])["reward"]) if ev.get("loot_table") else _grant_rewards(rng, ev.get("rewards"))
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    return "🗝 開啟了 %s！%s\n%s" % (ev["name"], ("獲得 " + "、".join(parts)) if parts else "裡面空空如也…", _footer())

_JUNK = ["一隻灌滿水的破靴子", "半截生鏽的罐頭", "一團纏死的舊魚線", "一塊被水磨圓的碎瓷片", "鄰居家漂走的塑膠小鴨"]
def _rar(k): return RARITY[k]["label"] + " " + RARITY[k]["tag"]
def _sloc(): return LOCATIONS[S["location_id"]]["name"] + " · " + SEASONS[S["season_id"]]["name"]
def _footer(): return "點數 %d ｜ %s ｜ 回合 %d ｜ 圖鑑 %d/%d" % (S["points"], _sloc(), S["turn"], len(S["encyclopedia"]), len(FISH))

# 緊湊狀態列：每次 cmd() 末尾附一行機讀 JSON，省得 AI 再 call status（也省 token）。關鍵資訊為主，不堆雜項。
def _state_json():
    bait = {b: n for b, n in S["bait_inventory"].items() if n > 0}
    j = {"pts": S["points"], "loc": LOCATIONS[S["location_id"]]["name"], "sea": SEASONS[S["season_id"]]["name"],
         "turn": S["turn"], "enc": "%d/%d" % (len(S["encyclopedia"]), len(FISH)),
         "bait": bait, "hold": len(S["catch_inventory"])}   # hold=未賣漁獲條數
    if S.get("pending_chests"): j["chest"] = len(S["pending_chests"])
    if S.get("oxygen", 0) > 0: j["oxygen"] = S["oxygen"]         # 氧氣瓶（dive 用）
    if S.get("fever", 0) > 0: j["fever"] = S["fever"]            # 剩餘翻倍竿數
    if S.get("free_bait", 0) > 0: j["free_bait"] = S["free_bait"]  # 剩餘免餌竿數
    lid = S["location_id"]   # 本地潛水點：未解鎖則示意藏寶圖碎片進度
    if not _dive_unlocked(lid):
        have = S.get("map_fragments", {}).get(lid, 0)
        if have > 0: j["map_frag"] = "%d/%d" % (have, _dive_frags_needed(LOCATIONS[lid]))
    return "📊 " + json.dumps(j, ensure_ascii=False)
# 某地點當季還有幾種沒見過的魚：normal=常規(常見~史詩)、legend=傳說/神話(單列、可遇不可求)。
# 傳說/神話只算這地"專屬"的（排除 locations:["all"] 的全域神話，免得每個釣點都被頂高、也免湊不滿常規牆）。
def _undiscovered_here(loc_id, sea_id):
    normal = legend = 0
    for f in FISH.values():
        if f.get("dive") or not _eligible(f, loc_id, sea_id) or f["id"] in S["encyclopedia"]: continue
        if f["rarity"] in ("legendary", "mythic"):
            if "all" not in f["locations"]: legend += 1
        else:
            normal += 1
    return normal, legend
# 某地點當季「水下」還有幾種沒見過的魚（只數 dive 魚）；買過氧氣瓶才對玩家顯示
def _undiscovered_dive(loc_id, sea_id):
    return sum(1 for f in FISH.values() if f.get("dive") and not f.get("branch_only") and _eligible(f, loc_id, sea_id) and f["id"] not in S["encyclopedia"])

def _c_status():
    baits = "、".join("%s×%d" % (BAITS[b]["name"], n) for b, n in S["bait_inventory"].items() if n > 0) or "（沒餌了，去 shop 買）"
    extra = ""
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items: extra += "\n物品：" + "、".join("%s×%d" % (ITEMS.get(k, {}).get("name", k), n) for k, n in items)
    if S.get("pending_chests"): extra += "\n📦 待開寶箱 %d 個（inventory 看，open 開）" % len(S["pending_chests"])
    frags = [(k, v) for k, v in S.get("map_fragments", {}).items() if v > 0 and not _dive_unlocked(k)]
    if frags: extra += "\n🧩 藏寶圖碎片：" + "、".join("%s %d/%d" % (LOCATIONS[k]["name"], v, _dive_frags_needed(LOCATIONS[k])) for k, v in frags)
    if S.get("dive_unlocked"): extra += "\n🗺️ 已解鎖潛水點：" + "、".join(LOCATIONS[l]["name"] for l in S["dive_unlocked"] if l in LOCATIONS)
    air = ("\n氧氣瓶：%d（dive 潛水捕魚用）" % S.get("oxygen", 0)) if (S.get("oxygen", 0) > 0 or S.get("oxygen_ever")) else ""
    return "【狀態】%s\n魚餌：%s%s\n未賣漁獲：%d 條 ｜ 總拋竿 %d%s" % (_footer(), baits, air, len(S["catch_inventory"]), S["stats"]["total_casts"], extra)
def _c_shop():
    lines = ["%s　%s　%d點　%s" % (b["id"], b["name"], b["cost"], ("（有偏好加成，見 look）" if (b["effects"].get("tag_weight_mult") or b["effects"].get("rarity_weight_mult")) else "無特殊效果")) for b in BAITS.values()]
    dive_open = bool(S.get("dive_unlocked"))   # 解鎖第一個潛水點後，氧氣瓶才上架（潛水是後期玩法）
    if dive_open:
        lines.append("%s　%s　%d點　%s" % (OXYGEN["id"], OXYGEN["name"], OXYGEN["cost"], "潛水用（一瓶潛一次，dive 下水）｜套餐：買 5 瓶 8 折、10 瓶 7 折｜多帶幾瓶，才夠應對深處大遺蹟的抉擇"))
    tail = "\n老闆搓了搓手：「好餌能讓這片水裡本來就有的魚更肯上鉤、更容易出稀有貨——可它變不出新魚種。想釣沒見過的魚，得換個水域、換個季節去尋。」"
    tail += "\n「想要水下那些上不了岸的稀客？買幾瓶氧氣，dive 潛下去。」" if dive_open else "\n「氧氣瓶？等你拼出第一張藏寶圖、找到能下水的地方，再來問我。」"
    return "【商店】（buy <id> [數量]）\n" + "\n".join(lines) + tail
def _c_buy(bait_id, qty):
    if bait_id in ("oxygen", "oxygen_tank", "氧氣瓶"):   # 氧氣瓶：潛水消耗品，單獨庫存
        if not S.get("dive_unlocked"):
            return "現在還買不了氧氣瓶——先在水面釣魚集齊藏寶圖碎片、解鎖第一個潛水點，店裡才會上架。"
        qty = max(1, int(qty))
        disc = 0.7 if qty >= 10 else (0.8 if qty >= 5 else 1.0)   # 套餐：≥5 瓶 8 折、≥10 瓶 7 折
        base = OXYGEN["cost"] * qty; cost = int(round(base * disc))
        if S["points"] < cost: return "點數不夠：%s×%d 需 %d 點%s，你只有 %d。" % (OXYGEN["name"], qty, cost, "（已含套餐折扣）" if disc < 1.0 else "", S["points"])
        S["points"] -= cost; S["oxygen"] = S.get("oxygen", 0) + qty; S["oxygen_ever"] = True
        saved = "，套餐省 %d 點" % (base - cost) if disc < 1.0 else ""
        return "買了 %s×%d，花 %d 點%s。剩 %d 點，現有氧氣瓶×%d。（用 dive 潛水）" % (OXYGEN["name"], qty, cost, saved, S["points"], S["oxygen"])
    b = BAITS.get(bait_id)
    if not b: return "沒有這種魚餌：%s。用 shop 看貨架。" % bait_id
    qty = max(1, int(qty)); cost = b["cost"] * qty
    if S["points"] < cost: return "點數不夠：%s×%d 需 %d 點，你只有 %d。" % (b["name"], qty, cost, S["points"])
    S["points"] -= cost; S["bait_inventory"][bait_id] = S["bait_inventory"].get(bait_id, 0) + qty
    return "買了 %s×%d，花 %d 點。剩 %d 點，現有 %s×%d。" % (b["name"], qty, cost, S["points"], b["name"], S["bait_inventory"][bait_id])
def _goto_list():
    def rank(l):
        return 0 if l["id"] == S["location_id"] else (1 if l["id"] in S["unlocked_locations"] else 2)
    entries = sorted(LOCATIONS.values(), key=lambda l: (rank(l), l["unlock_cost"]))
    lines = []
    for l in entries:
        cur = l["id"] == S["location_id"]; unlocked = l["id"] in S["unlocked_locations"]
        mark = "✦" if cur else ("·" if unlocked else "🔒")
        st = "【當前】" if cur else ("已解鎖" if unlocked else "%d點解鎖" % l["unlock_cost"])
        season_ok = S["season_id"] in l["available_seasons"]
        normal, legend = _undiscovered_here(l["id"], S["season_id"]) if season_ok else (0, 0)
        leg = "（+%d 傳說級）" % legend if legend > 0 else ""
        sea = "本季冷清" if not season_ok else ("本季待發現 %d 種%s" % (normal, leg) if normal > 0 else ("本季常規已集齊%s" % leg if legend > 0 else "本季已集齊"))
        dive_seg = ""
        if _dive_aware() and season_ok:
            if _dive_unlocked(l["id"]):
                dn = _undiscovered_dive(l["id"], S["season_id"])
                if dn > 0: dive_seg = "　🤿水下 %d 種待發現" % dn
            else:
                dive_seg = "　🔒潛水未解鎖(圖 %d/%d)" % (S.get("map_fragments", {}).get(l["id"], 0), _dive_frags_needed(l))
        lines.append("  %s %s　%s　—— %s · %s%s" % (mark, l["name"], l["id"], st, sea, dive_seg))
    return "【釣點】（goto <地點id> 前往；🔒 的需花點數解鎖）\n%s\n（你有 %d 點）" % ("\n".join(lines), S["points"])
def _c_goto(loc_id):
    if not loc_id: return _goto_list()   # 不帶引數 = 列出所有釣點
    loc = LOCATIONS.get(loc_id)
    if not loc: return "沒有這個地點：%s。（goto 不帶地點可看釣點清單）" % loc_id
    if loc_id not in S["unlocked_locations"]:
        if S["points"] < loc["unlock_cost"]: return "%s 還沒解鎖，需 %d 點，你只有 %d。" % (loc["name"], loc["unlock_cost"], S["points"])
        S["points"] -= loc["unlock_cost"]; S["unlocked_locations"].append(loc_id)
    S["location_id"] = loc_id; S["local_dry"] = 0
    season_ok = S["season_id"] in loc["available_seasons"]
    off = "（注意：本季節這裡沒什麼魚）" if not season_ok else ""
    char = ("\n" + loc["character"]) if loc.get("character") else ""
    normal, legend = _undiscovered_here(loc_id, S["season_id"]) if season_ok else (0, 0)
    leg_hint = "，外加 %d 種傳說級潛伏" % legend if legend > 0 else ""
    hint = "" if not season_ok else ("\n本季這裡還有 %d 種沒見過的魚%s。" % (normal, leg_hint) if normal > 0 else ("\n本季常規魚已集齊，但還有 %d 種傳說級潛伏。" % legend if legend > 0 else "\n本季這裡的常規魚你已集齊了。"))
    if _dive_aware() and season_ok:   # 接觸過潛水系統才提示水下
        if _dive_unlocked(loc_id):
            dn = _undiscovered_dive(loc_id, S["season_id"])
            if dn > 0: hint += "\n🤿 水下還有 %d 種沒見過的魚，dive 潛下去看看。" % dn
        else:
            have = S.get("map_fragments", {}).get(loc_id, 0)
            hint += "\n🔒 這裡的潛水點還沒解鎖——水面釣魚集藏寶圖碎片（已 %d/%d）拼出地圖就能潛。" % (have, _dive_frags_needed(loc))
    return "來到【%s】。%s%s%s%s" % (loc["name"], loc["description"], char, off, hint)
def _c_inv():
    out = []
    if S["catch_inventory"]:
        out.append("🐟 漁獲：\n" + "\n".join("  %s　%s　%scm　%d點" % (c["instance_id"], FISH.get(c["fish_id"], {}).get("name", c["fish_id"]), c["size"], c["value"]) for c in S["catch_inventory"]))
    items = [(k, n) for k, n in S.get("items", {}).items() if n > 0]
    if items:
        out.append("🎁 物品：\n" + "\n".join("  %s　%s×%d%s" % (k, ITEMS.get(k, {}).get("name", k), n, ("（可 sell item %s）" % k) if ITEMS.get(k, {}).get("sellable") else "") for k, n in items))
    if S.get("pending_chests"):
        out.append("📦 待開寶箱：\n" + "\n".join("  %s（open %s）" % (c["chest_uid"], c["chest_uid"]) for c in S["pending_chests"]))
    frags = [(k, v) for k, v in S.get("map_fragments", {}).items() if v > 0 and not _dive_unlocked(k)]
    if frags:
        out.append("🧩 藏寶圖碎片（集齊解鎖該地潛水）：\n" + "\n".join("  %s %d/%d" % (LOCATIONS[k]["name"], v, _dive_frags_needed(LOCATIONS[k])) for k, v in frags))
    if not out: return "漁簍空空。去 cast 拋幾竿吧。"
    return "【漁簍】（sell <例項id>/sell all/sell species <魚id>/sell item <物品id>）\n" + "\n".join(out)
def _c_sell(target):
    target = (target or "").strip()
    m = re.match(r"^item[:\s]+(.+)$", target)
    if m:
        iid = m.group(1).strip(); it = ITEMS.get(iid)
        if not it: return "沒有這種物品：%s" % iid
        if not it.get("sellable"): return "%s 不能賣。" % it["name"]
        have = S["items"].get(iid, 0)
        if have <= 0: return "你沒有 %s。" % it["name"]
        gain = it["value"] * have; S["points"] += gain; S["items"][iid] = 0
        return "賣了 %s×%d，得 %d 點。現有 %d 點。" % (it["name"], have, gain, S["points"])
    sm = re.match(r"^species[:\s]+(.+)$", target)
    if target == "all":
        sold = S["catch_inventory"]; S["catch_inventory"] = []
    elif sm:
        fid = sm.group(1).strip(); sold = [c for c in S["catch_inventory"] if c["fish_id"] == fid]; S["catch_inventory"] = [c for c in S["catch_inventory"] if c["fish_id"] != fid]
    else:
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == target), None)
        if not c: return "漁簍裡沒有這條：%s" % target
        sold = [c]; S["catch_inventory"] = [x for x in S["catch_inventory"] if x["instance_id"] != target]
    if not sold: return "沒有可賣的（%s）。" % target
    gain = sum(c["value"] for c in sold); S["points"] += gain
    out = "賣了 %d 條，得 %d 點。現有 %d 點。（圖鑑記錄保留）" % (len(sold), gain, S["points"])
    if target == "all":   # sell all 只賣魚，揹包裡若還有能賣的寶物，提示一下別漏
        treas = [(k, n) for k, n in S.get("items", {}).items() if n > 0 and ITEMS.get(k, {}).get("sellable")]
        if treas: out += "\n💎 揹包還有寶物沒賣：%s（用 sell item <物品id> 單獨賣）。" % "、".join("%s×%d" % (ITEMS[k]["name"], n) for k, n in treas)
    return out
def _c_enc():
    total = len(FISH); got = len(S["encyclopedia"]); by = {}
    for f in FISH.values():
        cur = by.get(f["rarity"], [0, 0]); cur[1] += 1
        if f["id"] in S["encyclopedia"]: cur[0] += 1
        by[f["rarity"]] = cur
    rl = "　".join("%s %d/%d" % (RARITY[k]["label"], by[k][0], by[k][1]) for k in RARITY if k in by)
    # 只列已發現的魚（不再刷一長串 ？？？）；沒發現的看上面各檔計數、按 goto「待發現」去找
    lines = ["✔ %s（%s）×%d 最大%scm" % (f["name"], _rar(f["rarity"]), S["encyclopedia"][f["id"]]["count"], S["encyclopedia"][f["id"]]["max_size"])
             for f in FISH.values() if f["id"] in S["encyclopedia"]]
    lb = ""
    for ev in EVENTS.values():
        if ev.get("unique") and ev.get("messages"):
            seen = sorted(S["seen_letters"].get(ev["id"], []))
            lb += "\n\n📜 %s %d/%d" % (ev["name"], len(seen), len(ev["messages"]))
            lb += ("\n" + "\n".join("  · %s" % ev["messages"][i] for i in seen)) if seen else "\n  （還沒收到任何一封）"
    body = "\n".join(lines) if lines else "（還沒收錄任何魚——去 cast 拋幾竿）"
    return "【圖鑑】%d/%d（只列已發現）　%s\n%s%s" % (got, total, rl, body, lb)
def _by_id_or_name(table, q):
    if q in table: return table[q]
    for v in table.values():
        if v.get("name") == q: return v
    return None
def _c_look(oid):
    f = _by_id_or_name(FISH, oid)
    if f:
        if f["id"] not in S["encyclopedia"]:
            return "？？？（%s）—— 你還沒見過它，得親手釣上來才會在圖鑑裡顯形。" % _rar(f["rarity"])
        locs = "任意水域" if "all" in f["locations"] else "、".join(LOCATIONS.get(l, {}).get("name", l) for l in f["locations"])
        seas = "全年" if "all" in f["seasons"] else "、".join(SEASONS.get(x, {}).get("name", x) for x in f["seasons"])
        latin = (" (%s)" % f["latin"]) if f.get("latin") else ""; rumor = ("\n📜 傳聞：%s" % f["rumor"]) if f.get("rumor") else ""
        cf = ("\n🫧 手感：%s" % f["capture_feel"]) if f.get("capture_feel") else ""
        diveflag = "（🤿 潛水魚，水面釣不到）" if f.get("dive") else ""
        return "%s%s（%s）%s\n%s%s%s\n體型 %s-%s%s ｜ 基礎價值 %s ｜ 出沒：%s · %s" % (f["name"], latin, _rar(f["rarity"]), diveflag, f["description"], rumor, cf, f["size_min"], f["size_max"], f["size_unit"], f["base_value"], locs, seas)
    l = _by_id_or_name(LOCATIONS, oid)
    if l: return "%s\n%s\n開放季節：%s　解鎖 %d 點" % (l["name"], l["description"], "、".join(SEASONS[x]["name"] for x in l["available_seasons"]), l["unlock_cost"])
    b = _by_id_or_name(BAITS, oid)
    if b: return "%s（%d點）\n%s" % (b["name"], b["cost"], b["description"])
    it = _by_id_or_name(ITEMS, oid)
    if it: return "%s%s\n%s" % (it["name"], ("（財寶，售價 %d 點）" % it["value"]) if it.get("sellable") else "（功能物品，不可賣）", it["description"])
    x = _by_id_or_name(SEASONS, oid)
    if x: return "%s\n%s" % (x["name"], x["description"])
    return "沒有這個物件：%s" % oid
_BITE_SOFT = ["浮標輕輕一沉——", "水面咕咚一聲，浮標沒了影——", "線微微一緊，有動靜——"]
_BITE_HARD = ["線猛地繃緊，差點脫手——！", "竿梢狠狠一彎，水花炸開——！", "一股大力往下死拽，險些握不住——！"]
def _bite_line(rng, rarity):
    pool = _BITE_HARD if rarity in ("rare", "epic", "legendary", "mythic") else _BITE_SOFT
    return pool[rng.rint(0, len(pool) - 1)]
# 選擇性詳細播報：傳說/神話=完整演出；新發現=🆕(名·稀有·尺寸·價值 + 圖鑑描述 + 🫧手感 + 首次收錄獎勵)；
# 稀有/史詩=一行 + 描寫；普通/少見=極簡一行。圖鑑描述與手感「都保留」(手感是水下魚特有)，只去掉重複的「圖鑑新發現」標籤、去掉 [例項id]。
def _format_catch(f, size, value, inst, first):
    u = f["size_unit"]; r = f["rarity"]; rl = RARITY[r]["label"]
    cf = ("\n🫧 " + f["capture_feel"]) if f.get("capture_feel") else ""   # 手感(水下魚)，與圖鑑描述並存
    flavor = f.get("description", "") + cf
    if r in ("legendary", "mythic"):   # 完整演出（👑/❖ 已夠隆重，不再加 🎉；🎉 留給圖鑑里程碑/全收集）
        top = "👑 ─── 傳 說 ─── 👑" if r == "legendary" else "✧ ────── ❖ 神 話 ❖ ────── ✧"
        nm = "（★首次收錄 +%d點）" % RARITY[r]["discovery_bonus"] if first else ""
        body = "%s · %s%s · %d點%s\n%s%s" % (f["name"], size, u, value, nm, flavor, ("\n📜 " + f["rumor"]) if f.get("rumor") else "")
        return "%s\n%s\n%s" % (top, body, top) if r == "mythic" else "%s\n%s" % (top, body)
    if first:   # 🆕 新發現：緊湊頭 + 圖鑑描述 + 🫧手感 + 首次收錄獎勵（不搶戲，🎉 留給傳說/里程碑）
        return "🆕 %s · %s · %s%s · %d點\n%s\n首次收錄 +%d點" % (f["name"], rl, size, u, value, flavor, RARITY[r]["discovery_bonus"])
    if r in ("rare", "epic"):
        return "%s %s · %s%s · %d點\n%s" % ("✦✦ 史詩" if r == "epic" else "✦ 稀有", f["name"], size, u, value, flavor)
    return "· %s%s %s%s +%d" % (f["name"], "（少見）" if r == "uncommon" else "", size, u, value)
def _ambience(loc, rng):
    # 氛圍句只在「換場景」後出一次：同一地點+季節裡反覆拋竿不再刷，換地點/季節才再出一句
    key = "%s|%s" % (S["location_id"], S["season_id"])
    if S.get("ambience_scene") == key: return ""
    S["ambience_scene"] = key
    amb = loc.get("ambience")
    if not amb: return ""
    return "\n（%s）" % amb[rng.rint(0, len(amb) - 1)]
# ⑤ 本地點當季「非傳說」魚是否已集齊（傳說/神話可遇不可求，不算進牆）
def _local_practical_cleared():
    elig = [f for f in FISH.values() if _eligible(f, S["location_id"], S["season_id"]) and f["rarity"] not in ("legendary", "mythic")]
    return bool(elig) and all(f["id"] in S["encyclopedia"] for f in elig)
# 世界內提示（不用 rng，保持三端確定性一致）
def _secret_hint():
    d = S.get("local_dry", 0)
    if d >= 8 and d % 8 == 0 and _local_practical_cleared():
        return "\n（你開始懷疑，這片水域當季或許已經沒有更多秘密了——也許該 goto 換個地方，或等季節流轉，去別處尋新魚群。）"
    return ""
# 單步拋竿：返回 dict（text + 結構化結果）。rng 由呼叫方管理生命週期，確保連釣與單竿 rng 一致。
# 記一條漁獲：進漁簍 + 更新圖鑑 + 首次發現獎勵。主釣/分裂/熱潮翻倍共用，確保編號與圖鑑一致。
def _record_catch(f, size, value):
    inst = "c_%03d" % (S["stats"]["total_caught"] + 1)
    S["catch_inventory"].append({"instance_id": inst, "fish_id": f["id"], "size": size, "value": value})
    S["stats"]["total_caught"] += 1
    first = _upd_enc(f, size, value)
    bonus = RARITY[f["rarity"]]["discovery_bonus"] if first else 0
    if bonus: S["points"] += bonus
    return inst, first, bonus
# 圖鑑里程碑播報（🎉 留給大場面）：剛收錄的這條若達成「某檔集齊 / 整十 / 全收集」就播一行
def _milestone_line(f, first):
    if not first: return ""
    got = len(S["encyclopedia"]); total = len(FISH)
    if got >= total: return "\n🎉🎉 全圖鑑收集完成！%d 種魚悉數收錄，你是這片水域的傳奇。" % total
    tier = [x for x in FISH.values() if x["rarity"] == f["rarity"]]
    if tier and all(x["id"] in S["encyclopedia"] for x in tier):
        return "\n🎉 「%s」魚已集齊！(%d 種全收錄)" % (RARITY[f["rarity"]]["label"], len(tier))
    if got % 10 == 0: return "\n🎉 圖鑑達成 %d/%d 種！" % (got, total)
    return ""

# ── 潛水點解鎖：水面釣魚集藏寶圖碎片，集齊拼成該地藏寶圖 → 解鎖這裡的潛水 ──
_FRAG_CHANCE = 0.15   # 水面釣到魚時、本地潛水未解鎖，額外撈到一塊碎片的機率
def _dive_unlocked(loc_id): return loc_id in S.get("dive_unlocked", [])
def _dive_aware(): return bool(S.get("oxygen_ever") or S.get("dive_unlocked") or S.get("map_fragments"))
def _dive_frags_needed(loc):   # 越深/越貴的水域，藏寶圖越難拼（3~5 塊）
    c = loc["unlock_cost"]
    return 3 if c <= 200 else (4 if c <= 480 else 5)
def _gain_fragment(loc_id):
    fr = S.setdefault("map_fragments", {}); fr[loc_id] = fr.get(loc_id, 0) + 1
    need = _dive_frags_needed(LOCATIONS[loc_id]); name = LOCATIONS[loc_id]["name"]
    if fr[loc_id] >= need:
        fr[loc_id] = 0
        if loc_id not in S.setdefault("dive_unlocked", []): S["dive_unlocked"].append(loc_id)
        return "\n🗺️ 集齊 %d 塊碎片，拼成了【%s】的藏寶圖——這片水域的潛水點解鎖了！（買氧氣瓶後 dive 下水）" % (need, name)
    return "\n🧩 還撈上來一塊【%s】的藏寶圖碎片！（%d/%d，集齊可解鎖這裡的潛水點）" % (name, fr[loc_id], need)

# ── 幸運隨機事件：成功釣到魚後小機率觸發，立即生效或給後續幾竿掛 buff ──
LUCK_CHANCE = 0.05          # 每條成功漁獲後觸發幸運事件的機率（水面：分裂魚鉤等；水下：小奇遇）
RUIN_CHANCE = 0.03          # 潛水時「大遺蹟」獨立觸發機率——各擲各的，不跟幸運事件搶額度
FULL_DEX_RUIN_BOOST = 3     # 全圖鑑後大遺蹟機率×倍：沒新魚可發現了，殘局轉向探遺蹟
_FEVER_CASTS = 3            # 漁獲熱潮持續竿數
_FREE_BAIT_CASTS = 3       # 河神祝福免餌竿數
_LUCK_EVENTS = [
    {"id": "split_hook", "weight": 28},
    {"id": "golden_touch", "weight": 24},
    {"id": "fever", "weight": 16},
    {"id": "river_blessing", "weight": 16},
    {"id": "tide_record", "weight": 8},
    {"id": "lucky_pearl", "weight": 8},
]
# 水下專屬幸運事件：只在潛水時進入抽取池（撞見水下奇觀、撿珍寶/寶庫）
_PEARL_TREASURES = ["coral_pearl", "gem_sapphire", "moonstone", "ambergris", "shipwreck_coin"]   # 蚌中生珠固定池（新水下遺物不進，保持水面一致）
# 潛水奇遇解析：純資料驅動（DIVE_ENCOUNTERS），獎勵交給 _grant_rewards 通用處理。加新奇觀=只加資料。
def _resolve_dive_encounter(rng, enc):
    parts = _grant_rewards(rng, enc.get("reward"))
    body = ("\n🎁 獲得 " + "、".join(parts)) if parts else ""
    return "%s ✨【%s】%s%s" % (enc.get("emoji", "🌊"), enc["name"], enc["text"], body)
def _roll_luck(rng, pool, bait_id, f, size, inst, mode="cast"):
    # 潛水：先單獨判「大遺蹟」——它有自己的機率，跟下面的幸運事件互不影響（不再共用一個 5% 名額）
    if mode == "dive":
        _full = len(S["encyclopedia"]) >= len(FISH)   # 全圖鑑後，大遺蹟更常出（殘局玩法）
        if rng.random() < RUIN_CHANCE * (FULL_DEX_RUIN_BOOST if _full else 1):
            ruins = [{"id": e["id"], "weight": e["weight"]} for e in DIVE_ENCOUNTERS if e.get("branch")]
            return "", _pick_by_weight(rng, ruins)["id"]   # 大遺蹟：不在此結算，交給遠征迴圈暫停做抉擇
    if rng.random() >= LUCK_CHANCE: return "", None
    # 潛水只出水下「小奇遇」(珊瑚宮/古遺蹟等，大遺蹟已在上面單獨判過)；水面用陸上幸運事件（分裂魚鉤/河神祝福等）
    if mode == "dive":
        events = [{"id": e["id"], "weight": e["weight"]} for e in DIVE_ENCOUNTERS if not e.get("branch")]
    else:
        events = _LUCK_EVENTS
    eid = _pick_by_weight(rng, events)["id"]
    if eid == "split_hook":   # 魚鉤一分為三：再釣上兩條
        weights = [_eff_weight(g, S["location_id"], S["season_id"], bait_id) for g in pool]
        got = []
        for _ in range(2):
            g = _wpick(rng, pool, weights); gs = _roll_size(rng, g); gv = _value(g, gs)
            gi, gfirst, _b = _record_catch(g, gs, gv)
            got.append("%s%s %s%s[%s]" % (g["name"], "★新" if gfirst else "", gs, g["size_unit"], gi))
        return "🪝✨ 分裂魚鉤！魚鉤一分為三，又拽上來兩條：" + "、".join(got), eid
    if eid == "golden_touch":   # 這條價值 ×3
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == inst), None)
        if not c: return "", None
        old = c["value"]; c["value"] = old * 3
        return "✨💰 點石成金！這條價值 ×3：%d → %d 點" % (old, c["value"]), eid
    if eid == "fever":
        S["fever"] = S.get("fever", 0) + _FEVER_CASTS
        return "🔥 漁獲熱潮！接下來釣到的 %d 條魚都會翻倍。" % _FEVER_CASTS, eid
    if eid == "river_blessing":
        if bait_id: S["bait_inventory"][bait_id] = S["bait_inventory"].get(bait_id, 0) + 1
        S["free_bait"] = S.get("free_bait", 0) + _FREE_BAIT_CASTS
        return "🌊🙏 河神的祝福！退還這一竿的餌，接下來 %d 竿不耗魚餌。" % _FREE_BAIT_CASTS, eid
    if eid == "tide_record":   # 這條直接漲到該種極限體型
        c = next((x for x in S["catch_inventory"] if x["instance_id"] == inst), None)
        if not c: return "", None
        rs = f["size_max"]; rv = _value(f, rs)
        e = S["encyclopedia"].get(f["id"])
        if e: e["max_size"] = max(e["max_size"], rs); e["total_value_earned"] += max(0, rv - c["value"])
        c["size"] = rs; c["value"] = rv
        return "🌊📏 千載難逢的漲潮！這條猛漲到極限 %s%s，價值 %d 點。" % (rs, f["size_unit"], rv), eid
    if eid == "lucky_pearl":   # 魚肚裡掏出一枚隨機財寶
        tk = _PEARL_TREASURES[rng.rint(0, len(_PEARL_TREASURES) - 1)]
        S["items"][tk] = S["items"].get(tk, 0) + 1
        return "🦪✨ 蚌中生珠！魚肚裡滾出一枚%s（可 sell item %s）。" % (ITEMS[tk]["name"], tk), eid
    enc = _DIVE_ENC_BY_ID.get(eid)   # 水下奇遇（資料驅動）
    if enc:
        if enc.get("branch"): return "", eid   # 大遺蹟：不在此結算，交給遠征迴圈暫停做抉擇
        return _resolve_dive_encounter(rng, enc), eid
    return "", None

_DIVE_JUNK = ["一截纏滿水草的爛繩", "半扇生滿藤壺的空貝殼", "一塊硌手的礁石", "一隻空了的海螺", "一團黏糊糊的水綿"]
_DIVE_BITE = ["你蹬腿下潛，眼前忽地一花——", "水壓裹住耳膜，一道影子從礁後竄出——", "屏住呼吸貼近水底，指尖觸到一片冰涼的鱗——"]
# 單步：mode="cast" 水面拋竿（耗魚餌），mode="dive" 潛水（耗氧氣瓶、不耗餌、只出水下魚）。
# 注意：水面分支的隨機抽取順序與舊版逐位一致——水下魚被 dive 過濾排除，故老存檔/水面確定性不破壞。
def _cast_step(rng, bait_id, mode="cast"):
    dive = mode == "dive"
    if dive:
        if S.get("oxygen", 0) <= 0:
            return {"text": "氧氣瓶用光了！去 shop 買氧氣瓶再潛。（沒扣回合）", "consumed": False, "kind": "no_air", "season_changed": False}
        S["oxygen"] -= 1
        bait_id = "basic_worm"   # 潛水無餌，借最樸素餌的「零加成」權重
    else:
        inv = S["bait_inventory"]
        if not bait_id:
            avail = [b for b in inv if inv[b] > 0]
            if not avail: return {"text": "沒有魚餌了！去 shop 買點餌再來。（沒扣回合）", "consumed": False, "kind": "no_bait", "season_changed": False}
            bait_id = sorted(avail, key=lambda b: BAITS[b]["cost"])[0]
        if bait_id not in BAITS: return {"text": "沒有這種魚餌：%s" % bait_id, "consumed": False, "kind": "bad_bait", "season_changed": False}
        if inv.get(bait_id, 0) <= 0: return {"text": "%s 用光了。換一種或去 shop 買。（沒扣回合）" % BAITS[bait_id]["name"], "consumed": False, "kind": "no_bait", "season_changed": False}
        if S.get("free_bait", 0) > 0: S["free_bait"] -= 1   # 河神祝福：本竿不耗餌
        else: inv[bait_id] -= 1
    bait = BAITS[bait_id]
    S["turn"] += 1
    if dive: S["stats"]["total_dives"] = S["stats"].get("total_dives", 0) + 1
    else: S["stats"]["total_casts"] += 1
    season_msg = _adv_season(); season_changed = season_msg != ""
    loc = LOCATIONS[S["location_id"]]
    # 水下不觸發漂流瓶/寶箱（那是水面浮標的事）
    event_chance = 0 if dive else ((loc.get("event_chance_base", 0.05) + bait["effects"].get("event_chance_add", 0)) if EVENTS else 0)
    if event_chance > 0 and rng.random() < event_chance:
        S["local_dry"] = S.get("local_dry", 0) + 1
        return {"text": season_msg + _resolve_event(rng) + _secret_hint(), "consumed": True, "kind": "event", "season_changed": season_changed}
    junk_chance = loc["junk_chance_base"] * (1.0 if dive else bait["effects"].get("junk_chance_mult", 1.0))
    if rng.random() < junk_chance:
        if not dive: S["local_dry"] = S.get("local_dry", 0) + 1
        if dive:
            return {"text": season_msg + "🪨 %s。空潛一次，什麼也沒摸到。%s" % (_DIVE_JUNK[rng.rint(0, len(_DIVE_JUNK) - 1)], _ambience(loc, rng)), "consumed": True, "kind": "junk", "season_changed": season_changed}
        return {"text": season_msg + "🪣 %s。空軍一竿。%s%s" % (_JUNK[rng.rint(0, len(_JUNK) - 1)], _ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "junk", "season_changed": season_changed}
    pool = [f for f in FISH.values() if _eligible(f, S["location_id"], S["season_id"]) and bool(f.get("dive")) == dive and not (dive and f.get("branch_only"))]
    if not pool:
        if not dive: S["local_dry"] = S.get("local_dry", 0) + 1
        if dive:
            return {"text": season_msg + "潛了下去，這片水域水下這個季節空蕩蕩的，什麼都沒有。%s" % _ambience(loc, rng), "consumed": True, "kind": "empty", "season_changed": season_changed}
        return {"text": season_msg + "浮標紋絲不動……這片水域這個季節什麼都沒咬鉤。%s%s" % (_ambience(loc, rng), _secret_hint()), "consumed": True, "kind": "empty", "season_changed": season_changed}
    weights = [_eff_weight(f, S["location_id"], S["season_id"], bait_id) for f in pool]
    f = _wpick(rng, pool, weights); size = _roll_size(rng, f); value = _value(f, size)
    inst, first, bonus = _record_catch(f, size, value)
    if first: S["local_dry"] = 0
    elif not dive: S["local_dry"] = S.get("local_dry", 0) + 1
    # 漁獲熱潮（上一事件掛的 buff）：本竿這條再翻一條
    fever_line = ""
    if S.get("fever", 0) > 0:
        S["fever"] -= 1
        di, dfirst, _b = _record_catch(f, size, value)
        fever_line = "\n🔥 熱潮翻倍：又得一條 %s%s（%s）" % (f["name"], "★新" if dfirst else "", di)
    _bite = (_DIVE_BITE[rng.rint(0, len(_DIVE_BITE) - 1)]) if dive else _bite_line(rng, f["rarity"])  # 仍抽一次(保持隨機流/同seed同結果)，但不再顯示咬鉤過場，省重複
    luck_line, luck_id = _roll_luck(rng, pool, bait_id, f, size, inst, mode)   # 小機率幸運事件（潛水多一組水下專屬）
    luck_seg = ("\n" + luck_line) if luck_line else ""
    frag_line = ""   # 水面釣魚集藏寶圖碎片：本地潛水未解鎖時，小機率額外撈一塊
    if not dive and not _dive_unlocked(S["location_id"]) and rng.random() < _FRAG_CHANCE:
        frag_line = _gain_fragment(S["location_id"])
    secret = "" if dive else _secret_hint()
    be = bait["effects"]   # 魚餌回饋：這條是否命中了所用餌的偏好（稀有度/標籤加成）
    pref = bool(be) and (f["rarity"] in be.get("rarity_weight_mult", {}) or any(t in be.get("tag_weight_mult", {}) for t in f.get("tags", [])))
    return {"text": season_msg + "%s%s%s%s%s%s%s" % (_format_catch(f, size, value, inst, first), _milestone_line(f, first), fever_line, luck_seg, frag_line, _ambience(loc, rng), secret),
            "consumed": True, "kind": "fish", "fish_name": f["name"], "rarity": f["rarity"], "first": first, "season_changed": season_changed, "luck": luck_id, "fever_hit": fever_line != "", "frag": frag_line != "", "pref": pref}

def _c_cast(bait_id):
    rng = _Rng(S["rngState"], S["rngCalls"])
    out = _cast_step(rng, bait_id)["text"]
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    return out

_RARITY_RANK = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "mythic": 5}
_SOLO_HINT = "\n💡 一次只釣 1 竿挺費 token——下次試 cast 10 連釣，只回 1 條彙總（配 stop=new/rare 還能釣到新種/稀有就自動停）。"
_DIVE_SOLO_HINT = "\n💡 多帶幾瓶氧氣可以連潛：dive 5（配 stop=new 釣到新種就停），省來回。"
def _cast_many(bait_id, times, stop_on):   # 僅水面拋竿（潛水走 _dive_start 遠征系統）
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
            highlights.append(r["text"]); stop_reason = "沒餌了"; break
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
            stop_reason = "發現新種" if new_hit else ("釣到稀有" if rare_hit else "遇到事件"); break
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    body = ("\n———\n".join(highlights) + "\n\n") if highlights else ""
    haul = "、".join("%s%s×%d" % (n, "★" if n in new_names else "", c) for n, c in caught.items()) or "空軍"
    head = "🎣 連釣 %d 竿%s" % (done, ("·" + stop_reason) if stop_reason else "")
    tail = "🐟 漁獲 %d：%s" % (caught_n, haul)
    if junk_n or empty_n: tail += "（空 %d）" % (junk_n + empty_n)
    bf = BAITS.get(bait_id, {}).get("effects") if bait_id else None
    if bf and pref_hits: tail += "｜🎣 %s偏好命中 %d 條" % (BAITS[bait_id]["name"], pref_hits)
    return "%s\n%s%s" % (head, body, tail)

# ── 潛水遠征：帶氧氣下水，途中觸發「大遺蹟」會暫停做抉擇(choose)，氧氣耗盡/surface 上岸出結算 ──
def _exp_render_branch(bid):
    enc = _DIVE_ENC_BY_ID[bid]; ox = S.get("oxygen", 0)
    lines = ["%s ✨【%s】%s" % (enc.get("emoji", "🌊"), enc["name"], enc["intro"]),
             "〔抉擇〕剩餘氧氣 %d 瓶 —— 用 choose <編號> 選：" % ox]
    for i, o in enumerate(enc["options"], 1):
        c = o.get("oxygen", 0); cost = "耗 %d 氧" % c if c > 0 else "免費"
        lines.append("  %d. %s（%s）%s" % (i, o["label"], cost, "" if c <= ox else "　🔒 氧氣不足"))
    return "\n".join(lines)
def _exp_run(rng):
    exp = S["expedition"]; stop = set(exp.get("stop", [])); seg = []; reason = None
    while exp["left"] > 0 and S.get("oxygen", 0) > 0:
        exp["left"] -= 1
        r = _cast_step(rng, None, "dive")
        if not r["consumed"]: break
        exp["done"] += 1
        rank = _RARITY_RANK.get(r.get("rarity", ""), 0); bid = r.get("luck")
        # 漁獲條數/新種/名單一律在結算時從庫存增量重算（分裂魚鉤/熱潮/分支魚獎勵等額外漁獲也算進去）
        if r["kind"] == "junk": exp["jn"] += 1
        elif r["kind"] == "empty": exp["en"] += 1
        if bid in _DIVE_BRANCH_IDS:   # 大遺蹟 → 暫停做抉擇
            exp["pending"] = bid; seg.append(r["text"])
            S["rngState"] = rng.state; S["rngCalls"] = rng.calls
            return ("\n———\n".join(seg) + "\n\n" if seg else "") + _exp_render_branch(bid)
        if r.get("first") or rank >= 2 or r.get("luck") or r.get("fever_hit") or r.get("frag"):
            seg.append(r["text"])
        new_hit = "new" in stop and r.get("first"); rare_hit = "rare" in stop and rank >= 2
        if new_hit or rare_hit:
            reason = "發現新種" if new_hit else "發現稀有"; break
    S["rngState"] = rng.state; S["rngCalls"] = rng.calls
    body = ("\n———\n".join(seg) + "\n\n") if seg else ""
    return body + _exp_settle(reason)
def _exp_settle(reason):   # 遠征結算：停因只在結尾說一次；新種用 ★ 標在名單裡；價值壓成一行
    exp = S.pop("expedition")
    trip = S["catch_inventory"][exp["inv0"]:]   # 本趟所有漁獲（含熱潮/分支魚獎勵的額外條）
    catch_value = sum(c["value"] for c in trip)
    enc0 = set(exp.get("enc0", []))
    new_names = {FISH.get(c["fish_id"], {}).get("name", c["fish_id"]) for c in trip if c["fish_id"] not in enc0}
    by = {}
    for c in trip:
        nm = FISH.get(c["fish_id"], {}).get("name", c["fish_id"]); by[nm] = by.get(nm, 0) + 1
    haul = "、".join("%s%s×%d" % (n, "★" if n in new_names else "", ct) for n, ct in by.items()) or "空潛"
    treasure_value = sum(ITEMS.get(k, {}).get("value", 0) * (S["items"].get(k, 0) - exp["items0"].get(k, 0)) for k in S.get("items", {}))
    extra_in = treasure_value + (S["points"] - exp["pts0"])
    oxy_spent = exp["oxy0"] - S.get("oxygen", 0); cost = oxy_spent * OXYGEN["cost"]
    income = catch_value + extra_in; net = income - cost
    head = ("🤿 遠征中止：%s" % reason) if reason else ("🤿 遠征歸來 · 氧氣耗盡" if S.get("oxygen", 0) <= 0 else "🤿 遠征歸來")
    s = "%s｜潛 %d/%d｜餘氧 %d" % (head, exp["done"], exp.get("budget", exp["done"]), S.get("oxygen", 0))
    s += "\n🐟 漁獲 %d：%s｜估值 %d點" % (len(trip), haul, catch_value)
    if extra_in: s += "｜🎁 +%d點" % extra_in
    if exp["jn"] + exp["en"]: s += "（空手 %d）" % (exp["jn"] + exp["en"])
    s += "\n💰 收益 %d − 氧氣 %d = 本趟 %+d點" % (income, cost, net)
    return s
def _dive_start(n, stop_on):
    if S.get("expedition"): return "你正在水下遠征中——先 choose <編號> 處理眼前的遺蹟，或 surface 返航。"
    loc_id = S["location_id"]
    if not _dive_unlocked(loc_id):
        loc = LOCATIONS[loc_id]; need = _dive_frags_needed(loc); have = S.get("map_fragments", {}).get(loc_id, 0)
        return "🔒 【%s】的潛水點還沒解鎖——先在水面釣魚集齊藏寶圖碎片（已 %d/%d），拼出地圖再來潛。" % (loc["name"], have, need)
    if S.get("oxygen", 0) <= 0: return "沒有氧氣瓶——去 shop 買氧氣瓶（buy oxygen）再潛。"
    n = max(1, min(20, int(n)))
    rng = _Rng(S["rngState"], S["rngCalls"])
    S["expedition"] = {"left": n, "budget": n, "pending": None, "oxy0": S["oxygen"], "pts0": S["points"],
                       "inv0": len(S["catch_inventory"]), "items0": dict(S.get("items", {})), "enc0": list(S["encyclopedia"]),
                       "done": 0, "jn": 0, "en": 0, "stop": list(stop_on or [])}
    opts = LOCATIONS[loc_id].get("dive_ambience", {}).get(S["season_id"], [])
    scene = ("🤿 " + opts[rng.rint(0, len(opts) - 1)] + "\n\n") if opts else ""
    return scene + _exp_run(rng)   # _exp_run 自己回寫 rng
def _c_choose(n):
    exp = S.get("expedition")
    if not exp or not exp.get("pending"): return "現在沒有要抉擇的遺蹟。（dive 開一趟遠征；遇到大遺蹟才用 choose）"
    enc = _DIVE_ENC_BY_ID.get(exp["pending"])
    if not enc: exp["pending"] = None; rng = _Rng(S["rngState"], S["rngCalls"]); out = "那處遺蹟已消散。\n\n" + _exp_run(rng); return out
    opts = enc["options"]
    if not (1 <= n <= len(opts)): return "選 1~%d（choose <編號>）。" % len(opts)
    o = opts[n - 1]; c = o.get("oxygen", 0)
    if c > S.get("oxygen", 0): return "氧氣不夠：「%s」要 %d 瓶，你只剩 %d。換個選項，或選返航/繞開那項。" % (o["label"], c, S.get("oxygen", 0))
    rng = _Rng(S["rngState"], S["rngCalls"])
    if c: S["oxygen"] -= c
    parts = _grant_rewards(rng, o["outcome"].get("reward"))
    txt = "〔%s〕%s" % (o["label"], o["outcome"]["text"]) + (("\n🎁 獲得 " + "、".join(parts)) if parts else "")
    exp["pending"] = None
    return txt + "\n\n" + _exp_run(rng)   # 繼續遠征
def _c_surface():
    if not S.get("expedition"): return "你不在水下。（dive 開一趟遠征）"
    S["expedition"]["pending"] = None
    return "你撥水上浮，結束這趟遠征。\n" + _exp_settle("主動返航")

_HELP = """文字釣魚遊戲（你是玩家）。用點數買魚餌→拋竿→按稀有度機率釣魚→賣魚換點數→集齊圖鑑。
指令（傳給 cmd()，大小寫不敏感）：
  cmd('status')               看點數/地點/季節/魚餌/圖鑑進度
  cmd('shop')                 看可買魚餌
  cmd('buy <餌id> [數量]')     買餌，如 cmd('buy glow_bait 2')
  cmd('cast [餌id]')          拋竿一次（不填=用最便宜可用餌）；核心動作
  cmd('cast [餌id] N')        一次連釣 N 竿（1~20），只回一個彙總，省來回
  cmd('cast N stop=rare')     連釣/連潛遇到 新種(new)/稀有(rare)/事件(event=漂流瓶·寶箱·寶物·水下奇遇) 就提前停；可逗號多選(stop=new,rare,event 遇到任一就停)
  cmd('buy oxygen [數量]')     買氧氣瓶（潛水用，一瓶潛一次；買 5 瓶 8 折、10 瓶 7 折）
  cmd('dive [帶幾瓶氧氣] [stop=..]') 開一趟潛水「遠征」：帶 N 瓶氧氣當深度預算，捕只在水下出沒的魚；途中遇「大遺蹟」會暫停讓你抉擇；氧氣耗盡/surface 上岸出遠征結算
  cmd('choose <編號>')         在大遺蹟處做抉擇（每個選項消耗不同氧氣，不夠的選不了）；不帶編號=重看選項
  cmd('surface')              主動結束當前遠征、上浮上岸
                              （潛水點要先解鎖：在該地水面釣魚/開寶箱會得到藏寶圖碎片，集齊自動拼成藏寶圖、解鎖這裡的潛水）
  cmd('goto')                 不帶引數 = 列出所有釣點（價格/本季待發現；買過氧氣瓶還顯示水下待發現）
  cmd('goto <地點id>')         前往該地點（未解鎖則花點數解鎖）
  cmd('inventory')            看漁簍 + 物品 + 待開寶箱
  cmd('sell <例項id>') | cmd('sell all') | cmd('sell species <魚id>') | cmd('sell item <物品id>')   賣魚/賣財寶換點數
  cmd('open <寶箱uid>')        開啟釣上來的寶箱（需鑰匙或點數）
  cmd('encyclopedia')         看圖鑑收集進度
  cmd('look <id或中文名>')     細看魚/地點/魚餌/季節/物品（如 cmd('look 月鱗鯉')；沒釣到的魚顯示 ？？？）
  cmd('A; B; C')              把多條指令用 ; 或換行串成一批、一次執行（最多 8 條），如 cmd('buy basic_worm 10; cast 10')、cmd('goto reed_river; cast 8 stop=new')
拋竿偶爾會遇到漂流瓶/寶箱/寶物等驚喜事件；釣到魚時也偶有幸運時刻（分裂魚鉤/漁獲熱潮/河神祝福…），可遇不可求。買氧氣瓶後可在任意釣點 dive 潛水，捕獲只有水下才有的魚種（水面拋竿釣不到）。每次返回末尾都有一行 📊 狀態列 JSON（點數/地點/季節/回合/圖鑑/餘餌/未賣漁獲；oxygen=氧氣瓶、fever=剩餘翻倍、free_bait=剩餘免餌），看它就夠、不必再單獨 status。
goto 清單會標出每個釣點當季還有幾種沒見過的魚（含單列的傳說級），照著去補圖鑑。
目標：用有限點數把圖鑑裡的魚儘量集滿（有的魚只在特定地點+季節出現）。一開始你並不知道有哪些魚——靠拋竿去發現。"""

def _drain_warn(out):
    """把待提示的存檔讀寫問題貼到輸出末尾，並清空（一次性）。保證任何返回都帶上 IO 提示。"""
    global _IO_WARN
    if _IO_WARN:
        out = out + "\n" + _IO_WARN
        _IO_WARN = ""
    return out

_BATCH_MAX = 8
def _run_one(line):
    """跑單條指令、返回結果文字（不 _load/_save、不附狀態列）。批次與單條共用；任何意外都兜成友好文字。"""
    line = (line or "").strip()
    if not line: return _HELP
    parts = line.split()
    c = parts[0].lower(); a = parts[1:]
    # 遠征進行中（水下）：只允許 choose/surface + 只讀指令，其餘先按下
    if S.get("expedition") and c not in ("choose", "ch", "surface", "up", "status", "s", "inventory", "inv", "i", "encyclopedia", "enc", "e", "look", "l", "help", "h"):
        return "你還在水下遠征中——先 choose <編號> 處理眼前的遺蹟，或 surface 返航上岸。"
    try:
        if c in ("help", "h"): return _HELP
        elif c in ("choose", "ch"):
            if a and a[0].lstrip("+").isdigit(): return _c_choose(int(a[0]))
            exp = S.get("expedition")
            return _exp_render_branch(exp["pending"]) if (exp and exp.get("pending")) else "現在沒有要抉擇的遺蹟。"
        elif c in ("surface", "up"): return _c_surface()
        elif c in ("status", "s"): return _c_status()
        elif c == "shop": return _c_shop()
        elif c == "buy":
            if len(a) > 1 and not a[1].lstrip("+").isdigit():
                return "數量得是個數字，例：buy basic_worm 2。"
            return _c_buy(a[0] if a else "", int(a[1]) if len(a) > 1 else 1)
        elif c in ("cast", "c"):
            cb = next((t for t in a if t in BAITS), None)
            ct = next((int(t) for t in a if t.isdigit()), 1)
            cs = next((t[5:].split(",") for t in a if t.startswith("stop=")), None)
            return _cast_many(cb, ct, cs)
        elif c == "dive":   # 潛水遠征：帶 N 瓶氧氣下水，遇大遺蹟暫停做抉擇。dive [帶幾瓶] [stop=...]
            dt = next((int(t) for t in a if t.isdigit()), 10)
            ds = next((t[5:].split(",") for t in a if t.startswith("stop=")), None)
            return _dive_start(dt, ds)
        elif c == "open": return _c_open(a[0] if a else "")
        elif c in ("goto", "go"): return _c_goto(a[0] if a else "")
        elif c in ("inventory", "inv", "i"): return _c_inv()
        elif c == "sell": return _c_sell(" ".join(a))
        elif c in ("encyclopedia", "enc", "e"): return _c_enc()
        elif c in ("look", "l"): return _c_look(a[0] if a else "")
        else: return "未知指令「%s」。調 cmd('help') 看詞表。" % c
    except Exception as e:
        # 公開 API 兜底：任何意外（含格式錯）都返回友好文字，絕不向呼叫方拋棧
        return "這條指令沒讀懂（%s）。看 cmd('help')，例：buy basic_worm 2 / cast 10 stop=rare。" % e

def cmd(line=""):
    """遊戲的唯一入口：傳一條文字指令，返回結果文字。任何輸入都只返回字串、不拋異常。
    可用 ; 或換行把多條指令串成一批一次執行（省來回 token），如 cmd('buy basic_worm 10; cast 10')。"""
    _load()
    raw = (line or "").strip()
    if not raw:
        return _drain_warn(_HELP + "\n" + _state_json())
    subs = [s.strip() for s in re.split(r"[;\n]+", raw) if s.strip()]   # 批次：; 或換行分隔
    if len(subs) > 1:
        run = subs[:_BATCH_MAX]
        out = "\n\n".join("▶ %s\n%s" % (s, _run_one(s)) for s in run)
        if len(subs) > _BATCH_MAX: out += "\n\n（一次最多 %d 條，多出的 %d 條已忽略）" % (_BATCH_MAX, len(subs) - _BATCH_MAX)
    else:
        out = _run_one(subs[0])
    _save()
    return _drain_warn(out + "\n" + _state_json())   # 末尾統一附一行 📊 狀態列 JSON

def new_game(seed=_DEFAULT_SEED):
    """重開一局（可指定種子，同種子+同指令完全可復現）。"""
    global S
    S = _new_state(seed); _save()
    return "已重開新局（種子 %d）。調 cmd('help') 看規則，cmd('cast') 開釣。" % S["seed"]
