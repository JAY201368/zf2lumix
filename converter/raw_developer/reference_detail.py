"""UI-to-kernel detail settings; original app's format-based bypass is separate."""
import math
from .reference_frontend import f32


def _ui(value):
    if not math.isfinite(value) or not 0<=value<=100:
        raise ValueError('Detail setting must be finite and in [0,100]')
    return f32(value)


def _round4(value):
    return f32(math.floor(f32(value*10000)+.5)/10000)


def sharpness_factor(value):
    return _round4(f32(_ui(value)/100))


def noise_reduction_level(value):
    value=_ui(value)
    # Preserve the original floating point divide/multiply order.
    if value>50:
        value=f32(f32(f32(f32(value-50)/50)*100)+50)
    else:
        value=f32(f32(value/50)*50)
    return int(_round4(value))


def raw_nr_settings(value):
    """Normal RAW edit path from a fresh edit-value record.

    The UI NR slider changes luminance only. Chroma and RPF retain zero from
    the record initializer; validCromaNR is enabled by normal edit conversion.
    Format-specific bypass and the all-effects reset path are excluded.
    """
    return dict(luminance=noise_reduction_level(value),chroma=0,rpf=0,
                chroma_enabled=True,random_level=0)
