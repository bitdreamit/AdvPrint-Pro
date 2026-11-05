#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AdvPrint Pro - Windows system tray icon (pure stdlib, ctypes only).

Gives the hub a REAL identity on Windows:
  * a printer-badge icon in the tray area (bottom-right corner)
  * tooltip "AdvPrint Pro vX.Y - running on http://127.0.0.1:PORT"
  * right-click menu:  Open dashboard / Print test page /
    Pause queue (check) / Start at Windows logon (check) /
    Restart hub (v2.8) / Exit
  * double-click opens the status (health) page

v2.6.2 - SELF-DRAWN MENU (shell-theme proof):
  Users with third-party shell replacements / theme tools
  (ExplorerPatcher, StartAllBack, custom dark themes, ...) reported
  the tray menu showing WHITE TEXT ON A WHITE BACKGROUND - every item
  invisible, the menu looked like an empty white box. The native
  Win32 menu takes its colors from the shell theme, so we cannot
  control it. Fix: the menu is now a small topmost popup window that
  WE paint ourselves (dark navy background, white text, blue hover,
  green checkmarks) - it renders identically on every machine, every
  theme, every shell replacement. If anything in the self-drawn menu
  fails, we fall back to the classic native menu (previous behavior).

Everything here is fail-safe: ANY error simply disables the tray and the
hub keeps printing. Nothing in this module may ever crash the hub.

The hub calls:
    import tray_windows
    tray_windows.start(icon=..., tooltip=..., callbacks={...})
Callbacks (all optional):
    on_open()            -> double-click / "Open dashboard"
    on_test()            -> "Print test page"
    is_paused()->bool    -> checkmark when menu is built
    on_pause_toggle()    -> user clicked Pause/Resume; returns new paused state
    is_autostart()->bool -> checkmark when menu is built
    on_autostart_toggle()-> user clicked Start at logon; returns new state
    on_restart()         -> "Restart hub" (v2.8): relaunch + exit
    on_exit()            -> "Exit"
