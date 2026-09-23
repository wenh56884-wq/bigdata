# 通信运营商综合库（telecom_operations_db）自然语言查询 → SQL 问答

> 使用对象：把中文业务问题转成标准 SQL（MySQL 兼容），字段一律采用英文表名 / 字段名，避免自造表名。

覆盖用户 customers、套餐产品 products、订购 subscriptions、通信详单 cdr_detail、月度账单 monthly_bills、营销活动 marketing_campaigns、客服记录 service_records、网络资源 network_resources 共 8 张表。

字段与取值约定：
- 用户状态 customer_status：正常/停机/欠费/预销户/已销户；gender：男/女/未知。
- 账单 payment_status：未出账/待支付/部分支付/已支付/逾期/坏账；欠费以 unpaid_amount>0 为准。
- 详单 call_type 区分语音/短信/流量，语音通话用 本地语音、长途语音。
- 产品目录带版本，取当前有效产品建议加 is_current=1。

## 库表字段速查

- customers（用户主信息表）：
    -  customer_id 用户ID
    -  id_card_no 身份证号
    -  customer_name 姓名
    -  customer_type 用户类型
    -  gender 性别
    -  birth_date 出生日期
    -  registration_date 入网时间
    -  cancel_date 销户时间
    -  customer_status 用户状态
    -  credit_level 信用等级
    -  vip_level VIP等级
    -  referral_customer_id 推荐人ID
    -  total_spend 累计消费
    -  avg_monthly_spend 月均消费
    -  last_recharge_date 最近充值时间
    -  loyalty_months 在网月数
    -  preferred_channel 偏好渠道
    -  address_json 地址信息
    -  tags_json 用户标签
    -  create_time 创建时间
    -  update_time 更新时间
    -  partition_key 分区键

- products（产品套餐目录表）：
    -  product_id 产品编码
    -  product_name 产品名称
    -  product_type 产品类型
    -  product_subtype 产品子类
    -  version 版本号
    -  is_current 是否当前版本
    -  effective_date 生效日期
    -  expire_date 失效日期
    -  base_fee 基础费用
    -  data_allowance 包含流量
    -  voice_allowance 包含语音
    -  sms_allowance 包含短信
    -  over_data_fee 超额流量单价
    -  over_voice_fee 超额语音单价
    -  roaming_zone 漫游区域
    -  product_attributes 产品属性
    -  max_subscribers 最大用户数
    -  partner_id 合作方ID
    -  commission_rate 佣金比例
    -  create_by 创建人
    -  create_time 创建时间
    -  update_time 更新时间
    -  audit_status 审核状态

- subscriptions（用户订购关系表）：
    -  subscription_id 订购关系ID
    -  customer_id 用户ID
    -  product_id 产品ID
    -  product_version 产品版本号
    -  msisdn 手机号码
    -  imsi 国际移动用户识别码
    -  iccid SIM卡号
    -  subscription_type 订购类型
    -  order_id 订单号
    -  start_date 生效日期
    -  end_date 到期日期
    -  actual_end_date 实际终止日期
    -  billing_cycle 出账日
    -  auto_renew 自动续约
    -  payment_method 付费方式
    -  monthly_fee 月固定费
    -  discount_rate 折扣率
    -  actual_monthly_fee 实际月费
    -  channel_code 办理渠道编码
    -  sales_agent_id 销售代理ID
    -  promotion_codes 促销码
    -  contract_duration 合约期
    -  termination_reason 终止原因
    -  create_time 创建时间
    -  update_time 更新时间
    -  data_source 数据来源

- cdr_detail（通信详单表）：
    -  cdr_id 详单ID
    -  msisdn 主叫号码
    -  called_number 被叫号码
    -  imsi 国际移动用户识别码
    -  imei 设备识别码
    -  call_type 通信类型
    -  call_start_time 开始时间
    -  call_end_time 结束时间
    -  duration_seconds 通话时长
    -  data_volume_mb 数据流量
    -  sms_count 短信条数
    -  home_location 归属地
    -  visit_location 漫游地
    -  lac 位置区码
    -  ci 小区标识
    -  cell_location 基站位置
    -  roaming_flag 是否漫游
    -  roaming_partner 漫游合作商
    -  call_result 呼叫结果
    -  chargeable_flag 是否计费
    -  basic_fee 基本费
    -  long_distance_fee 长途费
    -  roaming_fee 漫游费
    -  discount_fee 优惠减免
    -  total_fee 总费用
    -  billing_cycle 账期
    -  cdr_source 详单来源
    -  error_code 错误码
    -  raw_data_hash 数据哈希
    -  partition_hour 分区小时

- monthly_bills（月度账单表）：
    -  bill_id 账单ID
    -  customer_id 用户ID
    -  msisdn 手机号码
    -  billing_month 账期月份
    -  bill_generate_date 账单生成日期
    -  bill_due_date 缴费截止日
    -  base_plan_fee 基础套餐费
    -  voice_usage_fee 语音使用费
    -  data_usage_fee 流量使用费
    -  sms_usage_fee 短信使用费
    -  value_added_fee 增值业务费
    -  roaming_fee 漫游费
    -  one_time_fee 一次性费用
    -  subtotal 小计
    -  discount_amount 优惠金额
    -  tax_amount 税费
    -  total_amount 账单总额
    -  paid_amount 已缴金额
    -  unpaid_amount 未缴金额
    -  payment_status 支付状态
    -  late_fee 滞纳金
    -  last_payment_date 最近缴费日期
    -  invoice_id 发票号码
    -  bill_detail_json 账单明细
    -  audit_flag 是否已稽核
    -  version 账单版本
    -  create_time 创建时间
    -  update_time 更新时间

- marketing_campaigns（营销活动表）：
    -  campaign_id 活动ID
    -  campaign_name 活动名称
    -  campaign_type 活动类型
    -  target_segment 目标客群
    -  target_condition_json 目标条件
    -  channel 推广渠道
    -  budget_amount 预算金额
    -  actual_cost 实际成本
    -  start_date 开始日期
    -  end_date 结束日期
    -  extend_date 延期后结束日期
    -  status 活动状态
    -  kpi_target_json KPI指标目标
    -  actual_kpi_json 实际KPI指标
    -  participants_count 参与人数
    -  conversion_count 转化人数
    -  conversion_rate 转化率
    -  roi 投资回报率
    -  manager_id 负责人ID
    -  department_id 负责部门
    -  approval_flow 审批流程
    -  creatives_info 创意素材
    -  audit_trail 审计追踪
    -  create_time 创建时间
    -  update_time 更新时间
    -  data_version 数据版本

- service_records（客户服务记录表）：
    -  record_id 记录ID
    -  customer_id 用户ID
    -  msisdn 手机号码
    -  service_channel 服务渠道
    -  service_type 服务类型
    -  contact_time 接触时间
    -  service_start_time 服务开始时间
    -  service_end_time 服务结束时间
    -  duration_seconds 服务时长
    -  agent_id 客服工号
    -  agent_name 客服姓名
    -  skill_group 技能组
    -  first_level_reason 一级原因分类
    -  second_level_reason 二级原因分类
    -  detailed_reason 详细原因描述
    -  sentiment_score 情感分析分数
    -  urgency_level 紧急程度
    -  satisfaction_score 满意度评分
    -  is_complaint 是否投诉
    -  complaint_level 投诉等级
    -  follow_up_required 需跟进
    -  follow_up_deadline 跟进截止日
    -  resolution_status 解决状态
    -  resolution_code 解决编码
    -  resolution_description 解决描述
    -  transfer_count 转接次数
    -  hold_duration_seconds 等待时长
    -  related_order_id 关联订单号
    -  related_bill_id 关联账单号
    -  tags_json 标签信息
    -  create_time 创建时间

- network_resources（网络资源表）：
    -  resource_id 资源ID
    -  resource_type 资源类型
    -  resource_name 资源名称
    -  parent_resource_id 父资源ID
    -  administrative_region 行政区域
    -  longitude 经度
    -  latitude 纬度
    -  location_geo 地理坐标
    -  address 详细地址
    -  vendor 设备厂商
    -  equipment_model 设备型号
    -  installation_date 安装日期
    -  maintenance_status 维护状态
    -  capacity_voice 语音容量
    -  capacity_data_mbps 数据容量
    -  current_utilization 当前利用率
    -  avg_signal_strength 平均信号强度
    -  avg_data_rate 平均数据速率
    -  fault_count_30d 30天故障次数
    -  mttr_hours 平均修复时间
    -  power_consumption 能耗指标
    -  maintenance_cost 维护成本
    -  last_maintenance_date 上次维护日期
    -  next_maintenance_date 下次计划维护日期
    -  performance_metrics 性能指标
    -  create_time 创建时间
    -  update_time 更新时间

## 问答样例（题目 → 参考 SQL）

### 1 找出所有在北京的用户

题目：找出所有在北京的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE address_json LIKE '%北京%' OR address_json LIKE '%北京市%';
```

### 2 列出所有欠费的用户

题目：列出所有欠费的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE customer_status = '欠费';
```

### 3 显示所有男性用户

题目：显示所有男性用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE gender = '男';
```

### 4 找出所有5G套餐

题目：找出所有5G套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = '5G专享' OR product_name LIKE '%5G%';
```

### 5 显示当前有效的产品

题目：显示当前有效的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_current = 1 AND (expire_date IS NULL OR expire_date >= CURDATE());
```

### 6 找出价格高于100元的产品

题目：找出价格高于100元的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE base_fee > 100;
```

### 7 列出所有语音通话记录

题目：列出所有语音通话记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音');
```

### 8 找出通话时长超过10分钟的记录

题目：找出通话时长超过10分钟的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE duration_seconds > 600;
```

### 9 显示所有成功的通话记录

题目：显示所有成功的通话记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_result = '成功';
```

### 10 找出总金额超过500的账单

题目：找出总金额超过500的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE total_amount > 500;
```

### 11 列出所有未支付的账单

题目：列出所有未支付的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE payment_status IN ('待支付', '部分支付', '逾期') OR unpaid_amount > 0;
```

### 12 显示2024年的所有账单

题目：显示2024年的所有账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE YEAR(billing_month) = 2024;
```

