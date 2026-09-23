# 数据库查询技能卡：医院医疗数据分析库（healthcare_analytics_competition）

> **核验声明**：本卡字段名、类型、取值字典均对照本地 MySQL `information_schema` 与 `SELECT DISTINCT` 实测核验（核验日期 2026-09-09）。
> 数据量实测：patient_master_index 50,000 / medical_encounters 150,000 / medical_orders 200,000 / billing_transactions 250,000 / pharmacy_inventory 30,000 / medical_equipment_usage 80,000 / departments_wards 20 / medical_staff 2,000。
> 写 SQL 前仍以 `get_table_schema` 实时结构为准；本卡用于定位表、口径与常见写法。

## 1. 建库口径与数据类型约定

| 约定 | 说明 |
| --- | --- |
| 金额 | `decimal(28,8)`，单位元（`insurance_balance` 医保余额 1 万 = 10000） |
| 时间 | 就诊 `encounter_date`、结算 `transaction_date`、设备 `start_time`、药品 `expiration_date` 均为**真 DATETIME**，可直接用日期函数与半开区间 |
| 时间过滤 | 一律 `col >= '2024-01-01' AND col < '2024-02-01'`（避免 `BETWEEN ... '23:59:59'`）；大表（billing 25 万、orders 20 万行）必须先用时间条件收窄再聚合 |
| 患者口径 | 患者表 `delete_flag`：N=正常、Y=已删除；患者维度统计加 `delete_flag = 'N'`（现网数据仅 N，保留条件更稳妥） |

## 2. 八张表速览与主外键

