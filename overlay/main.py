"""Entry point: reads WoW chat, translates locally on demand, shows an overlay.

Chat arrives one of two ways. The pixel bridge is live: the companion addon
paints each message into a strip of coloured cells and this reads it straight
off the screen. Failing that, the client's own chat log still works, but the
client buffers it in blocks, so lines can lag by minutes and have to be pulled
in with the refresh button.
"""

import itertools
import json
import os
import queue
import sys
import threading
import time

import cards
import chatlog
import pixelbridge
import screengrab
import translate
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
CARDS_PATH = os.path.join(HERE, "cards.json")

CARD_POLL_MS = 15000
BRIDGE_POLL = 0.03          # ~30 Hz; the addon holds each message for 0.10 s
BRIDGE_RESCAN = 3.0         # seconds between full-screen hunts for the strip

DEFAULTS = {
    "chat_language": "nl",
    "my_language": "en",
    "chat_log_path": "",
    "ollama_host": "http://127.0.0.1:11434",
    "model": "aya-expanse:8b",
    # Generous on purpose: loading an 8B model off disk can take half a minute
    # on a machine without the VRAM to hold it.
    "timeout_seconds": 120,
    "workers": 2,
    "channels": [],
    "ignore_senders": [],
    # Clear of the top-left corner: that is where the addon paints its strip,
    # and covering it cuts the live feed.
    "geometry": "520x320+200+60",
    "compose_geometry": "480x300",
    "opacity": 0.88,
    "font_size": 10,
    "max_lines": 200,
    # Quiet stretch between two cards. Their own doubling schedule usually
    # spaces them out anyway; this only bites when a backlog piled up while
    # the overlay was closed, so a night away is not a burst of popups.
    "card_gap_seconds": 180,
    "card_first_seconds": 600,
    "card_min_seconds": 60,
    "card_max_days": 30,
}


def log_age(path):
    """Seconds since the client last committed anything to the log.

    The client buffers chat and writes it out in blocks, so a refresh can
    legitimately find nothing new. Showing the age separates "the game has
    not written yet" from "the overlay is stuck".
    """
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except OSError:
        return None