### 13 找出所有在营业厅办理的订购

题目：找出所有在营业厅办理的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE channel_code = '营业厅';
```

### 14 列出所有预付费用户

题目：列出所有预付费用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE payment_method = '预付费';
```

### 15 显示所有2024年新装的订购

题目：显示所有2024年新装的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE subscription_type = '新装' AND YEAR(start_date) = 2024;
```

### 16 找出所有投诉记录

题目：找出所有投诉记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE is_complaint = 1 OR service_type = '投诉';
```

### 17 列出热线电话的服务记录

题目：列出热线电话的服务记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE service_channel = '热线电话';
```

### 18 显示满意度为5分的记录

题目：显示满意度为5分的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE satisfaction_score = 5;
```

### 19 找出所有网络营销活动

题目：找出所有网络营销活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE channel IN ('APP推送', '社交媒体');
```

### 20 列出已结束的营销活动

题目：列出已结束的营销活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE status = '已结束';
```

### 21 显示预算超过10万的活动

题目：显示预算超过10万的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE budget_amount > 100000;
```

### 22 找出所有基站资源

题目：找出所有基站资源，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE resource_type = '基站';
```

### 23 列出正常运行的设备

题目：列出正常运行的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE maintenance_status = '正常';
```

### 24 显示华为的设备

题目：显示华为的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE vendor LIKE '%华为%';
```

### 25 找出钻石VIP用户

题目：找出钻石VIP用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE vip_level = '钻石';
```

### 26 列出企业用户

题目：列出企业用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE customer_type = '企业';
```

### 27 显示信用等级为10的用户

题目：显示信用等级为10的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE credit_level = 10;
```

### 28 找出包含流量的产品

题目：找出包含流量的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE data_allowance > 0;
```

### 29 列出国际漫游产品

题目：列出国际漫游产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = '国际漫游';
```

### 30 显示审核通过的产品

题目：显示审核通过的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE audit_status = '已生效';
```

### 31 找出流量使用记录

题目：找出流量使用记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_type = '流量';
```

### 32 列出国际漫游通话

题目：列出国际漫游通话，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_type = '国际漫游' OR (roaming_flag = 1 AND call_type IN ('本地语音', '长途语音', '视频通话'));
```

### 33 显示有错误的话单

题目：显示有错误的话单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE error_code IS NOT NULL AND error_code <> '';
```

### 34 找出有滞纳金的账单

题目：找出有滞纳金的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE late_fee > 0;
```

### 35 列出部分支付的账单

题目：列出部分支付的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE payment_status = '部分支付';
```

### 36 显示已审计的账单

题目：显示已审计的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE audit_flag = 1;
```

### 37 找出自动续约的订购

题目：找出自动续约的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE auto_renew = 1;
```

### 38 列出合约期24个月的订购

题目：列出合约期24个月的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE contract_duration = 24;
```

### 39 显示来自CRM系统的数据

题目：显示来自CRM系统的数据，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE data_source = 'CRM';
```

### 40 找出情感分数为负的服务记录

题目：找出情感分数为负的服务记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE sentiment_score < 0;
```

### 41 列出紧急的服务请求

题目：列出紧急的服务请求，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE urgency_level = '紧急';
```

### 42 显示需要跟进的记录

题目：显示需要跟进的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE follow_up_required = 1;
```

### 43 找出目标为高价值用户的活动

题目：找出目标为高价值用户的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE target_segment = '高价值用户';
```

### 44 列出转化率超过10%的活动

题目：列出转化率超过10%的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE conversion_rate > 0.1;
```

### 45 显示审批中的活动

题目：显示审批中的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE status = '审批中';
```

### 46 找出容量超过5000的设备

题目：找出容量超过5000的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE capacity_voice > 5000 OR capacity_data_mbps > 5000;
```

### 47 列出利用率超过80%的设备

题目：列出利用率超过80%的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE current_utilization > 80;
```

### 48 显示中兴的设备

题目：显示中兴的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE vendor LIKE '%中兴%';
```

### 49 找出注册超过3年的用户

题目：找出注册超过3年的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE registration_date < DATE_SUB(CURDATE(), INTERVAL 3 YEAR);
```

### 50 列出月均消费超过200的用户

题目：列出月均消费超过200的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE avg_monthly_spend > 200;
```

### 51 显示最近90天充值的用户

题目：显示最近90天充值的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE last_recharge_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY);
```

### 52 找出已下架的产品

题目：找出已下架的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE audit_status = '已下架';
```

### 53 列出包含500分钟语音的产品

题目：列出包含500分钟语音的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE voice_allowance = 500;
```

### 54 显示漫游区域为全球的产品

题目：显示漫游区域为全球的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE roaming_zone = '全球';
```

### 55 显示被叫忙的通话

题目：显示被叫忙的通话，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_result = '被叫忙';
```

### 56 找出本月账单

题目：找出本月账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE DATE_FORMAT(billing_month, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m');
```

### 57 列出欠费超过100的账单

题目：列出欠费超过100的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE unpaid_amount > 100;
```

### 58 显示有增值业务的账单

题目：显示有增值业务的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills WHERE value_added_fee > 0;
```

### 59 找出已结束的订购

题目：找出已结束的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE actual_end_date IS NOT NULL OR (end_date < CURDATE() AND actual_end_date IS NULL);
```

### 60 列出月底出账的用户

题目：列出月底出账的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE billing_cycle >= 28;
```

### 61 显示有促销码的订购

题目：显示有促销码的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions WHERE promotion_codes IS NOT NULL AND JSON_LENGTH(promotion_codes) > 0;
```

### 62 找出已解决的服务记录

题目：找出已解决的服务记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE resolution_status = '已解决';
```

### 63 显示转接过的服务

题目：显示转接过的服务，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records WHERE transfer_count > 0;
```

### 64 找出ROI大于2的活动

题目：找出ROI大于2的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE roi > 2;
```

### 65 列出参与人数超过5万的活动

题目：列出参与人数超过5万的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE participants_count > 50000;
```

### 66 显示节假日营销活动

题目：显示节假日营销活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE campaign_type = '节假日营销';
```

### 67 找出故障的设备

题目：找出故障的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE maintenance_status = '故障';
```

### 68 列出最近30天有故障的设备

题目：列出最近30天有故障的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE fault_count_30d > 0;
```

### 69 显示安装超过2年的设备

题目：显示安装超过2年的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE installation_date < DATE_SUB(CURDATE(), INTERVAL 2 YEAR);
```

### 70 找出微信办理的用户

题目：找出微信办理的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE preferred_channel = '线上';
```

### 71 列出推荐关系链

题目：列出推荐关系链，请输出对应SQL语句

参考 SQL：
```sql
WITH RECURSIVE chain AS (SELECT customer_id, customer_name, referral_customer_id, 0 AS lvl FROM customers WHERE referral_customer_id IS NULL UNION ALL SELECT c.customer_id, c.customer_name, c.referral_customer_id, chain.lvl + 1 FROM customers c JOIN chain ON c.referral_customer_id = chain.customer_id) SELECT * FROM chain;
```

### 72 显示信用等级前10的用户

题目：显示信用等级前10的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers ORDER BY credit_level DESC LIMIT 10;
```

### 73 找出流量单价低于0.03的产品

题目：找出流量单价低于0.03的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE over_data_fee < 0.03;
```

### 74 列出有佣金的产品

题目：列出有佣金的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE commission_rate > 0;
```

### 75 找出凌晨的通话记录

题目：找出凌晨的通话记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE HOUR(call_start_time) BETWEEN 0 AND 5;
```

### 76 列出周末的流量使用

题目：列出周末的流量使用，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE call_type = '流量' AND DAYOFWEEK(call_start_time) IN (1, 7);
```

### 77 找出累计消费前20的用户

题目：找出累计消费前20的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers ORDER BY total_spend DESC LIMIT 20;
```

### 78 列出各VIP等级用户数

题目：列出各VIP等级用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT vip_level, COUNT(*) AS user_cnt FROM customers GROUP BY vip_level;
```

### 79 显示用户来源渠道分布

题目：显示用户来源渠道分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT preferred_channel, COUNT(*) AS user_cnt FROM customers GROUP BY preferred_channel;
```

### 80 统计各类产品数量

题目：统计各类产品数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, COUNT(*) AS product_cnt FROM products GROUP BY product_type;
```

### 81 列出各价格区间产品数

题目：列出各价格区间产品数，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN base_fee < 30 THEN '30元以下' WHEN base_fee BETWEEN 30 AND 100 THEN '30-100元' WHEN base_fee BETWEEN 100 AND 300 THEN '100-300元' ELSE '300元以上' END AS price_range, COUNT(*) AS product_cnt FROM products GROUP BY price_range;
```

### 82 显示各审核状态产品数

题目：显示各审核状态产品数，请输出对应SQL语句

参考 SQL：
```sql
SELECT audit_status, COUNT(*) AS product_cnt FROM products GROUP BY audit_status;
```

### 83 统计各类通话数量

题目：统计各类通话数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT call_type, COUNT(*) AS call_cnt FROM cdr_detail GROUP BY call_type;
```

### 84 列出各通话结果数量

题目：列出各通话结果数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT call_result, COUNT(*) AS call_cnt FROM cdr_detail GROUP BY call_result;
```

### 85 显示各时段通话量

题目：显示各时段通话量，请输出对应SQL语句

参考 SQL：
```sql
SELECT HOUR(call_start_time) AS hour, COUNT(*) AS call_cnt FROM cdr_detail GROUP BY HOUR(call_start_time) ORDER BY hour;
```

### 86 统计各支付状态账单数

题目：统计各支付状态账单数，请输出对应SQL语句

参考 SQL：
```sql
SELECT payment_status, COUNT(*) AS bill_cnt FROM monthly_bills GROUP BY payment_status;
```

### 87 列出各月账单数量

题目：列出各月账单数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(billing_month, '%Y-%m') AS bill_month, COUNT(*) AS bill_cnt FROM monthly_bills GROUP BY DATE_FORMAT(billing_month, '%Y-%m') ORDER BY bill_month;
```

### 88 显示平均账单金额

题目：显示平均账单金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(total_amount) AS avg_amount FROM monthly_bills;
```

