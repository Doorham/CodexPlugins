from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any


DEVICE_ID = "vid_1038&pid_2232&mi_03"
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
REPORT_LENGTH = 65
QUERY_COMMAND = 0xB0
IO_TIMEOUT_MS = 800


class Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class DeviceInterfaceData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", Guid),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def _configure_libraries():
    hid = ctypes.WinDLL("hid")
    setupapi = ctypes.WinDLL("setupapi")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(Guid)]
    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(Guid), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
    ]
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Guid), wintypes.DWORD,
        ctypes.POINTER(DeviceInterfaceData),
    ]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(DeviceInterfaceData), ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    io_args = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(Overlapped),
    ]
    kernel32.WriteFile.argtypes = io_args
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = io_args
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(Overlapped),
        ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
    ]
    kernel32.GetOverlappedResult.restype = wintypes.BOOL
    kernel32.CancelIo.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return hid, setupapi, kernel32


def _find_device_path(hid, setupapi, device_id: str = DEVICE_ID) -> str | None:
    guid = Guid()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    device_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if not device_info or device_info == INVALID_HANDLE_VALUE:
        return None
    try:
        index = 0
        while True:
            interface = DeviceInterfaceData()
            interface.cbSize = ctypes.sizeof(interface)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                device_info, None, ctypes.byref(guid), index, ctypes.byref(interface),
            ):
                return None
            required = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                device_info, ctypes.byref(interface), None, 0,
                ctypes.byref(required), None,
            )
            if not required.value:
                index += 1
                continue
            detail = ctypes.create_string_buffer(required.value)
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = 8
            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                device_info, ctypes.byref(interface), detail, required.value, None, None,
            ):
                path = ctypes.wstring_at(ctypes.addressof(detail) + 4)
                if device_id.lower() in path.lower():
                    return path
            index += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(device_info)


def _overlapped_io(kernel32, handle, buffer, *, write: bool) -> bool:
    event = kernel32.CreateEventW(None, True, False, None)
    if not event:
        return False
    overlapped = Overlapped()
    overlapped.hEvent = event
    transferred = wintypes.DWORD()
    try:
        operation = kernel32.WriteFile if write else kernel32.ReadFile
        completed = operation(
            handle, buffer, len(buffer), ctypes.byref(transferred), ctypes.byref(overlapped),
        )
        if not completed and ctypes.get_last_error() != ERROR_IO_PENDING:
            return False
        if not completed:
            if kernel32.WaitForSingleObject(event, IO_TIMEOUT_MS) != WAIT_OBJECT_0:
                kernel32.CancelIo(handle)
                return False
            completed = kernel32.GetOverlappedResult(
                handle, ctypes.byref(overlapped), ctypes.byref(transferred), False,
            )
        return bool(completed and transferred.value)
    finally:
        kernel32.CloseHandle(event)


def parse_arctis_report(report) -> dict[str, Any]:
    if len(report) < 6 or report[2] == 2:
        return {"online": False}
    return {
        "online": True,
        "percent": min(int(report[4]), 100),
        "charging": report[5] == 1,
    }


def is_arctis_receiver_present() -> bool:
    """Return whether the exact Nova 5 receiver HID interface is present."""
    try:
        hid, setupapi, _ = _configure_libraries()
        return bool(_find_device_path(hid, setupapi))
    except (OSError, ValueError, TypeError, ctypes.ArgumentError):
        return False


def is_hid_path_present(path_contains: str) -> bool:
    """Check only present HID interface paths for a stable VID/PID fragment."""
    if not path_contains or not isinstance(path_contains, str):
        return False
    try:
        hid, setupapi, _ = _configure_libraries()
        return bool(_find_device_path(hid, setupapi, path_contains))
    except (OSError, ValueError, TypeError, ctypes.ArgumentError):
        return False


def read_arctis_battery() -> dict[str, Any]:
    """Read only the Arctis Nova 5 battery HID report; never logs report data."""
    try:
        hid, setupapi, kernel32 = _configure_libraries()
        path = _find_device_path(hid, setupapi)
        if not path:
            return {"online": False}
        handle = kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            return {"online": False}
        try:
            outgoing = (ctypes.c_ubyte * REPORT_LENGTH)()
            outgoing[1] = QUERY_COMMAND
            incoming = (ctypes.c_ubyte * REPORT_LENGTH)()
            if not _overlapped_io(kernel32, handle, outgoing, write=True):
                return {"online": False}
            if not _overlapped_io(kernel32, handle, incoming, write=False):
                return {"online": False}
            return parse_arctis_report(incoming)
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError, TypeError, ctypes.ArgumentError):
        return {"online": False}
