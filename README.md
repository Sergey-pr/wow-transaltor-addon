# WoW Chat Translator

Translates World of Warcraft TBC Anniversary chat with a local model, both
directions, between any pair of languages. Nothing leaves your machine.

Words you meet in chat can be turned into flashcards that come back on a
spaced-repetition schedule, so the game doubles as vocabulary practice.

## Why not a button inside the chat frame

WoW's Lua sandbox has no networking and no file access, so a model cannot run
inside the game. There is no channel *back in* either — SavedVariables are only
read when the UI loads, so every message would need a `/reload`.

That is why translations appear in a separate window on top of the game rather
than in the game's own chat frame.

## How chat gets out

Two ways, and the difference is minutes.

**The pixel bridge** is the live one. `ChatPixelBridge` paints each incoming
message into a strip of coloured cells in the top-left corner, six bits per
cell, and the overlay reads those pixels straight back off the screen. Chat
appears as you receive it. Only the public addon API is used and nothing is
read out of the game's memory.

**The chat log** is the fallback. `Logs/WoWChatLog.txt` is written live in
principle, but the client buffers it in blocks of tens of kilobytes: measured
on a populated realm, one flush of 49 KB in seven minutes, with lines sitting
unwritten for over five. That is why this path has a `refresh` button and the
pixel bridge exists at all.

The overlay uses whichever is available, and says which in the status bar.

## What's in the box

- `addon/ChatPixelBridge/` — the live channel. Paints chat as pixels.
- `addon/ChatLogAuto/` — keeps `/chatlog` enabled for the fallback path (the
  client resets it on every login). Optional; type `/chatlog` yourself instead.
- `overlay/` — a Python app with four windows:
  - **feed** — a translucent window over the game showing chat. Click a line to
    translate it;
  - **write** — type in your language, get the text in the chat language,
    copied to the clipboard automatically, paste it in game with Ctrl+V;
  - **card** — one flashcard at a time, popping up when it falls due;
  - **⚙ settings** — languages, model, filters and card timings, applied live.

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
ollama pull aya-expanse:8b
```

Model choice matters more than anything else here. Measured on Dutch guild
chat, an i7-6700 with 16 GB RAM and a 2 GB GPU (so the CPU does the work):

| Model | Size | Median | Notes |
|---|---|---|---|
| `qwen2.5:3b` | ~2 GB | 1.9 s | Fast, but mangles ordinary lines |
| `aya-expanse:8b` | ~5 GB | 5.3 s | Default. Cohere's translation model |
| `qwen2.5:7b` | ~4.7 GB | — | Middle ground, not measured here |

The size difference is not subtle. On the same sentences:

| Dutch | `qwen2.5:3b` | `aya-expanse:8b` |
|---|---|---|
| `smegmaatje gaat ook mee` | `smegmaatje is ook meegegaan` | `smegmaatje is also coming along` |
| `Bob gaat ook mee` | `Bob wants to as well` | `Bob is also coming along` |
| `gaat ook mee` | `sounds good` | `goes along` |
| `puggers zoeken en bt in` | `puggers wts en bt in` | `puggers seeking and BT in` |

A 3B model is simply too small for Dutch: it often replies in the source
language or invents a meaning. No amount of prompt wording fixes that.

**Loading takes a while.** An 8B model needs about 25 seconds to come off disk
on a machine without the VRAM to hold it. The overlay pays that cost at
startup — the status bar shows `loading …` and then `ready` — and asks Ollama
to keep the weights in memory for 30 minutes between translations. If you would
rather it let go sooner, lower `KEEP_ALIVE` in `overlay/translate.py`; the
trade is a 25-second pause the next time you click a line.

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

### 4. The addons

Copy both folders into your client's `Interface\AddOns\`. The flavour folder
depends on the client — Anniversary is `_anniversary_`:

```
World of Warcraft\_anniversary_\Interface\AddOns\ChatPixelBridge\
World of Warcraft\_anniversary_\Interface\AddOns\ChatLogAuto\
```

If the character screen marks them out of date, tick "Load out of date addons".
The `.toc` says `## Interface: 20504`; to get the exact number for your build,
type `/dump select(4, GetBuildInfo())` in game and put it in the `.toc`.

`ChatPixelBridge` draws a 132×36 strip in the very top-left corner. **Nothing
may cover it** — not the overlay window, not a UI addon, or the live feed
stops. Five seconds after the last message the body hides and only a 27×3
header stays — the overlay finds the strip by it, so it never goes away.
`/cpb off` hides it, `/cpb test` pushes a line through to check the link.

Pick what it sends with `/cpb`:

| Command | What it does |
|---|---|
| `/cpb channels` | List every channel with a tick beside the ones being sent |
| `/cpb only Guild Whisper` | Send exactly these and nothing else |
| `/cpb add Trade` | Start sending one more |
| `/cpb drop Trade` | Stop sending one |
| `/cpb all` | Send everything again |

Names are case-insensitive; quote one that contains a space, as in
`/cpb add "Whisper to"`. Filtering here rather than in the overlay is worth
doing: the strip carries about ten messages a second, and a busy Trade on its
own can saturate that. The overlay's own `channels` setting still applies on
top, so you can narrow further without touching the game.

`ChatLogAuto` is only needed for the fallback path.

### 5. Run it

Double-click **`overlay\run.vbs`**. From a terminal:

```bash
python overlay\main.py
```

