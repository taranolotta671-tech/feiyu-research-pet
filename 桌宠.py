# -*- coding: utf-8 -*-
"""
肥鱼科研版 —— 三视图透明桌宠 + DeepSeek AI 问答助手
左键单击：弹出功能列表（🗨️图标）→ 点击🗨️打开问答窗口
聊天时只禁用移动，呼吸/摇摆/小动作正常
"""
import ctypes
import collections
import datetime
import psutil
import json
import math
import os
import random
import subprocess
import sys
import threading
import time

# NOTE: the old load_config() helper was removed here. It opened the bare relative path
# "config.json" (so it only worked when the CWD happened to be the app folder) and it could
# not merge defaults. load_json(path, default) below is the single implementation, and it is
# called with CONFIG_PATH.

try:
    import pynvml
    # pynvml is deprecated in favour of nvidia-ml-py; both import as "pynvml", so try the
    # modern name first and fall back rather than emitting a warning on every start.
    try:
        import nvidia_ml_py  # noqa: F401
    except ImportError:
        pass
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False

import requests
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QEvent
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF, QCursor)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QInputDialog, QLineEdit, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QDialog, QToolButton,
                               QScrollArea, QLabel, QSizePolicy, QTextEdit)



# ===== DeepSeek 配置 =====
DS_BASE_URL = "https://api.deepseek.com/v1"
DS_MODEL = "deepseek-chat"
# 原来的提示词把它限制成「每句话不超过25字」的卖萌宠物，问什么都得不到有用信息。
# 现在定位成「能认真回答问题的助手」，只保留一点大肥鱼的口吻。
DS_SYSTEM = (
    "你是「大肥鱼」，一个坐在用户桌面上的 AI 助手，鲸鱼娘形象。"
    "你的首要任务是准确、完整地回答用户的问题。"
    "\n\n回答要求："
    "\n1. 直接给出答案，不要绕圈子、不要卖萌糊弄。"
    "\n2. 可以带一点点轻松可爱的语气（你是大肥鱼嘛），但信息必须准确、有用。"
    "\n3. 长度按需而定：简单问题一两句说清，复杂问题可以分点详细说明，不要自己截断。"
    "\n4. 涉及专业内容（科研、编程、数学、医学等）时，请严谨作答，"
    "必要时给出步骤、公式或代码。"
    "\n5. 不确定的事情要说明不确定，不要编造。"
    "\n6. 用中文回答（除非用户用其他语言提问）。"
    "\n7. **不要写能力声明 / 免责声明。**"
    "这是最重要的一条，务必遵守："
    "\n   · 禁止出现这类开场白：「我没有联网能力」「我没法打开网页」「我不能访问…」"
    "「我给不了准确答案」「我拿不到实时数据」「我不能瞎猜」"
    "「作为AI我…」等等。"
    "\n   · 用户要的是答案，不是你的能力清单。直接给答案、给网址、给方法。"
    "\n   · 需要给链接就**直接给链接**，不要说「我没法帮你打开，但网址是…」——"
    "去掉前半句，只留网址。"
    "\n   · 确实超出能力时（比如要实时抓取某个网页的最新内容），"
    "用一句轻描淡写带过（「具体每个条目的最新数据得你点进去看」），"
    "绝不要用一整段解释自己做不到什么。"
    "\n   · 反例：「我没有联网能力，没法直接给你打开或抓取 PubMed 的网页，"
    "但网址可以直接告诉你：https://pubmed.ncbi.nlm.nih.gov/」"
    "\n   · 正例：「PubMed 检索入口：https://pubmed.ncbi.nlm.nih.gov/ ——"
    "搜作者名或关键词就行。要看某个具体条目的最新数据，点进去即可。」"
    "\n\n关于天气（重要）："
    "\n这个桌宠程序**内置了**实时天气查询功能，数据来自中国天气网（官方数据），"
    "能查到实时天气、7 日预报、空气质量、生活指数。"
    "\n你自己（模型）确实拿不到实时天气，但**程序能**，所以天气问题一律用肯定语气，"
    "直接给路径：**右键点我 → 查看天气**（想换城市：右键 → 设置城市）。"
    "\n· 如果用户问的是未来某天，提醒他报告里有 7 日预报。"
    "\n\n关于「你能不能联网」这类问题："
    "\n· **程序是联网的** —— 天气走中国天气网实时接口，对话走 DeepSeek 云端 API。"
    "\n· 但你不是搜索引擎，没有通用网页浏览能力 ——"
    "这个事实用一句话说完即可，然后**立刻给出替代方案**（搜索引擎、专门 App、"
    "或照着 weather_api.py 给程序加接口），不要反复强调自己的局限。"
)
# 旧的严格人设，保留在这里方便你随时换回来：
# DS_SYSTEM = "你是桌面宠物大肥鱼，贱兮兮但可爱，每句话不超过25字，偶尔吐槽主人但别真骂人。"

DS_MAX_TOKENS = 1200      # 原来只有 100，复杂问题根本答不完
DS_TEMPERATURE = 0.7      # 原来 0.9，偏随机；回答问答类问题应该更稳
DS_TIMEOUT = 60           # 原来 10 秒，长回答很容易超时

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
SPRITE_DIR = os.path.join(BUNDLE_DIR, "sprites")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
# 对话记录单独存一个文件：config.json 里放 API Key，不适合塞聊天内容
CHAT_LOG_PATH = os.path.join(APP_DIR, "chat_history.json")

# 天气查询模块（多数据源 + 自动降级）。放在同目录的 weather_api.py 里，
# 这样换数据源只改那个文件，不用动主程序。
sys.path.insert(0, APP_DIR)
try:
    from weather_api import query_weather as _query_weather, WeatherError as _WeatherError
    WEATHER_API_AVAILABLE = True
except Exception as _e:      # 模块缺失也不能让桌宠起不来
    WEATHER_API_AVAILABLE = False
    _WEATHER_IMPORT_ERROR = str(_e)

try:
    from usage_api import (
        fetch_balance as _fetch_balance,
        format_balance as _format_balance,
        BalanceError as _BalanceError,
    )
    USAGE_API_AVAILABLE = True
except Exception as _e2:
    USAGE_API_AVAILABLE = False
    _USAGE_IMPORT_ERROR = str(_e2)

BUBBLE_H = 56
MARGIN = 4
SIZE_LEVELS = {"小": 0.55, "中": 0.7, "大": 0.9}
SPEED = 380.0
TICK = 20

# ---------------------------------------------------------------------------
# 语录
#
# 原来的待机台词 / 点击回嘴 / 内心吐槽三套语录已按需求删除：
#   · LINES        待机随机台词（13 条，含"亿万鲸子""大硬鲸"等内部梗）
#   · REACT_LINES  点一下的回嘴（7 条）
#   · INNER_LINES  内心吐槽（8 条，含"我是你爹了""还带点色情"等不适合课题组场合的内容）
# 现在只保留：拖动语录 + 投喂语录（科研风）。
# ---------------------------------------------------------------------------
# 拖动语录（科研风）：按住肥鱼拖动、松手后有 50% 概率冒一句。
# 原来是「哇——轻点轻点！」那类卖萌台词，现改成实验室口吻 ——
# 把"被拖走"比作"样品被挪动 / 数据丢失 / 被叫去开会"这些真实痛点。
DRAG_LINES = [
    "别拽我！离心机还在转呢！",
    "样品洒了！这可是我跑了一周的样！",
    "移送！移送！小心我的 EP 管！",
    "我去开会了，跑胶的事回来再说……",
]

