"""统一上传目录 + 自动解析 + 自动记忆 + Python 查表 的离线测试。

覆盖：
  ① services/uploads.py：落盘（中文名保留、同名不覆盖）、数据卡片、删除、取 DataFrame
  ② services/table_memory.py：卡片自动写入 / 脱敏、经验沉淀与回想、随文件删除清理
  ③ Python 查表：pandas 代码在沙箱里执行（df / pd / np 已注入）
  ④ web 上传接口：列表 / 上传 / 删除 / 令牌

不连真实数据库、不调模型；用临时目录，不污染 data/uploads。
跑法：python eval/_test_uploads.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))

import pandas as pd  # noqa: E402

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


def make_xlsx(path: Path) -> bytes:
    """造一个「大标题行 + 表头 + 数据」的真实形态 Excel，返回字节。"""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([
            ["重庆财经学院贫困生认定公示名单", None, None, None],
            ["序号", "姓名", "学院", "困难等级"],
            [1, "张三", "软件学院", "特别困难"],
            [2, "李四", "会计学院", "一般困难"],
            [3, "王五", "软件学院", "特别困难"],
        ]).to_excel(writer, sheet_name="Sheet1", index=False, header=False)
    return path.read_bytes()


def main() -> int:
    print("=" * 62)
    print("统一上传 / 自动解析 / 自动记忆 / Python 查表 测试")
    print("=" * 62)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        os.environ["UPLOAD_DIR"] = str(tmp / "uploads")
        os.environ["TABLE_MEMORY_PATH"] = str(tmp / "mem.json")
        try:
            from services.analytics import pysandbox
            from services.datasource import table_memory, uploads

            # ---------- ① 落盘与解析 ----------
            print("\n① 上传目录（落盘即解析）")
            truthy("目录自动创建", uploads.directory().is_dir())
            payload = make_xlsx(tmp / "学生名单.xlsx")

            entry = uploads.save("学生名单.xlsx", payload)
            check("文件名保留中文", entry["name"], "学生名单.xlsx")
            check("解析出 1 张表", entry["tables"], 1)
            check("解析出 3 行", entry["rows"], 3)
            check("状态为已解析", entry["status"], "已解析")

            again = uploads.save("学生名单.xlsx", payload)
            check("同名不覆盖而是改名", again["name"], "学生名单_1.xlsx")

            cards = uploads.profile_file(uploads.directory() / "学生名单.xlsx")
            check("卡片列名已去掉大标题行",
                  [f["name"] for f in cards[0]["columns"]], ["序号", "姓名", "学院", "困难等级"])
            grade = [f for f in cards[0]["columns"] if f["name"] == "困难等级"][0]
            check("枚举列列出取值", sorted(grade["values"]), ["一般困难", "特别困难"])

            # ---------- ② 自动记忆 ----------
            print("\n② 自动记忆（数据卡片 + 问答经验）")
            check("卡片自动写进记忆", table_memory.summary()["tables"], 2)
            card_text = table_memory.cards_text()
            truthy("卡片含列名", "学院" in card_text)
            truthy("示例值按列名脱敏（张三不出现）", "张三" not in card_text)
            truthy("学院取值不被误伤", "软件学院" in card_text)

            table_memory.remember_query("按学院统计人数",
                                        "df.groupby('学院').size()", table="t_x")
            check("经验已沉淀", table_memory.summary()["unique_questions"], 1)
            check("相似问题能回想", bool(table_memory.recall("按学院统计人数")), True)
            check("无关问题不召回", len(table_memory.recall("今天天气怎么样")), 0)

            # ---------- ③ 模型写 Python 查表 ----------
            print("\n③ Python 查表（df / pd / np 注入沙箱）")
            frame, used = uploads.load_dataframe("学生名单")
            check("取到正确的表", used.startswith("t_学生名单"), True)
            check("DataFrame 形状", frame.shape, (3, 4))

            code = "df.groupby('学院').size().sort_values(ascending=False)"
            out = pysandbox.run(code, {"df": frame, "pd": pd, "np": __import__("numpy")})
            check("分组统计执行成功", out["ok"], True)
            check("统计结果正确", out["result"].to_dict(), {"软件学院": 2, "会计学院": 1})

            out2 = pysandbox.run("result = df[df['困难等级']=='特别困难'].shape[0]",
                                 {"df": frame, "pd": pd})
            check("条件计数", out2["result_text"], "2")
            bad = pysandbox.run("import os", {"df": frame})
            check("沙箱仍然禁止 import", bad["ok"], False)

            # ---------- ④ 删除连带清理 ----------
            print("\n④ 删除（文件 + 记忆）")
            truthy("删除成功", uploads.delete("学生名单.xlsx"))
            check("记忆里卡片已清除", table_memory.summary()["tables"], 1)

            # ---------- ⑤ Web 接口 ----------
            print("\n⑤ Web 接口（上传 / 列表 / 删除 / 令牌）")
            import web as web_app
            client = web_app.app.test_client()
            listing = client.get("/api/uploads").get_json()
            truthy("列表接口可用", "files" in listing)

            resp = client.post("/api/uploads", data={
                "file": [(io.BytesIO(payload), "接口上传.xlsx")],
            }, content_type="multipart/form-data")
            check("上传返回 201", resp.status_code, 201)
            check("上传即解析", resp.get_json()["saved"][0]["tables"], 1)
            names = [f["name"] for f in client.get("/api/uploads").get_json()["files"]]
            truthy("文件出现在列表里", "接口上传.xlsx" in names)

            check("无令牌也能删（未设 ADMIN_TOKEN）",
                  client.delete("/api/uploads/接口上传.xlsx").status_code, 200)
            os.environ["ADMIN_TOKEN"] = "secret"
            check("设了令牌后无令牌被拒",
                  client.delete("/api/uploads/接口上传.xlsx").status_code, 401)
            os.environ.pop("ADMIN_TOKEN", None)
        finally:
            os.environ.pop("UPLOAD_DIR", None)
            os.environ.pop("TABLE_MEMORY_PATH", None)

    print("\n" + "=" * 62)
    print(f"结果：{_PASSED} 项通过，{_FAILED} 项失败")
    print("=" * 62)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
