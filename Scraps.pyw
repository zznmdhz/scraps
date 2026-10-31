# -*- coding: utf-8 -*-
"""Scraps · 碎片台 v2 — 极简语音/文本碎片钉屏工具（单文件、零依赖）。

核心交互：输入框在最下方 → 回车一条 → 立刻钉到上方；最新的在最上，最早的沉底。
每块可：复制 / 常驻(置顶区) / 归档 / 销毁(可撤销) / 发送到其他窗口。
数据存于数据目录（命令行 --data <dir> 可覆盖）。
"""
import json
import os
import sys
import time
import uuid
import traceback

import tkinter as tk
from tkinter import ttk

APP_NAME = "Scraps"
APP_TITLE = "Scraps · 碎片台"

DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "TextScraps")

# ---------------------------------------------------------------- 主题
BG0 = "#0C0F11"
PANEL = "#12171B"
CARD = "#161C21"
CARD_H = "#1C242A"
BORDER = "#232B31"
TEXT = "#DCE3E8"
MUTED = "#7C8A93"
ACCENT = "#F5A623"
DANGER = "#E0685A"
WHITE = "#F2F5F7"

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_SM = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 9)
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")

INPUT_MIN_H, INPUT_MAX_H = 2, 8


def now():
    return time.time()


def fmt_ts(ts, with_date=False):
    t = time.localtime(ts)
    if with_date:
        return time.strftime("%m-%d %H:%M", t)
    return time.strftime("%H:%M", t)


def new_id():
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- 数据层
class Store:
    """JSON 文件存储，原子写入；对话(stream) + 块(block) 两级。"""

    def __init__(self, path):
        self.path = path
        self.data = None
        self.load_error = None
        self._undo = None
        self.load()

    def load(self):
        self.data = {"version": 2, "threads": []}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("threads"), list):
                self.data = raw
            else:
                raise ValueError("结构不对")
        except Exception as e:
            self.load_error = str(e)
            try:
                backup = self.path + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S")
                os.replace(self.path, backup)
            except Exception:
                pass

    def save(self):
        d = os.path.dirname(self.path)
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ---- 对话 ----
    def threads(self):
        return self.data["threads"]

    def get_thread(self, tid):
        for t in self.threads():
            if t["id"] == tid:
                return t
        return None

    def new_thread(self, title=None):
        t = {"id": new_id(),
             "title": title or ("对话 " + time.strftime("%m-%d %H:%M")),
             "created": now(), "updated": now(), "archived": False, "blocks": []}
        self.threads().append(t)
        self.save()
        return t

    def list_streams(self, archived=False):
        """未归档对话按最近更新在前；归档对话同样排序。"""
        ts = [t for t in self.threads() if bool(t.get("archived")) == archived]
        return sorted(ts, key=lambda t: -t.get("updated", 0))

    def rename_thread(self, tid, title):
        t = self.get_thread(tid)
        if t and title.strip():
            t["title"] = title.strip()
            t["updated"] = now()
            self.save()

    def set_thread_archived(self, tid, val):
        t = self.get_thread(tid)
        if t:
            t["archived"] = val
            t["updated"] = now()
            self.save()
            return True
        return False

    def destroy_thread(self, tid):
        for i, t in enumerate(self.threads()):
            if t["id"] == tid:
                self.threads().pop(i)
                self._undo = {"kind": "thread", "thread": t, "index": i}
                self.save()
                return True
        return False

    # ---- 块 ----
    @staticmethod
    def block_index(t, bid):
        for i, b in enumerate(t["blocks"]):
            if b["id"] == bid:
                return i
        return None

    def add_block(self, tid, text):
        t = self.get_thread(tid)
        if not t:
            return None
        b = {"id": new_id(), "text": text, "ts": now(),
             "pinned": False, "archived": False}
        t["blocks"].append(b)
        t["updated"] = now()
        self.save()
        return b

    def set_block_flag(self, tid, bid, key, val):
        t = self.get_thread(tid)
        idx = self.block_index(t, bid) if t else None
        if idx is None:
            return False
        t["blocks"][idx][key] = val
        t["updated"] = now()
        self.save()
        return True

    def destroy_block(self, tid, bid):
        t = self.get_thread(tid)
        idx = self.block_index(t, bid) if t else None
        if idx is None:
            return False
        b = t["blocks"].pop(idx)
        t["updated"] = now()
        self._undo = {"kind": "block", "tid": tid, "block": b, "index": idx}
        self.save()
        return True

    def move_block(self, from_tid, bid, to_tid):
        if from_tid == to_tid:
            return False
        src, dst = self.get_thread(from_tid), self.get_thread(to_tid)
        idx = self.block_index(src, bid) if src else None
        if idx is None or not dst:
            return False
        b = src["blocks"].pop(idx)
        dst["blocks"].append(b)
        src["updated"] = now()
        dst["updated"] = now()
        self.save()
        return True

    def undo(self):
        op = self._undo
        if not op:
            return False
        self._undo = None
        if op["kind"] == "thread":
            self.threads().insert(min(op["index"], len(self.threads())), op["thread"])
        else:
            t = self.get_thread(op["tid"])
            if t:
                t["blocks"].insert(min(op["index"], len(t["blocks"])), op["block"])
        self.save()
        return True

    def counts(self):
        return len(self.threads()), sum(len(t["blocks"]) for t in self.threads())


