# -*- coding: utf-8 -*-
"""DeepSeek 账户余额查询。

只做一件事：调官方接口拿余额并排版显示。
（Token 用量统计已按需求移除 —— DeepSeek 本身也没有公开的用量查询接口。）

用法：
    from usage_api import fetch_balance, format_balance, BalanceError
    bal = fetch_balance(api_key)
    text = format_balance(bal)
"""

from datetime import datetime

import requests

TIMEOUT = 12


class BalanceError(Exception):
    """余额查询失败，message 可直接显示给用户。"""


def fetch_balance(api_key: str) -> dict:
    """查账户余额。

    返回 {'available': bool, 'total': '34.14', 'currency': 'CNY',
          'granted': '0.00', 'topped_up': '34.14'}
    接口：GET https://api.deepseek.com/user/balance
    """
    key = (api_key or "").strip()
    if not key:
        raise BalanceError("还没设置 DeepSeek API Key。\n右键点肥鱼 →「设置 Key」。")

    try:
        r = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise BalanceError("余额查询超时，检查网络。")
    except requests.exceptions.ConnectionError:
        raise BalanceError("连不上 api.deepseek.com，检查网络或代理。")
    except requests.exceptions.RequestException as e:
        raise BalanceError(f"余额查询失败：{type(e).__name__}")

    if r.status_code == 401:
        raise BalanceError("API Key 无效或已失效（HTTP 401）。")
    if r.status_code != 200:
        raise BalanceError(f"余额接口返回 HTTP {r.status_code}")

    try:
        data = r.json()
    except ValueError:
        raise BalanceError("余额接口返回的不是 JSON")

    infos = data.get("balance_infos") or []
    if not infos:
        return {"available": bool(data.get("is_available")), "total": "",
                "currency": "", "granted": "", "topped_up": ""}

    info = infos[0]
    return {
        "available": bool(data.get("is_available")),
        "total": str(info.get("total_balance", "")),
        "currency": str(info.get("currency", "CNY")),
        "granted": str(info.get("granted_balance", "")),
        "topped_up": str(info.get("topped_up_balance", "")),
    }


def _symbol(currency: str) -> str:
    cur = (currency or "CNY").upper()
    if cur in ("CNY", "RMB"):
        return "¥"
    if cur == "USD":
        return "$"
    return ""


def format_balance(bal: dict, checked_at: str = "") -> str:
    """把余额排成面板文本。行数尽量少。"""
    if not bal:
        return "余额信息为空"

    sym = _symbol(bal.get("currency"))
    total = bal.get("total") or "—"
    L = [f"💰 账户余额　{sym}{total}"]

    bits = []
    topped = bal.get("topped_up")
    granted = bal.get("granted")
    if topped and topped not in ("0.00", "0"):
        bits.append(f"充值 {sym}{topped}")
    if granted and granted not in ("0.00", "0"):
        bits.append(f"赠送 {sym}{granted}")
    if bits:
        L.append("　".join(bits))

    if not bal.get("available", True):
        L.append("⚠️ 余额不足，可能无法继续调用")

    if checked_at:
        L.append(f"查询于 {checked_at}")
    return "\n".join(L)


if __name__ == "__main__":
    # 命令行自测：python usage_api.py <api_key>
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        bal = fetch_balance(k)
        print(format_balance(bal, datetime.now().strftime("%H:%M:%S")))
    except BalanceError as e:
        print(f"[失败] {e}")