### 89 统计各类订购数量

题目：统计各类订购数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT subscription_type, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY subscription_type;
```

### 90 列出各渠道订购数

题目：列出各渠道订购数，请输出对应SQL语句

参考 SQL：
```sql
SELECT channel_code, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY channel_code;
```

### 91 显示平均合约期

题目：显示平均合约期，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(contract_duration) AS avg_contract_duration FROM subscriptions;
```

### 92 统计各类服务数量

题目：统计各类服务数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT service_type, COUNT(*) AS svc_cnt FROM service_records GROUP BY service_type;
```

### 93 列出各渠道服务数

题目：列出各渠道服务数，请输出对应SQL语句

参考 SQL：
```sql
SELECT service_channel, COUNT(*) AS svc_cnt FROM service_records GROUP BY service_channel;
```

### 94 显示平均满意度

题目：显示平均满意度，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(satisfaction_score) AS avg_satisfaction FROM service_records WHERE satisfaction_score IS NOT NULL;
```

### 95 统计各类活动数量

题目：统计各类活动数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT campaign_type, COUNT(*) AS camp_cnt FROM marketing_campaigns GROUP BY campaign_type;
```

### 96 列出各渠道活动数

题目：列出各渠道活动数，请输出对应SQL语句

参考 SQL：
```sql
SELECT channel, COUNT(*) AS camp_cnt FROM marketing_campaigns GROUP BY channel;
```

### 97 显示平均参与人数

题目：显示平均参与人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(participants_count) AS avg_participants FROM marketing_campaigns;
```

### 98 统计各类设备数量

题目：统计各类设备数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT resource_type, COUNT(*) AS res_cnt FROM network_resources GROUP BY resource_type;
```

### 99 列出各厂商设备数

题目：列出各厂商设备数，请输出对应SQL语句

参考 SQL：
```sql
SELECT vendor, COUNT(*) AS res_cnt FROM network_resources GROUP BY vendor;
```

### 100 显示平均利用率

题目：显示平均利用率，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(current_utilization) AS avg_utilization FROM network_resources;
```

### 101 找出消费最高的用户

题目：找出消费最高的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers ORDER BY total_spend DESC LIMIT 1;
```

### 102 列出最贵的套餐

题目：列出最贵的套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_current = 1 ORDER BY base_fee DESC LIMIT 1;
```

### 103 显示最长的通话

题目：显示最长的通话，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail ORDER BY duration_seconds DESC LIMIT 1;
```

### 104 找出最大的账单

题目：找出最大的账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM monthly_bills ORDER BY total_amount DESC LIMIT 1;
```

### 105 列出最新的订购

题目：列出最新的订购，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM subscriptions ORDER BY create_time DESC LIMIT 1;
```

### 106 显示最新的服务记录

题目：显示最新的服务记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM service_records ORDER BY contact_time DESC LIMIT 1;
```

### 107 找出最新的活动

题目：找出最新的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns ORDER BY start_date DESC LIMIT 1;
```

### 108 列出最新的设备

题目：列出最新的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources ORDER BY installation_date DESC LIMIT 1;
```

### 109 显示各状态用户数量

题目：显示各状态用户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_status, COUNT(*) AS user_cnt FROM customers GROUP BY customer_status;
```

### 110 统计男女用户比例

题目：统计男女用户比例，请输出对应SQL语句

参考 SQL：
```sql
SELECT SUM(CASE WHEN gender = '男' THEN 1 ELSE 0 END) AS male_cnt, SUM(CASE WHEN gender = '女' THEN 1 ELSE 0 END) AS female_cnt FROM customers;
```

### 111 列出各类型用户数

题目：列出各类型用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_type, COUNT(*) AS user_cnt FROM customers GROUP BY customer_type;
```

### 112 显示用户年龄分布

题目：显示用户年龄分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 18 THEN '18岁以下' WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 18 AND 30 THEN '18-30岁' WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 31 AND 50 THEN '31-50岁' WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 51 AND 60 THEN '51-60岁' ELSE '60岁以上' END AS age_group, COUNT(*) AS user_cnt FROM customers WHERE birth_date IS NOT NULL GROUP BY age_group;
```

### 113 统计各子类产品数

题目：统计各子类产品数，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_subtype, COUNT(*) AS product_cnt FROM products GROUP BY product_subtype;
```

### 114 列出各漫游区产品数

题目：列出各漫游区产品数，请输出对应SQL语句

参考 SQL：
```sql
SELECT roaming_zone, COUNT(*) AS product_cnt FROM products GROUP BY roaming_zone;
```

### 115 显示各话单来源数量

题目：显示各话单来源数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT cdr_source, COUNT(*) AS cdr_cnt FROM cdr_detail GROUP BY cdr_source;
```

### 116 统计各归属地话单数

题目：统计各归属地话单数，请输出对应SQL语句

参考 SQL：
```sql
SELECT home_location, COUNT(*) AS cdr_cnt FROM cdr_detail GROUP BY home_location;
```

### 117 列出各账单版本数量

题目：列出各账单版本数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT version, COUNT(*) AS bill_cnt FROM monthly_bills GROUP BY version;
```

### 118 显示各月份账单总额

题目：显示各月份账单总额，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(billing_month, '%Y-%m') AS bill_month, SUM(total_amount) AS total_amount FROM monthly_bills GROUP BY DATE_FORMAT(billing_month, '%Y-%m') ORDER BY bill_month;
```

### 119 统计各付费方式订购数

题目：统计各付费方式订购数，请输出对应SQL语句

参考 SQL：
```sql
SELECT payment_method, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY payment_method;
```

### 120 列出各数据来源订购数

题目：列出各数据来源订购数，请输出对应SQL语句

参考 SQL：
```sql
SELECT data_source, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY data_source;
```

### 121 显示各原因分类服务数

题目：显示各原因分类服务数，请输出对应SQL语句

参考 SQL：
```sql
SELECT first_level_reason, COUNT(*) AS svc_cnt FROM service_records GROUP BY first_level_reason ORDER BY svc_cnt DESC;
```

### 122 统计各紧急程度服务数

题目：统计各紧急程度服务数，请输出对应SQL语句

参考 SQL：
```sql
SELECT urgency_level, COUNT(*) AS svc_cnt FROM service_records GROUP BY urgency_level;
```

### 123 列出各目标客群活动数

题目：列出各目标客群活动数，请输出对应SQL语句

参考 SQL：
```sql
SELECT target_segment, COUNT(*) AS camp_cnt FROM marketing_campaigns GROUP BY target_segment;
```

### 124 显示各状态活动数

题目：显示各状态活动数，请输出对应SQL语句

参考 SQL：
```sql
SELECT status, COUNT(*) AS camp_cnt FROM marketing_campaigns GROUP BY status;
```

### 125 统计各区域设备数

题目：统计各区域设备数，请输出对应SQL语句

参考 SQL：
```sql
SELECT administrative_region, COUNT(*) AS res_cnt FROM network_resources GROUP BY administrative_region;
```

### 126 列出各状态设备数

题目：列出各状态设备数，请输出对应SQL语句

参考 SQL：
```sql
SELECT maintenance_status, COUNT(*) AS res_cnt FROM network_resources GROUP BY maintenance_status;
```

### 127 显示总用户数

题目：显示总用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS total_user_cnt FROM customers;
```

### 128 统计活跃用户数

题目：统计活跃用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS active_user_cnt FROM customers WHERE customer_status = '正常' AND (cancel_date IS NULL OR cancel_date > CURDATE());
```

### 129 列出销户用户数

题目：列出销户用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS cancelled_user_cnt FROM customers WHERE customer_status = '已销户';
```

### 130 显示产品总数

题目：显示产品总数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS product_total_cnt FROM products;
```

### 131 统计当前产品数

题目：统计当前产品数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS current_product_cnt FROM products WHERE is_current = 1;
```

### 132 列出话单总数

题目：列出话单总数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS cdr_total_cnt FROM cdr_detail;
```

### 133 统计流量记录数

题目：统计流量记录数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS data_cdr_cnt FROM cdr_detail WHERE call_type = '流量';
```

### 134 显示账单总数

题目：显示账单总数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS bill_total_cnt FROM monthly_bills;
```

### 135 统计已支付账单数

题目：统计已支付账单数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS paid_bill_cnt FROM monthly_bills WHERE payment_status = '已支付';
```

### 136 列出订购总数

题目：列出订购总数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS sub_total_cnt FROM subscriptions;
```

### 137 找出年龄在25-35之间的用户

题目：找出年龄在25-35之间的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE birth_date IS NOT NULL AND TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 25 AND 35;
```

### 138 列出最近3个月有活动的用户

题目：列出最近3个月有活动的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT c.customer_id, c.customer_name FROM customers c JOIN subscriptions s ON c.customer_id = s.customer_id WHERE s.start_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH);
```

### 139 显示每个用户的订购数量

题目：显示每个用户的订购数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY customer_id;
```

### 140 找出套餐变更过的用户

题目：找出套餐变更过的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT customer_id FROM subscriptions WHERE subscription_type IN ('升级', '降级') UNION SELECT customer_id FROM subscriptions GROUP BY customer_id, product_id HAVING COUNT(*) > 1;
```

### 141 列出通话最频繁的前10个号码

题目：列出通话最频繁的前10个号码，请输出对应SQL语句

参考 SQL：
```sql
SELECT msisdn, COUNT(*) AS call_cnt FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音', '视频通话') GROUP BY msisdn ORDER BY call_cnt DESC LIMIT 10;
```

### 142 显示每个号码的平均通话时长

题目：显示每个号码的平均通话时长，请输出对应SQL语句

参考 SQL：
```sql
SELECT msisdn, AVG(duration_seconds) AS avg_duration FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音', '视频通话') AND duration_seconds > 0 GROUP BY msisdn;
```

### 143 列出每个用户的月均账单

题目：列出每个用户的月均账单，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id, msisdn, AVG(total_amount) AS avg_bill_amount FROM monthly_bills GROUP BY customer_id, msisdn;
```

