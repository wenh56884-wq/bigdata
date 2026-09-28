# 换电脑迁移指南（九天梧桐 AI 工作台）

> 依据 2026-09-22 实际换机经历整理：当时从旧电脑（用户目录 `C:\Users\你的旧用户名`）迁到本机（`C:\Users\你的用户名`），
> 踩过的坑都记录在下面。按本文顺序操作即可平滑迁移。

## 迁移更新记录

### 2026-09-28：侧栏高度与滚动约束

- `app/index.html` 的桌面侧栏 `.side` 增加 `height: 100%`，与根布局的 `100vh` 高度保持一致。
- 增加 `min-height: 0`，避免纵向 flex 子项的默认最小高度把侧栏内容撑出视口。
- 增加 `overflow-y: auto`（并隐藏横向溢出），会话较多时侧栏可以独立滚动，不会挤压右侧聊天区。
- 会话列表 `.conv-list` 原有的 `flex: 1`、`min-height: 0` 和 `overflow-y: auto` 保留，桌面端形成稳定的双重布局约束；窄屏仍按原设计使用横向会话条。

验证：启动 `web.py` 后检查长会话列表，侧栏保持在视口高度内并可独立滚动；聊天消息区不随会话数量增长而溢出。

## 一、要带走的文件（🎒 清单）

| 带什么 | 位置 | 说明 |
| --- | --- | --- |
| ✅ **项目目录** | `比赛、\app\` 整个文件夹 | **但先删掉/排除 `.venv\` 和 `data\`**（见下方"绝对不要带"） |
| ✅ **三个 SQL 数据源** | `比赛、\*.sql`（共约 566 MB） | 没有它们数据库就没有数据；`_import_dbs.ps1` 靠它们重导 |
| ✅ **辅助脚本** | `比赛、\_setup_mysql.ps1`、`_import_dbs.ps1` | 新机装 MySQL / 导数据直接用 |
| ✅ **`.env` 配置文件** | `app\.env` | 含 API Key 与数据库连接配置；⚠️ 是机密文件，勿公开分享 |
| ⬜ 可选 | `app\data\` | 想保留聊天历史 / 记忆就带上（否则全新建） |

### 🚫 绝对不要带的三个东西

1. **`.venv\`** —— 虚拟环境里记录的是旧电脑的 Python 路径，复制过去 **100% 损坏**（这次换机的第一个坑）。
2. **`data\*.sqlite3-wal / -shm`** —— 如果带 `data\`，MySQL/SQLite 的 WAL 临时文件删掉更干净。
3. .env 外的任何缓存（`__pycache__\`、`.pytest_cache` 等），会自动重建。

## 二、新电脑上要装 & 要配（🔧 四步）

### 第 1 步：装 Python（3.10 ~ 3.13，推荐 3.11）

```powershell
py --list          # 检查是否已有；没有就去 python.org 装 3.11.x
```

### 第 2 步：重建虚拟环境 + 装依赖（**换机后必做**）

```powershell
cd "<项目目录>\app"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> ⚠️ **两个关键注意**（都是实测踩过的）：
> ① 装依赖必须用 `.\.venv\Scripts\python.exe` **完整路径**开头，不要用裸 `python.exe`
> （PATH 里的 `python` 可能指向别的环境，包装错地方）；
> ② 校验装没装对：`.\.venv\Scripts\python.exe -c "import langchain, flask; print('OK')"`。

### 第 3 步：装并初始化 MySQL（8.0 或 8.4 均可，不要用 5.7）

```powershell
winget install Oracle.MySQL --accept-package-agreements --accept-source-agreements
```

- winget 版**不会自动初始化**（不建数据目录、不注册服务）→ 用项目自带脚本：
  **管理员 PowerShell** 里运行 `_setup_mysql.ps1`（自动完成：建目录 + 写 my.ini + 初始化 + 注册 `MySQL84` 服务 + 设 root 密码 `123456`）。
