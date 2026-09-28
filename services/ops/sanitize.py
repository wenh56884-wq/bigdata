# -*- coding: utf-8 -*-
"""输出脱敏层：让回答里不出现个人关键信息（PII）。

为什么放在服务端而不是靠提示词约束：
    最终回答是模型的自由文本，"别泄露"这类要求不可靠；而三个业务库（金融/医疗/通信）
    里真实存在姓名、手机号、证件号、住址、银行卡这类字段，聚合回答时很容易被整段引用。
所以这里统一做两道处理：

    ① **数据预处理**（`mask_rows`）：工具查出的结果集，在**喂给模型之前**就按
       「列名 + 单元格内容」双判断脱敏：姓名 / 手机 / 身份证 / 邮箱 / 住址 / 卡号 /
       保单-病历号 / 出生日期……模型从一开始就没见过明文，自然引用不到；
       图表工具复用同一份缓存，画出来的图同样不含明文。
    ② **文本兜底**（`mask_text` / `StreamSanitizer`）：最终回答（含流式逐字输出）再过
       一遍正则，拦住模型复述、以及非结构化表格里那些"列名是 0/1"无从判断的单元格。

三重保险覆盖了三条出口：**给模型看的上下文 / 给用户看的回答 / 持久化下来的历史**。

开关（.env）：
    SANITIZE=0            关闭脱敏（自己查自己数据、内部演示时可用）
    SANITIZE_STRICT=1     严格模式：身份证/卡号/编号全部隐去，姓名只留姓，邮箱连带域名一起遮

幂等：脱敏结果里不会出现能被同一套规则再次命中的串（`138****5678` 不再匹配手机号），
所以用在哪里重复处理都安全。

自检：python -m services.ops.sanitize
"""

from __future__ import annotations

import os
import re


# --------------------------------------------------------------------------- #
# 开关
# --------------------------------------------------------------------------- #
def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "open")


def enabled() -> bool:
    """是否启用脱敏（默认开；SANITIZE=0 关闭）。"""
    return _env_flag("SANITIZE", default=True)


def strict() -> bool:
    """严格模式：能少露就少露（默认标准模式，保留"看得出是哪家医院/哪个运营商"这类结构）。"""
    return _env_flag("SANITIZE_STRICT")


# --------------------------------------------------------------------------- #
# 通用掩码小工具
# --------------------------------------------------------------------------- #
_STARS = "**********************************"


def _stars(n: int) -> str:
    return _STARS[:n] if 0 < n <= len(_STARS) else "*" * max(n, 0)


def _mask_head_tail(s: str, head: int, tail: int) -> str:
    """保留前 head 位、后 tail 位，中间补星；长度不够就全遮。"""
    n = len(s)
    if n <= 2:
        return "*" * n
    head = min(max(head, 0), n - 1)
    tail = min(max(tail, 0), n - head - 1)
    return s[:head] + _stars(n - head - tail) + (s[-tail:] if tail else "")


# --------------------------------------------------------------------------- #
# ① 自由文本规则（回答、兜底）
# --------------------------------------------------------------------------- #
def _re_id(m: re.Match) -> str:
    """身份证 / 护照等证件号：标准模式留前 6（行政区划）后 4，严格模式全遮。"""
    s = m.group(0)
    return _stars(len(s)) if strict() else (s[:6] + _stars(len(s) - 10) + s[-4:])


def _re_card(m: re.Match) -> str:
    """银行卡 / 长账号：标准模式留前 4 后 4（够识别是哪家行的卡，不够定位到人）。"""
    s = m.group(0)
    return _stars(len(s)) if strict() else _mask_head_tail(s, 4, 4)


def _mask_labeled_no(v: str) -> str:
    """「工号 A20240001」→「工号 A2*****01」。"""
    return _stars(len(v)) if strict() else _mask_head_tail(v, 2, 2)


def _mask_labeled_name(v: str) -> str:
    """「姓名：王小明」→「姓名：王**」。"""
    if not v:
        return v
    return v[:1] + _stars(max(len(v) - 1, 1))


def _re_labeled(mask_fn):
    """「标签：值」型规则统一处理：group(1) 连带冒号空格一起收回，替换后标点不丢。"""
    def _repl(m: re.Match) -> str:
        return m.group(1) + mask_fn(m.group(2))
    return _repl