### 144 显示连续欠费2个月以上的用户

题目：显示连续欠费2个月以上的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id FROM (SELECT customer_id, billing_month, LAG(billing_month) OVER (PARTITION BY customer_id ORDER BY billing_month) AS prev_month FROM monthly_bills WHERE unpaid_amount > 0 AND payment_status IN ('待支付', '部分支付', '逾期')) t WHERE prev_month IS NOT NULL AND DATE_ADD(prev_month, INTERVAL 1 MONTH) = billing_month GROUP BY customer_id;
```

### 145 找出账单金额波动大的用户

题目：找出账单金额波动大的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id, STDDEV(total_amount) AS bill_volatility FROM monthly_bills GROUP BY customer_id ORDER BY bill_volatility DESC LIMIT 10;
```

### 146 列出每个客服的服务记录数

题目：列出每个客服的服务记录数，请输出对应SQL语句

参考 SQL：
```sql
SELECT agent_id, agent_name, COUNT(*) AS svc_cnt FROM service_records GROUP BY agent_id, agent_name;
```

### 147 显示平均处理时间最短的客服

题目：显示平均处理时间最短的客服，请输出对应SQL语句

参考 SQL：
```sql
SELECT agent_id, agent_name, AVG(duration_seconds) AS avg_duration FROM service_records GROUP BY agent_id, agent_name ORDER BY avg_duration ASC LIMIT 1;
```

### 148 找出投诉率高的客服

题目：找出投诉率高的客服，请输出对应SQL语句

参考 SQL：
```sql
SELECT agent_id, agent_name, SUM(is_complaint) / COUNT(*) AS complaint_rate FROM service_records GROUP BY agent_id, agent_name ORDER BY complaint_rate DESC;
```

### 149 列出ROI最高的5个活动

题目：列出ROI最高的5个活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT campaign_id, campaign_name, roi FROM marketing_campaigns ORDER BY roi DESC LIMIT 5;
```

### 150 显示超出预算的活动

题目：显示超出预算的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns WHERE actual_cost > budget_amount;
```

### 151 找出执行时间最长的活动

题目：找出执行时间最长的活动，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM marketing_campaigns ORDER BY DATEDIFF(COALESCE(end_date, extend_date), start_date) DESC LIMIT 1;
```

### 152 列出故障率最高的设备类型

题目：列出故障率最高的设备类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT resource_type, SUM(fault_count_30d) / COUNT(*) AS fault_rate FROM network_resources GROUP BY resource_type ORDER BY fault_rate DESC LIMIT 1;
```

### 153 显示维护成本最高的设备

题目：显示维护成本最高的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources ORDER BY maintenance_cost DESC LIMIT 1;
```

### 154 找出性能最差的基站

题目：找出性能最差的基站，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE resource_type = '基站' ORDER BY current_utilization DESC, avg_signal_strength ASC LIMIT 1;
```

### 155 列出每个地区的网络设备数量

题目：列出每个地区的网络设备数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT administrative_region, COUNT(*) AS res_cnt FROM network_resources GROUP BY administrative_region;
```

### 156 显示有父子关系的设备

题目：显示有父子关系的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM network_resources WHERE parent_resource_id IS NOT NULL;
```

### 157 列出每个产品的平均折扣

题目：列出每个产品的平均折扣，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, AVG(discount_rate) AS avg_discount FROM subscriptions GROUP BY product_id;
```

### 158 显示产品的订购热度

题目：显示产品的订购热度，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, COUNT(*) AS sub_cnt FROM subscriptions GROUP BY product_id ORDER BY sub_cnt DESC;
```

### 159 找出最受欢迎的数据套餐

题目：找出最受欢迎的数据套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_id, pr.product_name, COUNT(s.subscription_id) AS sub_cnt FROM products pr JOIN subscriptions s ON pr.product_id = s.product_id AND pr.version = s.product_version WHERE pr.data_allowance > 0 GROUP BY pr.product_id, pr.product_name ORDER BY sub_cnt DESC LIMIT 1;
```

### 160 列出每月的新增用户

题目：列出每月的新增用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(registration_date, '%Y-%m') AS reg_month, COUNT(*) AS user_cnt FROM customers GROUP BY DATE_FORMAT(registration_date, '%Y-%m') ORDER BY reg_month;
```

### 161 显示用户流失趋势

题目：显示用户流失趋势，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(cancel_date, '%Y-%m') AS cancel_month, COUNT(*) AS user_cnt FROM customers WHERE customer_status = '已销户' GROUP BY DATE_FORMAT(cancel_date, '%Y-%m') ORDER BY cancel_month;
```

### 162 找出用户生命周期分布

题目：找出用户生命周期分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN loyalty_months < 6 THEN '6个月内' WHEN loyalty_months BETWEEN 6 AND 12 THEN '6-12个月' WHEN loyalty_months BETWEEN 13 AND 24 THEN '13-24个月' WHEN loyalty_months BETWEEN 25 AND 36 THEN '25-36个月' ELSE '36个月以上' END AS life_cycle, COUNT(*) AS user_cnt FROM customers GROUP BY life_cycle;
```

### 163 列出各时段话务量高峰

题目：列出各时段话务量高峰，请输出对应SQL语句

参考 SQL：
```sql
SELECT HOUR(call_start_time) AS hour, COUNT(*) AS call_cnt FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音', '视频通话') GROUP BY HOUR(call_start_time) ORDER BY call_cnt DESC LIMIT 3;
```

### 164 显示周末和工作日的话务量对比

题目：显示周末和工作日的话务量对比，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN DAYOFWEEK(call_start_time) IN (1, 7) THEN '周末' ELSE '工作日' END AS day_type, COUNT(*) AS call_cnt FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音', '视频通话') GROUP BY day_type;
```

### 165 找出各季度的账单收入

题目：找出各季度的账单收入，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(billing_month) AS year, QUARTER(billing_month) AS q, SUM(total_amount) AS total_income FROM monthly_bills GROUP BY YEAR(billing_month), QUARTER(billing_month) ORDER BY year, q;
```

### 166 列出每月坏账金额

题目：列出每月坏账金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(billing_month, '%Y-%m') AS bill_month, SUM(unpaid_amount) AS bad_debt_amount FROM monthly_bills WHERE payment_status = '坏账' GROUP BY DATE_FORMAT(billing_month, '%Y-%m') ORDER BY bill_month;
```

### 167 显示各渠道的转化率对比

题目：显示各渠道的转化率对比，请输出对应SQL语句

参考 SQL：
```sql
SELECT channel, AVG(conversion_rate) AS avg_conversion_rate FROM marketing_campaigns GROUP BY channel;
```

### 168 找出各类型活动的平均参与人数

题目：找出各类型活动的平均参与人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT campaign_type, AVG(participants_count) AS avg_participants FROM marketing_campaigns GROUP BY campaign_type;
```

### 169 列出各厂商设备的平均故障率

题目：列出各厂商设备的平均故障率，请输出对应SQL语句

参考 SQL：
```sql
SELECT vendor, SUM(fault_count_30d) / COUNT(*) AS fault_rate FROM network_resources GROUP BY vendor;
```

### 170 显示设备安装时间分布

题目：显示设备安装时间分布，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(installation_date) AS install_year, COUNT(*) AS res_cnt FROM network_resources GROUP BY YEAR(installation_date) ORDER BY install_year;
```

### 171 找出推荐关系最广的用户

题目：找出推荐关系最广的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT referral_customer_id, COUNT(*) AS referred_cnt FROM customers WHERE referral_customer_id IS NOT NULL GROUP BY referral_customer_id ORDER BY referred_cnt DESC LIMIT 1;
```

### 172 列出被推荐用户的平均消费

题目：列出被推荐用户的平均消费，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(total_spend) AS avg_spend FROM customers WHERE referral_customer_id IS NOT NULL;
```

### 173 显示产品价格的分布情况

题目：显示产品价格的分布情况，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN base_fee < 50 THEN '50元以下' WHEN base_fee BETWEEN 50 AND 100 THEN '50-100元' WHEN base_fee BETWEEN 100 AND 200 THEN '100-200元' ELSE '200元以上' END AS price_range, COUNT(*) AS product_cnt FROM products GROUP BY price_range;
```

### 174 找出数据量最大的产品

题目：找出数据量最大的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products ORDER BY data_allowance DESC LIMIT 1;
```

### 175 找出消费增长最快的用户

题目：找出消费增长最快的用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id, customer_name, avg_monthly_spend FROM customers WHERE customer_status = '正常' ORDER BY avg_monthly_spend DESC LIMIT 10;
```

### 176 找出潜在流失用户

题目：找出潜在流失用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM customers WHERE customer_status = '正常' AND cancel_date IS NULL AND (last_recharge_date IS NULL OR last_recharge_date < DATE_SUB(CURDATE(), INTERVAL 90 DAY));
```

### 177 列出用户价值分层

题目：列出用户价值分层，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN total_spend < 1000 THEN '低价值' WHEN total_spend BETWEEN 1000 AND 10000 THEN '中价值' WHEN total_spend BETWEEN 10000 AND 50000 THEN '高价值' ELSE '超高价值' END AS value_tier, COUNT(*) AS user_cnt FROM customers GROUP BY value_tier;
```

### 178 显示用户的交叉购买倾向

题目：显示用户的交叉购买倾向，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.customer_id, c.customer_name FROM customers c JOIN subscriptions s ON c.customer_id = s.customer_id JOIN products p ON s.product_id = p.product_id AND s.product_version = p.version GROUP BY c.customer_id, c.customer_name HAVING COUNT(DISTINCT p.product_type) >= 2;
```

### 179 找出异常流量使用模式

题目：找出异常流量使用模式，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM cdr_detail WHERE data_volume_mb < 0 OR data_volume_mb > 50000;
```

### 180 显示用户的通话行为聚类

题目：显示用户的通话行为聚类，请输出对应SQL语句

参考 SQL：
```sql
SELECT msisdn, COUNT(*) AS call_cnt, AVG(duration_seconds) AS avg_duration, CASE WHEN COUNT(*) >= 50 THEN '高频' WHEN COUNT(*) BETWEEN 20 AND 49 THEN '中频' ELSE '低频' END AS call_cluster FROM cdr_detail WHERE call_type IN ('本地语音', '长途语音', '视频通话') GROUP BY msisdn;
```