def human_age(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "%ds" % int(seconds)
    return "%dm" % int(seconds // 60)


def card_bounds(config):
    return (int(config["card_first_seconds"]),
            int(config["card_min_seconds"]),
            int(config["card_max_days"]) * 86400)


def load_config():
    config = dict(DEFAULTS)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                config.update(json.load(handle))
        except (OSError, ValueError) as exc:
            print("Could not read config.json (%s), using defaults." % exc)
    else:
        save_config(config)
    return config


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
    except OSError as exc:
        print("Could not write config.json: %s" % exc)


# What the window owns and nothing else does. Everything else in the file
# belongs to the settings dialog, which writes it the moment it changes.
LAYOUT_KEYS = ("geometry", "compose_geometry", "chat_log_path")


def save_layout(config):
    """Writes back the window layout without touching the rest of the file.

    Quitting used to dump the whole in-memory config, which silently undid any
    edit made to config.json while the overlay happened to be running.
    """
    on_disk = dict(DEFAULTS)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                on_disk.update(json.load(handle))
        except (OSError, ValueError):
            pass            # unreadable: fall back to what we hold
    on_disk.update({key: config[key] for key in LAYOUT_KEYS})
    save_config(on_disk)


def main():
    config = load_config()

    stop_event = threading.Event()
    events = queue.Queue()      # -> UI thread
    work = queue.Queue()        # incoming chat lines -> translation workers
    ids = itertools.count(1)
    pending = {}                # work id -> text mark in the Text widget
    originals = {}              # text mark -> the untranslated line

    bridge_state = [("looking for the pixel bridge…", False)]
    model_state = [("loading model…", False)]

    def show_state():
        text = "%s · %s" % (bridge_state[0][0], model_state[0][0])
        window.set_status(text, error=bridge_state[0][1] or model_state[0][1])

    reader = [None]             # the open LogReader, replaced when the path changes
    primed = [False]            # has the first, whole-log pass happened yet
    refreshing = [False]        # guards against overlapping refreshes
    worker_count = [0]

    def on_close():
        # Read geometry while the widgets still exist, so the layout survives.
        config["geometry"] = window.geometry()
        config["compose_geometry"] = composer.geometry()
        stop_event.set()
        if reader[0]:
            reader[0].close()

    def on_translate(mark):
        text = originals.get(mark)
        if not text:
            return
        work_id = next(ids)
        pending[work_id] = mark
        work.put((work_id, text, config["chat_language"], config["my_language"]))

    def on_card(word, mark):
        """Turns a picked word into a card, translating it off the UI thread."""
        sentence = originals.get(mark)
        if not sentence:
            return
        source, target = config["chat_language"], config["my_language"]
        if target == "auto" or source == target:
            events.put(("status", "set a chat and my language first", True))
            return
        if deck.has_word(word, source):
            events.put(("status", "'%s' is already in the deck" % word, False))
            return

        events.put(("status", "making a card for '%s'…" % word, False))

        def build():
            card = deck.new_card(
                word=word,
                sentence=sentence,
                word_translation=translator.translate_word(word, sentence, source, target) or "",
                sentence_translation=translator.translate(sentence, source, target) or "",
                source=source,
                target=target,
            )
            deck.add(card)
            events.put(("status", "card %d: '%s' — due in %d min"
                        % (len(deck), word, card.interval // 60), False))

        threading.Thread(target=build, daemon=True).start()

    window = ui.Overlay(
        geometry=config["geometry"],
        opacity=config["opacity"],
        font_size=config["font_size"],
        max_lines=config["max_lines"],
        on_close=on_close,
        on_compose=lambda: composer.show(),
        on_settings=lambda: settings.show(),
        on_translate=on_translate,
        on_card=on_card,
        on_refresh=lambda: refresh(),
        on_cards=lambda: editor.show(),
    )

    deck = cards.Deck(CARDS_PATH, *card_bounds(config))

    translator = translate.Translator(
        host=config["ollama_host"],
        model=config["model"],
        timeout=config["timeout_seconds"],
    )

    # ------------------------------------------------------------- producers

    def keep(message):
        """Filters are read fresh so settings apply without a restart."""
        if message.channel == "Bridge test":
            return True     # /cpb test must show up whatever is filtered
        channels = [c.lower() for c in config["channels"]]
        if channels and message.channel.lower() not in channels:
            return False
        return message.sender.lower() not in {s.lower()
                                              for s in config["ignore_senders"]}

    def refresh():
        """Reads whatever the client has written since the last look."""
        if reader[0] is None or refreshing[0]:
            return
        refreshing[0] = True
        log, first = reader[0], not primed[0]
        primed[0] = True

        def run():
            try:
                # The first pass replays the whole log, so only the newest
                # survivors are worth painting; later passes are just the tail.
                fresh = [m for m in log.drain() if keep(m)]
                if first:
                    fresh = fresh[-int(config["max_lines"]):]
                for message in fresh:
                    events.put(("new", None, message))
                events.put(("refreshed", len(fresh), log_age(log.path)))
            finally:
                refreshing[0] = False

        threading.Thread(target=run, daemon=True).start()

    def bridge_loop():
        """Live chat, straight off the screen. Survives the strip coming and
        going: hiding the addon or covering the strip just drops back to
        hunting for it again."""
        bridge = pixelbridge.Bridge()
        connected = False
        missing_reported = False
        last_scan = 0.0
        try:
            while not stop_event.is_set():
                if bridge.origin is None:
                    if connected:
                        connected = False
                        events.put(("bridge", False, None))
                    if time.monotonic() - last_scan < BRIDGE_RESCAN:
                        time.sleep(0.2)
                        continue
                    last_scan = time.monotonic()
                    if bridge.locate():
                        connected = True
                        missing_reported = False
                        events.put(("bridge", True, bridge.origin))
                    elif not missing_reported:
                        missing_reported = True
                        events.put(("bridge", None, None))
                    continue

                found = bridge.read()
                if found is None:
                    time.sleep(BRIDGE_POLL)
                    continue

                channel, sender, text = found
                message = chatlog.ChatMessage(channel, sender, text, "")
                if keep(message):
                    events.put(("new", None, message))
        finally:
            bridge.close()

    def worker():
        while not stop_event.is_set():
            try:
                message_id, text, source, target = work.get(timeout=0.5)
            except queue.Empty:
                continue
            events.put(("done", message_id, translator.translate(text, source, target)))

    def compose_request(text):
        """Outgoing direction: my language -> chat language."""
        source, target = config["my_language"], config["chat_language"]
        if target == "auto":
            events.put(("compose", None, "Set a specific chat language in settings "
                                         "— 'Auto-detect' cannot be a target."))
            return

        def run():
            events.put(("compose", translator.translate(text, source, target), None))

        threading.Thread(target=run, daemon=True).start()

    def check_ollama():
        ok, detail = translator.available()
        if not ok:
            events.put(("status", detail, True))
            return
        # Pay the weight-loading wait here rather than on the first click.
        events.put(("status", "loading %s…" % config["model"], False))
        warmed = translator.warm() is not None
        events.put(("model", warmed, None))

    def start_workers(count):
        while worker_count[0] < count:
            threading.Thread(target=worker, daemon=True).start()
            worker_count[0] += 1

    def start_reader():
        path = config["chat_log_path"] or chatlog.find_chat_log()
        if not path:
            window.set_status("chat log not found", error=True)
            window.add_message("setup", "translator",
                               "WoWChatLog.txt not found. Type /chatlog in game once, "
                               "then set the chat log path in settings.")
            return
        config["chat_log_path"] = path
        if reader[0]:
            reader[0].close()
        reader[0] = chatlog.LogReader(path, from_start=True)
        primed[0] = False
        refresh()
        window.set_status("connecting to Ollama…")
        threading.Thread(target=check_ollama, daemon=True).start()

    # -------------------------------------------------------------- settings

    def apply_settings(updated):
        path_changed = updated["chat_log_path"] != config["chat_log_path"]

        config.update(updated)
        save_config(config)

        translator.configure(host=config["ollama_host"], model=config["model"],
                             timeout=config["timeout_seconds"])
        window.set_opacity(config["opacity"])
        window.set_font_size(int(config["font_size"]))
        popup.font_size = int(config["font_size"])  # takes effect on the next card
        window.max_lines = config["max_lines"]
        window.set_direction(config["chat_language"], config["my_language"])
        composer.set_direction(config["my_language"], config["chat_language"])
        settings.config = config
        deck.set_bounds(*card_bounds(config))
        start_workers(int(config["workers"]))

        if path_changed:
            window.clear()
            start_reader()
        else:
            window.set_status("settings saved — checking Ollama…")
            threading.Thread(target=check_ollama, daemon=True).start()

    composer = ui.Composer(window.root, compose_request,
                           geometry=config["compose_geometry"])
    settings = ui.Settings(window.root, config, apply_settings,
                           models_provider=translator.installed_models)

    # ----------------------------------------------------------- flashcards

    # Counts from launch, so starting the overlay does not fire a card instantly.
    quiet_until = [time.monotonic() + int(config["card_gap_seconds"])]

    def on_answer(card, grade):
        deck.answer(card, grade)
        quiet_until[0] = time.monotonic() + int(config["card_gap_seconds"])
        window.set_status("%s — '%s' returns in %s"
                          % (grade, card.word, ui.CardEditor._due_text(card)))

    popup = ui.CardPopup(window.root, on_answer, font_size=int(config["font_size"]))
    def fill_card(card):
        """Fills in whatever a hand-typed card was left missing."""
        def run():
            source, target = card.source, card.target
            if not card.word_translation:
                card.word_translation = translator.translate_word(
                    card.word, card.sentence or card.word, source, target) or ""
            if card.sentence and not card.sentence_translation:
                card.sentence_translation = translator.translate(
                    card.sentence, source, target) or ""
            deck.save()
            window.root.after(0, editor.reload)

        if card.source and card.target and card.source != card.target:
            threading.Thread(target=run, daemon=True).start()

    editor = ui.CardEditor(
        window.root, deck, on_translate=fill_card,
        direction=lambda: (config["chat_language"], config["my_language"]))

    def review():
        # One card at a time, and never before the quiet stretch since the
        # last one has run out.
        if not popup.busy and time.monotonic() >= quiet_until[0]:
            due = deck.due_card()
            if due is not None and popup.show(due):
                quiet_until[0] = time.monotonic() + int(config["card_gap_seconds"])
        if not stop_event.is_set():
            window.root.after(CARD_POLL_MS, review)

    # -------------------------------------------------------------- UI pump

    def pump():
        added = False
        try:
            while True:
                kind, first, second = events.get_nowait()

                if kind == "new":
                    mark = window.add_message(
                        second.channel, second.sender, second.text)
                    if mark:
                        added = True
                        originals[mark] = second.text
                        # Marks for trimmed-away lines are unreachable; drop the
                        # oldest so a long session does not accumulate them.
                        while len(originals) > config["max_lines"]:
                            originals.pop(next(iter(originals)))

                elif kind == "done":
                    # The source line is deliberately kept: a card can still be
                    # cut out of a message long after it has been translated.
                    mark = pending.pop(first, None)
                    if second is None:
                        window.set_translation(mark, "(translation failed)", failed=True)
                    else:
                        window.set_translation(mark, second)

                elif kind == "compose":
                    if second is not None:
                        composer.set_result(second, failed=True)
                    elif first is None:
                        composer.set_result("(translation failed)", failed=True)
                    else:
                        composer.set_result(first)

                elif kind == "refreshed":
                    window.refresh_done()
                    # second is how stale the log itself is. The client writes
                    # in blocks, so "nothing new" usually means it has not
                    # flushed yet rather than that the chat went quiet.
                    window.set_status(
                        "%s — game last wrote %s ago"
                        % ("%d new" % first if first else "nothing new",
                           human_age(second)),
                        error=second is not None and second > 120 and not first)

                elif kind == "bridge":
                    # The two halves of the status are reported separately so
                    # the model warming up cannot paint over the bridge state.
                    bridge_state[0] = {
                        True: ("live", False),
                        False: ("pixel bridge lost — strip covered?", True),
                        None: ("pixel bridge not found — /cpb on in game?", True),
                    }[first]
                    show_state()

                elif kind == "model":
                    model_state[0] = ("model ready", False) if first else (
                        "%s did not answer — too big for this machine?"
                        % config["model"], True)
                    show_state()

                elif kind == "status":
                    window.set_status(first, error=second)
        except queue.Empty:
            pass

        if added:
            window.scroll_to_end()

        if not stop_event.is_set():
            window.root.after(80, pump)

    # ---------------------------------------------------------------- start

    window.set_direction(config["chat_language"], config["my_language"])
    start_workers(int(config["workers"]))
    start_reader()

    screengrab.set_dpi_aware()
    threading.Thread(target=bridge_loop, daemon=True).start()

    window.root.after(80, pump)
    window.root.after(CARD_POLL_MS, review)

    if len(deck):
        window.set_status("%d card(s) in the deck" % len(deck))

    try:
        window.root.mainloop()
    finally:
        stop_event.set()
        if reader[0]:
            reader[0].close()
        save_layout(config)


if __name__ == "__main__":
    sys.exit(main())
