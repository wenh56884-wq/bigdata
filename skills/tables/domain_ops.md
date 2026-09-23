# 非结构化表格技能卡：领域运算（domain_ops）

> 数据集：`Table_Domain-specific_Operations-数据.md` → **239 张表 / 2,563 行**（HTML 表 68 张），平均 10.7 行，最大 79 行。
> 题目文件：`Table_Domain-specific_Operations_task.json`（239 题）。核验日期 2026-09-18。

## 1. 数据长什么样

这是**专门考算术**的数据集：小表 + 少量数值，问题基本都是「同比 / 环比 / 占比 / 变化率 / 差额」。

- 最常见列名：`col1`(52) / `Name`(16) / `Rank`(12) / `year`(12) / `( in millions )`(8) / `amount ( in millions )`(7)；
- 大量表是 **两列结构**：`col1`（标签，如 “2015 net revenue”）+ 一个金额列；
- **年份常常写在列名里**（`12/31/2012`、`2015`、`december 31 , 2013`），而不是行里的某一列 —— 这种表要「按列取数」而不是按行筛；
- 领域：摩根大通财报、电力/新能源（含**反事实**题）、汽车、体育、榜单等；
- 单位：金额多为**百万美元**（列名里写明 `( in millions )`），比率已清洗成数字（`23%`→`23`）。

## 2. 典型题型 → 落点

| 问法 | 怎么做 |
| --- | --- |
| “从 X 年到 Y 年……百分比变化是多少” | 取两年数值 → **`(v2-v1)*100.0/v1`** → `ROUND(...,2)` |
| “增加了/减少了多少个基点” | 1 个基点 = 0.01%，先算差值再换算 |
| “占比 / 比重” | `SUM(部分)*100.0/SUM(整体)` |
| “如果某事没有发生，某年的 X 是多少”（反事实） | 在**明细表**里找该事件对应的增量，再从合计里剔除后重算 |
| “哪一项最高/最低” | `ORDER BY 数值 DESC LIMIT 1` |

## 3. 模板 SQL（已实跑，结果与参考答案一致）

**案例**：表 `t_b40962fe65f24d9`（摩根大通信用利差，2 行 2 列），
列名精确为 `( in millions )` 与 `one basis-point increase injpmorgan chase 2019s credit spread`，
两行分别是 `december 31 2012 → 34`、`december 31 2011 → 35`。
问「2011 → 2012 的百分比变化」→ 参考答案 **-2.86%**。

```sql
-- ✅ 正确：乘 100.0 强制浮点（实测返回 -2.86，与参考答案一致）
SELECT ROUND(
  (MAX(CASE WHEN "( in millions )" LIKE '%2012' THEN "one basis-point increase injpmorgan chase 2019s credit spread" END)
 - MAX(CASE WHEN "( in millions )" LIKE '%2011' THEN "one basis-point increase injpmorgan chase 2019s credit spread" END))
  * 100.0
  / MAX(CASE WHEN "( in millions )" LIKE '%2011' THEN "one basis-point increase injpmorgan chase 2019s credit spread" END)
, 2) AS pct_change
FROM t_b40962fe65f24d9;

-- ❌ 错误：整数相除会被截断，返回 0.0（同样写法只少了 100.0）
```

```sql
-- 两列表（col1 是标签）取某个标签的金额
SELECT "amount ( in millions )" FROM t_98a478f23b754a7 WHERE "col1" LIKE '%2015 net revenue%';

-- 「年份写在列名里」的表：直接对列取值（列名照抄 describe_table）
SELECT "col1", "12/31/2011", "12/31/2012" FROM t_33e1caefe2394d7 LIMIT 3;

-- 占比
SELECT ROUND(SUM(CASE WHEN "col1" LIKE '%coal%' THEN "amount ( in millions )" ELSE 0 END) * 100.0
           / SUM("amount ( in millions )"), 2) AS share FROM t_<表id>;
```


## 5. 口语说法 → 英文检索词 / 落点（实测对照）

| 用户可能这么说 | 英文检索词 | 表里通常落在哪 |
| --- | --- | --- |
| 净收入 / 营收 / 收入 | net income / revenue / income | 两列表的 `col1` 标签（如 “2015 net revenue”）或金额列 |
| 信用利差 / 利差 | credit spread / spread | 列名本身就是长句（`one basis-point increase … credit spread`） |
| 基点 / bp | basis point | 1 个基点 = 0.01%，算变化率前先统一单位 |
| 电价 / 零售电价 | retail electricity / electricity | 标签列（如 “retail electricity price”） |
| 煤 / 天然气 / 石油 | coal / natural gas / oil | 能源类表的 `col1` 标签 |
| 占比 / 百分比 / 比重 | percentage / percent / share | 先 SUM 再相除，记得 `*100.0` |
| 涨了 / 跌了 / 增长 / 变化率 | growth / increase / decrease | 先取两个数再算比值 |
| 如果…没有发生（反事实） | ——（先找事件明细） | 在明细表里定位事件，剔除后重算 |
## 6. 易错点

1. **整除陷阱**（本数据集最致命的坑）：`(a-b)/b*100` 在 SQLite 里大概率得 0 或整数，必须写成 `(a-b)*100.0/b`；
2. 列名带空格和括号（`"( in millions )"`、`"amount ( in millions )"`）→ 双引号包起来；
3. 列名里写错一个字**不会报错**（被当成字符串字面量），会静默给出错误数字 —— 列名一律从 `describe_table` 抄；
4. 年份可能在**列名**而不在数据里，先 `describe_table` 看清楚再写 SQL；
5. 反事实题（“假设…没有发生”）需要先定位事件明细表，再回到合计表重算，别直接拿现成的合计数字做减法。
