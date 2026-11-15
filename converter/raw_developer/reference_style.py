"""Research reference for recovered shader stages, NOT a RAW developer.

Input is normalized RGB at the shader's style entry, not display sRGB.
Host-side RAW transforms, metadata and style-table preparation remain separate.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import struct


@dataclass(frozen=True)
class StyleTable:
    kind: int
    size: int
    name: str
    values: tuple


def read_psl1(path):
    data = Path(path).read_bytes()
    if len(data) < 88 or data[:4] != b'PSL1':
        raise ValueError('Not a complete PSL1 resource')
    kind = data[4]
    size = int.from_bytes(data[5:9], 'little')
    if (kind, size) not in ((0, 2048), (1, 33)):
        raise ValueError('Unsupported PSL1 kind/size; only observed 3.1.0 layouts supported')
    if data[9] != 1:
        raise ValueError('Only observed half-float PSL1 encoding supported')
    count = size if kind == 0 else size ** 3 * 3
    if len(data) != 88 + count * 2:
        raise ValueError('PSL1 payload length mismatch')
    values = struct.unpack('<' + 'e' * count, data[88:])
    if not all(math.isfinite(x) for x in values):
        raise ValueError('Non-finite PSL1 payload')
    return StyleTable(kind, size, data[10:74].split(b'\0')[0].decode('utf-8'), values)


def clamp(x, upper=1.0):
    return max(0.0, min(upper, x))


def curve(x, values):
    """Linear sample; upper endpoint uses the last segment with fraction 1."""
    if not math.isfinite(x) or not 0 <= x <= 1 or len(values) < 2:
        raise ValueError('Curve input must be finite and within [0,1]')
    position = x * (len(values) - 1)
    i = min(int(position), len(values) - 2)
    t = position - i
    return values[i] + (values[i + 1] - values[i]) * t


def cube(rgb, values, size=33):
    """Interleaved RGB, R-fastest; trilinear, without output clipping."""
    if len(values) != size ** 3 * 3 or size < 2:
        raise ValueError('Cube shape mismatch')
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in rgb) or len(rgb) != 3:
        raise ValueError('Cube input must be finite RGB within [0,1]')
    p = [v * (size - 1) for v in rgb]
    i = [min(int(v), size - 2) for v in p]
    f = [v - j for v, j in zip(p, i)]
    out = [0.0, 0.0, 0.0]
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                at = ((i[2] + db) * size * size + (i[1] + dg) * size + i[0] + dr) * 3
                weight = math.prod(t if d else 1 - t for t, d in zip(f, (dr, dg, db)))
                for c in range(3):
                    out[c] += weight * values[at + c]
    return tuple(out)


def apply_style(rgb, gamma, correction, *, vlog_clip=4095, colorspace=0, tone=None):
    """Recovered ApplyPhotoStyleLut with bValidPhotoStyle=1.

    colorspace is the observed integer shader branch, not an ICC/profile name.
    tone black is rejected: original IR divides corrected luminance by zero.
    """
    if len(gamma) != 2048 or not 0 <= vlog_clip <= 4095:
        raise ValueError('Invalid style parameters')
    r, g, b = (clamp(v) for v in rgb)
    if colorspace == 2:
        r += (-0.33984375 if r >= g else -0.46484375) * (r - g) + (0.0234375 if r >= b else 0.03125) * (r - b)
        g += (0.10546875 if g >= r else 0.01171875) * (g - r)
        b += -0.0078125 * (b - r) + (-0.04296875 if b >= g else -0.08984375) * (b - g)
    if tone is not None:
        if len(tone) != 2048:
            raise ValueError('Tone correction requires 2048 entries')
        y = 0.299 * r + 0.587 * g + 0.114 * b
        if y <= 0:
            raise ValueError('Original tone correction black behavior is undefined; not emulated')
        gain = curve(y, tone) / y
        r, g, b = (clamp(v * gain) for v in (r, g, b))
    shaped = tuple(clamp(curve(v, gamma)) for v in (r, g, b))
    return tuple(clamp(v, vlog_clip / 4095.0) for v in cube(shaped, correction))


def apply_dual(rgb, first, strength1, second, strength2):
    """backendProcess48 ordering: blend and saturate after EACH active LUT."""
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in (strength1, strength2)):
        raise ValueError('Strength outside [0,1]')
    value = tuple(clamp(x) for x in rgb)
    for table, strength in ((first, strength1), (second, strength2)):
        if strength > 0:
            result = cube(value, table)
            value = tuple(clamp(strength * v + (1 - strength) * old)
                          for v, old in zip(result, value))
    return value
