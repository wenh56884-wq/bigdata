# 金融资产管理库（financial_asset_management）自然语言查询 → SQL 问答

> 使用对象：把中文业务问题转成标准 SQL（MySQL 兼容），字段一律采用英文表名 / 字段名，避免自造表名。

覆盖客户 clients、客户经理 managers、产品 products、对手方 counterparties、投资组合 portfolios、交易流水 transactions、持仓 holdings、风险指标 risk_metrics 共 8 张表。

字段与取值约定：
- 客户状态 clients.status：1=正常，2=冻结，3=销户。
- 风险等级：保守/稳健/平衡/成长/进取；产品类型：股票型/债券型/混合型/货币型/QDII/另类投资。
- 资产单位为元（1000 万=10000000，1 亿=100000000）。
- 客户联系方式 contact_info、产品资产配置 asset_allocation 为 JSON 字段。

## 库表字段速查

- managers（客户经理表）：
    -  manager_id 经理ID
    -  manager_code 工号
    -  manager_name 姓名
    -  department_id 部门ID
    -  department_name 部门名称
    -  position_level 职级
    -  hire_date 入职日期
    -  manage_assets_total 管理资产总额
    -  client_count 客户数量
    -  performance_score 绩效评分
    -  superior_id 上级ID

- clients（客户表）：
    -  client_id 客户ID
    -  client_code 客户编码
    -  client_name 客户名称
    -  client_type 客户类型
    -  risk_level 风险等级
    -  register_date 注册日期
    -  total_assets 总资产规模
    -  contact_info 联系信息
    -  manager_id 客户经理ID
    -  create_time 创建时间
    -  update_time 更新时间
    -  status 状态

- products（产品信息表）：
    -  product_id 产品ID
    -  product_code 产品代码
    -  product_name 产品名称
    -  product_type 产品类型
    -  risk_rating 风险评级
    -  currency 币种
    -  management_fee 管理费率
    -  performance_fee_rate 业绩报酬比例
    -  inception_date 成立日期
    -  benchmark_index 业绩比较基准
    -  asset_allocation 资产配置比例
    -  is_active 是否有效产品

- counterparties（对手方表）：
    -  counterparty_id 对手方ID
    -  counterparty_code 对手方编码
    -  counterparty_name 对手方名称
    -  counterparty_type 对手方类型
    -  credit_rating 信用评级
    -  country_code 国家代码
    -  is_active 是否有效
    -  establish_date 成立日期
    -  registered_capital 注册资本

- portfolios（投资组合表）：
    -  portfolio_id 组合ID
    -  portfolio_code 组合代码
    -  client_id 客户ID
    -  portfolio_type 组合类型
    -  target_return 目标收益率
    -  max_drawdown_limit 最大回撤限制
    -  inception_date 组合成立日
    -  termination_date 组合终止日
    -  current_value 当前市值
    -  contribution_amount 累计投入金额
    -  risk_adjust_return 风险调整后收益
    -  create_user 创建人
    -  create_time 创建时间

- transactions（交易流水表）：
    -  transaction_id 交易流水号
    -  trade_id 交易所成交编号
    -  portfolio_id 组合ID
    -  product_id 产品ID
    -  transaction_type 交易类型
    -  trade_date 交易日期
    -  settlement_date 结算日期
    -  transaction_quantity 交易数量
    -  transaction_price 成交价格
    -  transaction_amount 成交金额
    -  commission_fee 佣金费用
    -  stamp_duty 印花税
    -  net_amount 净额
    -  counterparty_id 对手方ID
    -  trader_id 交易员ID
    -  trade_time 交易时间
    -  status 交易状态

- holdings（持仓明细表）：
    -  holding_id 持仓记录ID
    -  portfolio_id 组合ID
    -  product_id 产品ID
    -  trade_date 交易日期
    -  holding_quantity 持有数量
    -  average_cost 平均成本
    -  market_price 市价
    -  market_value 市值
    -  unrealized_pnl 浮动盈亏
    -  holding_days 持有天数
    -  is_pledged 是否质押
    -  pledge_ratio 质押比例
    -  last_update 最后更新时间

- risk_metrics（风险监控表）：
    -  metric_id 指标ID
    -  portfolio_id 组合ID
    -  calc_date 计算日期
    -  var_95 VaR值
    -  expected_shortfall 预期损失
    -  max_drawdown 最大回撤
    -  volatility 波动率
    -  beta 贝塔系数
    -  sharp_ratio 夏普比率
    -  tracking_error 跟踪误差
    -  concentration_ratio 集中度
    -  liquidity_score 流动性评分
    -  risk_exposure 风险敞口
    -  is_alert 是否预警

## 问答样例（题目 → 参考 SQL）

### 1 列出所有姓王的客户信息

题目：列出所有姓王的客户信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_name LIKE '王%';
```

### 2 统计不同类型的客户数量

题目：统计不同类型的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, COUNT(*) AS client_cnt FROM clients GROUP BY client_type;
```

### 3 找出总资产超过1000万的客户

题目：找出总资产超过1000万的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE total_assets > 10000000;
```

### 4 显示所有活跃的产品

题目：显示所有活跃的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_active = 1;
```

### 5 按部门统计客户经理数量

题目：按部门统计客户经理数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_name, COUNT(*) AS manager_cnt FROM managers GROUP BY department_name;
```

### 6 找出2023年注册的客户

题目：找出2023年注册的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE YEAR(register_date) = 2023;
```

### 7 查看风险等级为'成长'的客户

题目：查看风险等级为'成长'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE risk_level = '成长';
```

### 8 统计各产品类型的数量

题目：统计各产品类型的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, COUNT(*) AS product_cnt FROM products GROUP BY product_type;
```

### 9 找出管理资产最多的前10位客户经理

题目：找出管理资产最多的前10位客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers ORDER BY manage_assets_total DESC LIMIT 10;
```

### 10 显示所有已终止的投资组合

题目：显示所有已终止的投资组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE termination_date IS NOT NULL;
```

### 11 统计各币种的产品数量

题目：统计各币种的产品数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT currency, COUNT(*) AS product_cnt FROM products GROUP BY currency;
```

### 12 找出夏普比率大于1的组合

题目：找出夏普比率大于1的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.portfolio_id, p.portfolio_code FROM risk_metrics rm JOIN portfolios p ON rm.portfolio_id = p.portfolio_id WHERE rm.sharp_ratio > 1;
```

### 13 列出所有状态为'冻结'的客户

题目：列出所有状态为'冻结'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE status = 2;
```

### 14 按职级统计客户经理的平均绩效

题目：按职级统计客户经理的平均绩效，请输出对应SQL语句

参考 SQL：
```sql
SELECT position_level, AVG(performance_score) AS avg_score FROM managers GROUP BY position_level;
```

### 15 找出所有银行类型的对手方

题目：找出所有银行类型的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE counterparty_type = '银行';
```

### 16 显示风险评级为5的产品

题目：显示风险评级为5的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE risk_rating = 5;
```

### 17 统计每个月的客户注册数量

题目：统计每个月的客户注册数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(register_date, '%Y-%m') AS reg_month, COUNT(*) AS client_cnt FROM clients GROUP BY DATE_FORMAT(register_date, '%Y-%m') ORDER BY reg_month;
```

### 18 找出成立时间超过10年的对手方

题目：找出成立时间超过10年的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE TIMESTAMPDIFF(YEAR, establish_date, CURDATE()) > 10;
```

### 19 列出所有全权委托类型的组合

题目：列出所有全权委托类型的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE portfolio_type = '全权委托';
```

### 20 统计各客户类型的平均资产

题目：统计各客户类型的平均资产，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, AVG(total_assets) AS avg_assets FROM clients GROUP BY client_type;
```

### 21 找出绩效评分低于60的客户经理

题目：找出绩效评分低于60的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE performance_score < 60;
```

### 22 显示管理费率超过2%的产品

题目：显示管理费率超过2%的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE management_fee > 0.02;
```

### 23 按国家统计对手方数量

题目：按国家统计对手方数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT country_code, COUNT(*) AS cp_cnt FROM counterparties GROUP BY country_code;
```

### 24 找出目标收益率超过10%的组合

题目：找出目标收益率超过10%的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE target_return > 0.1;
```

### 25 统计各风险等级的客户数量

题目：统计各风险等级的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT risk_level, COUNT(*) AS client_cnt FROM clients GROUP BY risk_level;
```

### 26 显示所有有业绩报酬的产品

题目：显示所有有业绩报酬的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE performance_fee_rate > 0;
```

### 27 找出客户数量最多的前5个部门

题目：找出客户数量最多的前5个部门，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_name, SUM(client_count) AS total_clients FROM managers GROUP BY department_name ORDER BY total_clients DESC LIMIT 5;
```

### 28 列出所有非中国的对手方

题目：列出所有非中国的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE country_code <> 'CN';
```

### 29 统计各组合类型的数量

题目：统计各组合类型的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_type, COUNT(*) AS portfolio_cnt FROM portfolios GROUP BY portfolio_type;
```

### 30 找出2024年成立的组合

题目：找出2024年成立的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE YEAR(inception_date) = 2024;
```

### 31 显示所有股票型产品

题目：显示所有股票型产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = '股票型';
```

### 32 找出最大回撤限制小于10%的组合

题目：找出最大回撤限制小于10%的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE max_drawdown_limit < 0.1;
```

### 33 统计各状态客户的数量

题目：统计各状态客户的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT status, COUNT(*) AS client_cnt FROM clients GROUP BY status;
```

### 34 列出所有总监及以上职级的客户经理

题目：列出所有总监及以上职级的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE position_level IN ('总监', '总经理');
```

### 35 找出注册资本超过10亿的对手方

题目：找出注册资本超过10亿的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE registered_capital > 1000000000;
```

### 36 显示所有失效的产品

题目：显示所有失效的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_active = 0;
```

### 37 找出成立时间最早的10个产品

题目：找出成立时间最早的10个产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products ORDER BY inception_date ASC LIMIT 10;
```

### 38 统计各月份的组合成立数量

题目：统计各月份的组合成立数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(inception_date, '%Y-%m') AS inc_month, COUNT(*) AS portfolio_cnt FROM portfolios GROUP BY DATE_FORMAT(inception_date, '%Y-%m') ORDER BY inc_month;
```

### 39 找出所有姓张或姓李的客户

题目：找出所有姓张或姓李的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_name LIKE '张%' OR client_name LIKE '李%';
```

### 40 显示所有非活跃的对手方

题目：显示所有非活跃的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE is_active = 0;
```

### 41 找出资产为空的客户

题目：找出资产为空的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE total_assets IS NULL;
```

### 42 统计各基准指数的产品数量

题目：统计各基准指数的产品数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT benchmark_index, COUNT(*) AS product_cnt FROM products GROUP BY benchmark_index;
```

### 43 列出所有入职超过5年的客户经理

题目：列出所有入职超过5年的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE TIMESTAMPDIFF(YEAR, hire_date, CURDATE()) > 5;
```

### 44 找出成立时间在2020-2021年之间的产品

题目：找出成立时间在2020-2021年之间的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE YEAR(inception_date) BETWEEN 2020 AND 2021;
```

### 45 显示所有客户编码以'C'开头的机构客户

题目：显示所有客户编码以'C'开头的机构客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_code LIKE 'C%' AND client_type = '机构';
```

### 46 统计各职位级别的平均管理资产

题目：统计各职位级别的平均管理资产，请输出对应SQL语句

参考 SQL：
```sql
SELECT position_level, AVG(manage_assets_total) AS avg_assets FROM managers GROUP BY position_level;
```

### 47 找出所有风险等级为保守且资产超过500万的客户

题目：找出所有风险等级为保守且资产超过500万的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE risk_level = '保守' AND total_assets > 5000000;
```

### 48 列出所有QDII类型的产品

题目：列出所有QDII类型的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = 'QDII';
```

### 49 找出成立时间最晚的10个组合

题目：找出成立时间最晚的10个组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios ORDER BY inception_date DESC LIMIT 10;
```

### 50 统计各年份的产品成立数量

题目：统计各年份的产品成立数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(inception_date) AS inc_year, COUNT(*) AS product_cnt FROM products GROUP BY YEAR(inception_date) ORDER BY inc_year;
```

### 51 显示所有信用评级低于A的对手方

题目：显示所有信用评级低于A的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE credit_rating IN ('BBB', 'BB', 'B', 'CCC', 'D');
```

### 52 找出所有组合价值低于投入金额的组合

题目：找出所有组合价值低于投入金额的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE current_value < contribution_amount;
```

### 53 列出所有风险评级为1的货币型产品

题目：列出所有风险评级为1的货币型产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE risk_rating = 1 AND product_type = '货币型';
```

### 54 找出所有资产为负值的客户

题目：找出所有资产为负值的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE total_assets < 0;
```

### 55 显示所有成立时间早于2010年的对手方

题目：显示所有成立时间早于2010年的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE establish_date < '2010-01-01';
```

### 56 统计各产品类型的管理费率平均值

题目：统计各产品类型的管理费率平均值，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(management_fee) AS avg_fee FROM products GROUP BY product_type;
```

### 57 找出所有绩效评分在90分以上的客户经理

题目：找出所有绩效评分在90分以上的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE performance_score > 90;
```

### 58 统计每天的平均交易数量

题目：统计每天的平均交易数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT AVG(daily_cnt) AS avg_daily_cnt FROM (SELECT trade_date, COUNT(*) AS daily_cnt FROM transactions GROUP BY trade_date) t;
```

### 59 找出所有成立时间在周一的组合

