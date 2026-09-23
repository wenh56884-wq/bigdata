# 医院医疗数据分析库（Healthcare_Analytics_Competition）自然语言查询 → SQL 问答

> 使用对象：把中文业务问题转成标准 SQL（MySQL 兼容），字段一律采用英文表名 / 字段名，避免自造表名。

覆盖患者 patient_master_index、就诊 medical_encounters、医嘱 medical_orders、药品库存 pharmacy_inventory、设备使用 medical_equipment_usage、医护人员 medical_staff、科室病区 departments_wards、费用 billing_transactions 共 8 张表。

字段与取值约定：
- 患者 gender：M=男，F=女；patient_level 含 普通/VIP/SVIP；delete_flag：N=正常，Y=已删除。
- 患者删除标志为 N 时计入统计（查询可加 delete_flag='N' 过滤）。
- 费用相关：医疗总收入按 medical_encounters.total_cost；结算净额按 billing_transactions.net_amount。

## 库表字段速查

- patient_master_index（患者主索引表）：
    -  patient_id 患者ID
    -  national_id 身份证号
    -  medical_card_no 就诊卡号
    -  patient_name 患者姓名
    -  gender 性别
    -  birth_date 出生日期
    -  age 年龄
    -  blood_type 血型
    -  marital_status 婚姻状况
    -  contact_phone 联系电话
    -  emergency_contact 紧急联系人
    -  address_json 地址信息
    -  insurance_type 医保类型
    -  insurance_no 医保号
    -  insurance_balance 医保余额
    -  is_blacklist 是否黑名单
    -  patient_level 患者等级
    -  create_time 创建时间
    -  update_time 更新时间
    -  data_source 数据来源
    -  remark 备注
    -  delete_flag 删除标志

- medical_encounters（就诊记录表）：
    -  encounter_id 就诊ID
    -  patient_id 患者ID
    -  hospital_id 医院ID
    -  department_id 科室ID
    -  doctor_id 医生ID
    -  encounter_type 就诊类型
    -  encounter_date 就诊时间
    -  discharge_date 出院时间
    -  chief_complaint 主诉
    -  diagnosis_code 诊断代码
    -  diagnosis_desc 诊断描述
    -  severity_level 严重程度
    -  temperature 体温
    -  blood_pressure 血压
    -  heart_rate 心率
    -  admission_type 入院类型
    -  discharge_disposition 出院去向
    -  total_cost 总费用
    -  insurance_payment 医保支付
    -  patient_payment 患者支付
    -  is_paid 是否支付
    -  encounter_status 就诊状态
    -  created_by 创建人
    -  created_time 创建时间
    -  updated_time 更新时间

- medical_orders（医嘱执行表）：
    -  order_id 医嘱ID
    -  encounter_id 就诊ID
    -  order_type 医嘱类型
    -  item_id 项目ID
    -  item_type 项目类型
    -  item_name 项目名称
    -  order_quantity 医嘱数量
    -  order_unit 医嘱单位
    -  frequency 给药频率
    -  administration_route 给药途径
    -  start_datetime 开始时间
    -  end_datetime 结束时间
    -  executing_nurse_id 执行护士ID
    -  executed_datetime 执行时间
    -  execution_status 执行状态
    -  cancel_reason 取消原因
    -  unit_price 单价
    -  total_price 总价
    -  is_urgent 是否紧急
    -  order_priority 医嘱优先级
    -  remark 备注
    -  audit_trail 审计跟踪
    -  created_time 创建时间

- pharmacy_inventory（药品库存与采购表）：
    -  inventory_id 库存ID
    -  drug_id 药品ID
    -  batch_number 批号
    -  supplier_id 供应商ID
    -  purchase_order_no 采购订单号
    -  purchase_date 采购日期
    -  expiration_date 有效期
    -  storage_location 存储位置
    -  current_quantity 当前数量
    -  unit_of_measure 计量单位
    -  unit_cost 单位成本
    -  total_cost 总成本
    -  reorder_level 再订货点
    -  safety_stock 安全库存
    -  last_restock_date 最后补货日期
    -  last_issue_date 最后出库日期
    -  inventory_status 库存状态
    -  quality_check_result 质检结果
    -  temperature_requirement 温度要求
    -  is_controlled_substance 是否管控药品
    -  shelf_life_days 保质期天数
    -  remark 备注
    -  created_by 创建人
    -  created_time 创建时间

- medical_equipment_usage（医疗设备使用表）：
    -  usage_id 使用记录ID
    -  equipment_id 设备ID
    -  encounter_id 就诊ID
    -  patient_id 患者ID
    -  start_time 开始时间
    -  end_time 结束时间
    -  duration_minutes 使用时长
    -  operator_id 操作员ID
    -  department_id 科室ID
    -  usage_type 使用类型
    -  parameters_json 设备参数
    -  readings_json 读数记录
    -  energy_consumption 能耗
    -  cost_per_minute 每分钟成本
    -  total_cost 总费用
    -  calibration_date 校准日期
    -  next_maintenance_date 下次维护日期
    -  error_codes 错误代码
    -  usage_status 使用状态
    -  quality_flag 质量标志
    -  audit_comments 审计意见
    -  created_time 创建时间

- medical_staff（医护人员表）：
    -  staff_id 员工ID
    -  employee_no 工号
    -  staff_name 员工姓名
    -  gender 性别
    -  birth_date 出生日期
    -  hire_date 入职日期
    -  department_id 科室ID
    -  job_title 职位
    -  qualification_level 资质等级
    -  specialization 专业方向
    -  supervisor_id 上级ID
    -  contact_phone 联系电话
    -  email 邮箱
    -  work_schedule 排班信息
    -  annual_leave_balance 年假余额
    -  performance_score 绩效分数
    -  certification_json 证书信息
    -  is_active 是否在职
    -  resignation_date 离职日期
    -  emergency_contact 紧急联系人
    -  address 住址
    -  created_time 创建时间
    -  updated_time 更新时间

- departments_wards（科室与病区表）：
    -  dept_ward_id 科室病区ID
    -  code 科室代码
    -  name 科室名称
    -  type 类型
    -  parent_id 上级ID
    -  hospital_id 医院ID
    -  location_building 所在楼栋
    -  location_floor 所在楼层
    -  location_room 房间号
    -  total_beds 总床位数
    -  available_beds 可用床位
    -  head_doctor_id 科室主任ID
    -  head_nurse_id 护士长ID
    -  specialty_focus 专业重点
    -  equipment_list 设备列表
    -  cost_center_code 成本中心代码
    -  revenue_target 收入目标
    -  monthly_budget 月度预算
    -  contact_number 联系电话
    -  email 邮箱
    -  is_active 是否启用
    -  created_date 创建日期
    -  last_audit_date 最后审计日期

- billing_transactions（费用明细与结算表）：
    -  transaction_id 交易ID
    -  billing_no 账单号
    -  encounter_id 就诊ID
    -  patient_id 患者ID
    -  transaction_date 交易日期
    -  transaction_type 交易类型
    -  item_id 项目ID
    -  item_type 项目类型
    -  item_description 项目描述
    -  quantity 数量
    -  unit_price 单价
    -  discount_rate 折扣率
    -  discount_amount 折扣金额
    -  taxable_amount 应税金额
    -  tax_rate 税率
    -  tax_amount 税额
    -  net_amount 净额
    -  insurance_coverage 医保覆盖率
    -  insurance_paid 医保支付
    -  patient_paid 患者支付
    -  outstanding_amount 未付金额
    -  payment_method 支付方式
    -  payment_status 支付状态
    -  invoice_no 发票号
    -  cost_center_code 成本中心代码
    -  department_id 科室ID
    -  reversal_ref_id 冲销参考ID
    -  audit_trail 审计跟踪
    -  created_by 创建人
    -  created_time 创建时间

## 问答样例（题目 → 参考 SQL）

### 1 查下咱医院有多少个科室

题目：查下咱医院有多少个科室？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS dept_cnt FROM departments_wards WHERE type <> '病区';
```

### 2 列出所有姓张的患者名字和手机号

题目：列出所有姓张的患者名字和手机号，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, contact_phone FROM patient_master_index WHERE patient_name LIKE '张%' AND delete_flag = 'N';
```

### 3 看看2024年1月有好多门诊就诊记录

题目：看看2024年1月有好多门诊就诊记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS visit_cnt FROM medical_encounters WHERE encounter_type = '门诊' AND encounter_date BETWEEN '2024-01-01' AND '2024-01-31 23:59:59';
```

### 4 哪个科室的床位最多

题目：哪个科室的床位最多？，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, total_beds FROM departments_wards ORDER BY total_beds DESC LIMIT 1;
```

### 5 年龄大于60岁的患者有几个

题目：年龄大于60岁的患者有几个？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS patient_cnt FROM patient_master_index WHERE age > 60 AND delete_flag = 'N';
```

### 6 急诊科的电话是多少

题目：急诊科的电话是多少？，请输出对应SQL语句

参考 SQL：
```sql
SELECT contact_number FROM departments_wards WHERE name = '急诊科';
```

### 7 医保余额超过1万的患者有哪些

题目：医保余额超过1万的患者有哪些？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM patient_master_index WHERE insurance_balance > 10000 AND delete_flag = 'N';
```

### 8 看看今天有多少设备在使用中

题目：看看今天有多少设备在使用中？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT equipment_id) AS in_use_cnt FROM medical_equipment_usage WHERE DATE(start_time) = CURDATE() AND usage_status = '正常完成';
```

### 9 查下阿莫西林还有多少库存

题目：查下阿莫西林还有多少库存，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(current_quantity) AS total_stock FROM pharmacy_inventory WHERE drug_id = 12345 AND inventory_status = '在库';
```

### 10 体温超过38.5度的就诊记录

题目：体温超过38.5度的就诊记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_encounters WHERE temperature > 38.5;
```

### 11 查查上个月的总收入是多少

题目：查查上个月的总收入是多少，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(total_cost) AS last_month_income FROM medical_encounters WHERE DATE_FORMAT(encounter_date, '%Y-%m') = DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m');
```

### 12 哪些医生是主任医师

题目：哪些医生是主任医师？，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, employee_no FROM medical_staff WHERE job_title = '主任医师' AND is_active = 1;
```

### 13 看看哪些药品快过期了（3个月内）

题目：看看哪些药品快过期了（3个月内），请输出对应SQL语句

参考 SQL：
```sql
SELECT batch_number, drug_id, expiration_date, current_quantity FROM pharmacy_inventory WHERE expiration_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 3 MONTH) AND inventory_status = '在库';
```

### 14 查查女性患者有多少

题目：查查女性患者有多少，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS female_cnt FROM patient_master_index WHERE gender = 'F' AND delete_flag = 'N';
```

### 15 查下住院患者的平均住院天数

题目：查下住院患者的平均住院天数，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(DATEDIFF(discharge_date, encounter_date)) AS avg_stay_days FROM medical_encounters WHERE encounter_type = '住院' AND discharge_date IS NOT NULL;
```

### 16 哪些设备需要维护了

题目：哪些设备需要维护了？，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT equipment_id FROM medical_equipment_usage WHERE next_maintenance_date <= CURDATE();
```

### 17 患者自付金额超过5000的记录

题目：患者自付金额超过5000的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_encounters WHERE patient_payment > 5000;
```

### 18 哪些医嘱被取消了

题目：哪些医嘱被取消了？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_orders WHERE execution_status = '已取消';
```

### 19 查查各血型的患者分布

题目：查查各血型的患者分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT blood_type, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY blood_type;
```

### 20 哪些员工还有年假

题目：哪些员工还有年假？，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, annual_leave_balance FROM medical_staff WHERE annual_leave_balance > 0 AND is_active = 1;
```

### 21 看看上个月药品采购花了多少钱

题目：看看上个月药品采购花了多少钱，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(total_cost) AS purchase_cost FROM pharmacy_inventory WHERE DATE_FORMAT(purchase_date, '%Y-%m') = DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m');
```

### 22 查查各支付方式的金额分布

题目：查查各支付方式的金额分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT payment_method, SUM(net_amount) AS total_amount FROM billing_transactions GROUP BY payment_method;
```

### 23 哪些患者的诊断是高血压

题目：哪些患者的诊断是高血压？，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.patient_id, p.patient_name FROM patient_master_index p JOIN medical_encounters e ON p.patient_id = e.patient_id WHERE e.diagnosis_desc LIKE '%高血压%';
```

### 24 查下各科室的可用床位数

题目：查下各科室的可用床位数，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, available_beds FROM departments_wards;
```