### 181 列出用户的资费敏感度

题目：列出用户的资费敏感度，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.customer_type, AVG(s.discount_rate) AS avg_discount_rate FROM subscriptions s JOIN customers c ON s.customer_id = c.customer_id WHERE s.discount_rate > 0 GROUP BY c.customer_type;
```

### 182 显示渠道效率分析

题目：显示渠道效率分析，请输出对应SQL语句

参考 SQL：
```sql
SELECT channel, COUNT(*) AS camp_cnt, AVG(conversion_rate) AS avg_conversion_rate, SUM(actual_cost) AS total_cost FROM marketing_campaigns GROUP BY channel;
```

### 183 找出服务瓶颈

题目：找出服务瓶颈，请输出对应SQL语句

参考 SQL：
```sql
SELECT first_level_reason, AVG(duration_seconds) AS avg_duration, AVG(transfer_count) AS avg_transfer FROM service_records WHERE resolution_status IN ('待处理', '处理中', '升级处理') GROUP BY first_level_reason ORDER BY avg_duration DESC;
```

### 184 显示问题集中度分析

题目：显示问题集中度分析，请输出对应SQL语句

参考 SQL：
```sql
SELECT first_level_reason, COUNT(*) AS svc_cnt, COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () AS pct FROM service_records GROUP BY first_level_reason ORDER BY svc_cnt DESC;
```

### 185 找出客服技能匹配度

题目：找出客服技能匹配度，请输出对应SQL语句

参考 SQL：
```sql
SELECT skill_group, AVG(satisfaction_score) AS avg_satisfaction, AVG(transfer_count) AS avg_transfer, COUNT(*) AS svc_cnt FROM service_records GROUP BY skill_group;
```

### 186 列出营销活动的边际效应

题目：列出营销活动的边际效应，请输出对应SQL语句

参考 SQL：
```sql
SELECT campaign_id, campaign_name, conversion_count, actual_cost, conversion_count / actual_cost AS marginal_efficiency FROM marketing_campaigns WHERE actual_cost > 0 ORDER BY marginal_efficiency DESC;
```

### 187 显示活动时间优化分析

题目：显示活动时间优化分析，请输出对应SQL语句

参考 SQL：
```sql
SELECT DAYOFWEEK(start_date) AS start_weekday, AVG(conversion_rate) AS avg_conversion_rate FROM marketing_campaigns GROUP BY DAYOFWEEK(start_date) ORDER BY start_weekday;
```

### 188 显示设备老化分析

题目：显示设备老化分析，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE WHEN TIMESTAMPDIFF(YEAR, installation_date, CURDATE()) < 3 THEN '3年内' WHEN TIMESTAMPDIFF(YEAR, installation_date, CURDATE()) BETWEEN 3 AND 5 THEN '3-5年' WHEN TIMESTAMPDIFF(YEAR, installation_date, CURDATE()) BETWEEN 6 AND 8 THEN '6-8年' ELSE '8年以上' END AS age_tier, COUNT(*) AS res_cnt, AVG(fault_count_30d) AS avg_fault_cnt FROM network_resources GROUP BY age_tier;
```

### 189 找出投资回报率低的设备

题目：找出投资回报率低的设备，请输出对应SQL语句

参考 SQL：
```sql
SELECT resource_id, resource_name, current_utilization, maintenance_cost FROM network_resources WHERE maintenance_status <> '退役' AND maintenance_cost > 0 ORDER BY current_utilization / maintenance_cost ASC LIMIT 10;
```

### 190 列出网络拓扑中的关键节点

题目：列出网络拓扑中的关键节点，请输出对应SQL语句

参考 SQL：
```sql
SELECT r.resource_id, r.resource_name, r.current_utilization FROM network_resources r WHERE r.current_utilization >= 90 OR r.resource_id IN (SELECT parent_resource_id FROM network_resources WHERE parent_resource_id IS NOT NULL GROUP BY parent_resource_id HAVING COUNT(*) > 5);
```

### 191 显示系统整体健康度

题目：显示系统整体健康度，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS total_res_cnt, SUM(maintenance_status = '故障') AS fault_cnt, AVG(current_utilization) AS avg_utilization, AVG(mttr_hours) AS avg_mttr, AVG(fault_count_30d) AS avg_fault_cnt_30d FROM network_resources;
```

### 192 找出最便宜的套餐

题目：找出最便宜的套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, version, product_name, product_type, base_fee
FROM products
WHERE is_current = 1 AND product_type = '基础套餐'
ORDER BY base_fee ASC
LIMIT 1;
```

### 193 列出全部在售产品中价格最低的产品

题目：列出全部在售产品中价格最低的产品（不限套餐类型），请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, version, product_name, product_type, base_fee
FROM products
WHERE is_current = 1
ORDER BY base_fee ASC
LIMIT 1;
```

### 194 找出月租低于30元的套餐

题目：找出月租低于30元的当前有效套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, version, product_name, product_type, base_fee
FROM products
WHERE is_current = 1 AND base_fee > 0 AND base_fee < 30
ORDER BY base_fee ASC;
```

### 195 找出最贵的基础套餐

题目：找出当前有效的基础套餐中价格（base_fee）最贵的套餐，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, version, product_name, product_type, base_fee
FROM telecom_operations_db.products
WHERE is_current = 1 AND product_type = '基础套餐'
ORDER BY base_fee DESC
LIMIT 1;
```

### 196 查询2024年2月账单总金额与欠费总额

题目：查询2024年2月账单的总金额、未支付欠费总额和有账单的用户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT customer_id) AS bill_users,
       ROUND(SUM(total_amount), 2) AS bill_total,
       ROUND(SUM(unpaid_amount), 2) AS unpaid_total
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-02-01' AND billing_month < '2024-03-01';
```

### 197 统计2024年1月短信发送量最多的前10个号码

题目：统计2024年1月短信发送量（sms_count）最多的前10个号码，请输出对应SQL语句

参考 SQL：
```sql
SELECT msisdn, SUM(sms_count) AS total_sms
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle >= '2024-01-01' AND billing_cycle < '2024-02-01'
  AND call_type = '短信'
GROUP BY msisdn
ORDER BY total_sms DESC
LIMIT 10;
```

### 198 查看当前处于停机状态的用户数量

题目：查看当前处于停机状态的用户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS stop_users
FROM telecom_operations_db.customers
WHERE customer_status = '停机';
```

### 199 统计2024年1月新开通订购的数量和客户数

题目：统计2024年1月新开通订购的记录数和去重客户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS order_cnt, COUNT(DISTINCT customer_id) AS cust_cnt
FROM telecom_operations_db.subscriptions
WHERE start_date >= '2024-01-01' AND start_date < '2024-02-01';
```

### 200 每个套餐的用户数与账单总额

题目：按套餐汇总订购用户数与 2024 年账单总额，客户-订购-产品-账单四表关联（账单按订购号码 msisdn 归集，产品取当前有效版 is_current=1，订购与产品必须按 product_id + version 双键关联；未出账的套餐号码不会出现在结果中，需查全部套餐订购量请改用订购表直连产品表），请输出对应SQL语句

参考 SQL：
```sql
SELECT p.product_id,
       p.product_name,
       p.product_type,
       COUNT(DISTINCT s.customer_id) AS sub_users,
       COUNT(DISTINCT b.customer_id) AS bill_users,
       ROUND(SUM(b.total_amount), 2) AS bill_total
FROM telecom_operations_db.products p
JOIN telecom_operations_db.subscriptions s
  ON s.product_id = p.product_id AND s.product_version = p.version
JOIN telecom_operations_db.monthly_bills b
  ON b.msisdn = s.msisdn
 AND b.billing_month >= '2024-01-01' AND b.billing_month < '2025-01-01'
WHERE p.is_current = 1
GROUP BY p.product_id, p.product_name, p.product_type
ORDER BY sub_users DESC, bill_total DESC;
```

### 201 哪个套餐最受欢迎：当前在网订购的套餐用户数排行

题目：口语化问法。看当前还在生效（start_date <= 今天 且 end_date >= 今天 且 actual_end_date IS NULL）的订购里，哪些套餐订的人最多，取前 10。注意订购表本身没有状态列，只能用时间字段判断有效性，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.product_id,
       p.product_name,
       p.product_type,
       p.base_fee,
       COUNT(DISTINCT s.customer_id) AS current_users
FROM telecom_operations_db.products p
JOIN telecom_operations_db.subscriptions s
  ON s.product_id = p.product_id AND s.product_version = p.version
WHERE p.is_current = 1
  AND s.start_date <= CURDATE()
  AND s.end_date >= CURDATE()
  AND s.actual_end_date IS NULL
GROUP BY p.product_id, p.product_name, p.product_type, p.base_fee
ORDER BY current_users DESC
LIMIT 10;
```

### 202 谁欠费最多：2024年累计欠费金额前10的客户

题目：口语化问法。查 2024 年账单里累计欠费最多的前 10 名客户及其主档状态和 VIP 等级。欠费口径按账单表的 unpaid_amount > 0 统计，请输出对应SQL语句

参考 SQL：
```sql
SELECT b.customer_id,
       c.customer_name,
       c.customer_status,
       c.vip_level,
       COUNT(*) AS unpaid_bill_cnt,
       ROUND(SUM(b.unpaid_amount), 2) AS unpaid_total
FROM telecom_operations_db.monthly_bills b
JOIN telecom_operations_db.customers c ON c.customer_id = b.customer_id
WHERE b.billing_month >= '2024-01-01' AND b.billing_month < '2025-01-01'
  AND b.unpaid_amount > 0