题目：找出所有成立时间在周一的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE DAYOFWEEK(inception_date) = 2;
```

### 60 显示所有交易金额超过100万的交易

题目：显示所有交易金额超过100万的交易，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE transaction_amount > 1000000;
```

### 61 统计各对手方类型的平均注册资本

题目：统计各对手方类型的平均注册资本，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_type, AVG(registered_capital) AS avg_capital FROM counterparties GROUP BY counterparty_type;
```

### 62 列出所有在2023年入职的客户经理

题目：列出所有在2023年入职的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE YEAR(hire_date) = 2023;
```

### 63 统计各风险等级的平均资产

题目：统计各风险等级的平均资产，请输出对应SQL语句

参考 SQL：
```sql
SELECT risk_level, AVG(total_assets) AS avg_assets FROM clients GROUP BY risk_level;
```

### 64 统计各月份的平均交易金额

题目：统计各月份的平均交易金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(trade_date, '%Y-%m') AS trade_month, AVG(transaction_amount) AS avg_amount FROM transactions GROUP BY DATE_FORMAT(trade_date, '%Y-%m') ORDER BY trade_month;
```

### 65 找出所有成立时间在春节前后一个月的组合

题目：找出所有成立时间在春节前后一个月的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE MONTH(inception_date) IN (1, 2, 3);
```

### 66 列出所有地址包含'北京'的客户

题目：列出所有地址包含'北京'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE contact_info LIKE '%北京%';
```

### 67 统计各产品类型的最大风险评级

题目：统计各产品类型的最大风险评级，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, MAX(risk_rating) AS max_rating FROM products GROUP BY product_type;
```

### 68 显示所有对手方编码长度为7的对手方

题目：显示所有对手方编码长度为7的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE CHAR_LENGTH(counterparty_code) = 7;
```

### 69 统计各年份的客户经理入职数量

题目：统计各年份的客户经理入职数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(hire_date) AS hire_year, COUNT(*) AS manager_cnt FROM managers GROUP BY YEAR(hire_date) ORDER BY hire_year;
```

### 70 找出所有管理费率在1%-2%之间的产品

题目：找出所有管理费率在1%-2%之间的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE management_fee BETWEEN 0.01 AND 0.02;
```

### 71 统计各组合类型的平均当前价值

题目：统计各组合类型的平均当前价值，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_type, AVG(current_value) AS avg_value FROM portfolios GROUP BY portfolio_type;
```

### 72 找出所有在9:00-11:00之间进行的交易

题目：找出所有在9:00-11:00之间进行的交易，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE TIME(trade_time) BETWEEN '09:00:00' AND '11:00:00';
```

### 73 显示所有产品名称长度超过10个字的产品

题目：显示所有产品名称长度超过10个字的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE CHAR_LENGTH(product_name) > 10;
```

### 74 统计各风险评级的平均管理费率

题目：统计各风险评级的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT risk_rating, AVG(management_fee) AS avg_fee FROM products GROUP BY risk_rating;
```

### 75 列出所有成立时间在同一天的产品和组合

题目：列出所有成立时间在同一天的产品和组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.product_id, p.product_name, pf.portfolio_id, pf.portfolio_code FROM products p JOIN portfolios pf ON DATE(p.inception_date) = DATE(pf.inception_date);
```

### 76 统计各币种的平均管理费率

题目：统计各币种的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT currency, AVG(management_fee) AS avg_fee FROM products GROUP BY currency;
```

### 77 找出所有交易状态为'已撤'的交易

题目：找出所有交易状态为'已撤'的交易，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE status = '已撤';
```

### 78 显示所有客户经理姓名以'张'开头且入职超过3年

题目：显示所有客户经理姓名以'张'开头且入职超过3年，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE manager_name LIKE '张%' AND TIMESTAMPDIFF(YEAR, hire_date, CURDATE()) > 3;
```

### 79 找出所有资产配置中股票比例超过80%的产品

题目：找出所有资产配置中股票比例超过80%的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.equity')) AS DECIMAL(6,4)) > 0.8;
```

### 80 列出所有成立时间在季度末的组合

题目：列出所有成立时间在季度末的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE MONTH(inception_date) IN (3, 6, 9, 12) AND DAY(inception_date) = DAY(LAST_DAY(inception_date));
```

### 81 统计各月份的平均佣金费用

题目：统计各月份的平均佣金费用，请输出对应SQL语句

参考 SQL：
```sql
SELECT DATE_FORMAT(trade_date, '%Y-%m') AS trade_month, AVG(commission_fee) AS avg_commission FROM transactions GROUP BY DATE_FORMAT(trade_date, '%Y-%m') ORDER BY trade_month;
```

### 82 找出所有客户类型为'家族信托'且资产超过1亿的客户

题目：找出所有客户类型为'家族信托'且资产超过1亿的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_type = '家族信托' AND total_assets > 100000000;
```

### 83 显示所有交易对手方为券商的交易

题目：显示所有交易对手方为券商的交易，请输出对应SQL语句

参考 SQL：
```sql
SELECT t.* FROM transactions t JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id WHERE cp.counterparty_type = '券商';
```

### 84 统计各产品类型的业绩报酬比例平均值

题目：统计各产品类型的业绩报酬比例平均值，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(performance_fee_rate) AS avg_fee_rate FROM products GROUP BY product_type;
```

### 85 找出所有在2024年有交易的组合

题目：找出所有在2024年有交易的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT portfolio_id FROM transactions WHERE YEAR(trade_date) = 2024;
```

### 86 列出所有客户经理及其管理的客户数量

题目：列出所有客户经理及其管理的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id, manager_name, client_count FROM managers;
```

### 87 统计各年份的产品平均风险评级

题目：统计各年份的产品平均风险评级，请输出对应SQL语句

参考 SQL：
```sql
SELECT YEAR(inception_date) AS inc_year, AVG(risk_rating) AS avg_rating FROM products GROUP BY YEAR(inception_date) ORDER BY inc_year;
```

### 88 找出所有状态为正常的客户

题目：找出所有状态为正常的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE status = 1;
```

### 89 列出所有活跃的产品（is_active为true）

题目：列出所有活跃的产品（is_active为true），请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_active = 1;
```

### 90 查出风险等级为'进取'的客户数量

题目：查出风险等级为'进取'的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS client_cnt FROM clients WHERE risk_level = '进取';
```

### 91 显示所有已终止的投资组合及其终止日期

题目：显示所有已终止的投资组合及其终止日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_id, portfolio_code, termination_date FROM portfolios WHERE termination_date IS NOT NULL;
```

### 92 统计每种产品类型的数量

题目：统计每种产品类型的数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, COUNT(*) AS product_cnt FROM products GROUP BY product_type;
```

### 93 列出所有买入类交易（transaction_type='买入'）

题目：列出所有买入类交易（transaction_type='买入'），请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE transaction_type = '买入';
```

### 94 显示所有夏普比率小于0的风险记录

题目：显示所有夏普比率小于0的风险记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM risk_metrics WHERE sharp_ratio < 0;
```

### 95 查出绩效评分高于90的客户经理

题目：查出绩效评分高于90的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE performance_score > 90;
```

### 96 列出所有个人客户的姓名和编码

题目：列出所有个人客户的姓名和编码，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, client_code FROM clients WHERE client_type = '个人';
```

### 97 找出所有风险等级是'进取'的客户ID

题目：找出所有风险等级是'进取'的客户ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id FROM clients WHERE risk_level = '进取';
```

### 98 显示所有有效的理财产品（产品）

题目：显示所有有效的理财产品（产品），请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE is_active = 1;
```

### 99 查询所有在2023年注册的客户数量

题目：查询所有在2023年注册的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS client_cnt FROM clients WHERE YEAR(register_date) = 2023;
```

### 100 列出所有客户经理的名字和工号

题目：列出所有客户经理的名字和工号，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, manager_code FROM managers;
```

### 101 找出所有管理资产总额超过1亿的客户经理ID

题目：找出所有管理资产总额超过1亿的客户经理ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id FROM managers WHERE manage_assets_total > 100000000;
```

### 102 显示所有货币型产品的名称和代码

题目：显示所有货币型产品的名称和代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, product_code FROM products WHERE product_type = '货币型';
```

### 103 查询所有状态为正常的客户信息

题目：查询所有状态为正常的客户信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE status = 1;
```

### 104 列出所有成立日期在2021年的产品ID和名称

题目：列出所有成立日期在2021年的产品ID和名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_name FROM products WHERE YEAR(inception_date) = 2021;
```

### 105 找出所有客户联系信息中的电话号码（仅展示前10条）

题目：找出所有客户联系信息中的电话号码（仅展示前10条），请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id, client_name, JSON_UNQUOTE(JSON_EXTRACT(contact_info, '$.phone')) AS phone FROM clients WHERE contact_info IS NOT NULL LIMIT 10;
```

### 106 列出所有个人客户的姓名和风险等级

题目：列出所有个人客户的姓名和风险等级，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, risk_level FROM clients WHERE client_type = '个人';
```

### 107 找出所有代码以'PROD0001'开头的产品名称和类型

题目：找出所有代码以'PROD0001'开头的产品名称和类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, product_type FROM products WHERE product_code LIKE 'PROD0001%';
```

### 108 统计有多少个有效的（未被冻结或销户）客户

题目：统计有多少个有效的（未被冻结或销户）客户？，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS valid_client_cnt FROM clients WHERE status = 1;
```

### 109 列出所有风险评级为5级的产品代码和名称

题目：列出所有风险评级为5级的产品代码和名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_code, product_name FROM products WHERE risk_rating = 5;
```

### 110 找出所有在2023年注册的客户编码和注册日期

题目：找出所有在2023年注册的客户编码和注册日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_code, register_date FROM clients WHERE YEAR(register_date) = 2023;
```

### 111 列出所有无效（已终止）的投资组合代码和创建时间

题目：列出所有无效（已终止）的投资组合代码和创建时间，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_code, create_time FROM portfolios WHERE termination_date IS NOT NULL;
```

### 112 统计每种客户类型的客户数量

题目：统计每种客户类型的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, COUNT(*) AS client_cnt FROM clients GROUP BY client_type;
```

### 113 找出所有夏普比率大于1的风险记录的计算日期

题目：找出所有夏普比率大于1的风险记录的计算日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_id, calc_date FROM risk_metrics WHERE sharp_ratio > 1;
```

### 114 列出所有交易类型为'买入'且状态为'已成'的交易流水号

题目：列出所有交易类型为'买入'且状态为'已成'的交易流水号，请输出对应SQL语句

参考 SQL：
```sql
SELECT transaction_id FROM transactions WHERE transaction_type = '买入' AND status = '已成';
```

### 115 查找客户经理表中管理资产总额最高的前5位经理的工号和姓名

题目：查找客户经理表中管理资产总额最高的前5位经理的工号和姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_code, manager_name FROM managers ORDER BY manage_assets_total DESC LIMIT 5;
```

### 116 找出每个客户名下资产规模最大的组合

题目：找出每个客户名下资产规模最大的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id, portfolio_id, portfolio_code, current_value FROM (SELECT c.client_id, p.portfolio_id, p.portfolio_code, p.current_value, ROW_NUMBER() OVER (PARTITION BY c.client_id ORDER BY p.current_value DESC) AS rn FROM clients c JOIN portfolios p ON c.client_id = p.client_id) t WHERE rn = 1;
```

### 117 计算每个产品被多少组合持有

题目：计算每个产品被多少组合持有，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, COUNT(DISTINCT portfolio_id) AS hold_cnt FROM holdings GROUP BY product_id;
```

### 118 找出每个客户经理管理的客户总资产

题目：找出每个客户经理管理的客户总资产，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, COALESCE(SUM(c.total_assets), 0) AS total_assets FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id GROUP BY m.manager_id, m.manager_name;
```

### 119 计算每个对手方的月均交易金额

题目：计算每个对手方的月均交易金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_id, SUM(transaction_amount) / COUNT(DISTINCT DATE_FORMAT(trade_date, '%Y-%m')) AS avg_month_amount FROM transactions GROUP BY counterparty_id;
```

### 120 找出最近30天内有交易的客户

题目：找出最近30天内有交易的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT c.client_id, c.client_name FROM clients c JOIN portfolios p ON c.client_id = p.client_id JOIN transactions t ON p.portfolio_id = t.portfolio_id WHERE t.trade_date >= CURDATE() - INTERVAL 30 DAY;
```

### 121 计算每个产品的累计交易金额

题目：计算每个产品的累计交易金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, SUM(transaction_amount) AS total_amount FROM transactions GROUP BY product_id;
```

### 122 找出每个部门绩效最好的客户经理

题目：找出每个部门绩效最好的客户经理，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id, manager_name, department_name, performance_score FROM (SELECT manager_id, manager_name, department_name, performance_score, ROW_NUMBER() OVER (PARTITION BY department_name ORDER BY performance_score DESC) AS rn FROM managers) t WHERE rn = 1;
```

### 123 计算每个组合的收益率

题目：计算每个组合的收益率，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_id, portfolio_code, (current_value - contribution_amount) / contribution_amount AS return_rate FROM portfolios WHERE contribution_amount > 0;
```

### 124 找出交易频率最高的前10个产品

题目：找出交易频率最高的前10个产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, COUNT(*) AS trade_cnt FROM transactions GROUP BY product_id ORDER BY trade_cnt DESC LIMIT 10;
```

### 125 计算每个客户类型的平均组合数量

题目：计算每个客户类型的平均组合数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, AVG(portfolio_cnt) AS avg_portfolio_cnt FROM (SELECT c.client_id, c.client_type, COUNT(p.portfolio_id) AS portfolio_cnt FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id, c.client_type) t GROUP BY client_type;
```