`run.vbs` opens no console window at all. `run.bat` also works, but a `.bat`
always flashes a console for a moment — Windows creates it before the script
gets a say. Run `main.py` directly when you want to see errors.

### 6. In game

Graphics → Display → **Windowed (Fullscreen)**. In exclusive fullscreen,
Windows will not draw any window on top of the game.

## Using it

### The feed

At startup the whole log is parsed and the newest messages that pass your
filters are shown, so the feed opens with history rather than empty. From then
on the pixel bridge appends new chat as it arrives.

Nothing is translated on its own. **Click a line and its translation appears
underneath it.** That keeps the model idle unless you actually want something,
which matters when each request costs a few seconds.

**`refresh`** is for the fallback path: it pulls whatever the client has
finally written to the log. With the pixel bridge connected you should not
need it.

Drag the feed by its top bar, resize it from the `◢` corner.

| Button | What it does |
|---|---|
| `refresh` | Pull new chat from the log (fallback path only) |
| `cards` | Open the deck editor |
| `+card` | Make a card from the selected text |
| `write` | Open the composer |
| `⚙` | Settings |
| `clear` | Empty the feed |
| `▁` | Shrink to a small badge; click the badge to bring it back |
| `✕` | Quit |

Position, size and font size are remembered.

### The composer

`Ctrl+Enter` translates, `Esc` closes. The result is copied to the clipboard on
its own; `Copy` copies it again.

### Flashcards

**Right-click any word in a chat line** to make a card from it. No selecting
needed. For a phrase, select it and press `+card`.

The card stores the word, the sentence it came from, and a translation of each.
Cards are looked up with a dictionary prompt rather than the chat one, which
matters: asked as chat, a bare word tends to come back transliterated.

A card pops up on its own when it falls due, one at a time. `Flip` (or Space)
reveals both translations and four grades, keys `1`–`4`:

- **Again** — back to 1 minute
- **Hard** — half the wait
- **Good** — double the wait: 10 min → 20 → 40 …
- **Easy** — four times the wait

All clamped between the floor and ceiling in settings. Closing the card or
pressing Esc counts as Again.

The window never takes focus — it would drop you out of the game — so click it
before using the keys.

`cards` opens the deck: fix a translation the model got wrong, reset a card's
timer, or delete it. The deck lives in `overlay/cards.json`.

**New** there writes a card by hand, for a word that never came past in chat.
Fill in what you know and press Save; any translation left blank is filled in
by the model in the background, so a word on its own is enough. The sentence is
optional. A word already in the deck is refused rather than duplicated.

Cards are scheduled in wall-clock time, so closing the overlay does not reset
anything. If a pile of them came due while it was closed, they are spaced out
by `card_gap_seconds` rather than fired back to back.

## Languages

Settings has two rows:

- **Chat language** — what people around you speak. `Auto-detect` is there for
  servers where that varies.
- **My language** — yours.

Incoming messages go Chat → My, the composer goes My → Chat. `Auto-detect`
works only as the chat language: nothing can be translated *into* it, and the
composer will ask you to pick a concrete language if you try.

## Configuration

`overlay/config.json` is created on first run; `⚙` edits the same values and
applies them immediately, without a restart.

| Key | What it does |
|---|---|
| `chat_language` | Chat language as a code like `nl`, or `auto` |
| `my_language` | Your language |
| `chat_log_path` | Path to `WoWChatLog.txt`. Blank means auto-detect |
| `model` | Ollama model |
| `timeout_seconds` | Give a large model room to load — 120 by default |
| `workers` | How many translations run in parallel |
| `channels` | Channel whitelist, e.g. `["Guild", "Say", "Whisper"]`. Empty means all |
| `ignore_senders` | Players whose messages are skipped |
| `max_lines` | Messages kept in the feed |
| `opacity` | Feed opacity, `0.0`–`1.0` |
| `card_gap_seconds` | Quiet stretch enforced between two card popups |
| `card_first_seconds` | How long a new card waits before its first showing |
| `card_min_seconds` | Floor on the interval, so wrong answers cannot spam |
| `card_max_days` | Ceiling on the interval |

Channel names come from the log: `Trade`, `LookingForGroup`, `General`, `Guild`,
`Say`, `Yell`, `Whisper`, `Whisper to`, `Party`, `Raid`. Case does not matter.
Loot channels, system messages and skill-up lines are always dropped.

Editing `config.json` by hand while the overlay is running is safe — on exit it
writes back only the window layout and merges it into whatever the file says.

Lowering `workers` is the one setting that needs a restart: the surplus threads
stay until you quit.

## Known limits

- Translations show up in the overlay, not in the game's chat frame. That is an
  API limit, not a bug.
- The pixel bridge needs its strip visible on screen. Cover it and the overlay
  falls back to hunting for it every few seconds; the status bar says so.
- The bridge carries roughly ten messages a second. A burst beyond that queues
  in the addon and catches up rather than being dropped.
- Latency is the model's response time: about 5 s for `aya-expanse:8b` on a CPU,
  under 2 s for a 3B model or on a GPU that fits the weights. Repeated phrases
  come back from cache instantly.
- Outgoing text is pasted into the game by hand with Ctrl+V. The addon cannot
  type in chat for you; automating chat output gets accounts banned.
- Card translations are only as good as the model. Check new cards in the deck
  editor and fix the ones it fumbled.