_factory_labeled = _re_labeled
_re_labeled = _factory_labeled(_mask_labeled_no)
_re_labeled_name = _factory_labeled(_mask_labeled_name)
# _mask_address 定义在下方「列驱动掩码」一节，用 lambda 延迟到调用时才解析
_re_labeled_addr = _factory_labeled(lambda v: _mask_address(v))


def _re_email(m: re.Match) -> str:
    local_head, domain = m.group(1), m.group(2)
    return f"{local_head}***@***" if strict() else f"{local_head}***@{domain}"


# 常见姓氏：把「客户满意度」「客户经理」这类词排除掉，只留真正像人名的组合
_CN_SURNAMES = (
    "王李张刘陈杨黄赵吴周徐孙马朱胡林郭何高罗郑梁谢宋唐许邓冯韩曹曾彭萧蔡潘田董袁于余叶蒋杜苏魏程吕丁"
    "沈任姚卢傅钟姜崔谭廖范汪陆金石戴贾韦夏邱方侯邹熊孟秦白江阎薛尹段雷黎史陶贺顾毛郝龚邵万钱严覃武"
    "戚莫孔向汤"
)
# 这些两字词常跟在「客户/联系人」后面，但不是人名
_NOT_PERSON = frozenset({
    "满意", "需求", "数量", "信用", "服务", "体验", "资料", "确认", "经理", "主管", "代表",
    "信息", "权益", "协议", "情况", "顾问", "须知", "中心", "编号", "群体", "价值", "等级",
    "类型", "来源", "备注", "地址", "名称", "占比", "数量", "规模", "新增", "流失", "回访",
})
_CONTEXT_PERSON = re.compile(
    r"((?:患者|客户|顾客|医师|医生|护士|联系人|负责人|投保人|被保险人|借款人|受益人|会员|员工|同事|机主|代理人|法定代表人|户主)\s*)"
    r"([一-龥]{2,3})(?=$|[，,。;；、!！?？\s（(：:])"
)


def _re_person_ctx(m: re.Match) -> str:
    """隐藏「客户李雷」「patient 王小明称谓」这类上下文里的人名。"""
    word = m.group(2)
    if word[0] not in _CN_SURNAMES or word in _NOT_PERSON:
        return m.group(0)                       # 「客户满意度」不是人名，原样保留
    return m.group(1) + word[0] + _stars(len(word) - 1)


# 顺序敏感：先处理「带标签」的（最不易误伤），再按顺序处理裸值；
# 掩码串（`138****5678`、`32********34`）不会再被后面的规则命中 → 天然幂等。
_TEXT_RULES: list[tuple[re.Pattern, object]] = [
    # 「身份证/护照/社保/病历/银行卡/账号/工号 + 编号」
    (re.compile(r"((?:身份证号?|证件号?|护照号?|社保号?|医保号?|病历号?|住院号?|门诊号?|银行卡号?|卡号|账号|账户号|工号|学号)\s*[:：]?\s*)([A-Za-z0-9]{6,20})"),
     _re_labeled),
    # 「住址/联系地址/收货地址 + 具体地址」
    (re.compile(r"((?:住址|家庭住址|联系地址|详细地址|通讯地址|通信地址|收货地址|家庭地址)\s*[:：]?\s*)([^\s,，;；。|、]{6,40})"),
     _re_labeled_addr),
    # 「姓名/联系人/患者/受益人 + 中文姓名」（模型复述时的典型写法）
    (re.compile(r"((?:姓名|客户姓名|用户姓名|户名|联系人|联系人姓名|患者姓名|病人姓名|医生姓名|受益人|法定代表人|投保人|被保险人)\s*[:：]\s*)([一-龥·]{2,8})"),
     _re_labeled_name),
    # 没有「姓名」字样的称谓 + 人名（姓氏表 + 黑名单双重校验，避免误伤「客户满意度」）
    (_CONTEXT_PERSON, _re_person_ctx),
    # 身份证（带出生日期合法性校验：避免把 18 位流水号误判成身份证）
    (re.compile(r"(?<!\d)([1-9]\d{5})(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"),
     _re_id),
    # 手机号 11 位
    (re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"), r"\1****\2"),
    # 银行卡 / 长账号 13-19 位（前后排除 . % ¥，别把金额当成卡号）
    (re.compile(r"(?<![\d.%$¥￥])(\d{6,11})(\d{4})(?![\d.%])"), _re_card),
    # 邮箱
    (re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"),
     _re_email),
    # IPv4
    (re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3})\.\d{1,3}\.\d{1,3}(?![\d.])"), r"\1.*.*"),
]


