# 数据库查询技能卡：金融资产管理库（financial_asset_management）

> **核验声明**：本卡字段名、类型、取值字典均对照本地 MySQL `information_schema` 与 `SELECT DISTINCT` 实测核验（核验日期 2026-09-09）。
> 数据量实测：clients 15,000 / portfolios 20,000 / transactions 100,000 / holdings 106,198 / risk_metrics 100,000 / products 200 / managers 500 / counterparties 100。
> 写 SQL 前仍以 `get_table_schema` 实时结构为准；本卡用于定位表、口径与常见写法。

## 1. 建库口径与数据类型约定（先读，避免低级错）

| 约定 | 说明 |
| --- | --- |
| 金额 | 一律 `decimal(28,8)`，单位元。1000 万 = `10000000`，不要写“万/亿” |
| 时间 | 全部为 **VARCHAR(20) 的 ISO 字符串**（`YYYY-MM-DD` 或带时分秒），不是 DATETIME 列 |
| 时间过滤 | 用字符串半开区间：`trade_date >= '2024-01-01' AND trade_date < '2024-02-01'`（ISO 零填充可直接字典序比较） |
| 月度聚合 | 用 `LEFT(trade_date, 7)` 取 `YYYY-MM`，**不要**对 VARCHAR 用 `DATE_FORMAT()` 做隐式转换（破坏索引且慢） |
| 费率 | `products.management_fee` 为**小数费率**（实测 0.0023~0.0388，即 0.023 = 2.3%/年），非百分数 |

## 2. 八张表速览（谁放“事实”，谁放“属性”）

| 表（实测行数） | 职责与连接键 |
| --- | --- |
| clients（15k） | 客户主档。PK client_id；`manager_id` → managers；状态用数值 `status` |
| managers（500） | 客户经理。PK manager_id；`department_name` 冗余在表内（按部门统计用本表即可，无需 join） |
| products（200） | 产品目录。PK product_id，`product_code` 唯一索引 |
| counterparties（100） | 交易对手方。PK counterparty_id；`credit_rating` 如 AAA/AA+ |
| portfolios（20k） | 客户投资组合。PK portfolio_id；`client_id` → clients；终止状态看 `termination_date` 是否非空（无 status 列） |
| transactions（100k） | 交易流水，逐笔事实。`portfolio_id/product_id/counterparty_id/trader_id` 外键 |
| holdings（106k） | 当前持仓事实。`portfolio_id/product_id`；浮动盈亏看 `unrealized_pnl` |
| risk_metrics（100k） | 组合风险指标，**一组合多日期多行**。`portfolio_id` + `calc_date` |

典型问法 → 表：客户/开户/等级/风险类型 → `clients`；按部门经理 → `managers`；产品在售、产品比价（管理费率最低/最高、业绩提成、风险等级最低/最高）→ `products`（在售口径 `is_active=1`）；组合当前资产/盈亏 → `portfolios`（市值 `current_value` vs 累计投入 `contribution_amount`）或 `holdings.unrealized_pnl`；交易笔数金额 → `transactions`；夏普/回撤等 → `risk_metrics`。

口语说法 → 正确落点（列名均核验）：
- “赚没赚 / 浮盈 / 浮亏 / 持仓”→ 持仓浮动盈亏 `holdings.unrealized_pnl`；组合整体盈亏 = `portfolios.current_value` 对比 `contribution_amount`（未终止 `termination_date IS NULL`）；
- “买了 / 卖了 / 申购 / 赎回 / 分红 / 派息多少”→ `transactions`（`transaction_type` 过滤 + `transaction_amount` 求和）；
- “管理费 / 业绩提成 / 费率最低最高、在售产品”→ `products.management_fee`（小数费率）/ `performance_fee_rate`，限定 `is_active=1`；
- “风险评级 / 风险最低最高”→ `products.risk_rating`（1-5）；
- “回撤 / 夏普 / 波动”→ `risk_metrics`（一组合多日期，先按 `MAX(calc_date)` 取最新再聚合）；
- “客户 / 经理名下规模 / 绩效”→ `clients.total_assets` / `managers.manage_assets_total`。

## 3. 字段取值字典（已实测）