### 25 心率异常（<60或>100）的患者就诊记录

题目：心率异常（<60或>100）的患者就诊记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT e.*, p.patient_name FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE e.heart_rate < 60 OR e.heart_rate > 100;
```

### 26 哪些供应商供应的药品最多

题目：哪些供应商供应的药品最多？，请输出对应SQL语句

参考 SQL：
```sql
SELECT supplier_id, COUNT(DISTINCT drug_id) AS drug_cnt FROM pharmacy_inventory GROUP BY supplier_id ORDER BY drug_cnt DESC;
```

### 27 哪些设备使用时长超过4小时

题目：哪些设备使用时长超过4小时？，请输出对应SQL语句

参考 SQL：
```sql
SELECT usage_id, equipment_id, duration_minutes FROM medical_equipment_usage WHERE duration_minutes > 240;
```

### 28 查查住院患者的费用明细

题目：查查住院患者的费用明细，请输出对应SQL语句

参考 SQL：
```sql
SELECT b.* FROM billing_transactions b JOIN medical_encounters e ON b.encounter_id = e.encounter_id WHERE e.encounter_type = '住院';
```

### 29 哪些药品是管控药品

题目：哪些药品是管控药品？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE is_controlled_substance = 1;
```

### 30 查查各科室的月收入目标

题目：查查各科室的月收入目标，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, revenue_target / 12 AS monthly_income_target FROM departments_wards;
```

### 31 哪些医嘱是紧急的

题目：哪些医嘱是紧急的？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_orders WHERE is_urgent = 1;
```

### 32 查查患者的婚姻状况分布

题目：查查患者的婚姻状况分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT marital_status, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY marital_status;
```

### 33 哪些交易有未付金额

题目：哪些交易有未付金额？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM billing_transactions WHERE outstanding_amount > 0;
```

### 34 查查医生的专业方向分布

题目：查查医生的专业方向分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT specialization, COUNT(*) AS staff_cnt FROM medical_staff WHERE job_title LIKE '%医师%' GROUP BY specialization;
```

### 35 哪些药品需要冷藏

题目：哪些药品需要冷藏？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE temperature_requirement = '冷藏';
```

### 36 查查各年龄段患者人数

题目：查查各年龄段患者人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN age < 18 THEN '未成年' WHEN age BETWEEN 18 AND 35 THEN '青年' WHEN age BETWEEN 36 AND 60 THEN '中年' ELSE '老年' END AS age_group, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY age_group;
```

### 37 哪些患者是VIP

题目：哪些患者是VIP？，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE patient_level = 'VIP' AND delete_flag = 'N';
```

### 38 查查各诊断的频次

题目：查查各诊断的频次，请输出对应SQL语句

参考 SQL：
```sql
SELECT diagnosis_desc, COUNT(*) AS freq FROM medical_encounters GROUP BY diagnosis_desc ORDER BY freq DESC;
```

### 39 哪些检查项目最常用

题目：哪些检查项目最常用？，请输出对应SQL语句

参考 SQL：
```sql
SELECT item_name, COUNT(*) AS use_cnt FROM medical_orders WHERE order_type = '检查' AND execution_status = '已执行' GROUP BY item_name ORDER BY use_cnt DESC;
```

### 40 查查设备的能耗情况

题目：查查设备的能耗情况，请输出对应SQL语句

参考 SQL：
```sql
SELECT equipment_id, SUM(energy_consumption) AS total_energy FROM medical_equipment_usage GROUP BY equipment_id;
```

### 41 哪些药品批次质检不合格

题目：哪些药品批次质检不合格？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE quality_check_result = '不合格';
```

### 42 查查员工的绩效排名

题目：查查员工的绩效排名，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, performance_score FROM medical_staff ORDER BY performance_score DESC;
```

### 43 哪些交易被冲销了

题目：哪些交易被冲销了？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM billing_transactions WHERE reversal_ref_id IS NOT NULL;
```

### 44 统计医院不同血型的患者各有多少人

题目：统计医院不同血型的患者各有多少人？，请输出对应SQL语句

参考 SQL：
```sql
SELECT blood_type, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY blood_type;
```

### 45 看看2024年1月有多少就诊记录

题目：看看2024年1月有多少就诊记录？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS visit_cnt FROM medical_encounters WHERE encounter_date BETWEEN '2024-01-01' AND '2024-01-31 23:59:59';
```

### 46 列出所有VIP患者的姓名和联系方式

题目：列出所有VIP患者的姓名和联系方式，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, contact_phone FROM patient_master_index WHERE patient_level = 'VIP' AND delete_flag = 'N';
```

### 47 查查医院现有库存的药品平均单价是多少

题目：查查医院现有库存的药品平均单价是多少？，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(unit_cost) AS avg_unit_cost FROM pharmacy_inventory WHERE inventory_status = '在库';
```

### 48 哪些药品属于管控药品

题目：哪些药品属于管控药品？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE is_controlled_substance = 1;
```

### 49 统计每个月新增的患者数量

题目：统计每个月新增的患者数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(create_time, '%Y-%m') AS reg_month, COUNT(*) AS patient_cnt FROM patient_master_index GROUP BY DATE_FORMAT(create_time, '%Y-%m') ORDER BY reg_month;
```

### 50 哪些患者超过60岁

题目：哪些患者超过60岁？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM patient_master_index WHERE age > 60 AND delete_flag = 'N';
```

### 51 看看急诊科现在有多少床位

题目：看看急诊科现在有多少床位？，请输出对应SQL语句

参考 SQL：
```sql
SELECT total_beds FROM departments_wards WHERE name = '急诊科';
```

### 52 统计各种就诊类型的数量

题目：统计各种就诊类型的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_type, COUNT(*) AS visit_cnt FROM medical_encounters GROUP BY encounter_type;
```

### 53 哪些药品快过期了（3个月内）

题目：哪些药品快过期了（3个月内）？，请输出对应SQL语句

参考 SQL：
```sql
SELECT batch_number, drug_id, expiration_date FROM pharmacy_inventory WHERE expiration_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 3 MONTH);
```

### 54 查查员工绩效最好的前10名

题目：查查员工绩效最好的前10名，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, performance_score FROM medical_staff ORDER BY performance_score DESC LIMIT 10;
```

### 55 统计不同医保类型的患者分布

题目：统计不同医保类型的患者分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT insurance_type, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY insurance_type;
```

### 56 哪些患者被标记为黑名单

题目：哪些患者被标记为黑名单？，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE is_blacklist = 1 AND delete_flag = 'N';
```

### 57 看看医院的科室都分布在哪些楼

题目：看看医院的科室都分布在哪些楼？，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT location_building FROM departments_wards WHERE location_building IS NOT NULL AND location_building <> '';
```

### 58 统计一下药品库存状态分布

题目：统计一下药品库存状态分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT inventory_status, COUNT(*) AS batch_cnt FROM pharmacy_inventory GROUP BY inventory_status;
```

### 59 哪些医嘱被取消了？原因是什么

题目：哪些医嘱被取消了？原因是什么？，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_id, item_name, cancel_reason FROM medical_orders WHERE execution_status = '已取消';
```

### 60 查查医生和护士分别有多少人

题目：查查医生和护士分别有多少人？，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(CASE WHEN job_title LIKE '%医师%' THEN 1 ELSE 0 END) AS doctor_cnt, SUM(CASE WHEN job_title LIKE '%护士%' THEN 1 ELSE 0 END) AS nurse_cnt FROM medical_staff WHERE is_active = 1;
```

### 61 看看体温异常的患者（>37.5℃）

题目：看看体温异常的患者（>37.5℃），请输出对应SQL语句

参考 SQL：
```sql
SELECT e.*, p.patient_name FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE e.temperature > 37.5;
```

### 62 统计各设备的使用状态

题目：统计各设备的使用状态，请输出对应SQL语句

参考 SQL：
```sql
SELECT usage_status, COUNT(*) AS usage_cnt FROM medical_equipment_usage GROUP BY usage_status;
```

### 63 哪些账单还没付款

题目：哪些账单还没付款？，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM billing_transactions WHERE payment_status IN ('未支付', '部分支付') OR outstanding_amount > 0;
```

### 64 查出所有男患者的名字和出生日期

题目：查出所有男患者的名字和出生日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, birth_date FROM patient_master_index WHERE gender = 'M' AND delete_flag = 'N';
```

### 65 列出所有医保类型为'城镇职工医保'的患者姓名和医保余额

题目：列出所有医保类型为'城镇职工医保'的患者姓名和医保余额，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, insurance_balance FROM patient_master_index WHERE insurance_type = '城镇职工医保' AND delete_flag = 'N';
```

### 66 找出所有未支付的就诊记录ID和总费用

题目：找出所有未支付的就诊记录ID和总费用，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, total_cost FROM medical_encounters WHERE is_paid = 0;
```

### 67 查出所有医生的姓名、工号和科室ID

题目：查出所有医生的姓名、工号和科室ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, employee_no, department_id FROM medical_staff WHERE job_title LIKE '%医师%' AND is_active = 1;
```

### 68 列出所有药品类医嘱的项目名称和数量

题目：列出所有药品类医嘱的项目名称和数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_id, item_name, order_quantity FROM medical_orders WHERE order_type = '药品';
```

### 69 查出所有库存状态为'在库'的药品批次号和当前数量

题目：查出所有库存状态为'在库'的药品批次号和当前数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT batch_number, current_quantity FROM pharmacy_inventory WHERE inventory_status = '在库';
```

### 70 找出所有使用类型为'诊疗使用'的设备使用记录ID和使用时长

题目：找出所有使用类型为'诊疗使用'的设备使用记录ID和使用时长，请输出对应SQL语句

参考 SQL：
```sql
SELECT usage_id, duration_minutes FROM medical_equipment_usage WHERE usage_type = '诊疗使用';
```

### 71 列出所有已支付的账单号和患者支付金额

题目：列出所有已支付的账单号和患者支付金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT billing_no, patient_paid FROM billing_transactions WHERE payment_status = '已支付';
```

### 72 查出所有急诊科的科室名称和总床位数

题目：查出所有急诊科的科室名称和总床位数，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, total_beds FROM departments_wards WHERE name = '急诊科';
```

### 73 找出所有黑名单患者的名字和联系方式

题目：找出所有黑名单患者的名字和联系方式，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, contact_phone FROM patient_master_index WHERE is_blacklist = 1 AND delete_flag = 'N';
```

### 74 列出所有男性患者的姓名和出生日期

题目：列出所有男性患者的姓名和出生日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, birth_date FROM patient_master_index WHERE gender = 'M' AND delete_flag = 'N';
```

### 75 找出医保类型是'城镇职工医保'的患者数量

题目：找出医保类型是'城镇职工医保'的患者数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS patient_cnt FROM patient_master_index WHERE insurance_type = '城镇职工医保' AND delete_flag = 'N';
```

### 76 显示所有姓'李'的患者信息

题目：显示所有姓'李'的患者信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM patient_master_index WHERE patient_name LIKE '李%' AND delete_flag = 'N';
```

### 77 列出所有在2023年创建的就诊记录ID和就诊日期

题目：列出所有在2023年创建的就诊记录ID和就诊日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, encounter_date FROM medical_encounters WHERE YEAR(encounter_date) = 2023;
```

### 78 有多少种不同的诊断描述

题目：有多少种不同的诊断描述？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT diagnosis_desc) AS diag_cnt FROM medical_encounters;
```

### 79 列出所有在职的医护人员姓名和工号

题目：列出所有在职的医护人员姓名和工号，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_name, employee_no FROM medical_staff WHERE is_active = 1;
```

### 80 显示所有属于'临床科室'类型的科室名称和代码

题目：显示所有属于'临床科室'类型的科室名称和代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, code FROM departments_wards WHERE type = '临床科室';
```

### 81 找出所有已支付的账单总净额是多少

题目：找出所有已支付的账单总净额是多少？，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(net_amount) AS total_net FROM billing_transactions WHERE payment_status = '已支付';
```

### 82 列出所有单价超过100元的药品医嘱的ID和总价

题目：列出所有单价超过100元的药品医嘱的ID和总价，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_id, total_price FROM medical_orders WHERE order_type = '药品' AND unit_price > 100;
```

### 83 显示患者'王建国'的身份证号和联系电话

题目：显示患者'王建国'的身份证号和联系电话，请输出对应SQL语句

