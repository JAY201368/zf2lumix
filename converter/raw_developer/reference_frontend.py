"""Recovered RAW front-end stages; not a complete RAW decoder/developer.

CPU log quantization is NOT bit-equivalent to Metal: real RW2 patches expose
one-code differences amplified by adaptive demosaic (up to 379 in the tested
chain). See reference_frontend.metal and raw-patches-verification.json.

Input to front_end is ALREADY black-subtracted, cropped RGGB uint16 Bayer.
The host's optical-black arguments must be supplied explicitly: metadata tag
values have not yet been proven to reach those Swift arguments unchanged.
"""
import math
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def subtract_decode_black(samples, black_green):
    """Decode's strip placement subtracts the SAME G black level at all sites."""
    if not isinstance(black_green, int) or not 0 <= black_green <= 65535:
        raise ValueError('Invalid green black level')
    if any(not isinstance(v, int) or not 0 <= v <= 65535 for v in samples):
        raise ValueError('Expected uint16 samples')
    return [max(0, v-black_green) for v in samples]


def crop_bayer(samples, width, height, left, top, crop_width, crop_height):
    """Valid-domain GetRAWData16 copy, with stricter bounds for our reference."""
    if any(not isinstance(v, int) for v in (width,height,left,top,crop_width,crop_height)):
        raise ValueError('Integer dimensions required')
    if (min(width,height,crop_width,crop_height) <= 0 or min(left,top) < 0
            or left%2 or top%2 or left+crop_width > width or top+crop_height > height
            or len(samples) != width*height):
        raise ValueError('Invalid even-origin Bayer crop')
    return [v for y in range(top,top+crop_height)
            for v in samples[y*width+left:y*width+left+crop_width]]


def front_end_params(wb_r, wb_b, optical_black, sampling_max, valid_clip):
    if not all(math.isfinite(v) and 0 < v <= 65535 for v in (wb_r,wb_b)):
        raise ValueError('WB gains outside reference domain')
    if len(optical_black) != 3 or len(sampling_max) != 3:
        raise ValueError('Expected three channel values')
    if any(not isinstance(v,int) or not 0 <= v <= 65535 for v in (*optical_black,*sampling_max)):
        raise ValueError('Channel levels outside reference domain')
    maxima = [f32(a-b) for a,b in zip(sampling_max,optical_black)]
    if valid_clip not in (0,1) or (valid_clip and min(maxima) < 0):
        raise ValueError('Unsupported clipping state')
    log_epsilon = f32(math.log(819.0))
    scale = f32(4095.0/f32(f32(math.log(17199.0))-log_epsilon))
    return (819.0,log_epsilon,scale,f32(wb_r),f32(wb_b),valid_clip,*maxima)


def pack_params(params):
    return struct.pack('<5fI3f',*params)


def front_end(samples, width, params):
    if not isinstance(width,int) or width <= 0 or len(samples)%width:
        raise ValueError('Invalid Bayer dimensions')
    epsilon,log_epsilon,scale,wr,wb,valid_clip,mr,mg,mb = params
    result = []
    for i,value in enumerate(samples):
        if not isinstance(value,int) or not 0 <= value <= 65535:
            raise ValueError('Expected uint16 samples')
        site = ((i//width)%2)*2+(i%width)%2
        gain = wr if site == 0 else wb if site == 3 else 1.0
        maximum = mr if site == 0 else mb if site == 3 else mg
        level = f32(value*gain)
        if valid_clip == 1:
            level = min(level,maximum)
        argument = f32(level+epsilon)
        if argument <= 0:
            raise ValueError('Logarithm outside reference domain')
        log_value = f32(math.log(argument))
        encoded = math.floor(f32(f32(f32(log_value-log_epsilon)*scale)+.5))
        result.append(max(0,min(65535,encoded)))
    return result
