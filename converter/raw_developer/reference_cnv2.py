"""cnv2Process neutral-adjustment branch, with explicit research parameters.

This does not infer Lab host defaults. Shading, saturation matrices, HSL and
split toning are disabled explicitly; those branches are not implemented here.
Output is 12-bit BGR stored in uint16, or the original biased difference layout.
"""
import math
import struct
from .reference_frontend import f32
from .reference_style import apply_style, clamp


def pack_neutral_params(*, pixel_max, brightness, wb_r, wb_b, style_enabled,
                        vlog_clip=4095, colorspace=0, tone_enabled=False, valid_ycc=False):
    if not all(math.isfinite(v) and v>0 for v in (pixel_max,brightness,wb_r,wb_b)):
        raise ValueError('Positive finite normalization/gains required')
    if not 0<=vlog_clip<=4095 or colorspace not in (0,1,2):
        raise ValueError('Unsupported style parameters')
    data=bytearray(352)
    for offset,value in ((0,brightness),(4,wb_r),(8,wb_b),(20,1),(24,1),(60,pixel_max)):
        struct.pack_into('<f',data,offset,value)
    for offset,value in ((44,int(tone_enabled)),(48,vlog_clip),(52,colorspace),
                         (56,int(style_enabled)),(172,int(valid_ycc))):
        struct.pack_into('<I',data,offset,value)
    # Unused in the neutral branch; initialize deterministically.
    for base in (64,112):
        for i in range(3):struct.pack_into('<f',data,base+16*i+4*i,1)
    return bytes(data)


def cnv2_neutral(bgr, *, pixel_max, brightness, wb_r, wb_b, gamma=None,
                 correction=None, vlog_clip=4095, colorspace=0, tone=None, valid_ycc=False):
    if len(bgr)!=3 or any(not isinstance(v,int) or not 0<=v<=65535 for v in bgr):
        raise ValueError('Expected uint16 BGR')
    if (gamma is None)!=(correction is None):raise ValueError('Both style tables required')
    pack_neutral_params(pixel_max=pixel_max,brightness=brightness,wb_r=wb_r,wb_b=wb_b,
                        style_enabled=gamma is not None,vlog_clip=vlog_clip,colorspace=colorspace)
    rgb=tuple(clamp(f32(clamp(f32(f32(v/f32(pixel_max))*f32(gain)))*f32(brightness)))
              for v,gain in zip(reversed(bgr),(wb_r,1,wb_b)))
    if gamma is not None:
        rgb=apply_style(rgb,gamma,correction,vlog_clip=vlog_clip,colorspace=colorspace,tone=tone)
    r,g,b=(int(f32(v*4095)) for v in rgb)
    return (((g-b)&65535)^32768,g,((g-r)&65535)^32768) if valid_ycc else (b,g,r)
