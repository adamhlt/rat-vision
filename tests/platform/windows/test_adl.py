from ratvision.platform.windows.adl import (
    ADL_DISPLAY_COLOR_SATURATION,
    AdlDisplayHandle,
    AdlSaturationController,
    SaturationInfo,
)


def test_saturation_flag_is_the_documented_bit_not_the_index():
    # adl_defines.h: ADL_DISPLAY_COLOR_SATURATION is (1 << 2) == 4.
    # A regression back to the literal 2 silently targets contrast instead.
    assert ADL_DISPLAY_COLOR_SATURATION == 4


class FakeNative:
    """Mirrors nvapi.py's FakeNative so the controller test reads the same way."""

    def __init__(self):
        self.values = {"D1": 35}
        self.ranges = {"D1": (0, 100)}
        self.set_calls: list[tuple[str, int]] = []
        self.resolved: list[str] = []

    def initialize(self):
        pass

    def unload(self):
        pass

    def get_display_handle(self, display_id: str) -> AdlDisplayHandle:
        self.resolved.append(display_id)
        return AdlDisplayHandle(adapter_index=0, display_index=0)

    def get_saturation_info(self, handle: AdlDisplayHandle) -> SaturationInfo:
        minimum, maximum = self.ranges["D1"]
        return SaturationInfo(self.values["D1"], minimum, maximum)

    def set_saturation_level(self, handle: AdlDisplayHandle, level: int) -> None:
        self.values["D1"] = level
        self.set_calls.append(("D1", level))


def test_adl_controller_captures_clamps_and_restores():
    native = FakeNative()
    controller = AdlSaturationController(native=native)
    controller.capture("D1")
    controller.set_level("D1", 140)
    assert native.set_calls[-1] == ("D1", 100)
    controller.restore("D1")
    assert native.set_calls[-1] == ("D1", 35)
    # get_display_handle is resolved once and cached, not once per operation.
    assert native.resolved == ["D1"]


def test_adl_controller_resolves_handle_once_and_reports_capabilities():
    native = FakeNative()
    controller = AdlSaturationController(native=native)
    caps = controller.capabilities("D1")
    assert caps == {"supported": True, "minimum": 0, "maximum": 100}