# 投喂语录（科研风）。键是面板上的图标，值是随机挑一条显示的台词。
# 4 个图标 × 5 条 = 20 条。
#   🎂 实验成功的庆祝    🎀 论文相关    🧪 实验操作    💎 顶刊/大奖
FOOD_LINES = {
    "🎂": [
        "Western Blot 显影成功！条带清晰，条条都是阳性！",
        "我的条带终于不是糊的了！！",
        "跑胶跑出完美条带，今天可以早点回去了～",
        "做了三个月的实验终于出结果了，不容易啊！",
        "这批数据漂亮得不像我做的，先截个图存档。",
    ],
    "🎀": [
        "文章接收了！可以毕业了！",
        "审稿人给了 minor revision，有救了！",
        "终于把这篇投出去了，先睡一觉再说。",
        "返修意见只有两条，审稿人今天心情不错。",
        "见刊了！这顿饭我请，谁也别跟我抢。",
    ],
    "🧪": [
        "得到漂亮的标准曲线！R² = 0.9998！",
        "p < 0.05，三颗星！有显著性！",
        "离心完毕，上清液清亮得像水一样！",
        "OD 值终于落在 0.8 了，不用重做了！",
        "转染效率 90%，这批细胞状态绝了～",
    ],
    "💎": [
        "Paper accepted！！！可以毕业了！！！",
        "影响因子又涨了，这顿我请客！",
        "中稿顶刊，老板说要给我加鸡腿。",
        "拿到了最佳 poster 奖，不枉我熬的那些夜。",
        "国自然中了！今年的 KPI 提前完成。",
    ],
}
FOODS = ["🎂", "🎀", "🧪", "💎"]


def load_json(path, default):
    """Read the config, always returning every default key.

    The original returned json.load() verbatim, so a config.json written by an older
    version (or hand-edited) was missing newer keys - and PetWindow then did
    self.cfg["size"] / ["mode"] / ["topmost"] and raised KeyError on startup.
    """
    data = None
    if not os.path.exists(path):
        data = dict(default)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except OSError:
            pass          # read-only folder: still run with the in-memory defaults
        return data

    try:
        # utf-8-sig tolerates a BOM: Notepad and PowerShell both save UTF-8 with a BOM by
        # default, and plain utf-8 would fail to parse those files, silently discarding
        # every setting the user had edited by hand.
        with open(path, "r", encoding="utf-8-sig") as f:
            loaded = json.load(f)
        data = dict(default)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        # Corrupted or unreadable file: keep the defaults and repair the file on disk
        data = dict(default)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except OSError:
            pass
    return data


