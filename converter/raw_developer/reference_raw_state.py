"""Recovered S5M2 host policies only; no RAW developer or complete WB model."""
import math

# Source uses MakerNote PHOTO_STYLE ids; target uses PANA_PHOTOSTYLE ids.
SOURCE_TO_TARGET = (2,3,4,5,6,7,9,10,12,8,11,1,1,13,14,15,16,17,18,19,20,21,22,23,24,25)
PRELUT_ADDRESSES = {50: 0x33bfc0, 64: 0x33d098, 80: 0x33e170}


def source_to_target(source):
    return SOURCE_TO_TARGET[source-2] if 2 <= source <= 27 else 1


def kelvin_position(kelvin):
    if not math.isfinite(kelvin) or kelvin <= 0:
        raise ValueError('Expected positive finite Kelvin')
    points = ((3000,256),(5000,512),(6500,618),(7500,725))
    index = 0 if kelvin < 5000 else 1 if kelvin < 6500 else 2
    (x0,y0),(x1,y1) = points[index:index+2]
    return int(max(0,min(65535,y0+(kelvin-x0)*(y1-y0)/(x1-x0))))


def style_weight(*, ctemp_tag=None, fallback_kelvin=None):
    """Initial readExif state. Later explicit Kelvin updates override position."""
    if ctemp_tag is not None:
        if not isinstance(ctemp_tag,int) or not 0 <= ctemp_tag <= 65535:
            raise ValueError('Invalid SHORT tag 0x011c')
        position = ctemp_tag
    elif fallback_kelvin is not None:
        position = kelvin_position(fallback_kelvin)
    else:
        raise ValueError('Missing tag and as-shot Kelvin; do not invent a default')
    return position, max(0.0,min(1.0,(position-256)/256))


def s5m2_style_policy(iso, source_style, target_style):
    """Camera ID 100 only, recovered GetPhotoStyleLUT selector.

    A curve name indicates which 49-knot table is needed, not the file ISO.
    Exact ISO comparisons are intentional: unlisted values do not interpolate.
    """
    if not isinstance(iso,int) or iso <= 0 or not 0 <= source_style <= 27 or not 1 <= target_style <= 25:
        raise ValueError('Outside observed S5M2 policy domain')
    mapping = {100:50,125:64,160:80} if source_style in (18,19,23) else {50:50,64:64,80:80}
    selected = mapping.get(iso)
    clip = {320:3300,400:3400,500:3496}.get(iso,3596) if target_style == 15 else 4095
    return {'prelut_iso_name':selected,'vlog_clip':clip,'photo_style_change_gain':1.0,
            'valid_tone_correct':int(selected is not None)}


def s5m2_wb_outputs(iso, source_style, rgb_levels, digital_gains=None):
    """GetWhiteBalance2 outputs for version >=0320, camera 100.

    This is NOT final shader WB/brightness or Kelvin/DBB conversion.
    The second gain output is G/256, optionally scaled 0.98 for low ISO.
    """
    if not isinstance(iso,int) or iso <= 0 or not 0 <= source_style <= 27:
        raise ValueError('Outside observed S5M2 WB domain')
    if len(rgb_levels)!=3 or any(not isinstance(x,int) or not 0<x<=65535 for x in rgb_levels):
        raise ValueError('Invalid RAW WB levels')
    levels=list(rgb_levels)
    if digital_gains is not None:
        if len(digital_gains)!=3 or any(not isinstance(x,int) or not 0<=x<=65535 for x in digital_gains):
            raise ValueError('Invalid digital gain tags')
        for i,gain in enumerate(digital_gains):
            if gain:
                product=levels[i]*gain
                if product>0x7fffffff: raise ValueError('Signed overflow outside research domain')
                levels[i]=product//256
    r,g,b=levels
    if g==0: raise ValueError('Zero corrected green level')
    threshold = 200 if source_style in (18,19) else 640 if source_style==17 else 100
    green_gain=g/256
    if source_style!=12 and iso<threshold: green_gain*=.98
    return (r/g,b/g,1.0,green_gain)


def s5m2_brightness_state(iso, source_style, base_gain, green_gain, pixel_max):
    """Later readExifAndUnpack adjustment, not final rendering exposure.

    GetWhiteBalance2 supplies base_gain=1 for S5M2, so the normal adjustment
    factor is 1. Non-unit inputs are useful for verifying the recovered math.
    """
    if not isinstance(iso, int) or iso <= 0 or not 0 <= source_style <= 27:
        raise ValueError('Outside observed S5M2 policy domain')
    if not all(math.isfinite(v) and v > 0 for v in (base_gain, green_gain)):
        raise ValueError('Expected finite positive gains')
    if not isinstance(pixel_max, int) or not 0 <= pixel_max <= 65535:
        raise ValueError('Invalid pixel maximum')
    bypass = source_style in (18,19,23) and iso < 200
    factor = 1.0 if bypass else max((1/base_gain+2)/3, .85)
    maximum = pixel_max if bypass else max(0,min(65535,math.ceil(pixel_max*factor-1e-10)))
    return factor, green_gain*factor, maximum


def relative_wb_for_cnv2(target_rgb_gains, as_shot_rgb_gains):
    """Traced non-flag-1 host branch: target R/B gains divided by as-shot R/B.

    Inputs must already be derived by the host WB model. This function does
    not implement Kelvin/DBB conversion or decide which branch is active.
    """
    from .reference_frontend import f32
    if len(target_rgb_gains)!=2 or len(as_shot_rgb_gains)!=2:
        raise ValueError('Expected R/B gain pairs')
    if any(not math.isfinite(v) or v<=0 for v in (*target_rgb_gains,*as_shot_rgb_gains)):
        raise ValueError('Positive finite WB gains required')
    return tuple(f32(target/base) for target,base in zip(target_rgb_gains,as_shot_rgb_gains))


def s5m2_cnv2_brightness(user_brightness, green_gain):
    """Normal RAW host: float32 UI exposure multiplied by float32 green gain."""
    from .reference_frontend import f32
    if any(not math.isfinite(v) or v<=0 for v in (user_brightness,green_gain)):
        raise ValueError('Positive finite brightness gains required')
    return f32(f32(user_brightness)*f32(green_gain))
