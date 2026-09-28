# 通用能力技能卡：统计分析 · Python 二次计算（analytics）

> 用途：对查询结果或业务表做统计画像、异常检测、聚类、同比环比、移动平均等二次分析。

## 1. 什么时候用
用户要求“做统计分析 / 画像 / 相关性 / 异常检测 / 聚类分群 / 同比环比 / 二次计算 / 用 Python 算”时使用。

## 2. 可用工具与选择
- `analyze_data(database, table, columns, where, sample_limit)`：单表数值画像 + 相关系数。
- `detect_data_anomalies(database, table, value_col, label_col, where)`：z-score / 箱线图 / 孤立森林投票找异常。
- `cluster_data(database, table, columns, max_k, where)`：客户 / 对象自动分群并解释簇特征。
- `run_python(code)`：对“最近一次查询结果”做二次计算；变量为 `rows`（行字典列表）和 `cols`。
- `query_table_python(code, table, question)`：用 pandas 查非结构化表格，变量为 `df`，可用 `pd` / `np`。

## 3. 标准流程
1. 先通过 `get_table_schema` 或 `describe_table` 确认表和列名。
2. 选择最合适的工具执行分析。
3. 用中文给出结论：关键统计量、异常项、分群画像或计算结果；数据多时用 Markdown 表格。

## 4. 易错点
- `run_python` 只能使用最近一次查询的缓存，先查数再计算。
- Python 沙箱禁止 `import` / `while`；用内置函数、`statistics`、`np` 时按工具示例写。
- 列名必须照抄实时结构返回，不要凭印象编列名。
- 结果涉及个人信息的，前端 / 后端会脱敏，回答时不要还原脱敏字段。
