# 非结构化表格技能卡：查询指南（guide）

> **核验声明**：本卡所有数字与模板 SQL 均在本地解析结果（sqlite3，787 张表 / 120,328 行）上**实跑核验**（核验日期 2026-09-18）。
> 解析产物：`data/tables.sqlite3`（由 `tables.py` 从 `非结构化数据/*-数据.md` 生成，可用 `python tables.py --build` 重建）。

## 1. 这个库是什么

`非结构化数据/` 下三份评测集里是 **markdown 管道表 / HTML 表**混排的文本，`tables.py` 把它们解析成结构化数据：

| 概念 | 说明 |
| --- | --- |
| 表 id | 源文件里 `=== 表id ===` 的 15 位十六进制串；**评测题 JSON 里的 `id` 就是表 id** |
| 物理表名 | `t_` + 表 id，例如 `t_b40962fe65f24d9` |
| 元数据表 | `_tables`（可直接用 SQL 查）：`table_name / source_id / dataset / dataset_title / n_rows / n_cols / columns / numeric_columns / is_html / source_file` |
| 数值列 | 解析时已清洗成**真正的数字**：`$ 100.00`→`100`、`1,234.5`→`1234.5`、`23%`→`23`、`(6.5)`→`-6.5`；`describe_table` 会列出哪些列是数值列 |
| 文本列 | 日期、名称等原样保留（日期是 ISO 文本，可直接 `substr()` / 字典序比较） |
| 行数分布 | 1–3 行 143 张、4–20 行 556 张、21–200 行 64 张、201–2000 行 15 张、2000 行以上 9 张（最大 13,200 行） |

## 2. 三个数据集（实测规模）

| key | 数据集 | 表数 | 行数 | HTML 表 | 典型问题 |
| --- | --- | --- | --- | --- | --- |
| `table_query` | 表格查询（Table_Query） | 500 | 6,279 | 151 | 某列叫什么、第一行第一格是什么、按取值找行 |
| `domain_ops` | 领域运算（Domain-specific Operations） | 239 | 2,563 | 68 | 同比/环比/占比/变化率等**算术**题 |
| `multi_step` | 多步检索（Multi-step Retrieval） | 48 | 111,486 | 12 | 大表上的多步筛选聚合、反事实假设、Top-N |

## 3. 标准查询流程（五个工具，**先分析再召回**）

1. `list_table_sets()` —— 确认数据范围（三个数据集的规模）。
2. `analyze_table_query(问题原文)` —— **本地规则分析（不花模型钱）**，一次给出四件事：
   数据集判定（该查 tq / ops / msr 哪个）、**中文术语 → 英文检索词**、题型 → 推荐 SQL 写法、坑提示。
3. `find_table(question=原文, dataset=第②步建议, keywords=第②步给的英文词)` —— 定位候选表。
   - 问题里带表 id（15 位十六进制）会**精确命中**（不需要靠关键词猜）；
   - 没给 keywords 时内部会自动做中文术语扩展；召回仍然弱时才会调一次模型补英文关键词。
4. `describe_table(table='t_xxxx')` —— 看**完整列名**、数值列、行数、前 3 行。
5. `query_tables(sql='...')` —— 只读 SQL 取数（单条 SELECT / WITH）。

> 实测精度（用评测集 787 道「问题 → 表 id」标注题做留出集测量）：
> 只靠关键词 **top1 22% / top5 39%**；加中文术语表与元语言过滤后 **top1 24% / top5 42%**；
> 再加一轮 LLM 关键词兜底可达 **top1 33% / top5 53%**。
> 对照之下，**问题里直接给表 id 时是 100% 命中** —— 所以拿不准就先把表 id 告诉它，或让用户从评测题里带 id 提问。


> 也可以用 `query_tables` 直接查元数据表按列名找表（实测可用）：
> ```sql
> SELECT table_name, dataset, n_rows, columns FROM _tables WHERE columns LIKE '%coffee%' LIMIT 5;
> ```

## 4. 易错点（都是实测踩过的）