### 126 查每个客户名下有多少个投资组合

题目：查每个客户名下有多少个投资组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_id, c.client_name, COUNT(p.portfolio_id) AS portfolio_cnt FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id, c.client_name;
```

### 127 列出每位客户经理管理的客户总资产（仅正常状态客户）

题目：列出每位客户经理管理的客户总资产（仅正常状态客户），请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, COALESCE(SUM(c.total_assets), 0) AS total_assets FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id AND c.status = 1 GROUP BY m.manager_id, m.manager_name;
```

### 128 统计每类产品在过去一年的交易总额

题目：统计每类产品在过去一年的交易总额，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_type, SUM(t.transaction_amount) AS total_amount FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE t.trade_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) GROUP BY pr.product_type;
```

### 129 查出所有已成交的卖出交易及其对手方名称

题目：查出所有已成交的卖出交易及其对手方名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT t.transaction_id, t.transaction_type, cp.counterparty_name FROM transactions t JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id WHERE t.transaction_type = '卖出' AND t.status = '已成';
```

### 130 找出每个客户的风险等级和其最大回撤限制

题目：找出每个客户的风险等级和其最大回撤限制，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT c.client_id, c.risk_level, pf.max_drawdown_limit FROM clients c JOIN portfolios pf ON c.client_id = pf.client_id;
```

### 131 查出每个产品类型对应的平均管理费率

题目：查出每个产品类型对应的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(management_fee) AS avg_fee FROM products GROUP BY product_type;
```

### 132 找出所有智能投顾类型的组合及其创建人

题目：找出所有智能投顾类型的组合及其创建人，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_id, portfolio_code, create_user FROM portfolios WHERE portfolio_type = '智能投顾';
```

### 133 统计每位客户经理手下客户的平均资产规模

题目：统计每位客户经理手下客户的平均资产规模，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, AVG(c.total_assets) AS avg_client_assets FROM managers m JOIN clients c ON m.manager_id = c.manager_id GROUP BY m.manager_id, m.manager_name;
```

### 134 查出所有货币型产品在2025年的交易笔数

题目：查出所有货币型产品在2025年的交易笔数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS trade_cnt FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE pr.product_type = '货币型' AND YEAR(t.trade_date) = 2025;
```

### 135 列出所有未终止且当前市值低于累计投入的组合

题目：列出所有未终止且当前市值低于累计投入的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE termination_date IS NULL AND current_value < contribution_amount;
```

### 136 找出所有客户类型为'养老金'的组合代码

题目：找出所有客户类型为'养老金'的组合代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_code FROM clients c JOIN portfolios p ON c.client_id = p.client_id WHERE c.client_type = '养老金';
```

### 137 统计每个交易状态的交易总金额

题目：统计每个交易状态的交易总金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT status, SUM(transaction_amount) AS total_amount FROM transactions GROUP BY status;
```

### 138 列出所有风险评级为5的产品及其成立日期

题目：列出所有风险评级为5的产品及其成立日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_code, inception_date FROM products WHERE risk_rating = 5;
```

### 139 查出所有机构客户的注册日期和总资产

题目：查出所有机构客户的注册日期和总资产，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_code, client_name, register_date, total_assets FROM clients WHERE client_type = '机构';
```

### 140 列出所有全权委托组合的客户名称和目标收益率

题目：列出所有全权委托组合的客户名称和目标收益率，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_name, p.portfolio_code, p.target_return FROM clients c JOIN portfolios p ON c.client_id = p.client_id WHERE p.portfolio_type = '全权委托';
```

### 141 查出所有交易员ID为1001的交易记录

题目：查出所有交易员ID为1001的交易记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE trader_id = 1001;
```

### 142 统计每种客户类型的数量（仅正常状态）

题目：统计每种客户类型的数量（仅正常状态），请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, COUNT(*) AS client_cnt FROM clients WHERE status = 1 GROUP BY client_type;
```

### 143 列出所有对手方类型为'银行'的名称和信用评级

题目：列出所有对手方类型为'银行'的名称和信用评级，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_name, credit_rating FROM counterparties WHERE counterparty_type = '银行';
```

### 144 找出所有客户经理职级为'总监'的人数

题目：找出所有客户经理职级为'总监'的人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS manager_cnt FROM managers WHERE position_level = '总监';
```

### 145 列出所有2025年有交易记录的组合ID

题目：列出所有2025年有交易记录的组合ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT portfolio_id FROM transactions WHERE YEAR(trade_date) = 2025;
```

### 146 统计每个产品类型的风险评级平均值

题目：统计每个产品类型的风险评级平均值，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(risk_rating) AS avg_rating FROM products GROUP BY product_type;
```

### 147 列出所有QDII产品及其币种

题目：列出所有QDII产品及其币种，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, currency FROM products WHERE product_type = 'QDII';
```

### 148 查出所有交易状态为'部成'或'部撤'的记录

题目：查出所有交易状态为'部成'或'部撤'的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE status IN ('部成', '部撤');
```

### 149 找出所有客户类型为'家族信托'且风险等级为'平衡'的客户

题目：找出所有客户类型为'家族信托'且风险等级为'平衡'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_type = '家族信托' AND risk_level = '平衡';
```

### 150 列出所有成立日期早于2022年的组合

题目：列出所有成立日期早于2022年的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE inception_date < '2022-01-01';
```

### 151 查出所有业绩报酬比例大于0.1的产品

题目：查出所有业绩报酬比例大于0.1的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE performance_fee_rate > 0.1;
```

### 152 统计每个客户经理管理的组合数量

题目：统计每个客户经理管理的组合数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, COUNT(p.portfolio_id) AS portfolio_cnt FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY m.manager_id, m.manager_name;
```

### 153 列出所有流动性评分低于3的风险记录

题目：列出所有流动性评分低于3的风险记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM risk_metrics WHERE liquidity_score < 3;
```

### 154 查出所有客户资产为空的客户编码

题目：查出所有客户资产为空的客户编码，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_code FROM clients WHERE total_assets IS NULL;
```

### 155 列出所有产品类型为'另类投资'且风险评级为5的产品

题目：列出所有产品类型为'另类投资'且风险评级为5的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = '另类投资' AND risk_rating = 5;
```

### 156 统计每个客户类型下的平均风险等级（映射为数值）

题目：统计每个客户类型下的平均风险等级（映射为数值），请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, AVG(CASE risk_level WHEN '保守' THEN 1 WHEN '稳健' THEN 2 WHEN '平衡' THEN 3 WHEN '成长' THEN 4 WHEN '进取' THEN 5 END) AS avg_risk FROM clients GROUP BY client_type;
```

### 157 找出所有交易佣金超过1万的记录

题目：找出所有交易佣金超过1万的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE commission_fee > 10000;
```

### 158 列出所有已销户客户（status=3）的名称和销户前最后更新时间

题目：列出所有已销户客户（status=3）的名称和销户前最后更新时间，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, update_time FROM clients WHERE status = 3;
```

### 159 查出所有Beta系数大于1.2的组合风险记录

题目：查出所有Beta系数大于1.2的组合风险记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM risk_metrics WHERE beta > 1.2;
```

### 160 找出所有产品名称包含'科技'的产品

题目：找出所有产品名称包含'科技'的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_name LIKE '%科技%';
```

### 161 列出所有客户经理入职日期在2022年之后的姓名和部门

题目：列出所有客户经理入职日期在2022年之后的姓名和部门，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, department_name FROM managers WHERE hire_date > '2021-12-31';
```

### 162 查出所有交易类型为'分红'或'派息'的净额

题目：查出所有交易类型为'分红'或'派息'的净额，请输出对应SQL语句

参考 SQL：
```sql
SELECT net_amount FROM transactions WHERE transaction_type IN ('分红', '派息');
```

### 163 找出所有组合当前市值与累计投入比值小于0.8的记录

题目：找出所有组合当前市值与累计投入比值小于0.8的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE contribution_amount > 0 AND current_value / contribution_amount < 0.8;
```

### 164 列出所有对手方国家代码非中国的名称

题目：列出所有对手方国家代码非中国的名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_name FROM counterparties WHERE country_code <> 'CN';
```

### 165 查出所有产品配置中股票比例超过0.7的产品

题目：查出所有产品配置中股票比例超过0.7的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.equity')) AS DECIMAL(6,4)) > 0.7;
```

### 166 找出所有客户联系方式中的邮箱地址

题目：找出所有客户联系方式中的邮箱地址，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id, client_name, JSON_UNQUOTE(JSON_EXTRACT(contact_info, '$.email')) AS email FROM clients WHERE contact_info IS NOT NULL;
```

### 167 列出所有交易时间在下午3点后的成交记录

题目：列出所有交易时间在下午3点后的成交记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE status = '已成' AND TIME(trade_time) > '15:00:00';
```

### 168 查出所有最大回撤限制低于0.1的组合

题目：查出所有最大回撤限制低于0.1的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE max_drawdown_limit < 0.1;
```

### 169 找出所有客户类型为'个人'且风险等级为'进取'的客户

题目：找出所有客户类型为'个人'且风险等级为'进取'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE client_type = '个人' AND risk_level = '进取';
```

### 170 列出所有2025年11月的风险指标记录

题目：列出所有2025年11月的风险指标记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM risk_metrics WHERE DATE_FORMAT(calc_date, '%Y-%m') = '2025-11';
```

### 171 查出所有产品成立日期距今超过5年的产品

题目：查出所有产品成立日期距今超过5年的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE TIMESTAMPDIFF(YEAR, inception_date, CURDATE()) > 5;
```

### 172 列出所有客户经理管理资产总额超过10亿的记录

题目：列出所有客户经理管理资产总额超过10亿的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE manage_assets_total > 1000000000;
```

### 173 查出所有交易印花税大于0的卖出交易

题目：查出所有交易印花税大于0的卖出交易，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE transaction_type = '卖出' AND stamp_duty > 0;
```

### 174 找出所有组合类型为'投资顾问'且目标收益率高于0.1的组合

题目：找出所有组合类型为'投资顾问'且目标收益率高于0.1的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE portfolio_type = '投资顾问' AND target_return > 0.1;
```

### 175 列出所有信用评级为'D'的对手方

题目：列出所有信用评级为'D'的对手方，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE credit_rating = 'D';
```

### 176 查出所有客户注册月份为1月的客户数量

题目：查出所有客户注册月份为1月的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS client_cnt FROM clients WHERE MONTH(register_date) = 1;
```

### 177 找出所有风险预警（is_alert=true）的组合ID

题目：找出所有风险预警（is_alert=true）的组合ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT portfolio_id FROM risk_metrics WHERE is_alert = TRUE;
```

### 178 列出所有产品币种为USD的产品名称

题目：列出所有产品币种为USD的产品名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name FROM products WHERE currency = 'USD';
```

### 179 查出所有交易数量为0但交易金额不为0的异常记录

题目：查出所有交易数量为0但交易金额不为0的异常记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE transaction_quantity = 0 AND transaction_amount <> 0;
```

### 180 找出所有客户名称含'信托'的客户类型

题目：找出所有客户名称含'信托'的客户类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT client_type FROM clients WHERE client_name LIKE '%信托%';
```

### 181 列出所有2024年成立的组合

题目：列出所有2024年成立的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE YEAR(inception_date) = 2024;
```

### 182 查出所有产品类型为'债券型'且管理费率低于0.01的产品

题目：查出所有产品类型为'债券型'且管理费率低于0.01的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE product_type = '债券型' AND management_fee < 0.01;
```

### 183 找出所有客户经理上级ID为空的记录（即最高层）

题目：找出所有客户经理上级ID为空的记录（即最高层），请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM managers WHERE superior_id IS NULL;
```

### 184 列出所有交易状态为'已成'且交易类型为'申购'的记录

题目：列出所有交易状态为'已成'且交易类型为'申购'的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions WHERE status = '已成' AND transaction_type = '申购';
```

### 185 查出所有组合终止日期在2025年内终止的组合

题目：查出所有组合终止日期在2025年内终止的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE YEAR(termination_date) = 2025;
```

### 186 查出所有客户资产为负值的客户编码和名称

题目：查出所有客户资产为负值的客户编码和名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_code, client_name FROM clients WHERE total_assets < 0;
```

### 187 找出所有交易时间精确到微秒的最早10条记录

题目：找出所有交易时间精确到微秒的最早10条记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM transactions ORDER BY trade_time ASC LIMIT 10;
```

### 188 查出所有客户联系方式中电话号码包含'138'的客户

题目：查出所有客户联系方式中电话号码包含'138'的客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE contact_info LIKE '%138%';
```

### 189 找出所有组合创建时间在上午9点前的记录

题目：找出所有组合创建时间在上午9点前的记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM portfolios WHERE TIME(create_time) < '09:00:00';
```

### 190 列出每位客户的名字以及他们对应的客户经理名字

题目：列出每位客户的名字以及他们对应的客户经理名字，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_name, m.manager_name FROM clients c LEFT JOIN managers m ON c.manager_id = m.manager_id;
```

### 191 计算每个客户类型的平均总资产规模

题目：计算每个客户类型的平均总资产规模，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, AVG(total_assets) AS avg_assets FROM clients GROUP BY client_type;
```

### 192 列出所有在2024年有过交易记录的投资组合代码

题目：列出所有在2024年有过交易记录的投资组合代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.portfolio_code FROM portfolios p JOIN transactions t ON p.portfolio_id = t.portfolio_id WHERE YEAR(t.trade_date) = 2024;
```

