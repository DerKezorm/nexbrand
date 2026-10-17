"""Colour arithmetic: WCAG contrast, CIEDE2000 distance, colour vision, CMYK, web scales.

The same numbers as ``frontend/src/lib/color.ts``; ``tests/test_colors.py`` and ``color.test.ts`` both check them
against ``tests/data/color_cases.json``, so the interface and the server never disagree about a pair.
"""

from __future__ import annotations

import math
import re

Rgb = tuple[float, float, float]


def _round(value: float) -> int:
    """Half up, as JavaScript's ``Math.round``; Python's own ``round`` goes to even and would part ways at x.5."""
    return math.floor(value + 0.5)


def rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def to_hex(color: Rgb) -> str:
    return "#" + "".join(f"{_round(min(255.0, max(0.0, channel))):02X}" for channel in color)


def _linear(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _gamma(channel: float) -> float:
    return 255 * (12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055)


def luminance(value: str) -> float:
    r, g, b = (_linear(c) for c in rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def shown_ratio(ratio: float) -> float:
    """A contrast ratio as it is shown: cut, never rounded up, to two places (one from 10:1). 4.4992 is shown as
    4.49, not as 4.50 beside "fails": a ratio shown at or above a threshold has reached it."""
    places = 10 if ratio >= 10 else 100
    return math.floor(ratio * places + 1e-9) / places


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_HEX_TEXT = re.compile(r"#?([0-9a-f]{3}|[0-9a-f]{6})|#([0-9a-f]{4}|[0-9a-f]{8})", re.ASCII)
_FUNCTION = re.compile(r"(rgba?|hsla?)\(\s*([^()]*?)\s*\)", re.ASCII)
_PART = re.compile(rf"({_NUMBER})(%|deg)?", re.ASCII)
#: Spaces as CSS knows them, nothing else: ``str.strip`` would also take ``\x1c`` and a no-break space, which the
#: browser keeps (the same in ``lib/color.ts``).
_SPACE = " \t\n\r\f\v"


def _parts(text: str) -> list[tuple[float, str]] | None:
    """The values inside ``rgb(…)`` or ``hsl(…)``: three, by commas or spaces, an alpha after ``/`` or a fourth comma
    left out."""
    body, _, _alpha = text.partition("/")
    items = [item for item in re.split(r"\s*,\s*|\s+", body.strip(_SPACE), flags=re.ASCII) if item]
    if len(items) == 4 and "," in body:
        items = items[:3]
    if len(items) != 3:
        return None
    out = []
    for item in items:
        match = _PART.fullmatch(item)
        if match is None:
            return None
        out.append((float(match.group(1)), match.group(2) or ""))
    return out


def parse(value: object) -> str | None:
    """A colour as people and style sheets write it, as ``#RRGGBB``: ``#RGB``, ``#RRGGBB`` (and with alpha, which is
    left out), the same without ``#``, ``rgb()``/``rgba()`` and ``hsl()``/``hsla()`` with commas or spaces. ``None``:
    not a colour read here (a name such as ``red`` neither). The same as ``parseColor`` in ``lib/color.ts``."""
    if not isinstance(value, str):
        return None
    text = value.strip(_SPACE).lower()
    if len(text) > 80:
        return None
    hexed = _HEX_TEXT.fullmatch(text)
    if hexed:
        digits = hexed.group(1) or hexed.group(2)
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits[:3])
        return "#" + digits[:6].upper()
    function = _FUNCTION.fullmatch(text)
    if function is None:
        return None
    parts = _parts(function.group(2))
    if parts is None:
        return None
    if function.group(1).startswith("rgb"):
        if any(unit == "deg" for _, unit in parts):
            return None
        channels = [number * 2.55 if unit == "%" else number for number, unit in parts]
        if any(channel < 0 or channel > 255 for channel in channels):
            return None
        return to_hex((channels[0], channels[1], channels[2]))
    (hue, hue_unit), (saturation, s_unit), (light, l_unit) = parts
    if hue_unit == "%" or s_unit == "deg" or l_unit == "deg" or not (0 <= saturation <= 100 and 0 <= light <= 100):
        return None
    return from_hsl(hue % 360, saturation, light)


def grade(ratio: float, large: bool = False) -> str:
    """WCAG 2.2 for text: ``AAA``, ``AA``, ``AA large`` (only for large text) or ``fail``."""
    if large:
        return "AAA" if ratio >= 4.5 else "AA" if ratio >= 3 else "fail"
    return "AAA" if ratio >= 7 else "AA" if ratio >= 4.5 else "AA large" if ratio >= 3 else "fail"


def text_on(ground: str, dark: str = "#14141A") -> str:
    return "#FFFFFF" if contrast(ground, "#FFFFFF") >= contrast(ground, dark) else dark


def hsl(value: str) -> tuple[int, int, int]:
    r, g, b = (c / 255 for c in rgb(value))
    high, low = max(r, g, b), min(r, g, b)
    delta = high - low
    hue = 0.0
    if delta:
        if high == r:
            hue = ((g - b) / delta) % 6
        elif high == g:
            hue = (b - r) / delta + 2
        else:
            hue = (r - g) / delta + 4
    hue = (hue * 60 + 360) % 360
    light = (high + low) / 2
    saturation = delta / (1 - abs(2 * light - 1)) if delta else 0.0
    return _round(hue), _round(saturation * 100), _round(light * 100)


def from_hsl(hue: float, saturation: float, light: float) -> str:
    saturation /= 100
    light /= 100

    def channel(n: int) -> float:
        k = (n + hue / 30) % 12
        a = saturation * min(light, 1 - light)
        return light - a * max(-1, min(k - 3, min(9 - k, 1)))

    return to_hex((channel(0) * 255, channel(8) * 255, channel(4) * 255))


def cmyk(value: str) -> tuple[int, int, int, int]:
    """Computed without a print profile; the interface says so wherever it shows it."""
    r, g, b = (c / 255 for c in rgb(value))
    k = 1 - max(r, g, b)
    if k >= 1:
        return 0, 0, 0, 100
    return (_round((1 - r - k) / (1 - k) * 100), _round((1 - g - k) / (1 - k) * 100),
            _round((1 - b - k) / (1 - k) * 100), _round(k * 100))


def _lab(value: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in rgb(value))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a: str, b: str) -> float:
    """CIEDE2000: below 1 nobody sees it, below about 5 it reads as the same colour slightly off."""
    l1, a1, b1 = _lab(a)
    l2, a2, b2 = _lab(b)
    rad = math.pi / 180
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cm**7 / (cm**7 + 25**7)))
    a1p = (1 + g) * a1
    a2p = (1 + g) * a2
    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)

    def hue(bb: float, ap: float) -> float:
        if bb == 0 and ap == 0:
            return 0.0
        value = math.atan2(bb, ap) / rad
        return value + 360 if value < 0 else value

    h1p = hue(b1, a1p)
    h2p = hue(b2, a2p)
    dlp = l2 - l1
    dcp = c2p - c1p
    dhp = 0.0
    if c1p * c2p != 0:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(dhp / 2 * rad)
    lpm = (l1 + l2) / 2
    cpm = (c1p + c2p) / 2
    hpm = h1p + h2p
    if c1p * c2p != 0:
        if abs(h1p - h2p) > 180:
            hpm = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
        else:
            hpm = (h1p + h2p) / 2
    t = (1 - 0.17 * math.cos((hpm - 30) * rad) + 0.24 * math.cos(2 * hpm * rad)
         + 0.32 * math.cos((3 * hpm + 6) * rad) - 0.2 * math.cos((4 * hpm - 63) * rad))
    d_theta = 30 * math.exp(-(((hpm - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cpm**7 / (cpm**7 + 25**7))
    sl = 1 + 0.015 * (lpm - 50) ** 2 / math.sqrt(20 + (lpm - 50) ** 2)
    sc = 1 + 0.045 * cpm
    sh = 1 + 0.015 * cpm * t
    rt = -math.sin(2 * d_theta * rad) * rc
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp_big / sh) ** 2 + rt * (dcp / sc) * (dhp_big / sh))


VISIONS = ("normal", "deutan", "protan", "tritan", "achromat")

# Machado, Oliveira, Fernandes 2009, full severity, applied in linear RGB.
_MATRICES = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.01182, 0.04294, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.3039)),
}


