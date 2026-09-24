"""Spaced-repetition deck: word cards cut out of the chat feed.

Scheduled the way Anki does it (the SM-2 family):

- A new card goes through short learning steps (1 min, then 10 min). Again
  sends it back to the first step, Hard repeats the step, Good moves on, and
  passing the last step graduates it to a one-day interval. Easy graduates it
  straight away, at four days.
- A graduated card carries an ease, 250% to start. Good multiplies the
  interval by it, Hard by 1.2 and knocks 15% off the ease, Easy multiplies by
  ease x 1.3 and adds 15%. Answering late counts in the card's favour, as in
  Anki: the time it actually survived goes into the next interval.
- Again on a graduated card is a lapse: the ease drops 20%, the card relearns
  through a 10 minute step, and then restarts at one day.

The floor and ceiling from the settings bound every wait, so a run of misses
cannot turn into a spam loop and a long streak cannot park a card for years.
"""

import json
import os
import threading
import time

MINUTE, DAY = 60, 24 * 60 * 60

FIRST_INTERVAL = 10 * MINUTE
MIN_INTERVAL = MINUTE
MAX_INTERVAL = 30 * DAY

LEARN_STEPS = (1 * MINUTE, 10 * MINUTE)
RELEARN_STEPS = (10 * MINUTE,)
GRADUATING_INTERVAL = 1 * DAY
EASY_INTERVAL = 4 * DAY
LAPSE_INTERVAL = 1 * DAY

START_EASE = 2.5
MIN_EASE = 1.3
HARD_FACTOR = 1.2
EASY_BONUS = 1.3

GRADES = ("again", "hard", "good", "easy")


def _clamp(seconds, minimum, maximum):
    # A minimum above the maximum would make the clamp order decide the answer,
    # so the floor wins and the result stays predictable.
    return int(max(minimum, min(max(maximum, minimum), seconds)))


def _hard_step(steps, step):
    """Hard while learning: halfway to the next step on the first, else a repeat."""
    if step == 0 and len(steps) > 1:
        return (steps[0] + steps[1]) / 2
    if len(steps) == 1:
        return min(steps[0] * 1.5, steps[0] + DAY)
    return steps[step]


