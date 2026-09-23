# 非结构化表格技能卡：多步检索（multi_step）

> 数据集：`Multi-step_Retrieval-数据.md` → **48 张表 / 111,486 行**（HTML 表 12 张），平均 2,322 行，最大 **13,200 行**。
> 题目文件：`Multi-step_Retrieval_task.json`（48 题）。核验日期 2026-09-18。

## 1. 数据长什么样

- **大表为主**：9 张表超过 2,000 行，最大的气象表 13,200 行、新能源（powertrain）表 12,654 行；
- 结构：`col1`（原表索引列，**39/48 张都有**） + 业务列；
- 数据主题（实测）：
  | 主题 | 代表列 | 说明 |
  | --- | --- | --- |
  | 咖啡消费流水 | `date` `datetime` `cash_type` `card` `money` `coffee_name` | 896 行/张，**有 4 张完全同构的表**（任选一张） |
  | 气象 | `Temperature` `Humidity` `Wind Speed` `Season` `Location` … | 13,200 行（HTML 表） |
  | 新能源/汽车 | `region` `category` `parameter` `mode` `powertrain` `year` `unit` `value` | 12,654 行/张，`value` 是数值列 |
  | 企业财报/保险/地区经济 | `报表日期` `收入` `保险编号` `地区生产总值` … | 中文列名，30–700 行 |
- 时间列是 **ISO 文本**（`2024-03-01` / `2024-03-01 10:15:50.520`），可直接 `substr("date",1,7)` 取月份。

## 2. 典型题型 → 落点

| 问法 | 怎么做 |
| --- | --- |
| “某类别的总量 / 平均 / 计数” | `WHERE` 过滤 → `GROUP BY` → `SUM`/`AVG`/`COUNT`，`ORDER BY` 取 Top-N |
| “哪个月最高 / 环比增长最快” | 先按月聚合（`GROUP BY substr(date,1,7)`），再自比较求环比 |
| “条件回溯明细”（如某卡号在某天的消费） | 用 `card` / `coffee_name` 等**特征值**过滤，必要时两步：先聚合再回表取明细 |
| “反事实假设”（假设某涨价没有发生） | 先在明细里定位该事件记录，剔除 / 修正后重算，不要直接拿现成合计做减法 |
| “跨表对比” | 每张表各查一次，最后在回答里对比（不要 JOIN 不同数据集的大表） |

## 3. 模板 SQL（已实跑）

以咖啡表 `t_05ab28a47b924ae`（896 行，列：`col1/date/datetime/cash_type/card/money/coffee_name`）为例：

```sql
-- ① 现金支付下各咖啡品类的销量与金额（实测：Latte 25 笔 / 991.0 居首）
SELECT "coffee_name", COUNT(*) AS n, ROUND(SUM("money"), 1) AS total
FROM t_05ab28a47b924ae
WHERE "cash_type" = 'cash'
GROUP BY "coffee_name"
ORDER BY total DESC LIMIT 5;

-- ② 按月趋势（实测：2024-03 → 206 笔 / 7050.2）
SELECT substr("date", 1, 7) AS ym, COUNT(*) AS n, ROUND(SUM("money"), 1) AS money
FROM t_05ab28a47b924ae
GROUP BY ym ORDER BY ym LIMIT 12;

-- ③ 条件计数（实测：Latte + 刷卡 = 162 笔）
SELECT COUNT(*) AS n FROM t_05ab28a47b924ae
WHERE "coffee_name" = 'Latte' AND "cash_type" = 'card';

-- ④ 两段式：先聚合定位，再回表取明细（大表推荐写法）
WITH top AS (
  SELECT "coffee_name" FROM t_05ab28a47b924ae
  GROUP BY "coffee_name" ORDER BY COUNT(*) DESC LIMIT 1
)
SELECT * FROM t_05ab28a47b924ae
WHERE "coffee_name" IN (SELECT "coffee_name" FROM top)
LIMIT 5;
```

新能源大表（`t_069390fab0b94f3`，12,654 行）按类别聚合（实测 3 组）：

```sql
SELECT "category", COUNT(*) AS n, ROUND(AVG("value"), 1) AS avg_value
FROM t_069390fab0b94f3 GROUP BY "category" ORDER BY n DESC LIMIT 5;
```


## 5. 口语说法 → 英文检索词 / 落点（实测对照）

| 用户可能这么说 | 英文检索词 | 表里通常落在哪 |
| --- | --- | --- |
| 咖啡 / 拿铁 / 卡布奇诺 / 美式 | coffee / latte / cappuccino / americano | `coffee_name` |
| 现金支付 / 刷卡 | cash / cash_type / card | `cash_type`（取值就是 cash / card） |
| 花了多少钱 / 消费金额 | money / amount / total | `money` |
| 哪个月 / 按月看趋势 | date / month | `date`（ISO 文本，`substr(date,1,7)` 取月份） |
| 天气 / 温度 / 湿度 / 风速 | weather / temperature / humidity / wind | 气象大表（13,200 行）的列名 |
| 新能源 / 车型 / 动力类型 | powertrain / ev / mode | powertrain 大表（12,654 行）的 `powertrain`/`mode` |
| 保险 / 保费 / 理赔 | insurance / premium / claim | 保险类表（中文列名为主） |
| 地区生产总值 / GDP | gdp / gross domestic product | 地区经济表（中文列名 `地区生产总值`） |
## 6. 易错点

1. **绝对不要 `SELECT *`**（最大 13,200 行）：先 `WHERE` / `GROUP BY`，`query_tables` 默认只回 100 行并提示截断；
2. `col1` 是原表自带的索引列，统计时**不要**把它当业务字段（例如不要 `COUNT(col1)` 当作业务数量）；
3. 同名同构表有多份（4 张咖啡表、3 张新能源表）→ 用 `n_rows` + 列名确认，任选一张即可，结果一致；
4. 中文列名（`报表日期`、`地区生产总值－第一产业`）要用双引号；
5. 反事实题不要心算，把假设落到 SQL 里（剔除对应记录后重算），答案才可复现；
6. 时间列是文本，比较用 ISO 字符串（`"date" >= '2024-03-01'`），需要按月就 `substr(...,1,7)`。