def mask_text(text: str) -> str:
    """对一段自由文本做脱敏（幂等，可重复调用）。"""
    if not text or not isinstance(text, str):
        return text
    if not enabled():
        return text
    out = text
    for pattern, repl in _TEXT_RULES:
        out = pattern.sub(repl, out)
    return out


# --------------------------------------------------------------------------- #
# ② 流式安全：-块文本可能把 `1381234|5678` 切成两半，直接-mentioned 逐段处理会漏掉
# --------------------------------------------------------------------------- #
_TAIL = 64          # 末尾保留待定的长度（跨 chunk 的最长模式 + 余量）
_MAX_PENDING = 8192  # 极端情况（超长无标点串）的兜底上限


def _safe_cut(buf: str) -> int:
    """返回可以安全输出的切点：只在"词边界"处下刀，且至少留下 _TAIL 个字符待定。"""
    if len(buf) <= _TAIL:
        return 0
    start = len(buf) - _TAIL
    # 往后找第一个「不可能是一个长模式中间」的字符：空白 / 中文标点 / 表格竖线 / 逗号
    for i in range(start, len(buf)):
        if buf[i] in " \t\r\n,，。；;：:|、（）()【】[]「」\"'":
            return i + 1
    # 找不到边界（一长串连续数字/字母）：让它先攒着，避免切一半漏判
    if len(buf) >= _MAX_PENDING:  # 攒太久了强制放行
        return len(buf)
    return 0


class StreamSanitizer:
    """流式输出的增量脱敏器。

    用法：push(chunk) 返回**现在可以安全吐给用户**的部分；流结束时 flush() 收尾。
    已经吐出去的内容不会再被改写，所以前端看到的始终是一次成型的文本。
    """

    def __init__(self) -> None:
        self._buf = ""

    def push(self, chunk: str) -> str:
        if not enabled():
            return chunk or ""
        self._buf += chunk or ""
        cut = _safe_cut(self._buf)
        if not cut:
            return ""
        safe, self._buf = self._buf[:cut], self._buf[cut:]
        return mask_text(safe)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        return mask_text(rest) if enabled() else rest


# --------------------------------------------------------------------------- #
# ③ 列驱动的掩码函数（结果集预处理）
# --------------------------------------------------------------------------- #
def _mask_name(v) -> str:
    s = str(v).strip()
    if not s:
        return s
    if " " in s:                       # John Smith → J*** S****
        parts = [p for p in s.split() if p]
        return " ".join(p[0] + _stars(max(len(p) - 1, 1)) for p in parts)
    if re.fullmatch(r"[一-龥·]+", s):   # 王小明 / 王**
        return s[0] + _stars(max(len(s) - 1, 1))
    if len(s) <= 2:
        return (s[0] + "*") if s else s
    return s[:1] + _stars(len(s) - 2) + s[-1]


def _mask_phone(v) -> str:
    s = str(v).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return _stars(len(s))
    if len(digits) >= 11:              # 手机号：留前 3 后 4
        head, tail = 3, 4
    else:                              # 固话 / 短号
        head, tail = 3, 2
    return digits[:head] + _stars(len(digits) - head - tail) + digits[-tail:]


def _mask_id_no(v) -> str:
    s = str(v).strip()
    if len(s) < 8:
        return _stars(len(s))
    return _stars(len(s)) if strict() else (s[:6] + _stars(max(len(s) - 10, 1)) + s[-4:])


def _mask_email_cell(v) -> str:
    s = str(v).strip()
    user, sep, domain = s.partition("@")
    if not sep:
        return _stars(len(s))
    return f"{user[:1]}***@***" if strict() else f"{user[:1]}***@{domain}"