- **若新机装的是 MySQL 8.0**：打开 `_setup_mysql.ps1`，把 `$base = "C:\Program Files\MySQL\MySQL Server 8.4"` 里的 `8.4` 改成 `8.0` 即可。
- **想换 root 密码**：脚本里 `$password` 和 `.env` 的 `DB_PASSWORD` **两处都要改**，保持一致。

### 第 4 步：导入三个业务库

```powershell
powershell -ExecutionPolicy Bypass -File "<项目目录>\_import_dbs.ps1"
```

- 自动完成：建库 → 硬链接到纯英文路径（避开中文路径）→ 逐库导入 → **逐表行数核对** → 清理链接；
- 预期结果：每库 8 张表，金融 39.2 万 / 医疗 78.2 万 / 通信 25.3 万行；全程约 8-15 分钟（视磁盘）。

## 三、必须检查 / 可能要改的配置

| 项目 | 位置 | 什么时候要改 |
| --- | --- | --- |
| 数据库连接 | `app\.env` 的 `DB_HOST / DB_PORT / DB_USER / DB_PASSWORD` | 新机 MySQL 端口不是 3306、或密码不是 123456 时 |
| LLM / API Key | `app\.env` 的 `DEEPSEEK_API_KEY` 等 | 换了 Key、或旧 Key 失效时（`/api/health` 的 `key_configured` 可验证） |
| MySQL 版本路径 | `_setup_mysql.ps1` 的 `$base` | 新机装 8.0 而不是 8.4 时 |
| 非结构化数据目录 | `.env` 的 `TABLE_DATA_DIR`（默认即可） | 数据目录改名/搬家时 |

> **代码本身不需要改任何东西**：`core/agent.py`、`services/knowledge/rag.py`、
> `services/datasource/tables.py`、`web.py` 等全部用 `Path(__file__)` 向上回溯定位项目根
> ——根目录文件用 `.parent`，二级包用 `parents[2]` / `.parent.parent.parent`
> ——目录整体搬到哪都能跑（已核查过零硬编码路径）。

> 📁 **注意：代码已按「板块」重组为嵌套包**（见 §七）。若你手上是重组前的旧版本，
> 请先对照 §七 的「模块路径对照表」确认文件位置，再执行下面的验证清单。

## 四、换机后验证清单（✅ 按顺序跑）

```powershell
cd "<项目目录>\app"

# 1. 依赖自检（应输出 OK）
.\.venv\Scripts\python.exe -c "import langchain, langgraph, flask, sklearn, matplotlib, pymysql, dotenv; print('OK')"

# 2. 全包语法自检（应无输出）
.\.venv\Scripts\python.exe -m compileall -q core services eval web.py predict.py build_techdoc.py

# 3. 数据库连通（应显示三个库各 8 张表）
.\.venv\Scripts\python.exe -c "from core import agent; import json; print(json.dumps(agent.database_status(), ensure_ascii=False))"

# 4. 规划引擎离线自测（不花钱）
.\.venv\Scripts\python.exe -m core.cognition.planning

# 5. 非结构化表格索引（如果没带 data\ 或数据有更新；约 5 秒）
.\.venv\Scripts\python.exe -m services.datasource.tables --build

# 6. 启动服务（浏览器开 http://127.0.0.1:5000）
.\.venv\Scripts\python.exe web.py        # 或双击 start_web.bat（入口仍在根目录，无需改）

# 7.（可选）评测冒烟：跑前 3 题
.\.venv\Scripts\python.exe -m eval.nlsql.eval_jiso --limit 3
```

## 五、五个必知的大坑（本次换机实证）