参考 SQL：
```sql
SELECT national_id, contact_phone FROM patient_master_index WHERE patient_name = '王建国' AND delete_flag = 'N';
```

### 84 找出所有在'门诊药房'存储的药品库存记录

题目：找出所有在'门诊药房'存储的药品库存记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE storage_location = '门诊药房';
```

### 85 有多少台医疗设备的下次维护日期已经过了今天

题目：有多少台医疗设备的下次维护日期已经过了今天？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT equipment_id) AS need_maintain_cnt FROM medical_equipment_usage WHERE next_maintenance_date < CURDATE();
```

### 86 列出所有职位是'主任医师'的在职医生姓名

题目：列出所有职位是'主任医师'的在职医生姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_name FROM medical_staff WHERE job_title = '主任医师' AND is_active = 1;
```

### 87 显示所有被标记为黑名单的患者ID和姓名

题目：显示所有被标记为黑名单的患者ID和姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE is_blacklist = 1 AND delete_flag = 'N';
```

### 88 找出所有在2024年10月开具的医嘱ID和开始时间

题目：找出所有在2024年10月开具的医嘱ID和开始时间，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_id, start_datetime FROM medical_orders WHERE DATE_FORMAT(start_datetime, '%Y-%m') = '2024-10';
```

### 89 列出所有'检查'类型的医嘱，并按单价降序排列

题目：列出所有'检查'类型的医嘱，并按单价降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_orders WHERE order_type = '检查' ORDER BY unit_price DESC;
```

### 90 显示所有医保拒付率为100%（即医保覆盖率为0）的账单详情

题目：显示所有医保拒付率为100%（即医保覆盖率为0）的账单详情，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM billing_transactions WHERE insurance_coverage = 0;
```

### 91 找出所有'儿科'科室的总床位数和可用床位数

题目：找出所有'儿科'科室的总床位数和可用床位数，请输出对应SQL语句

参考 SQL：
```sql
SELECT total_beds, available_beds FROM departments_wards WHERE name LIKE '%儿科%';
```

### 92 列出所有体温高于38.5摄氏度的就诊记录ID和体温值

题目：列出所有体温高于38.5摄氏度的就诊记录ID和体温值，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, temperature FROM medical_encounters WHERE temperature > 38.5;
```

### 93 列出所有男性患者的姓名和出生日期

题目：列出所有男性患者的姓名和出生日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, birth_date FROM patient_master_index WHERE gender = 'M' AND delete_flag = 'N';
```

### 94 找出所有医保类型是“城镇职工医保”的患者数量

题目：找出所有医保类型是“城镇职工医保”的患者数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS patient_cnt FROM patient_master_index WHERE insurance_type = '城镇职工医保' AND delete_flag = 'N';
```

### 95 显示所有医生的工号、姓名和职位

题目：显示所有医生的工号、姓名和职位，请输出对应SQL语句

参考 SQL：
```sql
SELECT employee_no, staff_name, job_title FROM medical_staff WHERE job_title LIKE '%医师%';
```

### 96 列出所有药品库存中当前数量大于1000的药品ID和数量

题目：列出所有药品库存中当前数量大于1000的药品ID和数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT drug_id, current_quantity FROM pharmacy_inventory WHERE current_quantity > 1000;
```

### 97 找出所有已支付的账单总净额是多少

题目：找出所有已支付的账单总净额是多少？，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(net_amount) AS total_net FROM billing_transactions WHERE payment_status = '已支付';
```

### 98 查询所有在2024年创建的就诊记录ID和就诊日期

题目：查询所有在2024年创建的就诊记录ID和就诊日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, encounter_date FROM medical_encounters WHERE YEAR(encounter_date) = 2024;
```

### 99 显示所有护士的姓名和联系电话

题目：显示所有护士的姓名和联系电话，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_name, contact_phone FROM medical_staff WHERE job_title LIKE '%护士%';
```

### 100 列出所有科室的名称和所在楼栋

题目：列出所有科室的名称和所在楼栋，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, location_building FROM departments_wards;
```

### 101 找出所有处方医嘱的总价格最高的前5条记录

题目：找出所有处方医嘱的总价格最高的前5条记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_id, item_name, total_price FROM medical_orders WHERE order_type = '药品' ORDER BY total_price DESC LIMIT 5;
```

### 102 查询所有患者的平均年龄

题目：查询所有患者的平均年龄，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(age) AS avg_age FROM patient_master_index WHERE delete_flag = 'N';
```

### 103 显示所有在“门诊药房”存储的药品库存ID和批号

题目：显示所有在“门诊药房”存储的药品库存ID和批号，请输出对应SQL语句

参考 SQL：
```sql
SELECT inventory_id, batch_number FROM pharmacy_inventory WHERE storage_location = '门诊药房';
```

### 104 列出所有已离职的员工姓名和离职日期

题目：列出所有已离职的员工姓名和离职日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_name, resignation_date FROM medical_staff WHERE is_active = 0 AND resignation_date IS NOT NULL;
```

### 105 找出所有“检查”类型的医嘱数量

题目：找出所有“检查”类型的医嘱数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS check_cnt FROM medical_orders WHERE order_type = '检查';
```

### 106 查询所有患者主索引表中，医保余额大于等于10000元的患者人数

题目：查询所有患者主索引表中，医保余额大于等于10000元的患者人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS patient_cnt FROM patient_master_index WHERE insurance_balance >= 10000 AND delete_flag = 'N';
```

### 107 显示所有“儿科”的科室ID和负责人ID

题目：显示所有“儿科”的科室ID和负责人ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT dept_ward_id, head_doctor_id FROM departments_wards WHERE name LIKE '%儿科%';
```

### 108 列出所有在2025年到期的药品库存ID和到期日期

题目：列出所有在2025年到期的药品库存ID和到期日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT inventory_id, expiration_date FROM pharmacy_inventory WHERE YEAR(expiration_date) = 2025;
```

### 109 找出所有“VIP”级别的患者姓名和联系方式

题目：找出所有“VIP”级别的患者姓名和联系方式，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, contact_phone FROM patient_master_index WHERE patient_level = 'VIP' AND delete_flag = 'N';
```

### 110 查询所有“急诊”就诊类型的平均费用

题目：查询所有“急诊”就诊类型的平均费用，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(total_cost) AS avg_cost FROM medical_encounters WHERE encounter_type = '急诊';
```

### 111 列出所有设备使用记录中，使用时长大于60分钟的记录ID和时长

题目：列出所有设备使用记录中，使用时长大于60分钟的记录ID和时长，请输出对应SQL语句

参考 SQL：
```sql
SELECT usage_id, duration_minutes FROM medical_equipment_usage WHERE duration_minutes > 60;
```

### 112 列出所有男性的患者姓名和联系方式

题目：列出所有男性的患者姓名和联系方式，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, contact_phone FROM patient_master_index WHERE gender = 'M' AND delete_flag = 'N';
```

### 113 找找看有没有叫'李华'的患者，显示他的ID和医保类型

题目：找找看有没有叫'李华'的患者，显示他的ID和医保类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, insurance_type FROM patient_master_index WHERE patient_name = '李华' AND delete_flag = 'N';
```

### 114 把所有被标记为黑名单的患者ID给我瞅瞅

题目：把所有被标记为黑名单的患者ID给我瞅瞅，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id FROM patient_master_index WHERE is_blacklist = 1 AND delete_flag = 'N';
```

### 115 查一下所有血型是'O'型的患者有多少个

题目：查一下所有血型是'O'型的患者有多少个，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS patient_cnt FROM patient_master_index WHERE blood_type = 'O' AND delete_flag = 'N';
```

### 116 给我一份2023年新增的所有患者的名单和创建时间

题目：给我一份2023年新增的所有患者的名单和创建时间，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name, create_time FROM patient_master_index WHERE YEAR(create_time) = 2023 AND delete_flag = 'N';
```

### 117 看看哪个科室代码是'DEPT001'，叫啥名字

题目：看看哪个科室代码是'DEPT001'，叫啥名字，请输出对应SQL语句

参考 SQL：
```sql
SELECT name FROM departments_wards WHERE code = 'DEPT001';
```

### 118 列出所有属于'临床科室'类型的科室名称

题目：列出所有属于'临床科室'类型的科室名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT name FROM departments_wards WHERE type = '临床科室';
```

### 119 找出总床位超过40张的科室有哪些

题目：找出总床位超过40张的科室有哪些，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, total_beds FROM departments_wards WHERE total_beds > 40;
```

### 120 告诉我所有在职的医生和护士的名字

题目：告诉我所有在职的医生和护士的名字，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_name FROM medical_staff WHERE is_active = 1 AND (job_title LIKE '%医师%' OR job_title LIKE '%护士%');
```

### 121 列出所有职称是'主任医师'的员工工号和姓名

题目：列出所有职称是'主任医师'的员工工号和姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT employee_no, staff_name FROM medical_staff WHERE job_title = '主任医师';
```

### 122 看看哪些药品批次号里带有'2024'的

题目：看看哪些药品批次号里带有'2024'的，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE batch_number LIKE '%2024%';
```

### 123 查一下库存里'阿莫西林胶囊'的总数量（假设drug_id=12345代表它）

题目：查一下库存里'阿莫西林胶囊'的总数量（假设drug_id=12345代表它），请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(current_quantity) AS total_qty FROM pharmacy_inventory WHERE drug_id = 12345;
```

### 124 列出所有已经过期的药品批次

题目：列出所有已经过期的药品批次，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE expiration_date < CURDATE();
```

### 125 找找看单价低于5元的药品库存记录

题目：找找看单价低于5元的药品库存记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM pharmacy_inventory WHERE unit_cost < 5;
```

### 126 列出所有'门诊'类型的就诊记录ID和日期

题目：列出所有'门诊'类型的就诊记录ID和日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, encounter_date FROM medical_encounters WHERE encounter_type = '门诊';
```

### 127 查一下诊断为'高血压'的就诊次数

题目：查一下诊断为'高血压'的就诊次数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS visit_cnt FROM medical_encounters WHERE diagnosis_desc LIKE '%高血压%';
```

### 128 找出体温高于38.5度的就诊记录ID

题目：找出体温高于38.5度的就诊记录ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id FROM medical_encounters WHERE temperature > 38.5;
```

### 129 列出所有还没付费的就诊记录ID

题目：列出所有还没付费的就诊记录ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id FROM medical_encounters WHERE is_paid = 0;
```

### 130 看看有多少病人是黑名单用户

题目：看看有多少病人是黑名单用户？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS blacklist_cnt FROM patient_master_index WHERE is_blacklist = 1 AND delete_flag = 'N';
```

### 131 统计不同性别的患者数量

题目：统计不同性别的患者数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT gender, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY gender;
```

### 132 查查年龄大于60岁的老年患者有哪些

题目：查查年龄大于60岁的老年患者有哪些，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE age > 60 AND delete_flag = 'N';
```

### 133 找找那些没有血型记录的病人

题目：找找那些没有血型记录的病人，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE (blood_type IS NULL OR blood_type = '') AND delete_flag = 'N';
```

### 134 看看哪些病人是VIP等级的

题目：看看哪些病人是VIP等级的，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name FROM patient_master_index WHERE patient_level = 'VIP' AND delete_flag = 'N';
```

### 135 统计不同类型的医保患者数量

题目：统计不同类型的医保患者数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT insurance_type, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY insurance_type;
```

### 136 看看2024年1月创建的患者档案

题目：看看2024年1月创建的患者档案，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM patient_master_index WHERE DATE_FORMAT(create_time, '%Y-%m') = '2024-01' AND delete_flag = 'N';
```

### 137 查查最近一个月更新的患者信息

题目：查查最近一个月更新的患者信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM patient_master_index WHERE update_time >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH) AND delete_flag = 'N';
```

### 138 统计各年龄段患者分布

题目：统计各年龄段患者分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN age < 18 THEN '未成年' WHEN age BETWEEN 18 AND 35 THEN '青年' WHEN age BETWEEN 36 AND 60 THEN '中年' ELSE '老年' END AS age_group, COUNT(*) AS patient_cnt FROM patient_master_index WHERE delete_flag = 'N' GROUP BY age_group;
```

### 139 看看不同职位的医护人员有多少

题目：看看不同职位的医护人员有多少，请输出对应SQL语句

参考 SQL：
```sql
SELECT job_title, COUNT(*) AS staff_cnt FROM medical_staff GROUP BY job_title;
```

### 140 查查哪些医护人员是主任医师

