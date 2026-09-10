"""Entry point: tails the WoW chat log, translates locally, shows an overlay."""

import itertools
import json
import os
import queue
import sys
import threading

import chatlog
import translate
import ui

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "chat_language": "nl",
    "my_language": "en",
    "chat_log_path": "",
    "ollama_host": "http://127.0.0.1:11434",
    "model": "qwen2.5:3b",
    "timeout_seconds": 30,
    "workers": 2,
    "translate_everything": False,
    "channels": [],
    "ignore_senders": [],
    "geometry": "520x320+40+40",
    "compose_geometry": "480x300",
    "opacity": 0.88,
    "font_size": 10,
    "max_lines": 200,
}


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


def main():
    config = load_config()

    stop_event = threading.Event()
    events = queue.Queue()      # -> UI thread
    work = queue.Queue()        # incoming chat lines -> translation workers
    ids = itertools.count(1)
    pending = {}                # id -> text mark in the Text widget

    reader_stop = threading.Event()   # replaced whenever the log path changes
    worker_count = [0]

    def on_close():
        # Read geometry while the widgets still exist, so the layout survives.
        config["geometry"] = window.geometry()
        config["font_size"] = window.font_size
        config["compose_geometry"] = composer.geometry()
        stop_event.set()
        reader_stop.set()

    window = ui.Overlay(
        geometry=config["geometry"],
        opacity=config["opacity"],
        font_size=config["font_size"],
        max_lines=config["max_lines"],
        on_close=on_close,
        on_compose=lambda: composer.show(),
        on_settings=lambda: settings.show(),
    )

    translator = translate.Translator(
        host=config["ollama_host"],
        model=config["model"],
        timeout=config["timeout_seconds"],
    )

    # ------------------------------------------------------------- producers

    def reader(path, local_stop):
        tailer = chatlog.LogTailer(path)
        for message in tailer.follow(local_stop):
            if stop_event.is_set():
                break
            if window.paused:
                continue

            # Filters are read fresh each line so settings apply without a restart.
            channels = [c.lower() for c in config["channels"]]
            if channels and message.channel.lower() not in channels:
                continue
            if message.sender.lower() in {s.lower() for s in config["ignore_senders"]}:
                continue

            source, target = config["chat_language"], config["my_language"]
            if not config["translate_everything"] and \
                    not translate.should_translate(message.text, source, target):
                continue

            message_id = next(ids)
            events.put(("new", message_id, message))
            work.put((message_id, message.text, source, target))

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
        events.put(("status", "listening" if ok else detail, not ok))

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
        threading.Thread(target=reader, args=(path, reader_stop), daemon=True).start()
        window.set_status("connecting to Ollama…")
        threading.Thread(target=check_ollama, daemon=True).start()

    # -------------------------------------------------------------- settings

    def apply_settings(updated):
        nonlocal reader_stop
        path_changed = updated["chat_log_path"] != config["chat_log_path"]

        config.update(updated)
        save_config(config)

        translator.configure(host=config["ollama_host"], model=config["model"],
                             timeout=config["timeout_seconds"])
        window.set_opacity(config["opacity"])
        window.max_lines = config["max_lines"]
        window.set_direction(config["chat_language"], config["my_language"])
        composer.set_direction(config["my_language"], config["chat_language"])
        settings.config = config
        start_workers(int(config["workers"]))

        if path_changed:
            reader_stop.set()
            reader_stop = threading.Event()
            start_reader()
        else:
            window.set_status("settings saved — checking Ollama…")
            threading.Thread(target=check_ollama, daemon=True).start()

    composer = ui.Composer(window.root, compose_request,
                           geometry=config["compose_geometry"])
    settings = ui.Settings(window.root, config, apply_settings,
                           models_provider=translator.installed_models)

    # -------------------------------------------------------------- UI pump

    def pump():
        try:
            while True:
                kind, first, second = events.get_nowait()

                if kind == "new":
                    pending[first] = window.add_message(
                        second.channel, second.sender, second.text)

                elif kind == "done":
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

                elif kind == "status":
                    window.set_status(first, error=second)
        except queue.Empty:
            pass

        if not stop_event.is_set():
            window.root.after(80, pump)

    # ---------------------------------------------------------------- start

    window.set_direction(config["chat_language"], config["my_language"])
    start_workers(int(config["workers"]))
    start_reader()

    window.root.after(80, pump)

    try:
        window.root.mainloop()
    finally:
        stop_event.set()
        reader_stop.set()
        save_config(config)


if __name__ == "__main__":
    sys.exit(main())
