from __future__ import annotations
from dataclasses import dataclass
import ctypes
import sys

@dataclass(slots=True)
class GpuInfo:
    provider: str

    @property
    def is_amd(self) -> bool:
        return self.provider == "amd"

    @property
    def is_nvidia(self) -> bool:
        return self.provider == "nvidia"

    @property
    def max_saturation(self) -> int:
        return 200 if self.is_amd else 100

    @property
    def default_saturation(self) -> int:
        return 100 if self.is_amd else 0

    @property
    def is_supported(self) -> bool:
        return self.provider in ("amd", "nvidia")

_GPU_INFO_CACHE: GpuInfo | None = None

def get_gpu_info() -> GpuInfo:
    global _GPU_INFO_CACHE
    if _GPU_INFO_CACHE is not None:
        return _GPU_INFO_CACHE

    provider = "none"
    if sys.platform == "win32":
        # Test léger de présence des DLLs sans initialiser les gros contrôleurs
        try:
            ctypes.WinDLL("nvapi64.dll")
            provider = "nvidia"
        except OSError:
            try:
                ctypes.WinDLL("atiadlxx.dll")
                provider = "amd"
            except OSError:
                pass

    _GPU_INFO_CACHE = GpuInfo(provider=provider)
    return _GPU_INFO_CACHE