"""

import ctypes
import os
import threading
from ctypes import wintypes

APP = "AdvPrint Pro"

# ---- win32 constants -------------------------------------------------
WM_NULL            = 0x0000
WM_DESTROY         = 0x0002
WM_PAINT           = 0x000F
WM_CLOSE           = 0x0010
WM_QUIT            = 0x0012
WM_ACTIVATE        = 0x0006
WM_KILLFOCUS       = 0x0008
WM_KEYDOWN         = 0x0100
WM_MOUSEMOVE       = 0x0200
WM_LBUTTONDOWN     = 0x0201
WM_LBUTTONUP       = 0x0202
WM_LBUTTONDBLCLK   = 0x0203
WM_RBUTTONUP       = 0x0205
WM_USER            = 0x0400
WM_APP             = 0x8000
TRAY_MSG           = WM_APP + 20          # our callback message id
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP  = 0x01, 0x02, 0x04
IMAGE_ICON = 1
LR_LOADFROMFILE   = 0x00000010
LR_DEFAULTSIZE    = 0x00000040
IDI_APPLICATION   = 32512
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x00000000, 0x00000800, 0x00000008
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
CS_VREDRAW, CS_HREDRAW = 0x0001, 0x0002
CS_DROPSHADOW     = 0x00020000
HWND_NOTOPMOST = -2
SW_HIDE = 0
SW_SHOWNA = 8                      # show without activation
SPI_GETWORKAREA    = 0x0030
LOGPIXELSX         = 88
FW_NORMAL          = 400
DEFAULT_CHARSET    = 1
CLEARTYPE_QUALITY  = 5
DT_LEFT, DT_VCENTER, DT_SINGLELINE = 0x0000, 0x0004, 0x0020
TRANSPARENT        = 1
VK_ESCAPE          = 0x1B
DWMWA_WINDOW_CORNER_PREFERENCE = 33     # Win11 rounded corners (fail-safe)
DWMWCP_ROUND       = 2

# menu item ids (high word safety: keep < 0x8000)
M_OPEN, M_TEST, M_PAUSE, M_AUTO, M_EXIT, M_RESTART, M_FIREWALL = (
    1001, 1002, 1003, 1004, 1005, 1006, 1007)

# menu colors (COLORREF = 0x00BBGGRR)
COL_BG     = 0x301B0D              # dark navy  RGB(13, 27, 48)
COL_HOVER  = 0xD84E1D              # blue       RGB(29, 78, 216)
COL_TEXT   = 0xF9F2ED              # near-white RGB(237, 242, 249)
COL_SEP    = 0x6A4C38              # subtle     RGB(56, 76, 106)
COL_CHECK  = 0x8EE76E              # green      RGB(110, 231, 142)

# ---- win32 types -----------------------------------------------------
user32   = ctypes.WinDLL("user32", use_last_error=True)
shell32  = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32    = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:
    dwmapi = None


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.WINFUNCTYPE(
                    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                    ctypes.c_size_t, ctypes.c_ssize_t)),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", ctypes.c_void_p),
                ("fErase", wintypes.BOOL),
                ("rcPaint", RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint), ("pt", POINT)]


class NOTIFYICONDATAW(ctypes.Structure):
    # struct is 976 bytes on x64; we only fill the classic prefix + guid
    class _GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort),
                    ("c", ctypes.c_ushort),
                    ("d", ctypes.c_ubyte * 8)]
    _fields_ = [("cbSize", ctypes.c_uint),
                ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", ctypes.c_uint),
                ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint),
                ("guidItem", _GUID),
                ("hBalloonIcon", ctypes.c_void_p)]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
    ctypes.c_size_t, ctypes.c_ssize_t)


# ---- v2.6.3: EXPLICIT PROTOTYPES (fixes the 64-bit tray crash) --------
# hub.log on 64-bit Windows showed:
#   [TRAY] tray unavailable: ArgumentError('argument 11: OverflowError:
#          int too long to convert')
# Root cause: kernel32.GetModuleHandleW had no restype declared, so
# ctypes truncated the real 64-bit HMODULE to a 32-bit signed int; the
# WNDCLASSW.hInstance field (c_void_p) sign-extended it back into a huge
# bogus value (~1.8e19); passing that field to CreateWindowExW - whose
# argument 11 IS hInstance - then failed ctypes' default 32-bit
# conversion. Net effect: the tray icon NEVER appeared on 64-bit
# machines. Every function that touches a HANDLE / pointer now has exact
# argtypes + restypes, so 64-bit values survive every call untouched.
_void_p  = ctypes.c_void_p
_u32     = ctypes.c_uint32
_i32     = ctypes.c_int32
_ssize   = ctypes.c_ssize_t
_size    = ctypes.c_size_t
_wstr    = ctypes.c_wchar_p
_P       = ctypes.POINTER

def _setprot(dll, name, restype=None, *argtypes):
    try:
        fn = getattr(dll, name)
    except AttributeError:
        return
    if restype is not None:
        fn.restype = restype
    if argtypes:
        fn.argtypes = list(argtypes)

# kernel32
_setprot(kernel32, "GetModuleHandleW", _void_p, _wstr)
# user32 - window / class management
_setprot(user32, "RegisterClassW", ctypes.c_ushort, _P(WNDCLASSW))
_setprot(user32, "CreateWindowExW", _void_p,
         _u32, _wstr, _wstr, _u32, _i32, _i32, _i32, _i32,
         _void_p, _void_p, _void_p, _void_p)
_setprot(user32, "DefWindowProcW", _ssize, _void_p, _u32, _size, _ssize)
_setprot(user32, "DestroyWindow", wintypes.BOOL, _void_p)
_setprot(user32, "ShowWindow", wintypes.BOOL, _void_p, _i32)
_setprot(user32, "SetForegroundWindow", wintypes.BOOL, _void_p)
_setprot(user32, "SetCapture", _void_p, _void_p)
_setprot(user32, "ReleaseCapture", wintypes.BOOL)
_setprot(user32, "GetMessageW", _ssize, _P(MSG), _void_p, _u32, _u32)
_setprot(user32, "TranslateMessage", wintypes.BOOL, _P(MSG))
_setprot(user32, "DispatchMessageW", _ssize, _P(MSG))
_setprot(user32, "PostMessageW", wintypes.BOOL,
         _void_p, _u32, _size, _ssize)
_setprot(user32, "PostQuitMessage", None, _i32)
_setprot(user32, "InvalidateRect", wintypes.BOOL, _void_p, _P(RECT),
         wintypes.BOOL)
_setprot(user32, "GetClientRect", wintypes.BOOL, _void_p, _P(RECT))
_setprot(user32, "GetWindowRect", wintypes.BOOL, _void_p, _P(RECT))
_setprot(user32, "GetCursorPos", wintypes.BOOL, _P(POINT))
_setprot(user32, "SystemParametersInfoW", wintypes.BOOL,
         _u32, _u32, _void_p, _u32)
_setprot(user32, "LoadCursorW", _void_p, _void_p, _void_p)
_setprot(user32, "LoadIconW", _void_p, _void_p, _void_p)
_setprot(user32, "LoadImageW", _void_p,
         _void_p, _wstr, _u32, _i32, _i32, _u32)
# user32 - painting
_setprot(user32, "GetDC", _void_p, _void_p)
_setprot(user32, "ReleaseDC", _i32, _void_p, _void_p)
_setprot(user32, "BeginPaint", _void_p, _void_p, _P(PAINTSTRUCT))
_setprot(user32, "EndPaint", wintypes.BOOL, _void_p, _P(PAINTSTRUCT))
_setprot(user32, "FillRect", _i32, _void_p, _P(RECT), _void_p)
_setprot(user32, "DrawTextW", _i32, _void_p, _wstr, _i32, _P(RECT), _u32)
# user32 - classic fallback menu
_setprot(user32, "CreatePopupMenu", _void_p)
_setprot(user32, "AppendMenuW", wintypes.BOOL,
         _void_p, _u32, _size, _wstr)
_setprot(user32, "TrackPopupMenu", wintypes.BOOL,
         _void_p, _u32, _i32, _i32, _i32, _void_p, _void_p)
_setprot(user32, "DestroyMenu", wintypes.BOOL, _void_p)
# gdi32
_setprot(gdi32, "GetDeviceCaps", _i32, _void_p, _i32)
_setprot(gdi32, "GetTextExtentPoint32W", wintypes.BOOL,
         _void_p, _wstr, _i32, _P(SIZE))
_setprot(gdi32, "SelectObject", _void_p, _void_p, _void_p)
_setprot(gdi32, "CreateFontW", _void_p,
         _i32, _i32, _i32, _i32, _i32, _u32, _u32, _u32, _u32,
         _u32, _u32, _u32, _u32, _wstr)
_setprot(gdi32, "CreateSolidBrush", _void_p, _u32)
_setprot(gdi32, "CreatePen", _void_p, _i32, _i32, _u32)
_setprot(gdi32, "DeleteObject", wintypes.BOOL, _void_p)
_setprot(gdi32, "MoveToEx", wintypes.BOOL,
         _void_p, _i32, _i32, _P(POINT))
_setprot(gdi32, "LineTo", wintypes.BOOL, _void_p, _i32, _i32)
_setprot(gdi32, "SetBkMode", _i32, _void_p, _i32)
_setprot(gdi32, "SetTextColor", _u32, _void_p, _u32)
# shell32
_setprot(shell32, "Shell_NotifyIconW", wintypes.BOOL,
         _u32, _P(NOTIFYICONDATAW))
# dwmapi
if dwmapi is not None:
    _setprot(dwmapi, "DwmSetWindowAttribute", _ssize,
             _void_p, _u32, _void_p, _u32)

# module handle is now a REAL unsigned 64-bit value (was silently
# truncated before v2.6.3 - the direct cause of the tray crash)
_HINSTANCE = kernel32.GetModuleHandleW(None)


# v2.6.2: the menu window class is registered ONCE per process with a
# MODULE-LEVEL trampoline that must never be garbage-collected (a
# per-instance trampoline would dangle after the first menu closes and
# crash the second open). The trampoline routes to the currently open
# menu, if any.
_MENU_CURRENT = [None]


def _menu_wndproc_trampoline(hwnd, msg, wparam, lparam):
    m = _MENU_CURRENT[0]
    if m is not None:
        try:
            return m._wndproc(hwnd, msg, wparam, lparam)
        except Exception:
            pass
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_MENU_PROC_REF = _WNDPROC(_menu_wndproc_trampoline)


def _dpi_scale():
    """Scale factor for the current primary monitor (1.0 = 96 dpi)."""
    try:
        dc = user32.GetDC(None)
        try:
            px = gdi32.GetDeviceCaps(dc, LOGPIXELSX)
            return max(1.0, float(px) / 96.0)
        finally:
            user32.ReleaseDC(None, dc)
    except Exception:
        return 1.0


# =====================================================================
#  v2.6.2: SELF-DRAWN MENU WINDOW
# =====================================================================
class _MenuWindow(object):
    """A tiny topmost popup we paint 100% ourselves.

    Dark navy background + white text + blue hover + green checks.
    Ignores whatever colors the user's shell theme tries to impose,
    so menu text is ALWAYS readable (fixes the white-on-white menu
    reported on machines with shell replacements / custom themes).

    Lifecycle: create(items) -> run() -> returns the picked command id,
    or 0 when dismissed without a choice. Raises on ANY setup failure
    (caller falls back to the native menu)."""

    CLASSNAME = "AdvPrintProMenuWnd"
    _registered = False
    _font_cache = {}          # v2.9.0: scale -> HFONT, reused across shows
                              # (creating a ClearType font on every
                              # right-click made the first paint sluggish)

    def __init__(self, items, logf=None):
        self.items = items            # list of ("sep",) / (text, cmd, check)
        self.logf = logf or (lambda *a, **k: None)
        self.hwnd = None
        self.font = None
        self.scale = _dpi_scale()
        self.row_h = int(30 * self.scale)
        self.pad = int(8 * self.scale)
        self.gutter = int(34 * self.scale)
        self.hover = -1
        self.pressed = -1
        self.visible = False
        self.result = 0
        self._width = 0
        self._height = 0

    # ---- setup -------------------------------------------------------
    def _ensure_class(self):
        if _MenuWindow._registered:
            return
        wc = WNDCLASSW()
        wc.style = CS_VREDRAW | CS_HREDRAW | CS_DROPSHADOW
        wc.lpfnWndProc = _MENU_PROC_REF      # module-level, never GC'd
        wc.hInstance = _HINSTANCE            # real 64-bit HMODULE (v2.6.3)
        wc.lpszClassName = self.CLASSNAME
        wc.hCursor = user32.LoadCursorW(None, 32512)   # IDC_ARROW
        if not user32.RegisterClassW(ctypes.byref(wc)) \
                and kernel32.GetLastError() != 1410:
            raise ctypes.WinError(kernel32.GetLastError())
        _MenuWindow._registered = True

    def _measure(self):
        """Compute the window size from the item texts (DPI-aware)."""
        dc = user32.GetDC(None)
        try:
            self.font = self._make_font()
            old = gdi32.SelectObject(dc, self.font)
            try:
                wmax = 0
                for it in self.items:
                    if it[0] == "sep":
                        continue
                    sz = SIZE()
                    gdi32.GetTextExtentPoint32W(dc, it[0], len(it[0]),
                                                ctypes.byref(sz))
                    if sz.cx > wmax:
                        wmax = sz.cx
            finally:
                gdi32.SelectObject(dc, old)
        finally:
            user32.ReleaseDC(None, dc)
        self._width = wmax + self.gutter + 2 * self.pad + int(18 * self.scale)
        rows = 0
        for it in self.items:
            rows += 1 if it[0] != "sep" else 0.5
        self._height = int(rows * self.row_h) + 2 * self.pad

    def _make_font(self):
        f = _MenuWindow._font_cache.get(self.scale)
        if f:
            return f
        f = gdi32.CreateFontW(
            ctypes.c_int(-int(15 * self.scale)), 0, 0, 0, FW_NORMAL,
            0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
            "Segoe UI")
        _MenuWindow._font_cache[self.scale] = f
        return f

    def _place(self):
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        wa = RECT()
        if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                            ctypes.byref(wa), 0):
            wa.left, wa.top, wa.right, wa.bottom = 0, 0, 1920, 1040
        x = pt.x
        y = pt.y
        if x + self._width > wa.right:
            x = pt.x - self._width
        if y + self._height > wa.bottom:
            y = pt.y - self._height
        x = max(wa.left, min(x, wa.right - self._width))
        y = max(wa.top, min(y, wa.bottom - self._height))
        return x, y

    # ---- run ---------------------------------------------------------
    def run(self):
        self._ensure_class()
        self._measure()
        x, y = self._place()
        self.hwnd = user32.CreateWindowExW(
            0x00000080 | 0x00000008,          # WS_EX_TOOLWINDOW | TOPMOST
            self.CLASSNAME, APP + " menu", 0x80000000,   # WS_POPUP
            int(x), int(y), self._width, self._height,
            None, None, _HINSTANCE, None)
        if not self.hwnd:
            raise ctypes.WinError(kernel32.GetLastError())
        # Win11: rounded corners (ignored on Win10, fail-safe everywhere)
        if dwmapi is not None:
            try:
                pref = ctypes.c_int(DWMWCP_ROUND)
                dwmapi.DwmSetWindowAttribute(self.hwnd, 33,
                                             ctypes.byref(pref), 4)
            except Exception:
                pass
        self.visible = True
        _MENU_CURRENT[0] = self
        user32.ShowWindow(self.hwnd, SW_SHOWNA)
        user32.SetForegroundWindow(self.hwnd)
        user32.SetCapture(self.hwnd)
        try:
            msg = MSG()
            while self.visible:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _MENU_CURRENT[0] = None
            user32.ReleaseCapture()
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            # v2.9.0: the font is shared (cached per scale) and must NOT
            # be deleted here - deleting it forced the NEXT right-click
            # to recreate it (and could paint garbage text once the
            # cached HFONT was freed).
        return self.result

    def _close(self, result=0):
        self.result = result
        self.visible = False
        try:
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        except Exception:
            pass

    # ---- hit test ----------------------------------------------------
    def _hit(self, lparam):
        """Row index under the mouse (lparam = packed client coords)."""
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        if x < 0 or y < 0 or x >= self._width or y >= self._height:
            return -1
        yy = y - self.pad
        idx = 0
        for it in self.items:
            h = int(self.row_h * (1 if it[0] != "sep" else 0.5))
            if yy < h:
                return idx if it[0] != "sep" else -1
            yy -= h
            if it[0] != "sep":
                idx += 1
        return -1

    def _pos_of(self, ordinal):
        """v3.0.1 FIX - map a selectable-row ORDINAL to its real position
        in self.items. _hit() counts only selectable rows, but self.items
        also holds ("sep",) entries; the old WM_LBUTTONUP code did
        self.items[idx] with the RAW ordinal, so every item AFTER the
        first separator executed the WRONG action: clicking 'Pause queue'
        did nothing, 'Start at Windows logon' paused the queue,
        'Restart hub' toggled autostart, 'Allow LAN in firewall'
        RESTARTED the hub and 'Exit' opened the firewall prompt - exactly
        the 'menu text and click not the same area' bug report. The
        highlight and the hit bands were always consistent (the same
        ordinal math everywhere) - only this final text->action lookup
        was shifted by one per separator."""
        n = 0
        for pos, it in enumerate(self.items):
            if it[0] != "sep":
                if n == ordinal:
                    return pos
                n += 1
        return -1

    def _row_rect(self, hdc, index):
        """RECT of the i-th selectable row (separators take half rows)."""
        rect = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        y = self.pad
        idx = 0
        for it in self.items:
            h = int(self.row_h * (1 if it[0] != "sep" else 0.5))
            if it[0] != "sep" and idx == index:
                rect.top = y
                rect.bottom = y + h
                return rect
            y += h
            if it[0] != "sep":
                idx += 1
        rect.top = rect.bottom = 0
        return rect

    # ---- painting ----------------------------------------------------
    def _paint(self, hwnd, wparam, lparam):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return 0
        try:
            bg = gdi32.CreateSolidBrush(COL_BG)
            user32.FillRect(hdc, ctypes.byref(ps.rcPaint), bg)
            gdi32.DeleteObject(bg)
            if not self.font:
                self.font = self._make_font()
            old_font = gdi32.SelectObject(hdc, self.font)
            old_bk = gdi32.SetBkMode(hdc, TRANSPARENT)
            old_tx = gdi32.SetTextColor(hdc, COL_TEXT)
            try:
                idx = 0
                y = self.pad
                for it in self.items:
                    if it[0] == "sep":
                        pen = gdi32.CreatePen(0, 1, COL_SEP)   # PS_SOLID
                        old_pen = gdi32.SelectObject(hdc, pen)
                        gdi32.MoveToEx(hdc, self.pad, y + int(self.row_h * 0.25), None)
                        gdi32.LineTo(hdc, self._width - self.pad,
                                     y + int(self.row_h * 0.25))
                        gdi32.SelectObject(hdc, old_pen)
                        gdi32.DeleteObject(pen)
                        y += int(self.row_h * 0.5)
                        continue
                    rect = self._row_rect(hwnd, idx)
                    if idx == self.hover:
                        hb = gdi32.CreateSolidBrush(COL_HOVER)
                        user32.FillRect(hdc, ctypes.byref(rect), hb)
                        gdi32.DeleteObject(hb)
                    text, _cmd, checked = it
                    if checked:
                        self._draw_check(hdc, rect)
                    trect = RECT()
                    trect.left = rect.left + self.gutter
                    trect.top = rect.top
                    trect.right = rect.right - self.pad
                    trect.bottom = rect.bottom
                    user32.DrawTextW(hdc, text, len(text), ctypes.byref(trect),
                                     DT_LEFT | DT_VCENTER | DT_SINGLELINE)
                    y += self.row_h
                    idx += 1
            finally:
                gdi32.SelectObject(hdc, old_font)
                gdi32.SetBkMode(hdc, old_bk)
                gdi32.SetTextColor(hdc, old_tx)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))
        return 0

    def _draw_check(self, hdc, rect):
        """A crisp green checkmark in the left gutter (2 GDI lines)."""
        pen = gdi32.CreatePen(0, max(2, int(2 * self.scale)), COL_CHECK)
        old = gdi32.SelectObject(hdc, pen)
        try:
            cx = self.pad + int(10 * self.scale)
            cy = (rect.top + rect.bottom) // 2
            gdi32.MoveToEx(hdc, cx - int(5 * self.scale), cy, None)
            gdi32.LineTo(hdc, cx - int(1 * self.scale), cy + int(4 * self.scale))
            gdi32.LineTo(hdc, cx + int(6 * self.scale), cy - int(4 * self.scale))
        finally:
            gdi32.SelectObject(hdc, old)
            gdi32.DeleteObject(pen)

    # ---- window proc -------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_PAINT:
                return self._paint(hwnd, wparam, lparam)
            if msg == WM_MOUSEMOVE:
                if not self._inside_cursor_screen():
                    self._close(0)          # clicked/dragged outside
                    return 0
                idx = self._hit(lparam)
                if idx != self.hover:
                    self.hover = idx
                    user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_LBUTTONDOWN:
                self.pressed = self._hit(lparam)
                return 0
            if msg == WM_LBUTTONUP:
                idx = self._hit(lparam)
                if idx >= 0 and idx == self.pressed:
                    # v3.0.1 fix: idx is a selectable-row ordinal - map it
                    # to the real self.items position first (the old
                    # self.items[idx] lookup was shifted by every
                    # separator: 'Exit' ran the firewall prompt, 'Allow
                    # LAN in firewall' restarted the hub, ...).
                    pos = self._pos_of(idx)
                    if pos >= 0:
                        self._close(self.items[pos][1])
                self.pressed = -1
                return 0
            if msg == WM_KEYDOWN and wparam == VK_ESCAPE:
                self._close(0)
                return 0
            if msg == WM_ACTIVATE:
                if (wparam & 0xFFFF) == 0:  # WA_INACTIVE -> user went away
                    self._close(0)
                return 0
            if msg == WM_KILLFOCUS:
                self._close(0)
                return 0
            if msg == WM_CLOSE:
                self._close(0)
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                return 0
        except Exception as e:
            self.logf("[TRAY] menu proc error: %r" % (e,))
            try:
                self._close(0)
            except Exception:
                pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _inside_cursor_screen(self):
        """With mouse capture, detect leaving the window (screen coords)."""
        pt = POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return True
        rect = RECT()
        if not user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            return True
        return (rect.left <= pt.x <= rect.right and
                rect.top <= pt.y <= rect.bottom)


class Tray(object):
    """One tray icon bound to one hidden message window."""

    def __init__(self, icon_path, tooltip, callbacks=None, logf=None):
        self.icon_path = icon_path or ""
        self.tooltip = (tooltip or APP)[:127]
        self.cb = callbacks or {}
        self.logf = logf or (lambda *a, **k: None)
        self.hwnd = None
        self.hicon = None
        self.uid = 7240                      # arbitrary, unique per process
        self._added = False
        self._alive = True
        self._tid = None

    # ---- helpers -----------------------------------------------------
    def _log(self, msg):
        try:
            self.logf("[TRAY] " + msg)
        except Exception:
            pass

    def _load_icon(self):
        if self.icon_path and os.path.isfile(self.icon_path):
            h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        return user32.LoadIconW(None, IDI_APPLICATION)

    # ---- window ------------------------------------------------------
    def _register_and_create(self):
        self.wc = WNDCLASSW()
        self.wc.style = CS_VREDRAW | CS_HREDRAW
        self.wc.lpfnWndProc = _WNDPROC(self._wndproc)   # keep a reference!
        self.wc.hInstance = _HINSTANCE                  # real 64-bit HMODULE
        self.wc.lpszClassName = "AdvPrintProTrayWnd"
        self.wc.hIcon = self._load_icon()
        if not user32.RegisterClassW(ctypes.byref(self.wc)) \
                and kernel32.GetLastError() != 1410:     # already registered
            raise ctypes.WinError(kernel32.GetLastError())
        self.hicon = self.wc.hIcon
        self.hwnd = user32.CreateWindowExW(
            0, self.wc.lpszClassName, APP + " tray", 0x80000000,  # WS_POPUP
            0, 0, 0, 0, None, None, self.wc.hInstance, None)
        if not self.hwnd:
            raise ctypes.WinError(kernel32.GetLastError())

    def _add_icon(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = self.hicon
        tip = self.tooltip
        nid.szTip = tip[:127]
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIconW(NIM_ADD) failed")
        self._added = True

    def _remove_icon(self):
        if self._added and self.hwnd:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = self.uid
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self._added = False

    # ---- message pump ------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == TRAY_MSG:
                ev = lparam & 0xFFFF
                if ev in (WM_RBUTTONUP, WM_LBUTTONUP):
                    self._show_menu()
                elif ev == WM_LBUTTONDBLCLK:
                    self._cb("on_open")
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._remove_icon()
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:                     # never die on UI errors
            self._log("wndproc error: %r" % (e,))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _cb(self, name):
        f = self.cb.get(name)
        if f:
            try:
                return f()
            except Exception as e:
                self._log("callback %s failed: %r" % (name, e))
        return None

    def _cb_async(self, name, done=None):
        """v2.9.0 SMOOTH TRAY: run a menu action on its own thread.
        Before, every action ran on the tray message-loop thread, so a
        slow one (browser launch, test page -> printer status WMI,
        firewall UAC) froze the icon: the next right-click 'lagged' and
        the menu stuttered while the action ran. Now the icon thread
        returns to GetMessage instantly and every action runs in the
        background."""
        def runner():
            try:
                r = self._cb(name)
                if done:
                    done(r)
            except Exception as e:
                self._log("async callback %s failed: %r" % (name, e))
        threading.Thread(target=runner, daemon=True,
                         name="advprint-tray-%s" % name).start()

    # ---- menu (v2.6.2 self-drawn, native fallback) --------------------
    def _menu_items(self):
        paused = bool(self._cb("is_paused"))
        auto = bool(self._cb("is_autostart"))
        return [
            ("Open dashboard", M_OPEN, False),
            ("Print test page", M_TEST, False),
            ("sep",),
            ("Pause queue", M_PAUSE, paused),
            ("Start at Windows logon", M_AUTO, auto),
            ("Restart hub", M_RESTART, False),
            ("Allow LAN in firewall", M_FIREWALL, False),
            ("sep",),
            ("Exit", M_EXIT, False),
        ]

    def _show_menu(self):
        items = self._menu_items()
        cmd = -1                                   # -1 = "not shown yet"
        try:
            menu = _MenuWindow(items, logf=self._log)
            cmd = menu.run()                       # 0 = dismissed, >0 pick
        except Exception as e:
            self._log("self-drawn menu unavailable (%r) - native menu" % (e,))
            cmd = -1
        if cmd < 0:                                # could not show at all
            try:
                cmd = self._show_menu_native(items)
            except Exception as e:
                self._log("native menu failed: %r" % (e,))
                return
        if cmd:
            self._dispatch_menu_cmd(cmd)

    def _show_menu_native(self, items):
        """Classic Win32 popup menu (pre-2.6.2 behavior). Colors come
        from the shell theme - that is exactly why it is only the
        FALLBACK now: on machines with shell replacements it rendered
        white-on-white. Kept as a safety net for exotic setups."""
        menu = user32.CreatePopupMenu()
        if not menu:
            return 0
        for it in items:
            if it[0] == "sep":
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                flags = MF_STRING | (MF_CHECKED if it[2] else 0)
                user32.AppendMenuW(menu, flags, it[1], it[0])
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # foreground quirk: menu must be dismissed properly
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        return int(cmd)

    def _dispatch_menu_cmd(self, cmd):
        if cmd == M_OPEN:
            self._cb_async("on_open")
        elif cmd == M_TEST:
            self._cb_async("on_test", done=lambda r: self._log(
                "test page queued from the tray menu"))
        elif cmd == M_PAUSE:
            self._cb_async("on_pause_toggle", done=lambda p: self._log(
                "queue %s (tray)" % ("paused" if p else "resumed")))
        elif cmd == M_AUTO:
            self._cb_async("on_autostart_toggle", done=lambda a: self._log(
                "autostart %s (tray)" % ("ON" if a else "OFF")))
        elif cmd == M_RESTART:
            # v2.8: the callback launches the new hub and schedules the
            # exit - the tray icon of THIS process disappears with it.
            self._log("restart requested from the tray menu")
            self._cb_async("on_restart")
        elif cmd == M_FIREWALL:
            # v2.8.2: one-click Windows firewall rule (single UAC prompt).
            self._log("firewall allow requested from the tray menu")
            self._cb_async("on_firewall")
        elif cmd == M_EXIT:
            self._log("exit requested from tray")
            self.stop()
            self._cb("on_exit")

    # ---- lifecycle ---------------------------------------------------
    def run(self):
        try:
            self._register_and_create()
            self._add_icon()
        except Exception as e:
            self._log("tray unavailable: %r" % (e,))
            self._alive = False
            return
        self._log("tray icon running (tooltip: %s)" % self.tooltip)
        msg = MSG()
        while self._alive and user32.GetMessageW(ctypes.byref(msg),
                                                 None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._remove_icon()
        self._log("tray loop ended")

    def start_thread(self):
        self._tid = threading.Thread(target=self.run, name="advprint-tray",
                                     daemon=True)
        self._tid.start()

    def stop(self):
        self._alive = False
        try:
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


_SINGLETON = None


def start(icon, tooltip, callbacks=None, logf=None):
    """Start the tray icon thread. Returns True when the icon is (being)
    shown. Never raises."""
    global _SINGLETON
    try:
        _SINGLETON = Tray(icon, tooltip, callbacks, logf)
        _SINGLETON.start_thread()
        return True
    except Exception as e:                          # absolute last resort
        try:
            (logf or (lambda *a, **k: None))("[TRAY] start failed: %r" % (e,))
        except Exception:
            pass
        return False
