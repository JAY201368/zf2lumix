"""Independent model-9 NR parameter calculation, before GPU host packing.

Includes full-resolution fresh RAW UI routing and zero-level RPF packing.
Special format bypass and reset are excluded. Calibration retains provenance.
"""
from bisect import bisect_right
import json
import math
from pathlib import Path
from .reference_frontend import f32

_CURVES = json.loads(Path(__file__).with_name('nr-parameter-curves.json').read_text())['curves']
PARAMETER_NAMES = ('GammaL', 'LPFSigma4L', 'NRTL', 'SizeL', 'RetryMaxL',
                   'SumFactMinL', 'LPFSigma4C', 'NRTC', 'SizeC', 'RetryMaxC',
                   'SumFactMinC', 'DiffLPFSigma4L', 'DiffLPFT', 'SizeAvgAbsDiffL',
                   'FinalSigma4C')
INTEGER_PARAMETERS = {3, 4, 8, 9, 13}


def _curve(index, value):
    points = _CURVES[index]
    j = max(0, min(len(points)-2, bisect_right([p[0] for p in points], value)-1))
    x0, y0 = points[j]
    x1, y1 = points[j+1]
    # Mode 0 extrapolates; it does not clamp at the end points.
    return y0 + (value-x0)*(y1-y0)/(x1-x0)


def calculate_nr_parameters(iso, luminance, chroma, *, random_level=0, resolution=1):
    """Return the 15 pre-RPF outputs of CalcNRParam for explicit valid inputs."""
    values = (iso, luminance, chroma, random_level, resolution)
    if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        raise ValueError('NR parameter inputs must be integers')
    if not 1 <= iso <= 204800 or not 0 <= luminance <= 150 or not 0 <= chroma <= 150:
        raise ValueError('Unsupported ISO or NR level')
    if not 0 <= random_level <= 100 or not 1 <= resolution <= 16:
        raise ValueError('Unsupported random NR level or resolution')
    l = luminance + 2*random_level - 10
    c = chroma - 10
    sigma_l = min(_curve(7, iso)*_curve(0, l), 2.)
    sigma_c = min(_curve(12, iso)*_curve(4, c), 3.)
    sigma_diff = min(_curve(17, iso)*_curve(2, luminance-10), 2.)
    size_l = min(math.floor(_curve(9, iso)+.5), 64)
    size_c = min(math.floor(_curve(14, iso)+.5), 64)
    final_c = sigma_c
    if resolution >= 2:
        if size_l >= 1:
            size_l = max(1, math.floor(size_l/resolution+.5))
        if size_c >= 1:
            size_c = max(1, math.floor(size_c/resolution+.5))
        sigma_l /= resolution
        sigma_c /= resolution
        sigma_diff /= resolution
    result = (
        max(1., min(_curve(21, iso)*_curve(6, l), 4.)),
        sigma_l, min(_curve(8, iso)*_curve(1, l), .05), size_l,
        min(math.floor(_curve(10, iso)+.5), 10), min(int(_curve(11, iso)), 20),
        sigma_c, min(_curve(13, iso)*_curve(5, c), .1), size_c,
        min(math.floor(_curve(15, iso)+.5), 10), min(int(_curve(16, iso)), 20),
        sigma_diff, min(_curve(18, iso)*_curve(3, l), .03),
        min(math.floor(_curve(19, iso)+.5), 64), final_c)
    return {name: value if i in INTEGER_PARAMETERS else f32(value)
            for i, (name, value) in enumerate(zip(PARAMETER_NAMES, result))}