### 193 找出每个产品类型的平均管理费率

题目：找出每个产品类型的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(management_fee) AS avg_fee FROM products GROUP BY product_type;
```

### 194 列出所有发生过'买入'交易的产品名称和交易日期

题目：列出所有发生过'买入'交易的产品名称和交易日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_name, t.trade_date FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE t.transaction_type = '买入';
```

### 195 统计每个部门的客户经理人数

题目：统计每个部门的客户经理人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_name, COUNT(*) AS manager_cnt FROM managers GROUP BY department_name;
```

### 196 找出所有客户风险等级为'稳健'且其投资组合目标收益率高于8%的组合代码

题目：找出所有客户风险等级为'稳健'且其投资组合目标收益率高于8%的组合代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_code FROM clients c JOIN portfolios p ON c.client_id = p.client_id WHERE c.risk_level = '稳健' AND p.target_return > 0.08;
```

### 197 列出所有在'风险管理部'工作的客户经理姓名及其绩效评分

题目：列出所有在'风险管理部'工作的客户经理姓名及其绩效评分，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, performance_score FROM managers WHERE department_name = '风险管理部';
```

### 198 显示所有交易金额大于10万元且状态为'已成'的交易ID和净额

题目：显示所有交易金额大于10万元且状态为'已成'的交易ID和净额，请输出对应SQL语句

参考 SQL：
```sql
SELECT transaction_id, net_amount FROM transactions WHERE transaction_amount > 100000 AND status = '已成';
```

### 199 找出所有客户经理管理的客户总数超过50人的经理姓名

题目：找出所有客户经理管理的客户总数超过50人的经理姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name FROM managers WHERE client_count > 50;
```

### 200 列出所有成立时间超过5年且仍处于激活状态的对手方名称和类型

题目：列出所有成立时间超过5年且仍处于激活状态的对手方名称和类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_name, counterparty_type FROM counterparties WHERE TIMESTAMPDIFF(YEAR, establish_date, CURDATE()) > 5 AND is_active = 1;
```

### 201 查询每个客户的风险等级分布情况（即每种风险等级有多少客户）

题目：查询每个客户的风险等级分布情况（即每种风险等级有多少客户），请输出对应SQL语句

参考 SQL：
```sql
SELECT risk_level, COUNT(*) AS client_cnt FROM clients GROUP BY risk_level;
```

### 202 列出所有客户类型为'机构'且总资产大于1亿元的客户名称和总资产，并按总资产降序排列

题目：列出所有客户类型为'机构'且总资产大于1亿元的客户名称和总资产，并按总资产降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, total_assets FROM clients WHERE client_type = '机构' AND total_assets > 100000000 ORDER BY total_assets DESC;
```

### 203 显示所有交易类型为'分红'或'派息'的交易涉及的产品名称和总金额

题目：显示所有交易类型为'分红'或'派息'的交易涉及的产品名称和总金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_name, SUM(t.transaction_amount) AS total_amount FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE t.transaction_type IN ('分红', '派息') GROUP BY pr.product_name;
```

### 204 查询每个投资组合类型的平均当前市值

题目：查询每个投资组合类型的平均当前市值，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_type, AVG(current_value) AS avg_value FROM portfolios GROUP BY portfolio_type;
```

### 205 找出所有客户经理中绩效评分最高的前三名的姓名和分数

题目：找出所有客户经理中绩效评分最高的前三名的姓名和分数，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, performance_score FROM managers ORDER BY performance_score DESC LIMIT 3;
```

### 206 查询所有在2024年有交易记录但没有持仓记录的投资组合ID

题目：查询所有在2024年有交易记录但没有持仓记录的投资组合ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT t.portfolio_id FROM transactions t WHERE YEAR(t.trade_date) = 2024 AND t.portfolio_id NOT IN (SELECT DISTINCT portfolio_id FROM holdings);
```

### 207 显示所有产品风险评级为5级且管理费率低于0.02的产品名称和费率

题目：显示所有产品风险评级为5级且管理费率低于0.02的产品名称和费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, management_fee FROM products WHERE risk_rating = 5 AND management_fee < 0.02;
```

### 208 查询每个币种的产品数量

题目：查询每个币种的产品数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT currency, COUNT(*) AS product_cnt FROM products GROUP BY currency;
```

### 209 找出所有客户经理入职日期在2022年之后且职级为'经理'或'高级经理'的人员姓名和部门

题目：找出所有客户经理入职日期在2022年之后且职级为'经理'或'高级经理'的人员姓名和部门，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, department_name FROM managers WHERE hire_date > '2021-12-31' AND position_level IN ('经理', '高级经理');
```

### 210 显示所有交易对手方国家代码不是'CN'的对手方名称和信用评级

题目：显示所有交易对手方国家代码不是'CN'的对手方名称和信用评级，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_name, credit_rating FROM counterparties WHERE country_code <> 'CN';
```

### 211 查询所有投资组合中，目标收益率与最大回撤限制之比最高的组合代码和该比率值

题目：查询所有投资组合中，目标收益率与最大回撤限制之比最高的组合代码和该比率值，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_code, target_return / max_drawdown_limit AS ratio FROM portfolios WHERE max_drawdown_limit > 0 ORDER BY ratio DESC LIMIT 1;
```

### 212 找出所有客户经理上级ID不为空的经理姓名及其上级经理姓名

题目：找出所有客户经理上级ID不为空的经理姓名及其上级经理姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, s.manager_name AS superior_name FROM managers m JOIN managers s ON m.superior_id = s.manager_id WHERE m.superior_id IS NOT NULL;
```

### 213 查询所有在2025年有过至少一笔'卖出'交易的投资组合ID和交易日期

题目：查询所有在2025年有过至少一笔'卖出'交易的投资组合ID和交易日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT t.portfolio_id, t.trade_date FROM transactions t WHERE t.transaction_type = '卖出' AND YEAR(t.trade_date) = 2025;
```

### 214 显示所有产品中，资产配置里股票比例超过70%的产品名称和该比例

题目：显示所有产品中，资产配置里股票比例超过70%的产品名称和该比例，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.equity')) AS DECIMAL(6,4)) AS equity_ratio FROM products WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(asset_allocation, '$.equity')) AS DECIMAL(6,4)) > 0.7;
```

### 215 列出所有客户状态为'冻结'或'销户'的客户ID和名称

题目：列出所有客户状态为'冻结'或'销户'的客户ID和名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id, client_name FROM clients WHERE status IN (2, 3);
```

### 216 查询所有交易时间为上午（9点到12点之间）的交易ID和时间

题目：查询所有交易时间为上午（9点到12点之间）的交易ID和时间，请输出对应SQL语句

参考 SQL：
```sql
SELECT transaction_id, trade_time FROM transactions WHERE TIME(trade_time) BETWEEN '09:00:00' AND '12:00:00';
```

### 217 找出所有客户经理管理资产总额排名前10%的经理ID和姓名

题目：找出所有客户经理管理资产总额排名前10%的经理ID和姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id, manager_name FROM (SELECT manager_id, manager_name, PERCENT_RANK() OVER (ORDER BY manage_assets_total DESC) AS pr FROM managers) t WHERE pr <= 0.1;
```

### 218 显示所有产品中，业绩报酬比例不为0的产品名称和该比例

题目：显示所有产品中，业绩报酬比例不为0的产品名称和该比例，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, performance_fee_rate FROM products WHERE performance_fee_rate <> 0;
```

### 219 查询每个客户拥有的投资组合数量，并筛选出拥有超过2个组合的客户ID

题目：查询每个客户拥有的投资组合数量，并筛选出拥有超过2个组合的客户ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id FROM (SELECT c.client_id, COUNT(p.portfolio_id) AS portfolio_cnt FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id) t WHERE portfolio_cnt > 2;
```

### 220 查询所有交易对手方注册资本大于10亿人民币的对手方名称和资本额

题目：查询所有交易对手方注册资本大于10亿人民币的对手方名称和资本额，请输出对应SQL语句

参考 SQL：
```sql
SELECT counterparty_name, registered_capital FROM counterparties WHERE registered_capital > 1000000000;
```

### 221 显示所有产品中，基准指数为'沪深300'的产品名称和类型

题目：显示所有产品中，基准指数为'沪深300'的产品名称和类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, product_type FROM products WHERE benchmark_index = '沪深300';
```

### 222 列出所有在2024年全年都没有任何交易记录的投资组合ID

题目：列出所有在2024年全年都没有任何交易记录的投资组合ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_id FROM portfolios p WHERE NOT EXISTS (SELECT 1 FROM transactions t WHERE t.portfolio_id = p.portfolio_id AND YEAR(t.trade_date) = 2024);
```

### 223 查询每个产品类型的平均风险评级

题目：查询每个产品类型的平均风险评级，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(risk_rating) AS avg_rating FROM products GROUP BY product_type;
```

### 224 查询所有交易中，佣金费用占成交金额比例最高的前5笔交易ID和该比例

题目：查询所有交易中，佣金费用占成交金额比例最高的前5笔交易ID和该比例，请输出对应SQL语句

参考 SQL：
```sql
SELECT transaction_id, commission_fee / transaction_amount AS ratio FROM transactions WHERE transaction_amount > 0 ORDER BY ratio DESC LIMIT 5;
```

### 225 列出所有客户中，注册日期最早的前10位客户姓名和注册日期

题目：列出所有客户中，注册日期最早的前10位客户姓名和注册日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, register_date FROM clients ORDER BY register_date ASC LIMIT 10;
```

### 226 找出所有产品中，在2022年成立的QDII类产品名称和成立日期

题目：找出所有产品中，在2022年成立的QDII类产品名称和成立日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, inception_date FROM products WHERE YEAR(inception_date) = 2022 AND product_type = 'QDII';
```

### 227 找出所有客户经理中，绩效评分低于80分的人数

题目：找出所有客户经理中，绩效评分低于80分的人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS manager_cnt FROM managers WHERE performance_score < 80;
```

### 228 列出所有在2024年12月发生过交易且交易对手方类型为'银行'的交易ID和对手方名称

题目：列出所有在2024年12月发生过交易且交易对手方类型为'银行'的交易ID和对手方名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT t.transaction_id, cp.counterparty_name FROM transactions t JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id WHERE DATE_FORMAT(t.trade_date, '%Y-%m') = '2024-12' AND cp.counterparty_type = '银行';
```

### 229 查询所有投资组合中，当前市值与累计投入金额之比（即收益率+1）最高的组合代码和该比率

题目：查询所有投资组合中，当前市值与累计投入金额之比（即收益率+1）最高的组合代码和该比率，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_code, current_value / contribution_amount AS ratio FROM portfolios WHERE contribution_amount > 0 ORDER BY ratio DESC LIMIT 1;
```

### 230 找出所有客户中，联系信息里的地址包含'北京'关键字的客户姓名

题目：找出所有客户中，联系信息里的地址包含'北京'关键字的客户姓名，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name FROM clients WHERE contact_info LIKE '%北京%';
```

### 231 找出所有客户经理中绩效评分最高的前三名的姓名和分数。 (变体 91)

题目：找出所有客户经理中绩效评分最高的前三名的姓名和分数。 (变体 91)，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, performance_score FROM managers ORDER BY performance_score DESC LIMIT 3;
```

### 232 麻烦列出所有在'风险管理部'工作的客户经理姓名及其绩效评分。 (变体 92)

题目：麻烦列出所有在'风险管理部'工作的客户经理姓名及其绩效评分。 (变体 92)，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, performance_score FROM managers WHERE department_name = '风险管理部';
```

### 233 找出所有产品中，在2022年成立的QDII类产品名称和成立日期。 (变体 93)

题目：找出所有产品中，在2022年成立的QDII类产品名称和成立日期。 (变体 93)，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, inception_date FROM products WHERE YEAR(inception_date) = 2022 AND product_type = 'QDII';
```

### 234 找出所有客户经理入职日期在2022年之后且职级为'经理'或'高级经理'的人员姓名和部门。 (变体 94)

题目：找出所有客户经理入职日期在2022年之后且职级为'经理'或'高级经理'的人员姓名和部门。 (变体 94)，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, department_name FROM managers WHERE hire_date > '2021-12-31' AND position_level IN ('经理', '高级经理');
```

### 235 请显示所有交易金额大于10万元且状态为'已成'的交易ID和净额。 (变体 95)

题目：请显示所有交易金额大于10万元且状态为'已成'的交易ID和净额。 (变体 95)，请输出对应SQL语句

参考 SQL：
```sql
SELECT transaction_id, net_amount FROM transactions WHERE transaction_amount > 100000 AND status = '已成';
```

### 236 找出所有客户经理上级ID不为空的经理姓名及其上级经理姓名。 (变体 97)

题目：找出所有客户经理上级ID不为空的经理姓名及其上级经理姓名。 (变体 97)，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, s.manager_name AS superior_name FROM managers m JOIN managers s ON m.superior_id = s.manager_id WHERE m.superior_id IS NOT NULL;
```

### 237 找出所有客户经理管理资产总额排名前10%的经理ID和姓名。 (变体 98)

题目：找出所有客户经理管理资产总额排名前10%的经理ID和姓名。 (变体 98)，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id, manager_name FROM (SELECT manager_id, manager_name, PERCENT_RANK() OVER (ORDER BY manage_assets_total DESC) AS pr FROM managers) t WHERE pr <= 0.1;
```

### 238 列出所有客户经理及其所属部门的名称

题目：列出所有客户经理及其所属部门的名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_name, department_name FROM managers;
```

### 239 找出每个客户的第一个投资组合的代码和成立日期

