# -*- coding: utf-8 -*-
"""
StockTicker —— 极简置顶浮动行情小工具
- 实时监控：默认 长安汽车 / 上证指数 / 创业板指（可在右键菜单增删）
- 无边框、置顶、可拖拽、可隐藏到托盘
- 迷你 K 线（右键可切换 1分/5分/15分/30分/60分/日K/周K）
- 全局热键 Ctrl+Alt+H 隐藏/显示
数据源：东方财富公开行情接口（无需密钥）
"""

import sys
import os
import time
import ctypes
import ctypes.wintypes
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QSystemTrayIcon,
    QInputDialog, QMessageBox
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QRect, QPoint, QSize, QTimer
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPixmap, QIcon, QCursor, QAction
)
import requests
import json
import logging
import traceback


# ----------------------------- 崩溃 / 异常日志 -----------------------------
# 把未捕获异常与 worker 报错写到 %APPDATA%\StockTicker\app.log，
# 便于事后排查（尤其闪退类问题）。
_LOG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "StockTicker"
)
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(_LOG_DIR, "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
except Exception:
    pass

def log_exc(tag=""):
    """记录当前异常堆栈到日志文件。"""
    try:
        logging.error(f"{tag}: " + traceback.format_exc())
    except Exception:
        pass

def _global_exc_hook(exc_type, exc_val, exc_tb):
    try:
        logging.error("UNCAUGHT: " + "".join(
            traceback.format_exception(exc_type, exc_val, exc_tb)))
    except Exception:
        pass

sys.excepthook = _global_exc_hook
try:
    threading.excepthook = lambda args: _global_exc_hook(
        args.exc_type, args.exc_value, args.exc_traceback)
except Exception:
    pass


def _num(v):
    """把东方财富可能返回的 '-' / '--' / '' / None 统一转成 float 或 None，
    避免字符串被当成数字传给绘制/比较时抛 TypeError 导致主线程闪退。"""
    if v is None or v == "" or v == "-" or v == "--":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resource_path(relative_path):
    """兼容源码运行与 PyInstaller 单文件解包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, relative_path)


APP_ICON = resource_path(os.path.join("assets", "app.ico"))

# 行情请求头（每次请求独立使用，便于多线程并发抓取）
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}

# ----------------------------- 配置 -----------------------------
QUOTE_INTERVAL = 3.0      # 行情刷新间隔（秒）
KLINE_INTERVAL = 12.0     # K线刷新间隔（秒）
KLINE_LMT = 80            # 取最近多少根

# K 线周期选项（klt 代码）—— 已联网核对东方财富接口：
# 分钟线用「分钟数」(1/5/15/30/60)，日/周线用 101/102。
# 注意：旧代码误用 101~107，实测那套是「日/周/月/季/年」，会把日线当成分时显示。
KLT_OPTIONS = {
    "1分钟": 1,
    "5分钟": 5,
    "15分钟": 15,
    "30分钟": 30,
    "60分钟": 60,
    "日K": 101,
    "周K": 102,
}
DEFAULT_KLT = 5           # 默认 5 分钟

# 当前 K 线周期（菜单可切换）
CURRENT_KLT = DEFAULT_KLT

# 默认标的：secid -> 显示名（None 表示用接口返回的名称自动填充）
SECIDS = {
    "0.000625": "长安汽车",
    "1.000001": "上证指数",
    "0.399006": "创业板指",
}
ORDER = list(SECIDS.keys())

# 中国习惯：涨红跌绿
RED = QColor(0xEF, 0x23, 0x2A)
GREEN = QColor(0x14, 0xB1, 0x43)

# 主题（右键可切换 深色/浅色），面板半透明让底色更“融”进桌面
THEME = "light"
_DARK = dict(
    panel=QColor(0x12, 0x14, 0x18, 0xCC),
    border=QColor(0x3C, 0x40, 0x48),
    hl=QColor(0x2A, 0x2E, 0x38),
    text=QColor(0xEC, 0xEF, 0xF3),
    grey=QColor(0x8A, 0x90, 0x99),
)
_LIGHT = dict(
    panel=QColor(0xF2, 0xF3, 0xF5, 0xEE),
    border=QColor(0xCF, 0xD2, 0xD8),
    hl=QColor(0xE1, 0xE3, 0xE8),
    text=QColor(0x20, 0x24, 0x2A),
    grey=QColor(0x6A, 0x6F, 0x77),
)
PANEL = _LIGHT["panel"]
BORDER = _LIGHT["border"]
HL = _LIGHT["hl"]
WHITE = _LIGHT["text"]
GREY = _LIGHT["grey"]

def set_theme(name):
    global THEME, PANEL, BORDER, HL, WHITE, GREY
    c = _LIGHT if name == "light" else _DARK
    THEME = name
    PANEL = c["panel"]
    BORDER = c["border"]
    HL = c["hl"]
    WHITE = c["text"]
    GREY = c["grey"]

# 整体缩放（右键「窗口缩放」可调）
SCALE = 1.0
BASE_W, BASE_ROW_H, BASE_TOP, BASE_H_KLINE = 300, 36, 8, 116

def recompute_layout():
    global W, ROW_H, TOP, H_KLINE
    W = int(round(BASE_W * SCALE))
    ROW_H = int(round(BASE_ROW_H * SCALE))
    TOP = int(round(BASE_TOP * SCALE))
    H_KLINE = int(round(BASE_H_KLINE * SCALE))

# ----------------------------- 设置持久化 -----------------------------
# 用户设置存到 %APPDATA%\StockTicker\config.json，重启自动恢复
# （主题 / 透明度 / 缩放 / K线周期 / K线显隐 / 缩放根数 / 激活标的 / 自选列表 / 窗口位置）
CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "StockTicker", "config.json"
)
TICKER = None   # 运行时指向 Ticker 实例，供 save_config 读取实例级设置


def load_config():
    """读取上次保存的用户设置；文件不存在/损坏时返回空字典（回退到代码默认值）。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


SETTINGS = load_config()


def save_config():
    """把当前所有用户设置写入配置文件，下次启动自动恢复。"""
    cfg = {
        "theme": THEME,
        "opacity": TICKER.opacity if TICKER else 0.9,
        "scale": SCALE,
        "klt": CURRENT_KLT,
        "show_kline": TICKER.show_kline if TICKER else True,
        "kzoom": TICKER.kzoom if TICKER else 60,
        "active": TICKER.active if TICKER else 0,
        "stocks": dict(SECIDS),
        "auto_dim": TICKER.auto_dim if TICKER else True,
    }
    if TICKER:
        cfg["pos"] = [TICKER.x(), TICKER.y()]
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 用已保存设置覆盖模块级默认值（字段存在时才覆盖，保证向后兼容老版本无配置文件的情况）
if isinstance(SETTINGS.get("theme"), str) and SETTINGS["theme"] in ("light", "dark"):
    set_theme(SETTINGS["theme"])
if isinstance(SETTINGS.get("scale"), (int, float)):
    SCALE = max(0.1, min(1.0, float(SETTINGS["scale"])))
if isinstance(SETTINGS.get("opacity"), (int, float)):
    # 透明度限制在 10%~100%，避免保存到不合范围的非法值
    _op = max(0.1, min(1.0, float(SETTINGS["opacity"])))
    SETTINGS["opacity"] = _op
if SETTINGS.get("klt") in KLT_OPTIONS.values():
    CURRENT_KLT = SETTINGS["klt"]
if isinstance(SETTINGS.get("stocks"), dict) and SETTINGS["stocks"]:
    SECIDS = {str(k): v for k, v in SETTINGS["stocks"].items()}
    ORDER = list(SECIDS.keys())


W = ROW_H = TOP = H_KLINE = 0
recompute_layout()

def FS(px):
    """按缩放系数返回字号"""
    return max(6, int(round(px * SCALE)))

# 高度随标的数量动态计算
def rows_h():
    return TOP + len(ORDER) * ROW_H + 6

def full_h():
    return rows_h() + H_KLINE + 6

def small_h():
    return rows_h() + 6


# ----------------------------- 数据抓取线程 -----------------------------
class Worker(QThread):
    updated = Signal(dict)

    def __init__(self):
        super().__init__()
        self.running = True
        self.qcache = {}
        self.kcache = {}
        self.last_kline = 0
        self.force_kline = True   # 首轮立即拉数据出图，不白等一个行情间隔
        # 用于即时唤醒刷新循环（切换K线周期等场景），避免最长等一个行情间隔
        self.refresh_event = threading.Event()
        # 行情并发抓取线程池：避免单标的请求超时拖累整体，缩短切换/刷新等待
        self._qexec = ThreadPoolExecutor(max_workers=4)
        self.active_secid = None   # 由 Ticker 同步当前激活标的，用于即时刷新其 K 线

    def stop(self):
        self.running = False
        self.refresh_event.set()

    def request_kline_refresh(self):
        self.force_kline = True
        self.refresh_event.set()

    def _quote_url(self, secid):
        ts = int(time.time() * 1000)
        return (
            "https://push2.eastmoney.com/api/qt/stock/get"
            f"?secid={secid}&fields=f43,f44,f45,f46,f57,f58,f60,f86,f169,f170"
            f"&fltt=2&invt=2&_={ts}"
        )

    def _kline_url(self, secid):
        ts = int(time.time() * 1000)
        return (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56"
            f"&klt={CURRENT_KLT}&fqt=1&end=20500101&lmt={KLINE_LMT}&_={ts}"
        )

    def fetch_quote(self, secid):
        # timeout=(connect, read)：避免某标的连接/读超时把整轮拖死
        r = requests.get(self._quote_url(secid), headers=HEADERS, timeout=(3, 8))
        d = (r.json() or {}).get("data") or {}
        return {
            "name": d.get("f58"),
            "code": d.get("f57"),
            "price": _num(d.get("f43")),
            "open": _num(d.get("f46")),
            "high": _num(d.get("f44")),
            "low": _num(d.get("f45")),
            "prev_close": _num(d.get("f60")),
            "pct": _num(d.get("f170")),   # 涨跌幅 %
            "chg": _num(d.get("f169")),   # 涨跌额
        }

    def fetch_kline(self, secid):
        r = requests.get(self._kline_url(secid), headers=HEADERS, timeout=(3, 8))
        kd = (r.json() or {}).get("data") or {}
        bars = []
        for s in (kd.get("klines") or []):
            p = s.split(",")
            if len(p) >= 6:
                try:
                    bars.append({
                        "t": p[0],
                        "o": float(p[1]),
                        "c": float(p[2]),
                        "h": float(p[3]),
                        "l": float(p[4]),
                        "v": float(p[5]),
                    })
                except (TypeError, ValueError):
                    # 单根数据异常（如停牌返回 '-'）跳过，不连累整图
                    continue
        return bars

    def run(self):
        try:
            while self.running:
                try:
                    # 等待：到点（行情间隔）或被强制刷新信号即时唤醒（0.1s 粒度）
                    waited = 0.0
                    while waited < QUOTE_INTERVAL and self.running:
                        if self.refresh_event.wait(0.1):
                            break
                        waited += 0.1
                    self.refresh_event.clear()
                    now = time.time()

                    # 切换周期 / 增删标的：立即只拉「当前激活标的」K 线并刷新，
                    # 不再被其它标的行情抓取阻塞，保证切换后 K 线最快可见
                    if self.force_kline and ORDER:
                        self._refresh_active_kline()
                        self.force_kline = False

                    # 行情：并发抓取（避免单标的超时拖累整体），缩短切换等待
                    do_k = (now - self.last_kline) >= KLINE_INTERVAL
                    qmap = self._fetch_all_quotes()
                    for secid, q in qmap.items():
                        if q and q.get("price") is not None:
                            if q.get("name"):
                                SECIDS[secid] = q["name"]
                            self.qcache[secid] = q

                    # K 线：到点整体刷新
                    if do_k:
                        self._fetch_all_klines()
                        self.last_kline = now

                    # 组装并推送
                    payload = {}
                    for secid in list(SECIDS.keys()):
                        payload[secid] = {
                            "q": self.qcache.get(secid),
                            "k": self.kcache.get(secid),
                        }
                    self.updated.emit(payload)
                except Exception:
                    # 单轮出错只记录，绝不退出循环 —— 否则线程一死界面就冻结
                    log_exc("worker iteration")
                    time.sleep(1)
        finally:
            try:
                self._qexec.shutdown(wait=False)
            except Exception:
                pass

    def _fetch_all_quotes(self):
        """并发抓取全部标的行情，单标的失败不影响其它，整体耗时约等于最慢一个。"""
        secids = list(SECIDS.keys())
        if not secids:
            return {}
        futures = {self._qexec.submit(self.fetch_quote, s): s for s in secids}
        out = {}
        for fut, s in futures.items():
            try:
                out[s] = fut.result(timeout=10)
            except Exception:
                out[s] = None
        return out

    def _fetch_all_klines(self):
        for secid in list(SECIDS.keys()):
            try:
                kk = self.fetch_kline(secid)
                if kk:
                    self.kcache[secid] = kk
            except Exception:
                pass

    def _refresh_active_kline(self):
        """仅刷新当前激活标的的 K 线并立即推送，用于切换周期/增删标的的即时反馈。"""
        if not ORDER:
            return
        secid = self.active_secid or ORDER[0]
        try:
            kk = self.fetch_kline(secid)
            if kk:
                self.kcache[secid] = kk
        except Exception:
            pass
        payload = {}
        for s in list(SECIDS.keys()):
            payload[s] = {
                "q": self.qcache.get(s),
                "k": self.kcache.get(s),
            }
        self.updated.emit(payload)


# ----------------------------- 全局热键（Ctrl+Alt+H） -----------------------------
# 独立线程跑 Windows 消息循环接收 WM_HOTKEY。
# 关键：必须显式声明 RegisterHotKey / GetMessageW 等的 argtypes/restype，
# 否则 64 位下指针参数被截断成 32 位，导致 WM_HOTKEY 消息读不出来、
# 表现为「热键注册了却毫无反应」（这是上一版热键失效的根因）。
# 用 NULL 窗口句柄注册，消息进入线程队列，不依赖 widget 的 winId()。
class HotkeyThread(QThread):
    toggled = Signal()
    MOD_CONTROL = 0x0002
    MOD_ALT = 0x0001
    MOD_NOREPEAT = 0x4000
    VK_H = 0x48
    WM_HOTKEY = 0x0312

    def __init__(self):
        super().__init__()
        self.running = True
        self.user32 = ctypes.windll.user32
        # 显式声明类型，避免 64 位指针截断
        self.user32.RegisterHotKey.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint]
        self.user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
        self.user32.GetMessageW.argtypes = [
            ctypes.POINTER(ctypes.wintypes.MSG), ctypes.wintypes.HWND,
            ctypes.wintypes.UINT, ctypes.wintypes.UINT]
        self.user32.GetMessageW.restype = ctypes.wintypes.LPARAM
        self.user32.TranslateMessage.argtypes = [
            ctypes.POINTER(ctypes.wintypes.MSG)]
        self.user32.TranslateMessage.restype = ctypes.wintypes.BOOL
        self.user32.DispatchMessageW.argtypes = [
            ctypes.POINTER(ctypes.wintypes.MSG)]
        self.user32.DispatchMessageW.restype = ctypes.wintypes.LPARAM
        self.user32.PostThreadMessageW.argtypes = [
            ctypes.wintypes.DWORD, ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
        self.user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

    def run(self):
        try:
            if not self.user32.RegisterHotKey(
                    None, 1,
                    self.MOD_CONTROL | self.MOD_ALT | self.MOD_NOREPEAT,
                    self.VK_H):
                # 返回失败：热键可能被占用，或无桌面会话（如 headless 环境）。
                # 此时退化为「右键菜单 / 托盘单击」也能显隐，不影响其它功能。
                logging.warning(
                    "RegisterHotKey 失败：可能热键已被占用或当前无桌面会话；"
                    "可改用右键菜单「显示/隐藏」或单击托盘图标")
                return
            msg = ctypes.wintypes.MSG()
            while self.running:
                ret = self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == self.WM_HOTKEY:
                    self.toggled.emit()
                self.user32.TranslateMessage(ctypes.byref(msg))
                self.user32.DispatchMessageW(ctypes.byref(msg))
            try:
                self.user32.UnregisterHotKey(None, 1)
            except Exception:
                pass
        except Exception:
            log_exc("hotkey loop")

    def stop(self):
        self.running = False
        try:
            # 让阻塞在 GetMessage 的线程退出循环
            self.user32.PostThreadMessageW(
                ctypes.wintypes.DWORD(self.currentThreadId()),
                0x0012, 0, 0)   # WM_QUIT
        except Exception:
            pass


# ----------------------------- 浮动窗口 -----------------------------
class Ticker(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self.active = int(SETTINGS.get("active", 0))
        self.active = max(0, min(self.active, max(0, len(ORDER) - 1)))
        self.show_kline = bool(SETTINGS.get("show_kline", True))
        self.opacity = float(SETTINGS.get("opacity", 0.9))
        self.dragging = False
        self._moved = False      # 本次拖拽是否真的移动过（用于决定是否保存位置）
        self.drag_offset = QPoint()
        self.kzoom = int(SETTINGS.get("kzoom", 60))   # K 线可见根数（滚轮缩放）
        self._hover = None       # 鼠标悬停的 K 线索引
        self._kl = None          # 最近一次 K 线绘制几何
        self.auto_dim = bool(SETTINGS.get("auto_dim", True))  # 鼠标离开2秒自动变暗
        self._dimmed = False     # 当前是否已变暗（内容降到约10%可见）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._dim)

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(self.opacity)
        self.setMouseTracking(True)   # 悬停无需按住鼠标即可响应
        self._apply_size()

        # 恢复上次保存的窗口位置（首次运行或读取失败时留在默认位置）
        pos = SETTINGS.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and \
                all(isinstance(v, (int, float)) for v in pos):
            self.move(int(pos[0]), int(pos[1]))

        self.worker = Worker()
        self.worker.updated.connect(self.on_data)
        self.worker.active_secid = ORDER[self.active]
        self.worker.daemon = True
        self.worker.start()

        # 全局热键 Ctrl+Alt+H：独立线程跑消息循环（详见 HotkeyThread）
        self.hotkey = HotkeyThread()
        self.hotkey.toggled.connect(self.toggle_visible)
        self.hotkey.daemon = True
        self.hotkey.start()

        self._build_context_menu()
        self._build_tray()

        # 注册实例，供 save_config 读取实例级设置
        global TICKER
        TICKER = self

    # ---------- 尺寸 ----------
    def _apply_size(self):
        self.resize(W, full_h() if self.show_kline else small_h())

    # ---------- 右键菜单 ----------
    def _build_context_menu(self):
        menu = QMenu(self)

        a_show = QAction("显示 / 隐藏  (Ctrl+Alt+H)", self)
        a_show.triggered.connect(self.toggle_visible)
        menu.addAction(a_show)

        a_k = QAction("切换 K 线显隐  (双击空白处)", self)
        a_k.triggered.connect(self.toggle_kline)
        menu.addAction(a_k)

        a_edge = QAction("离开自动变暗 (2秒)", self)
        a_edge.setCheckable(True)
        a_edge.setChecked(self.auto_dim)
        a_edge.triggered.connect(self.toggle_auto_dim)
        menu.addAction(a_edge)

        a_help = QAction("操作说明…", self)
        a_help.triggered.connect(self.show_help)
        menu.addAction(a_help)

        menu.addSeparator()

        # K 线周期子菜单
        k_menu = QMenu("K线周期", self)
        self.k_actions = {}
        for label, klt in KLT_OPTIONS.items():
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(klt == CURRENT_KLT)
            a.triggered.connect(
                lambda _=False, k=klt: self.set_klt(k)
            )
            k_menu.addAction(a)
            self.k_actions[klt] = a
        menu.addMenu(k_menu)

        # 透明度子菜单（10% ~ 100%）
        op_menu = QMenu("透明度", self)
        self.op_actions = {}
        for label, val in [("100%", 1.0), ("90%", 0.9), ("80%", 0.8),
                           ("70%", 0.7), ("60%", 0.6), ("50%", 0.5),
                           ("40%", 0.4), ("30%", 0.3), ("20%", 0.2),
                           ("10%", 0.1)]:
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(abs(val - self.opacity) < 1e-6)
            a.triggered.connect(
                lambda _=False, v=val: self.set_opacity(v)
            )
            op_menu.addAction(a)
            self.op_actions[val] = a
        menu.addMenu(op_menu)

        # 主题底色子菜单
        theme_menu = QMenu("主题底色", self)
        self.theme_actions = {}
        for label, name in [("深色（黑）", "dark"), ("浅色（白）", "light")]:
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(name == THEME)
            a.triggered.connect(
                lambda _=False, n=name: self.choose_theme(n)
            )
            theme_menu.addAction(a)
            self.theme_actions[name] = a
        menu.addMenu(theme_menu)

        # 窗口缩放子菜单（10% ~ 100%，不再放大超过原始尺寸）
        scale_menu = QMenu("窗口缩放", self)
        self.scale_actions = {}
        for label, val in [("100%", 1.0), ("90%", 0.9), ("80%", 0.8),
                           ("70%", 0.7), ("60%", 0.6), ("50%", 0.5),
                           ("40%", 0.4), ("30%", 0.3), ("20%", 0.2),
                           ("10%", 0.1)]:
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(abs(val - SCALE) < 1e-6)
            a.triggered.connect(
                lambda _=False, v=val: self.set_scale(v)
            )
            scale_menu.addAction(a)
            self.scale_actions[val] = a
        menu.addMenu(scale_menu)

        menu.addSeparator()

        # 添加 / 删除股票
        a_add = QAction("添加股票…", self)
        a_add.triggered.connect(self.add_stock)
        menu.addAction(a_add)

        self.del_menu = QMenu("删除股票", self)
        self.del_menu.aboutToShow.connect(self._refresh_del_menu)
        menu.addMenu(self.del_menu)
        self._refresh_del_menu()

        menu.addSeparator()
        a_exit = QAction("退出", self)
        a_exit.triggered.connect(self.quit_app)
        menu.addAction(a_exit)

        self.ctx_menu = menu

    def _refresh_del_menu(self):
        self.del_menu.clear()
        if not ORDER:
            a = QAction("(暂无标的)", self)
            a.setEnabled(False)
            self.del_menu.addAction(a)
            return
        for secid in ORDER:
            # 优先用实时行情里的名称（添加后下一次刷新即补全），其次 SECIDS，最后代码
            nm = SECIDS.get(secid) or secid
            q = self.data.get(secid, {}).get("q")
            if q and q.get("name"):
                nm = q["name"]
            a = QAction(f"{nm}  ({secid})", self)
            a.triggered.connect(
                lambda _=False, s=secid: self.remove_stock(s)
            )
            self.del_menu.addAction(a)

    # ---------- 托盘 ----------
    def _build_tray(self):
        self.tray_icon = QIcon(APP_ICON)
        if self.tray_icon.isNull():
            # 资源异常时保留一个可见的后备图标
            pix = QPixmap(16, 16)
            pix.fill(Qt.transparent)
            pp = QPainter(pix)
            pp.setBrush(QBrush(RED))
            pp.setPen(Qt.NoPen)
            pp.drawRect(4, 3, 3, 10)
            pp.setBrush(QBrush(GREEN))
            pp.drawRect(9, 6, 3, 7)
            pp.end()
            self.tray_icon = QIcon(pix)
        self.setWindowIcon(self.tray_icon)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.tray_icon)
        self.tray.setContextMenu(self.ctx_menu)
        self.tray.activated.connect(
            lambda reason: self.toggle_visible()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    # ---------- 数据回调 ----------
    def on_data(self, payload):
        self.data = payload
        self.update()

    # ---------- 显隐 ----------
    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self._undim()
            self.show()
            self.raise_()
            self.activateWindow()

    def toggle_auto_dim(self):
        self.auto_dim = not self.auto_dim
        if not self.auto_dim and self._dimmed:
            self._undim()
        save_config()

    def toggle_kline(self):
        self.show_kline = not self.show_kline
        self._apply_size()
        self.update()
        save_config()

    def show_help(self):
        """右键「操作说明」：向用户解释全部操作方式。"""
        text = (
            "【StockTicker 操作说明】\n\n"
            "● 显示 / 隐藏窗口\n"
            "    右键菜单「显示/隐藏」，或快捷键 Ctrl+Alt+H，或单击托盘图标。\n\n"
            "● 移动窗口\n"
            "    在窗口空白处（非 K 线悬停区）按住鼠标左键拖动。\n\n"
            "● 边缘吸附 / 离开自动变暗\n"
            "    拖到屏幕边缘附近会自动吸附对齐；鼠标离开窗口约 2 秒后自动\n"
            "    降到约 10% 透明度（内容变暗并显示提示条），鼠标移回去即恢复。\n"
            "    右键「离开自动变暗 (2秒)」可开关。\n\n"
            "● 切换 K 线标的\n"
            "    双击某支股票所在行；高亮行即为当前显示 K 线的标的。\n\n"
            "● 显示 / 隐藏 K 线\n"
            "    右键「切换 K 线显隐」，或双击窗口空白处。\n\n"
            "● 切换 K 线周期\n"
            "    右键「K 线周期」：1 / 5 / 15 / 30 / 60 分钟、日 K、周 K。\n"
            "    当前周期显示在 K 线区域左上角（默认 5 分钟 K 线）。\n\n"
            "● K 线缩放\n"
            "    鼠标在 K 线区域内滚动滚轮：向上滚放大（显示根数变少），向下滚缩小。\n\n"
            "● 查看单根数值\n"
            "    鼠标移到 K 线任意位置，自动显示该根的开 / 高 / 低 / 收。\n\n"
            "● 透明度 / 主题底色 / 窗口缩放\n"
            "    右键对应子菜单调整。\n\n"
            "● 添加 / 删除股票\n"
            "    右键「添加股票」输入代码（如 600519）或 secid；\n"
            "    「删除股票」子菜单按名称选择。\n\n"
            "● 退出\n"
            "    右键「退出」结束程序。\n\n"
            "数据来源：东方财富公开行情接口，非逐笔实时，存在延迟。"
        )
        QMessageBox.information(self, "操作说明", text)

    def set_klt(self, klt):
        global CURRENT_KLT
        CURRENT_KLT = klt
        for k, a in self.k_actions.items():
            a.setChecked(k == klt)
        self.worker.request_kline_refresh()
        self.update()
        save_config()

    def _sync_active(self):
        """把当前激活标的同步给数据线程，保证切换周期时即时刷新的是正确的标的。"""
        try:
            self.worker.active_secid = ORDER[self.active]
            save_config()
        except Exception:
            pass

    def choose_theme(self, name):
        set_theme(name)
        for k, a in self.theme_actions.items():
            a.setChecked(k == name)
        self.update()
        save_config()

    def set_opacity(self, v):
        self.opacity = v
        self.setWindowOpacity(v)
        for k, a in self.op_actions.items():
            a.setChecked(abs(k - v) < 1e-6)
        save_config()

    def set_scale(self, v):
        global SCALE
        SCALE = v
        recompute_layout()
        for k, a in self.scale_actions.items():
            a.setChecked(abs(k - v) < 1e-6)
        self._apply_size()
        self.update()
        save_config()

    # ---------- 增删股票 ----------
    def _parse_secid(self, text):
        text = text.strip()
        if "." in text:
            pre, code = text.split(".", 1)
            pre, code = pre.strip(), code.strip()
            if pre in ("0", "1") and code.isdigit():
                return f"{pre}.{code}"
            return None
        if text.isdigit() and len(text) == 6:
            if text[0] == "6":
                return f"1.{text}"      # 沪市
            return f"0.{text}"          # 深市 / 北交所
        return None

    def add_stock(self):
        text, ok = QInputDialog.getText(
            self, "添加股票",
            "输入股票代码（如 600519）或 secid（如 1.600519）：\n"
            "· 沪市 6 开头自动识别为 1.xxxxxx\n"
            "· 深市 0/3 开头、北交所 8/4 开头为 0.xxxxxx"
        )
        if not ok or not text:
            return
        secid = self._parse_secid(text)
        if not secid:
            QMessageBox.warning(
                self, "无法识别",
                "请输入 6 位股票代码，或形如 1.600519 的 secid。"
            )
            return
        if secid in SECIDS:
            QMessageBox.information(self, "已存在", f"{secid} 已在列表中")
            return
        SECIDS[secid] = None
        ORDER.append(secid)
        self.active = len(ORDER) - 1
        self._sync_active()
        self._refresh_del_menu()
        self._apply_size()
        self.worker.request_kline_refresh()
        self.update()
        save_config()

    def remove_stock(self, secid):
        if secid in SECIDS:
            del SECIDS[secid]
        if secid in ORDER:
            ORDER.remove(secid)
        self.active = min(self.active, max(0, len(ORDER) - 1))
        self._sync_active()
        self.worker.kcache.pop(secid, None)
        self.worker.qcache.pop(secid, None)
        self._refresh_del_menu()
        self._apply_size()
        self.update()
        save_config()

    def quit_app(self):
        save_config()
        self.worker.stop()
        try:
            self.hotkey.running = False
            self.hotkey.stop()
            self.hotkey.terminate()
        except Exception:
            pass
        try:
            ctypes.windll.user32.UnregisterHotKey(None, 1)
        except Exception:
            pass
        self.tray.hide()
        QApplication.instance().quit()

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 单击仅用于拖拽（切换股票改为双击）
            self.dragging = True
            self.drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)
            self._moved = True
        # 鼠标在 K 线上方时显示该根数值
        if self.show_kline and self._kl and self._kl.get("bars"):
            kl = self._kl
            gx, gy = e.position().x(), e.position().y()
            if (kl["y"] - 14 <= gy <= kl["y"] + kl["h"]
                    and kl["x"] <= gx <= kl["x"] + kl["w"]):
                n = len(kl["bars"])
                idx = int((gx - kl["x"]) / kl["cw"])
                idx = max(0, min(n - 1, idx))
                if self._hover != idx:
                    self._hover = idx
                    self.update()
            elif self._hover is not None:
                self._hover = None
                self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.dragging and self._moved:
            self._snap_to_edge()   # 拖到屏幕边缘附近自动吸附对齐
            save_config()   # 拖拽移动后保存窗口位置
        self.dragging = False
        self._moved = False

    def mouseDoubleClickEvent(self, e):
        # 双击某行 -> 切换该标的的 K 线；双击空白处 -> 切换 K 线显隐
        y = e.position().y()
        if len(ORDER) and TOP <= y < TOP + len(ORDER) * ROW_H:
            idx = int((y - TOP) // ROW_H)
            if 0 <= idx < len(ORDER):
                self.active = idx
                self._sync_active()
                if not self.show_kline:
                    self.show_kline = True
                    self._apply_size()
                self.update()
                save_config()   # 切换当前激活标的后保存
        else:
            self.toggle_kline()

    def contextMenuEvent(self, e):
        self.ctx_menu.exec(QCursor.pos())

    def wheelEvent(self, e):
        # 鼠标在 K 线区域时，滚轮缩放显示根数
        if self.show_kline and self._kl:
            gx, gy = e.position().x(), e.position().y()
            kl = self._kl
            if (kl["y"] - 14 <= gy <= kl["y"] + kl["h"]
                    and kl["x"] <= gx <= kl["x"] + kl["w"]):
                if e.angleDelta().y() > 0:
                    self.kzoom = max(10, self.kzoom - 6)      # 上滚放大
                else:
                    self.kzoom = min(KLINE_LMT, self.kzoom + 6)  # 下滚缩小
                self.update()
                save_config()   # 缩放根数变化后保存
                e.accept()
                return
        e.ignore()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.update()
        # 鼠标离开且开启「离开自动变暗」：2 秒后降到约 10% 透明度（不贴边）
        if self.auto_dim and not self.dragging and not self._dimmed:
            self._hide_timer.start(2000)
        super().leaveEvent(e)

    def enterEvent(self, e):
        # 鼠标回到窗口：取消变暗计时并恢复透明度
        if self._hide_timer.isActive():
            self._hide_timer.stop()
        if self._dimmed:
            self._undim()
        super().enterEvent(e)

    # ---------- 边缘吸附 / 离开自动变暗 ----------
    def _screen_geom(self):
        """返回当前窗口所在屏幕的可用区域（避开任务栏）。"""
        scr = self.screen()
        if scr is not None:
            return scr.availableGeometry()
        return QApplication.primaryScreen().availableGeometry()

    def _snap_to_edge(self):
        """拖拽松手时若靠近某屏幕边（阈值内），则吸附对齐到该边。"""
        g = self._screen_geom()
        thr = 18
        x, y = self.x(), self.y()
        w, h = self.width(), self.height()
        snapped = False
        if x <= g.x() + thr:
            x = g.x(); snapped = True
        elif x + w >= g.x() + g.width() - thr:
            x = g.x() + g.width() - w; snapped = True
        if y <= g.y() + thr:
            y = g.y(); snapped = True
        elif y + h >= g.y() + g.height() - thr:
            y = g.y() + g.height() - h; snapped = True
        if snapped:
            self.move(x, y)

    def _dim(self):
        """鼠标离开 2 秒后触发：进入变暗状态（内容降到约 10% 可见），并显示提示条。"""
        if self._dimmed or not self.auto_dim or self.dragging:
            return
        self._dimmed = True
        self.update()

    def _undim(self):
        """从变暗状态恢复。"""
        if not self._dimmed:
            return
        self._dimmed = False
        self.update()
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._kl = None

        rect = self.rect()
        p.setBrush(QBrush(PANEL))
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 12, 12)

        # 各标的行
        rm = int(12 * SCALE)
        pw = int(118 * SCALE)
        px = W - rm - pw
        for i, secid in enumerate(ORDER):
            y = TOP + i * ROW_H
            if i == self.active:
                p.setBrush(QBrush(HL))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRect(6, y - 2, W - 12, ROW_H - 2), 7, 7)
            p.setPen(Qt.NoPen)

            nm = SECIDS.get(secid) or secid
            d = self.data.get(secid, {})
            q = d.get("q")
            if q and q.get("name"):
                nm = q["name"]

            # 名称
            p.setPen(WHITE)
            p.setFont(QFont("Microsoft YaHei", FS(12), QFont.Bold))
            p.drawText(QRect(12, y, px - 18, ROW_H - 2),
                       Qt.AlignLeft | Qt.AlignVCenter, nm)

            # 价格 + 涨跌幅
            if q and q.get("price") is not None:
                # 二次防御：即便数据层漏转，这里也兜成数值，避免主线程绘制抛异常闪退
                price = _num(q.get("price")) or 0.0
                pct = _num(q.get("pct")) or 0.0
                col = RED if pct >= 0 else GREEN
                p.setPen(WHITE)
                p.setFont(QFont("Consolas", FS(13), QFont.Bold))
                p.drawText(QRect(px, y, pw, ROW_H // 2),
                           Qt.AlignRight | Qt.AlignVCenter,
                           f"{price:.2f}")
                p.setPen(col)
                p.setFont(QFont("Consolas", FS(11)))
                sign = "+" if pct >= 0 else ""
                am = _num(q.get("chg")) or 0.0
                ams = "+" if am >= 0 else ""
                p.drawText(QRect(px - int(8 * SCALE), y + ROW_H // 2,
                                 pw + int(8 * SCALE), ROW_H // 2),
                           Qt.AlignRight | Qt.AlignVCenter,
                           f"{sign}{pct:.2f}%  {ams}{am:.2f}")
            else:
                p.setPen(GREY)
                p.setFont(QFont("Microsoft YaHei", FS(11)))
                p.drawText(QRect(px, y, pw, ROW_H - 2),
                           Qt.AlignRight | Qt.AlignVCenter, "连接中…")

        # K 线区域
        if self.show_kline and ORDER:
            kx = int(10 * SCALE)
            ky = rows_h()
            kw = W - int(20 * SCALE)
            kh = H_KLINE - int(6 * SCALE)
            active_secid = ORDER[self.active]
            anm = SECIDS.get(active_secid) or active_secid
            aq = self.data.get(active_secid, {}).get("q")
            if aq and aq.get("name"):
                anm = aq["name"]
            p.setPen(GREY)
            p.setFont(QFont("Microsoft YaHei", FS(10)))
            kn = self._klt_name()
            klabel = kn if kn.endswith("K") else kn + "K"
            p.drawText(QRect(kx, ky - int(4 * SCALE), kw, int(14 * SCALE)),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       f"{anm}  ·  {klabel}")
            bars = self.data.get(active_secid, {}).get("k") or []
            if bars:
                bars = bars[-self.kzoom:]
            self._draw_kline(p, kx, ky + int(14 * SCALE), kw, kh - int(14 * SCALE), bars)
            if bars:
                n = len(bars)
                self._kl = {
                    "x": kx, "y": ky + int(14 * SCALE),
                    "w": kw, "h": kh - int(14 * SCALE),
                    "bars": bars, "cw": kw / n,
                }
                self._draw_hover(p)
            else:
                self._kl = None

        # 变暗状态：覆盖一层半透明遮罩把内容降到约 10% 可见，并在顶部画醒目提示条
        if self._dimmed:
            p.setBrush(QBrush(QColor(8, 9, 12, 224)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 12, 12)
            hint = "已隐藏 · 鼠标移入窗口恢复"
            p.setFont(QFont("Microsoft YaHei", FS(11), QFont.Bold))
            fm = p.fontMetrics()
            hw = fm.horizontalAdvance(hint) + 22
            hh = int(22 * SCALE)
            hx = max(4, (W - hw) // 2)
            hy = 4
            p.setBrush(QBrush(QColor(0x2A, 0x6E, 0xFF, 235)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRect(hx, hy, hw, hh), 6, 6)
            p.setPen(QColor(255, 255, 255, 255))
            p.drawText(QRect(hx, hy, hw, hh), Qt.AlignCenter, hint)

        p.end()

    def _klt_name(self):
        inv = {v: k for k, v in KLT_OPTIONS.items()}
        return inv.get(CURRENT_KLT, str(CURRENT_KLT))

    def _draw_kline(self, p, x, y, w, h, bars):
        if not bars:
            p.setPen(GREY)
            p.setFont(QFont("Microsoft YaHei", FS(11)))
            p.drawText(QRect(x, y, w, h), Qt.AlignCenter, "暂无K线数据")
            return

        highs = [b["h"] for b in bars]
        lows = [b["l"] for b in bars]
        mx, mn = max(highs), min(lows)
        rng = (mx - mn) if mx > mn else 1.0
        pad = 6
        n = len(bars)
        cw = w / n
        bw = max(1.5, cw * 0.62)

        def ymap(v):
            return y + h - ((v - mn) / rng) * (h - 2 * pad) - pad

        for i, b in enumerate(bars):
            cx = x + i * cw + cw / 2
            yo, yc = ymap(b["o"]), ymap(b["c"])
            yh, yl = ymap(b["h"]), ymap(b["l"])
            up = b["c"] >= b["o"]
            col = RED if up else GREEN
            p.setPen(QPen(col, 1))
            p.setBrush(QBrush(col))
            p.drawLine(int(cx), int(yh), int(cx), int(yl))
            top = min(yo, yc)
            bh = max(1.0, abs(yc - yo))
            p.drawRect(int(cx - bw / 2), int(top), int(bw), int(bh))

        # 最新价虚线（深浅主题下均可见的中性灰）
        last = bars[-1]["c"]
        ly = ymap(last)
        p.setPen(QPen(QColor(150, 150, 150, 170), 1, Qt.DashLine))
        p.drawLine(x, int(ly), x + w, int(ly))

        # 高/低标签
        p.setPen(GREY)
        p.setFont(QFont("Consolas", FS(9)))
        p.drawText(QRect(x, y, w, 12), Qt.AlignRight | Qt.AlignTop, f"{mx:.2f}")
        p.drawText(QRect(x, y + h - 12, w, 12), Qt.AlignRight | Qt.AlignBottom, f"{mn:.2f}")

    def _draw_hover(self, p):
        if self._hover is None or self._kl is None:
            return
        bars = self._kl["bars"]
        if not (0 <= self._hover < len(bars)):
            return
        b = bars[self._hover]
        cx = self._kl["x"] + self._hover * self._kl["cw"] + self._kl["cw"] / 2
        top_y = self._kl["y"]
        bot_y = self._kl["y"] + self._kl["h"]
        # 竖直指示线（深浅主题下均可见的中性灰）
        p.setPen(QPen(QColor(150, 150, 150, 220), 1))
        p.drawLine(int(cx), int(top_y), int(cx), int(bot_y))
        # 数值框：显示该根时间戳 + OHLC；时间戳便于核对周期是否准确，底色跟随主题
        txt_t = b["t"]
        txt_o = (f"开 {b['o']:.2f}  高 {b['h']:.2f}  "
                 f"低 {b['l']:.2f}  收 {b['c']:.2f}")
        # 动态选字号：保证两行框能放进「整个窗口」宽高（小缩放下框比窗口大才会被裁）
        fs = max(7, FS(10))
        while fs >= 7:
            p.setFont(QFont("Consolas", fs))
            fm = p.fontMetrics()
            th = int(fm.lineSpacing() * 2 + 6)
            tw = (max(fm.horizontalAdvance(txt_t),
                      fm.horizontalAdvance(txt_o)) + 12)
            if th <= self.height() - 6 and tw <= W - 6:
                break
            fs -= 1
        p.setFont(QFont("Consolas", fs))
        fm = p.fontMetrics()
        th = int(fm.lineSpacing() * 2 + 6)
        tw = max(fm.horizontalAdvance(txt_t),
                 fm.horizontalAdvance(txt_o)) + 12
        # 水平：优先放光标右侧，超出窗口则翻到左侧；整体夹在窗口内避免被裁
        lx = int(cx) + 8
        if lx + tw > W:
            lx = int(cx) - tw - 8
        if lx < 0:
            lx = 0
        if lx + tw > W:
            lx = max(0, W - tw)
        # 垂直：优先放在 K 线「上方」不挡柱；越界则夹到窗口内（用整窗高度，不局限 K 线区）
        ly = int(top_y) - th - 2
        if ly < 0:
            ly = int(bot_y) + 2
        if ly + th > self.height():
            ly = max(0, self.height() - th)
        p.setBrush(QBrush(PANEL))
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(QRect(lx, ly, tw, th), 4, 4)
        p.setPen(WHITE)
        p.drawText(QRect(lx, ly, tw, th // 2), Qt.AlignCenter, txt_t)
        p.drawText(QRect(lx, ly + th // 2, tw, th // 2), Qt.AlignCenter, txt_o)


# ----------------------------- 入口 -----------------------------
def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(APP_ICON))
    app.setQuitOnLastWindowClosed(False)
    w = Ticker()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