def simulate(value: str, vision: str) -> str:
    if vision == "normal":
        return value.upper()
    lin = [_linear(c) for c in rgb(value)]
    if vision == "achromat":
        grey = _gamma(0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2])
        return to_hex((grey, grey, grey))
    matrix = _MATRICES[vision]
    out = [min(1.0, max(0.0, sum(row[i] * lin[i] for i in range(3)))) for row in matrix]
    return to_hex((_gamma(out[0]), _gamma(out[1]), _gamma(out[2])))


def reach(fg: str, bg: str, target: float) -> str | None:
    """The nearest colour of the same hue that reaches ``target`` on ``bg``: darker or lighter, whichever first."""
    if contrast(fg, bg) >= target:
        return fg.upper()
    r, g, b = rgb(fg)
    for step in range(1, 101):
        part = step / 100
        darker = to_hex((r * (1 - part), g * (1 - part), b * (1 - part)))
        if contrast(darker, bg) >= target:
            return darker
        lighter = to_hex((r + (255 - r) * part, g + (255 - g) * part, b + (255 - b) * part))
        if contrast(lighter, bg) >= target:
            return lighter
    return None


STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
_STEP_LIGHT = (97, 93, 85, 75, 64, 54, 45, 37, 29, 21, 13)


def scale(value: str) -> list[tuple[int, str]]:
    """A web scale from 50 to 950 around one colour: the same hue, lightness in fixed steps, a little less colour at
    the ends."""
    hue, saturation, _ = hsl(value)
    out = []
    for step, light in zip(STEPS, _STEP_LIGHT, strict=True):
        sat = _round(saturation * (0.75 if light > 90 or light < 20 else 1))
        out.append((step, from_hsl(hue, sat, light)))
    return out