# ---------------------------------------------------------------- 系统集成
def press_voice_hotkey():
    """全局按下 Win+H 唤起 Windows 自带语音输入（系统级，免费，中英皆可）。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN, VK_H = 0x5B, 0x48
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_H, 0, 0, 0)
        user32.keybd_event(VK_H, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        return True
    except Exception:
        return False


def focus_existing_instance(prefix=APP_TITLE):
    """第二次双击启动时，找到已运行的窗口置前，而不是静默退出。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(prefix) and user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(cb, 0)
        if found:
            user32.SetForegroundWindow(found[0])
            return True
    except Exception:
        pass
    return False


def acquire_mutex(name):
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, name)
    return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- UI 组件
class Btn(tk.Label):
    """扁平文字按钮：无边框、悬停变色、手型光标。"""

    def __init__(self, master, text, command=None, bg=CARD, hover=CARD_H,
                 fg=TEXT, hover_fg=WHITE, font=FONT_SM, pad=(10, 4), **kw):
        super().__init__(master, text=text, bg=bg, fg=fg, font=font, cursor="hand2",
                         padx=pad[0], pady=pad[1], **kw)
        self._cmd = command
        self._bg, self._hover = bg, hover
        self._fg, self._hover_fg = fg, hover_fg
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self.config(bg=self._hover, fg=self._hover_fg))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg, fg=self._fg))

    def _click(self, e):
        if self._cmd:
            self._cmd()
        return "break"

    def set_text_color(self, fg):
        self._fg = fg
        self.config(fg=fg)


def bind_wheel(widget, fn):
    widget.bind("<MouseWheel>", fn)
    for c in widget.winfo_children():
        bind_wheel(c, fn)


class ScrollFrame(tk.Frame):
    """Canvas + 内部 Frame 的纵向滚动容器。"""

    def __init__(self, master, bg=BG0):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                style="Dark.TScrollbar")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Enter>", lambda e: self.rebind_wheel())

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "unit")

    def rebind_wheel(self):
        bind_wheel(self.body, self._wheel)

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def scroll_top(self):
        self.canvas.yview_moveto(0.0)

    def scroll_bottom(self):
        self.canvas.yview_moveto(1.0)


class InputDialog:
    def __init__(self, parent, title, initial=""):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.configure(bg=BG0)
        self.top.resizable(False, False)
        self.top.transient(parent)
        tk.Label(self.top, text=title, font=FONT_UI, bg=BG0, fg=WHITE).pack(padx=14,
                                                                            pady=(12, 4))
        self.e = tk.Entry(self.top, font=FONT_UI, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                          relief="flat", width=34)
        self.e.pack(padx=14, pady=4, ipady=5)
        self.e.insert(0, initial)
        self.e.select_range(0, "end")
        row = tk.Frame(self.top, bg=BG0)
        row.pack(pady=10)
        Btn(row, "取消", self.top.destroy, bg=BG0, hover=CARD).pack(side="left", padx=6)
        Btn(row, "确定", self.ok, bg=BG0, hover=CARD, fg=ACCENT, hover_fg=ACCENT).pack(side="left")
        self.e.bind("<Return>", lambda e: self.ok())
        self.e.focus_set()

    def ok(self):
        self.result = self.e.get().strip()
        self.top.destroy()


