# 在打包好的 exe 环境里真正导入并调用 weather_api / usage_api
#
# 背景：exe 里已经带了 GUI，没法直接跑命令行；但 PyInstaller 冻结后的
# sys.executable 还是这个 exe。用「--selftest 参数 + 子进程」的方式让 exe
# 自己再启动一次并执行这里的代码，就能确定性地验证模块是否打进包里。
#
# 这段代码会被嵌进 桌宠.py 的启动逻辑里（仅当带 --selftest 参数时执行）。

import io
import sys


def run_selftest():
    """验证两个新增模块在冻结环境里能用。返回退出码。"""
    # 注意：打包成 --windowed 之后 sys.stdout / sys.stderr 都是 None，
    # 直接调 sys.stdout.reconfigure() 会抛 AttributeError
    # （这个坑就是第一次跑 exe 自检时抓到的）。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    out = io.StringIO()

    def p(s=""):
        out.write(str(s) + "\n")

    p("=== 冻结环境自检 ===")
    p(f"  frozen       : {getattr(sys, 'frozen', False)}")
    p(f"  executable   : {sys.executable}")
    p(f"  _MEIPASS     : {getattr(sys, '_MEIPASS', '(无)')}")
    p("")

    ok = True

    # ---- weather_api ----
    try:
        from weather_api import query_weather, CITY_CODES
        p(f"  weather_api 导入成功，内置城市 {len(CITY_CODES)} 个")
        r = query_weather("北京", want_forecast=False)
        if r.ok:
            p(f"  天气查询   : {r.source}  {r.summary()}")
        else:
            p(f"  天气查询失败: {r.error.splitlines()[0] if r.error else '未知'}")
            ok = False
    except Exception as e:
        p(f"  weather_api 失败: {type(e).__name__}: {e}")
        ok = False

    p("")

    # ---- usage_api ----
    try:
        from usage_api import fetch_balance, BalanceError
        p("  usage_api 导入成功")
        try:
            bal = fetch_balance("")          # 空 key 应报友好错误，说明模块逻辑正常
            p(f"  余额查询   : {bal}")
        except BalanceError as e:
            first = str(e).splitlines()[0]
            p(f"  余额查询   : 按预期报错 -> {first}")
    except Exception as e:
        p(f"  usage_api 失败: {type(e).__name__}: {e}")
        ok = False

    p("")

    # ---- sprites ----
    try:
        import os
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        spdir = os.path.join(base, "sprites")
        pngs = [f for f in os.listdir(spdir) if f.endswith(".png")] if os.path.isdir(spdir) else []
        p(f"  sprites    : {len(pngs)} 个 png  ({spdir})")
        if not pngs:
            ok = False
    except Exception as e:
        p(f"  sprites 检查失败: {type(e).__name__}: {e}")
        ok = False

    p("")
    p(f"=== 结论: {'全部通过 OK' if ok else '有失败项'} ===")

    # 写到文件（GUI 程序没有 stdout，必须落盘）
    try:
        log = os.path.join(os.path.expanduser("~"), "feiyu_selftest.txt")
        with open(log, "w", encoding="utf-8") as f:
            f.write(out.getvalue())
    except Exception:
        pass
    return 0 if ok else 1
