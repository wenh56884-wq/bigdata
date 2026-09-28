# -*- coding: utf-8 -*-
"""问答准确率评测的数据集：题目 + **权威标准答案**（直接查库算出来，不靠模型）。

设计原则：
- 每题都**有唯一正确答案**，且能由 SQL / 文档原文直接算出（`truth_sql` + `db`）；
- 题目用日常问法（不写成 SQL），才能真正测出「理解 + 取数 + 表达」全链路；
- 覆盖三类：业务库 SQL 统计、知识库文档问答、工具（计算/时间）；
- 判分是**数值容差 + 关键词包含**，不依赖 LLM 打分——可重复、可回归。

新增用例：在 CASES 里加一条即可（truth_sql 返回一行一列的值，或 (数值, 文本) 组合）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

FIN = "financial_asset_management"
MED = "healthcare_analytics_competition"
TEL = "telecom_operations_db"


@dataclass
class Case:
    id: str
    question: str
    category: str                     # sql-finance / sql-health / sql-telecom / knowledge / tool
    db: str | None = None             # truth_sql 要在哪个库执行
    truth_sql: str | None = None      # 得到**权威答案**的 SQL（单值）
    expect_text: list[str] = field(default_factory=list)   # 期望出现的文本（任一命中即可）
    expect_regex: list[str] = field(default_factory=list)  # 期望命中的正则（说法多变时用）
    note: str = ""                    # 备注（口径说明）
    check: Callable[[str, list], bool] | None = None       # 自定义判分项


CASES: list[Case] = [
    # ---------------- 业务库：金融资产管理 ----------------
    Case("F1", "金融库里一共有多少个客户？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM clients"),
    Case("F2", "金融资产管理库里交易流水表一共有多少条记录？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM transactions"),
    Case("F3", "金融库 2024 年全年的交易总金额是多少？", "sql-finance", FIN,
         "SELECT SUM(transaction_amount) FROM transactions "
         "WHERE trade_date >= '2024-01-01' AND trade_date < '2025-01-01'"),
    Case("F4", "金融库里客户类型为「个人」的客户有多少个？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM clients WHERE client_type = '个人'"),
    Case("F5", "金融库的组合 portfolios 表一共有多少条记录？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM portfolios"),
    Case("F6", "金融库一共有多少位投资经理？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM managers"),
    Case("F7", "金融库里风险等级为「保守」的客户有多少人？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM clients WHERE risk_level = '保守'"),
    Case("F8", "金融库 2024 年新注册的客户有多少人？", "sql-finance", FIN,
         "SELECT COUNT(*) FROM clients "
         "WHERE register_date >= '2024-01-01' AND register_date < '2025-01-01'"),

    # ---------------- 业务库：医疗分析 ----------------
    Case("H1", "医疗库账单明细表一共有多少条记录？", "sql-health", MED,
         "SELECT COUNT(*) FROM billing_transactions"),
    Case("H2", "医疗库 2024 年账单的净额合计是多少？", "sql-health", MED,
         "SELECT SUM(net_amount) FROM billing_transactions "
         "WHERE transaction_date >= '2024-01-01' AND transaction_date < '2025-01-01'"),
    Case("H3", "医疗库 2024 年的住院人次是多少？", "sql-health", MED,
         "SELECT COUNT(*) FROM medical_encounters "
         "WHERE encounter_type = '住院' AND encounter_date >= '2024-01-01' "
         "AND encounter_date < '2025-01-01'"),
    Case("H4", "医疗库患者主索引里女性患者有多少人？", "sql-health", MED,
         "SELECT COUNT(*) FROM patient_master_index WHERE gender = 'F'"),
    Case("H5", "医疗库账单里支付状态为「已支付」的有多少条？", "sql-health", MED,
         "SELECT COUNT(*) FROM billing_transactions WHERE payment_status = '已支付'"),
    Case("H6", "医疗库的科室表里「临床科室」有多少个？", "sql-health", MED,
         "SELECT COUNT(*) FROM departments_wards WHERE type = '临床科室'"),
    Case("H7", "医疗库 2024 年药品费的金额合计是多少？", "sql-health", MED,
         "SELECT SUM(net_amount) FROM billing_transactions "
         "WHERE transaction_type = '药品费' AND transaction_date >= '2024-01-01' "
         "AND transaction_date < '2025-01-01'"),
    Case("H8", "医疗库的就诊记录一共有多少条？", "sql-health", MED,
         "SELECT COUNT(*) FROM medical_encounters"),

    # ---------------- 业务库：通信运营 ----------------
    Case("T1", "通信库一共有多少个客户？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM customers"),
    Case("T2", "通信库的通话详单表一共有多少条记录？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM cdr_detail"),
    Case("T3", "通信库里客户状态为「正常」的有多少人？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM customers WHERE customer_status = '正常'"),
    Case("T4", "通信库存量详单里「本地语音」类的记录有多少条？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM cdr_detail WHERE call_type = '本地语音'"),
    Case("T5", "通信库的服务记录里「投诉」类型的有多少条？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM service_records WHERE service_type = '投诉'"),
    Case("T6", "通信库 2024 年的月结账单应收总金额是多少？", "sql-telecom", TEL,
         "SELECT SUM(total_amount) FROM monthly_bills "
         "WHERE billing_month >= '2024-01-01' AND billing_month < '2025-01-01'"),
    Case("T7", "通信库产品表里一共有多少行产品数据？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM products"),
    Case("T8", "通信库已经销户的客户有多少人？", "sql-telecom", TEL,
         "SELECT COUNT(*) FROM customers WHERE customer_status = '已销户'"),

    # ---------------- 知识库文档（公司政策） ----------------
    Case("K1", "差旅结束后，报销单据要在几个工作日内提交？", "knowledge", None, None,
         expect_text=["5 个工作日", "5个工作日", "五个工作日"]),
    Case("K2", "一线城市出差的住宿标准，单晚上限是多少元？", "knowledge", None, None,
         expect_text=["600"]),
    Case("K3", "报销金额超过多少元需要二级审批？", "knowledge", None, None,
         expect_text=["3000", "3,000"]),
    Case("K4", "报销款一般几个工作日内到账？", "knowledge", None, None,
         expect_text=["15 个工作日", "15个工作日", "十五个工作日"]),
    Case("K5", "到一线城市出差的餐饮补贴标准是多少元每天？", "knowledge", None, None,
         expect_text=["120"]),
    Case("K6", "同住标准间按单间上限的百分之多少报销？", "knowledge", None, None,
         expect_text=["60%", "60 %"]),
    Case("K7", "发票抬头有什么要求？", "knowledge", None, None,
         expect_text=["公司全称", "统一社会信用代码"]),
    Case("K8", "单程打车超过多少元需要在报销单备注事由？", "knowledge", None, None,
         expect_text=["100"]),

    # ---------------- 进阶：跨表 / Top-N / 占比 / 去重 / 阈值 ----------------
    # 注：必须写清要不要过滤客户状态——默认过滤「正常」= 44，不过滤 = 45，两者都有依据
    Case("S1", "金融库里按 manager_id 分组，管理客户数最多的那位经理名下有多少个客户"
               "（不区分客户状态，全部计入）？", "sql-hard", FIN,
         "SELECT COUNT(*) c FROM clients WHERE manager_id IS NOT NULL "
         "GROUP BY manager_id ORDER BY c DESC LIMIT 1"),
    # 口径提醒：模型倾向于按业务常识排除「已取消/失败/冻结」，这些聚合题必须写清要不要算
    Case("S2", "金融库 2024 年「卖出」类交易的金额合计是多少（不区分交易状态，全部计入）？",
         "sql-hard", FIN,
         "SELECT SUM(transaction_amount) FROM transactions WHERE transaction_type = '卖出' "
         "AND trade_date >= '2024-01-01' AND trade_date < '2025-01-01'"),
    Case("S3", "金融库的 portfolios 表里一共涉及多少个不同的客户？", "sql-hard", FIN,
         "SELECT COUNT(DISTINCT client_id) FROM portfolios"),
    Case("S4", "金融库总资产超过 1000 万的客户有多少位（不区分客户状态，全部计入）？",
         "sql-hard", FIN,
         "SELECT COUNT(*) FROM clients WHERE total_assets > 10000000"),
    Case("S5", "医疗库里金额最高的那笔账单，净额是多少？", "sql-hard", MED,
         "SELECT MAX(net_amount) FROM billing_transactions"),
    Case("S6", "医疗库 2024 年账单的平均单笔净额是多少（不区分支付状态，全部计入）？",
         "sql-hard", MED,
         "SELECT AVG(net_amount) FROM billing_transactions "
         "WHERE transaction_date >= '2024-01-01' AND transaction_date < '2025-01-01'"),
    # 注：encounter_status 有「已完成/已取消/进行中」三态，问"人次"必须说清算不算已取消，
    # 否则模型排除已取消（3014）或按全量计（4476）都算有依据——拆成两道题，各自口径明确
    Case("S7", "医疗库 2024 年 encounter_type 为「门诊」的就诊记录一共有多少条（不论状态）？",
         "sql-hard", MED,
         "SELECT COUNT(*) FROM medical_encounters WHERE encounter_type = '门诊' "
         "AND encounter_date >= '2024-01-01' AND encounter_date < '2025-01-01'"),
    Case("S7b", "医疗库 2024 年 encounter_status 不是「已取消」的门诊记录有多少条？", "sql-hard", MED,
         "SELECT COUNT(*) FROM medical_encounters WHERE encounter_type = '门诊' "
         "AND encounter_date >= '2024-01-01' AND encounter_date < '2025-01-01' "
         "AND encounter_status <> '已取消'"),
    Case("S8", "通信库已销户客户占全部客户的百分比是多少？", "sql-hard", TEL,
         "SELECT ROUND(100.0 * SUM(customer_status = '已销户') / COUNT(*), 2) FROM customers"),
    Case("S9", "通信库 2024 年还有未缴清金额的账单有多少条？", "sql-hard", TEL,
         "SELECT COUNT(*) FROM monthly_bills WHERE unpaid_amount > 0 "
         "AND billing_month >= '2024-01-01' AND billing_month < '2025-01-01'"),
    Case("S10", "通信库里办理过订购业务的客户有多少个？", "sql-hard", TEL,
         "SELECT COUNT(DISTINCT customer_id) FROM subscriptions"),

    # ---------------- 知识库：换说法 / 反向问法 / 易混淆项 ----------------
    Case("K9", "拿个人抬头的发票来报销，公司给报吗？", "knowledge", None, None,
         expect_text=["不予报销", "不报销", "不能报销"]),
    Case("K10", "出差要延长行程的话，最晚什么时候补交申请？", "knowledge", None, None,
         expect_text=["1 个工作日", "1个工作日", "一个工作日"]),
    Case("K11", "非一线城市出差的住宿标准，单晚上限多少元？", "knowledge", None, None,
         expect_text=["400"]),
    Case("K12", "没有审批就先去出差了，这笔费用怎么处理？", "knowledge", None, None,
         expect_text=["不予报销", "不报销", "不能报销"]),

    # ---------------- 诚实性：查不到就要说实话 ----------------
    # 注：说法多变（"没有 xxx 这张表" / "不存在该表" / "查不到这张表"），用正则判而不是死关键词
    Case("N1", "金融库里 employee_performance 这张表一共有多少行数据？", "honesty", None, None,
         expect_regex=[r"没有.{0,40}这张表", r"不存在", r"找不到", r"没有找到", r"未找到",
                       r"库里.{0,20}没有"]),

    # ---------------- 工具 ----------------
    Case("C1", "帮我算一下 128 乘以 36 等于多少？", "tool", None, None,
         expect_text=["4608"]),
    Case("C2", "《公司差旅与报销政策》这份文档里，地铁公交相关的交通要求是怎么写的？",
         "knowledge", None, None, expect_text=["优先地铁"]),
]


def by_id(case_id: str) -> Case | None:
    for case in CASES:
        if case.id == case_id:
            return case
    return None
