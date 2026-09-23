"""Spaced-repetition deck: word cards cut out of the chat feed.

Four grades, Anki style: Again resets the wait to a minute, Hard halves it,
Good doubles it, Easy quadruples it. The bounds keep a long streak from parking
a card past the point of usefulness, and a run of misses from a spam loop.
"""

import json
import os
import threading
import time

FIRST_INTERVAL = 10 * 60
MIN_INTERVAL = 60
MAX_INTERVAL = 30 * 24 * 60 * 60
AGAIN_INTERVAL = 60

# grade -> multiplier on the current interval; None means start over.
GRADES = {"again": None, "hard": 0.5, "good": 2, "easy": 4}


def next_interval(interval, grade, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL):
    factor = GRADES[grade]
    step = AGAIN_INTERVAL if factor is None else interval * factor
    # A minimum above the maximum would make the clamp order decide the answer,
    # so the floor wins and the result stays predictable.
    return int(max(minimum, min(max(maximum, minimum), step)))


class Card:
    __slots__ = ("word", "sentence", "word_translation", "sentence_translation",
                 "source", "target", "interval", "due", "right", "wrong")

    def __init__(self, word, sentence, word_translation="", sentence_translation="",
                 source="", target="", interval=FIRST_INTERVAL, due=None,
                 right=0, wrong=0):
        self.word = word
        self.sentence = sentence
        self.word_translation = word_translation
        self.sentence_translation = sentence_translation
        self.source = source
        self.target = target
        self.interval = interval
        self.due = time.time() + interval if due is None else due
        self.right = right
        self.wrong = wrong

    def as_dict(self):
        return {name: getattr(self, name) for name in self.__slots__}

    def answer(self, grade, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL):
        # Only Again counts as a miss; Hard is still a recall, just a slow one.
        if grade == "again":
            self.wrong += 1
        else:
            self.right += 1
        self.interval = next_interval(self.interval, grade, minimum, maximum)
        self.due = time.time() + self.interval


class Deck:
    """The saved cards. Safe to touch from the UI and worker threads."""

    def __init__(self, path, first=FIRST_INTERVAL, minimum=MIN_INTERVAL,
                 maximum=MAX_INTERVAL):
        self.path = path
        self.set_bounds(first, minimum, maximum)
        self._cards = []
        self._claimed = set()   # words whose card is still being built
        self._lock = threading.Lock()
        self.load()

    def set_bounds(self, first, minimum, maximum):
        self.minimum, self.maximum = minimum, maximum
        self.first = self.clamp(first)

    def clamp(self, seconds):
        return int(max(self.minimum, min(max(self.maximum, self.minimum), seconds)))

    def new_card(self, **fields):
        """Builds a card on this deck's starting interval."""
        return Card(interval=self.first, **fields)

    def load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as exc:
            print("Could not read %s (%s), starting an empty deck." % (self.path, exc))
            return
        known = set(Card.__slots__)
        with self._lock:
            self._cards = [Card(**{k: v for k, v in entry.items() if k in known})
                           for entry in raw]

    def save(self):
        with self._lock:
            payload = [card.as_dict() for card in self._cards]
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except OSError as exc:
            print("Could not write %s: %s" % (self.path, exc))

    def add(self, card):
        with self._lock:
            self._cards.append(card)
        self.save()

    def has_word(self, word, source):
        with self._lock:
            return self._holds(word, source)

    def _holds(self, word, source):
        """has_word without the lock, for callers that already hold it."""
        needle = word.strip().lower()
        return any(c.word.strip().lower() == needle and c.source == source
                   for c in self._cards)

    def claim(self, word, source):
        """Reserves a word while its card is being built.

        A card cut out of the chat takes a few seconds of model time before it
        lands, and until then nothing in the deck says it is on its way -- so a
        second click on the same word used to start a second card. Returns False
        when the word is already in the deck or already being worked on; the
        caller releases it once the card lands or the attempt fails.
        """
        key = (word.strip().lower(), source)
        with self._lock:
            if key in self._claimed or self._holds(word, source):
                return False
            self._claimed.add(key)
            return True

    def release(self, word, source):
        with self._lock:
            self._claimed.discard((word.strip().lower(), source))

    def due_card(self, now=None):
        """The most overdue card, or None when nothing is waiting."""
        now = time.time() if now is None else now
        with self._lock:
            ready = [c for c in self._cards if c.due <= now]
            return min(ready, key=lambda c: c.due) if ready else None

    def answer(self, card, grade):
        card.answer(grade, self.minimum, self.maximum)
        self.save()

    def forget(self, card):
        with self._lock:
            if card in self._cards:
                self._cards.remove(card)
        self.save()

    def all_cards(self):
        """A snapshot, soonest due first, safe to iterate while the deck changes."""
        with self._lock:
            return sorted(self._cards, key=lambda c: c.due)

    def reschedule(self, card):
        """Puts a card back to the starting interval."""
        card.interval = self.first
        card.due = time.time() + card.interval
        self.save()

    def __len__(self):
        with self._lock:
            return len(self._cards)