题目：找出每个客户的第一个投资组合的代码和成立日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_id, portfolio_id, portfolio_code, inception_date FROM (SELECT client_id, portfolio_id, portfolio_code, inception_date, ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY inception_date ASC, portfolio_id ASC) AS rn FROM portfolios) t WHERE rn = 1;
```

### 240 统计每个产品类型的平均管理费率

题目：统计每个产品类型的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_type, AVG(management_fee) AS avg_fee FROM products GROUP BY product_type;
```

### 241 找出所有交易金额超过100000的买入交易，并显示其组合代码和交易日期

题目：找出所有交易金额超过100000的买入交易，并显示其组合代码和交易日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_code, t.trade_date FROM transactions t JOIN portfolios p ON t.portfolio_id = p.portfolio_id WHERE t.transaction_amount > 100000 AND t.transaction_type = '买入';
```

### 242 统计每个客户经理管理的客户总数

题目：统计每个客户经理管理的客户总数，请输出对应SQL语句

参考 SQL：
```sql
SELECT manager_id, manager_name, client_count AS total_client_cnt FROM managers;
```

### 243 列出所有触发了预警的风险记录对应的组合代码和计算日期

题目：列出所有触发了预警的风险记录对应的组合代码和计算日期，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.portfolio_code, rm.calc_date FROM risk_metrics rm JOIN portfolios p ON rm.portfolio_id = p.portfolio_id WHERE rm.is_alert = TRUE;
```

### 244 找出所有在2024年有过交易的组合代码

题目：找出所有在2024年有过交易的组合代码，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.portfolio_code FROM portfolios p JOIN transactions t ON p.portfolio_id = t.portfolio_id WHERE YEAR(t.trade_date) = 2024;
```

### 245 列出所有债券型产品及其基准指数

题目：列出所有债券型产品及其基准指数，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_name, benchmark_index FROM products WHERE product_type = '债券型';
```

### 246 统计每个对手方类型的交易次数

题目：统计每个对手方类型的交易次数，请输出对应SQL语句

参考 SQL：
```sql
SELECT cp.counterparty_type, COUNT(t.transaction_id) AS trade_cnt FROM transactions t JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id GROUP BY cp.counterparty_type;
```

### 247 列出所有个人客户的姓名和联系方式（电话号码）

题目：列出所有个人客户的姓名和联系方式（电话号码），请输出对应SQL语句

参考 SQL：
```sql
SELECT client_name, JSON_UNQUOTE(JSON_EXTRACT(contact_info, '$.phone')) AS phone FROM clients WHERE client_type = '个人';
```

### 248 统计每种客户类型的客户数量

题目：统计每种客户类型的客户数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, COUNT(*) AS client_cnt FROM clients GROUP BY client_type;
```

### 249 找出所有在2023年注册且状态为正常的客户信息

题目：找出所有在2023年注册且状态为正常的客户信息，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM clients WHERE YEAR(register_date) = 2023 AND status = 1;
```

### 250 列出所有已终止的投资组合（显示组合代码、客户ID和终止日期）

题目：列出所有已终止的投资组合（显示组合代码、客户ID和终止日期），请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_code, client_id, termination_date FROM portfolios WHERE termination_date IS NOT NULL;
```

### 251 计算每个产品的平均管理费率

题目：计算每个产品的平均管理费率，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, AVG(management_fee) AS avg_fee FROM products GROUP BY product_id;
```

### 252 找出所有风险评级为5级的有效产品

题目：找出所有风险评级为5级的有效产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM products WHERE risk_rating = 5 AND is_active = 1;
```

### 253 查询所有“银行”类型的对手方，并按注册资本降序排列

题目：查询所有“银行”类型的对手方，并按注册资本降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT * FROM counterparties WHERE counterparty_type = '银行' ORDER BY registered_capital DESC;
```

### 254 统计每个部门的客户经理人数

题目：统计每个部门的客户经理人数，请输出对应SQL语句

参考 SQL：
```sql
SELECT department_name, COUNT(*) AS manager_cnt FROM managers GROUP BY department_name;
```

### 255 找出所有夏普比率大于1的投资组合，并显示其当前市值和创建用户

题目：找出所有夏普比率大于1的投资组合，并显示其当前市值和创建用户，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_id, p.current_value, p.create_user FROM portfolios p JOIN risk_metrics rm ON p.portfolio_id = rm.portfolio_id WHERE rm.sharp_ratio > 1;
```

### 256 找出每个客户风险等级下，最大回撤超过其组合限制的组合

题目：找出每个客户风险等级下，最大回撤超过其组合限制的组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_id, c.risk_level, p.portfolio_code FROM clients c JOIN portfolios p ON c.client_id = p.client_id JOIN risk_metrics rm ON p.portfolio_id = rm.portfolio_id WHERE rm.max_drawdown > p.max_drawdown_limit;
```

### 257 统计每个部门的客户经理所管理客户的总交易金额

题目：统计每个部门的客户经理所管理客户的总交易金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.department_name, COALESCE(SUM(t.transaction_amount), 0) AS total_amount FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id LEFT JOIN portfolios p ON c.client_id = p.client_id LEFT JOIN transactions t ON p.portfolio_id = t.portfolio_id GROUP BY m.department_name;
```

### 258 找出所有在2025年Q3有交易、但当前无持仓的产品

题目：找出所有在2025年Q3有交易、但当前无持仓的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT t.product_id FROM transactions t WHERE t.trade_date BETWEEN '2025-07-01' AND '2025-09-30' AND t.product_id NOT IN (SELECT DISTINCT product_id FROM holdings);
```

### 259 找出所有客户-组合-交易-对手方链条中，对手方信用评级为'D'的交易记录

题目：找出所有客户-组合-交易-对手方链条中，对手方信用评级为'D'的交易记录，请输出对应SQL语句

参考 SQL：
```sql
SELECT t.transaction_id, cp.counterparty_name FROM clients c JOIN portfolios p ON c.client_id = p.client_id JOIN transactions t ON p.portfolio_id = t.portfolio_id JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id WHERE cp.credit_rating = 'D';
```

### 260 列出每个客户的名字、风险等级以及他们持有的所有投资组合的总当前市值，并按总市值降序排列

题目：列出每个客户的名字、风险等级以及他们持有的所有投资组合的总当前市值，并按总市值降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_name, c.risk_level, COALESCE(SUM(p.current_value), 0) AS total_value FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id, c.client_name, c.risk_level ORDER BY total_value DESC;
```

### 261 查询每个客户经理管理的所有客户在2024年的总交易金额（买入+卖出）

题目：查询每个客户经理管理的所有客户在2024年的总交易金额（买入+卖出），请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, COALESCE(SUM(t.transaction_amount), 0) AS total_amount FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id LEFT JOIN portfolios p ON c.client_id = p.client_id LEFT JOIN transactions t ON p.portfolio_id = t.portfolio_id AND YEAR(t.trade_date) = 2024 GROUP BY m.manager_id, m.manager_name;
```

### 262 找出每个客户类型下，平均单个投资组合的当前市值，并筛选出平均市值最高的客户类型

题目：找出每个客户类型下，平均单个投资组合的当前市值，并筛选出平均市值最高的客户类型，请输出对应SQL语句

参考 SQL：
```sql
SELECT client_type, AVG(value_per_portfolio) AS avg_value FROM (SELECT c.client_type, p.current_value AS value_per_portfolio FROM clients c JOIN portfolios p ON c.client_id = p.client_id) t GROUP BY client_type ORDER BY avg_value DESC LIMIT 1;
```

### 263 查询所有在2024年有交易记录且其交易对手方信用评级低于'A'的投资组合代码和对手方名称

题目：查询所有在2024年有交易记录且其交易对手方信用评级低于'A'的投资组合代码和对手方名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT DISTINCT p.portfolio_code, cp.counterparty_name FROM portfolios p JOIN transactions t ON p.portfolio_id = t.portfolio_id JOIN counterparties cp ON t.counterparty_id = cp.counterparty_id WHERE YEAR(t.trade_date) = 2024 AND cp.credit_rating < 'A';
```

### 264 列出所有客户经理姓名、部门以及他们管理的客户中风险等级为'进取'的客户数量，按数量降序排列

题目：列出所有客户经理姓名、部门以及他们管理的客户中风险等级为'进取'的客户数量，按数量降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, m.department_name, COUNT(c.client_id) AS aggressive_client_cnt FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id AND c.risk_level = '进取' GROUP BY m.manager_id, m.manager_name, m.department_name ORDER BY aggressive_client_cnt DESC;
```

### 265 查询每个产品类型的平均30天滚动交易金额（买入+卖出），并按平均金额降序排列

题目：查询每个产品类型的平均30天滚动交易金额（买入+卖出），并按平均金额降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_type, AVG(t.transaction_amount) AS avg_amount FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE t.trade_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY pr.product_type ORDER BY avg_amount DESC;
```

### 266 列出所有客户中，在2024年有交易但在2025年没有交易的客户姓名和ID

题目：列出所有客户中，在2024年有交易但在2025年没有交易的客户姓名和ID，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_id, c.client_name FROM clients c WHERE EXISTS (SELECT 1 FROM portfolios p JOIN transactions t ON p.portfolio_id = t.portfolio_id WHERE p.client_id = c.client_id AND YEAR(t.trade_date) = 2024) AND NOT EXISTS (SELECT 1 FROM portfolios p JOIN transactions t ON p.portfolio_id = t.portfolio_id WHERE p.client_id = c.client_id AND YEAR(t.trade_date) = 2025);
```

### 267 列出所有客户经理姓名、职级以及他们管理的客户在2024年的总佣金收入（所有交易的佣金费总和）

题目：列出所有客户经理姓名、职级以及他们管理的客户在2024年的总佣金收入（所有交易的佣金费总和），请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, m.position_level, COALESCE(SUM(t.commission_fee), 0) AS total_commission FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id LEFT JOIN portfolios p ON c.client_id = p.client_id LEFT JOIN transactions t ON p.portfolio_id = t.portfolio_id AND YEAR(t.trade_date) = 2024 GROUP BY m.manager_id, m.manager_name, m.position_level;
```

### 268 查询每个部门管理的客户总资产规模总和，并按总规模降序排列

题目：查询每个部门管理的客户总资产规模总和，并按总规模降序排列，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.department_name, COALESCE(SUM(c.total_assets), 0) AS total_assets FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id GROUP BY m.department_name ORDER BY total_assets DESC;
```

### 269 列出所有在2024年有'买入'交易且在2025年有'卖出'同一产品的客户姓名和产品名称

题目：列出所有在2024年有'买入'交易且在2025年有'卖出'同一产品的客户姓名和产品名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_name, pr.product_name FROM clients c JOIN portfolios p ON c.client_id = p.client_id JOIN transactions t1 ON p.portfolio_id = t1.portfolio_id AND t1.transaction_type = '买入' AND YEAR(t1.trade_date) = 2024 JOIN transactions t2 ON p.portfolio_id = t2.portfolio_id AND t2.transaction_type = '卖出' AND YEAR(t2.trade_date) = 2025 AND t2.product_id = t1.product_id JOIN products pr ON t1.product_id = pr.product_id;
```

### 270 查询所有投资组合中，其最大回撤（从风险指标表获取）超过其设定的最大回撤限制的投资组合代码、实际最大回撤和限制值

题目：查询所有投资组合中，其最大回撤（从风险指标表获取）超过其设定的最大回撤限制的投资组合代码、实际最大回撤和限制值，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_code, rm.max_drawdown, p.max_drawdown_limit FROM portfolios p JOIN risk_metrics rm ON p.portfolio_id = rm.portfolio_id WHERE rm.max_drawdown > p.max_drawdown_limit;
```

### 271 列出所有客户经理姓名、职级以及他们管理的客户在2024年的总佣金收入（所有交易的佣金费总和）。 (变体 100)

题目：列出所有客户经理姓名、职级以及他们管理的客户在2024年的总佣金收入（所有交易的佣金费总和）。 (变体 100)，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, m.position_level, COALESCE(SUM(t.commission_fee), 0) AS total_commission FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id LEFT JOIN portfolios p ON c.client_id = p.client_id LEFT JOIN transactions t ON p.portfolio_id = t.portfolio_id AND YEAR(t.trade_date) = 2024 GROUP BY m.manager_id, m.manager_name, m.position_level;
```

### 272 查询每个客户的风险等级以及他们拥有的投资组合数量

题目：查询每个客户的风险等级以及他们拥有的投资组合数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_id, c.risk_level, COUNT(p.portfolio_id) AS portfolio_cnt FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id, c.risk_level;
```

### 273 找出每个客户经理管理的所有客户的总资产规模之和，并按总规模降序排列，只显示前10名

题目：找出每个客户经理管理的所有客户的总资产规模之和，并按总规模降序排列，只显示前10名，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, COALESCE(SUM(c.total_assets), 0) AS total_assets FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id GROUP BY m.manager_id, m.manager_name ORDER BY total_assets DESC LIMIT 10;
```

### 274 列出所有在2024年有过交易记录的投资组合代码、客户名称和交易总金额

题目：列出所有在2024年有过交易记录的投资组合代码、客户名称和交易总金额，请输出对应SQL语句

参考 SQL：
```sql
SELECT p.portfolio_code, c.client_name, SUM(t.transaction_amount) AS total_amount FROM transactions t JOIN portfolios p ON t.portfolio_id = p.portfolio_id JOIN clients c ON p.client_id = c.client_id WHERE YEAR(t.trade_date) = 2024 GROUP BY p.portfolio_code, c.client_name;
```

### 275 找出每个客户经理所管理的客户中，单个客户总资产最高的客户名称和资产规模

题目：找出每个客户经理所管理的客户中，单个客户总资产最高的客户名称和资产规模，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, c.client_name, c.total_assets FROM managers m LEFT JOIN clients c ON m.manager_id = c.manager_id AND c.total_assets = (SELECT MAX(c2.total_assets) FROM clients c2 WHERE c2.manager_id = m.manager_id);
```