def _mask_address(v) -> str:
    s = str(v).strip()
    if len(s) <= 4:
        return _stars(len(s))
    # 优先保留到行政区划那一层（"北京市朝阳区……" → "北京市朝阳区***"）
    cut = -1
    for unit in ("区", "县", "旗", "镇", "乡", "市", "省"):
        pos = s.find(unit)
        if 1 <= pos <= 12:
            cut = max(cut, pos)
    if 2 <= cut < len(s) - 1:
        return s[:cut + 1] + _stars(min(len(s) - cut - 1, 6))
    # 退而求其次：保留前一小段（够看出是哪个城市/区域，不够定位到门牌）
    keep = max(len(s) // 3, 3)
    return s[:keep] + _stars(min(len(s) - keep, 8))


def _mask_card_no(v) -> str:
    s = str(v).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 8:
        return _stars(len(s))
    return _stars(len(digits)) if strict() else (digits[:4] + _stars(len(digits) - 8) + digits[-4:])


def _mask_serial(v) -> str:
    """病历号 / 保单号 / 住院号这类业务流水号：默认只留后 4 位（还够对账，不够定位到人）。"""
    s = str(v).strip()
    return _stars(len(s)) if strict() else _mask_head_tail(s, 0, 4)


def _mask_birth(v) -> str:
    """出生日期：精确到日仍是个人信息（可用于去匿名化），统一留到年/月。"""
    s = str(v).strip()
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})?[-/.月]?(\d{1,2})?日?", s)
    if m:
        year = m.group(1)
        month = m.group(2)
        return f"{year}-{month or '**'}-**"
    return _stars(max(len(s), 2))


def _mask_secret(v) -> str:
    return _stars(min(len(str(v)), 12)) or "******"


def _mask_ip_cell(v) -> str:
    s = str(v).strip()
    parts = s.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return _stars(len(s))


_MASKERS = {
    "name": _mask_name,
    "phone": _mask_phone,
    "id": _mask_id_no,
    "email": _mask_email_cell,
    "address": _mask_address,
    "card": _mask_card_no,
    "serial": _mask_serial,
    "birth": _mask_birth,
    "secret": _mask_secret,
    "ip": _mask_ip_cell,
}

_CN_LABELS = {
    "name": "姓名",
    "phone": "手机号",
    "id": "证件号",
    "email": "邮箱",
    "address": "地址",
    "card": "银行卡号",
    "serial": "业务流水号",
    "birth": "出生日期",
    "secret": "密钥",
    "ip": "IP 地址",
}


# --------------------------------------------------------------------------- #
# 列名 → 敏感类型（英文名按 token 匹配，中文名按子串匹配）
# --------------------------------------------------------------------------- #
_NAME_TOKENS = frozenset({
    "name", "names", "fullname", "username", "contact", "contacts", "contactperson",
    "beneficiary", "applicant", "holder", "payee", "borrower", "insured", "policyholder",
    "doctor", "patient", "customer", "client", "employee", "staff", "member", "customer_name",
})
# 这些列虽然带 name / customer 等字眼，存的却是物品/机构/维度，不该按人名处理
_NAME_SAFE_TOKENS = frozenset({
    "product", "file", "table", "column", "field", "sheet", "db", "dataset", "category",
    "type", "brand", "dept", "department", "company", "org", "role", "status", "level",
    "city", "country", "province", "index", "idx", "code", "key", "method", "rule", "model",
    "metric", "dimension", "plan", "task", "event", "template", "currency", "period", "region",
    "channel", "label", "group", "bank", "fund", "account_type", "acct_type", "branch", "store",
    "skill", "report", "source", "target", "server", "host", "app", "project", "dataset_name",
})

