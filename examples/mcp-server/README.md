# 🎣 把钓鱼引擎接成远程 MCP（Docker 部署指南）

把这个钓鱼引擎包成一个**远程 MCP server**，让 [claude.ai](https://claude.ai) 以及任何支持「自定义 MCP 连接器 / Streamable HTTP」的客户端，直接连上来玩——你的 AI 伴侣买饵、抛竿、潜水、集图鉴，进度跨对话不丢。

> 仓库主线的 `engine.py` / `fishing.py` **一行不改**。这个 example 只在外面薄薄包一层工具封装 + 给出三种联网入口，你按自己的环境挑一种即可。

---

## 成品架构

```
AI 客户端（claude.ai / Claude Desktop / 其它兼容 MCP 的工具）
   │  HTTPS
   ▼
你的入口（三选一：A. Cloudflare Tunnel ｜ B. 反代 Nginx/Caddy ｜ C. 局域网/本地）
   │
   ▼
FastMCP server  :3457  路径 /<你的密钥>      ← play_fishing / new_game 两个工具
   │
   ▼
fishing.cmd("cast 10")  ←→  fishing_save.json（挂载持久化，重启不丢进度）
```

## 文件清单

```
examples/mcp-server/
├── README.md          # 本文件
├── Dockerfile
├── compose.yaml       # 三种入口都在注释里，按需开关
├── requirements.txt
├── .gitignore
└── app/
    └── server.py      # MCP 封装（环境变量配置，无需改代码）
```

## 前置要求

- 一台能跑 Docker + Docker Compose 的机器
- （方法 A/B 需要）一个域名
- 想盲玩防剧透就用 `fishing.py`，想让模型读到鱼谱概率就用 `engine.py`

---

## 快速开始

### 1. 放引擎文件

把仓库根目录的引擎复制到 `app/` 下（盲玩与完整二选一即可，也可都放）：

```bash
cd examples/mcp-server
cp ../../fishing.py app/      # 盲玩版（推荐，防剧透）
# cp ../../engine.py app/     # 完整版（可选）
```

### 2. 设密钥 + 选引擎

先生成一串随机密钥当门禁：

```bash
openssl rand -hex 16
```

打开 `compose.yaml`，把它填进 `FISHING_PATH`（**记得保留开头的 `/`**），并按需设 `FISHING_ENGINE`：

```yaml
FISHING_PATH:   "/3f9a8c5d2e7b1a4f6c0d9e8b7a6f5e4d"   # ← 换成你刚生成的
FISHING_ENGINE: "fishing"                             # fishing=盲玩 / engine=完整
```

### 3. 起容器

```bash
docker compose up -d --build
docker compose logs -f fishing-mcp     # 看到 Uvicorn 监听 0.0.0.0:3457 就对了
```

### 4. 本机自测

```bash
# 打密钥路径：期望 HTTP 406（端点活着，只是 GET 没带 Accept 头——这是好消息，不是报错）
curl -s -o /dev/null -w "secret -> HTTP %{http_code}\n"  http://127.0.0.1:3457/<你的密钥>

# 打默认 /mcp：期望 404（说明 endpoint 已搬到密钥路径上 = 配置生效）
curl -s -o /dev/null -w "/mcp   -> HTTP %{http_code}\n"  http://127.0.0.1:3457/mcp
```

> **划重点**：`406 Not Acceptable` 代表「路径存在、只是你用 GET 且没带 `Accept: application/json, text/event-stream`」。真正代表「路径不对」的是 **404**。后面每一步都靠 **406 vs 404** 来判断通没通。

到这里后端就绪。接下来选一种入口把它接出去。

---

## 选择入口方式（三选一）

### 方法 A — Cloudflare Tunnel

适合：**有域名、想要免费 HTTPS、不想在防火墙上开端口。**

前提：你已经用 cloudflared（容器形态）跑着一条隧道。让钓鱼服务和 cloudflared **同处一个 Docker 网络**，靠容器名互访。

1. 查到 cloudflared 所在的网络名（假设它和某个已知容器同网）：
   ```bash
   docker inspect <cloudflared或同网容器> --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'
   ```
2. 编辑 `compose.yaml`：**删掉 `ports` 段**，并取消末尾 `networks` 注释、把 `name` 换成上面查到的网络名。`FISHING_HOST` 保持 `0.0.0.0`。然后 `docker compose up -d`（改了网络要重建）。
3. 在 Cloudflare 隧道里加一条 Public Hostname / 已发布应用程序路由：
   - 子域 + 域：如 `fishing` + `example.com`
   - **路径（Path）：留空**（密钥已经在后端 endpoint 里了，这里别再填，否则要求 URL 出现两次密钥，反而不匹配）
   - Service：`HTTP` → `fishing-mcp:3457`（**用容器名**，不是 `127.0.0.1`）

> ⚠️ 最常见的坑：cloudflared 容器内部的 `127.0.0.1` 指的是**它自己**，不是宿主机。所以要么像上面这样同网络用容器名，要么让钓鱼服务走 host 网络后用宿主机网关 IP（如 `172.17.0.1:3457`）。

验证（从公网打，不是容器内部）：

```bash
curl -s -o /dev/null -w "tunnel -> HTTP %{http_code}\n" https://fishing.example.com/<你的密钥>
```

`406` = 整条链路通；`530/502` = 隧道没接到后端（多半 Service 地址/端口不对）；`404` = Path 填了不该填的东西。

### 方法 B — 传统反代（Nginx / Caddy）

适合：**机器上已有反代，或想直接在 VPS 上签 HTTPS。**

把 `FISHING_HOST` 设回 `127.0.0.1`（只听本机，对外交给反代），`compose.yaml` 的 `ports` 保持 `127.0.0.1:3457:3457`。

**Nginx**（Streamable HTTP 可能走 SSE，下面几条指令缺一不可）：

```nginx
location /<你的密钥> {
    proxy_pass http://127.0.0.1:3457;   # 末尾不写路径，让 /<密钥> 原样透传给后端
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Connection "";
    proxy_buffering off;                # 流式必须关
    proxy_cache off;
    proxy_read_timeout 3600s;
    chunked_transfer_encoding on;
}
```

**Caddy**（自动 HTTPS，更短；后端只在 `/<密钥>` 上应答，其余自然 404）：

```caddy
fishing.example.com {
    reverse_proxy 127.0.0.1:3457
}
```

重载后验证：`curl -s -o /dev/null -w "%{http_code}\n" https://fishing.example.com/<你的密钥>` → `406` 即通。

### 方法 C — 纯本地 / 局域网 / Tailscale

适合：**只在内网或本机用，不出公网。**

把 `compose.yaml` 的 `ports` 改成 `"3457:3457"`（暴露给内网），客户端直接连：

```
http://<内网IP 或 Tailscale IP>:3457/<你的密钥>
```

**最轻方案（连 Docker 都不要）**：本地客户端（如 Claude Desktop）可以用 **stdio** 直接拉起脚本。把 `server.py` 末尾换成 `mcp.run(transport="stdio")`，把引擎文件和 `server.py` 放一起，然后在客户端配置里：

```json
{
  "mcpServers": {
    "fishing": {
      "command": "python",
      "args": ["/绝对路径/app/server.py"]
    }
  }
}
```

stdio 模式不需要密钥/端口/网络，进程由客户端本地启动。

---

## 在客户端里加连接器

**claude.ai**：设置 → 连接器 → 添加自定义连接器 → URL 填你的完整地址（含密钥路径）：

```
https://fishing.example.com/<你的密钥>
```

> 注意 URL **不用**再补 `/mcp`——密钥路径本身就是 endpoint。

新开一段对话、启用这个连接器，丢一句让它开钓：

> 你现在能玩钓鱼了。先 `status` 看看，再帮我连钓 10 竿、钓到稀有就停，回来跟我汇报战况。🎣

其它兼容 MCP 的客户端（Claude Desktop、各类 MCP 工具）填同一个 URL 即可；本地客户端走方法 C 的 stdio 也行。

---

## 常见坑（FAQ）

- **`406` 不是报错。** 它表示「路径存在、只是 GET 没带 `Accept` 头」。真正「路径不对」是 **404**。整个流程都靠 406 vs 404 判断。
- **`FISHING_HOST` 该填啥？** 容器间 / 隧道访问要 `0.0.0.0`；只本机反代可填 `127.0.0.1`。拿不准就用 `0.0.0.0` 配合密钥门禁 + 防火墙。
- **cloudflared 容器里的 `127.0.0.1` 是它自己**，不是宿主机。用同网络容器名（推荐），或宿主机网关 IP。
- **CF 路由的 Path 要留空。** 密钥已在 endpoint，重复填会导致不匹配。
- **改了 `server.py` 用 `docker compose restart`** 就行（代码是挂载进去的）；只有改 `Dockerfile` 或依赖才需要 `up -d --build`。
- **存档持久化**靠挂载 `./app:/app`——存档落在 `app/fishing_save.json`，重启不丢。记得 gitignore 它（本目录已带 `.gitignore`）。
- **单存档 = 所有对话共享同一局**，持续经营、跨对话不丢。想「每个客户端各玩各的」见下方进阶。

---

## 安全说明

密钥路径是这里唯一的门禁（security through obscurity）：**别把含密钥的 URL 外泄**，配合防火墙 / Fail2ban 足够个人玩。要更强的访问控制，可在反代层加 Basic Auth，或用 Cloudflare Access 给隧道加一层身份校验。

---

## 进阶（可选）

- **完整版 vs 盲玩**：`FISHING_ENGINE=engine` 让模型能读到鱼谱与概率；默认 `fishing` 把内容藏在打包数据里，模型只能靠抛竿亲手发现（远程 MCP 下模型本就读不到文件，盲玩天然成立）。
- **确定性复盘**：游戏是确定性的——`new_game(seed)` + 同一串指令序列，结果逐位可复现。想让别的模型「重走某一局」，给同样的 seed 和指令即可。
- **多会话隔离**：当前是单存档。若想让每个客户端/对话各有独立进度，需要把存档目录按会话隔离（例如为每个实例起一个独立容器+独立挂载目录，或改造存档路径按 key 分目录）。

---

## License

跟随主仓库，MIT。随便用、随便改、随便接到你和你 AI 的小日子里。🎣