class ConfirmDialog:
    def __init__(self, parent, title, text):
        self.ok = False
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.configure(bg=BG0)
        self.top.resizable(False, False)
        self.top.transient(parent)
        tk.Label(self.top, text=text, font=FONT_UI, bg=BG0, fg=TEXT, justify="left").pack(
            padx=16, pady=(14, 6))
        row = tk.Frame(self.top, bg=BG0)
        row.pack(pady=10)
        Btn(row, "取消", self.top.destroy, bg=BG0, hover=CARD).pack(side="left", padx=6)

        def yes():
            self.ok = True
            self.top.destroy()
        Btn(row, "确定销毁", yes, bg=BG0, hover="#2A1714", fg=DANGER, hover_fg=DANGER).pack(side="left")


# ---------------------------------------------------------------- 窗口
class Win:
    """极简窗口：底部输入 → 回车钉到上方；最新的在最上，最早的沉底。"""

    def __init__(self, app, tid=None):
        self.app = app
        self.topmost = False
        self.show_archived = False
        self._undo_btns = []

        self.root = tk.Toplevel(app.root)
        self.root.configure(bg=BG0)
        self.root.minsize(380, 380)
        n = len(app.windows)
        self.root.geometry("520x620+%d+%d" % (110 + n * 36, 80 + n * 32))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_topbar()
        self.stack = ScrollFrame(self.root, bg=BG0)
        self.stack.pack(fill="both", expand=True, padx=10, pady=(6, 2))
        self._build_input()
        self._build_status()

        if tid is None:
            lst = app.store.list_streams(False)
            tid = lst[0]["id"] if lst else None
        self.select_thread(tid, focus_input=False)

    # ---------- 骨架 ----------
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(side="top", fill="x")
        tk.Label(bar, text=APP_NAME, font=FONT_TITLE, bg=PANEL, fg=WHITE,
                 padx=10, pady=7).pack(side="left")
        self.btn_dialog = Btn(bar, "对话 ▾", self.dialog_menu, bg=PANEL, hover=CARD_H,
                              fg=ACCENT, hover_fg=ACCENT, pad=(10, 7))
        self.btn_dialog.pack(side="left")
        self.btn_dialog.bind("<Double-Button-1>", lambda e: self.rename_thread())
        self.btn_top = Btn(bar, "📌 置顶", self.toggle_topmost, bg=PANEL, hover=CARD_H,
                           fg=MUTED, hover_fg=ACCENT, pad=(8, 7))
        self.btn_top.pack(side="right")
        Btn(bar, "⧉ 新窗口", self.new_window, bg=PANEL, hover=CARD_H, fg=MUTED,
            hover_fg=WHITE, pad=(8, 7)).pack(side="right")

    def _build_input(self):
        fr = tk.Frame(self.root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        fr.pack(side="bottom", fill="x")
        self.input = tk.Text(fr, height=INPUT_MIN_H, bg=PANEL, fg=TEXT,
                             insertbackground=TEXT, selectbackground=BORDER,
                             relief="flat", font=FONT_UI, wrap="word",
                             padx=10, pady=8, bd=0, highlightthickness=0)
        self.input.pack(fill="x", padx=8, pady=(8, 2))
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<Shift-Return>", lambda e: None)
        self.input.bind("<<Modified>>", self._on_modified)
        row = tk.Frame(fr, bg=PANEL)
        row.pack(fill="x", padx=8, pady=(0, 8))
        Btn(row, "🎤 语音", self.voice_input, bg=PANEL, hover=CARD_H, fg=MUTED,
            hover_fg=ACCENT).pack(side="left")
        Btn(row, "📋 粘贴为块", self.paste_as_block, bg=PANEL, hover=CARD_H, fg=MUTED,
            hover_fg=WHITE).pack(side="left")
        Btn(row, "⏎ 钉住", self.post_block, bg=PANEL, hover=CARD_H, fg=ACCENT,
            hover_fg=ACCENT).pack(side="right")
        tk.Label(row, text="回车=钉住 · Shift+回车换行", font=("Microsoft YaHei UI", 8),
                 bg=PANEL, fg=MUTED).pack(side="right", padx=8)

    def _build_status(self):
        self.status_fr = tk.Frame(self.root, bg=BG0)
        self.status_fr.pack(side="bottom", fill="x")
        self.lbl_status = tk.Label(self.status_fr, text="", font=("Microsoft YaHei UI", 8),
                                   bg=BG0, fg=MUTED, anchor="w", padx=10, pady=3)
        self.lbl_status.pack(fill="x")
        self.refresh_status()

    def refresh_status(self, msg=None):
        self._clear_undo_btns()
        t, b = self.app.store.counts()
        base = "%d 对话 / %d 块 · 数据: %s" % (t, b, self.app.store.path)
        if self.app.store.load_error:
            base = "⚠ 数据文件曾损坏已备份 · " + base
        self.lbl_status.config(text=(msg + "   |   " if msg else "") + base)

    def status_flash(self, msg, undo=False):
        self._clear_undo_btns()
        self.lbl_status.config(text=msg)
        if undo:
            b = Btn(self.status_fr, "↩ 撤销", self.undo_last, bg=BG0, hover=CARD,
                    fg=ACCENT, hover_fg=ACCENT)
            b.pack(side="right", padx=10)
            self._undo_btns = [b]
            self.root.after(8000, self.refresh_status)
        else:
            self.root.after(3000, self.refresh_status)

    def _clear_undo_btns(self):
        for b in self._undo_btns:
            try:
                b.destroy()
            except Exception:
                pass
        self._undo_btns = []

    def undo_last(self):
        if self.app.store.undo():
            self.app.broadcast()
            self.status_flash("已撤销")

    # ---------- 渲染：常驻区 → 正常区(新在上) → 归档区 ----------
    def rebuild(self):
        st = self.app.store
        t = st.get_thread(self.tid)
        self.stack.clear()
        if not t:
            self.btn_dialog.config(text="没有对话 ▾")
            self.root.title(APP_TITLE)
            tk.Label(self.stack.body, text="点上方「对话 ▾ → ＋ 新对话」\n然后在下面输入，回车即钉住",
                     font=FONT_SM, bg=BG0, fg=MUTED, justify="left").pack(pady=40, padx=12)
            self.stack.rebind_wheel()
            return
        self.btn_dialog.config(text=t["title"][:14] + ("… " if len(t["title"]) > 14 else " ") + "▾")
        self.root.title("%s — %s" % (APP_TITLE, t["title"]))

        blocks = t["blocks"]
        pinned = [b for b in blocks if b.get("pinned") and not b.get("archived")]
        normal = [b for b in blocks if not b.get("pinned") and not b.get("archived")]
        archived = [b for b in blocks if b.get("archived")]

        if t.get("archived"):
            ban = tk.Frame(self.stack.body, bg="#241C13")
            ban.pack(fill="x", pady=(0, 4))
            tk.Label(ban, text="该对话已归档", font=FONT_SM, bg="#241C13", fg=ACCENT,
                     padx=8, pady=3).pack(side="left")
            Btn(ban, "↩ 恢复对话", lambda: self.set_thread_archived(False), bg="#241C13",
                hover="#332718", fg=TEXT).pack(side="right")

        if pinned:
            tk.Label(self.stack.body, text="★ 常驻 (%d)" % len(pinned),
                     font=("Microsoft YaHei UI", 8), bg=BG0, fg=ACCENT, anchor="w").pack(
                fill="x", padx=2, pady=(0, 2))
            for b in reversed(pinned):          # 新的在上
                self._render_card(t, b, blocks)

        for b in reversed(normal):              # 新的在上，旧的沉底
            self._render_card(t, b, blocks)

        if archived:
            txt = ("▾" if self.show_archived else "▸") + " 归档 (%d)" % len(archived)
            Btn(self.stack.body, txt, self.toggle_archived, bg=BG0, hover=CARD,
                fg=MUTED, hover_fg=WHITE, font=("Microsoft YaHei UI", 8), pad=(2, 6)).pack(
                fill="x", anchor="w")
            if self.show_archived:
                for b in reversed(archived):
                    self._render_card(t, b, blocks, dim=True)
        self.stack.rebind_wheel()

    def toggle_archived(self):
        self.show_archived = not self.show_archived
        self.rebuild()

    def _render_card(self, t, b, blocks, dim=False):
        num = self.app.store.block_index(t, b["id"]) + 1
        card = tk.Frame(self.stack.body, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=3)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=8, pady=(5, 0))
        meta = ("📌 " if b.get("pinned") else "") + "#" + str(num) + "  " + fmt_ts(b["ts"])
        tk.Label(head, text=meta, font=FONT_MONO, bg=CARD,
                 fg=MUTED if not dim else "#5A656C").pack(side="left")
        tk.Label(card, text=b["text"], font=FONT_UI, bg=CARD,
                 fg=TEXT if not dim else "#6E7980", justify="left", wraplength=420,
                 anchor="w", padx=8, pady=4).pack(fill="x")

        acts = tk.Frame(card, bg=CARD)
        acts.pack(fill="x", padx=4, pady=(0, 4))
        Btn(acts, "⧉ 复制", lambda bid=b["id"]: self.copy_block(bid), bg=CARD,
            hover=CARD_H, fg=MUTED, hover_fg=ACCENT, pad=(6, 2)).pack(side="left")
        if not dim:
            Btn(acts, "★ 常驻" if not b.get("pinned") else "☆ 取消常驻",
                lambda bid=b["id"]: self.toggle_pin_block(bid), bg=CARD, hover=CARD_H,
                fg=ACCENT if b.get("pinned") else MUTED, hover_fg=ACCENT,
                pad=(6, 2)).pack(side="left")
            send = tk.Menu(acts, tearoff=0, bg=CARD, fg=TEXT, activebackground=BORDER,
                           bd=0, font=FONT_SM)
            for ot in self.app.store.list_streams(False):
                if ot["id"] != t["id"]:
                    send.add_command(label="对话: " + ot["title"][:16],
                                     command=lambda bid=b["id"], oid=ot["id"]:
                                     self.move_block_to(bid, oid))
            send.add_command(label="＋ 新对话", command=lambda bid=b["id"]: self.move_block_new(bid))
            for w in self.app.windows:
                if w is not self:
                    send.add_command(label="窗口 %d 当前对话" % (self.app.windows.index(w) + 1),
                                     command=lambda bid=b["id"], w=w: self.move_block_to_win(bid, w))
            Btn(acts, "⇢ 发送到", lambda e, menu=send: menu.tk_popup(e.x_root, e.y_root),
                bg=CARD, hover=CARD_H, fg=MUTED, hover_fg=WHITE, pad=(6, 2)).pack(side="left")
        Btn(acts, "↩ 恢复" if dim else "▸ 归档",
            lambda bid=b["id"], d=dim: self.restore_block(bid) if d else self.archive_block(bid),
            bg=CARD, hover=CARD_H, fg=MUTED, hover_fg=WHITE, pad=(6, 2)).pack(side="right")
        Btn(acts, "✕ 销毁", lambda bid=b["id"]: self.destroy_block(bid), bg=CARD,
            hover=CARD_H, fg=DANGER, hover_fg=DANGER, pad=(6, 2)).pack(side="right")

    # ---------- 输入 ----------
    def _on_enter(self, e):
        self.post_block()
        return "break"

    def _on_modified(self, e):
        if self.input.edit_modified():
            lines = int(self.input.index("end-1c").split(".")[0])
            self.input.config(height=max(INPUT_MIN_H, min(INPUT_MAX_H, lines)))
            self.input.edit_modified(False)

    def post_block(self, text=None):
        if not self.tid:
            self.tid = self.app.store.new_thread()["id"]
        txt = text if text is not None else self.input.get("1.0", "end-1c").strip()
        if not txt:
            return
        b = self.app.store.add_block(self.tid, txt)
        self.input.delete("1.0", "end")
        self.app.broadcast()
        self.stack.scroll_top()
        self.input.focus_set()
        num = self.app.store.block_index(self.app.store.get_thread(self.tid), b["id"]) + 1
        self.status_flash("已钉住 #%d（新内容在最上面）" % num)

    def voice_input(self):
        self.input.focus_set()
        if press_voice_hotkey():
            self.status_flash("语音输入已唤起（Win+H），说完回车钉住")
        else:
            self.status_flash("唤起失败，请手动按 Win+H")

    def paste_as_block(self):
        try:
            txt = self.input.clipboard_get().strip()
        except Exception:
            self.status_flash("剪贴板是空的")
            return
        if txt:
            self.post_block(txt)

    # ---------- 块操作 ----------
    def copy_text(self, txt):
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.root.update_idletasks()

    def copy_block(self, bid):
        t = self.app.store.get_thread(self.tid)
        b = next((x for x in t["blocks"] if x["id"] == bid), None)
        if b:
            self.copy_text(b["text"])
            self.status_flash("已复制 #%d 到剪贴板" % (self.app.store.block_index(t, bid) + 1))

    def copy_thread(self):
        t = self.app.store.get_thread(self.tid)
        if not t:
            return
        lines = ["【%s】" % t["title"]]
        for i, b in enumerate(t["blocks"]):
            if not b.get("archived"):
                lines.append("#%d %s  %s" % (i + 1, fmt_ts(b["ts"]), b["text"]))
        self.copy_text("\n".join(lines))
        self.status_flash("已复制整段对话（%d 块）" % len(t["blocks"]))

    def toggle_pin_block(self, bid):
        t = self.app.store.get_thread(self.tid)
        b = next(x for x in t["blocks"] if x["id"] == bid)
        self.app.store.set_block_flag(self.tid, bid, "pinned", not b.get("pinned"))
        self.app.broadcast()

    def archive_block(self, bid):
        self.app.store.set_block_flag(self.tid, bid, "archived", True)
        self.app.broadcast()

    def restore_block(self, bid):
        self.app.store.set_block_flag(self.tid, bid, "archived", False)
        self.app.broadcast()

    def destroy_block(self, bid):
        self.app.store.destroy_block(self.tid, bid)
        self.app.broadcast()
        self.status_flash("已销毁，8 秒内可撤销", undo=True)

    def move_block_to(self, bid, to_tid):
        if self.app.store.move_block(self.tid, bid, to_tid):
            self.app.broadcast()
            tt = self.app.store.get_thread(to_tid)
            self.status_flash("块已移动到「%s」" % (tt["title"] if tt else "?"))

    def move_block_new(self, bid):
        t = self.app.store.new_thread()
        self.move_block_to(bid, t["id"])
        self.select_thread(t["id"])

    def move_block_to_win(self, bid, win):
        if win.tid and win.tid != self.tid:
            self.move_block_to(bid, win.tid)
        else:
            self.status_flash("目标窗口当前就是这个对话")

    # ---------- 对话 ----------
    def select_thread(self, tid, focus_input=True):
        self.tid = tid
        self.show_archived = False
        self.rebuild()
        self.stack.scroll_bottom()          # 老内容沉底，顶部留白给新块
        if focus_input:
            self.input.focus_set()

    def dialog_menu(self):
        st = self.app.store
        m = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT, activebackground=BORDER,
                    activeforeground=WHITE, bd=0, font=FONT_SM)
        m.add_command(label="＋ 新对话", command=self.new_thread)
        m.add_command(label="✎ 重命名当前对话", command=lambda: self.rename_thread(self.tid))
        m.add_command(label="⧉ 复制整段对话", command=self.copy_thread)
        m.add_separator()
        live = st.list_streams(False)
        if live:
            m.add_command(label="—— 切换对话 ——", state="disabled")
        for t in live:
            mark = "▸ " if t["id"] == self.tid else "   "
            m.add_command(label=mark + t["title"][:18],
                          command=lambda tid=t["id"]: self.select_thread(tid))
        arch = st.list_streams(True)
        for t in arch:
            m.add_command(label="   " + t["title"][:16] + "（归档）",
                          command=lambda tid=t["id"]: self.select_thread(tid))
        if self.tid:
            m.add_separator()
            cur = st.get_thread(self.tid)
            if cur and cur.get("archived"):
                m.add_command(label="↩ 恢复当前对话", command=lambda: self.set_thread_archived(False))
            else:
                m.add_command(label="▸ 归档当前对话", command=lambda: self.set_thread_archived(True))
            m.add_command(label="✕ 销毁当前对话", foreground=DANGER, command=self.destroy_thread)
        m.tk_popup(self.btn_dialog.winfo_rootx(),
                   self.btn_dialog.winfo_rooty() + self.btn_dialog.winfo_height())

    def new_thread(self):
        t = self.app.store.new_thread()
        self.app.broadcast()
        self.select_thread(t["id"])

    def rename_thread(self, tid=None):
        tid = tid or self.tid
        t = self.app.store.get_thread(tid)
        if not t:
            return
        d = InputDialog(self.root, "重命名对话", t["title"])
        self.root.wait_window(d.top)
        if d.result:
            self.app.store.rename_thread(tid, d.result)
            self.app.broadcast()

    def set_thread_archived(self, val):
        if self.tid:
            self.app.store.set_thread_archived(self.tid, val)
            self.app.broadcast()
            self.status_flash("对话已归档（对话菜单里可切回）" if val else "对话已恢复")

    def destroy_thread(self):
        t = self.app.store.get_thread(self.tid)
        if not t:
            return
        d = ConfirmDialog(self.root, "销毁对话",
                          "「%s」共 %d 块，销毁后 8 秒内可撤销。\n确定销毁？"
                          % (t["title"], len(t["blocks"])))
        self.root.wait_window(d.top)
        if not d.ok:
            return
        self.app.store.destroy_thread(self.tid)
        lst = self.app.store.list_streams(False)
        self.select_thread(lst[0]["id"] if lst else None)
        self.app.broadcast()
        self.status_flash("对话已销毁，8 秒内可撤销", undo=True)

    # ---------- 窗口 ----------
    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.btn_top.set_text_color(ACCENT if self.topmost else MUTED)

    def new_window(self, tid=None):
        self.app.open_window(tid or self.tid)

    def on_close(self):
        self.app.window_closed(self)