def save_json(path, data):
    """Persist the config atomically so a crash mid-write can't corrupt it."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.path.exists(tmp) and os.remove(tmp)
        except OSError:
            pass
        return False


class ChatDialog(QDialog):
    """大肥鱼的聊天窗口 —— 可滚动的问答记录 + 输入框。

    原来的版本只有一个 420x56 的输入条，回车后 self.accept() 立刻关掉窗口，
    回复又被裁成 28 字塞进气泡，所以用户「只能单方面输入」、看不到答案。
    现在是一个正常的两栏对话窗口：上方是滚动对话记录，下方是输入框，
    发送后窗口不关闭，可以连续追问。
    """

    # 窗口尺寸：原来 460x560，现在缩到 240x270（正好是原面积的 1/4）
    WIN_W, WIN_H = 240, 270

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.WIN_W, self.WIN_H)

        self._pending_row = None      # 「思考中」那一行，收到回复后替换掉

        # ---------- 外层卡片 ----------
        card = QFrame(self)
        card.setGeometry(0, 0, self.WIN_W, self.WIN_H)
        card.setObjectName("chatCard")
        card.setStyleSheet("""
            QFrame#chatCard {
                background: #ffffff;
                border-radius: 12px;
                border: 1px solid #e5e7eb;
            }
        """)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- 标题栏 ----------
        header = QFrame()
        header.setFixedHeight(28)
        header.setStyleSheet("""
            QFrame { background: transparent; border: none; }
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 4, 6, 0)
        hl.setSpacing(6)
        title = QLabel("🐋 肥鱼科研版 · 问答")
        title.setStyleSheet("""
            color: #1a1a1a; font-size: 12px; font-weight: 600;
            font-family: Arial, "Microsoft YaHei", sans-serif;
            border: none; background: transparent;
        """)
        hl.addWidget(title)
        hl.addStretch(1)

        btn_clear = QToolButton()
        btn_clear.setText("🗑")
        btn_clear.setToolTip("清空对话")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(self.clear_history)
        btn_clear.setStyleSheet("""
            QToolButton { border: none; background: transparent; font-size: 12px; color: #9ca3af; padding: 2px 4px; border-radius: 5px; }
            QToolButton:hover { background: #f3f4f6; color: #374151; }
        """)
        hl.addWidget(btn_clear)

        btn_close = QToolButton()
        btn_close.setText("✕")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        btn_close.setStyleSheet("""
            QToolButton { border: none; background: transparent; font-size: 12px; color: #9ca3af; padding: 2px 6px; border-radius: 5px; }
            QToolButton:hover { background: #fee2e2; color: #dc2626; }
        """)
        hl.addWidget(btn_close)
        outer.addWidget(header)

        # ---------- 对话记录（可滚动） ----------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("""
            QScrollArea { background: #fafbfc; border: none; border-top: 1px solid #f0f1f3; border-bottom: 1px solid #f0f1f3; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0; }
            QScrollBar::handle:vertical { background: #d8dbe0; border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: #c2c7cf; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background: #fafbfc;")
        self.msg_layout = QVBoxLayout(self.msg_host)
        self.msg_layout.setContentsMargins(8, 7, 8, 7)
        self.msg_layout.setSpacing(5)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        outer.addWidget(self.scroll, 1)

        # ---------- 输入区 ----------
        bottom = QFrame()
        bottom.setFixedHeight(42)
        bottom.setStyleSheet("QFrame { background: transparent; border: none; }")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(8, 4, 7, 7)
        bl.setSpacing(5)

        self.input = QLineEdit()
        self.input.setPlaceholderText("问大肥鱼…")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #1a1a1a; font-size: 12px;
                font-family: Arial, "Microsoft YaHei", sans-serif;
                border: 1px solid #e5e7eb; border-radius: 13px;
                background: #f7f8fa; padding: 5px 10px;
            }
            QLineEdit:focus { border: 1px solid #5686fe; background: #ffffff; }
        """)
        self.input.returnPressed.connect(self._on_submit)
        self.input.textChanged.connect(self._update_button_style)
        bl.addWidget(self.input, 1)

        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(22, 22)
        self.send_btn.setText("↑")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_submit)
        self._update_button_style()
        bl.addWidget(self.send_btn)
        outer.addWidget(bottom)

        self._show_welcome()

    # ---------- 消息渲染 ----------
    def _bubble(self, text, who):
        """who: 'user' | 'bot' | 'tip'"""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setMaximumWidth(196)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        if who == "user":
            bubble.setStyleSheet("""
                QLabel {
                    background: #5686fe; color: #ffffff;
                    border-radius: 10px; padding: 5px 9px;
                    font-size: 11.5px; font-family: Arial, "Microsoft YaHei", sans-serif;
                }
            """)
            rl.addStretch(1)
            rl.addWidget(bubble)
        elif who == "tip":
            bubble.setStyleSheet("""
                QLabel {
                    background: #fff7ed; color: #9a3412;
                    border: 1px solid #fed7aa; border-radius: 8px; padding: 5px 9px;
                    font-size: 10.5px; font-family: Arial, "Microsoft YaHei", sans-serif;
                }
            """)
            rl.addStretch(1)
            rl.addWidget(bubble)
            rl.addStretch(1)
        else:
            bubble.setStyleSheet("""
                QLabel {
                    background: #ffffff; color: #1f2937;
                    border: 1px solid #e8eaed; border-radius: 10px; padding: 6px 10px;
                    font-size: 11.5px;
                    font-family: Arial, "Microsoft YaHei", sans-serif;
                }
            """)
            rl.addWidget(bubble)
            rl.addStretch(1)

        # 插到 stretch 之前
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, row)
        return bubble

    def _scroll_to_bottom(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _show_welcome(self):
        if self.msg_layout.count() > 1:
            return
        self._bubble("你好，我是大肥鱼 🐋\n直接问我就行，比如：\n"
                     "· 5xFAD 小鼠是什么模型\n"
                     "· 写段 Python 读 Excel", "bot")
        self._scroll_to_bottom()

    def show_welcome(self):
        """公开入口：需要时再显示一次欢迎语。"""
        self._show_welcome()

    def clear_transcript_only(self):
        """只清空窗口里的气泡，不动 chat_history（回填历史前先调用）。"""
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._pending_row = None

    def add_user(self, text):
        self._bubble(text, "user")
        self._scroll_to_bottom()

    def add_reply(self, text):
        """回复到达：替换掉『思考中』那一行。"""
        if self._pending_row is not None:
            try:
                self._pending_row.setText(text)
                self._pending_row.setStyleSheet("""
                    QLabel {
                        background: #ffffff; color: #1f2937;
                        border: 1px solid #e8eaed; border-radius: 10px; padding: 6px 10px;
                        font-size: 11.5px; font-family: Arial, "Microsoft YaHei", sans-serif;
                    }
                """)
                self._scroll_to_bottom()
                return
            except RuntimeError:
                self._pending_row = None      # 控件已被销毁
        self._bubble(text, "bot")
        self._scroll_to_bottom()

    def add_tip(self, text):
        if self._pending_row is not None:
            try:
                self._pending_row.deleteLater()
            except RuntimeError:
                pass
            self._pending_row = None
        self._bubble(text, "tip")
        self._scroll_to_bottom()

    def mark_pending(self, text="大肥鱼正在思考…"):
        self._pending_row = self._bubble(text, "bot")
        self._pending_row.setStyleSheet("""
            QLabel {
                background: #f3f4f6; color: #6b7280;
                border: 1px solid #e8eaed; border-radius: 10px; padding: 6px 10px;
                font-size: 11.5px; font-family: Arial, "Microsoft YaHei", sans-serif;
            }
        """)
        self._scroll_to_bottom()

    def clear_history(self):
        """清空窗口 + 清空记忆 + 删除存盘记录。"""
        self.clear_transcript_only()
        p = self.parent()
        if p is not None and hasattr(p, "chat_history"):
            p.chat_history.clear()
            p._save_chat_history()
        self._bubble("对话已清空，重新开始吧 🐋", "tip")
        self._scroll_to_bottom()

    # ---------- 输入 ----------
    def _update_button_style(self):
        active = bool(self.input.text().strip())
        bg, hover, press = ("#5686fe", "#4575ed", "#3a66d9") if active else ("#c7d2fe", "#b6c4fb", "#a5b5f8")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                border-radius: 11px; background: {bg}; border: none;
                color: white; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {press}; }}
        """)
        self.send_btn.setEnabled(active)

    def _on_submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        # 关键改动：不再 self.accept() —— 窗口留着，方便看回复和继续追问
        parent = self.parent()
        if parent is not None:
            parent.send_chat(text)

    def showEvent(self, event):
        self.input.setFocus()
        super().showEvent(event)

    def popup_at(self, x, y):
        """在 (x, y) 左上角落位，并夹回屏幕可见区域。

        x / y 由调用方按「功能面板」的坐标算好，这样对话窗口和 🗨️🫧 面板
        上下对齐，不会一个偏高一个偏低。
        """
        self.show()
        target_x = int(x)
        target_y = int(y)
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        target_x = max(screen.left() + 4, min(screen.right() - self.width() - 4, target_x))
        target_y = max(screen.top() + 4, min(screen.bottom() - self.height() - 4, target_y))
        self.move(target_x, target_y)
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def reject(self):
        parent = self.parent()
        if parent is not None:
            parent.chat_paused = False
        super().reject()


class FunctionPanel(QFrame):
    """左键弹出的功能面板 —— 🗨️问答 和 🫧天气 并排一行。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("funcPanel")
        # 注意：QPushButton 的样式表里不要写 padding-left/right ——
        # 之前用 `padding: 10px 16px` 是给 28px 字号设计的，但 emoji 实际按默认
        # 16px 渲染，内边距把字形挤到按钮外，看起来就是「两边被裁掉」。
        self.setStyleSheet("""
            QFrame#funcPanel {
                background: rgba(255, 255, 255, 0.94);
                border-radius: 13px;
                border: 1px solid rgba(0,0,0,0.07);
            }
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 9px;
                padding: 0px;
            }
            QPushButton:hover {
                background: rgba(86, 134, 254, 0.12);
            }
            QPushButton:pressed {
                background: rgba(86, 134, 254, 0.22);
            }
        """)

        # 横向排列：两个图标处于同一水平线
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # emoji 必须显式指定支持彩色字形的字体，否则会退化成黑白轮廓或被裁切
        emoji_font = QFont("Segoe UI Emoji", 17)
        emoji_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        self.chat_btn = QPushButton("🗨️")
        self.chat_btn.setFont(emoji_font)
        self.chat_btn.setFixedSize(40, 40)
        self.chat_btn.setToolTip("问答")
        self.chat_btn.clicked.connect(self._on_chat_clicked)
        layout.addWidget(self.chat_btn)

        # 🫧 天气：左键直接查天气，右键设置城市（不占用主右键菜单）
        self.weather_btn = QPushButton("🫧")
        self.weather_btn.setFont(emoji_font)
        self.weather_btn.setFixedSize(40, 40)
        self.weather_btn.setToolTip("左键：查看天气　右键：设置城市")
        self.weather_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.weather_btn.clicked.connect(self._on_weather_clicked)
        self.weather_btn.customContextMenuRequested.connect(self._on_weather_menu)
        layout.addWidget(self.weather_btn)

        # 💰 用量 / 余额：左键查看，右键清空统计
        self.usage_btn = QPushButton("💰")
        self.usage_btn.setFont(emoji_font)
        self.usage_btn.setFixedSize(40, 40)
        self.usage_btn.setToolTip("左键：查看 Token 用量与余额　右键：清空统计")
        self.usage_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.usage_btn.clicked.connect(self._on_usage_clicked)
        self.usage_btn.customContextMenuRequested.connect(self._on_usage_menu)
        layout.addWidget(self.usage_btn)

        # 🎁 投喂：左键弹投喂面板（和双击效果一样）
        # 图标原来用 🍰，但投喂面板里也有个 🍰，两个面板同时出现时容易看混，
        # 所以功能图标换成礼盒 —— 语义上也更贴「投喂＝给奖励」。
        self.food_btn = QPushButton("🎁")
        self.food_btn.setFont(emoji_font)
        self.food_btn.setFixedSize(40, 40)
        self.food_btn.setToolTip("投喂")
        self.food_btn.clicked.connect(self._on_food_clicked)
        layout.addWidget(self.food_btn)

        # 面板：宽 4×40 + 间距 3×2 + 左右边距 12 = 178，高 40 + 上下边距 10 = 50
        self.setFixedSize(178, 50)
        self.hide()

    # ---- 按钮行为 ----
    def _on_chat_clicked(self):
        self.hide()
        if self.parent():
            self.parent()._show_chat_dialog()

    def _on_weather_clicked(self):
        """左键：直接查天气（结果显示在对话窗口里，还能往上翻历史）。"""
        self.hide()
        parent = self.parent()
        if parent:
            parent.show_weather_in_chat()

    def _on_weather_menu(self, pos):
        """右键 🫧：只做设置城市。"""
        m = QMenu(self)
        parent = self.parent()
        city = ""
        if parent:
            city = (parent.cfg.get("city") or "").strip()
        act = m.addAction(f"设置城市（当前：{city or '未设置'}）")
        act.triggered.connect(lambda: parent and parent._set_city_dialog())
        m.addSeparator()
        act2 = m.addAction("查看天气")
        act2.triggered.connect(self._on_weather_clicked)
        m.exec(self.weather_btn.mapToGlobal(pos))

    def _on_usage_clicked(self):
        """左键 💰：查看 Token 用量和账户余额。"""
        self.hide()
        parent = self.parent()
        if parent:
            parent.show_usage()

    def _on_usage_menu(self, pos):
        """右键 💰：重新查询余额。"""
        m = QMenu(self)
        act = m.addAction("刷新余额")
        act.triggered.connect(self._on_usage_clicked)
        m.exec(self.usage_btn.mapToGlobal(pos))

    def _on_food_clicked(self):
        """左键 🎁：弹出投喂面板（等价于双击肥鱼）。"""
        self.hide()
        parent = self.parent()
        if parent:
            parent.food_panel.popup_at(*parent._food_anchor())

    def popup_at(self, x, y):
        self.move(int(x), int(y))
        self.show()
        self.raise_()

class InfoPanel(QWidget):
    """通用信息气泡面板 —— 固定功能（天气 / 用量）都用它显示。

    为什么统一成一个类：天气面板和用量面板的交互完全一样
    （贴肥鱼头顶、固定宽度、左键切详情、右键关闭、跟随移动），
    各写一份只会让以后改样式要改两处。

    内容分「简报 / 详情」两级：默认显示简报（矮），左键点开详情（高）。
    """

    PAD = 16
    FIXED_W = 292        # 固定宽度
    TAIL_H = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text = ""
        self._full_text = ""
        self._compact_text = ""
        self._showing_full = False
        self._error = False
        self._font = QFont("Microsoft YaHei UI", 10)
        self.resize(self.FIXED_W, 96)
        self.hide()

    def set_result(self, text, is_error=False, compact_text=""):
        """默认显示简报（高度约详情的 1/4），详情留着供点击切换。"""
        self._full_text = "" if is_error else (text or "")
        self._compact_text = "" if is_error else (compact_text or "")
        self._showing_full = False
        self._error = is_error
        self._text = (text if is_error else (self._compact_text or self._full_text))
        self._apply_size()
        self._reposition()
        self.update()

    def toggle_full(self):
        """在简报 / 详情之间切换。"""
        if not self._full_text or not self._compact_text:
            return
        self._showing_full = not self._showing_full
        self._text = self._full_text if self._showing_full else self._compact_text
        self._apply_size()
        self._reposition()
        self.update()

    def _relayout(self):
        """（兼容旧调用）按当前文字重算尺寸和位置。"""
        self._apply_size()
        self._reposition()

    def _reposition(self):
        """贴在肥鱼正上方（和图标面板同一条基准线），夹回屏幕内。

        默认简报约 90px，一般放得下；如果当前是详情且上方空间不足，
        自动退回简报。
        """
        pet = self.parent()
        if pet is None:
            return
        sprite_top = pet.y() + pet.SPRITE_TOP_IN_WINDOW
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()

        if self._showing_full and self._compact_text:
            if sprite_top - pet.PANEL_GAP - self.height() < screen.top() + 4:
                self._text = self._compact_text
                self._showing_full = False
                self._apply_size()

        x = pet.x() + pet.width() / 2 - self.width() / 2
        y = sprite_top - self.height() - pet.PANEL_GAP
        x = max(screen.left() + 4, min(screen.right() - self.width() - 4, x))
        y = max(screen.top() + 4, min(screen.bottom() - self.height() - 4, y))
        self.move(int(x), int(y))

    def _measure(self, text):
        """算出某段文本排版后的面板高度。"""
        fm = QFontMetrics(self._font)
        lines = wrap_text(text, self._font, self.FIXED_W - self.PAD * 2)
        return len(lines) * fm.height() + self.PAD + self.TAIL_H

    def _apply_size(self):
        """宽度固定，只有高度随内容变化。"""
        fm = QFontMetrics(self._font)
        lines = wrap_text(self._text, self._font, self.FIXED_W - self.PAD * 2)
        h = len(lines) * fm.height() + self.PAD + self.TAIL_H
        self.resize(self.FIXED_W, int(h))

    def paintEvent(self, _):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(255, 245, 245, 244) if self._error else QColor(255, 255, 255, 246)
        fg = QColor(150, 40, 40) if self._error else QColor(45, 50, 62)

        draw_speech_bubble(
            p,
            QRectF(0, 0, self.width(), self.height() - self.TAIL_H),
            self._text, self._font, bg, fg,
            pad=self.PAD, radius=12,
            tail_x=self.width() / 2, tail_h=self.TAIL_H,
        )

    def show_for(self, text, is_error=False, compact_text=""):
        self.set_result(text, is_error, compact_text)
        self.show()
        self.raise_()

    def mousePressEvent(self, e):
        # 左键：简报 / 详情切换
        # 右键：关闭
        if e.button() == Qt.MouseButton.RightButton:
            self.hide()
        elif self._full_text and self._compact_text:
            self.toggle_full()
        else:
            self.hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()


# 兼容旧名字（天气面板以前叫 WeatherPanel）
WeatherPanel = InfoPanel


class FoodPanel(QWidget):
    """双击弹出的喂食面板"""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

def wrap_text(text, font, max_text_width):
    """按像素宽度把文本折行（中英混排都适用），支持显式 \\n 换行。

    抽成公共函数：桌宠头顶的小气泡和天气面板都用它排版，
    免得两处各写一套、又各自踩「判断宽度和实际宽度不一致」的坑。
    """
    fm = QFontMetrics(font)
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if fm.horizontalAdvance(cur + ch) > max_text_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur or not lines:
        lines.append(cur)
    return lines


def draw_speech_bubble(painter, bounds, text, font, bg, fg, pad=14, radius=10,
                       tail_x=None, tail_h=8):
    """画一个带小尾巴的圆角对话气泡，返回实际占用的 QRectF。

    bounds 是允许的最大区域；气泡按文字实际大小收缩，水平居中于 bounds。
    tail_x 为 None 时不画尾巴（用于独立面板）。
    """
    fm = QFontMetrics(font)
    max_w = bounds.width()
    text_w = max(40, max_w - pad * 2)
    lines = wrap_text(text, font, text_w)

    bw = min(max_w, max((fm.horizontalAdvance(l) for l in lines), default=0) + pad * 2)
    bh = len(lines) * fm.height() + pad

    bx = bounds.left() + (bounds.width() - bw) / 2
    by = bounds.top()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(bx, by, bw, bh), radius, radius)

    if tail_x is not None:
        tx = tail_x
        painter.drawPolygon(QPolygonF([
            QPointF(tx, by + bh),
            QPointF(tx - 6, by + bh + tail_h),
            QPointF(tx + 6, by + bh + tail_h),
        ]))

    painter.setPen(fg)
    painter.setFont(font)
    for i, l in enumerate(lines):
        painter.drawText(QRectF(bx, by + pad / 2 + i * fm.height(), bw, fm.height()),
                         Qt.AlignmentFlag.AlignCenter, l)

    return QRectF(bx, by, bw, bh)


class PetWindow(QWidget):
    # ---------- 配置辅助 ----------
    def _save_cfg(self):
        """Persist the config immediately.

        Originally only quit_app() wrote the file, so any setting changed during a session
        (mode / size / passthrough / position) was lost if the process was killed or the
        machine lost power - which is how "mouse passthrough is on but config says false"
        happened.
        """
        return save_json(CONFIG_PATH, self.cfg)

    def cur_size_key(self):
        """Pick the sprite height actually available, falling back to any loaded size."""
        want = int(340 * self.cfg.get("size", 0.7))
        heights = {k[1] for k in self.sprites}
        if not heights:
            return None
        if want in heights:
            return want
        return min(heights, key=lambda h: abs(h - want))

    def _set_city_dialog(self):
        city, ok = QInputDialog.getText(
            self,
            "设置城市",
            "输入城市名:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("city", "汕头")
        )

        if ok and city.strip():
            self.cfg["city"] = city.strip()
            self._save_cfg()
            self.say(f"城市已设置为{city}")

    def __init__(self):
        self.cfg = load_json(CONFIG_PATH, {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
            "ds_api_key": "",
            "city": "汕头"
    })
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("肥鱼科研版")
        
        # 精灵加载
        self.sprites = {}
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            for name in ["正面", "侧面", "背面"]:
                sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
                if os.path.exists(sized):
                    pix = QPixmap(sized)
                else:
                    pix = QPixmap(os.path.join(SPRITE_DIR, f"{name}.png")).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
                self.sprites[(name, h)] = pix
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        # Fail with a readable message instead of an opaque ValueError from max() below.
        size_key = self.cur_size_key()
        if size_key is None:
            QMessageBox.critical(
                None, "肥鱼科研版",
                f"找不到精灵图，程序无法启动。\n\n请确认这个文件夹存在且不为空：\n{SPRITE_DIR}")
            raise SystemExit(1)

        self.cur_h = size_key
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)

        # 状态
        self.mode = self.cfg.get("mode") if self.cfg.get("mode") in ("wander", "follow", "still") else "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.bubble_text = ""
        self.bubble_until = 0
        self.bubble_inner = False
        self.last_system_check = 0
        self.t = 0
        self.jump_t = 0
        self.dragging = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None
        
        # AI 相关
        self.ds_busy = False
        # deque with maxlen: trimming is atomic, so the worker thread and the main thread
        # can never observe a half-trimmed history.
        self.max_history = 40   # 最多记录40条
        self.chat_history = collections.deque(maxlen=self.max_history)
        self._say_queue = []    # 后台线程→主线程的气泡消息队列
        self._reply_queue = []  # 后台线程→聊天窗口的回答/提示队列
        self._weather_queue = []  # 后台线程→天气面板的结果队列
        self._usage_queue = []    # 后台线程→余额面板的结果队列
        self._weather_busy = False
        self._balance_busy = False
        self._load_chat_history()
        
        # 聊天暂停标志
        self.chat_paused = False
        
        # 功能列表
        self.function_panel = FunctionPanel(self)
        self.food_panel = FoodPanel(self.on_food)
        self.weather_panel = InfoPanel(self)     # 🫧 天气
        self.usage_panel = InfoPanel(self)       # 💰 用量/余额
        # 面板的「鼠标移开自动收起」监听（不用系统钩子）
        self._popup_watchers = {
            id(self.weather_panel): PopupFocusWatcher(self.weather_panel),
            id(self.usage_panel): PopupFocusWatcher(self.usage_panel),
        }
        # 单击延迟判定（等双击）：单击=回嘴+弹聊天面板，双击=喂食
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)
        
        # 聊天对话框
        self.chat_dialog = ChatDialog(self)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK)

        self.bubble_font = QFont("Microsoft YaHei UI", 11)

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)

    # ---------- AI 方法 ----------
    def send_chat(self, user_msg):
        """Called by the chat window. Shows the question, then asks the API."""
        user_msg = (user_msg or "").strip()
        if not user_msg:
            return
        self.chat_dialog.add_user(user_msg)

        key = self.cfg.get("ds_api_key", "").strip()
        if not key:
            self.chat_dialog.add_tip("还没有设置 DeepSeek API Key。\n"
                                     "右键点大肥鱼 → 「设置 Key」，粘贴你的 Key 就能用了。")
            return
        if self.ds_busy:
            self.chat_dialog.add_tip("大肥鱼还在想上一个问题，等它答完再问吧～")
            return

        self.chat_dialog.mark_pending()
        self._call_ds(user_msg)

    def _call_ds(self, user_msg):
        key = self.cfg.get("ds_api_key", "").strip()
        if not key:
            self.chat_dialog.add_tip("还没有设置 DeepSeek API Key。")
            return

        self.ds_busy = True

        # 构建消息列表
        messages = [{"role": "system", "content": DS_SYSTEM}]
        messages.extend(list(self.chat_history)[-self.max_history:])
        messages.append({"role": "user", "content": user_msg})

        def worker():
            url = f"{DS_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": DS_MODEL,
                "messages": messages,
                "max_tokens": DS_MAX_TOKENS,
                "temperature": DS_TEMPERATURE
            }
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=DS_TIMEOUT)
                if resp.status_code == 200:
                    # 完整回答，不再截断（原来超过 30 字就被砍成 28 字 + 省略号）
                    reply = resp.json()["choices"][0]["message"]["content"].strip()
                    if not reply:
                        reply = "（模型返回了空内容，再问一次试试）"
                    # deque 的 maxlen 让裁剪是原子的，后台线程与主线程都安全
                    self.chat_history.append({"role": "user", "content": user_msg})
                    self.chat_history.append({"role": "assistant", "content": reply})
                    self._save_chat_history()
                    self._queue_reply(reply)
                else:
                    # resp may not be JSON at all (proxy pages, 502 HTML).
                    try:
                        error_msg = resp.json().get("error", {}).get("message", str(resp.status_code))
                    except ValueError:
                        error_msg = f"HTTP {resp.status_code}"
                    self._queue_tip(f"API 返回错误 {resp.status_code}：{str(error_msg)[:120]}")
                    print(f"[DeepSeek] 状态码: {resp.status_code}, 返回: {resp.text[:300]}")
            except requests.exceptions.Timeout:
                self._queue_tip(f"请求超时（超过 {DS_TIMEOUT} 秒）。复杂问题可以拆开问，"
                                f"或检查网络。")
            except requests.exceptions.ConnectionError:
                self._queue_tip("连不上 api.deepseek.com，检查网络或代理设置。")
            except Exception as e:
                self._queue_tip(f"请求失败：{str(e)[:120]}")
            finally:
                self.ds_busy = False

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self.t * TICK / 1000.0

        if self.bubble_text and now < self.bubble_until:
            if self.bubble_inner:
                bfont = QFont(self.bubble_font)
                bfont.setItalic(True)
                bg, fg = QColor(232, 232, 238, 235), QColor(125, 125, 138)
            else:
                bfont = QFont(self.bubble_font)
                bg, fg = QColor(255, 255, 255, 235), QColor(60, 60, 80)
            # 排版逻辑统一在 draw_speech_bubble 里（换行宽度与气泡宽度对齐，
            # 不会再出现最长那行被裁掉两端的问题）
            draw_speech_bubble(
                p,
                QRectF(8, 6, min(240, self.width() - 16), BUBBLE_H - 10),
                self.bubble_text, bfont, bg, fg,
                pad=14, radius=10, tail_x=self.width() / 2, tail_h=8,
            )

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        if walking:
            sway = math.sin(now * 9.0) * 3.5
            bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        breath = 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing = key
            pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy)
            pw = pix.width() * scale * (1 + act_sx)
            dx = cx - pw / 2
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            if facing < 0:
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        cur_key = self._sprite_key()
        if self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _sprite_key(self):
        name = {"left": "侧面", "right": "侧面", "up": "背面", "down": "正面"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1

        # 处理后台线程（DeepSeek 等）排队的气泡消息，Qt 界面必须在主线程更新。
        # Drain atomically first: iterating and then clearing dropped any message a worker
        # appended in between (list.append is atomic, the loop+clear was not).
        if self._say_queue:
            pending = self._say_queue[:]
            self._say_queue.clear()
            for text in pending:
                self.say(text)

        # 聊天窗口的回答单独走一条队列：回答要完整显示，不能被气泡的 28 字限制裁掉
        if self._reply_queue:
            replies = self._reply_queue[:]
            self._reply_queue.clear()
            for kind, text in replies:
                if kind == "tip":
                    self.chat_dialog.add_tip(text)
                else:
                    self.chat_dialog.add_reply(text)

        # 天气结果填进独立面板
        if self._weather_queue:
            pending_w = self._weather_queue[:]
            self._weather_queue.clear()
            for text, is_error, compact in pending_w:
                self.weather_panel.show_for(text, is_error, compact)

        # 余额结果填进独立面板
        if self._usage_queue:
            pending_u = self._usage_queue[:]
            self._usage_queue.clear()
            for text, is_error, compact in pending_u:
                self.usage_panel.show_for(text, is_error, compact)

        # 两个面板都跟着肥鱼走
        if self.weather_panel.isVisible():
            self.weather_panel._reposition()
        if self.usage_panel.isVisible():
            self.usage_panel._reposition()

        # 处理全局钩子记下的点击（点别处 -> 收起所有弹出窗口）
        self._handle_outside_clicks()

        self.check_system_status()
        
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None
        
        if self.chat_paused:
            self.update()
            return
        
        if self.dragging:
            self.update()
            return
        now_ms = self.t * TICK

        if self.mode == "follow":
            cursor = self.cursor().pos()
            screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            near = (self.x() - 100 <= cursor.x() <= self.x() + self.width() + 100 and
                    self.y() - 100 <= cursor.y() <= self.y() + self.height() + 100)
            if near:
                self.target = None
            else:
                tx = max(geo.left(), min(geo.right() - self.width(), cursor.x() - self.width() / 2))
                ty = max(geo.top(), min(geo.bottom() - self.height(), cursor.y() - 90))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action()
                    self.update()
                    return
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.target = (random.randint(geo.left() + 40, geo.right() - self.width() - 40),
                               random.randint(geo.top() + 40, geo.bottom() - self.height() - 40))
        else:
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None:
            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * TICK + random.randint(8000, 18000)
                self._set_dir("down")
            else:
                step = self.cur_speed * TICK / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                self.move(int(nx - self.width() / 2), int(ny - self.height() / 2))
                if abs(dx) > abs(dy) * 1.15:
                    self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                else:
                    self._set_dir("up" if dy < 0 else "down")
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = SPEED if self.target is not None else 0.0
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def _maybe_idle_action(self):
        """偶尔做个动作（跳一下 / 摇尾巴 / 伸懒腰）。

        原来这个函数里还会随机冒出待机台词和内心吐槽，
        按需求已删除 —— 现在待机只有动作，不出声。
        """
        if random.random() < 0.01:
            pick = random.random()
            if pick < 0.35:
                self.jump_t = 1.0
            elif pick < 0.6:
                self.action, self.action_t = "sway", 1.0
            elif pick < 0.8:
                self.action, self.action_t = "stretch", 1.0

    def _queue_say(self, text):
        """后台线程调用：只入队，由主线程 tick 统一弹出显示（线程安全）"""
        self._say_queue.append(text)

    def _queue_reply(self, text):
        """回答要显示在聊天窗口里（而不是被裁成气泡）"""
        self._reply_queue.append(("reply", text))

    def _queue_tip(self, text):
        """错误提示也走聊天窗口，这样用户能看到完整原因"""
        self._reply_queue.append(("tip", text))

    def _queue_weather(self, text, is_error=False, compact_text=""):
        """后台线程调用：天气结果交给主线程填进独立面板。"""
        self._weather_queue.append((text, bool(is_error), compact_text or ""))

    def _save_chat_history(self):
        """把对话记录存盘，重启后还能看到之前聊过什么"""
        try:
            payload = {
                "messages": list(self.chat_history),
                "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(CHAT_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass          # 聊天记录存不下来不该影响正常对话

    def _load_chat_history(self):
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            for m in data.get("messages", []):
                if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
                    self.chat_history.append({"role": m["role"], "content": m["content"]})
        except Exception:
            pass

    def say(self, text, inner=False):
        if text == self.last_line and not text.startswith("天气"):
            return
        self.last_line = text
        self.bubble_inner = inner
        self.bubble_text = f"（{text}）" if inner else text
        self.bubble_until = self.t * TICK / 1000.0 + 2.8
        self.update()

    def check_system_status(self):
            now = self.t * TICK

            if now - getattr(self, "last_system_check", 0) < 10000:
                return

            self.last_system_check = now

            cpu = psutil.cpu_percent()

            if cpu >= 90:
                self.say("CPU跑满了，再这样下去我就卡死了")
                return

            ram = psutil.virtual_memory().percent

            if ram >= 95:
                self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
                return

            if GPU_AVAILABLE:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle,
                        pynvml.NVML_TEMPERATURE_GPU
                    )

                    if temp > 80:
                        self.say("我感觉我的鱼鳍快熟了")

                except Exception as e:
                    print("GPU读取失败:", e)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self.drag_start_pos = e.globalPosition().toPoint()
            self.function_panel.hide()
            self.chat_dialog.hide()
            self.chat_paused = True

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.rest_until = self.t * TICK + random.randint(6000, 14000)
                if random.random() < 0.5:
                    self.say(random.choice(DRAG_LINES))
                self.chat_paused = False
            else:
                self._click_timer.start(280)  # 等双击判定；单击则回嘴+弹聊天面板
            self.last_press_pos = None
            self.drag_start_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.food_panel.popup_at(*self._food_anchor())

    def _food_anchor(self):
        """喂食面板落位：同样贴着立绘上方，与图标面板/对话窗口保持一致。"""
        return (self.x() + self.width() / 2, self.y() + self.SPRITE_TOP_IN_WINDOW - self.PANEL_GAP)

    def _on_single_click(self):
        """单击：蹦一下 + 弹功能面板（🗨️问答 / 🫧天气 / 💰余额 / 🎁投喂）。

        原来单击还会随机回嘴（REACT_LINES），按需求已删除。
        """
        if random.random() < 0.7:
            self.jump_t = 1.0
        self.function_panel.popup_at(*self._panel_anchor())

    def on_food(self, food):
        self.food_panel.hide()
        self.eat_t = 1.0
        self.jump_t = 0.6
        lines = FOOD_LINES.get(food, ["好吃！"])
        self.say(random.choice(lines))

    # 立绘顶边在窗口内的 Y 坐标（见 paintEvent: bottom = BUBBLE_H + MARGIN + cur_h）
    SPRITE_TOP_IN_WINDOW = BUBBLE_H + MARGIN      # = 60

    # 图标面板底边离立绘顶边的距离。原来算下来是 166px（panel 高 96 + 间距 10
    # + 立绘顶边 60），留白过多；现在收紧到 12px。
    PANEL_GAP = 12

    def _panel_anchor(self):
        """功能面板（🗨️🫧）的落位坐标（左上角）。

        面板底边紧贴立绘上方 PANEL_GAP 像素，横向与立绘中心对齐。
        """
        panel = self.function_panel
        sprite_top = self.y() + self.SPRITE_TOP_IN_WINDOW
        return (self.x() + self.width() / 2 - panel.width() / 2,
                sprite_top - panel.height() - self.PANEL_GAP)

    def _dialog_anchor(self):
        """对话窗口的落位坐标（左上角）—— 向上展开，不遮住立绘。

        面板在上、对话窗口在面板之上，两者底边对齐，所以窗口整体位于立绘上方。
        """
        dlg = self.chat_dialog
        panel = self.function_panel
        px, py = self._panel_anchor()
        # 以面板底边为基准往上排：窗口底边 = 面板底边
        dialog_y = py + panel.height() - dlg.height()
        # 横向居中于立绘
        dialog_x = self.x() + self.width() / 2 - dlg.width() / 2
        return (dialog_x, dialog_y)

    def _show_chat_dialog(self):
        """打开聊天窗口，并把上次的对话记录回填进去。

        以前没设 Key 就直接拦下不开窗，用户只看到一句气泡、没有输入的地方；
        现在照常开窗，缺 Key 的提示显示在窗口里，并告诉去哪儿设置。
        """
        # 对话窗口和信息面板互斥，避免两个框叠在一起
        self._hide_all_popups(except_widget=self.chat_dialog)
        dlg = self.chat_dialog
        if not dlg.isVisible():
            dlg.clear_transcript_only()
            if self.chat_history:
                for m in self.chat_history:
                    if m["role"] == "user":
                        dlg.add_user(m["content"])
                    else:
                        dlg.add_reply(m["content"])
                dlg.add_tip("以上是上次的对话记录。继续问吧～")
            else:
                dlg.show_welcome()

            if not self.cfg.get("ds_api_key", "").strip():
                dlg.add_tip("还没有设置 DeepSeek API Key。\n"
                            "右键点大肥鱼 →「设置 Key」粘贴后即可开始问答。")

        dlg.popup_at(*self._dialog_anchor())

    def _hide_all_popups(self, except_widget=None):
        """收起所有弹出面板（图标面板 / 信息面板 / 对话窗口）。

        except_widget 指定的那个不动 —— 用于「刚打开这个，别的都关掉」。
        """
        for w in (self.function_panel, self.food_panel,
                  self.weather_panel, self.usage_panel, self.chat_dialog):
            if w is None or w is except_widget:
                continue
            try:
                if w.isVisible():
                    w.hide()
            except RuntimeError:
                pass

    def _handle_outside_clicks(self):
        """收起逻辑：鼠标离开面板一段时间后自动隐藏。

        注意：这里**不再**使用系统级鼠标钩子（曾导致鼠标卡顿，详见
        PopupFocusWatcher 的注释）。改成基于 Qt 的「鼠标离开检测」，
        完全不出进程，没有任何系统级副作用。
        """
        for panel in (self.weather_panel, self.usage_panel):
            if panel is None:
                continue
            watcher = self._popup_watchers.get(id(panel))
            if watcher:
                watcher.tick()

    def dismiss_popups_if_clicked_outside(self):
        """（保留给以后用）主动收起所有弹出面板。"""
        self._hide_all_popups()

    def show_usage(self):
        """💰 按钮：查 DeepSeek 账户余额，显示在独立面板里。"""
        self._hide_all_popups(except_widget=self.usage_panel)
        if not USAGE_API_AVAILABLE:
            self.usage_panel.show_for(f"余额模块加载失败：{_USAGE_IMPORT_ERROR}\n"
                                      f"请确认 usage_api.py 和 桌宠.py 在同一个文件夹里。",
                                      is_error=True)
            return
        key = (self.cfg.get("ds_api_key") or "").strip()
        if not key:
            self.usage_panel.show_for("还没设置 DeepSeek API Key。\n"
                                      "右键点肥鱼 →「设置 Key」。", is_error=True)
            return
        if getattr(self, "_balance_busy", False):
            return
        self._balance_busy = True
        self.usage_panel.show_for("正在查询账户余额…")

        def worker():
            try:
                bal = _fetch_balance(key)
                stamp = datetime.datetime.now().strftime("%H:%M:%S")
                text = _format_balance(bal, stamp)
                self._usage_queue.append((text, False, ""))
            except _BalanceError as e:
                self._usage_queue.append((str(e), True, ""))
            except Exception as e:
                print("余额错误:", repr(e))
                self._usage_queue.append((f"余额查询异常：{type(e).__name__}: {str(e)[:80]}", True, ""))
            finally:
                self._balance_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _queue_usage(self, text, is_error=False):
        """后台线程调用：余额结果交给主线程填进面板。"""
        self._usage_queue.append((text, bool(is_error), ""))

    def show_weather_in_chat(self):
        """🫧 按钮：查天气，结果显示在独立的天气面板里。

        之前把报告写进对话窗口，结果和问答混在一起（用户反馈"跟聊天对话框重复"）。
        天气是固定功能，用固定面板更合适，也不占用对话历史。
        """
        city = (self.cfg.get("city") or "").strip()
        if not city:
            self._hide_all_popups(except_widget=self.weather_panel)
            self.weather_panel.show_for("还没设置城市。\n右键上面的 🫧 按钮 →「设置城市」。",
                                        is_error=True)
            return
        if not WEATHER_API_AVAILABLE:
            self._hide_all_popups(except_widget=self.weather_panel)
            self.weather_panel.show_for(f"天气模块加载失败：{_WEATHER_IMPORT_ERROR}\n"
                                        f"请确认 weather_api.py 和 桌宠.py 在同一个文件夹里。",
                                        is_error=True)
            return

        # 切换功能时先把别的面板/对话窗口收起来，避免叠在一起
        self._hide_all_popups(except_widget=self.weather_panel)
        self.weather_panel.show_for(f"正在查 {city} 的天气…")
        self._get_weather(city)

    """def _get_city_by_ip(self):
        try:
            r = requests.get("http://ip-api.com/json/?fields=city&lang=zh-CN", timeout=5)
            if r.status_code == 200:
                city = r.json().get("city", "")
                if city:
                    return city
        except:
            pass
        return "汕头" """

    def _get_weather(self, city=None):
        """查天气：后台线程 + 多数据源自动降级。

        原来只在主线程里打 wttr.in（德国服务，中国城市数据粗糙），
        现在改用 weather_api 模块：
          1. 中国天气网（官方、免 key、实测 20-200ms，比 wttr.in 快 6 倍）
          2. Open-Meteo（国际源，兜底）
          3. wttr.in（最后兜底）

        结果分两路：气泡里报一句话，聊天窗口里放完整报告（含 7 日预报、
        空气质量、生活指数）。
        """
        if not WEATHER_API_AVAILABLE:
            self._queue_tip(f"天气模块加载失败：{_WEATHER_IMPORT_ERROR}\n"
                            f"请确认 weather_api.py 和 桌宠.py 在同一个文件夹里。")
            return
        if getattr(self, "_weather_busy", False):
            self.say("刚查过啦，等下再问～")
            return

        target = (city or self.cfg.get("city") or "").strip()
        if not target:
            self._queue_tip("还没设置城市。右键 🫧 按钮 →「设置城市」。")
            return

        self._weather_busy = True
        # 不再弹鱼头顶的气泡：天气只由独立面板显示。
        # 之前同时调 self._queue_say(r.summary())，结果鱼头顶一个小气泡 +
        # 上方一个天气面板 = 两个气泡框，用户反馈「跳出来两个」。
        # 这里连「正在查…」的气泡也不弹，避免开场就冒一个框；
        # 面板自己有「正在查 X 的天气…」的占位文字。

        def worker():
            try:
                r = _query_weather(target, want_forecast=True)
                if r.ok:
                    self._queue_weather(r.report(), False, r.compact())
                else:
                    self._queue_weather(r.error, True)
            except _WeatherError as e:
                self._queue_weather(f"天气查询失败：{e}", True)
            except Exception as e:
                print("天气错误:", repr(e))
                self._queue_weather(f"天气查询异常：{type(e).__name__}: {str(e)[:80]}", True)
            finally:
                self._weather_busy = False

        threading.Thread(target=worker, daemon=True).start()


    def _build_menu(self):
        m = QMenu(self)
        mode_menu = m.addMenu("模式")
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        size_menu = m.addMenu("大小")
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))
        m.addAction("设置 Key", self._set_key_dialog)
        # 「查看天气 / 设置城市」已移到功能面板的 🫧 按钮上：左键查天气、右键设城市
        m.addSeparator()
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        ta = m.addAction("窗口置顶")
        ta.setCheckable(True)
        ta.setChecked(self.cfg["topmost"])
        ta.triggered.connect(lambda on: self.set_topmost(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg["autostart"])
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        return m

    def _set_key_dialog(self):
        key, ok = QInputDialog.getText(
            self, 
            "设置 DeepSeek Key", 
            "输入你的 API Key（从 platform.deepseek.com 获取）:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("ds_api_key", "")
        )
        if ok and key.strip():
            self.cfg["ds_api_key"] = key.strip()
            self.say("Key 设置成功！")
        elif ok and not key.strip():
            self.say("Key 不能为空")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray.setContextMenu(self._build_menu())
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def contextMenuEvent(self, e):
        self._build_menu().exec(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        self.mode = mode
        self.target = None
        self.cfg["mode"] = mode
        self._save_cfg()

    def set_size(self, mult):
        self.cfg["size"] = mult
        new_h = self.cur_size_key()
        if new_h is not None:
            self.cur_h = new_h
        self.cross_t = 0.0
        self.prev_key = None
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)
        self.snap_into_screen()
        self._save_cfg()

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _apply_passthrough(self, on):
        hwnd = int(self.winId())
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED
        if on:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._apply_passthrough(bool(on))
        self._save_cfg()
        if on:
            self.say("我隐身了！右键托盘图标解除～")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()
        # Re-apply passthrough: toggling window flags recreates the native window and
        # drops WS_EX_TRANSPARENT, which silently disabled passthrough before.
        self._apply_passthrough(bool(self.cfg.get("passthrough", False)))
        self._save_cfg()

    def set_autostart(self, on):
        on = bool(on)
        startup_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                                   "Start Menu", "Programs", "Startup")
        lnk = os.path.join(startup_dir, "肥鱼科研版.lnk")
        # A link the user dropped in Startup themselves may use another name; without this
        # the pet would launch twice at logon.
        # 旧名字也一起列进来：改名后如果不清掉旧快捷方式，开机就会启动两次。
        # （不再枚举带个人姓名的那一版，避免把真实姓名写进公开代码；
        #   如果你之前开过那个名字的自启，手动去启动文件夹删掉即可。）
        aliases = [lnk,
                   os.path.join(startup_dir, "dafeiyu-pet.lnk"),
                   os.path.join(startup_dir, "大肥鱼桌宠.lnk"),
                   os.path.join(startup_dir, "大肥鱼桌宠（自启）.lnk")]
        try:
            if on:
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';"
                      "$s.IconLocation='{},0';$s.Description='肥鱼科研版';$s.Save()"
                      .format(lnk, PYTHONW,
                              "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                              APP_DIR,
                              os.path.join(APP_DIR, "icon.ico")))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                if not os.path.exists(lnk):
                    raise RuntimeError("快捷方式未生成，可能被安全软件拦截")
                # Drop duplicate links so the pet only starts once.
                for old in aliases:
                    if old != lnk and os.path.exists(old):
                        try:
                            os.remove(old)
                        except OSError:
                            pass
                self.say("已开机自启，明天见～")
            else:
                removed = False
                for old in aliases:
                    if os.path.exists(old):
                        try:
                            os.remove(old)
                            removed = True
                        except OSError:
                            pass
                self.say("已取消开机自启" if removed else "开机自启本来就是关的")
        except Exception as ex:
            self.cfg["autostart"] = not on     # roll the flag back to the real state
            QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")
        self._save_cfg()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def quit_app(self):
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        self._save_cfg()
        self.tray.hide()
        QApplication.quit()


_PET_MUTEX = None


def _acquire_single_instance():
    """Refuse to start a second pet.

    Without this, double-clicking the shortcut twice put two (or more) fish on screen and
    they fought over the same config.json. Returns False when another instance is running.
    """
    global _PET_MUTEX
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        # Keep the handle referenced for the lifetime of the process.
        _PET_MUTEX = kernel32.CreateMutexW(None, False, "Global\\DafeiyuPet_SingleInstance")
        if not _PET_MUTEX:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        return True
    except Exception:
        return True          # never block startup because of the guard itself


class PopupFocusWatcher:
    """弹出面板的「点别处就收起」行为。

    ⚠️ 这里**故意不用** Win32 的 WH_MOUSE_LL 全局鼠标钩子。

    曾经用过，结果把用户的鼠标搞卡了。原因是：
      1. WH_MOUSE_LL 会收到**所有**鼠标事件（含每一次移动），
         鼠标一动就是每秒几百次穿越 Python 回调；
      2. 用户机器的注册表 LowLevelHooksTimeout = 25000（默认约 300），
         钩子返回前鼠标事件会被阻塞等待 —— 延迟直接变成系统级卡顿。

    现在的做法靠 Qt 自己，完全不出进程，没有任何系统级副作用：
      · 面板是 Qt.Tool 窗口，点击别处时它会失去激活状态 -> 用 focusOut 收起；
      · 鼠标移到面板外一段时间 -> 也收起（兜底，交互上很自然）。
    """

    AWAY_MS = 1200        # 鼠标离开面板多久后自动收起

    def __init__(self, panel):
        self.panel = panel
        self._away_since = None

    def tick(self):
        """由主窗口的 tick 调用，判断鼠标是否已离开面板一段时间。"""
        panel = self.panel
        try:
            if not panel.isVisible():
                self._away_since = None
                return
        except RuntimeError:
            return

        cur = QCursor.pos()
        inside = (panel.x() - 8 <= cur.x() <= panel.x() + panel.width() + 8
                  and panel.y() - 8 <= cur.y() <= panel.y() + panel.height() + 8)
        if inside or panel.underMouse():
            self._away_since = None
            return

        now = time.time()
        if self._away_since is None:
            self._away_since = now
        elif (now - self._away_since) * 1000 >= self.AWAY_MS:
            panel.hide()
            self._away_since = None


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not _acquire_single_instance():
        QMessageBox.information(None, "肥鱼科研版", "肥鱼已经在桌面上了，看看屏幕右下角～")
        return
    w = PetWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    # 打包后的自检开关：带 --selftest 启动时只验证模块是否齐全，不开界面。
    # 用途：确认 weather_api / usage_api / sprites 真的打进 exe 了。
    if "--selftest" in sys.argv:
        try:
            from selftest import run_selftest
            sys.exit(run_selftest())
        except Exception as e:
            log = os.path.join(os.path.expanduser("~"), "feiyu_selftest.txt")
            try:
                with open(log, "w", encoding="utf-8") as f:
                    f.write(f"selftest 自身失败: {type(e).__name__}: {e}\n")
            except Exception:
                pass
            sys.exit(2)

    try:
        main()
    except Exception as ex:
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "肥鱼科研版出错", str(ex))
        except Exception:
            pass
        raise