_COL_RULES: list[tuple[frozenset, frozenset, str]] = [
    (frozenset({"idcard", "idcardno", "idno", "identity", "identityno", "ssn", "passportno", "nin", "taxid", "taxpayerid"}),
     frozenset({"身份证", "证件号", "证件号码", "身份证号", "社保号", "护照号", "纳税人识别号"}), "id"),
    (frozenset({"phone", "phonenumber", "mobile", "cellphone", "telephone", "tel", "telno", "contactno", "contactnumber", "whatsapp", "msisdn"}),
     frozenset({"手机", "手机号", "手机号码", "电话", "联系电话", "电话号码", "联系方式", "移动电话"}), "phone"),
    (frozenset({"email", "emailaddress", "mail", "mailaddress", "emailaddr"}),
     frozenset({"邮箱", "电子邮件", "电子邮箱", "邮件地址", "邮箱地址"}), "email"),
    (frozenset({"address", "addr", "domicile", "residence", "street", "shippingaddress", "billingaddress", "homeaddress", "postaddress"}),
     frozenset({"住址", "家庭住址", "联系地址", "详细地址", "通讯地址", "通信地址", "收货地址", "家庭地址"}), "address"),
    (frozenset({"bankcard", "cardno", "cardnumber", "bankaccount", "accountno", "accountnumber", "iban", "acctno"}),
     frozenset({"银行卡", "银行卡号", "银行账号", "卡号", "账号", "账户号", "收款账号"}), "card"),
    (frozenset({"mrn", "medicalrecord", "medicalrecordno", "recordno", "caseno", "patientid", "policyno", "policyid", "claimno", "insuranceno", "admissionno", "employeeid", "staffid"}),
     frozenset({"病历号", "住院号", "门诊号", "就诊号", "保单号", "理赔号", "员工号", "工号", "会员号"}), "serial"),
    (frozenset({"birth", "birthday", "birthdate", "dateofbirth", "dob"}),
     frozenset({"出生日期", "生日", "出生年月"}), "birth"),
    (frozenset({"password", "passwd", "pwd", "secret", "token", "privatekey", "apikey", "accesskey"}),
     frozenset({"密码", "口令", "密钥", "秘钥"}), "secret"),
    (frozenset({"ip", "ipaddress", "clientip", "loginip"}),
     frozenset({"ip地址", "登录ip"}), "ip"),
]


def _col_tokens(col: str) -> frozenset:
    """列名拆成 token：client_name / ClientName / _姓名 → {client, name, ...}。"""
    raw = str(col or "").strip().lower()
    parts = re.split(r"[^a-z0-9]+", raw)
    tokens = {p for p in parts if p}
    tokens |= {t for p in list(tokens) for t in _camel_split(p)}
    return frozenset(tokens)


