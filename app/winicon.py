# -*- coding: utf-8 -*-
"""Windows：把台股羅盤的黑色視窗（主控台）換上羅盤圖示與中文標題，工作列上就會顯示羅盤圖示。
不是 Windows、或系統不支援時什麼都不做。"""
import os
import sys


def apply(ico_path, title="台股羅盤（伺服器執行中，請保持開啟）"):
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32.SetConsoleTitleW(title)
        hwnd = k32.GetConsoleWindow()
        if not hwnd or not os.path.exists(ico_path):
            return False
        u32.LoadImageW.restype = wintypes.HANDLE
        u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        big = u32.LoadImageW(None, ico_path, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        small = u32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        WM_SETICON = 0x80
        if big:
            u32.SendMessageW(hwnd, WM_SETICON, 1, big)       # ICON_BIG：工作列、Alt+Tab
        if small:
            u32.SendMessageW(hwnd, WM_SETICON, 0, small)     # ICON_SMALL：視窗左上角
        try:
            k32.SetConsoleIcon(small or big)                 # 舊版主控台的隱藏函式，有就用
        except Exception:
            pass
        return True
    except Exception as e:
        try:
            sys.stderr.write("winicon: %s\n" % e)
        except Exception:
            pass
        return False