1. **旧 `.venv` 千万别复制**——里面存的是旧机器 Python 绝对路径，必坏（报 `did not find executable`）。
2. **装依赖别用裸 `python.exe`**——VS Code 终端里 PATH 的 python 可能不是 `.venv` 的，包装错地方还不报错（第一轮就中招）。
3. **winget 的 MySQL 只装程序不初始化**——必须手动建数据目录 + `mysqld --initialize-insecure` + 注册服务 + 设密码（`_setup_mysql.ps1` 已封装）。
4. **中文路径要绕开**——工作区路径含「比赛、」等中文时：cmd 重定向导入用**硬链接**（`_import_dbs.ps1` 已处理）；PowerShell 5.1 脚本文件本体不要含中文（UTF-8 无 BOM 会乱码）。
5. **MySQL 只支持 8.0+**——技能卡与模板 SQL 用到窗口函数（`LAG` / `ROW_NUMBER`）与 `utf8mb4_0900_ai_ci` 排序规则，5.7 会挂。

## 六、其它场景提示

- **比赛现场无网络**：LLM 必须联网（知识库检索可离线，但问答不可用）——提前确认网络或热点；
- **Mac / Linux 目标机**：Python/MySQL 照装；命令行把 `.venv\Scripts\` 换成 `.venv/bin/`；`viz.py` 出图的中文字体需另行安装（Windows 默认用雅黑，无此问题）；
- **磁盘空间**：SQL 源文件 566 MB + MySQL 数据约 1.5 GB + Python 环境约 1 GB，预留 **4 GB** 以上；
- **端口冲突**：MySQL 用 3306、Web 用 5000（可用环境变量 `PORT` 改），起服务前确认没被占用。

## 七、代码目录结构（按板块重组后）

代码按「板块」分三层包：同板块的模块收进同一个子文件夹，板块内再按需嵌套。
资源目录（`knowledge/`、`skills/`、`jiso/`、`非结构化数据/`、`data/`、`reports/`）位置不变；
`web.py` / `predict.py` / `build_techdoc.py` 作为入口留在根目录，**启动脚本无需改动**。

```
app/
├── core/                          # ① 核心大脑
│   ├── agent.py                   #   Agent 主控（编排 + 工具注册）
│   └── cognition/                 #   认知板块
│       ├── context.py             #     上下文工程
│       ├── planning.py            #     规划引擎
│       ├── prompting.py           #     提示词工程
│       └── reasoning.py           #     推理（CoT / ToT / MCTS / Reflexion）
├── services/                      # ② 能力服务
│   ├── knowledge/                 #   知识板块
│   │   ├── rag.py                 #     RAG 知识库检索
│   │   ├── vectordb.py            #     向量数据库
│   │   ├── document_ingest.py     #     文档 / 图片解析（PDF、Word、OCR）
│   │   └── knowledge_learning.py  #     知识自动学习
│   ├── datasource/                #   数据源板块
│   │   ├── tables.py              #     非结构化表格解析与查询
│   │   ├── spreadsheet.py         #     Excel / CSV / JSON / Parquet 解析
│   │   ├── table_memory.py        #     表格记忆
│   │   └── uploads.py             #     统一上传
│   ├── analytics/                 #   分析板块
│   │   ├── ml_forecast.py         #     时序预测
│   │   ├── ml_insight.py          #     数据洞察
│   │   ├── pysandbox.py           #     Python 沙箱
│   │   └── viz.py                 #     可视化
│   └── ops/                       #   运维板块
│       ├── sanitize.py            #     输出脱敏
│       ├── observability.py       #     可观测性
│       ├── debugging.py           #     调试
│       └── hitl.py                #     人工介入（HITL）
├── eval/                          # ③ 评测与测试
│   ├── nlsql/                     #   NL→SQL 评测：eval_jiso / _diff_eval
│   ├── accuracy/                  #   准确率与上下文评测：eval_accuracy / eval_context / qa_cases
│   └── tests/                     #   离线单测：_test_eval_core / _test_reason_and_data / _test_spreadsheet / _test_uploads / _test_vectordb
├── web.py                         # Web 入口（start_web.bat 指向它，不用改）
├── predict.py                     # 预测 CLI
└── build_techdoc.py               # 技术文档生成
```

### 模块路径对照（旧 → 新）

| 旧路径（扁平） | 新路径（嵌套包） |
| --- | --- |
| `agent.py` | `core/agent.py` |
| `planning.py` | `core/cognition/planning.py` |
| `prompting.py` | `core/cognition/prompting.py` |
| `context.py` | `core/cognition/context.py` |
| `reasoning.py` | `core/cognition/reasoning.py` |
| `rag.py` | `services/knowledge/rag.py` |
| `vectordb.py` | `services/knowledge/vectordb.py` |
| `document_ingest.py` | `services/knowledge/document_ingest.py` |
| `knowledge_learning.py` | `services/knowledge/knowledge_learning.py` |
| `tables.py` | `services/datasource/tables.py` |
| `spreadsheet.py` | `services/datasource/spreadsheet.py` |
| `table_memory.py` | `services/datasource/table_memory.py` |
| `uploads.py` | `services/datasource/uploads.py` |
| `ml_forecast.py` | `services/analytics/ml_forecast.py` |
| `ml_insight.py` | `services/analytics/ml_insight.py` |
| `pysandbox.py` | `services/analytics/pysandbox.py` |
| `viz.py` | `services/analytics/viz.py` |
| `sanitize.py` | `services/ops/sanitize.py` |
| `observability.py` | `services/ops/observability.py` |
| `debugging.py` | `services/ops/debugging.py` |
| `hitl.py` | `services/ops/hitl.py` |
| `eval_jiso.py` / `_diff_eval.py` | `eval/nlsql/…` |
| `eval_accuracy.py` / `eval_context.py` / `qa_cases.py` | `eval/accuracy/…` |
| `_test_*.py` | `eval/tests/…` |
| `web.py` / `predict.py` / `build_techdoc.py` | **不变**（仍在根目录） |

### 命令行用法随之改变

子包内的模块统一用 `python -m 包.模块` 运行（**必须在 `app/` 目录下执行**，
因为包的根是 `app/`）；根目录入口脚本不变。

```powershell
# 数据源 / 表格
python -m services.datasource.tables --build      # 重建表格索引
python -m services.datasource.tables --stats      # 表格规模统计
python -m services.datasource.spreadsheet 文件.xlsx  # 试解析表格文件

