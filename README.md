# WoW Chat Translator

Translates World of Warcraft TBC Anniversary chat with a local model, both
directions, between any pair of languages. Nothing leaves your machine.

## Why not a button inside the chat frame

WoW's Lua sandbox has no networking and no file access, so a model cannot run
inside the game. There is a channel *out*: the client writes
`Logs/WoWChatLog.txt` live. There is no channel *back in* — SavedVariables are
only read when the UI loads, so every message would need a `/reload`.

That is why translations appear in a separate window on top of the game rather
than in the game's own chat frame.

## What's in the box

- `addon/ChatLogAuto/` — a tiny addon that keeps `/chatlog` enabled (the client
  resets it on every login). Optional; you can type `/chatlog` yourself instead.
- `overlay/` — a Python app with three windows:
  - **feed** — a translucent window over the game showing incoming messages
    translated into your language;
  - **write** — type in your language, get the text in the chat language,
    copied to the clipboard automatically, paste it in game with Ctrl+V;
  - **⚙ settings** — languages, model and filters, applied live.

## Setup

### 1. Ollama

Pick whichever you already use — they all install the same thing.

| Method | Command |
|---|---|
| Installer | Download [OllamaSetup.exe](https://ollama.com/download/windows) and run it |
| winget | `winget install Ollama.Ollama` |
| Chocolatey | `choco install ollama` |
| Scoop | `scoop install ollama` |

Ollama runs as a background service and starts with Windows. Check it is up:

```bash
ollama list
```

### 2. The model

```bash
ollama pull qwen2.5:3b
```

Alternatives, if 3b is too slow or not good enough — put the name in settings
after pulling:

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:1.5b` | ~1 GB | Fastest, weaker on slang |
| `qwen2.5:3b` | ~2 GB | Default, good balance |
| `qwen2.5:7b` | ~4.7 GB | Best quality, wants a GPU |
| `gemma2:2b` | ~1.6 GB | Alternative if Qwen misbehaves |

### 3. Python

The app uses only the standard library, but it needs **tkinter**, which not
every Python build ships.

| Method | Command |
|---|---|
| Installer | [python.org/downloads/windows](https://www.python.org/downloads/windows/) — tick "tcl/tk and IDLE" and "Add python.exe to PATH" |
| winget | `winget install Python.Python.3.12` |
| Chocolatey | `choco install python` |
| Scoop | `scoop install python` |

Verify tkinter is there before going further:

```bash
python -c "import tkinter; print(tkinter.TkVersion)"
```

If that prints a version, you are set. If it raises
`ModuleNotFoundError: No module named '_tkinter'`, that build has no Tk —
install the python.org one, which always includes it. The embeddable ZIP
package never has tkinter, so don't use it.

### 4. The addon

Copy `addon/ChatLogAuto` into
`World of Warcraft\_classic_\Interface\AddOns\`.

If the character screen marks it out of date, tick "Load out of date addons".
The `.toc` says `## Interface: 20504` and Anniversary may run a newer build; to
get the exact number, type `/dump select(4, GetBuildInfo())` in game and put it
in the `.toc`.

Skipping the addon is fine — just type `/chatlog` in game after each login.

### 5. Run it

Double-click `overlay\run.bat`, or from a terminal:

```bash
python overlay\main.py
```

`run.bat` launches through `pythonw`, which keeps a console window from hanging
around. Run `main.py` directly when you want to see errors.

### 6. In game

Graphics → Display → **Windowed (Fullscreen)**. In exclusive fullscreen,
Windows will not draw any window on top of the game.

## Controls

Drag the feed by its top bar, resize it from the `◢` corner. Buttons: `pause`
stops taking new lines, `write` opens the composer, `⚙` opens settings, `clear`
empties the feed, `−`/`+` change the font size, `✕` quits. Position, size and
font size are remembered.

In the composer: `Ctrl+Enter` translates, `Esc` closes. The result is copied to
the clipboard on its own; `Copy` copies it again.

## Languages

Settings has two rows:

- **Chat language** — what people around you speak. `Auto-detect` is there for
  servers where that varies.
- **My language** — yours.

Incoming messages go Chat → My, the composer goes My → Chat. `Auto-detect`
works only as the chat language: nothing can be translated *into* it, and the
composer will ask you to pick a concrete language if you try.

Lines already written in your language never reach the model — a filter based
on common words and on the alphabet drops them first. If it guesses wrong, turn
on `Translate every line`.

## Configuration

`overlay/config.json` is created on first run; `⚙` edits the same values.

| Key | What it does |
|---|---|
| `chat_language` | Chat language as a code like `nl`, or `auto` |
| `my_language` | Your language |
| `chat_log_path` | Path to `WoWChatLog.txt`. Blank means auto-detect |
| `model` | Ollama model |
| `workers` | How many translations run in parallel |
| `translate_everything` | `true` translates every line, skipping the language filter |
| `channels` | Channel whitelist, e.g. `["Party", "Guild", "Whisper"]`. Empty means all |
| `ignore_senders` | Players whose messages are skipped |
| `opacity` | Feed opacity, `0.0`–`1.0` |

Loot channels, system messages and skill-up lines are always dropped.

Settings apply immediately, without a restart. The one exception is *lowering*
`workers`: the surplus threads stay until you quit.

## Known limits

- Translations show up in the overlay, not in the game's chat frame. That is an
  API limit, not a bug.
- Latency is the model's response time, usually 0.3–1 s on a GPU.
- Repeated phrases come back from cache instantly.
- Lines already in the log are not read retroactively — only what arrives after
  the app starts.
- Outgoing text is pasted into the game by hand with Ctrl+V. The addon cannot
  type in chat for you; automating chat output gets accounts banned.