| # | 坑 | 正确做法 |
| --- | --- | --- |
| 1 | **整数除法**：SQLite 里两个整数相除是整除，`(34-35)/35*100` 得 **0**，不是 -2.86 | 比值先乘浮点：`(a-b)*100.0/b`，或 `CAST(x AS REAL)` |
| 2 | **列名写错不会报错**：SQLite 把不存在的双引号标识符当**字符串字面量**，静默返回错误结果 | 列名一律**照抄** `describe_table` 的返回，不要凭印象拼 |
| 3 | 列名含空格/括号/中文/纯数字（`( in millions )`、`cash_type`、`"0"`、`"2015"`） | 一律用双引号包起来 |
| 4 | 大表 `SELECT *`（最大 13,200 行） | 先 `WHERE` / `GROUP BY` 聚合；`query_tables` 默认只回 100 行并提示截断 |
| 5 | 同名列集合的表非常多（**210 张**表列名都是 `0/1`，**105 张**是 `subject/predicate/object`） | 用问题里的**特征值**（专有名词、数值）或直接给表 id 定位 |
| 6 | 表内容以**英文**为主，中文提问直接检索命中率低 | 用 `find_table`（会自动补英文关键词），或直接给表 id |
| 7 | 这些表格**不在 MySQL 里** | 不要用 `execute_sql` 查它们；三个业务库的问题也不要用 `query_tables` |
| 8 | 同一份数据在数据集里可能出现多次（4 张咖啡表列名与行数完全相同） | 任选一张即可，或按 `n_rows` / `col1` 特征确认是哪一份 |

## 5. 通用模板 SQL（已实跑）

```sql
-- ① 看某张表的样子（小表可用；大表请加 LIMIT）
SELECT * FROM t_2646e8725e97437 LIMIT 3;

-- ② 按列名找表（元数据表可查）
SELECT table_name, dataset, n_rows, columns FROM _tables WHERE columns LIKE '%coffee%' LIMIT 5;

-- ③ 数据集规模盘点
SELECT dataset_title, COUNT(*) AS tables, SUM(n_rows) AS rows FROM _tables GROUP BY dataset;

-- ④ 某列的去重取值（先看口径再算数）
SELECT DISTINCT "cash_type" FROM t_05ab28a47b924ae;
```
## 6. 口语说法 → 检索词 / 写法（全局，细分见各数据集卡）

| 用户可能这么说 | 英文检索词（传给 find_table） | 落到哪 / 怎么写 |
| --- | --- | --- |
| 咖啡 / 现金 / 刷卡 / 拿铁 | coffee / cash / card / latte | 咖啡流水表（见 `multi_step` 卡） |
| 气象 / 温度 / 湿度 / 风速 | weather / temperature / humidity / wind | 气象大表（13,200 行） |
| 新能源 / 车型 / 动力类型 | powertrain / ev / mode | powertrain 大表（12,654 行） |
| 净收入 / 营收 / 利差 / 基点 | net income / revenue / spread / basis point | 财报类两列表（见 `domain_ops` 卡） |
| 保险 / 保费 / 理赔 | insurance / premium / claim | 保险类表（中文列名为主） |
| 地区生产总值 / GDP | gdp / gross domestic product | 地区经济表（中文列名） |
| 哪一列 / 第一行 / 某个单元格 | ——（用列名直接选） | 见 `table_query` 卡 |
| 年份 / 季度 / 月份 / 日期 | year / quarter / month / date | 时间列多为 ISO 文本，可直接字典序比较 |
| 占比 / 百分比 / 比重 | percent / share | `SUM(部分) * 100.0 / SUM(整体)` |
| 同比 / 环比 / 增长 / 变化率 | yoy / mom / growth | 先取两个数再 `(v2-v1)*100.0/v1` |
| 最多 / 最少 / 排名 / 前 N | top / most / rank | `ORDER BY 数值 DESC LIMIT N` |
| 每个 / 各 / 按… | group / by category | `GROUP BY 维度列` + 聚合 |
| 合计 / 一共多少钱 | total / sum | `ROUND(SUM(金额列), 2)` |
| 假设…没有发生 | ——（反事实） | 先定位事件明细，剔除后重算 |

> 这份对照也可以让 Agent 现算：`analyze_table_query(问题)` 会用同一套本地规则给出「数据集 + 英文检索词 + 题型写法」。

