from __future__ import annotations

import ctypes
from ctypes import wintypes


INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_PER_CONNECTION_OPTION = 75
INTERNET_PER_CONN_PROXY_BYPASS = 3


class _PerConnectionOptionValue(ctypes.Union):
    _fields_ = [
        ("dwValue", wintypes.DWORD),
        ("pszValue", wintypes.LPWSTR),
        ("ftValue", wintypes.FILETIME),
    ]


class _PerConnectionOption(ctypes.Structure):
    _fields_ = [
        ("dwOption", wintypes.DWORD),
        ("Value", _PerConnectionOptionValue),
    ]


class _PerConnectionOptionList(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("pszConnection", wintypes.LPWSTR),
        ("dwOptionCount", wintypes.DWORD),
        ("dwOptionError", wintypes.DWORD),
        ("pOptions", ctypes.POINTER(_PerConnectionOption)),
    ]


def apply_proxy_bypass(value: str) -> None:
    """Apply the LAN bypass list through WinINet, including its connection settings."""
    wininet = ctypes.WinDLL("wininet", use_last_error=True)
    set_option = wininet.InternetSetOptionW
    set_option.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
    set_option.restype = wintypes.BOOL

    text = ctypes.create_unicode_buffer(value)
    options = (_PerConnectionOption * 1)()
    options[0].dwOption = INTERNET_PER_CONN_PROXY_BYPASS
    options[0].Value.pszValue = ctypes.cast(text, wintypes.LPWSTR)
    option_list = _PerConnectionOptionList(
        dwSize=ctypes.sizeof(_PerConnectionOptionList),
        pszConnection=None,
        dwOptionCount=1,
        dwOptionError=0,
        pOptions=ctypes.cast(options, ctypes.POINTER(_PerConnectionOption)),
    )
    if not set_option(
        None,
        INTERNET_OPTION_PER_CONNECTION_OPTION,
        ctypes.byref(option_list),
        ctypes.sizeof(option_list),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if not set_option(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if not set_option(None, INTERNET_OPTION_REFRESH, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
