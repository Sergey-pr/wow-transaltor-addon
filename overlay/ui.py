"""Overlay feed, outgoing-message composer, flashcard popup and settings."""

import time
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

    _TRIM_SLACK = 200   # messages to overshoot by before a trim pass runs

    def __init__(self, geometry="520x320+40+40", opacity=0.88, font_size=10,
                 max_lines=200, on_close=None, on_compose=None, on_settings=None,
                 on_translate=None, on_card=None, on_refresh=None, on_cards=None):
        self.max_lines = max_lines
        self.on_close = on_close
        self.on_compose = on_compose
        self.on_settings = on_settings
        self.on_translate = on_translate
        self.on_card = on_card
        self.on_refresh = on_refresh
        self.on_cards = on_cards
        self.font_size = font_size
        self.opacity = opacity
        self._message_count = 0
        self._marks = []            # marks of the messages on screen, oldest first
        self._requested = set()
        self._click_tags = {}
        # Outlives _click_tags, which is emptied once a message is translated;
        # a word can still be turned into a card long after that.
        self._mark_by_tag = {}
        self._badge = None
        self._stowed_geometry = None

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
        _header_button(header, "▁", self.minimize)
        _header_button(header, "+", self._bigger)
        _header_button(header, "−", self._smaller)
        _header_button(header, "clear", self.clear)
        _header_button(header, "⚙", lambda: self.on_settings and self.on_settings())
        _header_button(header, "write", lambda: self.on_compose and self.on_compose())
        _header_button(header, "+card", self._card_from_selection)
        _header_button(header, "cards", lambda: self.on_cards and self.on_cards())

        self.refresh_button = _header_button(header, "refresh", self._refresh)

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
        self.text.bind("<Button-3>", self._card_from_pointer)
        self._apply_tags()

    def _card_from_pointer(self, event):
        """Right-click makes a card straight from the word under the cursor."""
        if not self.on_card:
            return
        found = self.word_at(event.x, event.y)
        if found:
            self.on_card(*found)
        else:
            self.set_status("cards come from the original line, not the translation")
        return "break"

    def _card_from_selection(self):
        if not self.on_card:
            return
        found = self.selected_word()
        if found:
            self.on_card(*found)
        else:
            self.set_status("select a word in a chat line first")

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

    # ------------------------------------------------------------- minimise

    BADGE_SIZE = 34

    def minimize(self):
        """Stows the feed behind a small badge that brings it back."""
        if self._badge is not None:
            return
        self._stowed_geometry = self.geometry()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.withdraw()

        badge = tk.Toplevel(self.root)
        badge.overrideredirect(True)
        badge.attributes("-topmost", True)
        badge.attributes("-alpha", max(0.8, self.opacity))
        badge.configure(bg=BG_HEADER, highlightthickness=1,
                        highlightbackground=FG_SENDER)
        badge.geometry("%dx%d+%d+%d" % (self.BADGE_SIZE, self.BADGE_SIZE, x, y))

        label = tk.Label(badge, text="⇄", bg=BG_HEADER, fg=FG_SENDER,
                         font=("Segoe UI", 14, "bold"), cursor="hand2")
        label.pack(fill="both", expand=True)

        # A press may start a drag, so the restore waits for the release and
        # only fires when the badge did not actually move.
        moved = [False]

        def press(event):
            moved[0] = False
            self._drag_offset = (event.x_root - badge.winfo_x(),
                                 event.y_root - badge.winfo_y())

        def drag(event):
            moved[0] = True
            dx, dy = self._drag_offset
            badge.geometry("+%d+%d" % (event.x_root - dx, event.y_root - dy))

        def release(_event):
            if not moved[0]:
                self.restore()

        for widget in (badge, label):
            widget.bind("<Button-1>", press)
            widget.bind("<B1-Motion>", drag)
            widget.bind("<ButtonRelease-1>", release)

        self._badge = badge

    def restore(self):
        if self._badge is None:
            return
        # The badge may have been dragged; reopen the feed where it now sits.
        x, y = self._badge.winfo_x(), self._badge.winfo_y()
        self._badge.destroy()
        self._badge = None

        size = self._stowed_geometry.split("+")[0] if self._stowed_geometry else None
        self.root.deiconify()
        self.root.geometry("%s+%d+%d" % (size, x, y) if size else "+%d+%d" % (x, y))
        self.root.lift()
        self.text.see("end")

    @property
    def minimized(self):
        return self._badge is not None

    def _refresh(self):
        if not self.on_refresh:
            return
        self.refresh_button.config(text="…")
        self.set_status("reading the log…")
        self.on_refresh()

    def refresh_done(self):
        self.refresh_button.config(text="refresh")

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
        for mark in self._marks:
            self.text.mark_unset(mark)
        self._marks.clear()
        self._click_tags.clear()
        self._mark_by_tag.clear()
        self._requested.clear()

    def add_message(self, channel, sender, original):
        """Appends a message. Its translation line stays hidden until clicked."""
        self._message_count += 1
        mark = "msg%d" % self._message_count
        click_tag = "click%d" % self._message_count
        hide_tag = "hide%d" % self._message_count

        self.text.configure(state="normal")
        if self.text.index("end-1c") != "1.0":
            self.text.insert("end", "\n")
        self.text.insert("end", "[%s] " % channel, "channel")
        self.text.insert("end", "%s: " % sender, "sender")
        self.text.insert("end", original + "\n", ("original", click_tag))
        self.text.mark_set(mark, "end-1c")
        self.text.mark_gravity(mark, "left")
        self.text.insert("end", "…\n", ("pending", hide_tag))
        self.text.configure(state="disabled")

        # Elide keeps the translation row out of the layout until it is wanted,
        # so the mark that set_translation needs already exists at the right spot.
        self.text.tag_configure(hide_tag, elide=True)
        # On release, not press: pressing is also the start of a drag, and
        # dragging out a word to make a card must not fire a translation.
        self.text.tag_bind(click_tag, "<ButtonRelease-1>",
                           lambda _e, m=mark, h=hide_tag: self._request(m, h))
        self.text.tag_bind(click_tag, "<Enter>",
                           lambda _e: self.text.configure(cursor="hand2"))
        self.text.tag_bind(click_tag, "<Leave>",
                           lambda _e: self.text.configure(cursor="arrow"))
        self._click_tags[mark] = click_tag
        self._mark_by_tag[click_tag] = mark
        self._marks.append(mark)

        self._trim()
        return mark

    def word_at(self, x, y):
        """The word under a pointer position, with the message it sits in."""
        return self._resolve("@%d,%d wordstart" % (x, y), "@%d,%d wordend" % (x, y))

    def selected_word(self):
        """The current mouse selection, with the message it sits in."""
        try:
            self.text.index("sel.first")
        except tk.TclError:
            return None
        return self._resolve("sel.first", "sel.last")

    def _resolve(self, start, end):
        try:
            word = self.text.get(start, end).strip()
            tags = self.text.tag_names(start)
        except tk.TclError:
            return None
        if not word:
            return None
        for tag in tags:
            # Only the original text carries a click tag, so a word picked out
            # of a translation row or a channel label is correctly ignored.
            if tag in self._mark_by_tag:
                return word, self._mark_by_tag[tag]
        return None

    def scroll_to_end(self):
        """Scrolling is deferred out of add_message: see() has to resolve every
        elided range, so calling it per line makes a bulk load quadratic."""
        self.text.see("end")

    def _request(self, mark, hide_tag):
        if mark in self._requested or not self.on_translate:
            return
        if self.text.tag_ranges("sel"):
            return   # the release ended a selection, not a plain click
        self._requested.add(mark)
        # Revealing the row grows the feed by a line, which would otherwise
        # push a reader sitting at the bottom off the end of it.
        at_bottom = self.text.dlineinfo("end-1c") is not None
        self.text.tag_configure(hide_tag, elide=False)
        if at_bottom:
            self.text.see("end")
        self.on_translate(mark)

    def set_translation(self, mark, translation, failed=False):
        """Replaces the placeholder after the model answers."""
        if mark is None:
            return
        try:
            start = self.text.index(mark)
        except tk.TclError:
            return  # the line was trimmed away while we waited

        # A translation lands wherever its message is, which is often well above
        # the last line. Jumping to the bottom would yank the feed out from
        # under whoever is reading it, so only a view already parked at the
        # bottom follows along. dlineinfo answers "is the last line on screen"
        # directly; the yview fraction never quite reaches 1.0 while elided
        # rows are counted in the total.
        at_bottom = self.text.dlineinfo("end-1c") is not None

        self.text.configure(state="normal")
        self.text.delete(start, "%s lineend" % start)
        self.text.insert(start, translation, "pending" if failed else "translation")
        self.text.configure(state="disabled")

        click_tag = self._click_tags.pop(mark, None)
        if click_tag:
            for event in ("<ButtonRelease-1>", "<Enter>", "<Leave>"):
                self.text.tag_unbind(click_tag, event)
            self.text.configure(cursor="arrow")
        if at_bottom:
            self.text.see("end")

    def _trim(self):
        """Drops whole messages once the feed outgrows max_lines.

        Trimming runs in batches: the channel-tag scan that finds message
        boundaries walks the whole widget, so doing it per line would undo the
        point of keeping a large buffer.
        """
        if len(self._marks) <= self.max_lines + self._TRIM_SLACK:
            return

        # Two indices per message; every message opens with a channel label.
        bounds = self.text.tag_ranges("channel")
        drop = len(self._marks) - self.max_lines
        if drop * 2 >= len(bounds):
            return

        self.text.configure(state="normal")
        self.text.delete("1.0", bounds[drop * 2])
        self.text.configure(state="disabled")

        # Deleting the text leaves the marks behind collapsed onto the cut, so
        # they have to be released by name.
        for mark in self._marks[:drop]:
            tag = self._click_tags.pop(mark, None) or "click%s" % mark[3:]
            self._mark_by_tag.pop(tag, None)
            self._requested.discard(mark)
            self.text.mark_unset(mark)
        del self._marks[:drop]

    def geometry(self):
        if self._badge is not None:
            # Withdrawn windows report a stale position, so quitting from the
            # badge must save the size it had, moved to where the badge sits.
            size = self._stowed_geometry.split("+")[0]
            return "%s+%d+%d" % (size, self._badge.winfo_x(), self._badge.winfo_y())
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