GROUP BY b.customer_id, c.customer_name, c.customer_status, c.vip_level
ORDER BY unpaid_total DESC
LIMIT 10;
```

### 203 找出2024年既欠费又投诉过的客户清单

题目：客户-账单-客服工单三表关联，找出 2024 年账单有欠费（unpaid_amount > 0）且客服记录标记为投诉（is_complaint = 1）的客户，需要去重，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT c.customer_id, c.customer_name, c.customer_status, c.vip_level
FROM telecom_operations_db.customers c
JOIN telecom_operations_db.monthly_bills b ON b.customer_id = c.customer_id
JOIN telecom_operations_db.service_records r ON r.customer_id = c.customer_id
WHERE b.billing_month >= '2024-01-01' AND b.billing_month < '2025-01-01'
  AND b.unpaid_amount > 0
  AND r.is_complaint = 1
LIMIT 20;
```

### 204 统计2024年1月通话时长最长的前10个号码及其套餐和客户

题目：详单-订购-产品-客户四表关联，统计 2024 年 1 月成功接通的语音通话（本地语音/长途语音）总时长，取前 10 个号码并带出客户姓名和所属套餐名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT d.msisdn,
       c.customer_name,
       p.product_name,
       COUNT(*) AS call_cnt,
       ROUND(SUM(d.duration_seconds) / 60, 1) AS duration_minutes
FROM telecom_operations_db.cdr_detail d
JOIN telecom_operations_db.subscriptions s ON s.msisdn = d.msisdn
JOIN telecom_operations_db.products p
  ON p.product_id = s.product_id AND p.version = s.product_version
JOIN telecom_operations_db.customers c ON c.customer_id = s.customer_id
WHERE d.billing_cycle >= '2024-01-01' AND d.billing_cycle < '2024-02-01'
  AND d.call_type IN ('本地语音', '长途语音')
  AND d.call_result = '成功'
GROUP BY d.msisdn, c.customer_name, p.product_name
ORDER BY duration_minutes DESC
LIMIT 10;
```

### 205 每种套餐类型里最能花钱的前五名用户

题目：口语化问法。按套餐类型（product_type）分组，用客户累计消费 total_spend 排名，每种类型取前 5 名用户。注意：一个客户可能同时订了同类型的多个套餐，先按客户去重再排名，用窗口函数 ROW_NUMBER 实现分组 Top-N，请输出对应SQL语句

参考 SQL：
```sql
WITH base AS (
    SELECT DISTINCT p.product_type, c.customer_id, c.customer_name, c.total_spend
    FROM telecom_operations_db.customers c
    JOIN telecom_operations_db.subscriptions s ON s.customer_id = c.customer_id
    JOIN telecom_operations_db.products p
      ON p.product_id = s.product_id AND p.version = s.product_version
    WHERE p.is_current = 1
      AND s.start_date <= CURDATE()
      AND s.end_date >= CURDATE()
      AND s.actual_end_date IS NULL
),
ranked AS (
    SELECT product_type, customer_id, customer_name, total_spend,
           ROW_NUMBER() OVER (PARTITION BY product_type ORDER BY total_spend DESC) AS rn
    FROM base
)
SELECT product_type, rn, customer_id, customer_name,
       ROUND(total_spend, 2) AS total_spend
FROM ranked
WHERE rn <= 5
ORDER BY product_type, rn;
```

### 206 哪个营销活动最划算：ROI排行前10

题目：口语化问法。按 ROI 从高到低列出前 10 个营销活动，带出活动名称、渠道、状态、参与人数、转化人数和转化率，请输出对应SQL语句

参考 SQL：
```sql
SELECT campaign_id, campaign_name, campaign_type, channel, status,
       participants_count, conversion_count,
       ROUND(conversion_rate, 4) AS conversion_rate,
       ROUND(roi, 2) AS roi
FROM telecom_operations_db.marketing_campaigns
WHERE roi IS NOT NULL
ORDER BY roi DESC
LIMIT 10;
```

### 207 各营销渠道的活动效果排名

题目：按渠道汇总营销活动的活动数、总预算、总实际成本、总转化人数和平均 ROI，并按平均 ROI 从高到低排名，请输出对应SQL语句

参考 SQL：
```sql
SELECT channel,
       COUNT(*) AS campaign_cnt,
       SUM(budget_amount) AS budget_total,
       ROUND(SUM(actual_cost), 2) AS cost_total,
       SUM(conversion_count) AS conversions,
       ROUND(AVG(roi), 2) AS avg_roi
FROM telecom_operations_db.marketing_campaigns
GROUP BY channel
ORDER BY avg_roi DESC;
```

### 208 每个省份故障最严重的前3个网络资源

题目：网络资源按行政区域（administrative_region）分组，按近 30 天故障次数（fault_count_30d）降序、利用率（current_utilization）降序取每组前 3 个，用 ROW_NUMBER 窗口函数实现，请输出对应SQL语句

参考 SQL：
```sql
WITH ranked AS (
    SELECT administrative_region, resource_id, resource_name, resource_type,
           fault_count_30d, ROUND(current_utilization, 2) AS utilization,
           ROW_NUMBER() OVER (PARTITION BY administrative_region
                              ORDER BY fault_count_30d DESC, current_utilization DESC) AS rn
    FROM telecom_operations_db.network_resources
)
SELECT administrative_region, rn, resource_id, resource_name, resource_type,
       fault_count_30d, utilization
FROM ranked
WHERE rn <= 3
ORDER BY administrative_region, rn;
```

### 209 现在各类客户状态各有多少人、占比多少

题目：口语化问法。统计客户主档 customer_status（正常/停机/欠费/预销户/已销户）的用户数和占比，占比用 COUNT(*) 除以客户总数计算并保留 2 位小数，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_status,
       COUNT(*) AS user_cnt,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM telecom_operations_db.customers), 2) AS user_pct
FROM telecom_operations_db.customers
GROUP BY customer_status
ORDER BY user_cnt DESC;
```

### 210 2024年1月有多少人欠费、占比是多少

题目：按账单口径统计 2024 年 1 月的账单用户数、欠费用户数（unpaid_amount > 0 且按 customer_id 去重）以及欠费用户占比，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT customer_id) AS bill_users,
       COUNT(DISTINCT CASE WHEN unpaid_amount > 0 THEN customer_id END) AS unpaid_users,
       ROUND(COUNT(DISTINCT CASE WHEN unpaid_amount > 0 THEN customer_id END) * 100.0
             / COUNT(DISTINCT customer_id), 2) AS unpaid_pct
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2024-02-01';
```

### 211 2024年1月通信业务构成占比

题目：把 2024 年 1 月详单按业务大类归类（本地语音/长途语音/视频通话归为语音类，短信/彩信归为短信类，流量/国际漫游归为流量与漫游），统计各类的记录数与占比，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE
         WHEN call_type IN ('本地语音', '长途语音', '视频通话') THEN '语音类'
         WHEN call_type IN ('短信', '彩信') THEN '短信类'
         WHEN call_type IN ('流量', '国际漫游') THEN '流量与漫游'
         ELSE '其他'
       END AS biz_type,
       COUNT(*) AS cdr_cnt,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM telecom_operations_db.cdr_detail
                                 WHERE billing_cycle >= '2024-01-01'
                                   AND billing_cycle < '2024-02-01'), 2) AS cdr_pct
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle >= '2024-01-01' AND billing_cycle < '2024-02-01'
GROUP BY biz_type
ORDER BY cdr_cnt DESC;
```

### 212 2024年各支付状态的账单金额与未缴占比

题目：按 payment_status 汇总 2024 年账单的张数、账单金额、未缴金额，并用窗口函数计算各状态未缴金额占全部未缴金额的比例，请输出对应SQL语句

参考 SQL：
```sql
SELECT payment_status,
       COUNT(*) AS bill_cnt,
       ROUND(SUM(total_amount), 2) AS total_amount,
       ROUND(SUM(unpaid_amount), 2) AS unpaid_amount,
       ROUND(SUM(unpaid_amount) * 100.0 / SUM(SUM(unpaid_amount)) OVER (), 2) AS unpaid_pct
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
GROUP BY payment_status
ORDER BY unpaid_amount DESC;
```

### 213 哪个客服渠道最容易招投诉：各渠道投诉率

题目：口语化问法。按服务渠道 service_channel 统计工单量、投诉量（is_complaint = 1）和投诉率，按投诉率降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT service_channel,
       COUNT(*) AS ticket_cnt,
       SUM(is_complaint) AS complaint_cnt,
       ROUND(SUM(is_complaint) * 100.0 / COUNT(*), 2) AS complaint_rate
FROM telecom_operations_db.service_records
GROUP BY service_channel
ORDER BY complaint_rate DESC;
```

### 214 2024年账单总额逐月环比增长率

题目：按月汇总 2024 年账单总额，用窗口函数 LAG 取上月金额并计算环比增长率（百分比，保留 2 位小数）和上月金额，请输出对应SQL语句

参考 SQL：
```sql
WITH monthly AS (
    SELECT LEFT(billing_month, 7) AS ym,
           ROUND(SUM(total_amount), 2) AS bill_total
    FROM telecom_operations_db.monthly_bills
    WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
    GROUP BY LEFT(billing_month, 7)
)
SELECT ym,
       bill_total,
       LAG(bill_total) OVER (ORDER BY ym) AS prev_month_total,
       ROUND((bill_total - LAG(bill_total) OVER (ORDER BY ym)) * 100.0
             / LAG(bill_total) OVER (ORDER BY ym), 2) AS mom_pct
FROM monthly
ORDER BY ym;
```

### 215 2024与2025年账单总额同比与人均账单对比

题目：对比 2024 年和 2025 年的账单总额、账单用户数、人均账单（ARPU = 账单总额 / 账单用户数），并用 LAG 计算总额同比增长率，请输出对应SQL语句

参考 SQL：
```sql
WITH yearly AS (
    SELECT LEFT(billing_month, 4) AS yr,
           COUNT(DISTINCT customer_id) AS bill_users,
           ROUND(SUM(total_amount), 2) AS bill_total
    FROM telecom_operations_db.monthly_bills
    WHERE billing_month >= '2024-01-01' AND billing_month < '2026-01-01'
    GROUP BY LEFT(billing_month, 4)
)
SELECT yr,
       bill_users,
       bill_total,
       ROUND(bill_total / bill_users, 2) AS arpu,
       LAG(bill_total) OVER (ORDER BY yr) AS prev_year_total,
       ROUND((bill_total - LAG(bill_total) OVER (ORDER BY yr)) * 100.0
             / LAG(bill_total) OVER (ORDER BY yr), 2) AS yoy_pct
