"""Reads the ChatPixelBridge strip back off the screen.

The addon paints one chat message at a time into a grid of coloured cells and
holds it there long enough to be sampled. This side finds that grid, snaps each
cell's colour to the nearest encoded level and reassembles the message.

Layout and encoding are fixed on both sides; see the addon for the other half.
"""

import math

import screengrab

COLS, ROWS = 44, 12
HEADER_CELLS = 9            # 6 magic + 1 sequence + 2 length
PAYLOAD_CELLS = COLS * ROWS - HEADER_CELLS
CELL_PIXELS = 3             # what the addon aims for; the real size is measured
SEPARATOR = "\x1f"

# White, red, green, blue, dark grey, light grey. Six cells rather than three:
# a shorter marker picks up false matches on a busy desktop, and locking onto
# the wrong spot means the feed silently never arrives.
MAGIC = (63, 48, 12, 3, 21, 42)
LEVELS = (0, 85, 170, 255)
# Halfway points between the levels: anything nearer than this snaps down.
_EDGES = (42, 127, 212)
# The marker is held to the real colour, not just the nearest level, so screen
# content that merely rounds the same way cannot pass for it.
MARKER_TOLERANCE = 24


def _level(value):
    for index, edge in enumerate(_EDGES):
        if value < edge:
            return index
    return 3


def _symbol(rgb):
    return _level(rgb[0]) * 16 + _level(rgb[1]) * 4 + _level(rgb[2])


def _exact_rgb(symbol):
    return (LEVELS[symbol // 16 % 4], LEVELS[symbol // 4 % 4], LEVELS[symbol % 4])


def _close(got, symbol):
    want = _exact_rgb(symbol)
    return max(abs(a - b) for a, b in zip(got, want)) <= MARKER_TOLERANCE


def _bytes_from(symbols):
    """Six bits a symbol, back into whole bytes; a partial tail is padding."""
    out = bytearray()
    acc = bits = 0
    for symbol in symbols:
        acc = (acc << 6) | symbol
        bits += 6
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
            acc &= (1 << bits) - 1
    return bytes(out)


class Bridge:
    """Finds the strip once, then samples it. Relocates itself if it moves.

    The cell size is measured off the marker rather than assumed. The game's
    UI units are not screen pixels, so how big a cell comes out depends on the
    resolution and UI scale, and may not even be a whole number of pixels.
    """

    def __init__(self):
        self.cell = float(CELL_PIXELS)
        self.origin = None          # top-left of the grid, in screen pixels
        self._last_sequence = None
        self._grab = None
        self._screen = None

    def _fit_grabber(self):
        width = int(math.ceil(COLS * self.cell)) + 1
        height = int(math.ceil(ROWS * self.cell)) + 1
        if self._grab is None or (self._grab.width, self._grab.height) != (width, height):
            if self._grab is not None:
                self._grab.close()
            self._grab = screengrab.Grabber(width, height)

    # ------------------------------------------------------------- locating

    def locate(self):
        """Scans the whole screen for the marker. Returns True on success.

        Hunts for the red cell rather than the white one that starts the
        marker: white covers half the desktop, pure red almost nothing. The
        byte search runs in C, which keeps a full-screen hunt near 0.1 s.
        """
        width, height = screengrab.screen_size()
        if self._screen is None or (self._screen.width, self._screen.height) != (width, height):
            if self._screen is not None:
                self._screen.close()
            self._screen = screengrab.Grabber(width, height)

        data = self._screen.grab(0, 0)

        def pixel(px, py):
            offset = (py * width + px) * 4
            return data[offset + 2], data[offset + 1], data[offset]

        needle = bytes((0, 0, 255))          # BGR of pure red
        start = 0
        while True:
            found = data.find(needle, start)
            if found < 0:
                return False
            start = found + 1
            if found % 4:                    # not aligned to a pixel boundary
                continue
            index = found // 4
            x, y = index % width, index // width
            if x and _close(pixel(x - 1, y), 48):
                continue                     # not the left edge of the red run

            cell = self._measure(pixel, width, x, y)
            if cell is None:
                continue
            origin = (x - cell, y)
            if origin[0] < 0 or origin[0] + COLS * cell > width \
                    or y + ROWS * cell > height:
                continue
            if not self._verify(pixel, origin, cell):
                continue

            self.cell = cell
            self.origin = origin
            self._last_sequence = None
            self._fit_grabber()
            return True

    @staticmethod
    def _measure(pixel, width, x, y):
        """Average width of the red..light-grey marker runs, in pixels."""
        runs = []
        cursor = x
        for symbol in MAGIC[1:]:
            length = 0
            while cursor < width and _close(pixel(cursor, y), symbol):
                length += 1
                cursor += 1
            if length == 0:
                return None
            runs.append(length)
        cell = sum(runs) / len(runs)
        # Uneven runs mean colour that merely happens to line up.
        if max(runs) - min(runs) > max(2, cell * 0.5):
            return None
        return cell

    def _verify(self, pixel, origin, cell):
        """Every marker cell, sampled at its centre, in both rows it spans."""
        x0, y0 = origin
        for slot, expected in enumerate(MAGIC):
            px = int(x0 + (slot + 0.5) * cell)
            py = int(y0 + 0.5 * cell)
            if not _close(pixel(px, py), expected):
                return False
        return True

    # -------------------------------------------------------------- reading

    def read(self):
        """Returns (channel, sender, text) for a message not seen before.

        None means nothing new: no strip on screen, the same message still
        showing, or a frame caught mid-repaint.
        """
        if self.origin is None:
            return None

        left, top = int(self.origin[0]), int(self.origin[1])
        frac_x, frac_y = self.origin[0] - left, self.origin[1] - top
        data = self._grab.grab(left, top)
        cell = self.cell

        def cell_symbol(index):
            col, row = index % COLS, index // COLS
            return _symbol(self._grab.pixel_at(
                data, int(frac_x + (col + 0.5) * cell),
                int(frac_y + (row + 0.5) * cell)))

        if tuple(cell_symbol(i) for i in range(len(MAGIC))) != MAGIC:
            self.origin = None          # moved, hidden, or covered up
            return None

        sequence = cell_symbol(len(MAGIC))
        if sequence == self._last_sequence:
            return None

        length = cell_symbol(len(MAGIC) + 1) * 64 + cell_symbol(len(MAGIC) + 2)
        if not 0 < length <= PAYLOAD_CELLS:
            return None

        symbols = [cell_symbol(HEADER_CELLS + i) for i in range(length)]
        try:
            payload = _bytes_from(symbols).decode("utf-8")
        except UnicodeDecodeError:
            return None                 # sampled mid-repaint; it will repeat

        parts = payload.split(SEPARATOR)
        if len(parts) != 3 or not parts[2]:
            return None

        self._last_sequence = sequence
        return parts[0], parts[1], parts[2]

    def close(self):
        if self._grab is not None:
            self._grab.close()
            self._grab = None
        if self._screen is not None:
            self._screen.close()
            self._screen = None
