from __future__ import annotations

# RAT VISION ADL (AMD Display Library) reimplementation, 2026-09-20.
# Behavior was cross-checked against AMD's public display-library SDK
# (GPUOpen-LibrariesAndSDKs/display-library, Sample/ColorCaps/main.cpp and
# include/{adl_sdk.h,adl_structures.h,adl_defines.h}); this Python ctypes
# implementation is modified/new RAT VISION code.
#
# Unlike NVAPI's DVC calls, ADL_Display_Color_* is public, documented API,
# so this does not need dvc_subprocess.py's crash-isolation treatment -
# AdlSaturationController below runs in-process. It already exposes the
# capture/set_level/restore/restore_all/capabilities shape
# WindowsColorBackend expects, so it can be wired in directly.

import ctypes
from dataclasses import dataclass
import sys

from ratvision.platform.base import PlatformUnavailableError

ADL_OK = 0

ADL_DISPLAY_COLOR_BRIGHTNESS = 1 << 0
ADL_DISPLAY_COLOR_CONTRAST = 1 << 1
ADL_DISPLAY_COLOR_SATURATION = 1 << 2
ADL_DISPLAY_COLOR_HUE = 1 << 3
ADL_DISPLAY_COLOR_TEMPERATURE = 1 << 4

ADL_DISPLAY_DISPLAYINFO_DISPLAYCONNECTED = 0x00000001
ADL_DISPLAY_DISPLAYINFO_DISPLAYMAPPED = 0x00000002
ADL_MAX_PATH = 256

_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
ADL_MAIN_MALLOC_CALLBACK = _CALLBACK_FACTORY(ctypes.c_void_p, ctypes.c_int)


class AdlError(RuntimeError):
    def __init__(self, operation: str, status: int):
        super().__init__(f"{operation} failed with ADL status {status}")
        self.operation = operation
        self.status = int(status)