FROM yearly
ORDER BY yr;
```

### 216 ARPU逐月变化与环比差额

题目：按月统计 2024 年账单用户数与账单总额，计算各月 ARPU（账单总额 / 账单用户数，保留 2 位小数）以及与上月的 ARPU 差额，请输出对应SQL语句

参考 SQL：
```sql
WITH monthly AS (
    SELECT LEFT(billing_month, 7) AS ym,
           COUNT(DISTINCT customer_id) AS bill_users,
           ROUND(SUM(total_amount), 2) AS bill_total
    FROM telecom_operations_db.monthly_bills
    WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
    GROUP BY LEFT(billing_month, 7)
)
SELECT ym,
       bill_users,
       bill_total,
       ROUND(bill_total / bill_users, 2) AS arpu,
       ROUND(ROUND(bill_total / bill_users, 2)
             - LAG(ROUND(bill_total / bill_users, 2)) OVER (ORDER BY ym), 2) AS arpu_mom_diff
FROM monthly
ORDER BY ym;
```

### 217 2024与2025年1月语音时长、流量、短信同比

题目：用条件聚合（CASE WHEN）一次算出 2024 年 1 月和 2025 年 1 月两个账期的语音通话分钟数、流量 MB 数和短信条数，做同期同比对比。注意详单表 billing_cycle 是 DATE 值字符串，用 IN 精确匹配账期，请输出对应SQL语句

参考 SQL：
```sql
SELECT LEFT(billing_cycle, 4) AS yr,
       ROUND(SUM(CASE WHEN call_type IN ('本地语音', '长途语音')
                      THEN duration_seconds ELSE 0 END) / 60, 1) AS voice_minutes,
       ROUND(SUM(CASE WHEN call_type = '流量'
                      THEN data_volume_mb ELSE 0 END), 2) AS data_mb,
       SUM(CASE WHEN call_type IN ('短信', '彩信')
                THEN sms_count ELSE 0 END) AS sms_cnt
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle IN ('2024-01-01', '2025-01-01')
GROUP BY LEFT(billing_cycle, 4)
ORDER BY yr;
```

### 218 哪个套餐类型最能打电话、最费流量

题目：口语化问法。把 2024 年 1 月详单按号码关联当前有效套餐，用条件聚合一次算出各套餐类型的去重用户数、语音通话分钟数、流量 MB 数和短信条数，按语音时长降序，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.product_type,
       COUNT(DISTINCT d.msisdn) AS user_cnt,
       ROUND(SUM(CASE WHEN d.call_type IN ('本地语音', '长途语音')
                      THEN d.duration_seconds ELSE 0 END) / 60, 1) AS voice_minutes,
       ROUND(SUM(CASE WHEN d.call_type = '流量'
                      THEN d.data_volume_mb ELSE 0 END), 2) AS data_mb,
       SUM(CASE WHEN d.call_type IN ('短信', '彩信')
                THEN d.sms_count ELSE 0 END) AS sms_cnt
FROM telecom_operations_db.cdr_detail d
JOIN telecom_operations_db.subscriptions s ON s.msisdn = d.msisdn
JOIN telecom_operations_db.products p
  ON p.product_id = s.product_id AND p.version = s.product_version
WHERE d.billing_cycle >= '2024-01-01' AND d.billing_cycle < '2024-02-01'
  AND p.is_current = 1
GROUP BY p.product_type
ORDER BY voice_minutes DESC;
```

### 219 2024年账单各费用科目合计

题目：一次性算出 2024 年账单的套餐费、语音费、流量费、短信费、增值业务费、漫游费、一次性费用和账单总额，各科目金额保留 2 位小数，请输出对应SQL语句

参考 SQL：
```sql
SELECT ROUND(SUM(base_plan_fee), 2) AS plan_fee,
       ROUND(SUM(voice_usage_fee), 2) AS voice_fee,
       ROUND(SUM(data_usage_fee), 2) AS data_fee,
       ROUND(SUM(sms_usage_fee), 2) AS sms_fee,
       ROUND(SUM(value_added_fee), 2) AS vas_fee,
       ROUND(SUM(roaming_fee), 2) AS roaming_fee,
       ROUND(SUM(one_time_fee), 2) AS one_time_fee,
       ROUND(SUM(total_amount), 2) AS total_amount
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01';
```

### 220 各客户状态下的高端客户、企业客户与性别缺失构成

题目：按 customer_status 分组，用条件聚合一次算出高端 VIP 客户数（金卡/钻石/黑卡）、企业客户数、政企客户数以及性别缺失或未知的客户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_status,
       COUNT(*) AS user_cnt,
       SUM(CASE WHEN vip_level IN ('金卡', '钻石', '黑卡') THEN 1 ELSE 0 END) AS high_vip_cnt,
       SUM(CASE WHEN customer_type = '企业' THEN 1 ELSE 0 END) AS corp_cnt,
       SUM(CASE WHEN customer_type = '政企' THEN 1 ELSE 0 END) AS gov_cnt,
       SUM(CASE WHEN gender IS NULL OR gender = '未知' THEN 1 ELSE 0 END) AS gender_unknown_cnt
FROM telecom_operations_db.customers
GROUP BY customer_status
ORDER BY user_cnt DESC;
```

### 221 统计2024年1月有通话记录的去重用户数

题目：详单表只有号码没有客户号，需要关联订购表按客户去重，统计 2024 年 1 月产生过通话详单的去重客户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT s.customer_id) AS call_users
FROM telecom_operations_db.cdr_detail d
JOIN telecom_operations_db.subscriptions s ON s.msisdn = d.msisdn
WHERE d.billing_cycle >= '2024-01-01' AND d.billing_cycle < '2024-02-01';
```

### 222 统计2024年1月有账单但没有通话详单的客户数

题目：先用子查询取出 2024 年 1 月有通话详单的客户，再用 NOT IN 反查有账单但没有任何通话详单的客户数（去重），注意 NULL 会导致 NOT IN 失效，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(DISTINCT b.customer_id) AS bill_users_without_cdr
FROM telecom_operations_db.monthly_bills b
WHERE b.billing_month >= '2024-01-01' AND b.billing_month < '2024-02-01'
  AND b.customer_id NOT IN (
      SELECT s.customer_id
      FROM telecom_operations_db.cdr_detail d
      JOIN telecom_operations_db.subscriptions s ON s.msisdn = d.msisdn
      WHERE d.billing_cycle >= '2024-01-01' AND d.billing_cycle < '2024-02-01'
  );
```

### 223 统计2024年各月新增订购量与去重客户数

题目：按月统计 2024 年新增订购（start_date 落在该月）的订购笔数、去重客户数和去重号码数，请输出对应SQL语句

参考 SQL：
```sql
SELECT LEFT(start_date, 7) AS ym,
       COUNT(*) AS order_cnt,
       COUNT(DISTINCT customer_id) AS cust_cnt,
       COUNT(DISTINCT msisdn) AS msisdn_cnt
FROM telecom_operations_db.subscriptions
WHERE start_date >= '2024-01-01' AND start_date < '2025-01-01'
GROUP BY LEFT(start_date, 7)
ORDER BY ym;
```

### 224 大家打电话一般聊多久：通话时长分档分布

题目：口语化问法。对 2024 年 1 月成功接通的语音通话按时长分档（0 秒、1-60 秒、61-300 秒、301-900 秒、900 秒以上），统计各档通话笔数和平均时长，并按档位从小到大排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE
         WHEN duration_seconds = 0 THEN '0秒'
         WHEN duration_seconds <= 60 THEN '1-60秒'
         WHEN duration_seconds <= 300 THEN '61-300秒'
         WHEN duration_seconds <= 900 THEN '301-900秒'
         ELSE '900秒以上'
       END AS duration_bucket,
       COUNT(*) AS call_cnt,
       ROUND(AVG(duration_seconds), 1) AS avg_seconds
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle >= '2024-01-01' AND billing_cycle < '2024-02-01'
  AND call_type IN ('本地语音', '长途语音')
  AND call_result = '成功'
GROUP BY duration_bucket
ORDER BY MIN(duration_seconds);
```

### 225 2024年账单金额分档分布

题目：把 2024 年账单按 total_amount 分档（50 元以下、50-100 元、100-200 元、200 元及以上），统计各档账单张数、去重客户数和金额合计，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE
         WHEN total_amount < 50 THEN '50元以下'
         WHEN total_amount < 100 THEN '50-100元'
         WHEN total_amount < 200 THEN '100-200元'
         ELSE '200元及以上'
       END AS amount_bucket,
       COUNT(*) AS bill_cnt,
       COUNT(DISTINCT customer_id) AS user_cnt,
       ROUND(SUM(total_amount), 2) AS amount_sum
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
GROUP BY amount_bucket
ORDER BY amount_sum DESC;
```

### 226 老用户和新用户谁更舍得花钱：入网时长分档

题目：口语化问法。按 registration_date 与当前日期的入网月数分档（1 年以内、1-2 年、2-3 年、3 年以上），统计各档客户数和平均月消费。registration_date 是带时分秒的字符串，取前 10 位当日期用，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE
         WHEN TIMESTAMPDIFF(MONTH, LEFT(registration_date, 10), CURDATE()) < 12 THEN '1年以内'
         WHEN TIMESTAMPDIFF(MONTH, LEFT(registration_date, 10), CURDATE()) < 24 THEN '1-2年'
         WHEN TIMESTAMPDIFF(MONTH, LEFT(registration_date, 10), CURDATE()) < 36 THEN '2-3年'
         ELSE '3年以上'
       END AS tenure_bucket,
       COUNT(*) AS user_cnt,
       ROUND(AVG(avg_monthly_spend), 2) AS avg_monthly_spend
FROM telecom_operations_db.customers
GROUP BY tenure_bucket
ORDER BY user_cnt DESC;
```

### 227 基站负载分档与平均故障次数

题目：把网络资源按利用率 current_utilization 分档（低负载<30%、中负载30%-60%、高负载60%-85%、告警>=85%），统计各档资源数、平均近 30 天故障次数和平均维护成本，请输出对应SQL语句

