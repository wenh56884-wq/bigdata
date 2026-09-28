"""Excel / CSV 表格文件能力的离线测试（不连数据库、不调模型、不写真实索引）。

覆盖三层：
  ① services/spreadsheet.py 解析层：xlsx 多 sheet / csv(UTF-8·BOM 与 GBK) / tsv / 无表头 / 坏文件
  ② services/tables.py 集成层：解析 → 入库 → 只读 SQL → 召回
  ③ 行为不变性：目录里没有表格文件时，行为与改造前一致（不凭空多出数据集）

跑法：python eval/_test_spreadsheet.py
"""
from __future__ import annotations

import contextlib
import shutil
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))

from services.datasource import spreadsheet, tables  # noqa: E402

_PASSED = 0
_FAILED = 0


def check(name: str, got, want) -> None:
    global _PASSED, _FAILED
    if got == want:
        _PASSED += 1
        print(f"  [OK] {name}")
    else:
        _FAILED += 1
        print(f"  [NG] {name}  期望={want!r} 实际={got!r}")


def truthy(name: str, condition: bool) -> None:
    check(name, bool(condition), True)


@contextlib.contextmanager
def temp_dir():
    """临时目录；Windows 上 SQLite 句柄可能没及时释放，删不掉不该算测试失败。"""
    path = Path(tempfile.mkdtemp(prefix="tbltest_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def make_fixtures(directory: Path) -> None:
    """造测试用的真实表格文件。"""
    import pandas as pd

    xlsx = directory / "销售明细.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        pd.DataFrame({"月份": ["2024-01", "2024-02", "2024-03"],
                      "销售额": [120000.5, 135800.0, 98000.25],
                      "区域": ["华东", "华南", "华北"]}).to_excel(
            writer, sheet_name="月度销售", index=False)
        pd.DataFrame({"产品": ["A", "B", "C"], "库存": [320, 155, 88]}).to_excel(
            writer, sheet_name="库存", index=False)
    # 国内 Excel 导出的 CSV 常是 GBK，这里两种编码都造一份
    (directory / "客户名单.csv").write_text(
        "客户编号,客户名称,等级,消费额\n1,张三,VIP,8800\n2,李四,普通,1200\n3,王五,VIP,15600\n",
        encoding="gbk")
    (directory / "指标.tsv").write_text("指标\t数值\n活跃用户\t12000\n留存率\t0.63\n", encoding="utf-8")
    (directory / "带BOM.csv").write_text("\ufeff月份,金额\n2024-01,100\n2024-02,200\n",
                                         encoding="utf-8")