- `clients.status`（int）：**1=正常 2=冻结 3=销户**；实测分布 正常 14,225 / 冻结 478 / 销户 297。
- `clients.client_type`：个人 / 机构 / 家族信托 / 养老金。
- `clients.risk_level`：保守 / 稳健 / 平衡 / 成长 / 进取。
- `products.product_type`：股票型 / 债券型 / 混合型 / 货币型 / QDII / 另类投资。
- `products.is_active`（tinyint）：1=有效（实测 183 有效），0=无效。
- `products.currency`：USD / CNY / HKD / EUR / GBP。
- `products.risk_rating`（int 1-5，1 最低 5 最高）。
- `transactions.transaction_type`：买入 / 卖出 / 申购 / 赎回 / 分红 / 派息 / 转换。
- `clients.contact_info`、`products.asset_allocation` 是 JSON 文本：筛选用 `LIKE '%关键词%'`，不能等值匹配。

## 4. 易错点（企业级注意）

- `risk_metrics` 一个组合多个 `calc_date`：与组合/客户 join 会**放大行数**。按组合取最新指标须先 `MAX(calc_date)` 去重（见模板 6）。
- `clients.total_assets` **存在 NULL 与负值**：做均值/分档前确认口径，必要时 `WHERE total_assets IS NOT NULL` 或在结论中说明包含负值。
- 问“赚没赚钱/浮盈”用 `holdings.unrealized_pnl`；问“流水/成交额”用 `transactions.transaction_amount`；两者不可混算。
- **产品比价/极值（费率最低/最高、风险最低/最高）先限定在售范围** `products.is_active = 1`；`management_fee / performance_fee_rate` 是小数费率（0.01 = 1%/年），别当百分数乘 100，回复用“年化费率 X%”表述。
- “已终止组合”= `termination_date IS NOT NULL`；不要在 portfolios 上写不存在的 `status` 列。
- 时间列是字符串：写日期过滤必须用**范围条件**，不要 `YEAR(col)=2024`（全列转数值，失去前缀命中）；月度用 `LEFT(col,7)` 分组即可。

## 5. 常用模板 SQL（列名已核验；年份/条件按需替换）

```sql
-- ① 客户状态分布（1正常/2冻结/3销户）
SELECT status, COUNT(*) AS client_cnt
FROM financial_asset_management.clients
GROUP BY status
ORDER BY status;

-- ② 有效客户按类型统计数量与平均总资产（含负值需在结论说明）
SELECT client_type, COUNT(*) AS client_cnt, ROUND(AVG(total_assets), 2) AS avg_assets
FROM financial_asset_management.clients
WHERE status = 1
GROUP BY client_type
ORDER BY client_cnt DESC;

-- ③ 高资产客户（总资产 > 1000 万，不含已销户）
SELECT client_id, client_name, total_assets
FROM financial_asset_management.clients
WHERE status <> 3 AND total_assets > 10000000
ORDER BY total_assets DESC
LIMIT 20;

-- ④ 管理资产 Top 10 客户经理
SELECT manager_id, manager_name, department_name, manage_assets_total, client_count
FROM financial_asset_management.managers
ORDER BY manage_assets_total DESC
LIMIT 10;

-- ⑤ 2024 年逐月交易笔数与金额（VARCHAR 时间 → LEFT 分组 + 半开区间）
SELECT LEFT(trade_date, 7) AS ym,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions
WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'
GROUP BY LEFT(trade_date, 7)
ORDER BY ym;

-- ⑥ 每个组合“最新一日”风险指标中的高夏普组合（先按 calc_date 去重再 join，避免行数放大）
SELECT p.portfolio_code, rm.calc_date, rm.sharp_ratio
FROM financial_asset_management.portfolios p
JOIN (
    SELECT portfolio_id, MAX(calc_date) AS latest_date
    FROM financial_asset_management.risk_metrics
    GROUP BY portfolio_id
) t ON t.portfolio_id = p.portfolio_id
JOIN financial_asset_management.risk_metrics rm
  ON rm.portfolio_id = t.portfolio_id AND rm.calc_date = t.latest_date
WHERE rm.sharp_ratio > 1 AND p.termination_date IS NULL
ORDER BY rm.sharp_ratio DESC
LIMIT 20;

-- ⑦ 亏损组合 Top（当前市值 < 累计投入，未终止）
SELECT portfolio_code, client_id, current_value, contribution_amount,
       ROUND(contribution_amount - current_value, 2) AS loss_amount
FROM financial_asset_management.portfolios
WHERE termination_date IS NULL AND current_value < contribution_amount
ORDER BY loss_amount DESC
LIMIT 20;
```

> 结束语：模板只为示范“正确写法”。真实查询仍先 `get_table_schema` 复核列名，无法判断口径的字段用 `SELECT col, COUNT(*) FROM 库.表 GROUP BY col` 看取值后再过滤。