题目：查查哪些医护人员是主任医师，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name FROM medical_staff WHERE job_title = '主任医师';
```

### 141 统计各科室的医护人员数量

题目：统计各科室的医护人员数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_id, COUNT(*) AS staff_cnt FROM medical_staff WHERE is_active = 1 GROUP BY department_id;
```

### 142 看看已离职的医护人员

题目：看看已离职的医护人员，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, resignation_date FROM medical_staff WHERE is_active = 0;
```

### 143 查查绩效分数在90分以上的优秀员工

题目：查查绩效分数在90分以上的优秀员工，请输出对应SQL语句

参考 SQL：
```sql
SELECT staff_id, staff_name, performance_score FROM medical_staff WHERE performance_score >= 90;
```

### 144 看看哪些科室有可用床位

题目：看看哪些科室有可用床位，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, available_beds FROM departments_wards WHERE available_beds > 0;
```

### 145 统计各类科室的数量

题目：统计各类科室的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT type, COUNT(*) AS dept_cnt FROM departments_wards GROUP BY type;
```

### 146 查查在门诊楼的科室

题目：查查在门诊楼的科室，请输出对应SQL语句

参考 SQL：
```sql
SELECT name FROM departments_wards WHERE location_building LIKE '%门诊%';
```

### 147 看看科室的联系方式

题目：看看科室的联系方式，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, contact_number, email FROM departments_wards;
```

### 148 统计启用状态的科室数量

题目：统计启用状态的科室数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS active_dept_cnt FROM departments_wards WHERE is_active = 1;
```

### 149 每个科室的医生数量是多少？按医生数从多到少排

题目：每个科室的医生数量是多少？按医生数从多到少排，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, COUNT(s.staff_id) AS doctor_cnt FROM departments_wards d LEFT JOIN medical_staff s ON d.dept_ward_id = s.department_id AND s.job_title LIKE '%医师%' AND s.is_active = 1 GROUP BY d.dept_ward_id, d.name ORDER BY doctor_cnt DESC;
```

### 150 看看每个科室接诊的患者人数，按从多到少排序

题目：看看每个科室接诊的患者人数，按从多到少排序，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, COUNT(DISTINCT e.patient_id) AS patient_cnt FROM medical_encounters e JOIN departments_wards d ON e.department_id = d.dept_ward_id GROUP BY d.dept_ward_id, d.name ORDER BY patient_cnt DESC;
```

### 151 找出每个患者最近一次就诊的时间和诊断

题目：找出每个患者最近一次就诊的时间和诊断，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, encounter_id, encounter_date, diagnosis_desc FROM (SELECT patient_id, encounter_id, encounter_date, diagnosis_desc, ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY encounter_date DESC) AS rn FROM medical_encounters) t WHERE rn = 1;
```

### 152 统计各医生的平均接诊费用和接诊次数

题目：统计各医生的平均接诊费用和接诊次数，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, AVG(e.total_cost) AS avg_cost, COUNT(e.encounter_id) AS visit_cnt FROM medical_encounters e JOIN medical_staff s ON e.doctor_id = s.staff_id WHERE s.job_title LIKE '%医师%' GROUP BY s.staff_id, s.staff_name;
```

### 153 找出住院时间超过10天的患者及所在科室

题目：找出住院时间超过10天的患者及所在科室，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.patient_name, d.name AS department_name, DATEDIFF(e.discharge_date, e.encounter_date) AS stay_days FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id JOIN departments_wards d ON e.department_id = d.dept_ward_id WHERE e.encounter_type = '住院' AND DATEDIFF(e.discharge_date, e.encounter_date) > 10;
```

### 154 查询患者就诊时开出的药品及价格

题目：查询患者就诊时开出的药品及价格，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.patient_name, e.encounter_id, o.item_name, o.unit_price, o.order_quantity, o.total_price FROM medical_orders o JOIN medical_encounters e ON o.encounter_id = e.encounter_id JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE o.order_type = '药品';
```

### 155 统计各科室的月均收入

题目：统计各科室的月均收入，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, revenue_target / 12 AS monthly_income FROM departments_wards;
```

### 156 找出使用次数最多的医疗设备TOP 10

题目：找出使用次数最多的医疗设备TOP 10，请输出对应SQL语句

参考 SQL：
```sql
SELECT equipment_id, COUNT(*) AS use_cnt FROM medical_equipment_usage GROUP BY equipment_id ORDER BY use_cnt DESC LIMIT 10;
```

### 157 查询主任医师及其下属的医生信息

题目：查询主任医师及其下属的医生信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, sub.staff_name AS subordinate_name FROM medical_staff s LEFT JOIN medical_staff sub ON sub.supervisor_id = s.staff_id WHERE s.job_title = '主任医师';
```

### 158 查询同时有门诊和住院记录的患者

题目：查询同时有门诊和住院记录的患者，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id FROM medical_encounters GROUP BY patient_id HAVING SUM(encounter_type = '门诊') > 0 AND SUM(encounter_type = '住院') > 0;
```

### 159 找出费用最高的前5次就诊记录

题目：找出费用最高的前5次就诊记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM medical_encounters ORDER BY total_cost DESC LIMIT 5;
```

### 160 查询各科室的床位使用率

题目：查询各科室的床位使用率，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, total_beds, available_beds, (total_beds - available_beds) / total_beds * 100 AS bed_usage_rate FROM departments_wards WHERE total_beds > 0;
```

### 161 统计每月药品采购金额

题目：统计每月药品采购金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(purchase_date, '%Y-%m') AS purchase_month, SUM(total_cost) AS purchase_amount FROM pharmacy_inventory GROUP BY DATE_FORMAT(purchase_date, '%Y-%m') ORDER BY purchase_month;
```

### 162 找出重复的药品批次记录

题目：找出重复的药品批次记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT drug_id, batch_number, COUNT(*) AS dup_cnt FROM pharmacy_inventory GROUP BY drug_id, batch_number HAVING COUNT(*) > 1;
```

### 163 查询各年龄段患者的平均就诊费用

题目：查询各年龄段患者的平均就诊费用，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN p.age < 18 THEN '未成年' WHEN p.age BETWEEN 18 AND 35 THEN '青年' WHEN p.age BETWEEN 36 AND 60 THEN '中年' ELSE '老年' END AS age_group, AVG(e.total_cost) AS avg_cost FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id GROUP BY age_group;
```

### 164 统计各供应商的药品采购情况

题目：统计各供应商的药品采购情况，请输出对应SQL语句

参考 SQL：
```sql
SELECT supplier_id, COUNT(*) AS batch_cnt, SUM(total_cost) AS total_cost FROM pharmacy_inventory GROUP BY supplier_id;
```

### 165 查询医护人员的排班冲突情况

题目：查询医护人员的排班冲突情况，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT s.staff_id, s.staff_name FROM medical_staff s JOIN JSON_TABLE(s.work_schedule, '$[*]' COLUMNS(d VARCHAR(10) PATH '$.date', st TIME PATH '$.start_time', et TIME PATH '$.end_time')) a JOIN JSON_TABLE(s.work_schedule, '$[*]' COLUMNS(d VARCHAR(10) PATH '$.date', st TIME PATH '$.start_time', et TIME PATH '$.end_time')) b ON a.d = b.d AND a.st < b.et AND b.st < a.et AND NOT (a.st = b.st AND a.et = b.et);
```

### 166 找出超过90天未使用的设备

题目：找出超过90天未使用的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT equipment_id, MAX(start_time) AS last_use_time FROM medical_equipment_usage GROUP BY equipment_id HAVING MAX(start_time) < DATE_SUB(CURDATE(), INTERVAL 90 DAY);
```

### 167 查出每个患者最近一次就诊的日期、科室名和主治医生名

题目：查出每个患者最近一次就诊的日期、科室名和主治医生名，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, encounter_date, department_name, doctor_name FROM (SELECT e.patient_id, e.encounter_date, d.name AS department_name, s.staff_name AS doctor_name, ROW_NUMBER() OVER (PARTITION BY e.patient_id ORDER BY e.encounter_date DESC) AS rn FROM medical_encounters e LEFT JOIN departments_wards d ON e.department_id = d.dept_ward_id LEFT JOIN medical_staff s ON e.doctor_id = s.staff_id) t WHERE rn = 1;
```

### 168 列出所有住院超过7天的患者姓名、住院天数和总费用

题目：列出所有住院超过7天的患者姓名、住院天数和总费用，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.patient_name, DATEDIFF(e.discharge_date, e.encounter_date) AS stay_days, e.total_cost FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE e.encounter_type = '住院' AND DATEDIFF(e.discharge_date, e.encounter_date) > 7;
```

### 169 找出每个科室的负责人姓名和联系电话

题目：找出每个科室的负责人姓名和联系电话，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, s.staff_name AS head_doctor, s.contact_phone FROM departments_wards d LEFT JOIN medical_staff s ON d.head_doctor_id = s.staff_id;
```

### 170 查出所有自费患者的就诊记录，包括姓名、就诊类型和自付金额

题目：查出所有自费患者的就诊记录，包括姓名、就诊类型和自付金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.patient_name, e.encounter_type, e.patient_payment FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE e.insurance_payment = 0 AND e.patient_payment > 0;
```

### 171 列出所有过期药品的名称、批次号和过期日期

题目：列出所有过期药品的名称、批次号和过期日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT batch_number, expiration_date FROM pharmacy_inventory WHERE expiration_date < CURDATE();
```

### 172 查出每位医生开的药品类医嘱总金额（按医生分组）

题目：查出每位医生开的药品类医嘱总金额（按医生分组），请输出对应SQL语句

参考 SQL：
```sql
SELECT e.doctor_id, s.staff_name, SUM(o.total_price) AS total_amount FROM medical_orders o JOIN medical_encounters e ON o.encounter_id = e.encounter_id LEFT JOIN medical_staff s ON e.doctor_id = s.staff_id WHERE o.order_type = '药品' GROUP BY e.doctor_id, s.staff_name;
```

### 173 列出2024年每个科室的就诊人次，并按人次降序排列

题目：列出2024年每个科室的就诊人次，并按人次降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, COUNT(e.encounter_id) AS visit_cnt FROM medical_encounters e JOIN departments_wards d ON e.department_id = d.dept_ward_id WHERE YEAR(e.encounter_date) = 2024 GROUP BY d.dept_ward_id, d.name ORDER BY visit_cnt DESC;
```

### 174 找出每个患者的最新一次就诊日期和诊断描述

题目：找出每个患者的最新一次就诊日期和诊断描述，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, encounter_id, encounter_date, diagnosis_desc FROM (SELECT patient_id, encounter_id, encounter_date, diagnosis_desc, ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY encounter_date DESC) AS rn FROM medical_encounters) t WHERE rn = 1;
```

### 175 统计每个医生（按姓名）在2024年的接诊次数和总收入

题目：统计每个医生（按姓名）在2024年的接诊次数和总收入，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, COUNT(e.encounter_id) AS visit_cnt, SUM(e.total_cost) AS total_income FROM medical_encounters e JOIN medical_staff s ON e.doctor_id = s.staff_id WHERE YEAR(e.encounter_date) = 2024 GROUP BY s.staff_id, s.staff_name;
```

### 176 列出所有药品医嘱中，使用了'阿莫西林'的患者姓名、就诊ID和用药数量

题目：列出所有药品医嘱中，使用了'阿莫西林'的患者姓名、就诊ID和用药数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.patient_name, e.encounter_id, o.order_quantity FROM medical_orders o JOIN medical_encounters e ON o.encounter_id = e.encounter_id JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE o.order_type = '药品' AND o.item_name LIKE '%阿莫西林%';
```

### 177 显示每个科室的主任医生姓名和护士长姓名

题目：显示每个科室的主任医生姓名和护士长姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, hd.staff_name AS head_doctor, hn.staff_name AS head_nurse FROM departments_wards d LEFT JOIN medical_staff hd ON d.head_doctor_id = hd.staff_id LEFT JOIN medical_staff hn ON d.head_nurse_id = hn.staff_id;
```

### 178 计算每个患者在2024年的总消费金额和医保支付总额

题目：计算每个患者在2024年的总消费金额和医保支付总额，请输出对应SQL语句

参考 SQL：
```sql
SELECT e.patient_id, SUM(e.total_cost) AS total_cost, SUM(e.insurance_payment) AS total_insurance FROM medical_encounters e WHERE YEAR(e.encounter_date) = 2024 GROUP BY e.patient_id;
```

### 179 列出所有在2024年11月有过就诊记录的患者姓名和联系电话

题目：列出所有在2024年11月有过就诊记录的患者姓名和联系电话，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.patient_name, p.contact_phone FROM patient_master_index p JOIN medical_encounters e ON p.patient_id = e.patient_id WHERE DATE_FORMAT(e.encounter_date, '%Y-%m') = '2024-11';
```

