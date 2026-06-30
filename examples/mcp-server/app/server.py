"""
把「AI 文字钓鱼」引擎包成一个远程 MCP server。

任何支持「自定义 MCP 连接器 / Streamable HTTP」的客户端（claude.ai、Claude Desktop，
以及其它兼容 MCP 的工具）都能连上来玩。游戏逻辑完全来自仓库里的 engine.py / fishing.py，
这里只做一层薄薄的工具封装，不改动任何核心。

配置全部走环境变量，无需改这份代码：
  FISHING_HOST    监听地址，默认 0.0.0.0（容器间/隧道访问需要；纯本机反代可设 127.0.0.1）
  FISHING_PORT    监听端口，默认 3457
  FISHING_PATH    Streamable HTTP 的 endpoint 路径，默认 /mcp
                  强烈建议设成一长串随机值当门禁，例如 /3f9a8c...（生成： openssl rand -hex 16）
  FISHING_ENGINE  fishing = 盲玩版（防剧透，推荐） / engine = 完整版（模型可读鱼谱与概率）
"""
import os

from mcp.server.fastmcp import FastMCP

# ── 选引擎：盲玩版把内容藏在打包数据里，模型只能靠抛竿亲手发现；完整版可直接读到鱼谱/概率 ──
_ENGINE_NAME = os.getenv("FISHING_ENGINE", "fishing").strip().lower()
if _ENGINE_NAME == "engine":
    import engine as game
else:
    import fishing as game

HOST = os.getenv("FISHING_HOST", "0.0.0.0")
PORT = int(os.getenv("FISHING_PORT", "3457"))
PATH = os.getenv("FISHING_PATH", "/mcp")
if not PATH.startswith("/"):
    PATH = "/" + PATH

mcp = FastMCP(
    "fishing",
    host=HOST,
    port=PORT,
    streamable_http_path=PATH,   # 把密钥做成 endpoint 路径 = 最简单的门禁
    stateless_http=True,         # 游戏状态在存档文件里、不依赖 MCP 会话；省掉 session-id 来回，反代/隧道更省心
)


@mcp.tool()
def play_fishing(command: str) -> str:
    """文字钓鱼游戏。把一条游戏指令作为 command 传入，返回结果文字。

    常用指令：
      help / status / shop / inventory / encyclopedia
      goto                                       不带参数 = 列出所有钓点
      goto <地点id>                              前往 / 解锁钓点
      cast [饵id] [次数] [stop=new,rare,event]   抛竿；带次数=连钓 1~20 竿；stop= 遇新种/稀有/事件就提前停
      buy <饵id> [数量]                          买饵；buy oxygen 5 买氧气瓶
      dive [带几瓶] [stop=...]                   潜水远征（需先 buy oxygen）
      choose <编号> / surface                    大遗迹处抉择 / 主动上浮
      sell <实例id | all | species 鱼id | item 物品id>
      open <宝箱uid> / look <id或中文名>

    省 token 技巧：用 `cast 10` 一次连钓只回一个汇总；用 ; 或换行把多条指令串成一批一次跑
    （最多 8 条），如 'buy basic_worm 10; cast 10'、'goto reed_river; cast 8 stop=new'。
    每次返回末尾都带一行 📊 状态栏 JSON，看它即可掌握当前局面，不必反复 status。
    """
    try:
        return game.cmd(command)
    except Exception as e:  # 引擎对任何输入都安全；走到这里多半是环境/存档目录问题
        return f"⚠️ 指令执行出错：{e}。请检查指令格式，或调 play_fishing('help') 看规则。"


@mcp.tool()
def new_game(seed: int = 0) -> str:
    """重开一局并清空当前进度。

    seed=0 用默认种子；填非 0 的整数用自定义种子。本游戏是确定性的——
    同一个种子 + 同一串指令序列，结果逐位可复现（便于复盘 / 分享同一局）。
    注意：这会清掉现有存档，慎用。
    """
    try:
        return game.new_game(seed) if seed else game.new_game()
    except Exception as e:
        return f"⚠️ 重开失败：{e}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
