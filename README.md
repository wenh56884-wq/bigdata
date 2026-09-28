# 九天梧桐 AI 工作台

一个本地运行的多会话 AI 数据工作台，基于 **LangChain 1.x ReAct Agent** 构建。它既能处理日常问答、计算和知识库检索，也能安全查询本机业务库、非结构化表格与上传的数据文件。

基础能力包括：
- `calculator` —— 安全地计算数学表达式
- `get_current_time` —— 获取当前时间
- `word_count` —— 统计中文字符 / 英文词数
- `run_python` / `query_table_python` —— 在受限沙箱中进行计算与 DataFrame 分析

以及 **RAG 知识库问答**：只要在 `knowledge/` 目录放入 `.md/.txt/.pdf` 文档
（支持子目录），Agent 会自动挂载 `search_knowledge` 检索工具，可结合文档回答
产品手册 / FAQ / 内部政策等问题（详见 [4.1 知识库问答（RAG Agent）](#41-知识库问答rag-agent)）。

以及 **MySQL 业务库直查问答**：Agent 会连接本机 MySQL 的 3 个业务库
`financial_asset_management`（金融）/ `healthcare_analytics_competition`（医疗）/
`telecom_operations_db`（通信），把自然语言问题转成只读 SQL 查询真实数据后再回答
（详见 [4.2 MySQL 业务库直查（NL→SQL→执行→回复）](#42-mysql-业务库直查nl-sql-执行-回复)）。

以及基于 **Checkpointer 的多会话（多重对话）记忆**：每个会话一个 `thread_id`，
上下文互相隔离，切换回来还能接着聊，历史落盘到 SQLite 后重启也不丢。

以及基于 **Sklearn 的机器学习预测**：把三个业务库的历史数据按自然月聚合后，
用 sklearn 多模型自动选优、递归预测未来 N 个月并生成 Markdown 预测报告，
既能聊天触发也能独立脚本运行（详见 [4.3 Sklearn 机器学习预测](#43-sklearn-机器学习预测)）。

以及 **非结构化表格库**：把 `非结构化数据/` 里三份评测集的 787 张 markdown / HTML 表格解析成
SQLite（120,328 行），Agent 用只读 SQL 直接问答，并配套四张查询技能卡
（详见 [4.4 非结构化表格库](#44-非结构化表格库解析--ai-查询)）。

以及完整的 **Agent = LLM(大脑) + Planning(规划) + Tool use(执行) + Memory(记忆)** 架构：

- **LLM（大脑）**：DeepSeek / 任意 OpenAI 兼容服务，带失败冷却与备用渠道自动切换；
- **Planning（规划）**：复杂任务先由规划器（`core/planning.py`）拆成 2~6 步执行计划，模型边做边
  勾选进度（网页实时显示计划面板），终答前再自检一轮，没做完自动补做；
- **Tool use（执行）**：27 个工具（业务库 SQL 直查 / 知识库检索 / **非结构化表格查询**（含本地问题分析）/ **Python 沙箱计算** / **统计分析与自动建模** /
  出图 / 机器学习预测 / 计划 / 记忆…）；
- **Memory（记忆）**：会话内 Checkpointer + 跨会话 Store + 长会话滚动摘要三层（详见
  [3.5 Agent 架构](#35-agent-架构llm--planning--tool-use--memory)）。

## 1. 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\python -m pip install -r requirements.txt
# macOS / Linux
source .venv/bin/activate && pip install -r requirements.txt
```

## 2. 配置 API Key

复制 `.env.example` 为 `.env` 并填入你的 API Key：

```bash
cp .env.example .env       # macOS / Linux
copy .env.example .env     # Windows
```

默认走 **DeepSeek**（快且便宜）：

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-在此填入你自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat       # deepseek-reasoner 是推理版，慢一些
```

想换回 OpenAI 兼容服务，把 `LLM_PROVIDER` 改成 `openai`，再填 `OPENAI_API_KEY / BASE_URL / MODEL`：

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxxxxxxxx
BASE_URL=                   # OpenAI 官方留空；用兼容服务请填完整地址
MODEL=gpt-3.5-turbo
```

两组配置可以同时存在，切换只改 `LLM_PROVIDER` 一个值；
命令行也可以临时指定：`python -m core.agent "问题" --provider openai`。

其它可选变量：

```env
REQUEST_TIMEOUT=60   # 单次请求超时（秒），超时直接报错，避免页面一直转圈
MAX_RETRIES=1        # 失败重试次数
```

> ⚠️ **安全**：`.env` 已在 `.gitignore` 中，**务必不要**把它提交到版本控制。
> 密钥一旦泄露（比如贴到聊天记录里），请立刻去服务商后台吊销并重新生成。

### 切换到其它兼容服务

只要服务端支持 OpenAI Chat Completions 协议，就配 `LLM_PROVIDER=openai` 后改 `BASE_URL`：

```env
# DeepSeek
BASE_URL=https://api.deepseek.com
MODEL=deepseek-chat

# Moonshot(Kimi)
BASE_URL=https://api.moonshot.cn/v1
MODEL=moonshot-v1-8k

# 阿里通义（OpenAI 兼容模式）
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-plus
```

## 3. 运行

```bash
python -m core.agent                       # 跑多会话隔离 demo（两个会话互不知情）
python -m core.agent "帮我算一下 123*456"   # 临时会话跑一个问题
python -m core.agent "帮我算一下 123*456" --stream   # 流式输出（打字机效果）
```

### 多会话命令行用法

```bash
python -m core.agent --new                 # 新建会话，打印 thread_id
python -m core.agent --list                # 列出所有会话
python -m core.agent "问题" --thread <id>   # 在指定会话里继续聊（带记忆）
python -m core.agent --history <id>        # 查看某会话的完整历史
python -m core.agent --rename <id> "标题"   # 重命名
python -m core.agent --delete <id>         # 删除会话及其检查点
```

## 3.1 Web 界面（多会话）

```bash
python web.py          # 默认 http://127.0.0.1:5000
# 可用环境变量：HOST / PORT / FLASK_DEBUG
```

> 助手名称：**九天梧桐**（浏览器标签「九天梧桐 AI 工作台」，侧栏图标「梧」；
> 改名前的旧名是「文浩 AI」，改名只影响显示文案与提示词身份，接口与功能不变）。

界面采用**豆包风格**视觉（Arco 色板）：主蓝 `#165DFF` 渐变、圆形品牌 logo、侧栏浅灰
`#F7F8FA`、会话选中淡蓝底、AI 回答为浅灰圆角卡片、用户消息为蓝色渐变气泡、
输入框为 16px 大圆角白卡（聚焦蓝色描边 + 淡蓝光圈）、发送 / 停止为圆形按钮、
各类开关为胶囊；深色模式同步换肤，favicon 与界面主色保持一致。
所有视觉变量集中在 `index.html` 样式表末尾的「**豆包风格**」一段，换肤只改这一段。

界面左侧是会话列表：新建、切换、双击重命名、删除；右侧是聊天区。
每个会话对应一个独立的 `thread_id`，Checkpointer 按它隔离记忆。
输入框左下方的「数据技能卡」下拉可**手动指定**本次回答按哪个库查询
（金融资产管理库 / 医院医疗数据分析库 / 通信运营商库，默认「自动识别」由 Agent 判断）；
选择会记住（localStorage）并随每次提问生效，在“深度搜索”模式下自动禁用（深度搜索走知识库检索，不查数据库）。

AI 的回答采用 **流式输出（打字机效果）**：`/api/chat` 返回 NDJSON 事件流，
浏览器收到 `token` 事件就逐字渲染，无需等整段回答生成完。

### HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查：Checkpointer 后端（`sqlite` / `memory`）、知识库 `rag`、数据库 `database`、长期记忆 `store`、`planning`（规划模式与参数）、`memory`（三层记忆与压缩开关）、`tables`（非结构化表格库规模） |
| GET | `/api/conversations` | 会话列表（按更新时间倒序） |
| POST | `/api/conversations` | 新建会话，body 可选 `{ "title": "..." }` |
| GET | `/api/conversations/<id>/messages` | 某会话的完整历史 **+ 该会话最近的执行计划 `plan` + 最近一轮的数据来源 `sources`**（刷新页面后计划面板、数据来源照常显示） |
| PATCH | `/api/conversations/<id>` | 重命名 `{ "title": "..." }` |
| DELETE | `/api/conversations/<id>` | 删除会话 + 清除该线程的所有检查点 |
| DELETE | `/api/conversations` | **一键清空全部会话**（元数据 + 各线程检查点全部清掉；跨会话长期记忆保留），返回 `{ "cleared": n }` |
| GET | `/api/memory` | 列出 Store 里的跨会话长期记忆；带 `?q=关键词` 时按相关度检索（如 `/api/memory?q=报销 标准`） |
| DELETE | `/api/memory/<key>` | 删除某条长期记忆 |
| GET | `/api/skills` | 列出可手动选择的数据查询技能卡（key / 中文名 / 就绪状态），供前端下拉填充 |
| GET | `/api/uploads` | 列出上传文件、上传目录与自动记忆概况 |
| POST | `/api/uploads` | 上传一个或多个文件；`multipart/form-data`，字段名为 `file` |
| GET | `/api/uploads/<name>/preview` | 预览上传的表格、文档正文或图片 OCR 文本 |
| GET | `/api/uploads/<name>/content` | 返回上传图片的原始内容，用于前端预览 |
| DELETE | `/api/uploads/<name>` | 删除上传文件，并同步清理相关记忆和表格索引 |
| GET / DELETE | `/api/uploads/memory` | 查看或清除上传表格的数据卡片与问答经验 |
| POST | `/api/chat` | 流式问答，返回 NDJSON 事件流（见下） |
| POST | `/api/deep` | 深度搜索：多轮知识库检索、查漏补缺并流式返回带引用的回答 |

`/api/chat` 请求体：`{ "question": "...", "thread_id": "<可选>", "skill": "<可选>" }`，
其中 `skill` 为页面手动指定的数据技能卡（库 key 或中文别名，如 `financial_asset_management` / `医疗`）：
指定后当轮会注入“手动指定数据范围”指令，强制按该库加载技能卡与查询；留空或省略 = 自动识别库。
响应是 **每行一个 JSON 事件**（`Content-Type: application/x-ndjson`），依次可能是：

```
{"type": "thinking",  "message": "正在制定执行计划…"}      # 过程提示（复杂任务才会有）
{"type": "plan",      "goal": "…", "steps": [...], "progress": {...}}   # 本轮执行计划
{"type": "plan_step", "step": {"id": 2, "title": "…", "status": "done"}} # 计划进度变化
{"type": "token", "content": "字增量"}                    # 前端逐字拼出回答（真·流式，一个 chunk 一个事件）
{"type": "rewind", "chars": 6}                            # 撤回已吐出的 n 个字符（模型调工具前的过渡句）
{"type": "tool",  "name": "calculator"}                   # 模型开始调用某个工具
{"type": "sources","items": [{"kind": "database", "label": "MySQL 业务库 · 医疗", "name": "…", "tables": [...], "rows": 12, "sql": "…"}]}
{"type": "done",  "thread_id": "…", "answer": "完整回答", "plan": {...}, "sources": [...]} # 本轮正常结束
{"type": "error", "message": "…"}                        # 中途出错（本回合不入历史）
```

> `token` 现在是**边出边发**（原先是终答轮一次性吐整段），所以浏览器上是逐字出现的打字机效果；
> 模型若在调用工具前写了“我先查一下”这类过渡句，也会先发出来、再由 `rewind` 原样撤回。

> 事件协议**向后兼容**：简单问题不会有 `plan` / `sources` 事件，前端对不认识的事件类型直接忽略即可，
> 老版本页面不会因为多出计划事件而报错。
> 需要「一次性拿完整结果」的旧接口可自行用 `thread_id + 各 token 拼接` 实现，
> 或直接调用 `ChatService.ask()`（它内部就是复用这条流式管线）。

## 3.2 多会话是怎么实现的

- **一个会话 = 一个 `thread_id`**：调用 `agent.invoke(..., {"configurable": {"thread_id": ...}})`，
  Checkpointer 以 `thread_id` 为键存取检查点，天然隔离。
- **历史读取**：`agent.get_state({"configurable": {"thread_id": ...}}).values["messages"]`。
- **持久化**：默认 `SqliteSaver`（`data/checkpoints.sqlite3`），依赖缺失时自动退回 `MemorySaver`。
- **元数据**：标题 / 时间 / 消息数存在 `data/conversations.json`，避免为列目录加载全部消息。
- **删除**：`checkpointer.delete_thread(thread_id)` 清掉该会话的所有检查点。

```python
from agent import ChatService

service = ChatService()
conv = service.new_conversation("聊聊数学")
print(service.ask(conv["id"], "我叫小明，记住我的名字")["answer"])
print(service.ask(conv["id"], "我叫什么？")["answer"])   # 能记住
print(service.history(conv["id"]))                        # 完整历史

# 流式版：service.stream_ask() 是生成器，逐 token 产出事件
for event in service.stream_ask(conv["id"], "现在几点了？"):
    if event["type"] == "token":
        print(event["content"], end="", flush=True)
```

## 3.3 流式输出是怎么做到的（System Prompt / Dynamic Prompt）

**为什么不能直接让 `create_agent` 流式？** LangChain 1.x 的 `create_agent` 内部每个
模型节点都用 `model.invoke()`（一次性等完整回答），拿不到中间 token。因此
`ChatService.stream_ask()` 在 Agent 之外自己跑一个**绑定工具的 ReAct 循环**：

```text
系统提示(每次现渲染) + 历史 + 本轮问题
        │  model.stream() 逐 token 产出（yield token 事件）
        ▼
   有没有 tool_call？ ──有──▶ 执行工具 → 把 AI/工具消息拼回去，再来一轮
        │无
        ▼
  graph.update_state() 把“本轮新增消息”写回 Checkpointer（记忆不断层）
```

这也顺带展示了两种提示词写法的区别：

- **System Prompt**：`_BASE_PROMPT` 是写死的角色 + 工具规则，构建 Agent 时固定注入；
- **Dynamic Prompt**：`build_system_prompt()` 用同一模板，但把运行时信息
  （当前时间 / 星期几）每次问答前重新渲染成 `SystemMessage` 再发给模型——
  问“现在几点”可以直接答，信息永远新鲜。

> 注意：`create_agent` 的 `system_prompt` 参数只接受固定 `str / SystemMessage`，
> 所以动态渲染发生在流式问答的每一轮模型调用之前。

上面这条链路如今还多带了两样动态内容——**本轮执行计划**与**长会话摘要**，
它们和「当前时间」一样由 `build_system_prompt(now, plan, summary)` 现渲染，
完整流程见 [3.5 Agent 架构](#35-agent-架构llm--planning--tool-use--memory)。

## 3.4 跨会话长期记忆（LangGraph Store）

项目里其实有**两层存储**，别混淆：

| 层 | 作用域 | 载体 | 作用 |
| --- | --- | --- | --- |
| Checkpointer | 按 `thread_id` 隔离 | `data/checkpoints.sqlite3` | 保存每场对话的消息历史，会话间互不可见 |
| Store | 全局共享 | `data/memory.sqlite3`（`SqliteStore`） | 跨会话长期记忆：任意会话都能读写同一份 KV |

`create_agent(model=..., checkpointer=..., store=...)` 挂上 Store 后，模型通过三个工具使用它：

- `remember(content, kind, tags)`：用户明确说“记住：……”时把事实写入共享 Store。
  `kind` 分 `fact`（事实）/ `preference`（偏好）/ `task`（待办）/ `other`，
  `tags` 逗号分隔便于以后按相关度召回；**内容完全相同的记忆不会产生副本**，
  只会刷新时间并提升重要度（重复叮嘱不会把 Store 撑爆）；
- `recall(query)`：查长期记忆。带关键词时按相关度返回最匹配的若干条
  （中文按「字 + 双字词」重叠打分，复用 `rag.tokenize`），留空则返回最近记住的；
  结果带类型 / 标签 / 相关度 / 记录时间，并累计 `use_count`，越常用的越容易被召回；
- `forget(target)`：用户说“忘掉 / 删除某条记忆”时，按内容片段或 key 删除并如实告知。

System Prompt 里已写入记忆规则：**只有明确要求“记住”才保存；普通聊天提到个人信息不会自作主张写入**。
所以既能演示“会话隔离”（B 不知道 A 聊过什么），又能演示“跨会话共享”（A 里说“记住：我是小明”，
新建的会话 B 问“我叫什么”也能答上来）。

```python
from agent import ChatService, list_memories

svc = ChatService()
a = svc.new_conversation("会话A")
b = svc.new_conversation("会话B")   # 全新会话，Checkpointer 里没有任何上下文
print(svc.ask(a["id"], "记住：我是小明，喜欢数学。")["answer"])
print(svc.ask(b["id"], "我叫什么？我喜欢什么？")["answer"])  # 靠 Store 跨会话答上来
print(list_memories())              # 查看 Store 里存了什么
```

Web 端也提供了记忆管理接口：

```
GET    /api/memory                   列出 Store 里的全部长期记忆
GET    /api/memory?q=报销 标准        按相关度检索长期记忆
DELETE /api/memory/<key>             删除某条长期记忆
```

**第三层记忆：长会话摘要压缩（`MEM_COMPACT`）**——对话很长时（默认超过 40 条消息），
把「较早的消息」交给模型压成一段**滚动摘要**（增量更新，不是每次重算），本轮只把
「摘要 + 最近 12 条原文」发给模型：上下文长度可控、早期约定过的事仍然记得住，
而 Checkpointer 里的完整历史**一条都不会删**（界面上仍是全量对话）。
摘要落盘在 `data/memory.sqlite3` 的 `thread_digest` 命名空间里，进程重启后仍有效。
三个开关见 `.env.example` 3.3 节：`MEM_COMPACT=1` / `MEM_COMPACT_AFTER=40` / `MEM_COMPACT_KEEP=12`。
摘要生成失败时会**退回全量历史**（宁可长一点，也不丢上下文）。

## 3.5 Agent 架构：LLM + Planning + Tool use + Memory

这个 Agent 不是「一问一答 + 顺手调个工具」，而是按 **LLM(大脑) + Planning(规划) +
Tool use(执行) + Memory(记忆)** 四件套组成的闭环，代码分布在 `core/agent.py`（编排）与
`core/planning.py`（规划引擎，纯逻辑、可离线单测）两个文件里。

### 一次提问的完整链路

```text
用户提问
   │
   ├─① Memory  取该会话历史 ── 对话很长？→「滚动摘要 + 最近 N 条原文」(MEM_COMPACT)
   │
   ├─② Planning  复杂任务？→ 规划器拆成 2~6 步 (planning.make_plan)
   │         └─ 注入 System Prompt：把计划变成「执行要求」
   │         └─ 前端收到 plan 事件 → 显示计划面板
   │
   ├─③ Tool use  绑定工具的 ReAct 循环（model.stream 逐 token 产出）
   │         └─ 每完成一步调用 update_plan 勾选 → plan_step 事件 → 面板进度实时刷新
   │
   ├─④ Reflect  终答前核对计划是否真的完成 (planning.reflect)
   │         └─ 没完成 → 把自检意见作为一次性提醒注入，继续执行（最多 PLAN_MAX_REFLECT 轮）
   │
   └─⑤ 落盘  本回合消息 → Checkpointer；计划进度 → 会话元数据（刷新页面还在）
```

> 这条链路就是 `ChatService.stream_ask()`。`ChatService.ask()`（命令行 / demo 用）
> 不再单独走 `create_agent.invoke()`，而是**复用同一条链路**把 token 拼成完整回答——
> 两个入口的行为彻底一致，不会再出现「网页有计划、命令行没有」的双份逻辑。

### 四种能力分别落在哪

| 能力 | 实现 | 说明 |
| --- | --- | --- |
| **LLM（大脑）** | `build_llm()` / `resolve_provider()` / `mark_provider_failed()` | DeepSeek 与任意 OpenAI 兼容服务；首选渠道失败自动进冷却并切备用渠道重试（流式与非流式两条路都有兜底） |
| **Planning（规划）** | `core/planning.py` + `create_task_plan()` + `plan_task` / `update_plan` 工具 | 任务拆解、计划状态机、执行自检；深度搜索的「拆子问题 / 查漏补缺」也复用同一套提示词与解析 |
| **Tool use（执行）** | `TOOLS`（26 个） + 手写 ReAct 循环 | 业务库 SQL 直查 / 表结构 / 技能卡 / 词表分析 / 非结构化表格（问题分析 + 召回 + 只读 SQL）/ **受限 Python 沙箱** / **统计分析 · 异常检测 · 聚类挖掘** / 画图 / 知识库检索 / sklearn 预测 / 计划 / 记忆；带死循环检测与最多 40 轮上限 |
| **Memory（记忆）** | Checkpointer + Store + 滚动摘要 | 会话内 / 跨会话 / 长会话压缩三层，见 [3.4](#34-跨会话长期记忆langgraph-store) |

### 规划（Planning）是怎么工作的

- **什么时候才规划**：`PLAN_MODE=auto`（默认）下由 `planning.needs_plan()` 打分决定——
  「先…然后…最后」「对比 / 汇总 / 预测 / 报告」「所有 / 每个 / 三个库」等特征累计 **≥3 分**才规划，
  「1+1 等于几」「上个月收入是多少」这类简单问题得 0 分，**不会多花一次模型调用**。
  也可以 `PLAN_MODE=always`（每题都规划）或 `PLAN_MODE=off`（关闭规划，回到老行为），
  命令行临时切换：`python -m core.agent "问题" --plan always`。
- **计划长什么样**：`{"goal": "一句话目标", "steps": ["步骤一", "步骤二", …]}`，
  由规划器（LLM）产出，解析器**容错**（代码围栏、前后解释、对象/数组混写、一行一条都能认）。
- **谁来推进**：计划注入 System Prompt 后，模型在正常 ReAct 循环里边做边调用
  `update_plan(step=序号, status='done', note='产出')` 勾选；后端比对状态变化，
  实时推送 `plan_step` 事件，网页计划面板的进度条就是这样来的。
- **怎么保证真的做完**：模型不再要工具（准备给终答）时，`planning.reflect()` 会把
  「目标 + 计划 + 本轮用过的工具 + 准备给出的回答」交给自检器，返回 `finish` 或 `continue`；
  `continue` 时把自检意见作为**一次性提醒**注入下一轮继续执行——
  它不会写进对话历史，所以界面里不会凭空出现一条用户消息。
- **跨轮次延续**：一句「继续 / 下一步 / 按计划」会沿用上一轮**没跑完的计划**，不用从头再来；
  计划落盘在会话元数据里，就算**服务重启**（内存注册表清空），`restore_plan()` 也能把它捞回来接着做。
- **计划会落盘**：每次计划或进度变化都写进 `data/conversations.json` 的会话元数据里，
  刷新 / 重开页面后 `/api/conversations/<id>/messages` 会带回来，面板照常显示。
- **失败安全**：规划失败、自检失败、摘要失败一律**安静降级**（继续按老流程执行），绝不打断对话。
- **离线自测**：`python -m core.planning` 跑一遍启发式判定、容错解析、状态机与反思解析，不花 API 费用。

### 参数与开关

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `PLAN_MODE` | `auto` | `auto` 启发式判断 / `always` 每题都规划 / `off` 关闭规划 |
| `PLAN_MAX_STEPS` | `6` | 计划最多几步（1~12） |
| `PLAN_REFLECT` | `1` | 终答前是否做一次执行自检 |
| `PLAN_MAX_REFLECT` | `1` | 自检后最多再继续几轮（0~3） |
| `MEM_COMPACT` | `1` | 是否开启长会话摘要压缩 |
| `MEM_COMPACT_AFTER` | `40` | 消息超过多少条开始压缩（8~2000） |
| `MEM_COMPACT_KEEP` | `12` | 压缩后保留最近多少条原文（2~400） |

> 以上开关都是**运行时读取**的（和深度搜索的 `DEEP_*` 一致），改完环境变量重启即生效，
> 命令行 `--plan` 也走同一套开关。

## 3.6 人性化细节（说话方式与交互）

「九天梧桐」不是一台只会吐表格的报表机，也不该是话痨。这套「人性化」是**明确的规则**，
不是靠模型自由发挥——都写在 System Prompt（`core/agent.py` 的回复风格 ①~⑧）与前端（`index.html`）里：

| 维度 | 做法 |
| --- | --- |
| 说话方式 | **先给结论再给依据**；用自然口语解释数字背后的意思（涨跌、和谁比、说明什么）；需要时补一句实在的建议。**明确禁止**：复述问题、罗列“我先…然后…最后”的步骤、出现 SQL / 工具名 / “分析步骤”、把回答拆成问题拆解式小标题 |
| 人味 | 开头允许一句自然承接（“查到了”“先说结论”），**最多一句**；长期记忆里存了称呼时可以偶尔叫一次，不每次叫；结尾可给**一个**自然的下一步建议，但不每轮都问、不连问两个问题 |
| 诚实与兜底 | 数据查不到、口径有歧义、工具失败时先如实说明，再讲清按什么假设给了结果，并给可行替代方案——而不是冷冰冰报错 |
| 表情 | 只在闲聊 / 安慰 / 道谢时偶尔用一两个，正式数据结论里不用 |
| 进度文案 | 工具名→人话映射（`TOOL_LABELS`）：`execute_sql` → “正在查询业务数据库”、`search_knowledge` → “正在翻知识库文档”、`forecast_metric` → “正在跑预测模型”…；以 `tool` 事件的 `label` 字段下发，网页显示成一枚带呼吸灯的胶囊 |
| 空状态问候 | 按当前时间自动切换（凌晨 / 早上 / 上午 / 中午 / 下午 / 晚上），文案随场景变化 |
| 报错 | 不再甩 `请求失败：…`：中止 → “已经停下了，想继续或换个问法都行”；出错 → 一句人话 + **一句该怎么办**，技术细节以小字附在后面 |
| 会话标题 | `make_title()` 自动剥掉“帮我 / 请 / 麻烦”这类客套开头与结尾标点，侧栏标题更像人写的 |

> 想调整语气：改 `core/agent.py` 里 `_BASE_PROMPT` 结尾的「回复风格」段落即可（①~⑧ 条），
> 无需碰任何业务逻辑；工具进度文案改 `TOOL_LABELS`。

## 3.7 输出脱敏：个人信息不外泄（`services/sanitize.py`）

三个业务库（金融 / 医疗 / 通信）里存在姓名、手机号、证件号、住址、银行卡这类真实字段，
非结构化表格和知识库文档里也可能夹带。光靠“提示词要求模型别泄露”是不可靠的（模型的回答是
自由文本），所以这里在**服务端**统一做了一条流水线，覆盖三条出口：

```text
① 结果集预处理   execute_sql / query_tables 查到的表
                 → 列名判定 + 单元格正则双重脱敏  → 才交给模型（图表复用同一份缓存）
② 文本兜底       SSE 逐字输出（StreamSanitizer）/ 最终 answer / 深度搜索回答
                 → 再过一遍正则，拦住复述与“列名是 0/1”的通用列
③ 落盘与溯源     写回 Checkpointer 的 AI 消息、数据来源里展示的 SQL、深度搜索引用片段
```

**① 列名判定**（`classify_column`）支持英文名、驼峰、中文名三种写法，含复合列名：

| 类型 | 掩码样子 | 典型列名 |
| --- | --- | --- |
| 姓名 | 王小明 → `王**`；John Smith → `J*** S****` | `client_name`、`contact_name`、`患者姓名` |
| 手机号 | `138****5678` | `phone`、`mobile`、`联系方式` |
| 证件号 | `320102********1234` | `id_card_no`、`证件号码` |
| 邮箱 | `x***@163.com` | `email`、`电子邮箱` |
| 住址 | `北京市朝阳区******`（保留到行政区划） | `home_address`、`家庭住址` |
| 银行卡 / 账号 | `6222***********6789` | `card_no`、`银行账号` |
| 流水号 | 只留后 4 位 | `patient_id`、`保单号`、`工号` |
| 出生日期 | `1990-01-**` | `birth_date`、`出生年月` |

同构列名不会误伤：`product_name` / `file_name` / `branch_name` / `city` / `net_profit`
都保持原样。被脱敏的列会在表头加上 `（已脱敏）` 后缀，并附一句
`本结果含个人信息，姓名、手机号…已按规则脱敏展示，请勿尝试还原`——让模型知道这是脱敏结果，
避免它“顺手补一个名字”导致幻觉。

**② 流式为什么要用 `StreamSanitizer`**：`1381234|5678` 可能被切成两个 chunk，逐段正则会漏判，
所以它在末尾留出 64 字符的悬尾区，只在标点 / 空格这类**安全边界**处下刀吐字，流结束时再兜一次。

**开关**（`.env`）：`SANITIZE=1`（默认开，设 `0` 关闭）/ `SANITIZE_STRICT=1`（严格模式：证件号、
卡号、编号全遮，邮箱连带域名一起遮；标准模式则保留首尾若干位方便核对）。

> 掩码串不会再被同一套规则命中 → **幂等**，重复调用安全。改规则只需动 `services/sanitize.py`；
> 改完自检：`python -m services.sanitize`。

## 3.8 提示词工程：把「听懂」这一步提前（`prompting.py`）

NL→SQL 的错误绝大多数不是 SQL 语法错，而是**没听懂**：

| 用户说的 | 容易出错的点 |
| --- | --- |
| 「上个月营收怎么样」 | 自然月还是最近 30 天？含不含退款？ |
| 「哪款套餐最好」 | "好"是按价格、订购量还是投诉率排？ |
| 「多少客户」 | 是 `COUNT(*)` 还是 `COUNT(DISTINCT client_id)`？ |
| 「那它的趋势呢」 | "它"指上一轮那张表、那个客户还是那个指标？ |

这些歧义如果丢给 ReAct 循环去猜，模型会在反复试工具里慢慢消歧——代价是多轮无效调用，
口径还可能飘。所以这里把它**提前**到一次便宜的结构化调用（温度 0、短输出）解决。

### ① 查询意图结构化（Query Understanding）

```text
用户提问 ── worth_understanding() 本地判断（闲聊/纯算术直接跳过）
            │
            ├─ 一次 LLM 结构化调用 ──→ QuerySpec ──→ render() ──→ 注入本轮 System Prompt
            │                          改写后的完整问题 / 任务类型 / 目标数据源
            │                          指标 / 维度 / 筛选 / 排序与 TopN
            │                          时间范围落成 **具体起止日期**
            │                          已识别歧义 + 建议的默认口径
            └─ 失败（模型不可用 / 返回非 JSON / 超时）→ 返回 None，**静默降级**，不影响问答
```

注入到提示词里的样子：

```text
【查询理解（预先解析，用于对齐口径；与真实表结构冲突时，一律以真实结构为准）】
· 改写后的完整问题：2025年8月（上自然月）通信库的在售套餐按订购量排在前5的产品
· 任务类型：排名 / TopN　目标数据源：通信业务库
· 要算的指标：订购笔数 COUNT(*)
· 时间范围：上个月 → 2025-08-01 ~ 2025-08-31（按月）
· 排序与截断：按订购量降序取前 5
· 已识别歧义：卖得最好是按订购量还是按收入
· 默认口径（**回答时必须用一句话向用户说明**）：按订购笔数统计
```

关键点：**多轮追问会拿最近 6 条 history 补主语**（解决「它 / 这个 / 那…呢」的指代问题），
**默认假设会被要求写进回答**（用户看得到口径，而不是拿到一个不知道怎么算出来的数）。

### ② 两份清单式约束

原先这些经验规则散落在 `_BASE_PROMPT` 的长段落里，遵循率有限。现在收敛成两个编号清单，
作为独立区块注入 System Prompt：

- `<sql_guardrails>` 写 SQL 前必查（10 条）：先核对真实列名不计编、取值不定先 `SELECT DISTINCT` 看、计数说清去重、时间按真实日期列、排序必须写明字段与 LIMIT、`COUNT(col)` 跳过 NULL、金额两位小数、大集合先聚合、一次只想一件事、结果异常先自检。
- `<answer_discipline>` 回答前必查（6 条）：只用查到的数字、说清口径（存在歧义时点明假设）、带单位与小数位、异常要说、不多答、失败不空转。

### ③ 工具描述里的正反例（few-shot）

`execute_sql` 的 docstring 里补了三组「反例 → 正例」，覆盖最高频的三类错误：
计数忘去重、排序问题少了范围与方向、日期当字符串比较且没按自然月聚合。

**开关**：`QUND=1` 默认开启，`QUND=0` 关闭回到原行为。自检：`python -m core.prompting`。

## 3.15 统一上传目录 + Python 查表 + 自动记忆（`services/uploads.py`、`services/table_memory.py`）

管理员上传的表格、文档和图片**统一放一个目录**。表格落盘后会自动解析与学习，用户问数时由模型可用**受限 Python** 查询；文档和图片中的文字会进入资料检索范围。

```text
管理员上传 → data/uploads/（统一目录，落盘）
                ↓ 自动（无需手工步骤）
        ① 解析出「数据卡片」写进记忆      ② 重建表格索引
                ↓
用户提问 → find_table（带上记忆：表结构 + 以前怎么查的）
        → describe_table（列名）→ query_table_python（模型写 Python）
                ↓
        成功后自动沉淀「问题 → 代码」，下次相似问题直接复用
```

### ① 统一目录与上传入口

| 项 | 说明 |
| --- | --- |
| 目录 | `data/uploads/`（`UPLOAD_DIR` 可改）；表格库会连同这个目录一起扫描 |
| 接口 | `POST /api/uploads`（multipart，字段 file，可多文件）、`GET /api/uploads`、`GET /api/uploads/<name>/preview`、`DELETE /api/uploads/<name>`、`GET /api/uploads/memory` |
| 前端 | 聊天页右上角「**数据**」按钮 → 右侧面板：点击或拖拽上传、文件列表、删除、显示「已学几个文件 / 沉淀几次经验」 |
| 管理员令牌 | 设了 `ADMIN_TOKEN` 后，写操作需 `?token=` 或 `X-Admin-Token`；不设则不校验（本地工作台默认） |
| 文件安全 | 只取文件名（防目录穿越）、去非法字符但**保留中文**、同名自动改名不覆盖、`UPLOAD_MAX_MB` 限大小 |
| 支持格式 | 表格：Excel / CSV / TSV / JSON / Parquet / SQLite / XML；资料：Markdown / TXT / PDF / Word / PowerPoint；图片：PNG / JPG / WebP / TIFF（OCR） |

命令行也行：`python -m services.uploads`（列目录）、`python -m services.uploads 文件.xlsx`（看数据卡片）。

### ② 用 Python 查表（不是写 SQL）

新增工具 `query_table_python`：把表读成 **pandas DataFrame 注入为 `df`**，连同 `pd` / `np`
一起放进既有沙箱（`services/pysandbox.py`），模型写 Python 执行。

```python
query_table_python("df.groupby('学院').size().sort_values(ascending=False)", table="test")
query_table_python("result = df[df['困难等级']=='特别困难'].shape[0]")
query_table_python("df.pivot_table(index='学院', columns='困难等级', values='序号', aggfunc='count')")
```

适合 SQL 不好写的活：分组透视、多层索引、字符串清洗、时间重采样、多表合并、占比与同比环比。
安全口径与 `run_python` 一致（禁 import / open / while，循环有步数预算）。

### ③ 自动记忆与学习（两类，全自动）

| 类型 | 何时产生 | 记什么 | 怎么用 |
| --- | --- | --- | --- |
| **数据卡片** | 文件上传即生成 | 每张表的列名、类型、示例值、枚举取值（如「困难等级：一般困难/特别困难」） | `find_table` 召回时带进上下文，模型不用再猜列名 |
| **问答经验** | 每次 Python 查表**成功**后 | 用户问了什么 → 用的哪张表 → 那段代码 | 下次问到相似问题，`find_table` 会先递上「上次是这么写的」，少走弯路 |

- 存在 `data/table_memory.json`（单文件、无需额外服务、可直接查看/修改）
- 只记**成功**的经验（失败写法记下来只会误导下一次）；相同问题+相同代码只累加命中次数
- 删除文件时，卡片与相关经验一并清理
- **脱敏**：卡片里的示例值按**列名**判定后遮蔽（`姓名` 列的「张三」→「张*」），
  而「软件学院」「特别困难」这类正常取值不受影响
- 管理员可在「数据」面板看到「已学 N 个文件 / 沉淀 M 次经验」

### ④ 测试

`python eval/_test_uploads.py` —— **29 项全部通过**：落盘（中文名/同名改名）、数据卡片（大标题行跳过、
枚举取值）、记忆写入与脱敏、经验沉淀与回想、**沙箱内执行 pandas 代码**、删除连带清理、
Web 接口（上传/列表/删除/令牌）。

## 3.14 查询 Excel / CSV 表格文件（`services/spreadsheet.py`）

**核查结论**：改造前**不能**。`services/tables.py` 只解析「非结构化数据/」下三个硬编码 `.md`
里的 Markdown / HTML 表格，把 `.xlsx` / `.csv` 丢进目录实测 `build()` 得到 **0 张表**。

现在补上了：把 Excel / CSV / TSV 文件放进 `非结构化数据/`，或从网页「数据」面板上传到 `data/uploads/`，重建索引后即可用同一条链路查：

```text
文件 → spreadsheet.parse_file() → tables.build() → tables.sqlite3
     → find_table（召回）→ describe_table（列名）→ query_tables（只读 SQL）
```

| 环节 | 实现 |
| --- | --- |
| 支持格式 | `.xlsx` / `.xlsm`（pandas + openpyxl）、`.csv` / `.tsv` / `.txt`（标准库 csv + 分隔符探测） |
| 多 sheet | 一个工作簿的每个 sheet 拆成独立一张表，表名带 sheet 名（可按 sheet 名召回） |
| 编码 | 自动探测 `utf-8-sig → gb18030 → utf-8 → big5`，Excel 导出的 GBK CSV 也能读 |
| 表头 | 首行非纯数字即当表头；否则自动生成 `col1…colN` 并把首行当数据 |
| 数值判定 | 复用 `tables` 的 `detect_numeric_columns / coerce_rows`，与 Markdown 表**同一套规则**（不会出现「Excel 算数值、CSV 算文本」的分裂） |
| 日期 | 转成 ISO 字符串（SQLite 无日期类型，文本仍可比较与 LIKE） |
| 规模保护 | `TABLE_FILE_MAX_ROWS=200000` / `TABLE_FILE_MAX_COLS=200` |
| 坏文件 | 单个文件读不动（缺依赖 / 加密 / 损坏）只记一行警告，不拖垮整次构建 |

```bash
python -m services.spreadsheet 销售明细.xlsx        # 只看解析结果，不写库
python -m services.spreadsheet 非结构化数据/         # 整个目录
python -m services.tables --rebuild                 # 解析进库（放新文件后执行）
```

旧版 `.xls` 需要 `xlrd`，未安装时**会明确提示「请另存为 .xlsx」**而不是静默跳过。

### 放新文件后怎么重建索引

Excel / CSV 放进目录后要重建一次。**服务开着也能重建**：`os.replace` 在 Windows 上会被占用拒绝，
此时自动退回「原地重建」（在库文件里 DROP 旧表再写一遍），所以不必停服务。

```bash
python -c "import sys; sys.path.insert(0,'.'); from services import tables; \
           print(tables.build(force=True, quiet=True))"
# 或：python -m services.tables --rebuild
```

### 过程中修掉的三个真问题

1. **中文表名被吃掉**：`_table_name()` 只保留 ASCII，中文文件名/中文列会退化成一串下划线，
   多个表还可能撞名。改为保留中文 + 6 位哈希后缀（`t_销售明细_xlsx_销售明细_月度销售_2df635`），
   并新增 `SCHEMA_VERSION` 让旧索引自动重建。
2. **表少时召回失灵**：IDF 是相对「库里有多少张表」算的，只放两三个 Excel 时分数天然低于
   固定阈值 1.5，问什么都没结果。改成「分数 **或** 覆盖率」双判据——命中查询词越全越该留。
3. **按文件名找不到表**：文件名 / sheet 名原本不在检索文本里，问「销售明细那张表」零召回。
   现在 `search_blob` 会把文件名、sheet 名、来源文件一起纳入。

**测试**：`python eval/_test_spreadsheet.py` —— **31 项全部通过**（解析层 15 + 集成层 13
+ 行为不变性 3，离线、不连库、不调模型）；`python -m services.spreadsheet` 自检 17 项。
真实索引重建后仍是 **787 张表 / 120328 行**，既有表格问答不受影响。

## 3.11 向量数据库（Vector Database）· `services/vectordb.py`

改造前的「向量检索」其实是**内存里的一个 list**：每次进程启动把全部分块重新算一遍 embedding，
没配 `EMBEDDING_*` 就完全退化成关键词——没有落盘、没有增量、没有索引结构、重启即失效。
补上的这个模块是一个**能称得上数据库**的实现：

```text
                 ┌─ local：字级 + bigram 哈希 TF-IDF（离线、零依赖、结果可复现）
 分块文本 → 向量化 ┤
                 └─ api  ：OpenAI 兼容 /embeddings（配 EMBEDDING_BASE_URL 后自动切换）
                                    ↓
                        SQLite 落盘（ref / text / meta / dim / backend / float32 BLOB）
                                    ↓
                     内存索引：IDF 重算 → 低于阈值走精确余弦，超过则建 IVF 倒排索引
                     （KMeans 粗量化 + nprobe 只搜最近若干簇；候选过少自动退回精确解）
```

| 维度 | 实现 |
| --- | --- |
| 持久化 | 向量以 float32 BLOB 存 SQLite（`app/data/vector.sqlite3`），重启直接加载；单 Sqlite 无需额外服务 |
| 两种向量化 | `local`（默认，哈希 bigram TF-IDF，离线）/ `api`（真语义 embedding，需配 `EMBEDDING_BASE_URL`） |
| ANN 索引 | 规模 <`VECTOR_IVF_MIN` 用精确余弦；大于则构建 **IVF**（KMeans + `nprobe`），候选不足自动回退，保证不漏召回 |
| IDF 处理 | 库里存**不含 IDF** 的原始 TF 向量，加载时按当前语料重算 IDF——新增文档不会让旧向量「过期」 |
| 操作 | `upsert / upsert_many / sync / search / delete / prune / clear / stats`，全部带 `RLock` 线程安全 |
| 元数据过滤 | `where` 支持字典（等值 / 列表枚举）或自定义谓词 |
| 增量同步 | `sync()` 按「ref 相同 + 文本相同 + 维度/后端一致」判定未变化，只重算改动过的；`prune=True` 删掉已从知识库移除的旧向量 |
| 一致性保护 | 换后端或改维度后旧向量会被判定失效并明确报错（**而不是算出错的相似度**） |

**与 RAG 的集成**：`RagService.rebuild()` 会把分块同步进向量库（`_sync_vectordb`），
smart 模式的 RRF 融合优先使用持久化向量库（不落盘的 `_VectorIndex` 作为旧路径保留);
向量库不可用时只是**降级**为关键词 / Embedding 单路，不影响知识库可用性。

```bash
python -m services.vectordb --stats                # 看条数、维度、是否启用 IVF、体积
python -m services.vectordb --search "报销流程"     # 直接检索一次
python -m services.vectordb --selftest             # 离线自检（20 项）
python eval/_test_vectordb.py                      # 含 rag.py 集成的离线测试（41 项）
```

> 说明：本地 `local` 后端是**词法层面**的语义（类似稠密版 TF-IDF，靠字 + bigram 的
> 部分匹配获得鲁棒性），不是 Transformer 语义；想要真语义就配 `EMBEDDING_*` 切到 `api`
> 后端（切后端后需要 `python -m services.rag --rebuild` 重建一次向量库）。

## 3.12 上下文工程（Context Engineering）· `core/context.py`

Agent 的上下文做成**可测量、可裁剪**的对象，而不是一直往上堆。四层，各有一条主线：

```
① 系统提示   build_system_prompt → compose()：每块标优先级 → 跨块去重 → 超预算从低优先级块开始丢
② 工具定义   select_tools_for()：按任务阶段动态注册子集 + render_tool_guide()：一行一个（用途+参数约束）
③ 检索上下文 smart_search()：查询改写 → 相关性阈值 → 来源标注 → 按段落裁剪
④ 度量       Meter：各层字符/token、工具失败率与重复调用率 → eval/eval_context.py 出四维指标
```

### ① 系统提示：分层组织

| 做法 | 实现 |
| --- | --- |
| 优先级明确 | `PRIORITY`：时间(0) < 安全清单(10) < 角色(20) < 任务/计划(30) < 示例(40) < 记忆(50) < 提示(60)；必留块标记 `optional=False`，超预算时**只丢低优先级的可选块** |
| 正面表述 | `ANSWER_EXAMPLE` 与 `PRIORITY_RULES` 都写成"应该怎么做"：给一次合格回答的完整样例 + 冲突时的取舍顺序（真实数据 > 技能卡 > 用户要求 > 省略习惯） |
| 去除冗余 | `compose()` 按**行指纹**跨块去重（规则在两个块里重复只留一份），`last_report` 里能看到本次去掉了多少重复行、丢了哪些块 |
| 长度控制 | `CTX_BUDGET`（默认 12000，实测全量约 8.5k）作为安全上限，真超了才裁 |

### ② 工具上下文：精简（实测省 30%~74%）

```text
报销制度是怎么规定的？     8/26 个（精简 73.8%）  knowledge
医疗库上个月收入多少      12/26 个（精简 53.5%）  sql
预测未来三个月收入        14/26 个（精简 45.8%）  forecast + sql
把客户按资产和频次分个群   15/26 个（精简 40.3%）  analysis + sql
```

- **分组注册**：`TOOL_GROUPS` 按阶段（sql / tables / knowledge / post / analysis / forecast）+ `CORE_TOOLS`（核心工具永不裁）；`bind_tools(子集)`，schema 是工具上下文里最占地方的一块，裁它就对了
- **描述精炼**：`TOOL_BRIEF` 每个工具一行，写完用途顺带写参数约束（例：`execute_sql：sql 必须是 SELECT/SHOW/DESCRIBE，必备 LIMIT`）
- **兜底**：判断不出阶段就给最可能的一组；任何异常返回全量——**宁可多给也不给漏**

### ③ 检索上下文：四个环节

| 环节 | 做法 |
| --- | --- |
| 查询改写 | `rewrite_query()`：先洗掉寒暄与口水词（"请问 … 来着呢"），优先用 `QuerySpec.rewritten` |
| 相关性过滤 | `CTX_MIN_SCORE=0.15` 过滤低相关片段；**全部**不过阈就返回「证据不足」提示——**而不是硬凑内容让模型编** |
| 来源标注 | 每条带 `来源：文件名 · 第n段 · PDF 第p页 · 更新于 YYYY-MM-DD · 相关度x.xxx`（更新时间由文档 mtime 补进 metadata，帮模型判断资料是否过期） |
| 长度裁剪 | `trim_snippet()` 按句子/段落裁剪到 `CTX_SNIPPET`（默认 800），并**优先保留与查询重叠最多的一段**，不留半句话 |

### ④ 评估与迭代

```bash
python eval/eval_context.py     # 四维评估，指标不达标就 exit 1（可直接接 CI）
```

| 维度 | 评估方式 | 本次实测 |
| --- | --- | --- |
| 任务完成率 | 12 条迷你测试集，每条指定「必须可用的工具」，检查精简后是否还在 | **100%** |
| 上下文效率 | 各层字符/token 统计 + 与全量注入对比 | 工具上下文省 **49.1%**；System Prompt 约 4.4k token |
| 工具调用质量 | `Meter` 记录调用，算失败率与**成功后重复调用**率 | 有效调用率 **60%**（失败后的重试不计为质量问题） |
| 响应一致性 | 同一输入连跑 3 次，工具集与提示必须逐字节一致 | **100%** |

`CTX_STATS=1` 时每次问答的 Context 度量会追加到 `data/context_stats.jsonl`，可做跨版本对比；
`CTX=0` 可随时回到改造前的行为（纯拼接 + 全量工具），方便做 A/B 对照。

## 3.13 问答准确率评测（任务完成率）· `eval/eval_accuracy.py`

\`\`\`bash
python eval/eval_accuracy.py                    # 跑全量 50 题
python eval/eval_accuracy.py --limit 6          # 快跑（看机制是否正常）
python eval/eval_accuracy.py --json eval/_r.json   # 出报告 + JSON（含每条的回答与判定）
\`\`\`

**数据集**（`eval/qa_cases.py`，50 题分 7 类），每条标准答案**来自真实数据源**而非人工抄写：

| 类别 | 题数 | 标准答案怎么来的 |
| --- | --- | --- |
| sql-finance / sql-health / sql-telecom | 8 / 8 / 8 | 直接在对应库执行 `truth_sql` 取单值 |
| sql-hard（跨表 / Top-N / 占比 / 去重 / 阈值） | 11 | 同上，SQL 更绕、更考口径 |
| knowledge（含换说法、反向问法） | 13 | 按政策文档原话的关键内容匹配 |
| honesty（答不出来要说实话） | 1 | 正则判「有没有承认查不到」 |
| tool | 1 | 算术结果 |

**判分**：数值题支持 unit/万倍/千分位写法（写「1307.95 亿」也算对），并区分「精确到 1 位小数」与
「四舍五入到整数」两种容忍度；文本题命中任一期望关键词或正则即可通过。

**当前得分（连续两轮）**：**50/50 = 100%**（单轮约 4 分钟）。

<details>
<summary>优化过程中真实修掉的问题（点开看细节）</summary>

| 现象 | 根因 | 修法 |
| --- | --- | --- |
| 知识类一度只有 22% | 知识型问题没命中关键词 → 路由到 SQL 组 → `search_knowledge` 压根没注册，模型只能去业务库里翻政策直到放弃 | ① 用**知识库文档动态抽取**关键词（文件名+标题，换文档自适应）② 默认组兜底给 sql+knowledge ③ 提示里加「问数 vs 问制度」路由规则 |
| 「报销金额超过多少元需要二级审批」答不出 | 大文档刷榜：政策 5 块 vs SQL 示例 1036 块，靠「金额/超过」把政策挤到第 4 位 | 检索管线加**查询词覆盖率重排**（命中更多不同查询词者优先）+ **同源限流**（同一来源最多占一半名额） |
| 「2024 门诊人次」时好时坏 | 我的**题目口径本身含糊**（算不算"已取消"） | 拆成两道口径明确的题；同理给涉及状态列的聚合题统一加上「不区分状态，全部计入」 |
| 「N1 表不存在」被判错（模型其实答对了） | 判分用固定关键词（要求"没有这张表"连写） | 文本题支持**正则判分** |

</details>

## 3.9 推理与规划：CoT / ToT / MCTS / Reflexion（`core/reasoning.py`）

已有的基础：**ReAct 手写循环**（工具与思考交替，带死循环检测、40 轮上限、渠道重试）、
**Plan-and-Execute**（`core/planning.py` 的 `needs_plan` → `make_plan` → `Plan` 状态机 → `update_plan`）。
缺的是「多条候选之间的搜索与择优」和「把失败经验攒下来」。补齐后是这样一层：

```text
                     ┌── CoT：事实 / 假设 / 步骤 / 自验 / 风险 先显式化
用户提问 → needs_plan ┤
                     └── 复杂任务 → ToT 树状多路径 ─┐
                                    MCTS 规划搜索 ──┴→ 最优计划 ─→ 交给 ReAct 执行
                                                                        │
                                                        Reflexion ←─────┘（终答前自检 + 反思记忆）
```

| 能力 | 实现 | 触发时机 / 成本 |
| --- | --- | --- |
| **CoT 思维链** | `COT_RULES`（静态注入）+ `cot_think()`（显式一次调用） | 节拍规则**零调用**注入；显式推理只在 `REASON_MODE=cot` 时 |
| **ToT 思维树** | `tot_search()`：每层生成 K 条不同路线 → LLM 自评打分 → beam 剪枝保留 top ⌈K/2⌉ → 下一层细化 | 复杂任务；`TOT_BREADTH=3` / `TOT_DEPTH=2`，约 3~5 次调用 |
| **MCTS 蒙特卡洛树** | `mcts_search()`：UCB1 选择 → 扩展 2 个候选下一步 → 模拟评分 → 反向传播（`Q += r`，每上层 ×0.98 衰减） | `MCTS_ITERS=4`；每轮节点还会记下候选用于渲染 |
| **Reflexion 反思** | `Reflexion` 类：每次自检的建议入账，下次带上历史；重复建议会被加重提醒并沉淀成「经验教训」注入下轮 | 沿用 `PLAN_REFLECT` / `PLAN_MAX_REFLECT`，不新增调用 |

树搜索的**候选路线与评分**会通过 `Trail` 渲染成「推理路径」进 System Prompt：

```text
· 推理策略：Tree-of-Thoughts（树状多路径探索）
· 候选「先核对后聚合」评分 9.2（口径稳）
· 候选「直接聚合」评分 6.1（缺表结构核对）
```

**开关**（`.env`）：`REASON_MODE=auto|react|cot|tot|mcts`（auto：复杂任务才上树搜索）、
`REASON_COT=1`（CoT 节拍）、`TOT_BREADTH` / `TOT_DEPTH`、`MCTS_ITERS` / `MCTS_MAX_STEPS`。
**任何环节失败都静默降级**为单条计划或不规划——绝不打断对话。自检：`python -m core.reasoning`。

## 3.10 三级数据能力（基础查询 / 统计分析 / 自动建模）

| 级别 | 能力 | 工具 / 模块 | 说明 |
| --- | --- | --- | --- |
| **初级** | SQL 查询 | `execute_sql`、`query_tables` | 三业务库只读 SQL + 非结构化表格库 SQLite |
| **初级** | **Python 计算** | `run_python` → `services/pysandbox.py` | 见下：受限沙箱 |
| **中级** | 统计分析 · 关联 · 公式 | `analyze_data` → `services/ml_insight.py` | 自动选列 → 统计画像（均值/四分位/偏度/缺失率/变异系数）+ Pearson & Spearman 相关矩阵 + 强相关组合解读 |
| **中级** | （继续沿用）技能卡 + 查询理解 | `get_db_skill`、`analyze_query`、`prompting.QuerySpec` | 口径与业务名词错别字纠正 |
| **高级** | 时序预测 | `forecast_metric` → `services/ml_forecast.py` | 原有能力：多模型选优 + 递归滚动预测（月度指标目录） |
| **高级** | **异常检测** | `detect_data_anomalies` | z-score(3σ) / 箱线图(1.5IQR) / **孤立森林** 三口径投票，≥2 票才算异常 |
| **高级** | **聚类挖掘** | `cluster_data` | 标准化 → KMeans 在 k=2..max_k 用**轮廓系数**自动定簇 → 每簇画像（哪些特征偏高/偏低、偏离几 σ）并自动命名 |

### `run_python`：受限 Python 沙箱

```python
先用 execute_sql 查数 → 结果自动注入为 rows（行字典列表）/ cols（列名）
run_python("result = [round((r['amount']-prev)/prev, 3) for prev, r in zip(vals, vals[1:])]")
```

- ✅ 允许：四则与比较、列表/字典推导、`len/sum/sorted/round/min/max/abs/enumerate/zip…`、内置 `math` / `statistics` / `numpy(写作 np)`、`print`
- ❌ 禁止：`import`、`open`、`eval/exec编译/getattr/globals`、下划线属性（`().__class__` 那条逃逸链）、`while` 循环
- ⏱ **防跑飞**：给每个循环体插桩计数，累计 >50 万次迭代直接中止
  （特意不用「线程 + join 超时」——那杀不死线程，`while True` 会一直吃掉一个核）
- 🔒 **脱敏内置**：数据进沙箱**之前**先按列名脱一遍（`mask_rows`），模型怎么写代码都吐不出个人信息

> 定位：这是给自家 Agent 用的**护栏**，不是多租户安全边界，真正隔离要靠容器。
> 自检：`python -m services.pysandbox`

### 统计列的自动甄别

`analyze_data` / `cluster_data` 不会把 `client_id` 这种列算成「均值 400.5」——
按三条判据排除并**在结果里说明原因**：列名像 `id/code/no/status/flag/is_x`、
整数且取值几乎不重复（疑似流水号）、只有两种整数取值（二值标志位）。
**带小数的列一律视为度量直接放行**（避免误杀 `total_assets` 这类高基数的业务量）。

### 隐私一致性

四个新工具的输出都过 `sanitize`：`run_python` 在**数据源头**脱敏，`analyze_data` /
`detect_data_anomalies` / `cluster_data` 在结果渲染后脱敏；其中异常点的标签列会按**真实列名**
（`patient_name` / `birth_date`）判定，所以「李玉梅」「1935-12-03」会被遮，
而「公费医疗 / 商业保险」这类枚举值不受影响。

**离线测试**：`python eval/_test_reason_and_data.py`（55 项断言，覆盖推理层、三级数据能力、脱敏与集成，不花钱不连库）。

## 4. 添加自定义工具

```python
from langchain_core.tools import tool

@tool
def my_tool(arg: str) -> str:
    """工具描述（Agent 用来判断何时调用）。"""
    return f"你输入的是 {arg}"

# 在 core/agent.py 里把它加入 _BASE_TOOLS 列表
_BASE_TOOLS = [calculator, get_current_time, word_count, my_tool]
```

## 4.1 知识库问答（RAG Agent）

把任意文档放进项目根目录的 `knowledge/` 文件夹（支持 `.md / .markdown / .txt / .pdf`，
可建子目录分类），重启服务后 Agent 会自动挂载 `search_knowledge` 工具——
**无需改任何代码**，项目已附带 3 份示例 Markdown。直接提问即可（回答会引用来源文件，
PDF 片段还会标注页码）：

```bash
python -m core.agent "X1 咖啡机提示 E03 怎么办？"      # Agent 先检索知识库再作答
python -m core.agent "出差报销的餐饮补贴是多少？"
python -m services.rag "咖啡机怎么除垢"                     # 只测知识库检索，不调用 LLM、不花钱
python -m services.rag --list                               # 查看知识库文档 / 检索后端
```

- **Markdown 与 PDF 都能喂**：文本类整篇分块；PDF 用 `pypdf` 逐页抽取文字再分块，
  命中片段会标注 `PDF 第 N 页`，方便翻原文件核对。扫描版 PDF（纯图片、无文字层）
  抽取不到文字，系统会在 `/api/health` 的 `rag.error` 里提示先做 OCR。
- **智能检索 = 多路召回 + RRF 融合重排**：`keyword`（零依赖 TF-IDF，离线可跑）引擎**恒可用**，
  中文按“字 + 双字词”索引，对小型知识库（几十 KB~几 MB）效果已不错；`smart` 模式把可用引擎
  各自召回候选后用 RRF 融合重排取 Top-K，只有一路可用时自动退化为该路。
- **可选升级为“关键词 + 语义”双路混合**：在 `.env` 配好一组 `EMBEDDING_*`（任意 OpenAI
  兼容的 embedding 服务，如硅基流动；DeepSeek 官方不提供 embedding）后**无需改代码**，
  向量引擎自动加入、升级为真语义混合；没配 / 服务不可用则自动保持关键词单路并写明原因。
  配置方法见 `.env.example` 的 `3.1` 小节（保持注释状态 = 纯本地离线）。
- **深度搜索（Deep Research 式）**：网页勾选“深度搜索”，或命令行
  `python -m core.agent --deep "问题"`：自动拆子问题 → 逐个子查询智能检索 → 查漏补缺（第二轮）
  → LLM 重排收敛 → 带 `[1][2]…` 引用的综合回答，过程与来源实时可见。
- 进程内新增 / 修改文档后调用 `rag_service.rebuild()` 即可重建索引（重启进程也会自动重建）。
- `/api/health` 会附带 `rag` 字段，显示知识库文档数、分块数、当前引擎（keyword / vector /
  双路混合）与告警。

> 提示：知识库文档属于业务数据，默认放在 `knowledge/`（受版本管理、可随项目分发）；
> 若要改成其它目录，请在 `services/rag.py` 中调整 `KNOWLEDGE_DIR`。

### RAG 管线与方法（`services/rag.py` 实现细节）

本项目的 RAG 是「**索引离线构建 + 查询在线检索 + LLM 有据作答**」的标准管线，五步：

1. **加载（Loader）**：扫描 `knowledge/`（含子目录）中的 `.md / .markdown / .txt / .pdf`，
   单文件上限 20MB。文本类按 UTF-8 整篇读入；PDF 用 `pypdf` 逐页抽取文字，因此命中片段
   能标注 `PDF 第 N 页`。无文字层的扫描件会跳过并在 `/api/health` 提示先做 OCR。
2. **分块（Chunking）**：`chunk_text()` 先按空行把文档切成段落，**尽量保持段落完整**；
   仅当单段超过 `CHUNK_SIZE`（默认 500 字符）时才用 `_split_long()` 切成带
   `CHUNK_OVERLAP`（默认 60 字符）重叠的滑动窗口，且切点优先落在句末标点 / 空白
   （`。！？；!?;\n，,、.… `），避免把句子从中间拦腰截断，兼顾召回与语义连贯。
3. **索引（Indexing）**：对规范分块（下标全局统一、供融合共享）构建**可并存的引擎**——
   - **keyword（恒可用，零依赖、纯本地）**：自实现 `_KeywordRetriever`（继承
     `BaseRetriever`）。分词用中文友好的 `tokenize()`：英文 / 数字整词保留，
     中文段拆成「**单字 + 相邻双字词（bigram）**」；词权重用平滑
     IDF：`idf(t) = log((N+1)/(df(t)+1)) + 1`，每篇片段存「词频 × IDF」向量并预计算 L2 范数。
     零第三方依赖、零网络请求，放好文档即可离线演示。
   - **vector（可选，语义引擎）**：`.env` 里配置 `EMBEDDING_*`（任意 OpenAI 兼容的
     embedding 服务，DeepSeek 官方不提供 embedding）后自动启用：全部分块经
     `langchain_openai.OpenAIEmbeddings` 向量化，装入内置的轻量内存余弦索引
     `_VectorIndex`（无需安装 chroma / faiss）。构建失败自动降级回 keyword-only，
     并在 `summary()` / 健康检查里记录原因，不影响使用。
4. **检索（Retrieval，smart 多路融合）**：`retrieve(mode="smart")` 让每个可用引擎各自召回
   `RAG_PER_LIST`（默认 8）个候选——keyword 端用「查询向量 · 文档向量 ÷ 两范数」的余弦相似度，
   vector 端由向量索引取最近邻；再用 **RRF**（Reciprocal Rank Fusion，
   `score = Σ 1/(RAG_RRF_K + 名次)`）把多路排名融合重排，取 Top-K（`RAG_TOP_K`，默认 3）
   最相关片段，并标注相关度分数与命中的引擎。也可以 `--backend keyword / vector` 指定单路。
   （可选：`RAG_RERANK=1` 时普通 `search_knowledge` 检索后还会让 LLM 对候选做一轮相关度
   打分重排，更准但更费时，默认关闭。）
5. **注入与作答（Generation）**：命中片段按「来源文件名 · 第几段（· PDF 第几页 · 相关度）」
   拼成带引用标注的文本，作为 `search_knowledge(query)` 工具的返回值交给 Agent。
   System Prompt 约定：问题涉及知识库内容时必须先检索、基于原文作答并注明引用了哪个文件，
   **检索不到就如实说明、严禁编造**——即标准的「检索增强 + 引用溯源」，而不是把全文塞给模型。

分块 / 检索参数均可用环境变量覆盖（默认值见 `services/rag.py` 顶部）：
`RAG_CHUNK_SIZE=500`（分块目标长度）、`RAG_CHUNK_OVERLAP=60`（相邻块重叠）、
`RAG_TOP_K=3`（最终返回片段数）、`RAG_PER_LIST=8`（每路引擎的召回池大小）、
`RAG_RRF_K=60`（RRF 融合常数，越大越看重前排名次）、`RAG_RERANK=0`（是否再加 LLM 重排）；
深度搜索另有 `DEEP_PLAN_MAX / DEEP_PER_QUERY / DEEP_EVIDENCE / DEEP_ROUND2 / DEEP_RERANK`，
说明见 `.env.example` 的 `3.1` 小节。

## 4.2 MySQL 业务库直查（NL→SQL→执行→回复）

Agent 内置四个工具，用于“问数 → 查库 → 回复”：

| 工具 | 说明 |
| --- | --- |
| `get_table_schema` | 实时读取某张表 / 整个库的**真实结构**（列名、类型、主键/索引、默认值、中文字段注释），`SQL 由 LLM 依据它直接编写`，是精准生成 SQL 的主要依据 |
| `execute_sql` | 对 MySQL 执行 **只读** SQL（`SELECT / SHOW / DESCRIBE / EXPLAIN / WITH`），自动拦截写语句；裸表名唯一时自动落到所属库，`products` 等同名表或跨库查询请写 `库名.表名` |
| `list_database_tables` | 列出 3 个业务库的全部表名，供确定库名表名 |
| `get_db_skill` | 加载某库的**查询技能卡**（`skills/database/*.md`：表速览 / 字段取值口径 / 易错点 / 模板 SQL），判库后先加载再写 SQL；参数支持 `financial_asset_management` / `金融` 等中英文名，留空返回技能卡清单 |

- 覆盖 3 个业务库：`financial_asset_management`（金融）、`healthcare_analytics_competition`（医疗）、`telecom_operations_db`（通信），各 8 张表，建表时带**中文字段注释**（表结构另见 `jiso/数据表结构.xlsx`）。
- **不依赖个人知识库也能精准写 SQL**：每库配一张人工整理的**查询技能卡**（`skills/database/*.md`：
  表速览 / 字段取值口径 / 易错点 / 模板 SQL），字段与取值均对照本地 MySQL `information_schema`
  逐列核验、模板 SQL 实跑通过；Agent 判库后先由 `get_db_skill` 加载技能卡，再
  `get_table_schema` 读取真实列名与业务注释后写语句，杜绝“凭印象编造列名”；`knowledge/` 里的
  “自然语言查询转 SQL 问答.md”（三库合计 819 条样例：金融 326 / 医疗 254 / 通信 239）仅在被问到字段业务口径时作辅助参考，一旦与真实表结构
  冲突以 `get_table_schema` 为准。
- 流程：默认由模型判断问题属于哪个库；也支持在 Web 输入栏手动指定（`/api/chat` 带 `skill`），
  指定后当轮 System Prompt 注入“手动指定数据范围”强制按所选库 → `get_db_skill` 加载该库技能卡
  （业务口径 / 易错点 / 模板 SQL）→ `get_table_schema` 取真实表结构（可多表/整库，冲突以真实
  结构为准）→ 据结构精准编写 SQL → `execute_sql` 执行 → 用查询结果以中文回复用户
  （关键数字 + Markdown 表格），不编造。
- **结果可视化（Matplotlib）**：需要把查询结果“画成图 / 看走势 / 看占比”时，Agent 先用
  `execute_sql` 取数，再调用 `plot_last_result` 生成图表，并在网页对话中**直接显示图片**
  （图片经 `/reports/*.png` 提供，前端 Markdown 已支持渲染图片）。
- 连接配置：默认 `localhost:3306 / root / 123456`，可在 `.env` 用 `DB_HOST / DB_PORT / DB_USER /
  DB_PASSWORD` 覆盖（见 `.env.example` 第 4 节）。依赖 `pymysql`（已加入 requirements.txt）。
- `/api/health` 会返回 `database` 字段（`{ok, databases:[库名（N 张表）…]}`），显示三个业务库连通情况。

```bash
python -m core.agent "姓张的患者有多少人？再给 3 条姓名和手机号"
python -m core.agent "按客户类型统计金融库客户数量，从多到少"
python -m core.agent "上个月医疗总收入是多少？"
```

## 4.3 Sklearn 机器学习预测

对三个业务库的历史数据按**自然月**聚合，用 sklearn 训练预测未来月份并生成 **Markdown 预测报告**。
实现分两个文件：

- `services/ml_forecast.py` —— 核心模块：取数（按月聚合）→ 特征工程（时间趋势 + 月度季节性 + 滞后值）→
  在 `LinearRegression / Ridge / RandomForest / GradientBoosting / SVR` 中做**前向验证**
  （用最近一段月份做验证集），按验证期 RMSE 自动挑最优模型 → 全量重训并**递归滚动预测**未来 N 个月 →
  输出各月预测值 + 趋势结论，并把完整报告写入 `reports/*.md`。
- `predict.py` —— 独立运行入口（不依赖聊天服务）；内置“指标预设目录”
  （金融 / 医疗 / 通信三库各若干业务指标，key 前缀即库缩写）。

聊天触发：在 Web 或命令行里问“预测医疗库未来 3 个月的收入 / 所有库下个月趋势并出报告”即可，
Agent 会自动调用 `list_forecast_metrics` + `forecast_metric`。

```bash
python predict.py                                          # 三库各跑其默认指标，生成 3 份报告
python predict.py --db healthcare                          # 只跑医疗库默认指标（月度医疗净收入）
python predict.py --metric telecom_bill_amount --horizon 12 # 指定指标预测 12 个月
python predict.py --list                                   # 查看全部可预测指标 key
python -m services.ml_forecast --metric healthcare_revenue # 直接跑模块（同 predict.py）
```

指标 key 一览：

| 库 | 指标 key | 含义 |
| --- | --- | --- |
| 金融 | `finance_trade_amount` / `finance_new_clients` / `finance_avg_volatility` | 月度交易金额 / 新开户数 / 平均波动率 |
| 医疗 | `healthcare_revenue` / `healthcare_encounters` / `healthcare_order_amount` / `healthcare_equipment_cost` | 月度净收入 / 就诊人次 / 医嘱费用 / 设备成本 |
| 通信 | `telecom_bill_amount` / `telecom_new_subscriptions` / `telecom_cdr_fee` / `telecom_cdr_duration` | 月度账单总额 / 新订购数 / 通话费用 / 通话时长 |

报告 `reports/*.md` 含：数据口径、历史时间范围、模型与验证精度（含候选模型对比表）、
未来各月预测值与环比、最近 12 个月真实值对照、趋势结论。每次运行（聊天或 `predict.py`）
都会在 `reports/` 同步生成**趋势图 PNG**（Matplotlib，历史 + 预测折线，报告头部图片嵌入），
文件同名前缀 + 时间戳。依赖 `scikit-learn`（已加入 requirements.txt；
国内安装可加镜像：`pip install scikit-learn -i https://pypi.tuna.tsinghua.edu.cn/simple`）。

## 4.4 非结构化表格库（解析 + AI 查询）

前两节管的是文档（RAG）和三个业务库（MySQL）；这一节管第三种数据：`非结构化数据/` 目录里那批
**写在 markdown / HTML 里的表格**。`services/tables.py` 把它们解析成结构化数据，Agent 就能像查数据库一样用 SQL 查。

### 一句话链路

```text
非结构化数据/*-数据.md      （=== 表id === 分块 + markdown 管道表 / HTML 表格）
       │  services/tables.py 解析：切块 → 解析表格 → 数值清洗 → 列名归一
       ▼
data/tables.sqlite3         （每张源表一个物理表 t_<表id>，另有元数据表 _tables）
       │  Agent 工具链：find_table → describe_table → query_tables（只读 SQL）
       ▼
九天梧桐用中文回答（数字全部来自 SQL 真实执行，可复现）
```


### 解析出来的规模（实测）

| 数据集 | key | 表数 | 行数 | HTML 表 | 典型问题 |
| --- | --- | ---: | ---: | ---: | --- |
| 表格查询 Table_Query | `table_query` | 500 | 6,279 | 151 | 某列叫什么、第一行第一格、按取值找行 |
| 领域运算 Domain-specific Ops | `domain_ops` | 239 | 2,563 | 68 | 同比 / 环比 / 占比 / 变化率等算术题 |
| 多步检索 Multi-step Retrieval | `multi_step` | 48 | 111,486 | 12 | 大表（最大 13,200 行）上的筛选聚合、反事实假设 |

合计 **787 张表 / 120,328 行**，索引约 13 MB，构建耗时约 5 秒。

### Agent 的五个工具（先分析、再召回、再写 SQL）

| 工具 | 作用 |
| --- | --- |
| `list_table_sets()` | 三个数据集的规模与适用题型（先确认数据范围） |
| `analyze_table_query(question, dataset)` | **本地规则分析，零模型调用**：数据集判定 + **中文术语→英文检索词** + **题型→推荐 SQL 写法** + 坑提示 + 下一步（对标业务库那条链路的 `analyze_query`） |
| `find_table(question, dataset, limit, keywords)` | 按问题召回候选表：带表 id 会**精确命中**；`keywords` 直接吃上一步给的英文词；不给时内部自动扩展中文术语，仍弱才调一次模型补词 |
| `describe_table(table)` | 看完整列名、**数值列**、行数与前 3 行预览（写 SQL 前必看） |
| `query_tables(sql, limit)` | 对表格库执行**只读** SQL（单条 SELECT / WITH），返回结果表格 |

**标准流程**：`analyze_table_query` → `find_table(…, dataset, keywords)` → `describe_table` → `query_tables`。

> 和 MySQL 那套是镜像关系：`get_db_skill` ↔ 表格技能卡、`analyze_query` ↔ `analyze_table_query`、
> `get_table_schema` ↔ `describe_table`、`execute_sql` ↔ `query_tables`。
> System Prompt 里写明了一条边界：**这些表格不在 MySQL 里**，问业务库走 `execute_sql`，问这批表格走 `query_tables`，别串门。

### 怎么让它和查 MySQL 一样准

业务库那条链路准，靠的是「术语表 + 题型写法 + 技能卡 + 写前核对结构」。表格这条链路现在补齐了同样的四件套：

| 手段 | 做法 | 效果 |
| --- | --- | --- |
| 术语对照 | `services/tables.py` 里的 `_CN_EN_TERMS`（人工整理，覆盖咖啡 / 气象 / 新能源 / 财报 / 保险 / 地区经济 / 体育等主题）：把「现金支付」「信用利差」「续航」翻成表里真实出现的英文词 | 中文提问对英文表格的召回显著变好 |
| 元语言过滤 | 题目里大量「单元格 / 列名 / 第几列」这类描述表格本身的词（实测占题目词一半以上）全部进停用词 | 噪声不再压过业务词 |
| 题型 → 写法 | `analyze_table_query` 把问题判成 10 类（占比 / 同比环比 / Top-N / 分组 / 计数 / 求和 / 平均 / 按月趋势 / 反事实 / 取值），每类直接给出 SQL 写法与坑 | 少走弯路，尤其是 `*100.0` 这类整除陷阱 |
| 写前核对 | 强制先 `describe_table` 抄列名，再写 SQL；System Prompt 写明失败自纠（列名/引号/表名/单条语句） | 杜绝「凭印象编列名」 |
| 显式表 id | 问题里带 15 位表 id 时**直达**（评测题的 `id` 就是表 id） | 命中率 100% |

**实测精度**（用评测集自带的 787 条「问题 → 表 id」标注做留出集测量，20% 留出、不参与调参）：

| 方案 | top1 | top5 |
| --- | ---: | ---: |
| 只靠关键词召回（改前） | 22.2% | 38.6% |
| + 中文术语表 + 元语言过滤 | **24.1%** | **42.4%** |
| + 一轮 LLM 关键词兜底 | **33.3%** | **53.3%** |
| 问题里直接给表 id | 100% | 100% |

> 说明：这份评测集的题目是模板化生成的（大量重复问法、成百张同构表），**自由文本召回天然有天花板**；
> 而它本来的设计就是「给定表 id 来问」。所以日常使用中，**把表 id 一起给它**是最稳的用法。
> 另外早期还试过「用标注对自动挖掘中英对照表」，实测反而把 top1 拉到 4%（学到的全是问法噪声），
> 已废弃并改成人工整理，过程记在 `.workbuddy/memory/2026-09-18.md`。


### 技能卡（skills/tables/）

沿用业务库技能卡同一套机制（`get_db_skill` 两族都能加载，网页「数据技能卡」下拉里也会出现）：

| 卡片 | 内容 |
| --- | --- |
| `guide.md` | 查询指南：库结构、表 id 规则、数值清洗约定、标准流程、**实测易错点**、通用模板 SQL |
| `table_query.md` | 500 张小表的特点（210 张是 `0/1` 两列 key-value、105 张是 `subject/predicate/object`）、题型与模板 |
| `domain_ops.md` | 算术题特点（年份常写在**列名**里）、同比 / 占比 / 反事实模板，附「参考答案 -2.86%」的完整 SQL |
| `multi_step.md` | 大表注意事项（别 `SELECT *`）、咖啡 / 气象 / 新能源三大主题的列结构与聚合模板 |

### 命令行（不调用模型也能用）

```bash
python -m services.tables --build                  # 解析并重建索引（787 张表，约 5 秒）
python -m services.tables --sets                   # 三个数据集的规模
python -m services.tables --find "Latte 咖啡品类"    # 关键词召回候选表
python -m services.tables --info t_05ab28a47b924ae # 看某张表的列与预览
python -m services.tables --sql "SELECT ..."       # 直接跑只读 SQL
python -m services.tables --questions multi_step --limit 5   # 看评测题样例
```

> 提示：Windows PowerShell 传中文参数可能乱码，用 `--find` 时建议用脚本或英文关键词。

### 解析规则

- **数值清洗**：`$ 100.00 → 100`、`1,234.5 → 1234.5`、`23% → 23`、`(6.5) → -6.5`、`-6.5 ( 6.5 ) → -6.5`；
  只对**数值列**（可解析比例 ≥ 80% 且至少 2 个）生效，其余列原样保留文本；
- **列亲和性**：数值列用 `NUMERIC`、文本列用 `TEXT` —— 所以 `01234` 不会被吃成 `1234`；
- **列名归一**：空表头 → `col1/col2…`，重名 → 加 `_2`，限长 80 字符；原始列名原样保留（含空格 / 中文 / 纯数字的列名写 SQL 时用双引号）；
- **只读安全**：查询走 `file:...?mode=ro` 只读连接 + 语句白名单，`ATTACH / PRAGMA / INSERT / DROP` 等一律拒绝。

### 实测（核验日期 2026-09-18）

- **与评测集参考答案一致**：表 `t_b40962fe65f24d9`（摩根大通信用利差）问「2011→2012 的百分比变化」，
  SQL 算出 **-2.86%**，与 `样例答案.json` 的参考答案完全一致；
- **自由提问走通全链路**：问「现金支付里卖得最多的咖啡品类是哪个？花了多少钱？」
  → `find_table`（自动补英文关键词 cash / coffee）→ `describe_table` → `query_tables`
  → 回答 **Latte 25 杯 / 991.00 元**并附完整排名表；
- **表 id 直达**：问题里带 15 位表 id 时精确命中，不再依赖关键词运气。

### 两个必踩的坑（已写进技能卡）

1. **整除**：SQLite 里 `(34-35)/35*100` 返回 **0**（整数相除截断），必须写成 `(a-b)*100.0/b`；
2. **引号标识符**：列名写错时 SQLite 会把 "不存在的列" 当**字符串字面量**，**不报错但结果全错** —— 列名一律从 `describe_table` 抄。

## 4.5 jiso 题集 NL→SQL 评测（`eval_jiso.py`）

`jiso/` 目录里是 **680 道标准评测题**（金融 279 / 医疗 210 / 通信 191，字段：`id / problem / sql`）。
`eval_jiso.py` 把它们逐题跑一遍，量化系统「自然语言 → SQL」的真实准确率，并产出可复盘的明细与报告。

**快速模式判分链路**（每题一次 LLM 调用；不走向量检索、不含知识库样例，避免"泄题"）：

```text
题目 ──▶ 组装提示词（对应库技能卡 + 实时真实表结构）──▶ LLM 直出 SQL（只输出 SQL）
                                                            │
            判分：生成 SQL 与参考 SQL 都在 MySQL 真实执行 ◀──┘
                 结果集比对：行序无关（多重集）· 列数一致 · 数值归一化（123＝123.0）
```

**用法**：

```bash
python eval_jiso.py --limit 10    # 试跑：每库前 10 题
python eval_jiso.py --db finance  # 只跑金融库
python eval_jiso.py               # 全量 680 题（约 12 分钟）
python eval_jiso.py --resume --out reports/jiso_eval_xxx   # 断点续跑（跳过已完成题）
```

输出到 `reports/jiso_eval_<时间戳>/`：`details.jsonl` 逐题明细（问题 / 生成 SQL / 参考 SQL / 状态 / 耗时）
与 `summary.md`（分库通过率 + 失败分类 + 错题样例）。`_test_eval_core.py` 是判分核心的离线单元测试（24 项，不花钱）。

**实测（2026-09-22，deepseek-chat）**：

| 提示词版本 | 金融 | 医疗 | 通信 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 初版 | 55.5% | 58.1% | 42.9% | **52.9%** |
| 优化版（现行 `eval_jiso.py`） | **79.2%** | **60.5%** | **66.0%** | **69.7%** |

提分关键在**把字段选择行为对齐题库风格**——初版失败中约 70% 是「列选择差异」（模型挑几列 / 参考 `SELECT *`，
或反之）。优化版提示词明确：未点名具体字段 → 输出全部字段（多表 JOIN 用主表别名 `.*`）；
点名类只输出点名字段；统计类只输出分组键 + 聚合值；**不要**自作主张加 `ROUND()`、加题目未提的过滤条件 / 排序 / 取最新。

> 另记录一次**未采纳的实验**：给医疗库追加"宽表紧凑输出"专属规则（v3）后，全量通过率为 68.4%，
> 低于 v2 的 69.7%（医疗/通信小幅回退），据此回退到 v2 提示词——题集内部风格存在混用，
> 继续细分规则收益递减而风险上升。三版明细分别留档在 `reports/jiso_eval_20260922_173755`（v1）、
> `reports/jiso_eval_v2`、`reports/jiso_eval_v3`，可用 `_diff_eval.py <v1.jsonl> <v2.jsonl>` 逐题对比修复 / 回退。

## 5. 项目结构

```
.
├── core/
│   ├── agent.py      # Agent 编排：LLM、工具、规划与三层记忆
│   ├── context.py    # 上下文组装、预算与工具动态选择
│   ├── planning.py   # 规划引擎：任务拆解 / 计划状态机 / 执行自检
│   ├── prompting.py  # 查询意图理解与提示词约束
│   └── reasoning.py  # CoT / ToT / MCTS / Reflexion 推理策略
├── services/
│   ├── rag.py        # RAG 知识库检索
│   ├── tables.py     # Markdown/HTML 表格解析与只读查询
│   ├── spreadsheet.py # Excel / CSV 等结构化文件解析
│   ├── uploads.py    # 上传文件管理、数据卡片与自动索引
│   ├── document_ingest.py # PDF / Word / PPT / 图片 OCR 文本提取
│   ├── vectordb.py   # SQLite 持久化向量库
│   ├── ml_forecast.py # sklearn 月度预测核心
│   ├── pysandbox.py  # 受限 Python 执行环境
│   ├── sanitize.py   # 输出脱敏
│   └── viz.py        # Matplotlib 图表
├── eval/             # 离线评测与回归测试
├── predict.py        # 独立运行的预测脚本（生成 reports/*.md）
├── web.py            # Flask 服务与 REST 接口
├── index.html        # 多会话聊天界面
├── jiso/             # 680 道标准评测题（id/problem/sql，金融 279 / 医疗 210 / 通信 191）
├── reports/          # 预测报告 / 评测报告输出目录（*.md + *.jsonl + 趋势图 *.png，运行时生成）
├── knowledge/        # RAG 知识库：放入 .md/.txt/.pdf 自动可检索（含三库 NL→SQL 问答样例）
│   ├── 公司差旅与报销政策.md
│   ├── 金融资产管理库-自然语言查询转SQL问答.md
│   ├── 医院医疗库-自然语言查询转SQL问答.md
│   └── 通信运营商库-自然语言查询转SQL问答.md
├── 非结构化数据/      # 表格数据源（三份评测集：*-数据.md + *_task.json，只读，可用 TABLE_DATA_DIR 覆盖）
├── skills/
│   ├── database/     # 数据库查询技能卡（每库一张；Agent 判库后由 get_db_skill 加载）
│   └── tables/       # 非结构化表格技能卡（guide / table_query / domain_ops / multi_step）
├── data/             # 运行时生成（已 gitignore）
│   ├── conversations.json     # 会话元数据（含执行计划与进度，刷新页面可恢复）
│   ├── checkpoints.sqlite3    # Checkpointer 落盘（会话内完整消息历史）
│   ├── memory.sqlite3         # 跨会话长期记忆 Store + 长会话滚动摘要
│   ├── tables.sqlite3         # 非结构化表格索引（787 张表，python -m services.tables --build 重建）
│   ├── uploads/               # 网页上传的文件（可由 UPLOAD_DIR 覆盖）
│   ├── table_memory.json      # 上传表的数据卡片与问答经验
│   └── vector.sqlite3         # 持久化向量索引
├── requirements.txt  # Python 依赖
├── .env.example      # 环境变量模板（不含真实密钥）
├── .env              # 真实密钥（已 gitignore）
├── .gitignore
├── MIGRATION.md      # 换电脑迁移指南（带什么 / 装什么 / 改什么 / 验证清单 / 实证坑）
└── README.md
```

## 6. 关键依赖版本

| 包 | 版本 |
| --- | --- |
| langchain | 1.4.0（1.x 已迁移到 `langchain.agents.create_agent`） |
| langchain-openai | ≥ 0.2 |
| pypdf | ≥ 4.0（PDF 文本抽取；`services/rag.py` 在用到 PDF 时懒加载） |
| langgraph | ≥ 1.0（`langgraph.checkpoint.*` 提供 Checkpointer） |
| langgraph-checkpoint-sqlite | ≥ 2.0（持久化用，缺失时自动退回内存版） |
| python-dotenv | ≥ 1.0 |
| flask | ≥ 3.0 |
| scikit-learn | ≥ 1.3（sklearn 月度预测用，含 numpy 依赖） |
| matplotlib | ≥ 3.8（`services/viz.py` 可视化用，懒加载；缺库不影响其它功能） |
| pandas / openpyxl / xlrd | 表格文件解析与 Excel 读写 |
| python-docx / python-pptx / rapidocr-onnxruntime | 上传 Word、PowerPoint 与图片资料的文本提取 |

> `core/planning.py`（规划引擎）与 `services/tables.py`（非结构化表格解析 / 查询）**只用 Python 标准库**
> （后者用 sqlite3，**不需要 pandas**），没有引入任何新依赖；表格数据只落在本地
> `data/tables.sqlite3`，**不写入 MySQL**。

## 7. 常见问题

- **页面提示“无法连接后端”**：先确认 `python web.py` 正在运行，再看终端是否报错
  （例如当前 Python 环境没装 flask，就会出现 `No module named 'flask'`）。
- **`/api/health` 返回 `memory`**：说明没装上 `langgraph-checkpoint-sqlite`，
  历史只在进程内存中保存，重启会丢。装上依赖后会自动切换为 `sqlite`。
- **想彻底清空历史**：删掉 `data/` 目录即可。
- **回答很慢 / 一直转圈**：优先用 `LLM_PROVIDER=deepseek`（`deepseek-chat` 通常 1~3 秒）；
  若用 `deepseek-reasoner` 或其它推理模型本身就会慢。
  `REQUEST_TIMEOUT` 控制超时上限，超时会直接报错而不是无限等待。
- **报“未找到 XXX_API_KEY”**：检查 `LLM_PROVIDER` 指的是哪一组变量，把对应那组填全。
- **非结构化表格的数据放在哪？** 只在本地：`非结构化数据/` 里的 markdown / HTML 表格由 `services/tables.py` 解析成
  `data/tables.sqlite3`（787 张表 / 120,328 行），**不会写进 MySQL**。重建索引：
  `python -m services.tables --build`（约 5 秒），看一眼规模：`python -m services.tables --stats`。
- **为什么 `execute_sql` 查不到 `t_xxxx` 这些表？** 因为它们不在 MySQL 里（MySQL 只有三个业务库）。
  问业务库用 `get_table_schema` + `execute_sql`，问这批表格用 `find_table` + `describe_table` + `query_tables`。
- **表格问题答不上来 / 召回不准？** 先把表 id（15 位十六进制）直接告诉它，或先 `python -m services.tables --find "关键词"`
  看能不能召回到目标表；中文问题对英文表格召回偏弱时，换成表里的英文取值（如 `Latte`、`jpmorgan`）效果更好。

## 8. 更新记录

> 约定：每次对代码 / 配置 / 文档做出修改后，都在本节**顶部**追加一条“日期 + 改了什么”，
> 只记功能与口径变化，保持简洁、如实。

### 2026-09-28（README 当前用法同步）

- 文档名称更新为「九天梧桐 AI 工作台」，简介改为当前的本地多会话数据工作台定位。
- 所有当前运行命令与代码入口统一为重构后的 `core/` 和 `services/` 目录，例如 `python -m core.agent`、`python -m services.tables`。
- HTTP 接口表补齐上传、预览、自动记忆和深度搜索接口；项目结构图补齐核心模块、服务模块与运行时数据。
- 上传说明补充文档与图片 OCR 支持，以及实际可接受的文件类型和关联依赖。

### 2026-09-28（`core/agent.py` 可读性重构，行为不变）

> 需求：`agent.py` 单文件 4200+ 行、170 个函数，重复定义与超长函数并存，改一处要翻很久。
> 本次只做**内部结构整理**，对外 API、工具数量、提示词内容与回答口径全部保持不变。

**修掉两处真实隐患**：① `_resolve_db_name` 被定义了两次（第二个覆盖第一个），
`get_table_schema(database='乱写')` 会拿着非法库名去连库而不是提示“库名没确定”——
现在拆成语义明确的两个：`_resolve_db_name()`（认不出返回 `None`）与
`_coerce_db_name()`（认不出原样返回，供数据洞察工具用），别名表只留一份 `_DB_ALIASES`；
② `knowledge_keywords()` 里引用了不存在的 `KNOWLEDGE_DIR`（异常被 `except` 吞掉，
导致知识库文件名关键词一直没被收集），改用 `rag_service.directory`。

**长函数拆分**：`plot_last_result` → `_column_index` / `_is_numeric_column` /
`_resolve_chart_axes` / `_collect_chart_points`；`get_table_schema` →
`_resolve_schema_target` / `_render_table_columns`；`query_tables` →
`_render_rows_table` / `_record_table_sources`；`stream_ask` 主循环 →
`_compose_round_messages` / `_tool_call_key` / `_invoke_tool_call`。

**其他整理**：散落的魔数收进常量区（`PLOT_CACHE_ROWS`、`SANDBOX_ROW_LIMIT`、
`PLOT_SCAN_ROWS`、`PLOT_MAX_POINTS`、`PLOT_NUMERIC_RATIO`、`SOURCE_TEXT_LIMIT`）；
连接关闭统一走 `_close_quietly`；删除 `build_system_prompt` 上重复且过期的第二份 docstring。

**验证**：模块导入通过，27 个工具注册正常（含曾因装饰器错位丢失的 `query_tables`）；
`eval/_test_vectordb.py`、`eval/_test_reason_and_data.py` 全部通过。

### 2026-09-24（统一上传目录 + Python 查表 + 自动记忆）

> 需求：放在一个统一目录，管理员从后台上传存放到 data 目录；用户问数时**由大模型编写 Python 语句**
> 查询表格；并对用户的问题**自动添加记忆和学习**（或每次存放进去自动解析）。

**新增 `services/uploads.py`（统一目录 + 落盘即解析）**：上传文件统一进 `app/data/uploads`
（`UPLOAD_DIR` 可改），表格库连同该目录一起扫描；保存后**自动**① 解析出「数据卡片」写进记忆
② 重建索引——管理员传完，用户马上能问，没有额外的手工步骤。文件名保留中文、只取文件名防穿越、
同名自动改名不覆盖、`UPLOAD_MAX_MB` 限大小。

**新增 `services/table_memory.py`（自动记忆与学习）**：两类记忆全自动——
① **数据卡片**（上传即生成：列名/类型/示例值/枚举取值）② **问答经验**（每次 Python 查表成功后
沉淀「问题 → 表 → 代码」，相似问题能回想）。存在 `data/table_memory.json`；只记成功经验，
相同写法只累加次数；删文件时一并清理；卡片里的示例值**按列名脱敏**（`姓名` 列「张三」→「张*」，
「软件学院」等正常取值不误伤）。

**新增工具 `query_table_python`（模型写 Python 查表）**：表读成 DataFrame 注入为 `df`，
连同 `pd`/`np` 放进既有沙箱（禁 import/open/while、循环有步数预算），
适合 SQL 不好写的活（分组透视、多层索引、时间重采样、多表合并、占比与同比环比）。
**接入**：`find_table` 返回时附带记忆（已记住的表结构 + 以前这么查过），并记下本轮表名。

**接口与前端**：`POST/GET/DELETE /api/uploads`、`GET /api/uploads/memory`；
聊天页右上角新增「**数据**」按钮 → 右侧面板（点击或拖拽上传、列表、删除、显示"已学几个文件/沉淀几次经验"）；
设了 `ADMIN_TOKEN` 时写操作需带令牌。

**测试**：新增 `eval/_test_uploads.py`（**29 项全部通过**）+ `table_memory` 自检 10 项；
既有全部模块回归通过（工具数 26 → 27，同步修正断言与 README）。README 新增 §3.15；
`.env.example` 新增 `UPLOAD_DIR / UPLOAD_MAX_MB / ADMIN_TOKEN / TABLE_MEMORY_PATH`。

### 2026-09-24（放入真实 Excel 后的联调修复）

> 场景：用户往 `非结构化数据/` 放了 `test.xlsx`（重庆财经学院贫困生认定公示名单，5520 行 × 5 列）。

**① 服务开着时索引重建不了**：`build()` 用「写临时文件 + os.replace」落盘，Windows 上服务占用
`tables.sqlite3` 时 replace 被拒（PermissionError），还留下一个 `.building` 垃圾文件。
改为：replace 失败时自动退回**原地重建**（在同一库文件里 DROP 旧表再写一遍）——**不必停服务**，
实测服务运行中重建成功（788 张表 / 125848 行）。

**② 表头错位**：该 Excel 第 1 行是合并大标题「重庆财经学院2026-2027学年贫困生认定公示名单」，
第 2 行才是真表头。原逻辑把首行当表头 → 列名变成那句标题、真表头被当成数据行，整张表没法查。
新增 `spreadsheet._drop_title_row()`：首行几乎只有一格有字（或有效格数远少于第二行）就跳过。
修后列名正确为 序号/姓名/学院/班级/困难等级，可按学院聚合统计。

**③ 隐私缺口**：`query_tables` 已脱敏，但 **`describe_table` 的前 3 行预览没脱**——
花名册类 Excel 会把真实姓名原样吐给模型。补上脱敏（按列名判定，实测 `李鑫月` → `李**`，
学院/班级/困难等级不受影响）；顺带修掉一个我自己引入的退化：preview 每行是 dict，
误用 `list(row)` 会取到列名而不是值。

**测试**：`eval/_test_spreadsheet.py` 增到 **34 项全部通过**（新增「大标题行 + 表头行」用例 3 项）；
其余模块自检与 `eval_context.py` 四项指标回归通过。

### 2026-09-24（支持查询 Excel / CSV 表格文件）

> 需求：检查项目是否可以查询 Excel 和 CSV 表格类数据。

**核查结论：改造前不能**。`services/tables.py` 只解析「非结构化数据/」下三个硬编码 `.md` 里的
Markdown / HTML 表格，实测把 `.xlsx` / `.csv` 放进目录后 `build()` 得到 **0 张表**。

**新增 `services/spreadsheet.py`**：解析 `.xlsx/.xlsm`（pandas + openpyxl）与
`.csv/.tsv/.txt`（标准库 csv + 分隔符探测）；多 sheet 拆成多张表；编码自动探测
（utf-8-sig → gb18030 → utf-8 → big5，Excel 导出的 GBK 也能读）；首行非纯数字即表头，
否则自动生成 col1…colN；数值判定复用 tables 的同一套规则；坏文件只警告不中断。
**接入 tables.py**：新增第四个数据集 `files`（目录里真有表格文件时才注册——没有文件时行为完全不变），
复用既有入库与查询链路，Agent 工具 `list_table_sets / find_table / query_tables` 零改动即可查。

**过程中修掉三个真问题**：
- **中文表名被吃掉**：`_table_name()` 只留 ASCII，中文文件名退化成一串下划线且可能撞名 →
  改为保留中文 + 6 位哈希后缀，并新增 `SCHEMA_VERSION=2` 让旧索引自动重建；
- **表少时召回失灵**：IDF 相对表数计算，只放两三个 Excel 时分数低于固定阈值 1.5 → 改成「分数或覆盖率」双判据；
- **按文件名找不到表**：文件名 / sheet 名不在检索文本里 → 纳入 `search_blob`。

**测试**：新增 `eval/_test_spreadsheet.py`（**31 项全部通过**：解析 15 + 集成 13 + 行为不变性 3），
模块自检 17 项；真实索引重建后仍是 787 张表 / 120328 行，既有召回正常；
`requirements.txt` 补 `pandas` / `openpyxl`；`.env.example` 加 `TABLE_FILE_MAX_ROWS/COLS`；
README 新增 §3.14。

### 2026-09-24（文件类型支持盘点：补 .xls 与单行数值列）

> 需求：确认项目一共能读取哪些文件类型。

盘点结果见下表。过程中发现并修掉两个「清单上写着支持、实际用不了」的问题：

1. **`.xls` 实际读不了**：`spreadsheet.py` 里有 `.xls` 分支，但环境**没装 `xlrd`**——老版 Excel 会静默解析失败。
   已安装 `xlrd>=2.0.1` 并写入 `requirements.txt`；用 xlwt 造真实 `.xls` 实测通过（读出列与行）。
2. **只有 1 行数据的表，数值列被判成文本**：`detect_numeric_columns` 要求「至少 2 个数值」，
   用户上传的小 Excel 常就一行，`SUM/AVG` 全废。改为 `min(2, len(values))`（只有 1 个值时按 1 个判）。
   回归：787 张表索引重建正常，数值列 1704 个；混合列（1200 / 无）仍判文本，行为未变。

### 2026-09-24（PDF 技术文档生成）

> 需求：生成项目 PDF 技术文档。

新增 `build_techdoc.py`（reportlab + 微软雅黑），一条命令产出
**《九天梧桐AI工作台技术文档.pdf》**（19 页，27 个书签，带封面 / 目录 / 页眉页码 / PDF 大纲）：

```bash
python build_techdoc.py                      # 输出到项目根目录
python build_techdoc.py -o docs/tech.pdf     # 指定输出
```

**为什么不手写文档**：工具清单、向量库条数、评测成绩、代码行数都在生成时**从代码与报告实时读取**，
重跑即同步，不会写完就过时。目录采用「两遍构建」——第一遍拿真实页码，第二遍回填，保证目录页码准确。
**文档大纲**：概述 / 快速开始 / 系统架构 / 模块清单 / LLM 容错 / 工具全表 / 推理与规划 / 三级数据能力 /
上下文工程 / 向量库与检索 / 记忆脱敏表格库 / HTTP 接口与前端 / 配置说明 / 评测体系 / 安全边界 / 附录（扩展与 FAQ）。

**依赖**：安装了 `reportlab`（生成用）与 `pypdf`（文档自检用，可选）。
过程中修掉两个真问题：① 评测表取错字段（报告里题目总数字段是 `n` 不是 `total`，会印出 `1 / None`）；
② 工具说明里的 markdown 记号（`**强调**`）被原样印进 PDF —— 生成时统一清洗。

### 2026-09-24（问答准确率评测：从 79.4% 到 100%）

> 需求：测试项目数据的问答准确率，提高到 95% 以上。

**做法**：先建可量化的数据集再谈优化。新增 `eval/qa_cases.py`（50 题 / 7 类，标准答案**全部由真实数据源算出**：
SQL 题直接在库里执行 `truth_sql` 取单值，知识题按政策原文匹配，诚实性题用正则判「有没有承认查不到」）+ 
`eval/eval_accuracy.py`（自动跑问答 + 判分 + 出 JSON 报告；数值题兼容万/亿/千分位写法）。

**基线 79.4%（27/34）**→ 定位到三类根因并逐个修：

1. **知识类只有 22%**：知识型问题没有命中任何路由关键词 → 落到 SQL 组 → `search_knowledge` **压根没注册**，
   模型只能去业务库里翻政策，反复重试直到放弃。修法：① 用**知识库文档动态抽取**路由关键词（文件名 + 各级标题，
   用户换文档自动适配；只取二级以内非样例标题，避免 SQL 样例标题把数据题误判到知识库）② 判断不出时默认给
   sql+knowledge 兜底 ③ 提示里新加「先判方向：问的数还是问的制度」路由规则（`context.ROUTING_RULES`）。
2. **知识检索被大文档刷榜**（「报销金额超过多少元需要二级审批」答不出）：政策文档 5 块 vs SQL 示例 1036 块，
   靠「金额/超过」把政策挤到第 4 位 → Top-K 里一条政策都没有。新增 `context.rerank_by_coverage()`
   （按「命中了查询里多少个不同词元」重排）与 `context.diversify()`（同一来源最多占一半名额），
   检索候选池同步扩大到 4 倍。政策片段从第 4 位提到第 1 位，且不影响其余问法。
3. **波动其实是我的题口径含糊**：「2024 门诊人次」算不算「已取消」（4476 vs 3014）、「管理客户最多的经理」
   算不算「正常」状态（45 vs 44）、「卖出交易合计」算不算「已成」（1307 亿 vs 1054 亿）— 模型按业务常识过滤，
   两边都有依据。改为**每题口径写死**（拆题 + 「不区分状态，全部计入」），把稳定性问题变成确定性问题。

**结果**：**连续两轮 50/50 = 100%**（单轮约 4 分钟）。
**回归**：context / reasoning / planning / prompting / sanitize / pysandbox / ml_insight / vectordb 自检、
`_test_eval_core.py`、`_test_reason_and_data.py`、`_test_vectordb.py`、`eval_context.py` 四项指标全部通过。
README 新增 §3.13 准确率评测章节。

### 2026-09-24（上下文工程 Context Engineering）

> 需求：系统提示的工程化分层组织（正面表述 / 提供示例 / 优先级明确 / 去除冗余）；工具精简（移除无关工具、
> 减少 30%~50% 工具上下文）、描述精炼、参数约束、分组注册；检索上下文（查询改写 / 相关性过滤 /
> 来源标注 / 长度裁剪）；以及**评估与迭代**四个维度。

**新增 `core/context.py`**：
- **① 系统提示分层**：每块带优先级（时间<安全<角色<任务<示例<记忆<提示），`compose()` 按**行指纹**跨块去重、
  超 `CTX_BUDGET` 时**从低优先级的可选块开始丢**（必留块不动）；补正面表述的 `ANSWER_EXAMPLE`
  （一次合格回答的完整样例）与 `PRIORITY_RULES`（冲突时的取舍顺序）；合成报告留在 `last_report`。
- **② 工具上下文**：`TOOL_GROUPS` 分 6 组 + 核心工具常驻，`select_tools_for()` 按意图动态注册，
  `bind_tools(子集)` 真正少传 schema；`TOOL_BRIEF` 每个工具一行写完用途 + 参数约束；
  判断不出阶段或异常时**返回全量**（宁可多给也不给漏）。
- **③ 检索上下文**：查询改写（洗寒暄/口水词，优先用 `QuerySpec.rewritten`）→ `CTX_MIN_SCORE` 相关性过滤
  （全部不过阈就返回「证据不足」而不是硬凑）→ 来源标注（路径/段落/页码/**更新时间**/相关度）→
  按句子裁剪到 `CTX_SNIPPET` 且优先保留与查询重叠最多的段落。
- **④ 度量**：`Meter` 记录各层字符/token 与工具调用质量，`CTX_STATS=1` 落盘 `data/context_stats.jsonl`。

**接入**：`build_system_prompt(tools=…)` 走分层合成；`stream_ask` 按问题动态注册工具并回填工具清单与一行式指引；
ReAct 循环里记录每次工具调用的成败；`smart_search` 走完整检索管线；rag 补上文档 `updated`（mtime）元数据。
**测试**：新增 `eval/eval_context.py` 四维评估——任务完成率 **100%**、工具上下文省 **49.1%**、
有效调用率 60%（达标）、响应一致性 **100%**，**四项全部达标**；`core/context.py` 自检通过，
既有全部模块自检与测试回归通过。README 新增 §3.12；`.env.example` 新增 `CTX_*` 配置段。

### 2026-09-24（向量数据库 Vector Database）

> 需求：构建向量数据库（存储、索引、检索高维向量的数据库系统）。

**改造前的问题**：rag.py 里的所谓语义检索是「进程启动时一次性算完、放内存 list」——
没有落盘、没有增量更新、没有索引结构、重启即失效、不配外部 embedding 就退化成关键词。

**新增 `services/vectordb.py`**：SQLite 持久化（float32 BLOB）；两种向量化后端 `local`（离线哈希 bigram TF-IDF）
与 `api`（OpenAI 兼容）；规模超阈值自动建 **IVF 倒排索引**（KMeans + nprobe，候选不足自动回退精确解）；
IDF 加载时重算保证增量入库不失真；upsert/sync/search(元数据过滤)/delete/prune/clear/stats 全套且线程安全；
换后端或改维度会明确报错而不是算出错的相似度。
**接入 rag.py**：`rebuild()` 同步落库并在文档删除后 prune；RRF 融合优先走向量库，不可用时降级；
`engines()` 暴露统计。**测试**：`eval/_test_vectordb.py` **41 项全部通过**（含临时知识库集成），模块自检 20 项。

### 2026-09-24（推理规划层 + 三级数据能力）

> 需求：拥有推理与规划（CoT / ReAct / Plan-and-Execute / ToT / MCTS / Reflexion）；
> 并核查是否具备「初级：SQL/Python 查询计算；中级：统计分析、关联查询与公式计算；高级：自动数据建模」。

**核查结论**：ReAct 手写循环 ✅、Plan-and-Execute ✅（planning 状态机）、Reflexion ⚠️（只有单路一次性自检）、
CoT ⚠️（只有软要求）、**ToT / MCTS ❌ 完全没有**；数据侧：SQL 查询 ✅、**Python 计算 ❌**（只有 200 字符的
`calculator`）、统计分析/关联 ⚠️（只能手写 SQL）、时序预测 ✅（但写死月度+单指标）、**异常检测/聚类 ❌**。

**新增 `core/reasoning.py`（推理规划层）**：
- **ToT 树状多路径探索**：每层生成 K 条**实质不同**的路线 → LLM 自评打分 → beam 剪枝 → 下一层细化，最终产出评分最高的路径；
- **MCTS 蒙特卡洛树搜索**：UCB1 选择 → 扩展候选下一步 → 模拟评分 → 反向传播（价值累加、每层 ×0.98 衰减）；
- **CoT**：`COT_RULES` 静态注入「事实→推断→动作→校验」四拍节拍（零调用），另有显式的 `cot_think()`；
- **Reflexion**：把每次自检的建议入账，下次自检带历史、**识别重复建议**并沉淀成「经验教训」注入下一轮；
- 树搜索的候选路线与评分会渲染成「推理路径」进提示词；`REASON_MODE / TOT_BREADTH / TOT_DEPTH / MCTS_ITERS` 可控，
  **任何失败静默降级**为单条计划。自检 `python core/reasoning.py`（16 项）。

**新增数据能力**：
- 初级：`run_python` + `services/pysandbox.py`——受限 Python 沙箱（禁 import/open/eval/下划线属性/while，
  **循环体插桩 50 万步预算**而非不可靠的线程超时），数据进沙箱前先脱敏；
- 中级：`analyze_data`——自动甄别度量列（排除 ID/流水号/二值位），出统计画像 + Pearson/Spearman 相关矩阵与解读；
- 高级：`detect_data_anomalies`（z-score + 箱线图 + 孤立森林三口径投票）、`cluster_data`（轮廓系数自动定簇 + 簇画像自动命名），
  均在 `services/ml_insight.py`，只用 numpy/sklearn，不新增依赖。

**测试**：新增 `eval/_test_reason_and_data.py`（**55 项断言全部通过**，离线、不连库、不花 API 费用）+ 三个模块自带自检；
既有的 `eval/_test_eval_core.py`、`planning.py`、`prompting.py`、`sanitize.py` 回归通过。
**README**：新增 §3.9 推理与规划、§3.10 三级数据能力章节；工具数 22 → 26；`.env.example` 新增推理与沙箱开关。

### 2026-09-24（提示词工程：查询意图结构化 + 两份必查清单 + 工具正反例）

> 需求：增强提示词工程，让问答取数更准确。

- **新增 `prompting.py`（查询意图结构化 Query Understanding）**：正式取数前用一次便宜的结构化调用
  （温度 0、短输出）把口语提问消歧成 `QuerySpec`——时间范围落成**具体起止日期**、计数说清有没有去重、
  "最好"写明排序字段与升降序、内置「歧义清单 + 建议的默认口径」，并把它渲染进本轮 System Prompt。
  **多轮追问会带最近 6 条历史补主语**，解决「它 / 这个 / 那…呢」这类缺主语的失败；
  **默认假设被要求写进回答**，用户看得到口径而不是拿到一个来路不明的数。
- **代价与降级**：只对「像在问数据」的问题触发（`worth_understanding()` 本地判断，打招呼 / 纯算术跳过）；
  理解失败（模型不可用 / 返回非 JSON / 超时）一律静默返回 `None`，走原流程，不影响可用性。
- **两份清单式约束**注入 System Prompt：`<sql_guardrails>` 写 SQL 前必查 10 条、
  `<answer_discipline>` 回答前必查 6 条——把原先散落在长段落里的经验规则收敛成编号清单。
- **工具描述加 few-shot**：`execute_sql` docstring 补三组「反例 → 正例」（计数忘去重、
  排序问题少了范围与方向、日期当字符串比较且没按自然月聚合）。
- **开关**：`QUND=1`（默认开，`0` 关闭）；自检 `python prompting.py`。
- **README**：新增 §3.8 提示词工程章节；`.env.example` 新增 `3.6 提示词工程` 小节。

### 2026-09-23（输出脱敏：个人关键信息不外泄）

> 需求：对数据进行预处理、脱敏清洗，回复里不出现个人关键信息。

- **新增 `sanitize.py`（输出脱敏层）**，服务端统一处理，三条出口全覆盖：
  - **① 数据预处理**：`execute_sql` / `query_tables` 的结果集在**喂给模型之前**按「列名 + 单元格值」
    双重判断脱敏（姓名 / 手机 / 身份证 / 邮箱 / 住址 / 银行卡 / 流水号 / 出生日期…）；
    `plot_last_result` 复用同一份缓存，图表同样不含明文。表头加 `（已脱敏）` 后缀并附一句说明，
    避免模型发现值不对就自己“补”名字造成幻觉。
  - **② 文本兜底**：SSE 逐字输出（新的 `StreamSanitizer`，用悬尾 + 安全边界解决「号码被切成两个
    chunk 导致漏判」）、`done.answer`、深度搜索回答统一再过一遍正则。
  - **③ 落盘与溯源**：写回 Checkpointer 的 AI 消息（`_sanitize_message`）、数据来源里展示给用户的
    SQL（`record_source`，where 条件里的手机号最容易漏）、知识库检索片段与深度搜索引用片段都脱敏。
- **误伤控制**：`product_name` / `file_name` / `city` / `net_profit` 等同构列名不处理；「客户满意度」
  这类词被姓氏表 + 黑名单挡住不误判；金额 `12345678.90` 不会被当成卡号。掩码串不再命中同一套规则
  → **幂等**，重复处理安全。
- **开关**：`SANITIZE=1`（默认开，设 `0` 关闭）、`SANITIZE_STRICT=1`（严格模式：证件号 / 卡号 / 编号
  全遮、邮箱连带域名一起遮）。自检：`python sanitize.py`。
- **README**：新增 §3.7「输出脱敏」章节；`.env.example` 新增 `3.5 输出脱敏` 小节。

### 2026-09-23（回答真流式 + 左侧一键清空会话 + 问题框常驻底部 + 数据来源可追溯）

> 需求：① 回答要流式输出；② 左侧能一键清除会话；③ 问题输入框固定；④ 给出的数据要带上数据来源。

- **回答改成真·流式（打字机）**：原先 `stream_ask()` 只把终答轮的整段回答**一次性**塞进一个 `token` 事件
  （看着还像“等半天后整段弹出”），现改为模型每吐一个 chunk 就立刻下发一个 `token` 事件；
  代价是模型有时会在调工具前先写一句过渡句（也已流出去了），因此新增 **`rewind` 事件**：
  工具轮 / 自检不通过要重写 / 渠道失败要重试时，告诉前端「撤回最后 n 个字」，仍然保持
  「只给结果、不给过程」的产品口径。前端收到 `rewind` 会回退已渲染的文字并恢复“正在处理”态。
  （已用假模型脚本端到端验证：token 多事件发出、rewind 字数与过渡句长度一致。）
- **左侧一键清空会话**：侧栏「历史会话」右侧新增 **清空会话** 按钮（窄屏也保留），
  二次确认后清掉全部会话；后端新增 `DELETE /api/conversations`（`ChatService.clear_conversations()` +
  `ConversationStore.clear()`），会连带清掉各线程在 Checkpointer 里的检查点，**跨会话长期记忆保留**；
  清空后自动新建一个干净会话，可直接接着问。注意：`ConversationStore.clear()` 的返回值注解写成 `list`
  而非 `list[str]`——类体内 `list` 已被实例方法遮蔽，写泛型注解会在 import 阶段直接 `TypeError`。
- **问题框固定在底部**：`.composer` 改为 `position: sticky; bottom: 0`（并提高层级 + 渐变背景），
  消息再多也只是消息区内部滚动，输入框始终停在聊天区最下方、随时可直接打字。
- **数据来源可追溯**：新增一套轻量**来源登记**（`agent.py` 的 `record_source / take_sources / reset_sources`）——
  `execute_sql`（哪个 MySQL 库、哪些表、返回行数、SQL）、`query_tables`（哪张非结构化表、所属数据集与源文件）、
  `search_knowledge`（哪份知识库文档、第几段 / PDF 第几页）、`forecast_metric`（哪个指标、哪张表、预测月数、报告路径）、
  `plot_last_result`（图表取数出处）；同一出处自动合并（表名累计、行数与 SQL 以最后一次为准）。
  这些出处随 **`sources` 事件**下发并存进会话元数据，前端在回答卡片下方渲染「**数据来源**」区；
  回到旧会话（`GET /api/conversations/<id>/messages`）同样能看到。系统提示同步加了第 ⑨ 条：
  正文不必罗列出处（卡片自动生成），但估算值 / 口径假设必须在正文说清。
- **数据来源面板改版（视觉）**：从朴素列表换成**可折叠的出处卡片**——整块一张圆角卡，标题栏
  「数据来源 + N 处」点击即可收起（超过 6 条默认收起，避免压住正文）；每条按类型配**彩色徽章 + 图标**
  （数据库蓝 / 表格库青 / 知识库紫 / 预测橙 / 图表绿，深浅色各一套 `--ds-*` 变量），左侧竖色条区分类型，
  主标题用**友好显示名**（库 key → 金融/医疗/通信业务库、日志化的 `t_xxx` → 数据集名、文档路径 → 文件名 + 目录、
  预测 → 指标中文名、图表 → 图表标题），表名用等宽 chip、行数用千分位 pill，**SQL 默认折叠**在 `<details>` 里
  （点「查看执行的 SQL」展开）；深度搜索的引用片段同样按 `[n] 文件名 · 第几段 / PDF 第几页 + 摘录` 渲染。
- **来源详情抽屉（交互）**：参照 DeepSeek 搜索结果面板——**点击任一出处卡片，右侧滑出详情抽屉**
  （`.src-drawer`）：类型徽章 + 名称/位置、基本信息（类型 / 名称 / 位置 / 数据量 / 来源标识）、
  涉及数据表 chip、定位 pill（第几段 / PDF 第几页）、说明与原文摘录、完整 SQL 代码块；
  遮罩点击 / × / Esc 均可关闭，窄屏占满全宽。卡片悬停出现「查看详情」箭头暗示可点；
  卡内「查看执行的 SQL」的原地展开不冒泡（点它不会弹抽屉）。深度搜索的引用片段同样支持。
- **README**：§3.1 HTTP 接口表补 `DELETE /api/conversations`，NDJSON 事件说明补 `token`（流式）/ `rewind` / `sources`。

### 2026-09-22（新机环境重建 + jiso NL→SQL 评测上线 + 提示词优化）

> 需求：在新电脑上恢复项目运行；接入 jiso 题集做评测并尽可能提分。

- **环境重建（换到新电脑）**：旧 `.venv` 随迁移失效（内部路径指向旧电脑）→ 按 §1 用本机 Python 3.11 重建并装齐依赖；
  本机原无 MySQL → 用 `winget` 安装 **MySQL 8.4.9 LTS**（`Oracle.MySQL`），因安装包不自动初始化，
  手动补齐数据目录 / `my.ini`（utf8mb4）/ 数据初始化 / **`MySQL84` 服务注册**（root/123456，开机自启）；
  三个业务库 dump 全量导入（金融 39.2 万行 / 医疗 78.2 万行 / 通信 25.3 万行，共约 7.5 分钟，导入后逐表行数核对无差）。
- **新增 `eval_jiso.py`（NL→SQL 评测，§4.5）+ `_test_eval_core.py`（离线单测 24 项）**：680 道题快速模式评测——
  技能卡 + 实时表结构 → **单次 LLM 直出 SQL** → 生成 SQL 与参考 SQL **都真实执行**后做结果集比对判分
  （行序无关的多重集比较、列数一致、数值归一化 `123＝123.0`）；安全上生成 SQL 过只读校验，
  `DROP` / 多语句 / 写操作直接判失败；支持 `--db / --limit / --resume / --out`，输出 `details.jsonl` + `summary.md`。
- **评测结果**：初版提示词 **52.9%**（金融 55.5 / 医疗 58.1 / 通信 42.9）→ 优化版 **69.7%**（79.2 / 60.5 / 66.0）。
  初版失败构成：**列选择差异 220 条（70.7%）**、ROUND 精度 / 类型差异 59、真实逻辑差异 32、执行报错 6、题集自身问题 3。
- **提分手段（7 组提示词规则，已固化进 `eval_jiso.py`）**：① 字段选择对齐题库风格（未点名具体字段 → 输出全部字段，
  多表 JOIN 用主表别名 `.*`；点名类只输出点名字段；统计类只输出分组键 + 聚合值）；② 数值格式（不套 `ROUND()`、
  年份用 `YEAR()`）；③ 写法安全（JOIN 各处列名加表别名前缀、`GROUP BY` 时 SELECT 只放分组键 / 聚合、避开 `REGEXP_SUBSTR`）；
  ④ 不过度设计（不加题目未要求的过滤 / 排序 / 取"最新"）。「对齐字段选择」一条即修复百余题。
- **一次未采纳的实验（诚实留档）**：给医疗库追加"宽表紧凑输出"专属规则（v3）后全量 68.4% **低于** v2 的 69.7%，
  已回退——题集内部风格存在混用，继续细分规则收益递减风险上升；三版明细留档见 §4.5。
- **README**：新增 §4.5（评测用法 / 判分口径 / 实测表 / 实验记录），§5 项目结构同步（`eval_jiso.py`、`jiso/`、`knowledge/` 现状）。
- **仓库整理**：删除 5 个一次性分析脚本与 `data/` 旧备份（`uds/` 索引、`_removed_uds_agent_*` / `_rollback_backup_*` 两个历史备份目录、旧机残留 `_wait_del.ps1`）；
  保留 `_test_eval_core.py`（判分单测）与 `_diff_eval.py`（评测版本对比工具）供后续复盘。
- **新增 `MIGRATION.md`（换电脑迁移指南）**：带走清单（`.venv` 坚决不带）、新机四步（Python → 重建 venv → MySQL 初始化 → 导入数据）、
  要检查的配置（`.env` / 脚本内 MySQL 版本路径）、换机验证清单，以及本次换机实证的五个坑。

### 2026-09-18（非结构化表格查询提精度：本地问题分析器 + 术语对照 + 题型写法 + 精度实测）

> 需求：让 AI 查非结构化数据像查 MySQL 一样精准，提示词等该补的都补上。

- **新增 `analyze_table_query(question, dataset)`（工具数 21 → 22）**：对标业务库链路的 `analyze_query`，
  **纯本地规则、零模型调用**，一次给出四件事：① 数据集判定（tq / ops / msr，带命中词与分数）
  ② **中文术语 → 英文检索词**（表内容是英文，这步直接决定召回）③ **题型 → 推荐 SQL 写法**
  （占比 / 同比环比 / Top-N / 分组 / 计数 / 求和 / 平均 / 按月趋势 / 反事实 / 取值，共 10 类）
  ④ 坑提示与下一步调用顺序。**标准流程变成 analyze → find → describe → query**。
- **新增中文术语对照表（`_CN_EN_TERMS`，人工整理）**：覆盖咖啡消费 / 气象 / 新能源 / 财报金融 /
  保险 / 地区经济 / 体育餐饮等主题，把「现金支付」「信用利差」「续航」「零售电价」这类口语词翻成
  表里真实出现的英文词；`find_table` 会自动用它扩展检索词，**不再依赖每次都调模型翻译**。
- **元语言停用词大扩充**：统计 787 道题后发现，「单元格 / 列名 / 第几列 / 编码」这类描述表格本身的词
  占了题目词的一半以上，之前会把真正有区分度的词压下去；现在全部进停用词。
- **`find_table` 新增 `keywords` 参数**：直接吃 `analyze_table_query` 产出的英文词；
  已经给了 keywords 就不再调模型翻译（省一次调用）。
- **修掉一个隐蔽 bug**：`find_tables` 里「问题带表 id 直接命中」那段正则中的 `\b` 早先被写成了
  **退格控制字符**（模板转义吃掉），导致这条最快路径**一直是死代码** —— 现已修复并实测可用。
- **System Prompt**：表格规则从「五步」升级为「analyze → find → describe → query」七条，
  并补上与业务库同款的「**关键词→写法速查**」（占比 / 同比环比 / Top-N / 分组 / 计数 / 求和 / 平均 /
  按月 / 反事实 / 取值）和「**失败自纠**」（列名没照抄、引号、表名、单条语句、召回换词或直接要表 id）。
- **技能卡补齐「口语说法 → 英文检索词 / 落点」对照表**：四张卡各加一节（实测核验），
  与业务库技能卡的「口语说法 → 正确落点」对齐；guide 卡的流程改为五工具版并写入实测精度。
- **精度实测（用评测集自带 787 条「问题 → 表 id」标注，20% 留出、不参与调参）**：
  只靠关键词 top1 22.2% / top5 38.6% → 加术语表与元语言过滤 **top1 24.1% / top5 42.4%** →
  再加一轮 LLM 关键词兜底 **top1 33.3% / top5 53.3%**；**问题里直接给表 id 时 100%**。
- **一次失败的方法也记下来**：先用「标注对自动挖掘中英对照表」试过，留出集上 top1 从 22% **掉到 4%**
  （学到的全是问法噪声），已废弃；改为人工整理 + 实跑验证，对应做法写进了 README 与开发笔记。

### 2026-09-18（撤回：表格数据不进 MySQL，恢复「只写本地 SQLite」）

> 需求：不放 MySQL 库里，恢复原来的样子。

- **数据侧**：镜像库 `unstructured_tables`（787 张表 + 2 张元数据表）已从本机 MySQL **整库删除**；
  现在库里只有原有三个业务库（各 8 张表）与系统库，**与改动前完全一致**。
- **代码侧**：`tables.py` 删掉整个 MySQL 章节（导入 / 只读查询 / 引擎判定 / 校验器 / CLI 开关），
  元数据读取、`table_info`、召回索引、`query`、`stats` 全部回到纯 SQLite；列名上限从 62
  （当年为 MySQL 标识符留的余量）恢复为 80。`agent.py` 删除镜像表名映射，`list_database_tables` /
  `database_status` 恢复只报三个业务库，System Prompt 去掉「当前引擎」注入，
  `describe_table` / `query_tables` 恢复 SQLite 方言说明与「这些表不在 MySQL 里」的边界。
- **配置 / 文档**：`.env.example` 移除 `TABLE_MYSQL_DB` / `TABLE_ENGINE`；
  README 删除「也放进你自己的 MySQL（镜像库）」小节，链路图、边界说明、实测与易错点全部恢复为 SQLite 口径。
- **技能卡**：`skills/tables/` 四张卡改回 SQLite 方言（双引号、`substr`、整除陷阱），并**重新实跑核验**。
- **回归**：索引重建 787 张表 / 120,328 行；技能卡模板复跑一致（信用利差 **-2.86%**、咖啡 **Latte 25 笔 / 991.0**）；
  端到端两条全中；`/api/health`、`/api/skills`（7 张卡）、首页均正常；
  全仓库 `grep mysql` 仅剩本条记录。**注意：这是今天早些时候「试做 MySQL 镜像」的回退**，
  表格数据的唯一存放处仍是 `data/tables.sqlite3`。

### 2026-09-18（新增：非结构化表格库 —— 解析 + AI 查询 + 技能卡）

> 需求：把 非结构化数据/ 目录里的数据解析出来，并让它也能通过 AI 查询；技能做完整。

- **新增 `tables.py`（解析 + 查询引擎，零新依赖）**：把 `非结构化数据/*-数据.md` 里
  `=== 表id ===` 分块中的 **markdown 管道表 / HTML 表格**解析成结构化数据并落进 SQLite
  （`data/tables.sqlite3`）：**787 张表 / 120,328 行**，构建约 5 秒、索引约 13 MB。
  - 切块 → 围栏识别（markdown / html）→ 表格解析 → **数值清洗** → 列名归一 → 入库（每源表一个 `t_<表id>` + 元数据表 `_tables`）；
  - 数值清洗实测规则：`$ 100.00→100`、`1,234.5→1234.5`、`23%→23`、`(6.5)→-6.5`、`-6.5 ( 6.5 )→-6.5`；
    只对「可解析比例 ≥ 80% 且至少 2 个」的数值列生效（阈值取 2 是因为评测集里有大量 2~3 行的小表）；
  - 列亲和性 `NUMERIC` / `TEXT` 分开，避免 `01234` 被吃成 `1234`；
  - **只读安全**：`file:...?mode=ro` 只读连接 + 单条 SELECT/WITH 白名单，ATTACH / PRAGMA / 写语句全部拒绝；
  - 召回带 **IDF 加权**（年份这类到处都是的词权重低，jpmorgan / Latte 这类稀有词权重高）+
    **分隔符归一**（`cash_type` 也能被 “cash” 命中），并滤掉提问功能词（第一 / 年的 / 哪个）；
  - 命令行：`--build / --sets / --find / --info / --sql / --questions`，不调用模型也能用。
- **Agent 接入四个工具（工具数 17 → 21）**：`list_table_sets / find_table / describe_table / query_tables`，
  与 MySQL 那套镜像（`get_table_schema ↔ describe_table`、`execute_sql ↔ query_tables`）。
  中文问题在召回不足时**自动补一轮英文关键词**再检索（表格内容以英文为主），结果里会标注用过的关键词；
  问题里带 15 位表 id 时**精确直达**。
- **System Prompt**：新增「非结构化表格规则」——五步流程 + 明确边界（**这些表格不在 MySQL 里**，
  问业务库走 execute_sql，问这批表格走 query_tables，别串门）；工具清单仍由 `TOOLS` 自动生成。
- **技能卡做完整（`skills/tables/` 四张）**，并**与业务库技能卡合并进同一套机制**：
  `get_db_skill` 现在两族都能加载（`_match_skill` 统一解析），`/api/skills` 与网页「数据技能卡」下拉
  自动多出 4 项（`guide / table_query / domain_ops / multi_step`），手动指定表格数据集时会注入对应的强制指令。
  - `guide.md`：库结构、表 id 规则、清洗约定、标准流程、**实测易错点**、通用模板 SQL；
  - `table_query.md`（500 张小表特点）、`domain_ops.md`（年份写在列名里 / 算术模板）、
    `multi_step.md`（大表注意事项与三大主题聚合模板）；
  - 卡片里的模板 SQL **全部实跑核验**后写入。
- **两个实测踩到的坑（已写进卡片与 README）**：
  ① **整除陷阱** —— SQLite 里 `(34-35)/35*100` 得 **0**，必须 `*100.0`；
  ② **引号标识符陷阱** —— 列名写错时 SQLite 把 `“不存在的列”` 当字符串字面量，**不报错但结果全错**。
- **实测**：解析 787 张表 / 120,328 行无失败；只读校验拦截全部写语句；
  **与评测集参考答案一致**（信用利差 2011→2012 = **-2.86%**，与 `样例答案.json` 相同）；
  端到端问答三条全中：表 id 直达算百分比变化、`predicate` 列识别、自由提问「现金支付卖得最多的咖啡」
  → 自动 find_table → query_tables → **Latte 25 杯 / 991.00 元** + 排名表。
- **依赖**：只用标准库 `sqlite3`（**不再需要 pandas**），requirements.txt 无变化。
> 注：本条做完后还试过「把 787 张表整库导入 MySQL 镜像库」，按需求**已回退**——
> 详见本节顶部「撤回：表格数据不进 MySQL」一条。

### 2026-09-18（修复：多进程并发写会话元数据会把会话整条弄丢）

- **现象**：网页服务（`python web.py`）与命令行 / 脚本会**同时**读写 `data/conversations.json`，
  而每次写盘都是**整文件覆盖**——谁最后写谁赢，先写入的那些会话会被后写入的进程整条抹掉，
  表象就是「会话列表里怎么少了一个会话」。
- **修复**：`ConversationStore` 新增 `_reload()`，`create / update / delete / list` 在加锁后
  **先重新读一次磁盘再改动**，只保留本进程这次的修改：最多丢「同一会话的并发字段更新」，
  不会再丢整个会话；`list()` 也顺带取磁盘最新，长时间运行的服务不会显示陈旧列表。
  磁盘文件损坏或读失败时**保持内存里的版本**，绝不因为一次读失败就把别人的会话清空。
- **回归**：用两个 `ConversationStore` 实例模拟两个进程——A 建、B 建、A 改自己的、A 删自己的，
  四步都验证 B 的会话仍在；把文件写成非法 JSON 后 `list()` 仍返回内存中的会话。

### 2026-09-18（人性化改版：说话方式 + 交互体验）

> 需求：优化更人性化。

- **回复风格重写（`agent.py` 的 `_BASE_PROMPT`）**：从原先的「只呈现结果 + 结论，不要反问」升级为
  ①先结论后依据 ②说人话（解释数字背后的涨跌与含义，给实在建议）③禁止机器味（不复述问题、不罗列执行步骤、
  不出现 SQL / 工具名 / 分析小标题）④开头最多一句自然承接、记忆里有称呼可偶尔叫一次
  ⑤结尾最多一个自然的下一步建议（不每轮问、不连问）⑥拿不准就如实说明并给替代方案
  ⑦问候贴合当前时间 ⑧表情只在闲聊里偶尔用。**反啰嗦的红线一条没丢**（禁复述、禁步骤、禁内部信息）。
- **生成中进度说人话**：新增 `TOOL_LABELS` + `tool_label()`，把工具名映射成
  「正在查询业务数据库 / 正在翻知识库文档 / 正在跑预测模型 / 正在把这件事记下来…」，
  以 `tool` 事件的 **`label` 字段**下发（老前端不认识就忽略，向后兼容）；
  网页上显示成一枚带呼吸灯的胶囊（`.ai-status`），出字后自动收起，不再出现 `execute_sql` 这类内部名字。
- **空状态按时间问候（`index.html`）**：凌晨 / 早上 / 上午 / 中午 / 下午 / 晚上 / 深夜七档，
  标题与副标题一起换（如「下午好，我是九天梧桐 / 下午适合出结论，要不要我先把数据整一整？」）。
- **友好报错**：中止 → 「已经停下了，想继续或换个问法都行」；出错 → 一句人话 + **一句该怎么办**
  （确认服务在运行再重试），技术细节以小字附在后面；模型没吐内容时也不再是「（模型没有返回内容）」，
  而是「我这次没组织出回答，换个问法或再说一次试试？」；首页连不上后端时的提示也改成
  「暂时连不上后端 + 怎么恢复 + 技术细节」。深度搜索路径的报错同步改成人话。
- **会话标题更像人写的**：`make_title()` 先剥掉「帮我 / 请 / 麻烦 / 能不能 / 我想」等客套开头与结尾标点，
  再截断——「帮我算一下 123*456 等于多少？」→ 侧栏显示「算一下 123*456 等于多少」。
- **计划提示更口语**：制定计划的提示由「正在制定执行计划…（含多步骤动作：…）」改为
  「让我先把这件事理成几步…」（内部判断依据仍保留在 `plan` 事件里）。
- **文档**：README 新增 [3.6 人性化细节](#36-人性化细节说话方式与交互)（说话方式 / 人味 / 诚实兜底 /
  表情 / 进度文案 / 问候 / 报错 / 标题 一览，并说明「想改语气只改回复风格段落」）。**无新增依赖**。
- **实测**：问「上月医疗库总收入是多少？」→「**查到了。**按就诊口径……说明一下：库里最新数据到 11/29，
  所以『上月』我按最近一个完整月份算……要不要我顺手把结算口径的净额也拉出来对比？」（339 字，
  先结论 + 讲清假设 + 一个自然的下一步）；问「你好呀，你在忙什么？」→ 结合当前时间的自然闲聊（90 字）。
  工具标签、标题剥离、`node --check`、`py_compile` 均验证通过。

### 2026-09-18（移除「非结构化数据表格智能体」`uds_agent/`）

> 需求：去掉非结构化数据智能体。

- **删除 `uds_agent/` 整个包**（dataset / retriever / solver / llm / tools / cli / ui / ui.html 等 10 个文件），
  连同它的 Web 操作台、CLI 与批量评测入口。本机本来就没装 `pandas`，`UDS_ENABLED=False`，
  这套能力此前**并没有真正生效**（`TOOLS` 一直是 17 个），所以主站功能零影响。
- **`agent.py` 回退 5 处**：① 顶部 `try: from uds_agent.tools import UDS_TOOLS` 整块（含 `UDS_ENABLED`）；
  ② `TOOLS` 末尾追加的 4 个表格工具；③ `uds_summary()` 函数；④ System Prompt 里的「非结构化表格规则」段落；
  ⑤ `/api/health` 返回体里的 `"uds"` 字段。
- **`web.py`**：移除 `uds_agent.ui` 蓝图注册；`/uds/` 与 `/uds/api/*` 全部下线（现在返回 404）。
- **`index.html`**：移除侧栏「非结构化数据表格」入口及其样式、首屏「非结构化表格问答」能力标签、
  表格反事实示例问题；侧栏脚注恢复为「3 个 MySQL 业务库 · RAG 知识库 · Sklearn 预测 · 跨会话记忆」。
- **README**：删除第 7 节「非结构化数据智能体」与两条对应更新记录；原 §8 常见问题、§9 更新记录
  顺延为 §7 / §8；项目结构里的 `uds_agent/`、`非结构化数据/`、`reports/uds/` 条目一并移除。
- **工具数**：当时为 **17 个**（数据库直查 / 知识库检索 / 出图 / sklearn 预测 / 规划 / 记忆）；
  同日晚些时候新增了 4 个非结构化表格工具，现为 **21 个**（见本节上方「非结构化表格库」一条）。
- **数据保留**：`非结构化数据/`（三份评测集 + 样例答案，约 12MB）**没有被删除**，仍在项目根目录；
  要一起清掉直接删该目录即可。被移除的代码与运行产物已整体备份到
  `data/_removed_uds_agent_20260918/`（`data/uds/` 索引缓存、`reports/uds/` 批量答题结果），
  确认无误后可自行删除这个备份目录（`uds_agent/` 与 `非结构化数据/` 从未被 git 跟踪，删了就找不回）。
- **验证**：`py_compile` 全部通过；`agent.TOOLS` = 17；`import web` 正常；`/` 与 `/api/health`
  正常、`/uds/` 返回 404；前端 `node --check` 通过；仓库内 `grep uds / 非结构化` 零命中。

### 2026-09-18（前端改版为豆包风格 + 全项目体检）

- **前端改版（index.html，纯样式、零功能变更）**：由原先的绿 / 蓝紫主题整体换成**豆包风格**
  （Arco 色板）：主色 `#165DFF` 蓝色渐变、品牌 logo 改为圆形渐变（侧栏 30px / 空状态 68px）、
  侧栏底 `#F7F8FA`、会话项选中淡蓝底 `#F2F7FF`、AI 回答改为浅灰圆角卡片（14px）、
  用户气泡改为蓝色渐变 + 「右下小尖角」大圆角（16px）、输入框改为 16px 大圆角白卡
  （聚焦蓝色描边 + 淡蓝光圈）、发送 / 停止按钮改为圆形、「显示过程 / 深度搜索 / 数据技能卡」
  改为胶囊控件、代码块改深色 `#1D2129`、表格去掉斑马纹并改浅灰表头、
  执行计划与深度搜索面板统一淡蓝底、空状态改为大圆 logo + 淡蓝能力胶囊 + 两列建议卡片；
  深色模式 token 同步换肤，favicon 换成同款蓝色渐变圆形。
  所有变量集中在样式表末尾「豆包风格」一段，后续换肤只改这一段；**事件协议、接口与 JS 行为零变更**。
- **viz.py 配色同步**：图表色板改为与主界面一致的 Arco 色（`#165DFF / #00B42A / #FF7D00 / …`），
  历史线 / 预测线 / 网格 / 注释灰同步替换，预测报告里的趋势图与网页风格统一。
- **项目体检结果**：`py_compile` 对 7 个脚本全部通过；`python planning.py` 离线自测通过；
  Flask 测试客户端冒烟 `/`、`/api/health`、`/api/conversations`、`/api/skills`、`/api/memory` 均 200，
  `database` 显示三个业务库已连、`rag` 就绪、`key_configured=true`；`.gitignore` 确认覆盖 `.env / data/ / reports/`。
- **修复依赖缺失**：原环境**未安装 matplotlib**（requirements.txt 已声明），会导致出图工具、
  预测报告趋势图与聊天里的图表一直为空；已补装 `matplotlib 3.11.2`，`viz.plot_query` 实测出图成功。
  （`viz.py` 的 basedpyright 类型告警为改动前既有，非本次引入。）

### 2026-09-18（Agent 架构升级：LLM + Planning + Tool use + Memory）

- **新增 `planning.py`（规划引擎，Planning）**：纯逻辑模块，自己不调用 LLM（模型调用由
  `complete` 回调注入，agent.py 传的是 `_llm_complete`），提供四件事：
  ① 计划状态机 `Plan` / `PlanStep`（待办 / 进行中 / 已完成 / 已跳过 / 失败、进度、
  按序号或标题关键字定位、反思时追加步骤）；② 提示词构造（任务拆解 / 执行自检 / 深度搜索拆解）；
  ③ 容错解析（代码围栏、前后解释文字、对象与数组混写、一行一条、中英文状态词都能认）；
  ④ 启发式 `needs_plan()`（多步骤 + 分析类 + 多对象等特征累计 ≥3 分才规划）。
  `python planning.py` 可离线自测启发式、解析与状态机，**零 API 费用**。
- **agent.py 接入规划闭环**：`stream_ask()` 现在是
  「记忆压缩 → 规划 → ReAct 执行 → 自检补漏 → 落盘」五步链路：
  - 复杂任务先由规划器拆成 2~6 步并注入 System Prompt；模型每完成一步调用新工具
    `update_plan` 勾选，后端比对状态变化后以 `plan_step` 事件实时推送进度；
  - 终答轮由自检器 `planning.reflect()` 核对「计划是否真的完成」，未完成则把自检意见作为
    **一次性提醒**注入下一轮补做（`PLAN_MAX_REFLECT` 默认 1 次；提醒不写入对话历史，
    界面上不会凭空多出一条用户消息）；
  - 说「继续 / 下一步 / 按计划」会沿用上一轮**未完成**的计划（进程重启导致内存注册表清空时，
    由新增的 `restore_plan()` 从会话元数据恢复）；计划与进度落盘到会话元数据，
    刷新 / 重开页面后由 `/api/conversations/<id>/messages` 带回来；
  - 规划 / 自检 / 摘要任何一步失败都**安静降级**为原流程，绝不打断对话。
- **新增两个规划工具**：`plan_task(goal, steps)`（登记或替换执行计划）、
  `update_plan(step, status, note)`（勾选步骤，step 支持序号或标题关键字）。
  System Prompt 里的工具清单改为由 `TOOLS` 自动生成，杜绝「提示词写一份、注册表另一份」的漂移。
- **记忆升级（Memory）**：`remember` 增加 `kind`（fact/preference/task/other）与 `tags`，
  **内容重复自动合并**（刷新时间 + 提升重要度，不再堆积副本）；`recall(query)` 支持按相关度召回
  （中文按「字 + 双字词」重叠打分，复用 `rag.tokenize`），返回类型 / 标签 / 相关度 / 时间，
  并累计使用次数；新增 `forget(target)` 按内容片段或 key 删除记忆。
  **新增第三层记忆——长会话滚动摘要**（`MEM_COMPACT`，默认超过 40 条消息触发、保留最近 12 条原文）：
  早期对话压成**增量**摘要 + 最近原文发给模型，上下文不再越聊越长；Checkpointer 里的完整历史
  一条都不删；摘要生成失败会退回全量历史（宁可长一点，也不丢上下文）。
- **重合功能合并（不重复造轮子）**：
  - `ask()` 不再单独走 `create_agent.invoke()`，改为复用 `stream_ask()` 同一执行引擎
    （把 token 拼成完整回答），命令行 / demo / 网页三个入口行为彻底一致；
    `create_agent` 仅保留用于 Checkpointer 的状态读写（`get_state` / `update_state`）；
  - 深度搜索的「拆子问题」（`_deep_plan_queries`）与「查漏补缺」（`_gap_fill_queries`）
    统一到 `planning.research_queries()` / `planning.gap_queries()`；
    `_extract_string_list`、`_strip_code_fence` 合并到
    `planning.parse_string_list()` / `planning.strip_code_fence()`；
  - `stream_ask` 里内联的备用渠道选择改为复用现成的 `_next_backup_provider()`；
  - 默认会话元数据仓库改为模块级单例（`default_conversation_store()`），
    避免多实例各持一份内存缓存互相覆盖。
- **Web / 界面**：`/api/chat`、`/api/deep` 事件协议**向后兼容**地新增
  `thinking` / `plan` / `plan_step` 与 `done.plan`（老前端忽略未知类型即可）；
  `/api/conversations/<id>/messages` 额外返回该会话最近的 `plan`；
  `/api/memory` 支持 `?q=关键词` 相关度检索；`/api/health` 新增 `planning` 与 `memory` 两段概况。
  网页新增**执行计划面板**（目标 + 步骤 + 进度条 + 逐步状态），刷新页面会从会话元数据恢复；
  简单问题不出现面板，界面与旧版完全兼容。
- **文档 / 配置**：README 新增 [3.5 Agent 架构](#35-agent-架构llm--planning--tool-use--memory)
  （链路图、四种能力落点、规划细节、参数表），补充三层记忆、事件协议与项目结构；
  `.env.example` 新增 3.2（规划）与 3.3（记忆）两节。**无新增第三方依赖**。
- **实测**：`python planning.py` 离线自测通过；端到端验证「简单问题不规划（1.3s 直接回答）」、
  「复杂问题自动规划 4 步并逐步勾选完成」、「自检返回 continue 后确实补做了新一轮且提醒未写入历史」、
  「跨会话记忆写入与召回」、「长会话摘要生成 + 第二次复用缓存」、「`PLAN_MODE=off` 回到老行为」、
  「Web：`/api/chat` 完整事件流、历史带 plan、`/api/memory?q=`、`/api/skills`、`/` 均 200」、
  「命令行 `--stream` 与 `--deep` 正常」。
- **改名**：助手名称由「文浩 AI」统一改为 **九天梧桐** ——浏览器标题「九天梧桐 AI 工作台」、
  侧栏品牌「九天梧桐 AI 助手」与图标单字（浩 → 梧）、空状态问候语、输入框提示语、
  每条回复的身份标签与头像、网页 favicon（内联 SVG 文字 梧）、
  命令行与启动脚本的日志前缀 `[九天梧桐]`，以及 System Prompt 里的身份
  （问「你是谁 / 你叫什么」会回答九天梧桐）。纯改名，**接口、事件协议与功能行为零变化**。

### 2026-09-10（知识库扩充：三库 NL→SQL 各 +40 条）

- **新增样例共 120 条**：金融 `#287–326`、医疗 `#215–254`、通信 `#200–239`，
  全部在本机 MySQL 8.0.21 **逐条实跑通过**（含 CTE 与窗口函数）。
- **覆盖类型**：多表 JOIN、分组 Top-N、占比 / 比率、同比 / 环比、条件聚合（CASE WHEN）、
  去重计数、分桶 / 区间、时间窗口与日期函数、HAVING / NULL / 异常值排查、CTE / 子查询；
  每库含 ≥6 条口语化问法（如"哪个医生最忙""谁欠费最多""哪个套餐最受欢迎"）。
- **实测口径与坑（已写入对应样例题目，供检索命中）**：
  - 金融库：MySQL 8.0.21 下 `LEFT JOIN … WHERE t.x IS NULL` 反连接经 hash join 会返回错误结果，
    改用 `NOT EXISTS`（样例 320 注明）；`trader_id` 与 `managers.manager_id` 无交集；
    `credit_rating` 实际取值仅 BBB / A / BB / D / A+ / CCC / B / AA；
  - 医疗库：数据止于 2025-11，凡以 `CURDATE()` 为基准的就诊类窗口必为空，
    改用表内最新时间锚定（样例 237/238/241）；`current_quantity ≈ 5 × reorder_level`，
    "低于再订货线"类问法必为空集（样例 254 注明）；`doctor_id` 关联全量人员（含护士/技师），
    需叠加 `job_title LIKE '%医师'`；
  - 通信库：账单 / 详单最新时间早于当前日期，动态窗口以最新账期锚定（样例 230/231/232）；
    账单表号码与套餐号码仅有部分相交（样例 200 注明）。
- **效果**：上述难题的检索命中由"旧样例 / 部分相关"变为**直接命中对应新样例**
  （如"每个客户经理名下客户的总资产排名"→ #294/#287；"各科室收入占比"→ #249；
  "谁欠费最多"→ #202；"每个套餐的用户数和账单总额对比"→ #200）。
- **README**：§4.2 的样例条数由"680 道"更正为三库合计 819 条（金融 326 / 医疗 254 / 通信 239）。

### 2026-09-09（Matplotlib 可视化 + 报告出图）

- **新增 `viz.py`**：Matplotlib 可视化模块（懒加载，中文标题、Agg 出图）——
  `plot_forecast()` 画"历史 + 预测"趋势图；`plot_query()` 把查询结果画折线/柱状图；均输出 `reports/*.png`。
- **预测报告自动出图（ml_forecast.py / predict.py）**：每次运行都会在 `reports/` 生成趋势图 PNG，
  并嵌入 Markdown 报告头部（`![…](图表.png)`）；聊天触发与命令行都会在返回里带上图名。
- **对话结果可视化（agent.py）**：`execute_sql` 自动记住最近一次查询结果；新增工具
  `plot_last_result(title, x_col, y_cols)` 据此画图并返回图片引用；System Prompt 写入
  “要画图先查数再 plot_last_result、回复引用图片地址”的规则，已加入工具注册。
- **Web（web.py / index.html）**：新增 `/reports/<文件>.png` 静态接口（只放行顶层 png、防穿越）；
  前端 Markdown 渲染支持图片（同源 `/…` 或 http(s)，转义防注入）并增加图片样式。
- **依赖**：requirements.txt 新增 `matplotlib>=3.8`；README 同步 4.2/4.3/项目结构/依赖说明。

### 2026-09-09（检查修复）

- **安全修复（agent.py）**：`calculator` 由 `eval` 沙箱改为 **AST 白名单求值**（堵属性链逃逸导致的任意代码执行）；
  SQL 只读校验先剥离字符串 / 注释 / 反引号标识符再查关键字与分号（修复 `SHOW CREATE TABLE` 等误杀、
  字符串含 `;` 的误判），危险关键字补充 `load_file` / `sys_exec` / `sys_eval`；
  `_env_flag` 修复 `default=True` 时 `DEEP_ROUND2=0` / `DEEP_RERANK=0` 无法关闭的问题。
- **bug 修复（index.html）**：修复表格渲染引用未声明变量 `headDone` 导致的报错（含 Markdown 表格的回答会渲染失败）；
  健康徽标改为按 `/api/health` 实际返回解析（`database.{ok,databases}` / `rag.{enabled,built,backend}`），
  并改用 textContent 节点拼接。
- **配置（web.py）**：`FLASK_DEBUG` 默认关闭（原默认开启调试器），开发时用 `FLASK_DEBUG=1`。
- **文档（README）**：删除 §4.2 重复段落、工具数量改为四个、`database` 字段描述对齐实际结构。

### 2026-09-09

- **Web 界面全面改版（index.html）**：全新现代视觉 ——
  - 新增 **深色 / 浅色主题切换**（右上角按钮，偏好存 localStorage，刷新不闪烁）；
  - 聊天区柔和渐变光斑背景、AI 回复呈毛玻璃卡片、用户消息渐变气泡、消息入场动画；
  - 顶栏新增 **后端健康徽标**（实时显示 `x/3` 库已连、RAG 就绪状态），侧栏底部同步服务状态灯；
  - AI 回答支持**一键复制**（悬停显示）；Markdown **代码块带语言标签 + 复制按钮**；
  - 表格斑马纹 / 悬停高亮、新增 `blockquote` 引用与删除线样式；
  - 空状态改为能力徽章 + 建议问题分组；会话列表显示数量角标；
  - 界面全量改为 **CSS 变量驱动**，颜色统一走主题变量，便于后续换肤；
  - 全部图标用内联 SVG（无外部 CDN），功能与旧版完全兼容（接口契约不变）。
- **NL→SQL 关键词抓取工具 `analyze_query`（agent.py）**：新增按业务库分组的口语词表
  （通信 / 金融 / 医疗各 40+ 个领域词并分权重）、表级线索、12 组“口语说法 → 真实字段口径”术语对照、
  10 组动作 / 时间写法提示；问句口语化或拿不准库 / 表 / 字段时，先调用它抓“关键字 + 关键提示词”再写 SQL。
- **System Prompt（agent.py）**：写入流程规则“先 `analyze_query(问题原文)` 抓词 → 再按返回加载技能卡、核对表结构”，
  并把 `analyze_query` 加入工具注册清单。
- **查询技能卡（skills/database/）**：三张技能卡各追加 6 条“口语说法 → 正确落点（列名均核验）”对照。
- **知识库问答语料（knowledge/）**：三份“自然语言查询转 SQL 问答”各追加样例：
  通信 `#195-199`、金融 `#283-286`、医疗 `#211-214`（共 13 条，均为高频口语变体），
  所有新增 SQL 已在本机 MySQL 实跑验证通过。
- **README**：新增本节“更新记录”，此后每次改动都同步记录到本节顶部。