### 180 统计不同医保类型患者的平均年龄

题目：统计不同医保类型患者的平均年龄，请输出对应SQL语句

参考 SQL：
```sql
SELECT insurance_type, AVG(age) AS avg_age FROM patient_master_index WHERE delete_flag = 'N' GROUP BY insurance_type;
```

### 181 找出所有由'张伟'医生诊治过的门诊患者姓名和就诊日期

题目：找出所有由'张伟'医生诊治过的门诊患者姓名和就诊日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.patient_name, e.encounter_date FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id JOIN medical_staff s ON e.doctor_id = s.staff_id WHERE s.staff_name = '张伟' AND e.encounter_type = '门诊';
```

### 182 显示所有'检查'费用的项目描述、数量、单价和总净额，并关联到账单表

题目：显示所有'检查'费用的项目描述、数量、单价和总净额，并关联到账单表，请输出对应SQL语句

参考 SQL：
```sql
SELECT b.billing_no, b.item_description, b.quantity, b.unit_price, b.net_amount FROM billing_transactions b WHERE b.item_type = '检查';
```

### 183 列出所有在2023年采购、且将在未来6个月内过期的药品批次号和过期日期

题目：列出所有在2023年采购、且将在未来6个月内过期的药品批次号和过期日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT batch_number, expiration_date FROM pharmacy_inventory WHERE YEAR(purchase_date) = 2023 AND expiration_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 6 MONTH);
```

### 184 找出所有执行状态为'已取消'的医嘱的医生姓名、患者姓名和取消原因

题目：找出所有执行状态为'已取消'的医嘱的医生姓名、患者姓名和取消原因，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name AS doctor_name, p.patient_name, o.cancel_reason FROM medical_orders o JOIN medical_encounters e ON o.encounter_id = e.encounter_id JOIN medical_staff s ON e.doctor_id = s.staff_id JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE o.execution_status = '已取消';
```

### 185 列出所有患者姓名和他们的紧急联系人姓名及关系

题目：列出所有患者姓名和他们的紧急联系人姓名及关系，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_name, JSON_UNQUOTE(JSON_EXTRACT(emergency_contact, '$.name')) AS contact_name, JSON_UNQUOTE(JSON_EXTRACT(emergency_contact, '$.relation')) AS relation FROM patient_master_index WHERE delete_flag = 'N';
```

### 186 找出所有在'心血管内科'就诊过的患者姓名和诊断描述

题目：找出所有在'心血管内科'就诊过的患者姓名和诊断描述，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.patient_name, e.diagnosis_desc FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id JOIN departments_wards d ON e.department_id = d.dept_ward_id WHERE d.name = '心血管内科';
```

### 187 显示每个医护人员的直接上级姓名

题目：显示每个医护人员的直接上级姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, sup.staff_name AS superior_name FROM medical_staff s LEFT JOIN medical_staff sup ON s.supervisor_id = sup.staff_id;
```

### 188 计算2024年每个季度的总收入（按就诊记录计算）

题目：计算2024年每个季度的总收入（按就诊记录计算），请输出对应SQL语句

参考 SQL：
```sql
SELECT QUARTER(e.encounter_date) AS q, SUM(e.total_cost) AS total_income FROM medical_encounters e WHERE YEAR(e.encounter_date) = 2024 GROUP BY QUARTER(e.encounter_date) ORDER BY q;
```

### 189 列出所有在2024年有过住院记录的患者姓名和他们的出院去向

题目：列出所有在2024年有过住院记录的患者姓名和他们的出院去向，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.patient_name, e.discharge_disposition FROM medical_encounters e JOIN patient_master_index p ON e.patient_id = p.patient_id WHERE e.encounter_type = '住院' AND YEAR(e.encounter_date) = 2024;
```

### 190 统计不同性别医护人员的数量

题目：统计不同性别医护人员的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT gender, COUNT(*) AS staff_cnt FROM medical_staff GROUP BY gender;
```

### 191 找出所有在同一天内有两次及以上就诊记录的患者ID和就诊日期

题目：找出所有在同一天内有两次及以上就诊记录的患者ID和就诊日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, DATE(encounter_date) AS visit_date, COUNT(*) AS visit_cnt FROM medical_encounters GROUP BY patient_id, DATE(encounter_date) HAVING COUNT(*) >= 2;
```

### 192 列出2024年每个科室的就诊人次，并按人次降序排列

题目：列出2024年每个科室的就诊人次，并按人次降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.name AS department_name, COUNT(e.encounter_id) AS visit_cnt FROM medical_encounters e JOIN departments_wards d ON e.department_id = d.dept_ward_id WHERE YEAR(e.encounter_date) = 2024 GROUP BY d.dept_ward_id, d.name ORDER BY visit_cnt DESC;
```

### 193 找出每个医生看过的病人总数，并列出看诊人数最多的前10位医生姓名

题目：找出每个医生看过的病人总数，并列出看诊人数最多的前10位医生姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, COUNT(DISTINCT e.patient_id) AS patient_cnt FROM medical_encounters e JOIN medical_staff s ON e.doctor_id = s.staff_id GROUP BY s.staff_id, s.staff_name ORDER BY patient_cnt DESC LIMIT 10;
```

### 194 统计每个患者在2024年的总消费金额（包括医保和个人支付）

题目：统计每个患者在2024年的总消费金额（包括医保和个人支付），请输出对应SQL语句

参考 SQL：
```sql
SELECT e.patient_id, SUM(e.insurance_payment + e.patient_payment) AS total_cost FROM medical_encounters e WHERE YEAR(e.encounter_date) = 2024 GROUP BY e.patient_id;
```

### 195 列出所有在“药剂科”工作的员工姓名和职位

题目：列出所有在“药剂科”工作的员工姓名和职位，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_name, s.job_title FROM medical_staff s JOIN departments_wards d ON s.department_id = d.dept_ward_id WHERE d.name = '药剂科';
```

### 196 找出所有“检查”类医嘱对应的项目名称和总费用，并按费用降序排

题目：找出所有“检查”类医嘱对应的项目名称和总费用，并按费用降序排，请输出对应SQL语句

参考 SQL：
```sql
SELECT item_name, SUM(total_price) AS total_cost FROM medical_orders WHERE order_type = '检查' AND execution_status = '已执行' GROUP BY item_name ORDER BY total_cost DESC;
```

### 197 查询2024年每个月的总收入（净额）

题目：查询2024年每个月的总收入（净额），请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(transaction_date, '%Y-%m') AS income_month, SUM(net_amount) AS total_income FROM billing_transactions WHERE YEAR(transaction_date) = 2024 GROUP BY DATE_FORMAT(transaction_date, '%Y-%m') ORDER BY income_month;
```

### 198 帮我算算每个患者一共看过几次病

题目：帮我算算每个患者一共看过几次病，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, COUNT(*) AS visit_cnt FROM medical_encounters GROUP BY patient_id;
```

### 199 列出看诊次数超过5次的患者ID和看诊次数

题目：列出看诊次数超过5次的患者ID和看诊次数，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, COUNT(*) AS visit_cnt FROM medical_encounters GROUP BY patient_id HAVING COUNT(*) > 5;
```

### 200 算算每个科室的平均床位使用率

题目：算算每个科室的平均床位使用率，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, (total_beds - available_beds) / total_beds AS avg_bed_usage_rate FROM departments_wards WHERE total_beds > 0;
```

### 201 找出平均绩效评分最高的职位

题目：找出平均绩效评分最高的职位，请输出对应SQL语句

参考 SQL：
```sql
SELECT job_title FROM medical_staff GROUP BY job_title ORDER BY AVG(performance_score) DESC LIMIT 1;
```

### 202 看看每个月新增多少患者

题目：看看每个月新增多少患者，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(create_time, '%Y-%m') AS reg_month, COUNT(*) AS patient_cnt FROM patient_master_index GROUP BY DATE_FORMAT(create_time, '%Y-%m') ORDER BY reg_month;
```

### 203 算算哪种医嘱类型用得最多

题目：算算哪种医嘱类型用得最多，请输出对应SQL语句

参考 SQL：
```sql
SELECT order_type, COUNT(*) AS order_cnt FROM medical_orders GROUP BY order_type ORDER BY order_cnt DESC LIMIT 1;
```

### 204 看看哪个护士执行的医嘱数量最多

题目：看看哪个护士执行的医嘱数量最多，请输出对应SQL语句

参考 SQL：
```sql
SELECT executing_nurse_id, COUNT(*) AS order_cnt FROM medical_orders WHERE execution_status = '已执行' GROUP BY executing_nurse_id ORDER BY order_cnt DESC LIMIT 1;
```

### 205 看看每年医保支付总额是多少

题目：看看每年医保支付总额是多少，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(transaction_date) AS year, SUM(insurance_paid) AS total_insurance FROM billing_transactions GROUP BY YEAR(transaction_date) ORDER BY year;
```

### 206 找出每个科室床位数最多的那个科室

题目：找出每个科室床位数最多的那个科室，请输出对应SQL语句

参考 SQL：
```sql
SELECT name, total_beds FROM departments_wards ORDER BY total_beds DESC LIMIT 1;
```

### 207 查查同一科室里绩效前3的员工

题目：查查同一科室里绩效前3的员工，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_id, staff_id, staff_name, performance_score FROM (SELECT department_id, staff_id, staff_name, performance_score, ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY performance_score DESC) AS rn FROM medical_staff WHERE is_active = 1) t WHERE rn <= 3;
```

### 208 找出患者中年龄最大和最小的

题目：找出患者中年龄最大和最小的，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name, age FROM (SELECT patient_id, patient_name, age, RANK() OVER (ORDER BY age DESC) AS rk_desc, RANK() OVER (ORDER BY age ASC) AS rk_asc FROM patient_master_index WHERE delete_flag = 'N') t WHERE rk_desc = 1 OR rk_asc = 1;
```

### 209 统计医保余额大于平均值的患者

题目：统计医保余额大于平均值的患者，请输出对应SQL语句

参考 SQL：
```sql
SELECT patient_id, patient_name, insurance_balance FROM patient_master_index WHERE insurance_balance > (SELECT AVG(insurance_balance) FROM patient_master_index WHERE delete_flag = 'N') AND delete_flag = 'N';
```

### 210 看看哪些医生的绩效高于科室平均绩效

题目：看看哪些医生的绩效高于科室平均绩效，请输出对应SQL语句

参考 SQL：
```sql
SELECT s.staff_id, s.staff_name, s.department_id, s.performance_score FROM medical_staff s WHERE s.is_active = 1 AND s.job_title LIKE '%医师%' AND s.performance_score > (SELECT AVG(performance_score) FROM medical_staff WHERE department_id = s.department_id AND is_active = 1);
```

### 211 找出单次就诊总费用最高的5条记录

题目：找出单次就诊总费用（total_cost）最高的前5条就诊记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT encounter_id, patient_id, hospital_id, encounter_type, encounter_date, total_cost
FROM healthcare_analytics_competition.medical_encounters
ORDER BY total_cost DESC
LIMIT 5;
```

### 212 统计各支付状态的结算笔数和净额

题目：统计2024年1月各支付状态下的结算笔数和结算净额，请输出对应SQL语句

参考 SQL：
```sql
SELECT payment_status,
       COUNT(*) AS tx_cnt,
       ROUND(SUM(net_amount), 2) AS net_total
FROM healthcare_analytics_competition.billing_transactions
WHERE transaction_date >= '2024-01-01' AND transaction_date < '2024-02-01'
GROUP BY payment_status
ORDER BY net_total DESC;
```

### 213 找出库存低于再订货水平且效期临近的在库药品

题目：找出当前在库、库存不超过再订货水平、且有效期在90天内的药品批次，请输出对应SQL语句

参考 SQL：
```sql
SELECT drug_id, batch_number, current_quantity, reorder_level, expiration_date
FROM healthcare_analytics_competition.pharmacy_inventory
WHERE inventory_status = '在库'
  AND current_quantity <= reorder_level
  AND expiration_date >= CURDATE()
  AND expiration_date < DATE_ADD(CURDATE(), INTERVAL 90 DAY)