def main() -> int:
    print("=" * 62)
    print("Excel / CSV 表格文件能力测试")
    print("=" * 62)

    # ---------- ① 解析层 ----------
    print("\n① 解析层（services/spreadsheet.py）")
    with temp_dir() as raw:
        tmp = Path(raw)
        make_fixtures(tmp)

        check("目录能发现 4 个表格文件", len(spreadsheet.discover(tmp)), 4)

        parsed = list(spreadsheet.parse_directory(tmp))
        # xlsx 两个 sheet + csv + tsv + 带BOM.csv = 5 张表
        check("共解析出 5 张表", len(parsed), 5)

        by_id = {sid: tbl for _file, sid, tbl in parsed}
        monthly = by_id.get("销售明细#月度销售")
        truthy("多 sheet 拆成不同 source_id", monthly is not None)
        if monthly:
            check("列名取自首行", monthly["columns"], ["月份", "销售额", "区域"])
            check("行数正确", len(monthly["rows"]), 3)
            check("销售额被判为数值列", monthly["numeric"][1], True)
            check("区域不是数值列", monthly["numeric"][2], False)
            check("数值已转成 float", monthly["rows"][0][1], 120000.5)

        check("GBK 编码的中文能读", by_id["客户名单"]["rows"][0][1], "张三")
        check("BOM 不进列名", by_id["带BOM"]["columns"][0], "月份")
        check("TSV 按制表符切分", by_id["指标"]["columns"], ["指标", "数值"])

        # 真实 Excel 常见的「大标题行 + 表头行」：第 1 行只有一个合并标题
        import pandas as pd
        titled = tmp / "带标题.xlsx"
        with pd.ExcelWriter(titled, engine="openpyxl") as writer:
            pd.DataFrame([
                ["重庆财经学院2026-2027学年贫困生认定公示名单", None, None, None],
                ["序号", "姓名", "学院", "困难等级"],
                [1, "张三", "软件学院", "特别困难"],
                [2, "李四", "会计学院", "一般困难"],
            ]).to_excel(writer, sheet_name="Sheet1", index=False, header=False)
        _sid, tbl = list(spreadsheet.parse_file(titled))[0]
        check("大标题行被跳过，真正的表头生效", tbl["columns"], ["序号", "姓名", "学院", "困难等级"])
        check("标题表的数据行数", len(tbl["rows"]), 2)
        check("标题表的数据正确", tbl["rows"][0][1], "张三")

        # 无表头 → 自动列名；空文件 → 0 张表；非法后缀 → 报错
        (tmp / "无表头.csv").write_text("1,2\n3,4\n", encoding="utf-8")
        _sid, tbl = list(spreadsheet.parse_file(tmp / "无表头.csv"))[0]
        check("无表头自动生成列名", tbl["columns"], ["col1", "col2"])
        check("无表头时首行当数据", len(tbl["rows"]), 2)

        (tmp / "空.csv").write_text("", encoding="utf-8")
        check("空文件产出 0 张表", len(list(spreadsheet.parse_file(tmp / "空.csv"))), 0)
        try:
            list(spreadsheet.parse_file(tmp / "说明.docx"))
            check("非法后缀应报错", "没报错", "SpreadsheetError")
        except spreadsheet.SpreadsheetError:
            check("非法后缀应报错", "SpreadsheetError", "SpreadsheetError")

    # ---------- ② 与 tables 集成：入库 → SQL → 召回 ----------
    print("\n② 集成层（解析 → 入库 → 只读 SQL → 召回）")
    with temp_dir() as raw:
        tmp = Path(raw)
        make_fixtures(tmp)
        origin_dir, origin_db = tables.TABLE_DATA_DIR, tables.DB_PATH
        try:
            tables.TABLE_DATA_DIR, tables.DB_PATH = tmp, tmp / "tables.sqlite3"
            stats = tables.build(force=True, quiet=True)
            check("入库表数", stats.get("tables"), 5)
            truthy("files 数据集已注册", "files" in tables.DATASETS)
            truthy("list_sets 里能看见 files",
                   any(s["key"] == "files" and s["tables"] == 5 for s in tables.list_sets()))
            truthy("available() 判定可用", tables.available())

            # 中文文件名不再被吃掉，且不同表不撞名
            names = [row[0] for row in
                     tables.query("SELECT table_name FROM _tables")[1]]
            truthy("表名保留了中文", any("销售明细" in n for n in names))
            check("表名互不重复", len(set(names)), len(names))

            monthly = [n for n in names if "月度销售" in n][0]
            cols, rows, _trunc, err = tables.query(
                f"SELECT 区域, SUM(销售额) AS 合计 FROM {monthly} GROUP BY 区域 ORDER BY 合计 DESC")
            check("聚合查询无错", err, "")
            check("分组汇总结果正确", rows, [["华南", 135800.0], ["华东", 120000.5],
                                              ["华北", 98000.25]])

            client = [n for n in names if "客户名单" in n][0]
            cols, rows, _trunc, err = tables.query(
                f"SELECT 客户名称 FROM {client} ORDER BY 消费额 DESC")
            check("中文列排序查询", [r[0] for r in rows], ["王五", "张三", "李四"])

            # 三种问法都要能召回：按内容词、按文件名、按 sheet 名
            for phrase, keyword in (("销售额 区域 月度", "月度销售"),
                                    ("销售明细", "月度销售"),
                                    ("客户名单", "客户名单")):
                hits = tables.find_tables(phrase, limit=3)
                truthy(f"能召回：{phrase}", any(keyword in h.get("table", "") for h in hits))

            # 文件变动 → 签名变化 → 自动重建
            (tmp / "指标.tsv").write_text("指标\t数值\n活跃用户\t99999\n", encoding="utf-8")
            check("文件改了会触发重建", tables.build(force=False, quiet=True)["rebuilt"], True)
            check("查到新值", tables.query(
                f"SELECT 数值 FROM {[n for n in [r[0] for r in tables.query('SELECT table_name FROM _tables')[1]] if '指标' in n][0]}"
                " WHERE 指标='活跃用户'")[1], [["99999"]])
        finally:
            tables.TABLE_DATA_DIR, tables.DB_PATH = origin_dir, origin_db

    # ---------- ③ 行为不变性 ----------
    print("\n③ 行为不变性（目录里没有 Excel/CSV 时）")
    with temp_dir() as raw:
        tmp = Path(raw)
        (tmp / "假数据.md").write_text("| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        origin_dir, origin_db = tables.TABLE_DATA_DIR, tables.DB_PATH
        try:
            tables.TABLE_DATA_DIR, tables.DB_PATH = tmp, tmp / "tables.sqlite3"
            tables.build(force=True, quiet=True)
            truthy("没有表格文件时不注册 files", "files" not in tables.DATASETS)
            check("数据集数量仍是 3", len(tables.DATASETS), 3)
        finally:
            tables.TABLE_DATA_DIR, tables.DB_PATH = origin_dir, origin_db
            tables._register_file_dataset()          # 恢复成真实目录的状态

    print("\n" + "=" * 62)
    print(f"结果：{_PASSED} 项通过，{_FAILED} 项失败")
    print("=" * 62)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