class _AdapterInfoNative(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * ADL_MAX_PATH),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", ctypes.c_char * ADL_MAX_PATH),
        ("strPNPString", ctypes.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


class _AdlDisplayIdNative(ctypes.Structure):
    _fields_ = [
        ("iDisplayLogicalIndex", ctypes.c_int),
        ("iDisplayPhysicalIndex", ctypes.c_int),
        ("iDisplayLogicalAdapterIndex", ctypes.c_int),
        ("iDisplayPhysicalAdapterIndex", ctypes.c_int),
    ]


class _AdlDisplayInfoNative(ctypes.Structure):
    _fields_ = [
        ("displayID", _AdlDisplayIdNative),
        ("iDisplayControllerIndex", ctypes.c_int),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayManufacturerName", ctypes.c_char * ADL_MAX_PATH),
        ("iDisplayType", ctypes.c_int),
        ("iDisplayOutputType", ctypes.c_int),
        ("iDisplayConnector", ctypes.c_int),
        ("iDisplayInfoMask", ctypes.c_int),
        ("iDisplayInfoValue", ctypes.c_int),
    ]


@dataclass(frozen=True, slots=True)
class AdlDisplayHandle:
    """(adapter, display) pair ADL_Display_Color_* expects - resolved once
    per display_id and reused, mirroring NvApiNative's opaque handle."""

    adapter_index: int
    display_index: int


@dataclass(frozen=True, slots=True)
class SaturationInfo:
    current: int
    minimum: int
    maximum: int


class AdlNative:
    def __init__(self, *, library=None):
        if library is None:
            if sys.platform != "win32":
                raise PlatformUnavailableError("AMD ADL requires Windows")
            try:
                library = ctypes.WinDLL("atiadlxx.dll")
            except OSError as exc:
                raise PlatformUnavailableError(
                    "atiadlxx.dll not found (no AMD driver installed?)"
                ) from exc
        self._library = library

        self._crt = ctypes.CDLL("msvcrt")
        self._crt.malloc.restype = ctypes.c_void_p
        self._crt.malloc.argtypes = [ctypes.c_size_t]

        self._crt.free.restype = None
        self._crt.free.argtypes = [ctypes.c_void_p]

        @ADL_MAIN_MALLOC_CALLBACK
        def _alloc(size: int) -> int:
            return self._crt.malloc(size) or 0

        self._alloc_callback = _alloc
        
        self._free = self._crt.free

        self._create = self._bind(
            "ADL_Main_Control_Create", [ADL_MAIN_MALLOC_CALLBACK, ctypes.c_int]
        )
        self._destroy = self._bind("ADL_Main_Control_Destroy", [])
        self._num_adapters = self._bind(
            "ADL_Adapter_NumberOfAdapters_Get", [ctypes.POINTER(ctypes.c_int)]
        )
        self._adapter_info_get = self._bind(
            "ADL_Adapter_AdapterInfo_Get",
            [ctypes.POINTER(_AdapterInfoNative), ctypes.c_int],
        )
        self._display_info_get = self._bind(
            "ADL_Display_DisplayInfo_Get",
            [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.POINTER(_AdlDisplayInfoNative)),
                ctypes.c_int,
            ],
        )
        self._color_get = self._bind(
            "ADL_Display_Color_Get",
            [ctypes.c_int] * 3 + [ctypes.POINTER(ctypes.c_int)] * 5,
        )
        self._color_set = self._bind("ADL_Display_Color_Set", [ctypes.c_int] * 4)

    def _bind(self, name: str, argtypes: list):
        func = getattr(self._library, name)
        func.restype = ctypes.c_int
        func.argtypes = argtypes
        return func

    @staticmethod
    def _check(operation: str, status: int) -> None:
        if int(status) < ADL_OK:
            raise AdlError(operation, int(status))

    def initialize(self) -> None:
        self._check("ADL_Main_Control_Create", self._create(self._alloc_callback, 1))

    def unload(self) -> None:
        self._check("ADL_Main_Control_Destroy", self._destroy())

    def _adl_free(self, pointer) -> None:
        if pointer:
            self._free(ctypes.cast(pointer, ctypes.c_void_p))

    def _adapters(self) -> list[_AdapterInfoNative]:
        count = ctypes.c_int(0)
        self._check(
            "ADL_Adapter_NumberOfAdapters_Get",
            self._num_adapters(ctypes.byref(count)),
        )
        if count.value <= 0:
            return []
        buffer = (_AdapterInfoNative * count.value)()
        self._check(
            "ADL_Adapter_AdapterInfo_Get",
            self._adapter_info_get(buffer, ctypes.sizeof(buffer)),
        )
        return list(buffer)

    def get_display_handle(self, display_id: str) -> AdlDisplayHandle:
        """Resolve a GDI device name (e.g. "\\\\.\\DISPLAY1", the same
        display_id WindowsDisplayProvider hands out) to an ADL
        (adapter_index, display_index) pair, following the enumeration
        order AMD's own ColorCaps sample uses."""
        target = display_id.encode("mbcs", errors="ignore") if sys.platform == "win32" else display_id.encode()
        for adapter in self._adapters():
            if adapter.strDisplayName != target:
                continue
            handle = self._display_index_for(adapter.iAdapterIndex, target)
            if handle is not None:
                return handle
        raise AdlError(f"resolve display {display_id!r}", -1)

    def _display_index_for(self, adapter_index: int, target: bytes) -> AdlDisplayHandle | None:
        count = ctypes.c_int(0)
        info_ptr = ctypes.POINTER(_AdlDisplayInfoNative)()
        status = self._display_info_get(
            adapter_index, ctypes.byref(count), ctypes.byref(info_ptr), 0
        )
        if status < ADL_OK or not info_ptr:
            return None
        try:
            required = ADL_DISPLAY_DISPLAYINFO_DISPLAYCONNECTED | ADL_DISPLAY_DISPLAYINFO_DISPLAYMAPPED
            for entry in info_ptr[: count.value]:
                if entry.iDisplayInfoValue & required != required:
                    continue
                if entry.displayID.iDisplayLogicalAdapterIndex != adapter_index:
                    continue
                if target and entry.strDisplayName and entry.strDisplayName != target:
                    continue
                return AdlDisplayHandle(adapter_index, entry.displayID.iDisplayLogicalIndex)
            
            for entry in info_ptr[: count.value]:
                if entry.iDisplayInfoValue & required != required:
                    continue
                if entry.displayID.iDisplayLogicalAdapterIndex == adapter_index:
                    return AdlDisplayHandle(adapter_index, entry.displayID.iDisplayLogicalIndex)
            return None
        finally:
            self._adl_free(info_ptr)

    def get_saturation_info(self, handle: AdlDisplayHandle) -> SaturationInfo:
        cur, dft, low, high, step = (ctypes.c_int(0) for _ in range(5))
        self._check(
            "ADL_Display_Color_Get",
            self._color_get(
                handle.adapter_index,
                handle.display_index,
                ADL_DISPLAY_COLOR_SATURATION,
                ctypes.byref(cur),
                ctypes.byref(dft),
                ctypes.byref(low),
                ctypes.byref(high),
                ctypes.byref(step),
            ),
        )
        return SaturationInfo(cur.value, low.value, high.value)

    def set_saturation_level(self, handle: AdlDisplayHandle, level: int) -> None:
        self._check(
            "ADL_Display_Color_Set",
            self._color_set(
                handle.adapter_index,
                handle.display_index,
                ADL_DISPLAY_COLOR_SATURATION,
                int(level),
            ),
        )


class AdlSaturationController:
    """AMD counterpart to NvApiDvcController - same capture/set_level/
    restore/restore_all/capabilities shape WindowsColorBackend expects."""

    def __init__(self, *, native=None):
        self.native = native or AdlNative()
        self.native.initialize()
        self.handles: dict[str, AdlDisplayHandle] = {}
        self.originals: dict[str, int] = {}
        self.ranges: dict[str, tuple[int, int]] = {}

    def _handle(self, display_id: str) -> AdlDisplayHandle:
        if display_id not in self.handles:
            self.handles[display_id] = self.native.get_display_handle(display_id)
        return self.handles[display_id]

    def capture(self, display_id: str) -> None:
        if display_id in self.originals:
            return
        info = self.native.get_saturation_info(self._handle(display_id))
        self.originals[display_id] = info.current
        self.ranges[display_id] = (info.minimum, info.maximum)

    def set_level(self, display_id: str, level: int) -> None:
        self.capture(display_id)
        minimum, maximum = self.ranges[display_id]
        clamped = min(max(int(level), minimum), maximum)
        self.native.set_saturation_level(self._handle(display_id), clamped)

    def restore(self, display_id: str) -> None:
        if display_id in self.originals:
            self.native.set_saturation_level(self._handle(display_id), self.originals[display_id])

    def restore_all(self) -> None:
        for display_id in list(self.originals):
            self.restore(display_id)

    def capabilities(self, display_id: str) -> dict[str, object]:
        try:
            self.capture(display_id)
        except Exception as exc:
            return {"supported": False, "reason": str(exc)}
        minimum, maximum = self.ranges[display_id]
        return {"supported": True, "minimum": minimum, "maximum": maximum}

    def close(self) -> None:
        self.restore_all()
        self.native.unload()