ORDER BY expiration_date ASC;
```

### 214 统计就诊次数最多的前10个科室

题目：统计就诊次数最多的前10个科室及其就诊次数，请输出对应SQL语句

参考 SQL：
```sql
SELECT dw.name AS dept_name, COUNT(*) AS encounter_cnt
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
GROUP BY dw.dept_ward_id, dw.name
ORDER BY encounter_cnt DESC
LIMIT 10;
```

### 215 统计各科室医疗收入排名与人均就诊费用

题目：按就诊口径统计各临床/医技科室（排除病区）的医疗收入（medical_encounters.total_cost 求和）、就诊人次与人均费用，按收入降序排列，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       COUNT(*) AS encounter_cnt,
       ROUND(SUM(me.total_cost), 2) AS total_revenue,
       ROUND(AVG(me.total_cost), 2) AS avg_cost_per_encounter
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
WHERE dw.type <> '病区'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY total_revenue DESC;
```

### 216 每位医生的接诊量与创收排名（关联医护与科室主档）

题目：统计2025年每位接诊人员的接诊人次与就诊创收（SUM(medical_encounters.total_cost)），并带出姓名、职称与其所属科室名称，按创收降序取前10，请输出对应SQL语句。口径说明：medical_encounters.doctor_id 关联的是 medical_staff 全量人员档案（含护士、技师、行政/后勤），如需只看医师，需按 job_title LIKE '%医师' 过滤；科室口径取医生主档 medical_staff.department_id。

参考 SQL：
```sql
SELECT ms.staff_id,
       ms.staff_name,
       ms.job_title,
       dw.name AS dept_name,
       COUNT(*) AS encounter_cnt,
       ROUND(SUM(me.total_cost), 2) AS revenue
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.medical_staff ms
  ON ms.staff_id = me.doctor_id
LEFT JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = ms.department_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
GROUP BY ms.staff_id, ms.staff_name, ms.job_title, dw.name
ORDER BY revenue DESC
LIMIT 10;
```

### 217 统计各科室结算收入与医保支付比例

题目：按结算口径（billing_transactions.net_amount）统计2025年各科室的结算净额、医保支付金额，并计算医保支付占结算净额的比例（%），排除病区并按结算净额降序，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       COUNT(*) AS tx_cnt,
       ROUND(SUM(bt.net_amount), 2) AS net_total,
       ROUND(SUM(bt.insurance_paid), 2) AS insurance_paid_total,
       ROUND(SUM(bt.insurance_paid) / SUM(bt.net_amount) * 100, 2) AS insurance_ratio_pct
FROM healthcare_analytics_competition.billing_transactions bt
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = bt.department_id
WHERE bt.transaction_date >= '2025-01-01' AND bt.transaction_date < '2026-01-01'
  AND dw.type <> '病区'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY net_total DESC;
```

### 218 按就诊类型与患者等级交叉统计人次和平均费用

题目：把2025年就诊记录与患者主档关联，按「就诊类型 × 患者等级」交叉统计就诊人次与平均单次费用，仅统计未删除患者（delete_flag='N'），请输出对应SQL语句（大表先用半开区间的时间条件收窄再关联）。

参考 SQL：
```sql
SELECT me.encounter_type,
       p.patient_level,
       COUNT(*) AS encounter_cnt,
       ROUND(AVG(me.total_cost), 2) AS avg_total_cost
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.patient_master_index p
  ON p.patient_id = me.patient_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  AND p.delete_flag = 'N'
GROUP BY me.encounter_type, p.patient_level
ORDER BY me.encounter_type, p.patient_level;
```

### 219 每个科室就诊量最高的前3名医生（分组 Top-N）

题目：统计2025年每个科室就诊人次最多的前3名医生，输出科室名、医生姓名与该医生在本科室的就诊人次及科内排名，请使用窗口函数实现，输出对应SQL语句。

参考 SQL：
```sql
WITH doctor_encounter AS (
  SELECT me.department_id,
         me.doctor_id,
         COUNT(*) AS encounter_cnt
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY me.department_id, me.doctor_id
), ranked AS (
  SELECT de.department_id,
         de.doctor_id,
         de.encounter_cnt,
         ROW_NUMBER() OVER (PARTITION BY de.department_id
                            ORDER BY de.encounter_cnt DESC, de.doctor_id) AS dept_rank
  FROM doctor_encounter de
)
SELECT dw.name AS dept_name,
       ms.staff_name,
       ms.job_title,
       r.encounter_cnt,
       r.dept_rank
FROM ranked r
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = r.department_id
JOIN healthcare_analytics_competition.medical_staff ms
  ON ms.staff_id = r.doctor_id
WHERE r.dept_rank <= 3
ORDER BY dw.name, r.dept_rank;
```

### 220 每个科室费用最高的前5位患者（分组 Top-N）

题目：统计2025年每个科室就诊总费用最高的前5位患者，输出科室名、患者姓名、该患者在本科室的就诊次数与累计费用及科内排名，请输出对应SQL语句。

参考 SQL：
```sql
WITH patient_cost AS (
  SELECT me.department_id,
         me.patient_id,
         COUNT(*) AS encounter_cnt,
         SUM(me.total_cost) AS patient_total_cost
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY me.department_id, me.patient_id
), ranked AS (
  SELECT pc.department_id,
         pc.patient_id,
         pc.encounter_cnt,
         pc.patient_total_cost,
         ROW_NUMBER() OVER (PARTITION BY pc.department_id
                            ORDER BY pc.patient_total_cost DESC, pc.patient_id) AS dept_rank
  FROM patient_cost pc
)
SELECT dw.name AS dept_name,
       p.patient_name,
       p.patient_level,
       r.encounter_cnt,
       ROUND(r.patient_total_cost, 2) AS patient_total_cost,
       r.dept_rank
FROM ranked r
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = r.department_id
JOIN healthcare_analytics_competition.patient_master_index p
  ON p.patient_id = r.patient_id
WHERE r.dept_rank <= 5
ORDER BY dw.name, r.dept_rank;
```

### 221 哪个医生最忙？全院接诊量前10的医师

题目：（口语化问法→业务口径：2025年全院接诊人次最多的医生）统计2025年接诊人次最多的前10名医师，输出姓名、职称、所属科室与接诊人次，请输出对应SQL语句。注意 doctor_id 关联的是 medical_staff 全量人员，必须加 ms.job_title LIKE '%医师' 才能只统计医师。

参考 SQL：
```sql
SELECT ms.staff_id,
       ms.staff_name,
       ms.job_title,
       dw.name AS dept_name,
       COUNT(*) AS encounter_cnt
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.medical_staff ms
  ON ms.staff_id = me.doctor_id
LEFT JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = ms.department_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  AND ms.job_title LIKE '%医师'
GROUP BY ms.staff_id, ms.staff_name, ms.job_title, dw.name
ORDER BY encounter_cnt DESC, ms.staff_id
LIMIT 10;
```

### 222 每个科室创收最高的前3名医生

题目：按就诊口径（SUM(medical_encounters.total_cost)）统计2025年每个科室创收最高的前3名医生，输出科室名、医生姓名、创收金额与科内排名，请输出对应SQL语句。

参考 SQL：
```sql
WITH doctor_revenue AS (
  SELECT me.department_id,
         me.doctor_id,
         COUNT(*) AS encounter_cnt,
         SUM(me.total_cost) AS revenue
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY me.department_id, me.doctor_id
), ranked AS (
  SELECT dr.department_id,
         dr.doctor_id,
         dr.encounter_cnt,
         dr.revenue,
         ROW_NUMBER() OVER (PARTITION BY dr.department_id
                            ORDER BY dr.revenue DESC, dr.doctor_id) AS dept_rank
  FROM doctor_revenue dr
)
SELECT dw.name AS dept_name,
       ms.staff_name,
       ms.job_title,
       r.encounter_cnt,
       ROUND(r.revenue, 2) AS revenue,
       r.dept_rank
FROM ranked r
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = r.department_id
JOIN healthcare_analytics_competition.medical_staff ms
  ON ms.staff_id = r.doctor_id
WHERE r.dept_rank <= 3
ORDER BY dw.name, r.dept_rank;
```

### 223 各患者等级人数与占比

题目：统计各患者等级（普通/VIP/SVIP）的在册人数及占全部未删除患者的比例（%），请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.patient_level,
       COUNT(*) AS patient_cnt,
       ROUND(COUNT(*) / (SELECT COUNT(*)
                         FROM healthcare_analytics_competition.patient_master_index
                         WHERE delete_flag = 'N') * 100, 2) AS ratio_pct
FROM healthcare_analytics_competition.patient_master_index p
WHERE p.delete_flag = 'N'
GROUP BY p.patient_level
ORDER BY patient_cnt DESC;
```

### 224 各科室结算收入占比（窗口函数计算占比）

题目：统计2025年各科室结算净额及其占全院结算净额的比例（%），排除病区并按净额降序，请用窗口函数 SUM() OVER () 计算占比，输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       ROUND(SUM(bt.net_amount), 2) AS net_total,
       ROUND(SUM(bt.net_amount) / SUM(SUM(bt.net_amount)) OVER () * 100, 2) AS ratio_pct
FROM healthcare_analytics_competition.billing_transactions bt
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = bt.department_id
WHERE bt.transaction_date >= '2025-01-01' AND bt.transaction_date < '2026-01-01'
  AND dw.type <> '病区'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY net_total DESC;
```

### 225 各医保类型患者占比与平均医保余额

题目：统计各医保类型（城镇职工医保/城乡居民医保/新农合/商业保险/公费医疗/自费）的患者人数、占比（%）与平均医保余额（insurance_balance，单位元），仅统计未删除患者，请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.insurance_type,
       COUNT(*) AS patient_cnt,
       ROUND(COUNT(*) / (SELECT COUNT(*)
                         FROM healthcare_analytics_competition.patient_master_index
                         WHERE delete_flag = 'N') * 100, 2) AS ratio_pct,
       ROUND(AVG(p.insurance_balance), 2) AS avg_insurance_balance
FROM healthcare_analytics_competition.patient_master_index p
WHERE p.delete_flag = 'N'
GROUP BY p.insurance_type
ORDER BY patient_cnt DESC;
```

### 226 2025年各月结算收入环比增长率

题目：按结算口径统计2025年每个月的结算净额，并计算相对上月的环比增长额与环比增长率（%），请用 LAG() 窗口函数实现，输出对应SQL语句。

参考 SQL：
```sql
WITH monthly AS (
  SELECT DATE_FORMAT(bt.transaction_date, '%Y-%m') AS ym,
         ROUND(SUM(bt.net_amount), 2) AS net_total
  FROM healthcare_analytics_competition.billing_transactions bt
  WHERE bt.transaction_date >= '2025-01-01' AND bt.transaction_date < '2026-01-01'
  GROUP BY ym
)
SELECT ym,
       net_total,
       LAG(net_total) OVER (ORDER BY ym) AS prev_month_total,
       ROUND(net_total - LAG(net_total) OVER (ORDER BY ym), 2) AS mom_diff,
       ROUND((net_total - LAG(net_total) OVER (ORDER BY ym))
             / LAG(net_total) OVER (ORDER BY ym) * 100, 2) AS mom_growth_pct
FROM monthly
ORDER BY ym;
```

### 227 2024与2025年度就诊人次和收入对比及增长率

题目：按就诊口径对比2024年与2025年的就诊人次与医疗收入，并计算收入的同比增长率（%），请输出对应SQL语句。

参考 SQL：
```sql
WITH yearly AS (
  SELECT YEAR(me.encounter_date) AS yr,
         COUNT(*) AS encounter_cnt,
         ROUND(SUM(me.total_cost), 2) AS revenue
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2024-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY yr
)
SELECT yr,
       encounter_cnt,
       revenue,
       LAG(revenue) OVER (ORDER BY yr) AS prev_year_revenue,
       ROUND((revenue - LAG(revenue) OVER (ORDER BY yr))
             / LAG(revenue) OVER (ORDER BY yr) * 100, 2) AS yoy_growth_pct
FROM yearly
ORDER BY yr;
```

### 228 2025年各季度就诊人次与2024年同期同比

题目：按季度统计2024、2025年就诊人次，输出2025年各季度人次、2024年同期人次与同比增长率（%），请输出对应SQL语句。

