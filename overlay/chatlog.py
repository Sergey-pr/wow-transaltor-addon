"""Finds WoWChatLog.txt, follows it, and turns raw lines into ChatMessage objects."""

import os
import re
import time
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

FLAVORS = ["_classic_", "_classic_era_", "_classic_ptr_", "_retail_"]


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


def _clean_sender(name):
    return name.split("-")[0].strip()


def parse_line(line):
    """Parses one chat log line. Returns a ChatMessage or None for system noise."""
    raw = line.rstrip("\r\n")
    if not raw.strip():
        return None

    body = _TIMESTAMP.sub("", raw).strip()
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


class LogTailer:
    """Follows the chat log the way `tail -f` does, surviving rotation and truncation."""

    def __init__(self, path, from_start=False, poll=0.25):
        self.path = path
        self.poll = poll
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

    def follow(self, stop_event):
        """Yields ChatMessage objects until stop_event is set."""
        while not stop_event.is_set():
            if self._handle is None:
                if not os.path.isfile(self.path):
                    time.sleep(1.0)
                    continue
                try:
                    self._open()
                except OSError:
                    time.sleep(1.0)
                    continue

            line = self._handle.readline()
            if line:
                if not line.endswith(b"\n"):
                    # Partial write: rewind and wait for the rest of the line.
                    self._handle.seek(-len(line), os.SEEK_CUR)
                    time.sleep(self.poll)
                    continue
                message = parse_line(line.decode("utf-8", errors="replace"))
                if message:
                    yield message
                continue

            if self._reopened():
                self._handle.close()
                self._handle = None
                self.from_start = True
                continue

            time.sleep(self.poll)

        if self._handle:
            self._handle.close()
            self._handle = None