def pack_directional_parameters(parameters, *, pixel_max=4095, chroma_enabled=1):
    """Distinct third/fourth stage buffers, preserving host float32 rounding."""
    import struct
    p = parameters
    size_l, size_c = p['SizeL'], p['SizeC']
    step_l = max(1, min(int(f32(f32(p['LPFSigma4L'])*f32(2.3))), size_l))
    step_c = max(1, min(int(f32(f32(p['LPFSigma4C'])*f32(2.3))), size_c))
    threshold_l = min(math.ceil(f32(f32(pixel_max)*f32(p['NRTL']))), 4095)
    threshold_c = min(math.ceil(f32(f32(pixel_max)*f32(p['NRTC']))), 4095)
    third = (pixel_max, threshold_l, 1, min(size_l, max(2*step_l, size_l//3)),
             step_l, p['RetryMaxL'], threshold_c, 1, chroma_enabled,
             min(size_c, max(2*step_c, size_c//3)), step_c, p['RetryMaxC'],
             p['SumFactMinL'], p['SumFactMinC'])
    fourth = (pixel_max, threshold_l//2, threshold_l//2, size_l,
              max(1, min(3*step_l-1, size_l)), min(1, p['RetryMaxL']),
              threshold_c//2, threshold_c//2, chroma_enabled, size_c,
              max(1, min(3*step_c-1, size_c)), min(1, p['RetryMaxC']),
              p['SumFactMinL'], p['SumFactMinC'])
    return tuple(struct.pack('<f11i2f', *v) for v in (third, fourth))


def nr_gaussian_weights(sigma):
    """Positive-sigma 2D host kernel, with original size/float32 reduction.

    Zero/negative sigma invokes a different host fallback and is not accepted.
    Returns (odd side, row-major normalized float32 weights).
    """
    if not math.isfinite(sigma) or not .01 <= sigma <= 4:
        raise ValueError('Gaussian sigma outside audited positive domain')
    sigma = f32(sigma)
    inverse = 1. / (2. * sigma * sigma)
    total = 1.
    radius = 1
    while True:
        value = math.pow(math.e, -float(radius*radius)*inverse)
        if value < total*1e-10:
            break
        total += 2.*value
        radius += 1
    radius -= 1
    side = 2*radius+1
    inverse = float(f32(1./f32(f32(sigma+sigma)*sigma)))
    weights = [f32(math.pow(math.e,-float(x*x+y*y)*inverse))
               for y in range(-radius,radius+1) for x in range(-radius,radius+1)]
    total = 0.
    for value in weights:
        total = f32(total+value)
    return side, [f32(value/total) for value in weights]


def pack_second_parameters(*, pixel_max, side_l, side_c, chroma_enabled,
                           rpf_sizes, over_rpf, over_hlpf):
    """Second host buffer; maximum is overwritten with the caller's value."""
    import struct
    return struct.pack('<f8i', pixel_max, *rpf_sizes, side_l, chroma_enabled,
                       side_c, over_rpf, over_hlpf)


def pack_fifth_parameters(*, pixel_max, gamma, abs_size, abs_max, side_l,
                          side_c, chroma_enabled, cb_gain, cr_gain):
    """Final host buffer, taking already-computed threshold and inverse gains."""
    import struct
    return struct.pack('<2f5i2f', pixel_max, gamma, abs_size, abs_max, side_l,
                       chroma_enabled, side_c, cb_gain, cr_gain)


def nr_luminance_gains():
    """Fixed host cross-product normalization; these are not standard YCbCr."""
    b, r = f32(3.8203125), f32(1.4140625)
    g = f32(b*r)
    scale = f32(1./f32(f32(b+g)+r))
    return tuple(f32(v*scale) for v in (b,g,r))


def nr_encoded_luminance(bgr, *, pixel_max, gamma, gains=None):
    """Host threshold helper, preserving powf and intermediate float32 values."""
    import ctypes
    if gains is None:
        gains = nr_luminance_gains()
    if pixel_max <= 0 or gamma <= 0 or any(v < 0 for v in bgr):
        raise ValueError('Positive maximum/gamma and nonnegative samples required')
    values = [f32(f32(v)*f32(g)) for v,g in zip(bgr,gains)]
    value = f32(f32(values[0]+values[1])+values[2])
    gamma = f32(gamma)
    if gamma != 1.:
        x = f32(value/f32(pixel_max))
        exponent = f32(1./gamma)
        powf = ctypes.CDLL(None).powf
        powf.argtypes = [ctypes.c_float,ctypes.c_float]
        powf.restype = ctypes.c_float
        power = powf(x,exponent)
        linear = f32(x*8.)
        value = f32((max(power,linear) if exponent>1. else min(power,linear))*f32(pixel_max))
    return int(value)


def nr_abs_threshold(parameters, *, pixel_max=4095):
    """Final reconstruction threshold includes the entire difference window."""
    white = nr_encoded_luminance((pixel_max,)*3,pixel_max=pixel_max,gamma=parameters['GammaL'])
    side = f32(2*parameters['SizeAvgAbsDiffL']+1)
    area_scaled_white = f32(f32(f32(white)*side)*side)
    return int(f32(f32(parameters['DiffLPFT'])*area_scaled_white))


def nr_inverse_gains():
    """Green reconstruction coefficients for the fixed normalized host matrix."""
    b, _, r = nr_luminance_gains()
    return f32(-2*b), f32(-2*r)


def nr_zero_rpf_parameters(gamma, *, pixel_max=4095):
    """Full-resolution RPF-level-0 calibration and its host threshold packing.

    Level zero does not zero the calibration: the original returns .8,1,.2,.2.
    The size-1 windows are retained rather than assuming this stage is disabled.
    """
    threshold,over,hlpf = f32(.8),f32(.2),f32(.2)
    base = min(f32(f32(pixel_max)*threshold),f32(pixel_max))
    limit = nr_encoded_luminance((base,)*3,pixel_max=pixel_max,gamma=gamma)
    def factor(value):
        boundary = f32(f32(pixel_max)*f32(f32(threshold+value)/threshold))
        delta = nr_encoded_luminance((boundary,)*3,pixel_max=pixel_max,gamma=gamma)-limit
        return 16384//delta
    return dict(rpf_sizes=(1,1,1),limit=limit,over_rpf=factor(over),over_hlpf=factor(hlpf))


def normal_raw_nr_buffers(iso, ui_value, *, pixel_max=4095):
    """Full-resolution normal RAW edit branch; no format bypass/reset handling."""
    import struct
    from .reference_detail import raw_nr_settings
    settings=raw_nr_settings(ui_value)
    p=calculate_nr_parameters(iso,settings['luminance'],settings['chroma'])
    sl,wl=nr_gaussian_weights(p['LPFSigma4L'])
    sc,wc=nr_gaussian_weights(p['LPFSigma4C'])
    rpf=nr_zero_rpf_parameters(p['GammaL'],pixel_max=pixel_max)
    cb,cr=nr_inverse_gains()
    third,fourth=pack_directional_parameters(p,pixel_max=pixel_max,chroma_enabled=1)
    buffers=dict(first=struct.pack('<5f2i',pixel_max,*nr_luminance_gains(),p['GammaL'],rpf['rpf_sizes'][0],rpf['limit']),
                 second=pack_second_parameters(pixel_max=pixel_max,side_l=sl,side_c=sc,chroma_enabled=1,
                                               rpf_sizes=rpf['rpf_sizes'],over_rpf=rpf['over_rpf'],over_hlpf=rpf['over_hlpf']),
                 hlpf=struct.pack('<f',pixel_max),third=third,fourth=fourth,
                 fifth=pack_fifth_parameters(pixel_max=pixel_max,gamma=p['GammaL'],abs_size=p['SizeAvgAbsDiffL'],
                     abs_max=nr_abs_threshold(p,pixel_max=pixel_max),side_l=sl,side_c=sc,chroma_enabled=1,cb_gain=cb,cr_gain=cr),
                 weightsL=struct.pack('<'+'f'*len(wl),*wl),weightsC=struct.pack('<'+'f'*len(wc),*wc))
    return buffers,dict(ui_value=ui_value,iso=iso,settings=settings,parameters=p,rpf=rpf,gaussian_sides=[sl,sc],
                        forward_gains=nr_luminance_gains(),inverse_gains=(cb,cr))