参考 SQL：
```sql
WITH quarterly AS (
  SELECT YEAR(me.encounter_date) AS yr,
         QUARTER(me.encounter_date) AS qtr,
         COUNT(*) AS encounter_cnt
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2024-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY yr, qtr
)
SELECT cur.yr,
       cur.qtr,
       cur.encounter_cnt,
       prev.encounter_cnt AS same_qtr_last_year_cnt,
       ROUND((cur.encounter_cnt - prev.encounter_cnt) / prev.encounter_cnt * 100, 2) AS yoy_growth_pct
FROM quarterly cur
JOIN quarterly prev
  ON prev.yr = cur.yr - 1 AND prev.qtr = cur.qtr
WHERE cur.yr = 2025
ORDER BY cur.qtr;
```

### 229 各年龄段就诊人数与平均费用（条件聚合分段）

题目：把2025年就诊患者按下述口径分段：<18 未成年、18-34 青年、35-49 中年、50-64 中老年、≥65 老年，一次查询输出各年龄段的就诊人次、去重患者数与平均单次就诊费用，请用 CASE WHEN 实现，输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE WHEN p.age < 18 THEN '1-未成年(<18)'
            WHEN p.age < 35 THEN '2-青年(18-34)'
            WHEN p.age < 50 THEN '3-中年(35-49)'
            WHEN p.age < 65 THEN '4-中老年(50-64)'
            ELSE '5-老年(65+)' END AS age_group,
       COUNT(*) AS encounter_cnt,
       COUNT(DISTINCT me.patient_id) AS patient_cnt,
       ROUND(AVG(me.total_cost), 2) AS avg_total_cost
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.patient_master_index p
  ON p.patient_id = me.patient_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  AND p.delete_flag = 'N'
GROUP BY age_group
ORDER BY age_group;
```

### 230 各科室五类就诊类型人次一表输出（条件聚合）

题目：用一次查询把每个科室的门诊、急诊、住院、体检、复诊五类就诊人次横向输出（CASE WHEN 条件聚合），只保留住院人次大于0的科室并按住院人次降序，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       SUM(CASE WHEN me.encounter_type = '门诊' THEN 1 ELSE 0 END) AS outpatient_cnt,
       SUM(CASE WHEN me.encounter_type = '急诊' THEN 1 ELSE 0 END) AS emergency_cnt,
       SUM(CASE WHEN me.encounter_type = '住院' THEN 1 ELSE 0 END) AS inpatient_cnt,
       SUM(CASE WHEN me.encounter_type = '体检' THEN 1 ELSE 0 END) AS physical_exam_cnt,
       SUM(CASE WHEN me.encounter_type = '复诊' THEN 1 ELSE 0 END) AS revisit_cnt,
       COUNT(*) AS total_encounter_cnt
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
GROUP BY dw.dept_ward_id, dw.name
HAVING SUM(CASE WHEN me.encounter_type = '住院' THEN 1 ELSE 0 END) > 0
ORDER BY inpatient_cnt DESC, dw.name;
```

### 231 各支付状态的笔数、净额与医保自付拆分及欠费率

题目：按结算表 payment_status（已支付/部分支付/未支付/医保待结算/已退款）统计2025年各状态的笔数、结算净额、医保支付合计、患者自付合计、未结清金额合计，并计算存在未结清金额（outstanding_amount>0）的笔数占比（%），请输出对应SQL语句。

参考 SQL：
```sql
SELECT bt.payment_status,
       COUNT(*) AS tx_cnt,
       ROUND(SUM(bt.net_amount), 2) AS net_total,
       ROUND(SUM(bt.insurance_paid), 2) AS insurance_paid_total,
       ROUND(SUM(bt.patient_paid), 2) AS patient_paid_total,
       ROUND(SUM(bt.outstanding_amount), 2) AS outstanding_total,
       ROUND(SUM(CASE WHEN bt.outstanding_amount > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS arrears_tx_ratio_pct
FROM healthcare_analytics_competition.billing_transactions bt
WHERE bt.transaction_date >= '2025-01-01' AND bt.transaction_date < '2026-01-01'
GROUP BY bt.payment_status
ORDER BY net_total DESC;
```

### 232 各科室接诊患者数（去重）与就诊人次对比

题目：统计2025年各科室的就诊人次与去重接诊患者数（COUNT(DISTINCT patient_id)），并计算人均就诊次数，用于区分「人次」与「人数」口径，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       COUNT(*) AS encounter_cnt,
       COUNT(DISTINCT me.patient_id) AS patient_cnt,
       ROUND(COUNT(*) / COUNT(DISTINCT me.patient_id), 2) AS encounter_per_patient
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY encounter_cnt DESC;
```

### 233 每位医生服务患者数（去重）与接诊人次 Top10

题目：统计2025年接诊人次最多的前10名医生，同时输出去重服务患者数，用于对比「接诊人次」与「服务人数」，请输出对应SQL语句。

参考 SQL：
```sql
SELECT ms.staff_id,
       ms.staff_name,
       ms.job_title,
       COUNT(*) AS encounter_cnt,
       COUNT(DISTINCT me.patient_id) AS patient_cnt
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.medical_staff ms
  ON ms.staff_id = me.doctor_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
GROUP BY ms.staff_id, ms.staff_name, ms.job_title
ORDER BY encounter_cnt DESC, ms.staff_id
LIMIT 10;
```

### 234 住院一般要住几天？住院时长分段统计

题目：（口语化问法→业务口径：按 DATEDIFF(discharge_date, encounter_date) 计算住院天数）把住院就诊分为1-3天、4-7天、8-14天、15天以上四档，输出各档人次数、平均住院天数与平均单次费用，请输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE WHEN t.los_days <= 3 THEN '1-短(1-3天)'
            WHEN t.los_days <= 7 THEN '2-中(4-7天)'
            WHEN t.los_days <= 14 THEN '3-较长(8-14天)'
            ELSE '4-长(15天以上)' END AS los_group,
       COUNT(*) AS inpatient_cnt,
       ROUND(AVG(t.los_days), 1) AS avg_los_days,
       ROUND(AVG(t.total_cost), 2) AS avg_total_cost,
       MAX(t.los_days) AS max_los_days
FROM (SELECT DATEDIFF(me.discharge_date, me.encounter_date) AS los_days,
             me.total_cost
      FROM healthcare_analytics_competition.medical_encounters me
      WHERE me.encounter_type = '住院'
        AND me.discharge_date IS NOT NULL) t
GROUP BY los_group
ORDER BY los_group;
```

### 235 单次就诊费用档位分布与占比

题目：统计2025年单次就诊费用（medical_encounters.total_cost）落在 5000元以下、5000-2万、2万-3.5万、3.5万以上四个档位的就诊人次与占比（%），请输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE WHEN me.total_cost < 5000 THEN '1-5000元以下'
            WHEN me.total_cost < 20000 THEN '2-5000-2万元'
            WHEN me.total_cost < 35000 THEN '3-2万-3.5万元'
            ELSE '4-3.5万元以上' END AS cost_band,
       COUNT(*) AS encounter_cnt,
       ROUND(COUNT(*) / (SELECT COUNT(*)
                         FROM healthcare_analytics_competition.medical_encounters
                         WHERE encounter_date >= '2025-01-01'
                           AND encounter_date < '2026-01-01') * 100, 2) AS ratio_pct,
       ROUND(AVG(me.total_cost), 2) AS avg_total_cost
FROM healthcare_analytics_competition.medical_encounters me
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
GROUP BY cost_band
ORDER BY cost_band;
```

### 236 在库药品批次效期分段统计（近效期预警）

题目：把状态为「在库」的药品批次按效期分为已过期（expiration_date < 当天）、90天内到期、180天内到期、半年以上四档，输出各档批次数、库存数量合计与库存金额合计，请输出对应SQL语句（金额取 total_cost）。

参考 SQL：
```sql
SELECT CASE WHEN pi.expiration_date < CURDATE() THEN '1-已过期'
            WHEN pi.expiration_date < DATE_ADD(CURDATE(), INTERVAL 90 DAY) THEN '2-90天内到期'
            WHEN pi.expiration_date < DATE_ADD(CURDATE(), INTERVAL 180 DAY) THEN '3-180天内到期'
            ELSE '4-半年以上' END AS expiry_band,
       COUNT(*) AS batch_cnt,
       ROUND(SUM(pi.current_quantity), 2) AS quantity_total,
       ROUND(SUM(pi.total_cost), 2) AS amount_total
FROM healthcare_analytics_competition.pharmacy_inventory pi
WHERE pi.inventory_status = '在库'
GROUP BY expiry_band
ORDER BY expiry_band;
```

### 237 最新月份与上月就诊人次及医疗收入环比

题目：本库就诊数据最新月份为2025年11月，请对比2025年10月与2025年11月的就诊人次与医疗收入（就诊口径）并计算环比增长额与环比增长率（%），时间过滤使用半开区间，请输出对应SQL语句。

参考 SQL：
```sql
WITH monthly AS (
  SELECT DATE_FORMAT(me.encounter_date, '%Y-%m') AS ym,
         COUNT(*) AS encounter_cnt,
         SUM(me.total_cost) AS revenue
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-10-01' AND me.encounter_date < '2025-12-01'
  GROUP BY ym
)
SELECT ym,
       encounter_cnt,
       ROUND(revenue, 2) AS revenue,
       ROUND(revenue - LAG(revenue) OVER (ORDER BY ym), 2) AS mom_diff,
       ROUND((revenue - LAG(revenue) OVER (ORDER BY ym))
             / LAG(revenue) OVER (ORDER BY ym) * 100, 2) AS mom_growth_pct
FROM monthly
ORDER BY ym;
```

### 238 近7天每日就诊量与收入（以数据最新就诊日为基准）

题目：统计最近7天的每日就诊人次与医疗收入。注意本库数据截止到2025-11-29，若用 CURDATE() 会查不到数据，因此以表内最大 encounter_date 为基准回溯6天，请输出对应SQL语句。

参考 SQL：
```sql
SELECT DATE(me.encounter_date) AS stat_date,
       COUNT(*) AS encounter_cnt,
       ROUND(SUM(me.total_cost), 2) AS revenue
FROM healthcare_analytics_competition.medical_encounters me
WHERE me.encounter_date >= DATE_SUB(DATE((SELECT MAX(encounter_date)
                                          FROM healthcare_analytics_competition.medical_encounters)),
                                    INTERVAL 6 DAY)
GROUP BY DATE(me.encounter_date)
ORDER BY stat_date;
```

### 239 按周统计2025年就诊人次与医疗收入

题目：按 ISO 周（DATE_FORMAT(encounter_date,'%x-W%v')）统计2025年各周的就诊人次与医疗收入，并输出该周的起始日期，请输出对应SQL语句。

参考 SQL：
```sql
SELECT DATE_FORMAT(me.encounter_date, '%x-W%v') AS iso_week,
       MIN(DATE(me.encounter_date)) AS week_start_date,
       COUNT(*) AS encounter_cnt,
       ROUND(SUM(me.total_cost), 2) AS revenue
FROM healthcare_analytics_competition.medical_encounters me
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
GROUP BY iso_week
ORDER BY iso_week;
```

### 240 各科室2025年四个季度医疗收入横向对比

题目：用条件聚合把2025年每个科室的四个季度医疗收入（就诊口径 total_cost）横向输出，并给出全年合计，排除病区并按全年收入降序，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       ROUND(SUM(CASE WHEN QUARTER(me.encounter_date) = 1 THEN me.total_cost ELSE 0 END), 2) AS q1_revenue,
       ROUND(SUM(CASE WHEN QUARTER(me.encounter_date) = 2 THEN me.total_cost ELSE 0 END), 2) AS q2_revenue,
       ROUND(SUM(CASE WHEN QUARTER(me.encounter_date) = 3 THEN me.total_cost ELSE 0 END), 2) AS q3_revenue,
       ROUND(SUM(CASE WHEN QUARTER(me.encounter_date) = 4 THEN me.total_cost ELSE 0 END), 2) AS q4_revenue,
       ROUND(SUM(me.total_cost), 2) AS year_revenue
FROM healthcare_analytics_competition.medical_encounters me
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  AND dw.type <> '病区'
GROUP BY dw.dept_ward_id, dw.name
ORDER BY year_revenue DESC;
```

### 241 病人一般什么时候来？按小时统计就诊高峰

题目：（口语化问法→业务口径：按 HOUR(encounter_date) 统计全天24小时的就诊人次分布）统计2025年10-11月各小时段的就诊人次，按小时升序输出，用于识别就诊高峰时段，请输出对应SQL语句。

