"""Finds WoWChatLog.txt, follows it, and turns raw lines into ChatMessage objects."""

import os
import re
from dataclasses import dataclass

# Where Blizzard installs WoW by default. The flavor folder differs per client:
# Anniversary TBC is usually _classic_, Era is _classic_era_.
SEARCH_ROOTS = [
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"C:\World of Warcraft",
    r"C:\Games\World of Warcraft",
    r"D:\World of Warcraft",
    r"D:\Games\World of Warcraft",
    r"D:\Program Files (x86)\World of Warcraft",
    r"E:\World of Warcraft",
    r"E:\Games\World of Warcraft",
]

FLAVORS = ["_anniversary_", "_classic_", "_classic_era_", "_classic_ptr_", "_retail_"]


def find_chat_log():
    """Returns the most recently written WoWChatLog.txt, or None."""
    found = []
    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for flavor in FLAVORS:
            path = os.path.join(root, flavor, "Logs", "WoWChatLog.txt")
            if os.path.isfile(path):
                found.append(path)
    if not found:
        return None
    return max(found, key=os.path.getmtime)


@dataclass
class ChatMessage:
    channel: str
    sender: str
    text: str
    raw: str


_TIMESTAMP = re.compile(r"^\d+/\d+ \d+:\d+:\d+\.\d+\s+")

# "[2. Trade - Orgrimmar] Naam-Realm: bericht"  /  "[Guild] Naam: bericht"
_CHANNEL = re.compile(r"^\[(?P<channel>[^\]]+)\]\s*(?P<sender>[^:]+?):\s*(?P<text>.+)$")
# "Naam says: bericht" / whispers / yells
_VERB = re.compile(r"^(?P<sender>\S+?) (?P<verb>says|yells|whispers): (?P<text>.+)$")
# outgoing whisper
_TO = re.compile(r"^To (?P<sender>[^:]+?): (?P<text>.+)$")

# Channel names we never want to translate.
NOISE = ("loot", "system", "combat", "skill", "currency", "money")

# The client writes its own markup into the log. Guild lines arrive as
# "|Hchannel:GUILD|h[Guild]|h Naam: bericht", and item links inside a message
# body look the same, so the display text is kept and the wrapper dropped.
_HYPERLINK = re.compile(r"\|H.*?\|h(.*?)\|h")
_COLOR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r")
_TEXTURE = re.compile(r"\|T.*?\|t")


def strip_markup(text):
    text = _HYPERLINK.sub(r"\1", text)
    text = _COLOR.sub("", text)
    return _TEXTURE.sub("", text)


def _clean_sender(name):
    return name.split("-")[0].strip()


def parse_line(line):
    """Parses one chat log line. Returns a ChatMessage or None for system noise."""
    raw = line.rstrip("\r\n")
    if not raw.strip():
        return None

    body = _TIMESTAMP.sub("", raw).strip()
    if "|" in body:
        body = strip_markup(body).strip()
    if not body:
        return None

    m = _CHANNEL.match(body)
    if m:
        channel = m.group("channel").strip()
        if any(n in channel.lower() for n in NOISE):
            return None
        # Strip the leading channel number: "2. Trade - Orgrimmar" -> "Trade"
        pretty = re.sub(r"^\d+\.\s*", "", channel).split(" - ")[0]
        return ChatMessage(pretty, _clean_sender(m.group("sender")), m.group("text").strip(), raw)

    m = _VERB.match(body)
    if m:
        verb = m.group("verb")
        channel = {"says": "Say", "yells": "Yell", "whispers": "Whisper"}[verb]
        return ChatMessage(channel, _clean_sender(m.group("sender")), m.group("text").strip(), raw)

    m = _TO.match(body)
    if m:
        return ChatMessage("Whisper to", _clean_sender(m.group("sender")), m.group("text").strip(), raw)

    # Anything else is a system line (level ups, loot, quest text).
    return None


class LogReader:
    """Reads the chat log in bites, remembering where it stopped.

    Survives the rotation and truncation the client does between sessions.
    """

    def __init__(self, path, from_start=False):
        self.path = path
        self.from_start = from_start
        self._handle = None
        self._inode = None

    def _open(self):
        # Binary mode on purpose: text-mode tell() returns an opaque cookie, and
        # this tailer needs real byte offsets to rewind over a partial line.
        handle = open(self.path, "rb")
        stat = os.fstat(handle.fileno())
        # Blizzard rewrites the file on a new session; remember what we opened.
        self._inode = (stat.st_ino, stat.st_dev)
        if not self.from_start:
            handle.seek(0, os.SEEK_END)
        self.from_start = False
        self._handle = handle

    def _reopened(self):
        """True when the file on disk is no longer the one we hold open."""
        try:
            stat = os.stat(self.path)
        except OSError:
            return False
        if (stat.st_ino, stat.st_dev) != self._inode:
            return True
        return stat.st_size < self._handle.tell()

    def drain(self):
        """Yields every message written since the last call, then returns.

        Never blocks: the caller decides when to look again. The read position
        is kept between calls, so the first call replays the whole log and each
        later one hands over only what is new.
        """
        # Twice at most: a new session truncates the log, and the replacement
        # has to be picked up in this same call rather than the next one.
        for _ in range(2):
            if self._handle is None:
                if not os.path.isfile(self.path):
                    return
                try:
                    self._open()
                except OSError:
                    return

            while True:
                line = self._handle.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    # A half-written line: rewind and leave it for next time.
                    self._handle.seek(-len(line), os.SEEK_CUR)
                    return
                message = parse_line(line.decode("utf-8", errors="replace"))
                if message:
                    yield message

            if not self._reopened():
                return
            self.close()
            self.from_start = True

    def close(self):
        if self._handle:
            self._handle.close()
            self._handle = None
