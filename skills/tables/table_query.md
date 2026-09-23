# 非结构化表格技能卡：表格查询（table_query）

> 数据集：`Table_Query-数据.md` → **500 张表 / 6,279 行**（HTML 表 151 张），平均 12.6 行，最大 1,420 行。
> 题目文件：`Table_Query_task.json`（500 题，题里的 `id` 就是表 id）。核验日期 2026-09-18。

## 1. 数据长什么样

- 以小表为主：**556/787 张表在 20 行以内**，大量是维基信息框、榜单、时间序列；
- 列名规律（实测统计）：
  | 列名集合 | 张数 | 说明 |
  | --- | --- | --- |
  | `0` / `1` | 210 | 从 HTML 表解析出来的**两列 key-value**（左列是字段名，右列是值） |
  | `subject` / `predicate` / `object` | 105 | 知识图谱三元组（`predicate` = 谓词） |
  | `Year` / `Response` | 50 | 年份—回答/计数 |
  | `date` / `OT` 等 | 若干 | 时间序列 |
- 数值列不多，多数是文本（名称、日期、条目）。

## 2. 典型题型 → 落点

| 问法 | 怎么做 |
| --- | --- |
| “哪一列被称为 X / 表格里有没有 X 列” | `describe_table` 看列名，或 `SELECT * ... LIMIT 1` 看表头 |
| “第一行第一格 / 某个单元格的值” | 直接 `SELECT` 该列，用 `LIMIT` / `rowid` 定位行 |
| “X 的 Y 是什么”（key-value 表） | 两列结构里按左列筛，取右列 |
| “有哪些类别 / 取值” | `SELECT DISTINCT "列名"` |

## 3. 模板 SQL（已实跑）

```sql
-- ① 看表头与首行（小表最常用）
SELECT * FROM t_2646e8725e97437 LIMIT 3;
-- 结果：subject=2014 World Weightlifting Championships – men's 105 kg, predicate=point in time, object=2014

-- ② 两列 key-value 表（列名是 "0" 和 "1"，必须加双引号）
SELECT "1" AS 值 FROM t_<表id> WHERE "0" = 'name';

-- ③ 取某列全部去重取值（先看口径）
SELECT DISTINCT "predicate" FROM t_2646e8725e97437;

-- ④ 按年份取值
SELECT "Year", "Response" FROM t_<表id> WHERE "Year" >= 2000 ORDER BY "Year" LIMIT 20;
```


## 5. 口语说法 → 英文检索词 / 落点（实测对照）

表内容是英文、用户说中文，直接把口语词丢进检索往往对不上。这张表是**人工整理 + 实跑验证**的对照，
Agent 也可以用 `analyze_table_query` 自动生成同一套（本地规则，不花钱）。

| 用户可能这么说 | 英文检索词（传给 find_table 的 keywords） | 表里通常落在哪 |
| --- | --- | --- |
| 哪一列是「谓词」/ 主语 / 宾语 | predicate / subject / object | 三元组表的列名本身（105 张表就是 subject/predicate/object） |
| 第一行第一格 / 某个单元格的值 | ——（用列名直接选） | `SELECT "列名" FROM t_xxx LIMIT 1` |
| 表格里有「名称」列吗 | name / title / label | 先 `describe_table` 看列名最稳 |
| 年份 / 年度 / 哪一年 | year | `Year`、`date`，或列名里直接写着年份 |
| 排序 / 排名 / 第几 | rank / order | `Rank` 这一类列 |
| 一共几条 / 多少行 | count / number | `COUNT(*)` |
| 有哪些类别 / 取值 | category / type / distinct | `SELECT DISTINCT "列名"` |
## 6. 易错点

- 列名 `"0"` `"1"` 是**列名不是字面量**，写 SQL 时别漏了双引号；
- 这类表常有 **1 行的极小表**（143 张表只有 1–3 行），数值列判定要求至少 2 个数值，
  所以单行的数字（如 `object=2014`）会保持**文本**——比较时按文本比较，必要时 `CAST(... AS INTEGER)`；
- 同一张源表在数据集里可能重复出现（210 张两列表大量同构），定位时优先用问题里的**具体取值**（人名、赛事名、年份）。