### 276 统计2024年每个季度各类产品类型的交易净额（买入金额-卖出金额），并按产品类型和季度排序

题目：统计2024年每个季度各类产品类型的交易净额（买入金额-卖出金额），并按产品类型和季度排序，请输出对应SQL语句

参考 SQL：
```sql
SELECT pr.product_type, QUARTER(t.trade_date) AS q, SUM(CASE WHEN t.transaction_type = '买入' THEN t.net_amount ELSE 0 END) - SUM(CASE WHEN t.transaction_type = '卖出' THEN t.net_amount ELSE 0 END) AS net_amount FROM transactions t JOIN products pr ON t.product_id = pr.product_id WHERE YEAR(t.trade_date) = 2024 GROUP BY pr.product_type, QUARTER(t.trade_date) ORDER BY pr.product_type, q;
```

### 277 查询所有处于预警状态（is_alert=TRUE）的投资组合的客户名称、组合代码以及最新的最大回撤值

题目：查询所有处于预警状态（is_alert=TRUE）的投资组合的客户名称、组合代码以及最新的最大回撤值，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_name, p.portfolio_code, rm.max_drawdown AS latest_max_drawdown FROM risk_metrics rm JOIN portfolios p ON rm.portfolio_id = p.portfolio_id JOIN clients c ON p.client_id = c.client_id WHERE rm.is_alert = TRUE AND rm.calc_date = (SELECT MAX(calc_date) FROM risk_metrics WHERE portfolio_id = rm.portfolio_id AND is_alert = TRUE);
```

### 278 列出所有客户经理及其直接上级经理的姓名。如果上级是总经理，则显示部门名称

题目：列出所有客户经理及其直接上级经理的姓名。如果上级是总经理，则显示部门名称，请输出对应SQL语句

参考 SQL：
```sql
SELECT m.manager_name, CASE WHEN s.position_level = '总经理' THEN s.department_name ELSE s.manager_name END AS superior_info FROM managers m LEFT JOIN managers s ON m.superior_id = s.manager_id;
```

### 279 查询每个客户的总资产（来自clients表）与其所有投资组合的当前总市值（来自portfolios表）之间的差额，并找出差额绝对值最大的前5个客户

题目：查询每个客户的总资产（来自clients表）与其所有投资组合的当前总市值（来自portfolios表）之间的差额，并找出差额绝对值最大的前5个客户，请输出对应SQL语句

参考 SQL：
```sql
SELECT c.client_id, c.client_name, c.total_assets - COALESCE(SUM(p.current_value), 0) AS diff FROM clients c LEFT JOIN portfolios p ON c.client_id = p.client_id GROUP BY c.client_id, c.client_name, c.total_assets ORDER BY ABS(c.total_assets - COALESCE(SUM(p.current_value), 0)) DESC LIMIT 5;
```

### 280 找出管理费率最低的在售产品

题目：找出当前在售产品中管理费率最低的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_code, product_name, product_type, risk_rating, management_fee
FROM financial_asset_management.products
WHERE is_active = 1
ORDER BY management_fee ASC
LIMIT 1;
```

### 281 列出业绩提成比例最高的前5个在售产品

题目：列出业绩提成比例（performance_fee_rate）最高的前5个在售产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_code, product_name, product_type, performance_fee_rate
FROM financial_asset_management.products
WHERE is_active = 1
ORDER BY performance_fee_rate DESC
LIMIT 5;
```

### 282 找出风险评级最低的在售产品

题目：找出当前在售产品中风险评级（risk_rating，1最低）最低的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_code, product_name, product_type, risk_rating, management_fee
FROM financial_asset_management.products
WHERE is_active = 1
ORDER BY risk_rating ASC, management_fee ASC
LIMIT 1;
```

### 283 找出管理费率最高的在售产品

题目：找出当前在售产品中管理费率最高的产品，请输出对应SQL语句

参考 SQL：
```sql
SELECT product_id, product_code, product_name, product_type, management_fee
FROM financial_asset_management.products
WHERE is_active = 1
ORDER BY management_fee DESC
LIMIT 1;
```

### 284 统计在售高风险产品的数量

题目：统计当前在售产品中风险评级（risk_rating）为5级的产品数量，请输出对应SQL语句

参考 SQL：
```sql
SELECT COUNT(*) AS high_risk_cnt
FROM financial_asset_management.products
WHERE is_active = 1 AND risk_rating = 5;
```

### 285 找出亏损金额最大的前5个投资组合

题目：找出未终止的投资组合中当前市值低于累计投入、亏损金额最大的前5个组合，请输出对应SQL语句

参考 SQL：
```sql
SELECT portfolio_code, client_id, current_value, contribution_amount,
       ROUND(contribution_amount - current_value, 2) AS loss_amount
FROM financial_asset_management.portfolios
WHERE termination_date IS NULL AND current_value < contribution_amount
ORDER BY loss_amount DESC
LIMIT 5;
```

### 286 统计2024年每个月的交易笔数和成交总额

题目：按月份统计2024年每个月的交易笔数和成交总额，请输出对应SQL语句

参考 SQL：
```sql
SELECT LEFT(trade_date, 7) AS ym,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions
WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'
GROUP BY LEFT(trade_date, 7)
ORDER BY ym;
```

### 287 哪个客户经理手下的客户最有钱

题目：按客户经理分组，统计其名下状态为正常的客户人数，以及这些客户 total_assets（总资产）的合计，按合计金额从高到低取前10名客户经理。口径：只统计 status=1（正常）且 total_assets 非空的客户，输出经理姓名、所属部门。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, m.department_name,
       COUNT(c.client_id) AS client_cnt,
       ROUND(SUM(c.total_assets), 2) AS clients_assets_sum
FROM financial_asset_management.managers m
JOIN financial_asset_management.clients c ON c.manager_id = m.manager_id
WHERE c.status = 1 AND c.total_assets IS NOT NULL
GROUP BY m.manager_id, m.manager_name, m.department_name
ORDER BY clients_assets_sum DESC
LIMIT 10;
```

### 288 统计各产品类型的持仓市值与浮动盈亏

题目：把持仓表 holdings 与产品表 products 关联，按产品类型（product_type）汇总：涉及多少投资组合、多少条持仓记录、持仓市值 market_value 合计、浮动盈亏 unrealized_pnl 合计，按持仓市值合计降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.product_type,
       COUNT(DISTINCT h.portfolio_id) AS portfolio_cnt,
       COUNT(*) AS holding_cnt,
       ROUND(SUM(h.market_value), 2) AS market_value_sum,
       ROUND(SUM(h.unrealized_pnl), 2) AS unrealized_pnl_sum
FROM financial_asset_management.holdings h
JOIN financial_asset_management.products p ON p.product_id = h.product_id
GROUP BY p.product_type
ORDER BY market_value_sum DESC;
```

### 289 查询未终止组合中持仓市值最高的10条客户持仓明细

题目：关联 clients、portfolios、holdings、products 四张表，列出未终止组合（termination_date IS NULL）中持仓市值最高的10条记录，输出客户名称、组合代码、产品名称、产品类型、持仓市值和浮动盈亏。请输出对应SQL语句。

参考 SQL：
```sql
SELECT c.client_code, c.client_name, pf.portfolio_code,
       p.product_name, p.product_type,
       ROUND(h.market_value, 2) AS market_value,
       ROUND(h.unrealized_pnl, 2) AS unrealized_pnl
FROM financial_asset_management.holdings h
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = h.portfolio_id
JOIN financial_asset_management.clients c ON c.client_id = pf.client_id
JOIN financial_asset_management.products p ON p.product_id = h.product_id
WHERE pf.termination_date IS NULL
ORDER BY h.market_value DESC
LIMIT 10;
```

### 290 按交易对手方信用评级统计2024年交易规模

