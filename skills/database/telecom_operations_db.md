# 数据库查询技能卡：通信运营商库（telecom_operations_db）

> **核验声明**：本卡字段名、类型、取值字典均对照本地 MySQL `information_schema` 与 `SELECT DISTINCT` 实测核验（核验日期 2026-09-09）。
> 数据量实测：customers 15,000 / subscriptions 37,700 / cdr_detail 100,000 / monthly_bills 59,132 / products 29（产品+版本）/ service_records 20,000 / marketing_campaigns 500 / network_resources 215。
> 写 SQL 前仍以 `get_table_schema` 实时结构为准；本卡用于定位表、口径与常见写法。

## 1. 建库口径与数据类型约定（先读，避免低级错）

| 约定 | 说明 |
| --- | --- |
| 金额 | 金额类列多为 `decimal(28,8)`，个别资费列类型为 int（`base_fee`/`monthly_fee` 单位也是元）；汇总用 `ROUND(SUM(x), 2)` |
| 账期 | `cdr_detail.billing_cycle`、`monthly_bills.billing_month` 都是 **VARCHAR 的 DATE 值（主值形如 `YYYY-MM-01`）**，不是 `YYYY-MM` 字符串，也不是 DATETIME |
| 账期过滤 | 用半开区间 `billing_cycle >= '2024-01-01' AND billing_cycle < '2024-02-01'`（命中按月分区）；月度展示可用 `LEFT(billing_month, 7)` |
| 明细大表 | cdr_detail（10 万行，按月分区）、monthly_bills（5.9 万行）：**必须带账期条件**再聚合，严禁无账期的全表 SUM |
| 产品目录 | products 是**版本化目录**，PK =（product_id, version）；取“当前版”用 `is_current = 1` |

## 2. 八张表速览与主外键

| 表（实测行数） | 职责与连接键 |
| --- | --- |
| customers（15k） | 用户主档。PK customer_id；当前状态看 `customer_status`；手机号在 subscriptions，**本表无 msisdn** |
| products（29） | 套餐目录（多版本）。PK (product_id varchar, version)；`is_current=1` 为当前有效版 |
| subscriptions（37.7k） | 订购关系。PK subscription_id；`customer_id`/`product_id`/`product_version`/`msisdn`；**无状态列**，有效性靠时间字段判断 |
| cdr_detail（100k） | 通信详单。PK cdr_id；`msisdn`（主叫）；账期 `billing_cycle` 按月分区 |
| monthly_bills（59k） | 月度账单。PK bill_id；`customer_id`/`msisdn`；账期 `billing_month` |
| marketing_campaigns（500） | 营销活动主档（预算/状态/KPI/ROI 字段均在表内） |
| service_records（20k） | 客服工单/通话（渠道/原因/满意度/是否投诉/解决状态） |
| network_resources（215） | 基站等网络资源（维护状态/容量/利用率/故障次数） |

典型问法 → 表：用户量/入网销户/欠费状态 → `customers`；有哪些套餐/5G、套餐比价（最便宜/最贵/月租最低/价格低于 X 元）→ `products`（用 `base_fee` 排序并限定 `is_current=1`）；谁订了什么套餐/在网订购 → `subscriptions`；通话时长流量短信漫游费 → `cdr_detail`；账单总额/欠费缴费 → `monthly_bills`；活动转化 ROI → `marketing_campaigns`；投诉满意度 → `service_records`。

口语说法 → 正确落点（列名均核验）：
- “套餐多少钱 / 月租多少 / 资费 / 最便宜 / 最贵 / 低于 X 元”→ `products.base_fee`（元，`is_current=1`；基础套餐比价再加 `product_type='基础套餐'`）；
- “谁订了 XX / 用了 XX 套餐 / 本月新开通 / 还在网 / 退了没”→ `subscriptions`（当前生效 = `start_date<=CURDATE() AND end_date>=CURDATE() AND actual_end_date IS NULL`）；
- “通话/流量/短信最多的号码、打了几分钟、漫游费”→ `cdr_detail`（大表必带 `billing_cycle` 半开区间，时长 `duration_seconds`、流量 `data_volume_mb`、短信 `sms_count`）；
- “某月账单多少钱 / 欠费 / 还没缴”→ `monthly_bills`（`billing_month` 半开区间；欠费 `unpaid_amount>0`）；
- “投诉 / 客服 / 满意度 / 故障报修”→ `service_records`；“活动预算 / ROI / 转化”→ `marketing_campaigns`；“基站 / 覆盖 / 故障设备”→ `network_resources`。

## 3. 字段取值字典（已实测）

- `customers.customer_status`：正常 / 停机 / 欠费 / 预销户 / 已销户。
- `customers.gender`：男 / 女 / **未知**（注释提示含空值及异常值，做画像统计需按原值分组汇报）；`vip_level`：普通 / 银卡 / 金卡 / 钻石 / 黑卡。
- `products.product_type`：基础套餐 / 流量包 / 语音包 / 增值业务 / 国际漫游 / 5G专享。
- `monthly_bills.payment_status`：已支付 / 待支付 / 部分支付 / 逾期（列注释另含 未出账/坏账，现网未见则按实际返回汇报）。
- `cdr_detail.call_type`：本地语音 / 长途语音 / 视频通话 / 国际漫游 / 短信 / 彩信 / 流量；`call_result`：成功/被叫忙/未接听/关机/不在服务区/呼入限制/其他。
- `subscriptions.billing_cycle`（int 1-28）是**每月出账日**，不是账期月份，别拿它当月过滤。
- 数值单位：`duration_seconds` 秒、`data_volume_mb` MB（注释提示含负值异常）、`sms_count` 条、`data_allowance` GB、`voice_allowance` 分钟、`sms_allowance` 条。