def _camel_split(word: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", str(word or "")) if len(w) > 2]


# 复合列名：`id_card_no` / `card_no` / `phone_no` 拆成 token 后单词本身不敏感，
# 但组合起来含义明确。放在单词规则之前判断（更具体者优先）。
_COL_COMBOS: list[tuple[tuple[frozenset, ...], str]] = [
    ((frozenset({"id", "card"}), frozenset({"id", "no"}), frozenset({"id", "number"}),
      frozenset({"identity", "no"}), frozenset({"id", "code"})), "id"),
    # 客户/患者/会员编号：单看 patient 会落到"人名"规则，实际是流水号
    ((frozenset({"patient", "id"}), frozenset({"customer", "id"}), frozenset({"client", "id"}),
      frozenset({"member", "id"}), frozenset({"user", "id"}), frozenset({"customer", "no"})), "serial"),
    ((frozenset({"card", "no"}), frozenset({"bank", "card"}), frozenset({"acct", "no"}),
      frozenset({"account", "no"}), frozenset({"card", "number"})), "card"),
    ((frozenset({"phone", "no"}), frozenset({"tel", "no"}), frozenset({"mobile", "no"}),
      frozenset({"contact", "no"}), frozenset({"phone", "number"})), "phone"),
    ((frozenset({"email", "addr"}), frozenset({"mail", "addr"}), frozenset({"mail", "address"})), "email"),
    ((frozenset({"address", "line"}), frozenset({"addr", "line"}), frozenset({"home", "address"})), "address"),
]


def classify_column(col: str) -> str | None:
    """判断一列保存的是不是个人信息；是则返回类型 key，否则 None。"""
    if not col:
        return None
    raw = str(col).strip()
    tokens, lower = _col_tokens(raw), raw.lower()
    for combos, kind in _COL_COMBOS:
        if any(combo <= tokens for combo in combos):
            return kind
    for en, cn, kind in _COL_RULES:
        if tokens & en:
            return kind
        if any(word in lower for word in cn):
            return kind
    # 人名放在最后判，并先排除「产品名 / 文件名 / 库名」这类同构列名
    if tokens & _NAME_TOKENS and not (tokens & _NAME_SAFE_TOKENS):
        return "name"
    if any(word in lower for word in ("姓名", "客户姓名", "户名", "联系人", "受益人", "投保人", "医生姓名", "患者姓名")):
        return "name"
    return None


# --------------------------------------------------------------------------- #
# 结果集预处理：给模型看之前先把表格里的个人信息挖掉
# --------------------------------------------------------------------------- #
def _mask_cell(value, kind: str | None):
    """单个单元格：先按列类型处理，再跑一次文本兜底（通用列里也可能躺着手机号）。"""
    if value is None:
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value                                   # 数值不会是 PII（金额/年份等）
    text = str(value)
    if kind:
        try:
            out = _MASKERS[kind](value)
        except Exception:
            out = text
        if out != text:
            # 掩码结果本身不再含完整号码；极端情况（列里混着邮箱）再兜一次
            return out
        return mask_text(text)
    # 非敏感列：只在"看起来像"的时候处理，避免对普通文本反复跑正则
    if len(text) >= 7 and re.search(r"[@\d]", text):
        return mask_text(text)
    return text


def mask_rows(headers, rows):
    """结果集脱敏。返回 (新 headers, 新 rows, 被处理的列名列表)。

    列名列表用于给模型一句交代（"含个人信息，已脱敏：姓名、手机号"），
    免得它发现值不对就自己"补"一个名字出来。
    """
    cols = list(headers or [])
    body = list(rows or [])
    kinds = [classify_column(c) for c in cols]
    if not enabled() or not any(kinds):
        return cols, body, []

    masked_cols: list[str] = []
    new_header = []
    for col, kind in zip(cols, kinds):
        new_header.append(f"{col}(已脱敏)" if kind else col)
        if kind and col not in masked_cols:
            masked_cols.append(col)

    new_rows = []
    for row in body:
        cells = list(row)
        new_rows.append([_mask_cell(v, kinds[i]) if i < len(kinds) else v for i, v in enumerate(cells)])
    return new_header, new_rows, masked_cols


def note_for(masked_cols: list[str]) -> str:
    """给模型/用户的一句话交代。"""
    if not masked_cols:
        return ""
    shown = "、".join(str(c) for c in masked_cols[:6])
    more = f" 等 {len(masked_cols)} 项" if len(masked_cols) > 6 else ""
    return f"（本结果含个人信息，{shown}{more}已按规则脱敏展示，请勿尝试还原）"


# --------------------------------------------------------------------------- #
# 自检：python -m services.ops.sanitize
# --------------------------------------------------------------------------- #
def _demo() -> None:
    cases = [
        ["客户姓名", "手机号", "身份证号", "邮箱", "住址", "银行卡号", "净收入"],
        ["王小明", "13812345678", "320102199001011234", "xiaoming@163.com",
         "北京市朝阳区三里屯路 7 号 1201", "6222020200123456789", 12345.67],
        ["李雷", "13900001111", "11010119850505001X", "lilei@hospital.org.cn",
         "上海市浦东新区世纪大道 100 号", "6217000099887766554", 8890.0],
    ]
    headers, rows, masked = mask_rows(cases[0], cases[1:])
    print("列名：", headers)
    print("命中：", masked)
    for r in rows:
        print("  ", r)
    print("说明：", note_for(masked))
    print()
    for t in [
        "该患者 王小明，身份证 320102199001011234，电话 13812345678，邮箱 xiaoming@163.com，住址：北京市朝阳区三里屯路7号",
        "联系人：张三，工号 A20240001，账号 6222020200123456789",
        "2024 年净收入 12345678.90 元，同比增长 12.3%（不要当成卡号）",
        "以下句子不该被改：客户满意度 92%，会员 12345 人，订单 20240115 号，服务热线 4001234567，主治医师赵（2字以下不判）",
    ]:
        print("原文：", t)
        print("脱敏：", mask_text(t))
    print()
    stream = StreamSanitizer()
    out = "".join(stream.push(c) for c in ["该客户138", "1234", "5678，很好", "，身份证320", "102199001011234。"])
    print("流式：", out + stream.flush())


if __name__ == "__main__":
    if not enabled():
        print("(SANITIZE=0 —— 脱敏已关闭，下面展示的是不脱敏的对照结果)")
    _demo()