题目：关联 transactions 与 counterparties，按对手方信用评级 credit_rating 汇总2024年的交易笔数与成交金额，并统计该评级下涉及多少个不同对手方，按成交金额降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT cp.credit_rating,
       COUNT(DISTINCT cp.counterparty_id) AS counterparty_cnt,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(t.transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions t
JOIN financial_asset_management.counterparties cp ON cp.counterparty_id = t.counterparty_id
WHERE t.trade_date >= '2024-01-01' AND t.trade_date < '2025-01-01'
GROUP BY cp.credit_rating
ORDER BY trade_amount DESC;
```

### 291 统计各部门管理的未终止组合数量与总市值

题目：以 managers 为核心，经 clients 关联到 portfolios，统计每个部门（department_name）下客户经理人数、未终止组合数量以及组合当前市值 current_value 合计，按总市值降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.department_name,
       COUNT(DISTINCT m.manager_id) AS manager_cnt,
       COUNT(DISTINCT pf.portfolio_id) AS portfolio_cnt,
       ROUND(SUM(pf.current_value), 2) AS portfolio_value_sum
FROM financial_asset_management.managers m
JOIN financial_asset_management.clients c ON c.manager_id = m.manager_id
JOIN financial_asset_management.portfolios pf ON pf.client_id = c.client_id
WHERE pf.termination_date IS NULL
GROUP BY m.department_name
ORDER BY portfolio_value_sum DESC;
```

### 292 统计每个部门管理资产规模前3名的客户经理

题目：用窗口函数在每个部门内部按 manage_assets_total 降序排名，只保留每个部门的前3名客户经理，输出部门、名次、经理姓名、管理资产总额和客户数。请输出对应SQL语句。

参考 SQL：
```sql
WITH dept_rank AS (
    SELECT manager_id, manager_name, department_name, manage_assets_total, client_count,
           ROW_NUMBER() OVER (PARTITION BY department_name ORDER BY manage_assets_total DESC) AS rn
    FROM financial_asset_management.managers
)
SELECT department_name, rn, manager_id, manager_name,
       ROUND(manage_assets_total, 2) AS manage_assets_total, client_count
FROM dept_rank
WHERE rn <= 3
ORDER BY department_name, rn;
```

### 293 统计每种客户类型中总资产最高的前3名客户

题目：在状态正常且 total_assets 非空的客户中，按 client_type 分组用窗口函数取总资产降序排名，返回每种客户类型的前3名客户的姓名与总资产。请输出对应SQL语句。

参考 SQL：
```sql
WITH client_rank AS (
    SELECT client_id, client_name, client_type, total_assets,
           ROW_NUMBER() OVER (PARTITION BY client_type ORDER BY total_assets DESC) AS rn
    FROM financial_asset_management.clients
    WHERE status = 1 AND total_assets IS NOT NULL
)
SELECT client_type, rn, client_id, client_name, ROUND(total_assets, 2) AS total_assets
FROM client_rank
WHERE rn <= 3
ORDER BY client_type, rn;
```

### 294 用相关子查询统计每位客户经理名下总资产前2名的客户

题目：不使用窗口函数，用相关子查询实现分组 Top-2：对每个客户，统计同一经理名下总资产比它高的客户数量，若少于2个则该客户属于前2名，输出经理姓名、客户姓名与总资产。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.manager_name, c.client_name, ROUND(c.total_assets, 2) AS total_assets
FROM financial_asset_management.clients c
JOIN financial_asset_management.managers m ON m.manager_id = c.manager_id
WHERE c.total_assets IS NOT NULL
  AND (SELECT COUNT(*)
       FROM financial_asset_management.clients c2
       WHERE c2.manager_id = c.manager_id
         AND c2.total_assets IS NOT NULL
         AND c2.total_assets > c.total_assets) < 2
ORDER BY m.manager_name, c.total_assets DESC;
```

### 295 统计每种组合类型中盈利金额最高的前3个组合

题目：在未终止组合中，用窗口函数按 portfolio_type 分组、按（当前市值 - 累计投入）即盈利金额降序排名，取每种组合类型的前3名，输出组合代码、当前市值、累计投入与盈利金额。请输出对应SQL语句。

参考 SQL：
```sql
WITH pf_rank AS (
    SELECT portfolio_id, portfolio_code, portfolio_type,
           current_value, contribution_amount,
           ROUND(current_value - contribution_amount, 2) AS profit_amount,
           ROW_NUMBER() OVER (PARTITION BY portfolio_type
                              ORDER BY (current_value - contribution_amount) DESC) AS rn
    FROM financial_asset_management.portfolios
    WHERE termination_date IS NULL
)
SELECT portfolio_type, rn, portfolio_code,
       ROUND(current_value, 2) AS current_value,
       ROUND(contribution_amount, 2) AS contribution_amount,
       profit_amount
FROM pf_rank
WHERE rn <= 3
ORDER BY portfolio_type, rn;
```

### 296 统计各客户类型客户数占全部客户的比例

题目：按 client_type 统计客户数量，并计算该类型客户数占全部客户总数（15000人）的百分比，保留两位小数，按客户数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT client_type,
       COUNT(*) AS client_cnt,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS client_pct
FROM financial_asset_management.clients
GROUP BY client_type
ORDER BY client_cnt DESC;
```

### 297 统计2024年各产品类型交易金额占比

题目：关联 transactions 与 products，按产品类型汇总2024年的成交金额，并计算各类型成交金额占2024年全部成交金额的百分比，保留两位小数，按占比降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.product_type,
       ROUND(SUM(t.transaction_amount), 2) AS trade_amount,
       ROUND(SUM(t.transaction_amount) * 100.0 / SUM(SUM(t.transaction_amount)) OVER (), 2) AS amount_pct
FROM financial_asset_management.transactions t
JOIN financial_asset_management.products p ON p.product_id = t.product_id
WHERE t.trade_date >= '2024-01-01' AND t.trade_date < '2025-01-01'
GROUP BY p.product_type
ORDER BY amount_pct DESC;
```

### 298 统计2024年各交易类型的笔数占比与佣金占比

题目：按 transaction_type 统计2024年的交易笔数、笔数占比、佣金费 commission_fee 合计及其占比，用窗口函数计算占比，按笔数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT transaction_type,
       COUNT(*) AS trade_cnt,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS cnt_pct,
       ROUND(SUM(commission_fee), 2) AS commission_sum,
       ROUND(SUM(commission_fee) * 100.0 / SUM(SUM(commission_fee)) OVER (), 2) AS commission_pct
FROM financial_asset_management.transactions
WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'
GROUP BY transaction_type
ORDER BY trade_cnt DESC;
```

### 299 统计各客户风险等级持有的持仓市值占比

题目：关联 holdings、portfolios、clients，按客户风险等级 risk_level 汇总持仓市值 market_value，并计算各等级市值占全部持仓市值的百分比，同时统计涉及的客户数，按市值降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT c.risk_level,
       COUNT(DISTINCT c.client_id) AS client_cnt,
       ROUND(SUM(h.market_value), 2) AS market_value_sum,
       ROUND(SUM(h.market_value) * 100.0 / SUM(SUM(h.market_value)) OVER (), 2) AS value_pct
FROM financial_asset_management.holdings h
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = h.portfolio_id
JOIN financial_asset_management.clients c ON c.client_id = pf.client_id
GROUP BY c.risk_level
ORDER BY market_value_sum DESC;
```

### 300 统计2024年各月交易金额环比增长率

题目：先用CTE按 LEFT(trade_date,7) 聚合出2024年逐月交易笔数与成交金额，再用窗口函数 LAG 取上一个月金额，计算环比增长率（%），保留两位小数，按月份排序。 口径说明：2024年1月没有上月数据，其环比字段为 NULL 属预期。请输出对应SQL语句。

参考 SQL：
```sql
WITH monthly AS (
    SELECT LEFT(trade_date, 7) AS ym,
           COUNT(*) AS trade_cnt,
           SUM(transaction_amount) AS trade_amount
    FROM financial_asset_management.transactions
    WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'
    GROUP BY LEFT(trade_date, 7)
)
SELECT ym, trade_cnt,
       ROUND(trade_amount, 2) AS trade_amount,
       ROUND(LAG(trade_amount) OVER (ORDER BY ym), 2) AS prev_month_amount,
       ROUND((trade_amount - LAG(trade_amount) OVER (ORDER BY ym)) * 100.0
             / LAG(trade_amount) OVER (ORDER BY ym), 2) AS mom_pct
FROM monthly
ORDER BY ym;
```

### 301 统计2025年各月交易金额同比2024年的增长率

题目：分别按 LEFT(trade_date,7) 聚合2024年与2025年各月的成交金额，再按“月份”对应关联（2025-01 对应 2024-01），计算同比增长率（%），保留两位小数，按2025年月份排序。 口径说明：库内2025年交易数据截至2025-11-28，2025年12月无数据，故只返回1-11月的同比结果。请输出对应SQL语句。

参考 SQL：
```sql
SELECT a.ym AS ym_2025,
       ROUND(a.amount_2025, 2) AS amount_2025,
       ROUND(b.amount_2024, 2) AS amount_2024,
       ROUND((a.amount_2025 - b.amount_2024) * 100.0 / b.amount_2024, 2) AS yoy_pct
FROM (
    SELECT LEFT(trade_date, 7) AS ym, SUM(transaction_amount) AS amount_2025
    FROM financial_asset_management.transactions
    WHERE trade_date >= '2025-01-01' AND trade_date < '2026-01-01'
    GROUP BY LEFT(trade_date, 7)
) a
JOIN (
    SELECT LEFT(trade_date, 7) AS ym, SUM(transaction_amount) AS amount_2024
    FROM financial_asset_management.transactions
    WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'
    GROUP BY LEFT(trade_date, 7)
) b ON b.ym = CONCAT('2024', RIGHT(a.ym, 3))
ORDER BY ym_2025;
```

### 302 统计各产品类型2024年对比2023年的交易额同比增长率

题目：先用 CASE WHEN 在同一次聚合里分别算出2023年与2024年的成交金额，再用外层查询计算同比增长率（%），保留两位小数，按同比增长率降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT product_type,
       ROUND(amount_2023, 2) AS amount_2023,
       ROUND(amount_2024, 2) AS amount_2024,
       ROUND((amount_2024 - amount_2023) * 100.0 / amount_2023, 2) AS yoy_pct
FROM (
    SELECT p.product_type,
           SUM(CASE WHEN t.trade_date >= '2023-01-01' AND t.trade_date < '2024-01-01'
                    THEN t.transaction_amount ELSE 0 END) AS amount_2023,
           SUM(CASE WHEN t.trade_date >= '2024-01-01' AND t.trade_date < '2025-01-01'
                    THEN t.transaction_amount ELSE 0 END) AS amount_2024
    FROM financial_asset_management.transactions t
    JOIN financial_asset_management.products p ON p.product_id = t.product_id
    WHERE t.trade_date >= '2023-01-01' AND t.trade_date < '2025-01-01'
    GROUP BY p.product_type
) x
ORDER BY yoy_pct DESC;
```

### 303 统计各年度交易笔数与成交金额及同比增长率

题目：按 LEFT(trade_date,4) 聚合出各年度交易笔数与成交金额，用窗口函数 LAG 取上一年度金额并计算同比增长率（%），保留两位小数，按年度排序。 口径说明：库内交易数据覆盖2020-2025年，2020年没有上一年度数据，其同比增长率为 NULL 属预期。请输出对应SQL语句。

参考 SQL：
```sql
WITH yearly AS (
    SELECT LEFT(trade_date, 4) AS yr,
           COUNT(*) AS trade_cnt,
           SUM(transaction_amount) AS trade_amount
    FROM financial_asset_management.transactions
    GROUP BY LEFT(trade_date, 4)
)
SELECT yr, trade_cnt,
       ROUND(trade_amount, 2) AS trade_amount,
       ROUND(LAG(trade_amount) OVER (ORDER BY yr), 2) AS prev_year_amount,
       ROUND((trade_amount - LAG(trade_amount) OVER (ORDER BY yr)) * 100.0
             / LAG(trade_amount) OVER (ORDER BY yr), 2) AS yoy_pct
FROM yearly
ORDER BY yr;
```

### 304 用条件聚合统计各风险等级客户人数与平均资产

题目：按客户风险等级 risk_level 分组，用条件聚合一次算出：客户总数、正常/冻结/销户人数、总资产未披露（NULL）人数，以及平均总资产，按客户数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT risk_level,
       COUNT(*) AS client_cnt,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS normal_cnt,
       SUM(CASE WHEN status = 2 THEN 1 ELSE 0 END) AS frozen_cnt,
       SUM(CASE WHEN status = 3 THEN 1 ELSE 0 END) AS closed_cnt,
       SUM(CASE WHEN total_assets IS NULL THEN 1 ELSE 0 END) AS null_asset_cnt,
       ROUND(AVG(total_assets), 2) AS avg_assets
FROM financial_asset_management.clients
GROUP BY risk_level
ORDER BY client_cnt DESC;
```

### 305 统计各客户类型的状态分布与资产异常客户数

题目：按客户类型 client_type 分组，用条件聚合一次输出：正常、冻结、销户客户数，以及总资产为负（负资产）和高资产（总资产大于1000万）的客户数，按正常客户数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT client_type,
       SUM(status = 1) AS normal_cnt,
       SUM(status = 2) AS frozen_cnt,
       SUM(status = 3) AS closed_cnt,
       SUM(total_assets < 0) AS negative_asset_cnt,
       SUM(total_assets > 10000000) AS high_asset_cnt
FROM financial_asset_management.clients
GROUP BY client_type
ORDER BY normal_cnt DESC;
```

### 306 哪位客户经理最会赚钱（2024年买卖金额分列）

题目：以客户经理为维度，用条件聚合把2024年客户的买入、卖出、申购、赎回金额分成四列输出，按卖出金额降序取前10名，用于横向比较各经理名下客户的交易活跃度与资金流向。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, m.department_name,
       ROUND(SUM(CASE WHEN t.transaction_type = '买入' THEN t.transaction_amount ELSE 0 END), 2) AS buy_amount,
       ROUND(SUM(CASE WHEN t.transaction_type = '卖出' THEN t.transaction_amount ELSE 0 END), 2) AS sell_amount,
       ROUND(SUM(CASE WHEN t.transaction_type = '申购' THEN t.transaction_amount ELSE 0 END), 2) AS subscribe_amount,
       ROUND(SUM(CASE WHEN t.transaction_type = '赎回' THEN t.transaction_amount ELSE 0 END), 2) AS redeem_amount
FROM financial_asset_management.transactions t
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = t.portfolio_id
JOIN financial_asset_management.clients c ON c.client_id = pf.client_id
JOIN financial_asset_management.managers m ON m.manager_id = c.manager_id
WHERE t.trade_date >= '2024-01-01' AND t.trade_date < '2025-01-01'
GROUP BY m.manager_id, m.manager_name, m.department_name
ORDER BY sell_amount DESC
LIMIT 10;
```

### 307 统计各产品类型的在售数量与平均管理费率

题目：按产品类型 product_type 分组，用条件聚合统计产品总数、在售（is_active=1）数量、停售（is_active=0）数量，并只对在售产品求平均管理费率（management_fee 为小数费率，如 0.023 表示 2.3%/年），按产品总数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT product_type,
       COUNT(*) AS product_cnt,
       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_cnt,
       SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive_cnt,
       ROUND(AVG(CASE WHEN is_active = 1 THEN management_fee END), 4) AS avg_active_fee
FROM financial_asset_management.products
GROUP BY product_type
ORDER BY product_cnt DESC;
```

### 308 统计被最多客户持有的产品前10名（去重计数）

题目：关联 holdings、products、portfolios，统计每只产品被多少个不同客户持有（COUNT(DISTINCT client_id)）、涉及多少个组合，按持有客户数降序取前10名，考察产品覆盖率。请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.product_id, p.product_name, p.product_type,
       COUNT(DISTINCT pf.client_id) AS client_cnt,
       COUNT(DISTINCT h.portfolio_id) AS portfolio_cnt
FROM financial_asset_management.holdings h
JOIN financial_asset_management.products p ON p.product_id = h.product_id
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = h.portfolio_id
GROUP BY p.product_id, p.product_name, p.product_type
ORDER BY client_cnt DESC
LIMIT 10;
```

### 309 统计各部门有持仓的客户数与产品覆盖数

题目：以 managers、clients、portfolios、holdings 依次内关联，按部门 department_name 汇总：有持仓的去重客户数、去重组合数、去重产品数，按有持仓客户数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.department_name,
       COUNT(DISTINCT c.client_id) AS hold_client_cnt,
       COUNT(DISTINCT pf.portfolio_id) AS portfolio_cnt,
       COUNT(DISTINCT h.product_id) AS product_cnt
FROM financial_asset_management.managers m
JOIN financial_asset_management.clients c ON c.manager_id = m.manager_id
JOIN financial_asset_management.portfolios pf ON pf.client_id = c.client_id
JOIN financial_asset_management.holdings h ON h.portfolio_id = pf.portfolio_id
GROUP BY m.department_name
ORDER BY hold_client_cnt DESC;
```

### 310 统计2025年11月每个交易日的交易笔数与交易客户数

题目：筛选 trade_date 在 2025-11-01 至 2025-12-01 之间的交易（时间列是 VARCHAR 的 ISO 字符串，用半开区间做字符串比较），按交易日分组，统计交易笔数、去重客户数和去重组合数，按日期排序。请输出对应SQL语句。

参考 SQL：
```sql
SELECT t.trade_date,
       COUNT(*) AS trade_cnt,
       COUNT(DISTINCT pf.client_id) AS client_cnt,
       COUNT(DISTINCT t.portfolio_id) AS portfolio_cnt
FROM financial_asset_management.transactions t
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = t.portfolio_id
WHERE t.trade_date >= '2025-11-01' AND t.trade_date < '2025-12-01'
GROUP BY t.trade_date
ORDER BY t.trade_date;
```

### 311 统计各信用评级对手方服务的产品数与组合数（去重计数）

题目：以内关联 transactions 与 counterparties，按信用评级 credit_rating 汇总：对手方去重个数、涉及的去重产品数、去重组合数，按对手方个数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT cp.credit_rating,
       COUNT(DISTINCT cp.counterparty_id) AS counterparty_cnt,
       COUNT(DISTINCT t.product_id) AS product_cnt,
       COUNT(DISTINCT t.portfolio_id) AS portfolio_cnt
FROM financial_asset_management.counterparties cp
JOIN financial_asset_management.transactions t ON t.counterparty_id = cp.counterparty_id
GROUP BY cp.credit_rating
ORDER BY counterparty_cnt DESC;
```

### 312 按总资产档位统计客户数量分布

题目：对非销户客户（status <> 3）按总资产分档统计人数与资产合计：未披露（NULL）、负资产、0-100万、100万-500万、500万-1000万、1000万以上。注意 total_assets 存在 NULL 与负值，分档顺序在别名中用数字前缀保证排序。请输出对应SQL语句。

参考 SQL：
```sql
SELECT asset_bucket,
       COUNT(*) AS client_cnt,
       ROUND(SUM(total_assets), 2) AS asset_sum
FROM (
    SELECT CASE
             WHEN total_assets IS NULL THEN '1_未披露'
             WHEN total_assets < 0 THEN '2_负资产'
             WHEN total_assets < 1000000 THEN '3_0-100万'
             WHEN total_assets < 5000000 THEN '4_100万-500万'
             WHEN total_assets < 10000000 THEN '5_500万-1000万'
             ELSE '6_1000万以上'
           END AS asset_bucket,
           total_assets
    FROM financial_asset_management.clients
    WHERE status <> 3
) x
GROUP BY asset_bucket
ORDER BY asset_bucket;
```

### 313 哪些组合在闷声担风险（按波动率区间统计组合数）

题目：先取每个组合最新一日（MAX(calc_date)）的风险指标，避免一组合多日期放大行数，再按波动率 volatility 分档统计组合数与平均夏普比率：低波动（<10%）、中波动（10%-20%）、较高波动（20%-30%）、高波动（≥30%）。 口径说明：risk_metrics 中实测只有355个组合存在风险指标记录，故各档组合数合计为355。请输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE
         WHEN rm.volatility < 0.1 THEN '低波动(<10%)'
         WHEN rm.volatility < 0.2 THEN '中波动(10%-20%)'
         WHEN rm.volatility < 0.3 THEN '较高波动(20%-30%)'
         ELSE '高波动(>=30%)'
       END AS vol_bucket,
       COUNT(*) AS portfolio_cnt,
       ROUND(AVG(rm.sharp_ratio), 4) AS avg_sharp_ratio,
       ROUND(AVG(rm.max_drawdown), 4) AS avg_max_drawdown
FROM financial_asset_management.risk_metrics rm
JOIN (
    SELECT portfolio_id, MAX(calc_date) AS latest_date
    FROM financial_asset_management.risk_metrics
    GROUP BY portfolio_id
) t ON t.portfolio_id = rm.portfolio_id AND t.latest_date = rm.calc_date
GROUP BY vol_bucket
ORDER BY MIN(rm.volatility);
```

### 314 按持仓天数分档统计持仓数量与浮动盈亏

题目：对持仓表按 holding_days 分档统计：3个月以内、3-6个月、6-12个月、1-2年、2年以上，输出各档持仓笔数、持仓市值合计与浮动盈亏合计，并按持仓天数由短到长排序。请输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE
         WHEN holding_days < 90 THEN '3个月以内'
         WHEN holding_days < 180 THEN '3-6个月'
         WHEN holding_days < 365 THEN '6-12个月'
         WHEN holding_days < 730 THEN '1-2年'
         ELSE '2年以上'
       END AS holding_bucket,
       COUNT(*) AS holding_cnt,
       ROUND(SUM(market_value), 2) AS market_value_sum,
       ROUND(SUM(unrealized_pnl), 2) AS unrealized_pnl_sum
FROM financial_asset_management.holdings
GROUP BY holding_bucket
ORDER BY MIN(holding_days);
```

### 315 按管理资产规模档位统计客户经理人数与平均绩效

题目：对客户经理按 manage_assets_total 分档：1亿以下、1亿-5亿、5亿-10亿、10亿-30亿、30亿以上，统计各档人数与平均绩效分 performance_score，并按规模档位由小到大排序。请输出对应SQL语句。

参考 SQL：
```sql
SELECT CASE
         WHEN manage_assets_total < 100000000 THEN '1亿以下'
         WHEN manage_assets_total < 500000000 THEN '1亿-5亿'
         WHEN manage_assets_total < 1000000000 THEN '5亿-10亿'
         WHEN manage_assets_total < 3000000000 THEN '10亿-30亿'
         ELSE '30亿以上'
       END AS scale_bucket,
       COUNT(*) AS manager_cnt,
       ROUND(AVG(performance_score), 2) AS avg_performance
FROM financial_asset_management.managers
GROUP BY scale_bucket
ORDER BY MIN(manage_assets_total);
```

### 316 最近30天大家都交易了多少（以库内最新交易日为基准）

题目：动态取交易表中最新的 trade_date 作为基准日，统计基准日前30天（含基准日）的交易笔数、去重组合数与成交金额合计。时间列是 VARCHAR 的 ISO 字符串，用字符串范围条件过滤，不对列使用日期函数。 口径说明：基准日取库内最新交易日（当前为2025-11-28），窗口为基准日前30天至基准日，含首尾。请输出对应SQL语句。

参考 SQL：
```sql
SELECT COUNT(*) AS trade_cnt,
       COUNT(DISTINCT portfolio_id) AS portfolio_cnt,
       ROUND(SUM(transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions
WHERE trade_date >= DATE_FORMAT(
          DATE_SUB((SELECT MAX(trade_date) FROM financial_asset_management.transactions), INTERVAL 30 DAY),
          '%Y-%m-%d')
  AND trade_date <= (SELECT MAX(trade_date) FROM financial_asset_management.transactions);
```

### 317 统计库内最近一个有交易的月份各交易类型情况

题目：用子查询取最新的 trade_date 所属月份（LEFT(MAX(trade_date),7)），统计该自然月内各交易类型的笔数与成交金额，按成交金额降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT transaction_type,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions
WHERE LEFT(trade_date, 7) = (SELECT LEFT(MAX(trade_date), 7) FROM financial_asset_management.transactions)
GROUP BY transaction_type
ORDER BY trade_amount DESC;
```

### 318 统计2025年第三季度各产品类型的交易情况

题目：筛选 trade_date 在 2025-07-01 至 2025-10-01 之间（半开区间）的交易，按产品类型统计交易笔数与成交金额，按成交金额降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT p.product_type,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(t.transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions t
JOIN financial_asset_management.products p ON p.product_id = t.product_id
WHERE t.trade_date >= '2025-07-01' AND t.trade_date < '2025-10-01'
GROUP BY p.product_type
ORDER BY trade_amount DESC;
```

### 319 按自然周统计2025年10月的交易笔数与成交金额

题目：筛选2025年10月的交易，用 WEEK(STR_TO_DATE(trade_date,'%Y-%m-%d'), 3) 归入自然周（模式3=周一为一周起点），输出周序号、该周起止日期、交易笔数与成交金额，按周排序。请输出对应SQL语句。

参考 SQL：
```sql
SELECT WEEK(STR_TO_DATE(trade_date, '%Y-%m-%d'), 3) AS week_no,
       MIN(trade_date) AS week_start,
       MAX(trade_date) AS week_end,
       COUNT(*) AS trade_cnt,
       ROUND(SUM(transaction_amount), 2) AS trade_amount
FROM financial_asset_management.transactions
WHERE trade_date >= '2025-10-01' AND trade_date < '2025-11-01'
GROUP BY WEEK(STR_TO_DATE(trade_date, '%Y-%m-%d'), 3)
ORDER BY week_no;
```

### 320 哪些客户光开户不交易

题目：找出状态正常但从未产生过任何交易记录的客户（其名下所有组合都没有交易流水），输出客户编号、姓名、类型与总资产，按总资产降序取前20名。写法说明：用 NOT EXISTS 反连接，不要用 LEFT JOIN 后接 WHERE t.xxx IS NULL，本库 MySQL 8.0.21 在多层左连接反查时会给出错误结果。请输出对应SQL语句。

参考 SQL：
```sql
SELECT c.client_id, c.client_code, c.client_name, c.client_type,
       ROUND(c.total_assets, 2) AS total_assets
FROM financial_asset_management.clients c
WHERE c.status = 1
  AND NOT EXISTS (
      SELECT 1
      FROM financial_asset_management.portfolios pf
      JOIN financial_asset_management.transactions t ON t.portfolio_id = pf.portfolio_id
      WHERE pf.client_id = c.client_id
  )
ORDER BY c.total_assets DESC
LIMIT 20;
```

### 321 哪些客户没留紧急联系人

题目：clients.contact_info 是 JSON 文本列，不能等值匹配，用 LIKE 找出其中 emergency_contact 为 null 的客户，输出客户编号、姓名、类型与联系方式原文，取前20条。请输出对应SQL语句。

参考 SQL：
```sql
SELECT client_id, client_code, client_name, client_type, contact_info
FROM financial_asset_management.clients
WHERE contact_info LIKE '%"emergency_contact": null%'
LIMIT 20;
```

### 322 统计各客户类型中总资产未披露客户的比例

题目：clients.total_assets 存在 NULL（未披露），按客户类型统计：未披露人数、已披露人数以及未披露人数占该类型客户总数的百分比，保留两位小数，按未披露人数降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT client_type,
       SUM(CASE WHEN total_assets IS NULL THEN 1 ELSE 0 END) AS null_asset_cnt,
       SUM(CASE WHEN total_assets IS NOT NULL THEN 1 ELSE 0 END) AS known_asset_cnt,
       ROUND(100.0 * SUM(CASE WHEN total_assets IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS null_pct
FROM financial_asset_management.clients
GROUP BY client_type
ORDER BY null_asset_cnt DESC;
```

### 323 用HAVING筛选管理客户多且户均资产高的客户经理

题目：按客户经理分组，只统计 total_assets 非空的客户，用 HAVING 筛出管理客户数不少于30人且户均总资产超过300万元的客户经理，输出经理姓名、部门、客户数与户均资产，按户均资产降序排列。请输出对应SQL语句。

参考 SQL：
```sql
SELECT m.manager_id, m.manager_name, m.department_name,
       COUNT(c.client_id) AS client_cnt,
       ROUND(AVG(c.total_assets), 2) AS avg_client_assets
FROM financial_asset_management.managers m
JOIN financial_asset_management.clients c ON c.manager_id = m.manager_id
WHERE c.total_assets IS NOT NULL
GROUP BY m.manager_id, m.manager_name, m.department_name
HAVING COUNT(c.client_id) >= 30 AND AVG(c.total_assets) > 3000000
ORDER BY avg_client_assets DESC;
```

### 324 手上持仓市值超过全体平均水平的客户有哪些

题目：先用CTE按客户汇总持仓总市值（holdings 关联 portfolios 后按 client_id 求和），再关联 clients 取客户信息，筛出持仓总市值高于全体客户平均持仓市值的客户，按市值降序取前20名。请输出对应SQL语句。

参考 SQL：
```sql
WITH client_value AS (
    SELECT pf.client_id, SUM(h.market_value) AS total_market_value
    FROM financial_asset_management.holdings h
    JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = h.portfolio_id
    GROUP BY pf.client_id
)
SELECT c.client_id, c.client_name, c.client_type,
       ROUND(cv.total_market_value, 2) AS total_market_value
FROM client_value cv
JOIN financial_asset_management.clients c ON c.client_id = cv.client_id
WHERE cv.total_market_value > (SELECT AVG(total_market_value) FROM client_value)
ORDER BY cv.total_market_value DESC
LIMIT 20;
```

### 325 手上产品波动最大的组合是谁（取最新风险指标）

题目：用CTE先取出每个组合最新一日（MAX(calc_date)）的风险指标，再关联 portfolios 筛出未终止组合，按波动率 volatility 降序取前10名，输出组合代码、组合类型、计算日期、波动率、最大回撤与夏普比率。请输出对应SQL语句。

参考 SQL：
```sql
WITH latest_metric AS (
    SELECT rm.portfolio_id, rm.calc_date, rm.volatility, rm.max_drawdown, rm.sharp_ratio, rm.is_alert
    FROM financial_asset_management.risk_metrics rm
    JOIN (
        SELECT portfolio_id, MAX(calc_date) AS latest_date
        FROM financial_asset_management.risk_metrics
        GROUP BY portfolio_id
    ) t ON t.portfolio_id = rm.portfolio_id AND t.latest_date = rm.calc_date
)
SELECT pf.portfolio_code, pf.portfolio_type, lm.calc_date, lm.volatility,
       lm.max_drawdown, lm.sharp_ratio, lm.is_alert
FROM latest_metric lm
JOIN financial_asset_management.portfolios pf ON pf.portfolio_id = lm.portfolio_id
WHERE pf.termination_date IS NULL
ORDER BY lm.volatility DESC
LIMIT 10;
```

### 326 哪个部门的客户最有钱（部门户均资产对比全公司平均）

题目：先用CTE按部门算出客户数与客户户均总资产（只算 total_assets 非空的客户），再与全公司户均总资产对比，输出部门、客户数、部门户均资产、全公司户均资产以及差值，按部门户均资产降序排列。请输出对应SQL语句。

参考 SQL：
```sql
WITH dept_avg AS (
    SELECT m.department_name,
           COUNT(DISTINCT c.client_id) AS client_cnt,
           AVG(c.total_assets) AS dept_avg_assets
    FROM financial_asset_management.managers m
    JOIN financial_asset_management.clients c ON c.manager_id = m.manager_id
    WHERE c.total_assets IS NOT NULL
    GROUP BY m.department_name
)
SELECT department_name,
       client_cnt,
       ROUND(dept_avg_assets, 2) AS dept_avg_assets,
       (SELECT ROUND(AVG(total_assets), 2)
        FROM financial_asset_management.clients
        WHERE total_assets IS NOT NULL) AS company_avg_assets,
       ROUND(dept_avg_assets - (SELECT AVG(total_assets)
                                FROM financial_asset_management.clients
                                WHERE total_assets IS NOT NULL), 2) AS diff_vs_company
FROM dept_avg
ORDER BY dept_avg_assets DESC;
```