## 4. 易错点（企业级注意）

- **“欠费”两套口径**：`customers.customer_status='欠费'` 是用户当前主档状态（快照）；账单欠费以 `monthly_bills.unpaid_amount > 0` 为准（含 待支付/部分支付/逾期 中未缴部分）。问“某月欠费用户”用账单表按账期去重 customer_id；问“当前处于欠费的用户”才用 customers。
- **产品关联必须带版本**：`subscriptions.product_version = products.version`（仅 product_id 会错配历史版本），并配合 `products.is_current=1` 或直接 join 指定版本。
- **在网订购无状态列**：默认“当前生效”口径 = `start_date <= CURDATE() AND end_date >= CURDATE() AND actual_end_date IS NULL`（提前退订会写 actual_end_date），如与业务口径不符需向用户确认。
- 明细/账单是大表：不给账期范围就直接跑 SUM/GROUP BY 会扫描全分区，应先在时间条件上收窄；结果给 `LIMIT`。
- **套餐比价（最便宜/最贵）易错**：比较范围先落在“当前有效目录”`products.is_current = 1`，价格看 `base_fee`（int，单位元）并排序 + `LIMIT`；`流量包 / 语音包 / 增值业务` 的 `base_fee` 可能为 0，问“最便宜的套餐”默认限定 `product_type = '基础套餐'`，只有用户指“全部在售产品 / 所有产品比价”才放开类型过滤，答复里写清口径；问“5G 套餐比价”按 `product_type = '5G专享'` 限定。
- 金额是 DECIMAL，除“件数/时长”外不要用 COUNT 数钱；`data_volume_mb` 有负值异常，求均值留意。
- `address_json` 是 JSON 文本，按城市筛选用 `LIKE '%北京%' OR LIKE '%北京市%'`。

## 5. 常用模板 SQL（列名已核验；账期/年份按需替换）

```sql
-- ① 用户当前状态分布
SELECT customer_status, COUNT(*) AS user_cnt
FROM telecom_operations_db.customers
GROUP BY customer_status
ORDER BY user_cnt DESC;

-- ② 2024 年各月账单汇总（先按月收窄再分组；billing_month 为 DATE 值）
SELECT LEFT(billing_month, 7) AS ym,
       COUNT(DISTINCT customer_id) AS bill_users,
       ROUND(SUM(total_amount), 2) AS bill_total,
       ROUND(SUM(unpaid_amount), 2) AS unpaid_total
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
GROUP BY LEFT(billing_month, 7)
ORDER BY ym;

-- ③ 2024-01 欠费用户（欠费以 unpaid_amount > 0 为准，账单维度）
SELECT customer_id, msisdn, billing_month, total_amount, unpaid_amount, payment_status
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2024-02-01'
  AND unpaid_amount > 0
ORDER BY unpaid_amount DESC
LIMIT 20;

-- ④ 当前有效套餐（产品目录当前版）
SELECT product_id, version, product_name, product_type,
       base_fee, voice_allowance, data_allowance, sms_allowance
FROM telecom_operations_db.products
WHERE is_current = 1
ORDER BY product_type, product_name;

-- ⑤ 2024-01 语音通话时长与费用 Top 号码（详单大表必带账期；仅计成功语音）
SELECT msisdn,
       COUNT(*) AS call_cnt,
       ROUND(SUM(duration_seconds) / 60, 1) AS duration_minutes,
       ROUND(SUM(total_fee), 2) AS call_fee
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle >= '2024-01-01' AND billing_cycle < '2024-02-01'
  AND call_type IN ('本地语音', '长途语音')
  AND call_result = '成功'
GROUP BY msisdn
ORDER BY duration_minutes DESC
LIMIT 20;

-- ⑥ 当前生效订购明细（默认口径：未退订且未到期；产品按 product_id+version 双键关联）
SELECT s.msisdn, s.customer_id, s.start_date, s.end_date,
       p.product_name, p.version, s.monthly_fee, s.contract_duration
FROM telecom_operations_db.subscriptions s
JOIN telecom_operations_db.products p
  ON p.product_id = s.product_id AND p.version = s.product_version
WHERE s.start_date <= CURDATE()
  AND s.end_date >= CURDATE()
  AND s.actual_end_date IS NULL
ORDER BY s.msisdn
LIMIT 20;

-- ⑦ 当前有效“最便宜的基础套餐”（最贵把 ASC 改 DESC；比价只限当前版）
SELECT product_id, version, product_name, product_type, base_fee
FROM telecom_operations_db.products
WHERE is_current = 1
  AND product_type = '基础套餐'
ORDER BY base_fee ASC
LIMIT 1;
```

> 结束语：模板只为示范“正确写法”。真实查询仍先 `get_table_schema` 复核列名，取值不明确的字段用 `SELECT col, COUNT(*) FROM 库.表 GROUP BY col` 看分布后再过滤。
