"""Recovered yccBlurH/V and yccCNR kernels; explicit host parameters only.

First/third uint16 fields carry biased G-B/G-R until the final conversion.
No standard YCbCr coefficients or assumed Lab default strengths are used.
"""
import math
from .reference_frontend import f32


def _validate(pixels,width,height):
    if not all(isinstance(v,int) and v>0 for v in (width,height)) or len(pixels)!=width*height:
        raise ValueError('Invalid dimensions')
    if any(len(p)!=3 or any(not isinstance(v,int) or not 0<=v<=65535 for v in p) for p in pixels):
        raise ValueError('Expected three uint16 fields')


def blur(pixels,width,height,params,*,vertical=False):
    _validate(pixels,width,height)
    a,b,c,blur_green,strength,radius,divisor=params
    if any(not math.isfinite(v) or v<0 for v in (a,b,c)) or abs(a+b+c-1)>1e-6:
        raise ValueError('Only nonnegative normalized blur weights audited')
    if radius not in range(1,33) or divisor!=radius*2+1 or not 0<=strength<=256 or blur_green not in (0,1):
        raise ValueError('Outside audited blur parameter domain')
    def at(x,y):return pixels[max(0,min(height-1,y))*width+max(0,min(width-1,x))]
    result=[]
    for y in range(height):
        for x in range(width):
            sample=lambda k:at(x,y+k) if vertical else at(x+k,y)
            center=sample(0);green=center[1]
            if blur_green:
                green=int(f32(f32(f32(a*sample(-1)[1])+f32(b*green))+f32(c*sample(1)[1])))
            if strength>0:
                chroma=[sum(sample(k)[channel] for k in range(-radius,radius+1))//divisor for channel in (0,2)]
            elif vertical:
                chroma=[max(0,min(65535,green+32768-center[channel])) for channel in (0,2)]
            else:chroma=[center[0],center[2]]
            result.append((chroma[0],green,chroma[1]))
    return result


def chroma_finish(filtered,original,width,height,*,strength,step):
    _validate(filtered,width,height);_validate(original,width,height)
    if not isinstance(strength,int) or not 0<=strength<=256 or step not in range(1,33):
        raise ValueError('Outside audited CNR domain')
    def at(x,y):return filtered[max(0,min(height-1,y))*width+max(0,min(width-1,x))]
    result=[]
    for y in range(height):
        for x in range(width):
            center=at(x,y);total=[2*center[0],2*center[2]];count=2
            for dx,dy in ((step,0),(2*step,0),(3*step,0),(0,step),(0,2*step),(0,3*step)):
                left,right=at(x-dx,y-dy),at(x+dx,y+dy)
                pair=[left[c]+right[c] for c in (0,2)]
                if sum(abs(pair[i]-2*center[c]) for i,c in enumerate((0,2)))<256:
                    total=[a+b for a,b in zip(total,pair)];count+=2
            output=[]
            for i,c in enumerate((0,2)):
                local=total[i]//count-32768
                previous=original[y*width+x][c]-32768
                delta=((256-strength)*previous+strength*local)>>8
                output.append(max(0,min(65535,center[1]-delta)))
            result.append((output[0],center[1],output[1]))
    return result


def host_blur_params(sigma,blur_green,strength,radius):
    """Recovered host Gaussian packing; expf supplied by the system C library.

    The single final field is 2*radius+1. When reused by CNR it is a sampling
    step, not an independently chosen radius. UI defaults remain unproven.
    """
    import ctypes
    import ctypes.util
    if not math.isfinite(sigma) or not .01<=sigma<=100:
        raise ValueError('Sigma outside audited domain')
    if blur_green not in (0,1) or strength not in range(257) or radius not in range(1,16):
        raise ValueError('Host parameters outside audited domain')
    sigma=f32(sigma)
    exponent=f32(-f32(1/f32(f32(2*sigma)*sigma)))
    lib=ctypes.CDLL(ctypes.util.find_library('m') or None)
    expf=lib.expf;expf.argtypes=[ctypes.c_float];expf.restype=ctypes.c_float
    side=expf(exponent)
    total=f32(f32(side+1)+side)
    return (f32(side/total),f32(1/total),f32(side/total),blur_green,strength,radius,2*radius+1)


def normal_raw_chroma_params():
    """Fresh neutral edit record: no HSL blur, independent chroma strength 192."""
    return host_blur_params(2.,0,192,5)