| 表（实测行数） | 职责与连接键 |
| --- | --- |
| patient_master_index（50k） | 患者主档。PK patient_id；`gender` M=男/F=女/**U=未知**（三值！） |
| medical_encounters（150k） | 就诊事实。PK encounter_id；`patient_id`→患者、`department_id`→科室、`doctor_id`→医护 |
| medical_orders（200k） | 医嘱事实。PK order_id；`encounter_id`→就诊；金额取 `total_price`（数量列名是 **`order_quantity`**，没有 `quantity`） |
| pharmacy_inventory（30k） | 药品库存批次。PK inventory_id；`drug_id` 关联**外部药品目录**（本库 8 表内无药名字典） |
| medical_equipment_usage（80k） | 设备使用事实。PK usage_id；`equipment_id`/`encounter_id`/`patient_id`；时长 **`duration_minutes`(分钟)**，无 duration_seconds |
| medical_staff（2k） | 医护主档。PK staff_id；`department_id`→科室；在职看 `is_active` |
| departments_wards（20） | 科室与病区**同表**。PK dept_ward_id；`type` 三值：临床科室/医技科室/病区 |
| billing_transactions（250k） | 费用结算流水（细粒度，一笔就诊可多行）。`encounter_id`/`patient_id`/`department_id` 外键 |

典型问法 → 表：患者量/年龄性别/医保余额 → 患者表；就诊量/门诊住院/医疗总收入、费用极值（单次费用最高/最低）→ `medical_encounters`（金额看 `total_cost`）；医嘱与项目费用 → `medical_orders`；库存效期 → `pharmacy_inventory`；设备使用时长费用 → `medical_equipment_usage`；科室数/床位 → `departments_wards`；结算净额/医保自付/欠费、单笔收费最贵 → `billing_transactions`。

口语说法 → 正确落点（列名均核验）：
- “看诊 / 住院花了多少钱、单次费用最高”→ `medical_encounters.total_cost`（就诊维度，一次就诊一行）；
- “医药费 / 检查费 / 手术费、单笔最贵、结算净额 / 医保付 / 自付 / 退款”→ `billing_transactions`（`net_amount` / `insurance_paid` / `patient_paid` / `payment_status`）；
- “某病 / 某医嘱开了多少、金额”→ `medical_orders`（金额 `total_price`、数量 `order_quantity`、类型 `order_type`）；
- “XX 药库存 / 效期 / 低于警戒”→ `pharmacy_inventory`（无药名，先经 `medical_orders.item_name LIKE` 定位 `drug_id`）；
- “某设备用了多少小时 / 费用 / 坏了”→ `medical_equipment_usage`（`duration_minutes` / `total_cost` / `usage_status`）；
- “医生 / 护士绩效、在职”→ `medical_staff`（`performance_score` / `is_active`）。

## 3. 字段取值字典（已实测）

- `patient_master_index.gender`：**M / F / U**（U=未知，统计三值都要给）；`patient_level`：普通 / VIP / SVIP。
- `departments_wards.type`：**临床科室 / 医技科室 / 病区**。口径约定：科室数 = `type <> '病区'`（临床+医技）。
- `medical_encounters.encounter_type`：门诊 / 急诊 / 住院 / 体检 / 复诊；是否结清看 `is_paid`（tinyint 0/1）。
- `medical_orders.order_type`：药品 / 检查 / 检验 / 治疗 / 手术 / 护理；`execution_status`：未执行/执行中/已执行/已取消。
- `pharmacy_inventory.inventory_status`：在库 / 待验 / 停用 / 退货 / 报损。
- `medical_equipment_usage.usage_status`：正常完成 / 异常终止 / 计划内维护。
- `billing_transactions.payment_status`：已支付 / 部分支付 / 未支付 / 医保待结算 / 已退款。
- `medical_orders.item_type`（varchar 标识）与 `billing_transactions.item_type` 是类型码，展示要结合业务字典，不要直接输出编码。

## 4. 易错点（企业级注意）

- **收入口径必须说清来源**：医疗总收入 = `SUM(medical_encounters.total_cost)`（就诊维度）；结算净额 = `SUM(billing_transactions.net_amount)`（费用流水维度）。两者粒度不同、不可混用，回复时注明口径。
- **费用极值排序先定粒度**：“费用最高/最低的一次就诊”→ `medical_encounters.total_cost`；“单笔最贵的收费项目/结算明细”→ `billing_transactions`（`unit_price`×`quantity` 或 `net_amount`）；“金额最高的一条医嘱”→ `medical_orders.total_price`。三处字段粒度不同，不可串用，写 SQL 前按问法选定一张表。
- 结算表的医保/自付是 `insurance_paid / patient_paid`；就诊表是 `insurance_payment / patient_payment`，**字段名不通用**。
- `medical_encounters` 没有 `payment_status` 列（它是 `is_paid`），别照抄结算表列名。
- 按人计数用 `COUNT(DISTINCT patient_id)`，防止一患者多就诊/多结算重复计入。
- 药品库存无药名：`pharmacy_inventory` 只有数字 `drug_id`。问“XX 药还有多少”先经 `medical_orders.item_name LIKE` 定位到 drug_id，或请用户提供药品编号，不要臆造 `drug_name` 列。
- 设备“在用数”是状态口径问题：`usage_status` 只有 正常完成/异常终止/计划内维护，没有“使用中”枚举，需要先用模板还原问法或给用户明确说明。

## 5. 常用模板 SQL（列名已核验；年份/月份按需替换）

```sql
-- ① 在册患者按性别分布（M=男 F=女 U=未知，三值都给）
SELECT gender, COUNT(*) AS patient_cnt
FROM healthcare_analytics_competition.patient_master_index
WHERE delete_flag = 'N'
GROUP BY gender;

-- ② 某月医疗总收入（就诊口径，encounter_date 为 DATETIME，用半开区间）
SELECT ROUND(SUM(total_cost), 2) AS total_revenue, COUNT(*) AS encounter_cnt
FROM healthcare_analytics_competition.medical_encounters
WHERE encounter_date >= '2024-01-01' AND encounter_date < '2024-02-01';

-- ③ 某月结算净额与医保/自付拆分（结算口径，注意与 ② 粒度不同）
SELECT ROUND(SUM(net_amount), 2)   AS settle_net,
       ROUND(SUM(insurance_paid), 2) AS insurance_paid,
       ROUND(SUM(patient_paid), 2)   AS patient_paid
FROM healthcare_analytics_competition.billing_transactions
WHERE transaction_date >= '2024-01-01' AND transaction_date < '2024-02-01';

-- ④ 某月科室结算收入 Top（结算表 department_id = 科室表 dept_ward_id）
SELECT dw.name AS dept_name,
       COUNT(*) AS tx_cnt,
       ROUND(SUM(bt.net_amount), 2) AS settle_amount
FROM healthcare_analytics_competition.billing_transactions bt
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = bt.department_id
WHERE bt.transaction_date >= '2024-01-01' AND bt.transaction_date < '2024-02-01'
  AND dw.type <> '病区'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY settle_amount DESC
LIMIT 20;

-- ⑤ 库存低于再订货线且在库的药品（含效期提醒列）
SELECT drug_id, batch_number, current_quantity, reorder_level, expiration_date
FROM healthcare_analytics_competition.pharmacy_inventory
WHERE inventory_status = '在库'
  AND current_quantity <= reorder_level
  AND expiration_date >= CURDATE()
ORDER BY (reorder_level - current_quantity) DESC
LIMIT 50;

-- ⑥ 某月设备使用时长与费用 Top（仅统计正常完成的使用记录）
SELECT equipment_id,
       COUNT(*) AS usage_cnt,
       ROUND(SUM(duration_minutes) / 60, 1) AS usage_hours,
       ROUND(SUM(total_cost), 2) AS usage_cost
FROM healthcare_analytics_competition.medical_equipment_usage
WHERE usage_status = '正常完成'
  AND start_time >= '2024-01-01' AND start_time < '2024-02-01'
GROUP BY equipment_id
ORDER BY usage_cost DESC
LIMIT 20;
```

> 结束语：模板只为示范“正确写法”。真实查询仍先 `get_table_schema` 复核列名，取值不明确的字段用 `SELECT col, COUNT(*) FROM 库.表 GROUP BY col` 看分布后再过滤。