# 知识库
python -m services.knowledge.rag --list           # 查看知识库文档与检索后端
python -m services.knowledge.vectordb --stats     # 向量库状态

# 离线自检（不调用模型、不花钱）
python -m core.cognition.planning                 # 规划引擎
python -m core.cognition.prompting                # 提示词工程
python -m services.ops.sanitize                   # 输出脱敏
python -m services.analytics.ml_insight           # 数据洞察

# 评测
python -m eval.nlsql.eval_jiso --limit 3          # 评测冒烟
python -m eval.tests._test_eval_core              # 判分核心单测

# 问答 / 服务（入口脚本未变）
python -m core.agent "帮我算一下 123*456"           # 命令行问答
python web.py                                     # 启动 Web 服务
python predict.py --db healthcare                 # 预测报告
```

### 重组时同步修好的两类引用

1. **跨模块 import**：全部改为绝对包路径，例如
   `from rag import tokenize` → `from services.knowledge.rag import tokenize`、
   `import agent as ag` → `from core import agent as ag`。
2. **项目根路径**：移进子包的文件层级 +1，`Path(__file__).resolve().parents[1]`
   → `parents[2]`、`.parent.parent` → `.parent.parent.parent`；
   根目录的 `web.py` / `build_techdoc.py` 与 `core/agent.py` 保持原样。

> 已核查：全包 `compileall` 通过；`core.agent`、`web`、`predict` 及全部子模块 import 正常；
> `planning` / `prompting` / `sanitize` / `ml_insight` / `vectordb` 离线自检全部通过。