class CardPopup:
    """One flashcard at a time: word and sentence, then their translations."""

    def __init__(self, parent, on_answer):
        self.parent = parent
        self.on_answer = on_answer
        self.window = None
        self.card = None

    @property
    def busy(self):
        return self.window is not None and self.window.winfo_exists()

    def show(self, card):
        if self.busy:
            return False
        self.card = card
        self._build()
        return True

    def _build(self):
        window = tk.Toplevel(self.parent)
        window.title("Card")
        window.configure(bg=BG)
        window.attributes("-topmost", True)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", lambda: self._answer(False))
        self.window = window

        body = tk.Frame(window, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=self.card.word, bg=BG, fg=FG_TRANSLATION,
                 font=("Segoe UI", 18, "bold"), wraplength=380,
                 justify="left", anchor="w").pack(fill="x")

        tk.Label(body, text=self.card.sentence, bg=BG, fg=FG_ORIGINAL,
                 font=("Segoe UI", 10, "italic"), wraplength=380,
                 justify="left", anchor="w").pack(fill="x", pady=(8, 0))

        self.back = tk.Frame(body, bg=BG)

        tk.Frame(self.back, bg="#2a3040", height=1).pack(fill="x", pady=(14, 10))
        tk.Label(self.back, text=self.card.word_translation or "(no translation)",
                 bg=BG, fg=FG_OK, font=("Segoe UI", 15, "bold"), wraplength=380,
                 justify="left", anchor="w").pack(fill="x")
        tk.Label(self.back, text=self.card.sentence_translation or "",
                 bg=BG, fg=FG_TRANSLATION, font=("Segoe UI", 10), wraplength=380,
                 justify="left", anchor="w").pack(fill="x", pady=(6, 0))

        self.buttons = tk.Frame(body, bg=BG)
        self.buttons.pack(fill="x", pady=(16, 0))

        self.flip_button = self._button(self.buttons, "Flip  (Space)", self.flip,
                                        FG_TRANSLATION)
        self.flip_button.pack(fill="x")

        window.bind("<space>", lambda _e: self.flip())
        window.bind("<Escape>", lambda _e: self._answer(False))
        self._place(window)
        # Deliberately no focus_force here: this pops up over a running game,
        # and pulling focus would drop the player out of it. Clicking the card
        # gives it focus, after which the key bindings work.
        window.lift()

    @staticmethod
    def _button(parent, text, command, colour):
        return tk.Button(parent, text=text, command=command, bg=BG_HEADER,
                         fg=colour, activebackground="#2a3040",
                         activeforeground=colour, bd=0, padx=14, pady=6,
                         font=("Segoe UI", 10, "bold"), cursor="hand2")

    def _place(self, window):
        """Centres the card so it cannot open off-screen."""
        window.update_idletasks()
        width, height = window.winfo_width(), window.winfo_height()
        x = (window.winfo_screenwidth() - width) // 2
        y = (window.winfo_screenheight() - height) // 3
        window.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def flip(self):
        if not self.busy or self.back.winfo_ismapped():
            return
        self.back.pack(fill="x", before=self.buttons)
        self.flip_button.pack_forget()

        wrong = self._button(self.buttons, "Wrong", lambda: self._answer(False), FG_ERROR)
        wrong.pack(side="left", expand=True, fill="x", padx=(0, 4))
        right = self._button(self.buttons, "Right", lambda: self._answer(True), FG_OK)
        right.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.window.bind("<Left>", lambda _e: self._answer(False))
        self.window.bind("<Right>", lambda _e: self._answer(True))
        self._place(self.window)

    def _answer(self, correct):
        card = self.card
        self.card = None
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        if card is not None and self.on_answer:
            self.on_answer(card, correct)