# ---------------------------------------------------------------- 应用主控
WELCOME_TEXT = """Scraps 用法（这条示例看完可 ✕ 销毁）：
1. 最下面输入框打字，或点 🎤 语音（等同按 Win+H），说完回车 → 钉住
2. 新钉住的永远在最上面，最早的沉底
3. 每块可 ⧺ 复制、★ 常驻（浮到顶部常驻区）、▸ 归档、✕ 销毁（8秒内可撤销）
4. ⧺ 新窗口可同时挂多个对话；📌 置顶让窗口压在最上面
5. 「⇢ 发送到」把这块贴到别的对话或别的窗口
6. 数据文件位置见底部状态栏"""


class App:
    def __init__(self, store_path=None):
        self.store = Store(store_path or DEFAULT_STORE_PATH)
        self.windows = []
        self.root = tk.Tk()
        self.root.withdraw()
        self._style()
        if not self.store.threads():              # 首次运行放一条示例
            t = self.store.new_thread("Scraps 怎么用")
            for line in WELCOME_TEXT.split("\n"):
                self.store.add_block(t["id"], line)
            self.store.save()
        self.open_window()

    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        for ori in ("Vertical", "Horizontal"):
            try:
                st.layout(ori + ".Dark.TScrollbar", st.layout(ori + ".TScrollbar"))
            except Exception:
                pass
        st.configure("Dark.TScrollbar", background=CARD, troughcolor=BG0,
                     bordercolor=BG0, arrowcolor=MUTED, borderwidth=0)

    def open_window(self, tid=None):
        w = Win(self, tid)
        self.windows.append(w)
        return w

    def broadcast(self):
        for w in list(self.windows):
            try:
                w.rebuild()
                w.refresh_status()
            except Exception:
                pass

    def window_closed(self, win):
        try:
            self.windows.remove(win)
        except ValueError:
            pass
        win.root.destroy()
        if not self.windows:
            self.root.quit()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- 冒烟自检
