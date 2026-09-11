"""Reading pixels back off the screen, through GDI and nothing else.

Pillow would be one import away, but the whole app runs on the standard
library and a screenshot is not worth breaking that for.
"""

import ctypes
from ctypes import wintypes

_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# Handles are 64-bit; without argtypes ctypes passes them as C int and the
# call fails with an overflow rather than anything that points at the cause.
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                          wintypes.DWORD]
_gdi32.BitBlt.restype = wintypes.BOOL
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                             wintypes.UINT, ctypes.c_void_p,
                             ctypes.POINTER(BITMAPINFO), wintypes.UINT]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]


def screen_size():
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def set_dpi_aware():
    """Without this, capture coordinates are silently rescaled on a scaled display."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v1
    except (AttributeError, OSError):
        try:
            _user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class Grabber:
    """Holds the GDI objects so a repeated grab does not re-allocate them."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self._screen = _user32.GetDC(0)
        self._memdc = _gdi32.CreateCompatibleDC(self._screen)
        self._bitmap = _gdi32.CreateCompatibleBitmap(self._screen, width, height)
        _gdi32.SelectObject(self._memdc, self._bitmap)

        self._info = BITMAPINFO()
        self._info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self._info.bmiHeader.biWidth = width
        # Negative height asks for a top-down image, so row 0 is the top one.
        self._info.bmiHeader.biHeight = -height
        self._info.bmiHeader.biPlanes = 1
        self._info.bmiHeader.biBitCount = 32
        self._info.bmiHeader.biCompression = BI_RGB
        self._buffer = ctypes.create_string_buffer(width * height * 4)

    def grab(self, left, top):
        """Returns the region as raw BGRA bytes, 4 per pixel, row-major."""
        _gdi32.BitBlt(self._memdc, 0, 0, self.width, self.height,
                      self._screen, left, top, SRCCOPY)
        _gdi32.GetDIBits(self._memdc, self._bitmap, 0, self.height,
                         self._buffer, ctypes.byref(self._info), DIB_RGB_COLORS)
        return self._buffer.raw

    def pixel_at(self, data, x, y):
        offset = (y * self.width + x) * 4
        blue, green, red = data[offset], data[offset + 1], data[offset + 2]
        return red, green, blue

    def close(self):
        if self._bitmap:
            _gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._memdc:
            _gdi32.DeleteDC(self._memdc)
            self._memdc = None
        if self._screen:
            _user32.ReleaseDC(0, self._screen)
            self._screen = None

    def __del__(self):
        self.close()