class CardEditor:
    """Browse the deck: fix a bad translation, reset a timer, drop a card."""

    FIELDS = [
        ("word", "Word"),
        ("word_translation", "Means"),
        ("sentence", "Sentence"),
        ("sentence_translation", "Meaning"),
    ]

    def __init__(self, parent, deck):
        self.parent = parent
        self.deck = deck
        self.window = None
        self.rows = {}          # tree row id -> Card

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            self.reload()
            return
        self._build()

    def _build(self):
        window = tk.Toplevel(self.parent)
        window.title("Cards")
        window.geometry("640x480")
        window.configure(bg=BG)
        window.attributes("-topmost", True)
        window.minsize(520, 400)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self.window = window

        style = ttk.Style(window)
        style.theme_use("clam")
        style.configure("Cards.Treeview", background=BG_INPUT, fieldbackground=BG_INPUT,
                        foreground=FG_TRANSLATION, borderwidth=0, rowheight=22)
        style.configure("Cards.Treeview.Heading", background=BG_HEADER,
                        foreground=FG_STATUS, borderwidth=0)
        style.map("Cards.Treeview", background=[("selected", "#2a3040")])

        columns = ("word", "means", "due", "score")
        self.tree = ttk.Treeview(window, columns=columns, show="headings",
                                 style="Cards.Treeview", selectmode="browse")
        for name, title, width in (("word", "Word", 150), ("means", "Means", 190),
                                   ("due", "Due in", 90), ("score", "Right/Wrong", 90)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._load_selected())

        form = tk.Frame(window, bg=BG, padx=10)
        form.pack(fill="x")
        self.vars = {}
        for row, (key, title) in enumerate(self.FIELDS):
            tk.Label(form, text=title, bg=BG, fg=FG_STATUS, font=("Segoe UI", 9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
            self.vars[key] = tk.StringVar()
            tk.Entry(form, textvariable=self.vars[key], bg=BG_INPUT,
                     fg=FG_TRANSLATION, insertbackground=FG_TRANSLATION, bd=0,
                     highlightthickness=1, highlightbackground="#2a3040",
                     highlightcolor=FG_SENDER).grid(row=row, column=1, sticky="ew",
                                                    pady=2, ipady=3)
        form.columnconfigure(1, weight=1)

        buttons = tk.Frame(window, bg=BG, padx=10, pady=10)
        buttons.pack(fill="x")

        self.status = tk.Label(buttons, text="", bg=BG, fg=FG_STATUS,
                               font=("Segoe UI", 8), anchor="w")
        self.status.pack(side="left")

        for text, command, colour in (("Close", window.destroy, FG_STATUS),
                                      ("Delete", self._delete, FG_ERROR),
                                      ("Reset timer", self._reset, FG_STATUS),
                                      ("Save", self._save, FG_OK)):
            tk.Button(buttons, text=text, command=command, bg=BG_HEADER, fg=colour,
                      activebackground="#2a3040", activeforeground=colour, bd=0,
                      padx=12, pady=4, font=("Segoe UI", 9), cursor="hand2"
                      ).pack(side="right", padx=(6, 0))

        self.reload()

    @staticmethod
    def _due_text(card):
        left = card.due - time.time()
        if left <= 0:
            return "now"
        if left < 3600:
            return "%d min" % (left // 60)
        if left < 86400:
            return "%.1f h" % (left / 3600)
        return "%.1f d" % (left / 86400)

    def reload(self):
        selected = self.rows.get(self._selection())
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for card in self.deck.all_cards():
            row = self.tree.insert("", "end", values=(
                card.word, card.word_translation, self._due_text(card),
                "%d / %d" % (card.right, card.wrong)))
            self.rows[row] = card
            if card is selected:
                self.tree.selection_set(row)
        self.status.config(text="%d card(s)" % len(self.rows), fg=FG_STATUS)
        self._load_selected()

    def _selection(self):
        picked = self.tree.selection()
        return picked[0] if picked else None

    def _current(self):
        return self.rows.get(self._selection())

    def _load_selected(self):
        card = self._current()
        for key, _title in self.FIELDS:
            self.vars[key].set(getattr(card, key) if card else "")

    def _save(self):
        card = self._current()
        if not card:
            return self._warn("pick a card first")
        word = self.vars["word"].get().strip()
        if not word:
            return self._warn("the word cannot be empty")
        card.word = word
        for key, _title in self.FIELDS[1:]:
            setattr(card, key, self.vars[key].get().strip())
        self.deck.save()
        self.reload()
        self.status.config(text="saved '%s'" % card.word, fg=FG_OK)

    def _reset(self):
        card = self._current()
        if not card:
            return self._warn("pick a card first")
        self.deck.reschedule(card)
        self.reload()
        self.status.config(text="'%s' starts over" % card.word, fg=FG_OK)

    def _delete(self):
        card = self._current()
        if not card:
            return self._warn("pick a card first")
        self.deck.forget(card)
        self.reload()
        self.status.config(text="deleted '%s'" % card.word, fg=FG_STATUS)

    def _warn(self, message):
        self.status.config(text=message, fg=FG_ERROR)


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
        ("card_gap_seconds", "Min gap between cards (seconds)"),
        ("card_first_seconds", "Card first interval (seconds)"),
        ("card_min_seconds", "Card interval floor (seconds)"),
        ("card_max_days", "Card interval ceiling (days)"),
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

        tk.Label(body, text="Click any message in the feed to translate it.",
                 bg=BG, fg=FG_CHANNEL, font=("Segoe UI", 8), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
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

        updated["opacity"] = round(float(self.vars["opacity"].get()), 2)

        self.on_save(updated)
        self.window.destroy()