def run_smoke(store_path, report_path):
    """真实建 UI + 走一遍核心链路，结果写 report_path，3.6 秒后自动退出。"""
    global DEFAULT_STORE_PATH
    DEFAULT_STORE_PATH = store_path
    app = App(store_path=store_path)
    w = app.windows[0]
    rep = {"ok": False, "steps": []}

    def step(name, fn):
        try:
            fn()
            rep["steps"].append({"name": name, "ok": True})
        except Exception:
            rep["steps"].append({"name": name, "ok": False, "err": traceback.format_exc()})

    def card_texts():
        """按显示顺序返回每张卡的正文。"""
        out = []
        for c in w.stack.body.winfo_children():
            if isinstance(c, tk.Frame):
                for sub in c.winfo_children():
                    if isinstance(sub, tk.Label):
                        out.append(sub.cget("text"))
                        break
        return out

    def body():
        try:
            st = app.store
            t = st.new_thread("冒烟对话")
            app.broadcast()
            w.select_thread(t["id"])

            def post3():
                for txt in ("第一段：最早说的", "第二段：中间说的", "第三段：最新说的"):
                    w.input.insert("1.0", txt)
                    w.post_block()
            step("连发3块", post3)

            def order_newest_first():
                cts = card_texts()
                assert len(cts) == 3, cts
                assert cts[0].startswith("第三段"), cts
                assert cts[2].startswith("第一段"), cts
            step("新在上旧在下", order_newest_first)

            def pin_top():
                w.toggle_pin_block(t["blocks"][0]["id"])   # 最早那块 → 常驻区
                app.broadcast()
                cts = card_texts()
                assert cts[0].startswith("第一段"), cts
            step("常驻浮顶", pin_top)

            def clip():
                w.copy_block(t["blocks"][2]["id"])
                assert "第三段" in w.root.clipboard_get()
            step("单块复制", clip)

            def clip_thread():
                w.copy_thread()
                got = w.root.clipboard_get()
                assert "冒烟对话" in got and "第一段" in got
            step("整段复制", clip_thread)

            def move():
                t2 = st.new_thread("目标对话")
                assert st.move_block(t["id"], t["blocks"][2]["id"], t2["id"])
                assert len(t2["blocks"]) == 1
                app.broadcast()
            step("块移到别的对话", move)

            def arch():
                w.archive_block(t["blocks"][1]["id"])
                w.toggle_archived()
                cts = card_texts()
                assert any(x.startswith("第二段") for x in cts), cts
                w.restore_block(t["blocks"][1]["id"])
            step("归档+恢复", arch)

            def multiwin():
                w2 = app.open_window(t["id"])
                assert len(app.windows) == 2
                w2.root.destroy()
                app.windows.remove(w2)
            step("多窗口", multiwin)

            def destroy_undo():
                bid = t["blocks"][1]["id"]
                w.destroy_block(bid)
                assert st.undo()
                assert st.block_index(st.get_thread(t["id"]), bid) is not None
            step("销毁+撤销", destroy_undo)

            rep["cards"] = len(card_texts())
            with open(store_path, encoding="utf-8") as f:
                rep["threads_on_disk"] = len(json.load(f)["threads"])
            rep["ok"] = all(s["ok"] for s in rep["steps"])
        except Exception:
            rep["fatal"] = traceback.format_exc()
        finally:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)

    app.root.after(400, body)
    app.root.after(3600, app.root.quit)
    app.run()


# ---------------------------------------------------------------- 入口
DEFAULT_STORE_PATH = os.path.join(DEFAULT_DATA_DIR, "store.json")


def main():
    global DEFAULT_STORE_PATH
    args = sys.argv[1:]
    if "--data" in args:
        i = args.index("--data")
        DEFAULT_STORE_PATH = os.path.join(args[i + 1], "store.json")
    if "--smoke" in args:
        i = args.index("--smoke")
        run_smoke(os.path.join(args[i + 1], "store.json"), args[i + 2])
        return
    if not acquire_mutex("Local\\ScrapsSingleton_v1"):
        focus_existing_instance()
        return
    App().run()


if __name__ == "__main__":
    main()