class Card:
    __slots__ = ("word", "sentence", "word_translation", "sentence_translation",
                 "source", "target", "interval", "due", "right", "wrong",
                 "phase", "step", "ease", "review_interval", "lapses")

    def __init__(self, word, sentence, word_translation="", sentence_translation="",
                 source="", target="", interval=FIRST_INTERVAL, due=None,
                 right=0, wrong=0, phase=None, step=0, ease=START_EASE,
                 review_interval=0, lapses=0):
        self.word = word
        self.sentence = sentence
        self.word_translation = word_translation
        self.sentence_translation = sentence_translation
        self.source = source
        self.target = target
        # The wait last scheduled: the gap between the previous showing and
        # `due`. Not the same as review_interval, the graduated interval the
        # ease multiplies, which a lapse's short relearning steps leave alone.
        self.interval = interval
        self.due = time.time() + interval if due is None else due
        self.right = right
        self.wrong = wrong
        if phase is None:
            # A card saved before there were phases: a long wait means it was
            # already learned, anything shorter goes through the steps.
            if interval >= GRADUATING_INTERVAL:
                phase, review_interval = "review", interval
            else:
                phase = "learn"
        self.phase = phase          # "learn", "review" or "relearn"
        self.step = step
        self.ease = ease
        self.review_interval = review_interval
        self.lapses = lapses

    def as_dict(self):
        return {name: getattr(self, name) for name in self.__slots__}

    def schedule(self, grade, now=None, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL):
        """What answering `grade` would do, as the fields it would change.

        Leaves the card alone, so the popup can print each button's wait
        before one is picked.
        """
        now = time.time() if now is None else now
        phase, step, ease = self.phase, self.step, self.ease
        review, lapses = self.review_interval, self.lapses

        if phase in ("learn", "relearn"):
            steps = LEARN_STEPS if phase == "learn" else RELEARN_STEPS
            step = min(step, len(steps) - 1)
            if grade == "again":
                step, wait = 0, steps[0]
            elif grade == "hard":
                wait = _hard_step(steps, step)
            elif grade == "good" and step + 1 < len(steps):
                step, wait = step + 1, steps[step + 1]
            else:
                # Good past the last step, or Easy: out of learning. A relearned
                # card goes back to the interval its lapse left it with.
                if phase == "learn":
                    wait = EASY_INTERVAL if grade == "easy" else GRADUATING_INTERVAL
                else:
                    wait = review + (DAY if grade == "easy" else 0)
                phase, step, review = "review", 0, wait
        elif grade == "again":
            ease = max(MIN_EASE, ease - 0.2)
            lapses += 1
            phase, step, review = "relearn", 0, LAPSE_INTERVAL
            wait = RELEARN_STEPS[0]
        else:
            # Time the card survived past its due date, which Anki credits.
            late = max(0, now - self.due)
            hard = max(review, (review + late / 4) * HARD_FACTOR)
            good = max((review + late / 2) * ease, hard + DAY)
            if grade == "hard":
                ease, wait = max(MIN_EASE, ease - 0.15), hard
            elif grade == "good":
                wait = good
            else:
                wait = max((review + late) * ease * EASY_BONUS, good + DAY)
                ease += 0.15
            review = wait

        wait = _clamp(wait, minimum, maximum)
        if phase == "review":
            review = _clamp(review, minimum, maximum)
        return {"phase": phase, "step": step, "ease": round(ease, 2),
                "review_interval": review, "lapses": lapses,
                "interval": wait, "due": now + wait}

    def preview(self, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL):
        """grade -> seconds until the card would be back."""
        now = time.time()
        return {g: self.schedule(g, now, minimum, maximum)["interval"] for g in GRADES}

    def answer(self, grade, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL):
        # Only Again counts as a miss; Hard is still a recall, just a slow one.
        if grade == "again":
            self.wrong += 1
        else:
            self.right += 1
        for name, value in self.schedule(grade, None, minimum, maximum).items():
            setattr(self, name, value)

    def restart(self, first):
        """Back to a brand-new card: learning steps and the starting ease."""
        self.phase, self.step, self.ease = "learn", 0, START_EASE
        self.review_interval, self.lapses = 0, 0
        self.interval = first
        self.due = time.time() + first


class Deck:
    """The saved cards. Safe to touch from the UI and worker threads."""

    def __init__(self, path, first=FIRST_INTERVAL, minimum=MIN_INTERVAL,
                 maximum=MAX_INTERVAL):
        self.path = path
        self.set_bounds(first, minimum, maximum)
        self._cards = []
        self._claimed = set()   # words whose card is still being built
        # card -> when it was closed unanswered. Queues it by that moment
        # instead of its due date, which is left alone so the overdue credit
        # a review card earns is still there once it is answered.
        self._skipped = {}
        self._lock = threading.Lock()
        self.load()

    def set_bounds(self, first, minimum, maximum):
        self.minimum, self.maximum = minimum, maximum
        self.first = self.clamp(first)

    def clamp(self, seconds):
        return _clamp(seconds, self.minimum, self.maximum)

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
            self._skipped.clear()

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
            return (min(ready, key=lambda c: self._skipped.get(c, c.due))
                    if ready else None)

    def skip(self, card, now=None):
        """Sends a card to the back of the queue without answering it."""
        with self._lock:
            self._skipped[card] = time.time() if now is None else now

    def preview(self, card):
        """grade -> seconds, for labelling the answer buttons."""
        return card.preview(self.minimum, self.maximum)

    def answer(self, card, grade):
        with self._lock:
            self._skipped.pop(card, None)
        card.answer(grade, self.minimum, self.maximum)
        self.save()

    def forget(self, card):
        with self._lock:
            if card in self._cards:
                self._cards.remove(card)
            self._skipped.pop(card, None)
        self.save()

    def all_cards(self):
        """A snapshot, soonest due first, safe to iterate while the deck changes."""
        with self._lock:
            return sorted(self._cards, key=lambda c: c.due)

    def reschedule(self, card):
        """Starts a card over as new, on the starting interval."""
        with self._lock:
            self._skipped.pop(card, None)
        card.restart(self.first)
        self.save()

    def __len__(self):
        with self._lock:
            return len(self._cards)
