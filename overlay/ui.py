"""Overlay feed, outgoing-message composer and the settings dialog."""

import tkinter as tk
from tkinter import ttk

import languages

BG = "#12141a"
BG_HEADER = "#1b1f2a"
BG_INPUT = "#1e222c"
FG_CHANNEL = "#6f7a8f"
FG_SENDER = "#7fb2ff"
FG_ORIGINAL = "#7d8798"
FG_TRANSLATION = "#e8ecf3"
FG_STATUS = "#9aa4b5"
FG_ERROR = "#ff7a7a"
FG_OK = "#8ee08e"


def _header_button(parent, text, command, side="right"):
    button = tk.Label(parent, text=text, bg=BG_HEADER, fg=FG_STATUS,
                      font=("Segoe UI", 9), padx=6, cursor="hand2")
    button.pack(side=side)
    button.bind("<Button-1>", lambda _event: command())
    button.bind("<Enter>", lambda event: event.widget.config(fg=FG_TRANSLATION))
    button.bind("<Leave>", lambda event: event.widget.config(fg=FG_STATUS))
    return button


class Overlay:
    """Borderless always-on-top window showing the translated incoming feed."""

    def __init__(self, geometry="520x320+40+40", opacity=0.88, font_size=10,
                 max_lines=200, on_close=None, on_compose=None, on_settings=None):
        self.max_lines = max_lines
        self.on_close = on_close
        self.on_compose = on_compose
        self.on_settings = on_settings
        self.paused = False
        self.font_size = font_size
        self.opacity = opacity
        self._message_count = 0

        self.root = tk.Tk()
        self.root.title("WoW Chat Translator")
        self.root.geometry(geometry)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", opacity)
        self.root.configure(bg=BG)
        self.root.minsize(300, 140)

        self._build_header()
        self._build_body()
        self._build_grip()

    # ---------------------------------------------------------------- layout

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG_HEADER, height=26)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        self.title = tk.Label(header, text="→", bg=BG_HEADER, fg=FG_SENDER,
                              font=("Segoe UI", 9, "bold"), padx=8)
        self.title.pack(side="left")

        self.status = tk.Label(header, text="starting…", bg=BG_HEADER, fg=FG_STATUS,
                               font=("Segoe UI", 8))
        self.status.pack(side="left", padx=4)

        _header_button(header, "✕", self._close)
        _header_button(header, "+", self._bigger)
        _header_button(header, "−", self._smaller)
        _header_button(header, "clear", self.clear)
        _header_button(header, "⚙", lambda: self.on_settings and self.on_settings())
        _header_button(header, "write", lambda: self.on_compose and self.on_compose())

        self.pause_button = _header_button(header, "pause", self._toggle_pause)

        # Dragging the header moves the whole borderless window.
        for widget in (header, self.title, self.status):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

    def _build_body(self):
        self.text = tk.Text(self.root, bg=BG, fg=FG_TRANSLATION, bd=0,
                            highlightthickness=0, wrap="word", padx=10, pady=6,
                            font=("Segoe UI", self.font_size), cursor="arrow")
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")
        self._apply_tags()

    def _build_grip(self):
        grip = tk.Label(self.root, text="◢", bg=BG, fg=FG_CHANNEL, cursor="sizing")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<Button-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)

    def _apply_tags(self):
        size = self.font_size
        self.text.tag_configure("channel", foreground=FG_CHANNEL, font=("Segoe UI", size - 1))
        self.text.tag_configure("sender", foreground=FG_SENDER, font=("Segoe UI", size, "bold"))
        self.text.tag_configure("original", foreground=FG_ORIGINAL, font=("Segoe UI", size - 1, "italic"))
        self.text.tag_configure("translation", foreground=FG_TRANSLATION, font=("Segoe UI", size))
        self.text.tag_configure("pending", foreground=FG_CHANNEL, font=("Segoe UI", size, "italic"))

    # ---------------------------------------------------------- interactions

    def _drag_start(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        dx, dy = self._drag_offset
        self.root.geometry("+%d+%d" % (event.x_root - dx, event.y_root - dy))

    def _resize_start(self, event):
        self._resize_origin = (event.x_root, event.y_root,
                               self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, event):
        x0, y0, width, height = self._resize_origin
        self.root.geometry("%dx%d" % (max(300, width + event.x_root - x0),
                                      max(140, height + event.y_root - y0)))

    def _toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.config(text="resume" if self.paused else "pause")
        self.set_status("paused" if self.paused else "listening")

    def _bigger(self):
        self.set_font_size(min(20, self.font_size + 1))

    def _smaller(self):
        self.set_font_size(max(7, self.font_size - 1))

    def set_font_size(self, size):
        self.font_size = size
        self.text.configure(font=("Segoe UI", size))
        self._apply_tags()

    def set_opacity(self, value):
        self.opacity = value
        self.root.attributes("-alpha", value)

    def _close(self):
        if self.on_close:
            self.on_close()
        self.root.destroy()

    # ----------------------------------------------------------------- feed

    def set_direction(self, source_code, target_code):
        self.title.config(text="%s → %s" % (languages.name_for(source_code),
                                            languages.name_for(target_code)))

    def set_status(self, text, error=False):
        self.status.config(text=text, fg=FG_ERROR if error else FG_STATUS)

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def add_message(self, channel, sender, original):
        """Appends a message with a placeholder translation. Returns its mark id."""
        if self.paused:
            return None

        self._message_count += 1
        mark = "msg%d" % self._message_count

        self.text.configure(state="normal")
        if self.text.index("end-1c") != "1.0":
            self.text.insert("end", "\n")
        self.text.insert("end", "[%s] " % channel, "channel")
        self.text.insert("end", "%s: " % sender, "sender")
        self.text.insert("end", original + "\n", "original")
        self.text.mark_set(mark, "end-1c")
        self.text.mark_gravity(mark, "left")
        self.text.insert("end", "…\n", "pending")
        self.text.configure(state="disabled")

        self._trim()
        self.text.see("end")
        return mark

    def set_translation(self, mark, translation, failed=False):
        """Replaces the placeholder after the model answers."""
        if mark is None:
            return
        try:
            start = self.text.index(mark)
        except tk.TclError:
            return  # the line was trimmed away while we waited

        self.text.configure(state="normal")
        self.text.delete(start, "%s lineend" % start)
        self.text.insert(start, translation, "pending" if failed else "translation")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _trim(self):
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > self.max_lines:
            self.text.configure(state="normal")
            self.text.delete("1.0", "%d.0" % (lines - self.max_lines))
            self.text.configure(state="disabled")

    def geometry(self):
        return "%dx%d+%d+%d" % (self.root.winfo_width(), self.root.winfo_height(),
                                self.root.winfo_x(), self.root.winfo_y())


class Composer:
    """Type in your own language, get chat-ready text to paste into WoW."""

    def __init__(self, parent, on_request, geometry="480x300"):
        self.on_request = on_request
        self._geometry = geometry
        self._direction = ("", "")
        self.window = None
        self.parent = parent

    def geometry(self):
        if self.window is not None and self.window.winfo_exists():
            return "%dx%d" % (self.window.winfo_width(), self.window.winfo_height())
        return self._geometry

    def _build(self):
        window = tk.Toplevel(self.parent)
        window.title("Write a message")
        window.geometry(self._geometry)
        window.configure(bg=BG)
        window.attributes("-topmost", True)
        window.minsize(360, 240)
        window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window = window

        self.direction = tk.Label(window, bg=BG, fg=FG_SENDER,
                                  font=("Segoe UI", 9, "bold"), anchor="w", padx=10)
        self.direction.pack(fill="x", pady=(8, 4))
        self._paint_direction()

        self.input = tk.Text(window, height=4, bg=BG_INPUT, fg=FG_TRANSLATION,
                             insertbackground=FG_TRANSLATION, bd=0,
                             highlightthickness=1, highlightbackground="#2a3040",
                             highlightcolor=FG_SENDER, wrap="word", padx=8, pady=6,
                             font=("Segoe UI", 10))
        self.input.pack(fill="both", expand=True, padx=10)
        self.input.bind("<Control-Return>", lambda _event: self.translate())
        self.input.bind("<Escape>", lambda _event: self.hide())

        buttons = tk.Frame(window, bg=BG)
        buttons.pack(fill="x", padx=10, pady=6)

        self.translate_button = tk.Button(
            buttons, text="Translate  (Ctrl+Enter)", command=self.translate,
            bg=BG_HEADER, fg=FG_TRANSLATION, activebackground="#2a3040",
            activeforeground=FG_TRANSLATION, bd=0, padx=10, pady=4,
            font=("Segoe UI", 9), cursor="hand2")
        self.translate_button.pack(side="left")

        self.copy_button = tk.Button(
            buttons, text="Copy", command=self.copy, bg=BG_HEADER,
            fg=FG_TRANSLATION, activebackground="#2a3040",
            activeforeground=FG_TRANSLATION, bd=0, padx=10, pady=4,
            font=("Segoe UI", 9), cursor="hand2", state="disabled")
        self.copy_button.pack(side="left", padx=6)

        self.status = tk.Label(buttons, text="", bg=BG, fg=FG_STATUS,
                               font=("Segoe UI", 8))
        self.status.pack(side="left", padx=6)

        self.output = tk.Text(window, height=4, bg=BG, fg=FG_TRANSLATION, bd=0,
                              highlightthickness=1, highlightbackground="#2a3040",
                              wrap="word", padx=8, pady=6, font=("Segoe UI", 10))
        self.output.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.output.configure(state="disabled")

    def show(self):
        if self.window is None or not self.window.winfo_exists():
            self._build()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.input.focus_set()

    def hide(self):
        if self.window is not None and self.window.winfo_exists():
            self._geometry = self.geometry()
            self.window.withdraw()

    def set_direction(self, source_code, target_code):
        self._direction = (source_code, target_code)
        if self.window is not None and self.window.winfo_exists():
            self._paint_direction()

    def _paint_direction(self):
        source, target = self._direction
        self.direction.config(text="%s → %s" % (languages.name_for(source),
                                                languages.name_for(target)))

    def translate(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return "break"
        self.status.config(text="translating…", fg=FG_STATUS)
        self.copy_button.config(state="disabled")
        self.on_request(text)
        return "break"  # keep Ctrl+Enter from inserting a newline

    def set_result(self, translation, failed=False):
        if self.window is None or not self.window.winfo_exists():
            return
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", translation)
        self.output.configure(state="disabled")

        if failed:
            self.status.config(text="failed", fg=FG_ERROR)
        else:
            self.status.config(text="ready to paste", fg=FG_OK)
            self.copy_button.config(state="normal")
            self.copy()

    def copy(self):
        text = self.output.get("1.0", "end").strip()
        if not text:
            return
        self.parent.clipboard_clear()
        self.parent.clipboard_append(text)
        self.status.config(text="copied — paste in chat with Ctrl+V", fg=FG_OK)


class Settings:
    """Dialog over config.json. Hands a plain dict back to the caller on save."""

    FIELDS_TEXT = [
        ("ollama_host", "Ollama host"),
        ("model", "Model"),
        ("chat_log_path", "Chat log path (blank = auto)"),
        ("channels", "Channels (comma separated, blank = all)"),
        ("ignore_senders", "Ignore senders (comma separated)"),
    ]

    FIELDS_NUMBER = [
        ("workers", "Parallel translations"),
        ("timeout_seconds", "Timeout (seconds)"),
        ("max_lines", "Max lines kept"),
    ]

    def __init__(self, parent, config, on_save, models_provider=None):
        self.parent = parent
        self.config = config
        self.on_save = on_save
        self.models_provider = models_provider
        self.window = None

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            return
        self._build()

    def _build(self):
        window = tk.Toplevel(self.parent)
        window.title("Translator settings")
        window.configure(bg=BG)
        window.attributes("-topmost", True)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self.window = window

        body = tk.Frame(window, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)

        self.vars = {}
        row = 0

        def label(text, r):
            tk.Label(body, text=text, bg=BG, fg=FG_STATUS, font=("Segoe UI", 9),
                     anchor="w").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))

        # --- languages
        tk.Label(body, text="Languages", bg=BG, fg=FG_SENDER,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        row += 1

        label("Chat language (translate from)", row)
        self.vars["chat_language"] = tk.StringVar(
            value=languages.name_for(self.config.get("chat_language", "nl")))
        ttk.Combobox(body, textvariable=self.vars["chat_language"],
                     values=languages.choices(include_auto=True), state="readonly",
                     width=28).grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        label("My language (translate to)", row)
        self.vars["my_language"] = tk.StringVar(
            value=languages.name_for(self.config.get("my_language", "en")))
        ttk.Combobox(body, textvariable=self.vars["my_language"],
                     values=languages.choices(include_auto=False), state="readonly",
                     width=28).grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        tk.Label(body, text="Outgoing messages go the other way: My → Chat.",
                 bg=BG, fg=FG_CHANNEL, font=("Segoe UI", 8), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        row += 1

        # --- model and filtering
        tk.Label(body, text="Model and filtering", bg=BG, fg=FG_SENDER,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w", pady=(4, 6))
        row += 1

        installed = self.models_provider() if self.models_provider else []

        for key, title in self.FIELDS_TEXT:
            label(title, row)
            value = self.config.get(key, "")
            if isinstance(value, list):
                value = ", ".join(value)
            self.vars[key] = tk.StringVar(value=value)
            if key == "model" and installed:
                ttk.Combobox(body, textvariable=self.vars[key], values=installed,
                             width=28).grid(row=row, column=1, sticky="ew", pady=4)
            else:
                tk.Entry(body, textvariable=self.vars[key], bg=BG_INPUT,
                         fg=FG_TRANSLATION, insertbackground=FG_TRANSLATION,
                         bd=0, highlightthickness=1, highlightbackground="#2a3040",
                         width=30).grid(row=row, column=1, sticky="ew", pady=4, ipady=3)
            row += 1

        for key, title in self.FIELDS_NUMBER:
            label(title, row)
            self.vars[key] = tk.StringVar(value=str(self.config.get(key, "")))
            tk.Entry(body, textvariable=self.vars[key], bg=BG_INPUT,
                     fg=FG_TRANSLATION, insertbackground=FG_TRANSLATION, bd=0,
                     highlightthickness=1, highlightbackground="#2a3040",
                     width=30).grid(row=row, column=1, sticky="ew", pady=4, ipady=3)
            row += 1

        self.vars["translate_everything"] = tk.BooleanVar(
            value=bool(self.config.get("translate_everything", False)))
        tk.Checkbutton(body, text="Translate every line (skip the language filter)",
                       variable=self.vars["translate_everything"], bg=BG,
                       fg=FG_STATUS, selectcolor=BG_INPUT, activebackground=BG,
                       activeforeground=FG_TRANSLATION, bd=0,
                       highlightthickness=0, font=("Segoe UI", 9),
                       anchor="w").grid(row=row, column=0, columnspan=2,
                                        sticky="w", pady=(6, 2))
        row += 1

        # --- appearance
        label("Opacity", row)
        self.vars["opacity"] = tk.DoubleVar(value=float(self.config.get("opacity", 0.88)))
        tk.Scale(body, variable=self.vars["opacity"], from_=0.3, to=1.0,
                 resolution=0.02, orient="horizontal", bg=BG, fg=FG_STATUS,
                 troughcolor=BG_INPUT, highlightthickness=0, bd=0,
                 activebackground=FG_SENDER, length=200).grid(
                     row=row, column=1, sticky="ew", pady=4)
        row += 1

        self.error = tk.Label(body, text="", bg=BG, fg=FG_ERROR, font=("Segoe UI", 8),
                              anchor="w", wraplength=360, justify="left")
        self.error.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))

        tk.Button(buttons, text="Cancel", command=window.destroy, bg=BG_HEADER,
                  fg=FG_STATUS, activebackground="#2a3040", bd=0, padx=12,
                  pady=4, font=("Segoe UI", 9), cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(buttons, text="Save", command=self._save, bg=BG_HEADER,
                  fg=FG_TRANSLATION, activebackground="#2a3040", bd=0, padx=16,
                  pady=4, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(side="right")

        body.columnconfigure(1, weight=1)

    def _save(self):
        updated = dict(self.config)

        updated["chat_language"] = languages.code_for(self.vars["chat_language"].get())
        updated["my_language"] = languages.code_for(self.vars["my_language"].get())

        if updated["chat_language"] == updated["my_language"]:
            self.error.config(text="Chat language and my language must differ.")
            return

        for key, _title in self.FIELDS_TEXT:
            value = self.vars[key].get().strip()
            if key in ("channels", "ignore_senders"):
                updated[key] = [part.strip() for part in value.split(",") if part.strip()]
            else:
                updated[key] = value

        for key, title in self.FIELDS_NUMBER:
            raw = self.vars[key].get().strip()
            try:
                number = int(float(raw))
            except ValueError:
                self.error.config(text="%s must be a number." % title)
                return
            if number < 1:
                self.error.config(text="%s must be at least 1." % title)
                return
            updated[key] = number

        updated["translate_everything"] = bool(self.vars["translate_everything"].get())
        updated["opacity"] = round(float(self.vars["opacity"].get()), 2)

        self.on_save(updated)
        self.window.destroy()
