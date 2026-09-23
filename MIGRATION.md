# 换电脑迁移指南（九天梧桐 AI 工作台）

> 依据 2026-09-22 实际换机经历整理：当时从旧电脑（用户目录 `C:\Users\你的旧用户名`）迁到本机（`C:\Users\你的用户名`），
> 踩过的坑都记录在下面。按本文顺序操作即可平滑迁移。

## 一、要带走的文件（🎒 清单）

| 带什么 | 位置 | 说明 |
| --- | --- | --- |
| ✅ **项目目录** | `比赛、\agent\` 整个文件夹 | **但先删掉/排除 `.venv\` 和 `data\`**（见下方"绝对不要带"） |
| ✅ **三个 SQL 数据源** | `比赛、\*.sql`（共约 566 MB） | 没有它们数据库就没有数据；`_import_dbs.ps1` 靠它们重导 |
| ✅ **辅助脚本** | `比赛、\_setup_mysql.ps1`、`_import_dbs.ps1` | 新机装 MySQL / 导数据直接用 |
| ✅ **`.env` 配置文件** | `agent\.env` | 含 API Key 与数据库连接配置；⚠️ 是机密文件，勿公开分享 |
| ⬜ 可选 | `agent\data\` | 想保留聊天历史 / 记忆就带上（否则全新建） |

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
cd "<项目目录>\agent"
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
| 数据库连接 | `agent\.env` 的 `DB_HOST / DB_PORT / DB_USER / DB_PASSWORD` | 新机 MySQL 端口不是 3306、或密码不是 123456 时 |
| LLM / API Key | `agent\.env` 的 `DEEPSEEK_API_KEY` 等 | 换了 Key、或旧 Key 失效时（`/api/health` 的 `key_configured` 可验证） |
| MySQL 版本路径 | `_setup_mysql.ps1` 的 `$base` | 新机装 8.0 而不是 8.4 时 |
| 非结构化数据目录 | `.env` 的 `TABLE_DATA_DIR`（默认即可） | 数据目录改名/搬家时 |

> **代码本身不需要改任何东西**：`agent.py / rag.py / tables.py / web.py` 等全部用
> `Path(__file__).resolve().parent` 定位项目根，目录整体搬到哪都能跑（已核查过零硬编码路径）。

## 四、换机后验证清单（✅ 按顺序跑）

```powershell
cd "<项目目录>\agent"

# 1. 依赖自检（应输出 OK）
.\.venv\Scripts\python.exe -c "import langchain, langgraph, flask, sklearn, matplotlib, pymysql, dotenv; print('OK')"

# 2. 全脚本语法自检（应无输出）
.\.venv\Scripts\python.exe -m py_compile agent.py web.py planning.py rag.py tables.py viz.py predict.py ml_forecast.py eval_jiso.py

# 3. 数据库连通（应显示三个库各 8 张表）
.\.venv\Scripts\python.exe -c "import agent, json; print(json.dumps(agent.database_status(), ensure_ascii=False))"

# 4. 规划引擎离线自测（不花钱）
.\.venv\Scripts\python.exe planning.py

# 5. 非结构化表格索引（如果没带 data\ 或数据有更新；约 5 秒）
.\.venv\Scripts\python.exe tables.py --build

# 6. 启动服务（浏览器开 http://127.0.0.1:5000）
.\.venv\Scripts\python.exe web.py        # 或双击 start_web.bat

# 7.（可选）评测冒烟：跑前 3 题
.\.venv\Scripts\python.exe eval_jiso.py --limit 3
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