参考 SQL：
```sql
SELECT HOUR(me.encounter_date) AS hour_of_day,
       COUNT(*) AS encounter_cnt
FROM healthcare_analytics_competition.medical_encounters me
WHERE me.encounter_date >= '2025-10-01' AND me.encounter_date < '2025-12-01'
GROUP BY hour_of_day
ORDER BY hour_of_day;
```

### 242 从未就诊过的患者有多少（LEFT JOIN 空值排查）

题目：统计在册（delete_flag='N'）但从未产生任何就诊记录的患者数量，并按患者等级分组输出，请用 LEFT JOIN ... IS NULL 实现，输出对应SQL语句。

参考 SQL：
```sql
SELECT p.patient_level,
       COUNT(*) AS never_visited_cnt
FROM healthcare_analytics_competition.patient_master_index p
LEFT JOIN healthcare_analytics_competition.medical_encounters me
  ON me.patient_id = p.patient_id
WHERE p.delete_flag = 'N'
  AND me.encounter_id IS NULL
GROUP BY p.patient_level
ORDER BY never_visited_cnt DESC;
```

### 243 从没开过医嘱的就诊记录（LEFT JOIN 空值排查）

题目：找出没有任何医嘱记录的就诊，按就诊类型统计这类就诊的人次，请用 LEFT JOIN medical_orders ... IS NULL 实现，输出对应SQL语句。

参考 SQL：
```sql
SELECT me.encounter_type,
       COUNT(*) AS no_order_encounter_cnt
FROM healthcare_analytics_competition.medical_encounters me
LEFT JOIN healthcare_analytics_competition.medical_orders mo
  ON mo.encounter_id = me.encounter_id
WHERE mo.order_id IS NULL
GROUP BY me.encounter_type
ORDER BY no_order_encounter_cnt DESC;
```

### 244 单次费用超过本科室平均1.5倍的高额就诊（异常值排查）

题目：找出单次就诊费用（total_cost）高于本科室平均单次费用1.5倍的高额就诊记录，输出就诊ID、患者ID、科室、费用、本科室平均费用与倍数，取倍数最高的20条，请输出对应SQL语句。

参考 SQL：
```sql
SELECT me.encounter_id,
       me.patient_id,
       me.encounter_type,
       dw.name AS dept_name,
       ROUND(me.total_cost, 2) AS total_cost,
       ROUND(d.avg_dept_cost, 2) AS dept_avg_cost,
       ROUND(me.total_cost / d.avg_dept_cost, 2) AS times_of_dept_avg
FROM healthcare_analytics_competition.medical_encounters me
JOIN (SELECT department_id,
             AVG(total_cost) AS avg_dept_cost
      FROM healthcare_analytics_competition.medical_encounters
      GROUP BY department_id) d
  ON d.department_id = me.department_id
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = me.department_id
WHERE me.total_cost > d.avg_dept_cost * 1.5
ORDER BY times_of_dept_avg DESC
LIMIT 20;
```

### 245 已经过期但仍挂在「在库」状态的药品批次

题目：找出有效期已过（expiration_date < 当天）但 inventory_status 仍为「在库」的药品批次，输出药品ID、批次号、剩余数量、有效期与已过期天数，按过期天数降序取20条，请输出对应SQL语句。

参考 SQL：
```sql
SELECT pi.drug_id,
       pi.batch_number,
       ROUND(pi.current_quantity, 2) AS current_quantity,
       pi.expiration_date,
       DATEDIFF(CURDATE(), pi.expiration_date) AS overdue_days
FROM healthcare_analytics_competition.pharmacy_inventory pi
WHERE pi.inventory_status = '在库'
  AND pi.expiration_date < CURDATE()
ORDER BY overdue_days DESC
LIMIT 20;
```

### 246 谁还欠着钱？欠费金额最高的前10位患者

题目：（口语化问法→业务口径：billing_transactions.outstanding_amount 为未结清金额）统计未结清金额合计最高的前10位患者，输出患者ID、姓名、患者等级、结算笔数与欠费合计，仅统计未删除患者，请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.patient_id,
       p.patient_name,
       p.patient_level,
       COUNT(*) AS tx_cnt,
       ROUND(SUM(bt.outstanding_amount), 2) AS outstanding_total
FROM healthcare_analytics_competition.billing_transactions bt
JOIN healthcare_analytics_competition.patient_master_index p
  ON p.patient_id = bt.patient_id
WHERE bt.outstanding_amount > 0
  AND p.delete_flag = 'N'
GROUP BY p.patient_id, p.patient_name, p.patient_level
ORDER BY outstanding_total DESC
LIMIT 10;
```

### 247 平均就诊费用高于全院平均的科室（CTE 子查询）

题目：用 CTE 先算出各科室2025年的平均单次就诊费用与全院平均单次费用，再筛选出平均费用高于全院平均的科室，输出科室名、就诊人次、科室平均费用与全院平均费用，请输出对应SQL语句。

参考 SQL：
```sql
WITH dept_avg AS (
  SELECT me.department_id,
         COUNT(*) AS encounter_cnt,
         AVG(me.total_cost) AS dept_avg_cost
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY me.department_id
), overall AS (
  SELECT AVG(me.total_cost) AS overall_avg_cost
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
)
SELECT dw.name AS dept_name,
       da.encounter_cnt,
       ROUND(da.dept_avg_cost, 2) AS dept_avg_cost,
       ROUND(o.overall_avg_cost, 2) AS overall_avg_cost
FROM dept_avg da
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = da.department_id
CROSS JOIN overall o
WHERE da.dept_avg_cost > o.overall_avg_cost
ORDER BY dept_avg_cost DESC;
```

### 248 2025年就诊总费用高于患者平均水平的 VIP/SVIP 高价值患者（CTE 子查询）

题目：用 CTE 先按患者汇总2025年就诊总费用与就诊次数，再筛出总费用高于全体患者平均总费用的 VIP/SVIP 患者，输出患者ID、姓名、等级、就诊次数与累计费用，按累计费用降序取20条，请输出对应SQL语句。

参考 SQL：
```sql
WITH patient_total AS (
  SELECT me.patient_id,
         COUNT(*) AS encounter_cnt,
         SUM(me.total_cost) AS patient_total_cost
  FROM healthcare_analytics_competition.medical_encounters me
  WHERE me.encounter_date >= '2025-01-01' AND me.encounter_date < '2026-01-01'
  GROUP BY me.patient_id
), avg_total AS (
  SELECT AVG(pt.patient_total_cost) AS avg_patient_cost
  FROM patient_total pt
)
SELECT p.patient_id,
       p.patient_name,
       p.patient_level,
       pt.encounter_cnt,
       ROUND(pt.patient_total_cost, 2) AS patient_total_cost,
       ROUND(a.avg_patient_cost, 2) AS avg_patient_cost
FROM patient_total pt
JOIN healthcare_analytics_competition.patient_master_index p
  ON p.patient_id = pt.patient_id
CROSS JOIN avg_total a
WHERE pt.patient_total_cost > a.avg_patient_cost
  AND p.patient_level IN ('VIP', 'SVIP')
ORDER BY patient_total_cost DESC
LIMIT 20;
```

### 249 各科室结算收入占比与院内排名（CTE + 窗口函数）

题目：用 CTE 先汇总2025年各科室结算净额，再用窗口函数一次性输出科室名、结算净额、院内收入排名与占全院比例（%），排除病区并按排名输出，请输出对应SQL语句。

参考 SQL：
```sql
WITH dept_revenue AS (
  SELECT bt.department_id,
         SUM(bt.net_amount) AS net_total
  FROM healthcare_analytics_competition.billing_transactions bt
  WHERE bt.transaction_date >= '2025-01-01' AND bt.transaction_date < '2026-01-01'
  GROUP BY bt.department_id
)
SELECT dw.name AS dept_name,
       ROUND(dr.net_total, 2) AS net_total,
       RANK() OVER (ORDER BY dr.net_total DESC) AS revenue_rank,
       ROUND(dr.net_total / SUM(dr.net_total) OVER () * 100, 2) AS ratio_pct
FROM dept_revenue dr
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = dr.department_id
WHERE dw.type <> '病区'
ORDER BY revenue_rank;
```

### 250 设备使用时长与费用 Top10（仅正常完成的使用记录）

题目：统计2025年使用费用最高的前10台设备，输出设备ID、使用次数、累计使用小时数（duration_minutes/60）、平均单次时长与累计费用，仅统计 usage_status='正常完成' 的记录，请输出对应SQL语句。

参考 SQL：
```sql
SELECT ue.equipment_id,
       COUNT(*) AS usage_cnt,
       ROUND(SUM(ue.duration_minutes) / 60, 1) AS usage_hours,
       ROUND(AVG(ue.duration_minutes), 1) AS avg_minutes,
       ROUND(SUM(ue.total_cost), 2) AS usage_cost
FROM healthcare_analytics_competition.medical_equipment_usage ue
WHERE ue.usage_status = '正常完成'
  AND ue.start_time >= '2025-01-01' AND ue.start_time < '2026-01-01'
GROUP BY ue.equipment_id
ORDER BY usage_cost DESC
LIMIT 10;
```

### 251 各科室设备异常终止率排名（HAVING 过滤小样本）

题目：统计各科室设备使用记录中「异常终止」占比（%），输出科室名、使用次数、异常终止次数与异常率，仅保留使用次数不少于5次的科室，按异常率降序，请用 HAVING 过滤，输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS dept_name,
       COUNT(*) AS usage_cnt,
       SUM(CASE WHEN ue.usage_status = '异常终止' THEN 1 ELSE 0 END) AS abnormal_cnt,
       ROUND(SUM(CASE WHEN ue.usage_status = '异常终止' THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS abnormal_rate_pct
FROM healthcare_analytics_competition.medical_equipment_usage ue
JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = ue.department_id
GROUP BY ue.department_id, dw.name
HAVING COUNT(*) >= 5
ORDER BY abnormal_rate_pct DESC;
```

### 252 谁的绩效最好？在职医护绩效前10名

题目：（口语化问法→业务口径：medical_staff.is_active=1 且按 performance_score 降序）统计在职医护中绩效评分最高的前10名，输出工号、姓名、职称、所属科室、绩效评分与入职日期，请输出对应SQL语句。

参考 SQL：
```sql
SELECT ms.employee_no,
       ms.staff_name,
       ms.job_title,
       dw.name AS dept_name,
       ROUND(ms.performance_score, 2) AS performance_score,
       ms.hire_date
FROM healthcare_analytics_competition.medical_staff ms
LEFT JOIN healthcare_analytics_competition.departments_wards dw
  ON dw.dept_ward_id = ms.department_id
WHERE ms.is_active = 1
ORDER BY ms.performance_score DESC, ms.staff_id
LIMIT 10;
```

### 253 各科室与病区床位使用率排名

题目：统计有病床设置的科室与病区的床位总数、可用床位数与床位使用率（%）=（总床位-可用床位）/总床位，仅保留 total_beds > 0 的单元，按使用率降序，请输出对应SQL语句。

参考 SQL：
```sql
SELECT dw.name AS unit_name,
       dw.type,
       dw.total_beds,
       dw.available_beds,
       ROUND((dw.total_beds - dw.available_beds) / dw.total_beds * 100, 2) AS bed_usage_rate_pct
FROM healthcare_analytics_competition.departments_wards dw
WHERE dw.total_beds > 0
ORDER BY bed_usage_rate_pct DESC;
```

### 254 哪个药快没了？在库批次库存量最少的10个批次

题目：（口语化问法→业务口径：pharmacy_inventory 无药名列，只能按 drug_id + 批次看库存；本库在库批次的 current_quantity 均约为 reorder_level 的5倍，没有低于再订货线的批次，故按库存量升序取最少的批次作为「快没了」预警）列出未过期、状态为「在库」且库存数量最少的10个药品批次，输出药品ID、批次号、库存数量、再订货水平、安全库存与有效期，请输出对应SQL语句。

参考 SQL：
```sql
SELECT pi.drug_id,
       pi.batch_number,
       ROUND(pi.current_quantity, 2) AS current_quantity,
       ROUND(pi.reorder_level, 2) AS reorder_level,
       ROUND(pi.safety_stock, 2) AS safety_stock,
       pi.expiration_date
FROM healthcare_analytics_competition.pharmacy_inventory pi
WHERE pi.inventory_status = '在库'
  AND pi.expiration_date >= CURDATE()
ORDER BY pi.current_quantity ASC, pi.drug_id
LIMIT 10;
```
