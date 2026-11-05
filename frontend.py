#!/usr/bin/env python3

"""
NAVI — signal interface

Отвечает за Tkinter UI, анимацию, IPC, логи и запуск executor.py.
Протокол событий JSON Lines сохранён.
"""

from __future__ import annotations

import json
import math
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path


# ---------------------------------------------------------------------
# конфигурация
# ---------------------------------------------------------------------

WINDOW_W = 720
WINDOW_H = 600

LEFT_W = 240
RIGHT_W = 240

SOCKET_PATH = "/tmp/navi-ui.sock"
CONTROL_SOCKET_PATH = "/tmp/navi-control.sock"
LISTENER_CONTROL_SOCKET_PATH = "/tmp/navi-listener-control.sock"

ROOT = Path(__file__).resolve().parent

BG = "#050811"
LEFT_BG = "#080d18"
PANEL = "#0a1020"
BORDER = "#192741"

TEXT = "#dce7fa"
MUTED = "#72829e"
DIM = "#3d506e"

CYAN = "#4bdcff"
BLUE = "#2379c7"
GREEN = "#80f7b0"
YELLOW = "#ffd479"
RED = "#ff647c"


class NaviFrontend(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("NAVI // signal interface")
        self.resizable(True, True)
        self.minsize(720, 600)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Alt-F4>", lambda _e: self.close())

        x = max(0, (self.winfo_screenwidth() - WINDOW_W) // 2)
        y = max(0, (self.winfo_screenheight() - WINDOW_H) // 2)
        self.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")

        self.state_name = "idle"
        self.hover_core = False
        self.t0 = time.perf_counter()

        self.event_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.executor_lock = threading.Lock()

        self.server = None
        self.listener_client = None
        self.executor = None

        # Значения по умолчанию до первого <Configure>
        self.cx = (WINDOW_W - LEFT_W - RIGHT_W) / 2
        self.cy = WINDOW_H * 0.34
        self.core_scale = 1.0
        self.wave_width = 340

        self._build_ui()
        self._start_executor()
        self._start_ipc()

        self.after(33, self._animation_loop)
        self.after(40, self._poll_events)

        self._log("NAVI interface initialized")

    # =================================================================
    # resize
    # =================================================================

    def _resize_center(self, event):
        if event.widget is not self.center:
            return

        width = max(1, event.width)
        height = max(1, event.height)

        self.cx = width / 2
        self.cy = height * 0.34

        # Масштаб ядра (0.22 вместо 0.24 — даёт запас над статус-бейджем)
        k_h = (height * 0.22) / 164.0
        k_w = (width * 0.5 - 12) / 164.0
        self.core_scale = max(0.3, min(1.0, k_h, k_w))

        if not hasattr(self, "center_footer"):
            return

        try:
            # --- Бейдж ---
            self.status_badge.place_configure(
                x=width // 2, y=int(height * 0.60), anchor="n",
            )

            # --- Заголовок ---
            self.status_title.place_configure(
                x=width // 2, y=int(height * 0.66), anchor="n",
                width=min(430, max(220, width - 24)),
            )

            # --- Подзаголовок ---
            # ВАЖНО: wraplength — опция Label, а не place.
            # Его нельзя передавать в place_configure (иначе TclError и
            # весь resize обрывается на этой строке).
            self.status_subtitle.place_configure(
                x=width // 2, y=int(height * 0.72), anchor="n",
                width=min(430, max(220, width - 24)),
            )
            self.status_subtitle.configure(
                wraplength=min(420, max(200, width - 32)),
            )

            # --- Волна ---
            wave_w = max(160, min(340, width - 40))
            if wave_w != self.wave_width:
                self.wave_width = wave_w
                self.wave.configure(width=wave_w)
            self.wave.place_configure(
                x=width // 2, y=int(height * 0.80), anchor="n",
            )

            # --- Футер ---
            self.center_footer.place_configure(
                x=0, y=max(0, height - 30), width=width,
            )
        except tk.TclError as exc:
            self._log(f"resize_center: {exc}")

    def _resize_left(self, event):
        if event.widget is not self.left:
            return
        self._layout_left(event.height)

    def _layout_left(self, height):
        if not hasattr(self, "left_cards"):
            return

        height = max(1, height)

        self.wake_separator.place_configure(y=height - 160)
        self.wake_label.place_configure(y=height - 142)
        self.wake_value.place_configure(y=height - 118)
        self.local_label.place_configure(y=height - 56)

        top = 150
        gap = 12
        bottom_reserve = 168
        cards_area = height - top - bottom_reserve
        n = len(self.left_cards)
        card_h = max(40, min(91, (cards_area - gap * (n - 1)) / n))
        spacing = card_h + gap
        show_desc = card_h >= 85

        for i, (card, num, ttl, desc) in enumerate(self.left_cards):
            y = top + i * spacing
            card.place(x=15, y=y, width=190, height=card_h)  # было 160

            if show_desc:
                num.place(x=10, y=9, width=28, height=17)
                ttl.place(x=42, y=8, width=140, height=20)  # было 38/112
                desc.place(
                    x=10, y=37, width=170,  # было 140
                    height=max(20, card_h - 45),
                )
            else:
                num.place(x=10, y=(card_h - 17) // 2, width=28, height=17)
                ttl.place(x=42, y=(card_h - 20) // 2, width=140, height=20)
                desc.place_forget()

    def _resize_right(self, event):
        if event.widget is not self.right or not hasattr(self, "log"):
            return

        width = max(170, event.width)
        height = max(200, event.height)

        log_height = max(100, height - 225)
        self.log.place_configure(width=max(120, width - 32), height=log_height)
        self.system_status_label.place_configure(y=height - 107)
        self.system_indicator.place_configure(y=height - 79, width=max(120, width - 32))
        self.socket_label.place_configure(y=height - 44, width=max(120, width - 32))

    # =================================================================
    # UI
    # =================================================================

    def _build_ui(self):
        self.left = tk.Frame(self, bg=LEFT_BG, width=190)
        self.center = tk.Frame(self, bg=BG)
        self.right = tk.Frame(self, bg=BG, width=220)

        self.left.pack(side="left", fill="y")
        self.left.pack_propagate(False)

        self.right.pack(side="right", fill="y")
        self.right.pack_propagate(False)

        self.center.pack(side="left", fill="both", expand=True)

        self._build_left()
        self._build_center()
        self._build_right()
        self.right.bind("<Configure>", self._resize_right, add="+")

    def _label(
            self, parent, text, *,
            x, y, width=None, height=None,
            fg=TEXT, bg=None, size=9,
            font="DejaVu Sans Mono", bold=False,
            anchor="w", justify="left",
            wraplength=None,
    ):
        widget = tk.Label(
            parent,
            text=text,
            fg=fg,
            bg=bg or parent.cget("bg"),
            font=(font, size, "bold" if bold else "normal"),
            anchor=anchor,
            justify=justify,
        )
        if wraplength is not None:
            widget.configure(wraplength=wraplength)

        opts = {"x": x, "y": y}
        if width is not None:
            opts["width"] = width
        if height is not None:
            opts["height"] = height
        widget.place(**opts)
        return widget

    def _build_left(self):
        self._label(
            self.left, "N A V I", x=18, y=24,
            width=184, height=32, fg=CYAN, size=18, bold=True,
        )
        self._label(
            self.left, "SIGNAL / INTERFACE", x=19, y=57,
            width=184, height=18, fg=MUTED, size=7,
        )

        self.left_separator = tk.Frame(self.left, bg=BORDER, height=1)
        self.left_separator.place(x=18, y=91, width=184)

        self._label(
            self.left, "COMMAND INDEX", x=18, y=111,
            width=184, height=18, fg=MUTED, size=8, bold=True,
        )

        items = [
            ("01", "«Введи»", "Ввод продиктованного текста"),
            ("02", "«Нажми»", "Нажатие клавиш"),
            ("03", "«Открой/закрой»", "Запуск/закрытие приложения/вкладки"),
            ("04", "«Фокус»", "Установка фокуса на элемент сайта"),
        ]

        self.left_cards = []
        for number, title, description in items:
            card = tk.Frame(
                self.left,
                bg=LEFT_BG,
                highlightthickness=1,
                highlightbackground=BORDER,
            )
            card.place(x=15, y=150, width=190, height=91)  # было 160

            num = self._label(
                card, number, x=10, y=9,
                width=28, height=17, fg=CYAN, size=8,
            )
            ttl = self._label(
                card, title, x=42, y=8,
                width=140, height=20, fg=TEXT, size=10,  # было 112
            )
            desc = self._label(
                card, description, x=10, y=37,
                width=170, height=42, fg=MUTED,
                size=8, font="DejaVu Sans",
                wraplength=165,  # ключевое
            )
            self.left_cards.append((card, num, ttl, desc))

        self.wake_separator = tk.Frame(self.left, bg=BORDER, height=1)
        self.wake_separator.place(x=18, y=600, width=184)

        self.wake_label = self._label(
            self.left, "WAKE WORD", x=18, y=618,
            width=184, height=17, fg=MUTED, size=8,
        )
        self.wake_value = self._label(
            self.left, "NAVI", x=18, y=642,
            width=184, height=28, fg=CYAN, size=15, bold=True,
        )
        self.local_label = self._label(
            self.left, "LOCAL VOICE SYSTEM", x=18, y=704,
            width=184, height=16, fg=DIM, size=7,
        )

        self.left.bind("<Configure>", self._resize_left, add="+")
        self._layout_left(WINDOW_H)

    def _build_center(self):
        cw = WINDOW_W - LEFT_W - RIGHT_W
        self.cx = cw / 2
        self.cy = WINDOW_H * 0.34
        self.wave_width = 340

        self.center.bind("<Configure>", self._resize_center)

        self.canvas = tk.Canvas(
            self.center,
            width=cw,
            height=WINDOW_H,
            bg=BG,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)

        self.canvas.bind("<Motion>", self._mouse_move)
        self.canvas.bind("<Leave>", self._mouse_leave)
        self.canvas.bind("<Button-1>", self._core_click)

        self.status_badge = tk.Label(
            self.center,
            text="●  SIGNAL STANDBY",
            bg="#0a1825",
            fg=CYAN,
            font=("DejaVu Sans Mono", 8, "bold"),
            padx=12,
            pady=6,
        )
        self.status_badge.place(x=cw // 2, y=458, anchor="n")

        self.status_title = tk.Label(
            self.center,
            text="Канал открыт",
            bg=BG,
            fg=TEXT,
            font=("DejaVu Sans", 18, "bold"),
            justify="center",
        )
        self.status_title.place(
            x=cw // 2, y=503, anchor="n", width=430, height=35,
        )

        self.status_subtitle = tk.Label(
            self.center,
            text="Произнесите NAVI, чтобы обратиться к системе.",
            bg=BG,
            fg=MUTED,
            font=("DejaVu Sans", 10),
            justify="center",
            wraplength=420,
        )
        self.status_subtitle.place(
            x=cw // 2, y=545, anchor="n", width=430, height=36,
        )

        self.wave = tk.Canvas(
            self.center,
            width=340,
            height=43,
            bg=BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            bd=0,
        )
        self.wave.place(x=cw // 2, y=602, anchor="n")

        self.center_footer = self._label(
            self.center, "NAVI / LOCAL INTELLIGENCE NODE",
            x=0, y=721, width=cw, height=18,
            fg=DIM, size=7, anchor="center",
        )

    def _build_right(self):
        self._label(
            self.right, "EVENT STREAM", x=16, y=25,
            width=175, height=20, fg=MUTED, size=8, bold=True,
        )
        self._label(
            self.right, "LIVE // JSONL", x=16, y=48,
            width=175, height=16, fg=DIM, size=7,
        )

        tk.Frame(self.right, bg=BORDER, height=1).place(
            x=16, y=78, width=188,
        )

        self.log = tk.Text(
            self.right,
            bg=BG,
            fg=MUTED,
            insertbackground=CYAN,
            selectbackground="#172844",
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("DejaVu Sans Mono", 8),
            wrap="word",
            state="disabled",
        )
        self.log.place(x=16, y=93, width=188, height=535)

        self.system_status_label = self._label(
            self.right, "SYSTEM STATUS", x=16, y=653,
            width=175, height=18, fg=MUTED, size=8, bold=True,
        )

        self.system_indicator = tk.Label(
            self.right,
            text="●  INITIALIZING",
            bg=BG,
            fg=YELLOW,
            font=("DejaVu Sans Mono", 8),
            anchor="w",
        )
        self.system_indicator.place(x=16, y=681, width=188, height=20)

        self.socket_label = self._label(
            self.right, "LOCAL SOCKET IPC", x=16, y=716,
            width=188, height=16, fg=DIM, size=7,
        )

    # =================================================================
    # state
    # =================================================================

    def set_state(self, state):
        self.state_name = state

        states = {
            "idle": (
                "●  SIGNAL STANDBY",
                "Канал открыт",
                "Произнесите NAVI, чтобы обратиться к системе.",
                CYAN,
                "●  SYSTEM READY",
            ),
            "listening": (
                "●  RECEIVING SIGNAL",
                "Слушаю вас",
                "Запись активна. Говорите после сигнала.",
                CYAN,
                "●  MICROPHONE ACTIVE",
            ),
            "processing": (
                "●  PROCESSING",
                "Обрабатываю запрос",
                "Передаю распознанную команду исполнительному модулю.",
                YELLOW,
                "●  PROCESSING REQUEST",
            ),
            "speaking": (
                "●  RESPONSE",
                "Команда выполняется",
                "NAVI обрабатывает результат.",
                GREEN,
                "●  RESPONSE ACTIVE",
            ),
            "calibrating": (
                "●  CALIBRATION",
                "Калибровка канала",
                "Определяется уровень фонового шума.",
                YELLOW,
                "●  CALIBRATING",
            ),
            "error": (
                "●  SIGNAL ERROR",
                "Сбой системы",
                "Проверьте состояние процессов и журнал событий.",
                RED,
                "●  ATTENTION REQUIRED",
            ),
        }

        badge, title, subtitle, accent, system = states.get(
            state, states["idle"],
        )
        self.status_badge.configure(text=badge, fg=accent)
        self.status_title.configure(text=title)
        self.status_subtitle.configure(text=subtitle)
        self.system_indicator.configure(text=system, fg=accent)

    # =================================================================
    # animation
    # =================================================================

    def _animation_loop(self):
        if self.stop_event.is_set():
            return

        t = time.perf_counter() - self.t0
        self._draw_core(t)
        self._draw_wave(t)

        if self.state_name == "listening":
            pulse = (math.sin(t * 6) + 1) / 2
            self.status_badge.configure(
                bg="#0a1825" if pulse < 0.65 else "#10263a",
            )
        else:
            self.status_badge.configure(bg="#0a1825")

        self.after(33, self._animation_loop)

    def _draw_core(self, t):
        c = self.canvas
        c.delete("visual")

        cx, cy = self.cx, self.cy
        k = self.core_scale
        active = self.state_name == "listening"
        processing = self.state_name == "processing"

        # Фоновые линии сканирования
        span = min(190 * k, cx - 8)
        line_h = 400 * k
        if line_h > 1:
            for i in range(13):
                yy = cy - line_h / 2 + ((i * 43 + int(t * 12) % 43) % line_h)
                c.create_line(
                    cx - span, yy, cx + span, yy,
                    fill="#09111f", width=1, tags="visual",
                )

        # Тихие внешние кольца
        for radius, color in ((164, "#10213a"), (145, "#102b45")):
            r = radius * k
            c.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=color, width=1, tags="visual",
            )

        pulse = math.sin(t * (3.0 if active else 1.2))
        radius = (112 + (8 * pulse if active else 3 * pulse)) * k
        c.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            outline="#153e5b", width=1, tags="visual",
        )

        # Вращающиеся сегменты
        r98 = 98 * k
        for i in range(8):
            start = (t * (35 if active else 12) + i * 45) % 360
            extent = 19 if processing else 27
            c.create_arc(
                cx - r98, cy - r98, cx + r98, cy + r98,
                start=start, extent=extent,
                style="arc",
                outline=CYAN if active else "#28769c",
                width=2 if active else 1,
                tags="visual",
            )

        # Внутренний диск
        disk = (65 + (3 * math.sin(t * 4) if active else 0)) * k
        fill = "#0a1c30" if self.hover_core else "#080f1c"
        c.create_oval(
            cx - disk, cy - disk, cx + disk, cy + disk,
            fill=fill, outline="#204261", width=1, tags="visual",
        )

        # Абстрактный глаз
        eye_w = (43 + (4 * math.sin(t * 5) if active else 0)) * k
        eye_h = (20 + (2 * math.sin(t * 3) if active else 0)) * k
        c.create_oval(
            cx - eye_w, cy - eye_h, cx + eye_w, cy + eye_h,
            outline=CYAN if active else "#4286a8",
            width=2, tags="visual",
        )

        # Зрачок
        orbit = (7 if active else 3) * k
        px = cx + math.cos(t * 1.5) * orbit
        py = cy + math.sin(t * 1.8) * orbit * 0.6
        pupil = 8 * k
        inner = 3 * k
        c.create_oval(
            px - pupil, py - pupil, px + pupil, py + pupil,
            fill=CYAN if active else "#3b99c5",
            outline="", tags="visual",
        )
        c.create_oval(
            px - inner, py - inner, px + inner, py + inner,
            fill="#e5fbff", outline="", tags="visual",
        )

        # Прицельные метки
        mark_r = 132 * k
        mark_len = 9 * k
        for i in range(4):
            angle = t * (0.2 if active else 0.08) + i * math.pi / 2
            x = cx + math.cos(angle) * mark_r
            y = cy + math.sin(angle) * mark_r
            c.create_line(
                x, y,
                x + math.cos(angle) * mark_len,
                y + math.sin(angle) * mark_len,
                fill="#28617f", width=1, tags="visual",
            )

        # Боковые маркеры
        side = 175 * k
        tick = 12 * k
        for dx in (-side, side):
            c.create_line(
                cx + dx, cy,
                cx + dx + (tick if dx < 0 else -tick), cy,
                fill="#1b4966", tags="visual",
            )

    def _draw_wave(self, t):
        c = self.wave
        c.delete("wave")

        width = max(1, getattr(self, "wave_width", 340))
        height = 43
        mid = height / 2
        active = self.state_name == "listening"
        processing = self.state_name == "processing"

        c.create_line(
            0, mid, width, mid,
            fill="#12243a", width=1, tags="wave",
        )

        usable = width - 18
        if usable <= 0:
            return
        bar_count = max(9, int(usable / 8.4))
        step = usable / (bar_count - 1) if bar_count > 1 else usable

        for i in range(bar_count):
            x = 9 + i * step
            a = abs(math.sin(t * 5 + i * 0.53))
            b = abs(math.sin(t * 3.1 + i * 0.87))

            if active:
                amp = 4 + 13 * a + 5 * b
            elif processing:
                amp = 3 + 7 * a
            else:
                amp = 2 + 3 * a

            c.create_line(
                x, mid - amp, x, mid + amp,
                fill=CYAN if active else "#277a9c",
                width=2, tags="wave",
            )

    def _mouse_move(self, event):
        dx = event.x - self.cx
        dy = event.y - self.cy
        self.hover_core = math.hypot(dx, dy) <= 67 * self.core_scale

    def _mouse_leave(self, _event):
        self.hover_core = False

    def _core_click(self, event):
        dx = event.x - self.cx
        dy = event.y - self.cy
        if math.hypot(dx, dy) <= 67 * self.core_scale:
            self._log("CORE: voice activation handled by listener")

    # =================================================================
    # Executor
    # =================================================================

    def _start_executor(self):
        path = ROOT / "executor.py"
        if not path.exists():
            self._log("executor.py not found")
            self.set_state("error")
            return

        try:
            self.executor = subprocess.Popen(
                [sys.executable, str(path)],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            threading.Thread(
                target=self._read_executor, daemon=True,
            ).start()
            self._log("executor: online")
        except Exception as error:
            self._log(f"executor: {error}")
            self.set_state("error")

    def _read_executor(self):
        if not self.executor or not self.executor.stdout:
            return

        for line in self.executor.stdout:
            line = line.strip()

            if not line:
                continue

            try:

                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "log", "message": line}

            if not isinstance(event, dict):
                event = {"type": "log", "message": repr(event)}

            self.event_queue.put(event)

    def _send_executor(self, payload):
        with self.executor_lock:
            if not self.executor or not self.executor.stdin:
                self._log("executor unavailable")
                return
            try:
                self.executor.stdin.write(
                    json.dumps(payload, ensure_ascii=False) + "\n",
                )
                self.executor.stdin.flush()
            except (BrokenPipeError, OSError):
                self._log("executor: connection lost")

    def _set_listener_paused(self, paused):
        command = "pause" if paused else "resume"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(LISTENER_CONTROL_SOCKET_PATH)
                sock.sendall(command.encode("utf-8"))
        except OSError as error:
            self._log(f"listener control ({command}): {error}")

    # =================================================================
    # IPC
    # =================================================================

    def _start_ipc(self):
        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)

            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(SOCKET_PATH)
            os.chmod(SOCKET_PATH, 0o600)
            self.server.listen(4)

            threading.Thread(
                target=self._accept_listener, daemon=True,
            ).start()
            self._log(f"IPC: listening on {SOCKET_PATH}")
        except Exception as error:
            self._log(f"IPC: {error}")
            self.set_state("error")

    def _accept_listener(self):
        while not self.stop_event.is_set():
            try:
                client, _ = self.server.accept()
                self.listener_client = client
                threading.Thread(
                    target=self._read_listener,
                    args=(client,),
                    daemon=True,
                ).start()

            except OSError:
                break

    def _read_listener(self, client):
        buffer = b""
        try:
            while not self.stop_event.is_set():
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk

                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError) as error:
                        self.event_queue.put({
                            "type": "log",
                            "message": f"IPC parse error: {error}",
                        })
                        continue

                    if not isinstance(event, dict) or not isinstance(
                        event.get("type"), str
                    ):
                        self.event_queue.put({
                            "type": "log",
                            "message": f"IPC invalid event: {event!r}",
                        })
                        continue

                    self.event_queue.put(event)
        except OSError:
            pass

        finally:
            try:
                client.close()
                
            except OSError:
                pass

    # =================================================================
    # event handling
    # =================================================================

    def _poll_events(self):
        if self.stop_event.is_set():
            return

        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self.after(40, self._poll_events)

    def _handle_event(self, event):
        if not isinstance(event, dict):
            self._log(f"IPC invalid event: {event!r}")
            return

        kind = event.get("type")

        if kind == "state":
            state = event.get("state", "idle")
            self.set_state(state)
            if state == "error":
                self._set_listener_paused(False)

        elif kind == "wake":
            self._log("WAKE WORD: NAVI")

        elif kind == "command":
            command = event.get("text", "").strip()
            if command:
                self._log(f"> {command}")
                self._set_listener_paused(True)
                self._send_executor({
                    "type": "command",
                    "text": command,
                })

        elif kind == "response":
            self._set_listener_paused(False)
            self._log(event.get("message", "executor: done"))
            self.set_state(event.get("state", "idle"))

        elif kind == "log":
            message = event.get("message", "")
            if message:
                self._log(message)

        elif kind == "listener":
            state = event.get("state", "unknown")
            self._log(f"listener: {state}")

        elif kind == "worker":
            state = event.get("state", "unknown")
            self._log(f"whisper worker: {state}")

    # =================================================================
    # Log and shutdown
    # =================================================================

    def _log(self, message):
        if not hasattr(self, "log") or not self.winfo_exists():
            return

        timestamp = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _tell_launcher_to_shutdown(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(CONTROL_SOCKET_PATH)
                sock.sendall(
                    (json.dumps({"type": "shutdown"}) + "\n").encode("utf-8")
                )
        except OSError:
            pass

    def close(self):
        if self.stop_event.is_set():
            return

        self.stop_event.set()
        self._tell_launcher_to_shutdown()

        if self.executor:
            try:
                if self.executor.stdin:
                    with self.executor_lock:
                        self.executor.stdin.write(
                            json.dumps({"type": "shutdown"}) + "\n"
                        )
                        self.executor.stdin.flush()
            except OSError:
                pass

            try:
                self.executor.terminate()
                
            except OSError:
                pass

        for conn in (self.listener_client, self.server):
            if conn:
                try:
                    conn.close()
                except OSError:
                    pass

        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
        except OSError:
            pass

        self.destroy()


if __name__ == "__main__":
    app = NaviFrontend()
    app.mainloop()