参考 SQL：
```sql
SELECT CASE
         WHEN current_utilization < 30 THEN '低负载(<30%)'
         WHEN current_utilization < 60 THEN '中负载(30%-60%)'
         WHEN current_utilization < 85 THEN '高负载(60%-85%)'
         ELSE '告警(>=85%)'
       END AS util_bucket,
       COUNT(*) AS resource_cnt,
       ROUND(AVG(fault_count_30d), 2) AS avg_fault_cnt,
       ROUND(AVG(maintenance_cost), 2) AS avg_maintenance_cost
FROM telecom_operations_db.network_resources
GROUP BY util_bucket
ORDER BY resource_cnt DESC;
```

### 228 2025年11月客服工单按周统计

题目：按自然周（YEARWEEK 模式 1，周一为一周起点）统计 2025 年 11 月的客服工单量、周起始日期和投诉工单数，contact_time 是带时分秒的字符串，直接用日期函数处理，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEARWEEK(contact_time, 1) AS year_week,
       MIN(DATE(contact_time)) AS week_start,
       COUNT(*) AS ticket_cnt,
       SUM(is_complaint) AS complaint_cnt
FROM telecom_operations_db.service_records
WHERE contact_time >= '2025-11-01' AND contact_time < '2025-12-01'
GROUP BY YEARWEEK(contact_time, 1)
ORDER BY year_week;
```

### 229 2024年各季度账单汇总

题目：按季度汇总 2024 年的账单用户数、账单总额和欠费总额，季度用 YEAR + QUARTER 拼接成 2024-Q1 形式，请输出对应SQL语句

参考 SQL：
```sql
SELECT CONCAT(YEAR(billing_month), '-Q', QUARTER(billing_month)) AS quarter,
       COUNT(DISTINCT customer_id) AS bill_users,
       ROUND(SUM(total_amount), 2) AS bill_total,
       ROUND(SUM(unpaid_amount), 2) AS unpaid_total
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
GROUP BY quarter
ORDER BY quarter;
```

### 230 最近6个月账单趋势（以最新账期为基准的动态窗口）

题目：以数据中最新账期为准，用日期函数动态计算最近 6 个月（含最新账期）的起始账期，统计各月账单用户数和账单总额。注意 billing_month 是 DATE 值字符串，需要先转成当月 1 号再比较，请输出对应SQL语句

参考 SQL：
```sql
SELECT LEFT(billing_month, 7) AS ym,
       COUNT(DISTINCT customer_id) AS bill_users,
       ROUND(SUM(total_amount), 2) AS bill_total
FROM telecom_operations_db.monthly_bills
WHERE billing_month >= DATE_FORMAT(
          DATE_SUB((SELECT MAX(billing_month) FROM telecom_operations_db.monthly_bills),
                   INTERVAL 5 MONTH), '%Y-%m-01')
GROUP BY LEFT(billing_month, 7)
ORDER BY ym;
```

### 231 上一个完整账月的账单汇总（以最新账期为基准）

题目：以数据中最新账期为基准，用日期函数取上一个自然月（不包含最新账期所在月）的账单用户数、账单总额和欠费总额，请输出对应SQL语句

参考 SQL：
```sql
WITH latest AS (
    SELECT MAX(billing_month) AS max_month
    FROM telecom_operations_db.monthly_bills
)
SELECT LEFT(b.billing_month, 7) AS ym,
       COUNT(DISTINCT b.customer_id) AS bill_users,
       ROUND(SUM(b.total_amount), 2) AS bill_total,
       ROUND(SUM(b.unpaid_amount), 2) AS unpaid_total
FROM telecom_operations_db.monthly_bills b, latest
WHERE b.billing_month >= DATE_FORMAT(DATE_SUB(latest.max_month, INTERVAL 1 MONTH), '%Y-%m-01')
  AND b.billing_month < DATE_FORMAT(latest.max_month, '%Y-%m-01')
GROUP BY LEFT(b.billing_month, 7);
```

### 232 最近30天的客服工单量与投诉量（以最新工单时间为基准）

题目：以数据中最新工单时间 contact_time 为基准，用 DATE_SUB 计算最近 30 天的工单量、投诉工单数和平均满意度，请输出对应SQL语句

参考 SQL：
```sql
SELECT MAX(contact_time) AS latest_contact_time,
       COUNT(*) AS ticket_cnt,
       SUM(is_complaint) AS complaint_cnt,
       ROUND(AVG(satisfaction_score), 2) AS avg_satisfaction
FROM telecom_operations_db.service_records
WHERE contact_time >= DATE_SUB((SELECT MAX(contact_time) FROM telecom_operations_db.service_records),
                               INTERVAL 30 DAY);
```

### 233 未来3个月内到期的在网订购有多少

题目：统计当前未退订（actual_end_date IS NULL）且将在未来 3 个月内到期的订购笔数和去重客户数，到期时间用 DATE_ADD(CURDATE(), INTERVAL 3 MONTH) 计算，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS expiring_cnt,
       COUNT(DISTINCT customer_id) AS cust_cnt
FROM telecom_operations_db.subscriptions
WHERE actual_end_date IS NULL
  AND end_date >= CURDATE()
  AND end_date < DATE_ADD(CURDATE(), INTERVAL 3 MONTH);
```

### 234 有多少客户从来没出过账单

题目：口语化问法。用 LEFT JOIN 加 IS NULL 找出在账单表中没有任何记录的客户数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS no_bill_customers
FROM telecom_operations_db.customers c
LEFT JOIN telecom_operations_db.monthly_bills b ON b.customer_id = c.customer_id
WHERE b.bill_id IS NULL;
```

### 235 投诉次数不少于2次的客户

题目：从客服记录中统计投诉（is_complaint = 1）次数不少于 2 次的客户，用 HAVING 过滤分组结果，按投诉次数降序取前 20 条，请输出对应SQL语句

参考 SQL：
```sql
SELECT customer_id, COUNT(*) AS complaint_cnt
FROM telecom_operations_db.service_records
WHERE is_complaint = 1
GROUP BY customer_id
HAVING COUNT(*) >= 2
ORDER BY complaint_cnt DESC, customer_id
LIMIT 20;
```

### 236 需要重点关注的网络资源告警清单

题目：列出近 30 天故障次数不少于 3 次或利用率不低于 85% 的网络资源，带出资源类型、所属区域、维护状态、故障次数和利用率，请输出对应SQL语句

参考 SQL：
```sql
SELECT resource_id, resource_name, resource_type, administrative_region,
       maintenance_status, fault_count_30d,
       ROUND(current_utilization, 2) AS utilization
FROM telecom_operations_db.network_resources
WHERE fault_count_30d >= 3
   OR current_utilization >= 85
ORDER BY fault_count_30d DESC, utilization DESC;
```

### 237 2024年详单数据质量与异常值排查

题目：排查 2024 年详单的数据质量：统计记录总数、流量为负的记录数（data_volume_mb 存在负值异常）、费用为负的记录数、费用为 0 的记录数、号码为空的记录数和通话成功的记录数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS cdr_cnt,
       SUM(CASE WHEN data_volume_mb < 0 THEN 1 ELSE 0 END) AS negative_data_cnt,
       SUM(CASE WHEN total_fee < 0 THEN 1 ELSE 0 END) AS negative_fee_cnt,
       SUM(CASE WHEN total_fee = 0 THEN 1 ELSE 0 END) AS zero_fee_cnt,
       SUM(CASE WHEN msisdn IS NULL THEN 1 ELSE 0 END) AS null_msisdn_cnt,
       SUM(CASE WHEN call_result = '成功' THEN 1 ELSE 0 END) AS success_cnt
FROM telecom_operations_db.cdr_detail
WHERE billing_cycle >= '2024-01-01' AND billing_cycle < '2025-01-01';
```

### 238 客户主档状态与账单欠费口径不一致的客户数

题目：排查口径差异：客户主档状态为正常或停机，但 2024 年账单存在未缴金额（unpaid_amount > 0）的客户数，按主档状态分组。注意主档状态是快照，账单欠费以 unpaid_amount 为准，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.customer_status,
       COUNT(DISTINCT c.customer_id) AS mismatch_cust_cnt
FROM telecom_operations_db.customers c
JOIN telecom_operations_db.monthly_bills b ON b.customer_id = c.customer_id
WHERE c.customer_status IN ('正常', '停机')
  AND b.unpaid_amount > 0
  AND b.billing_month >= '2024-01-01' AND b.billing_month < '2025-01-01'
GROUP BY c.customer_status
ORDER BY mismatch_cust_cnt DESC;
```

### 239 谁花钱最多：2024年账单总额前10客户及其当前套餐

题目：口语化问法。先用 CTE 聚合出 2024 年账单总额前 10 的客户，再关联客户主档，并用另一个聚合子查询取出客户当前生效的基础套餐名称（一个客户可能有多个订购，先聚合再关联避免行数膨胀），请输出对应SQL语句

参考 SQL：
```sql
WITH top_cust AS (
    SELECT customer_id,
           ROUND(SUM(total_amount), 2) AS bill_total
    FROM telecom_operations_db.monthly_bills
    WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'
    GROUP BY customer_id
    ORDER BY bill_total DESC
    LIMIT 10
),
main_plan AS (
    SELECT s.customer_id, MIN(p.product_name) AS product_name
    FROM telecom_operations_db.subscriptions s
    JOIN telecom_operations_db.products p
      ON p.product_id = s.product_id AND p.version = s.product_version
    WHERE p.is_current = 1
      AND p.product_type = '基础套餐'
      AND s.start_date <= CURDATE()
      AND s.end_date >= CURDATE()
      AND s.actual_end_date IS NULL
    GROUP BY s.customer_id
)
SELECT t.customer_id,
       c.customer_name,
       c.customer_status,
       t.bill_total,
       m.product_name
FROM top_cust t
JOIN telecom_operations_db.customers c ON c.customer_id = t.customer_id
LEFT JOIN main_plan m ON m.customer_id = t.customer_id
ORDER BY t.bill_total DESC;
```
