"""Distortion-only research path; no chromatic aberration or lens shading."""
from bisect import bisect_right
import ctypes
import math
import struct
from .reference_frontend import f32

_fma = ctypes.CDLL(None).fma
_fma.argtypes = [ctypes.c_double]*3
_fma.restype = ctypes.c_double


def distortion_rate(coefficients):
    """getLensRate: inverse radial displacement sampled at 101 radii."""
    if len(coefficients)!=4 or any(not -32768<=v<=32767 for v in coefficients):
        raise ValueError('Expected four signed 16-bit coefficients')
    g0,g2,g4,g6=(v/32768 for v in coefficients)
    scale=1/(1+g0);points=[(0.,0.)]
    previous=0.
    for i in range(1,101):
        r=i*4/100;r2=r*r;r4=r2*r2;r6=r2*r4
        radius=r*_fma(g6,r6,_fma(g4,r4,_fma(g2,r2,1.)))*scale
        points.append((radius,(r-radius)/radius))
        if radius>2 or previous>=radius:
            # Original count excludes the terminating point.
            points.pop();break
        previous=radius
    if len(points)<2:raise ValueError('Unsupported non-monotonic distortion curve')
    points.sort();xx=[x for x,y in points];out=[]
    for i in range(101):
        value=i/100;j=max(0,min(len(points)-2,bisect_right(xx,value)-1))
        x0,y0=points[j];x1,y1=points[j+1]
        out.append(f32(y0+(value-x0)*(y1-y0)/(x1-x0)))
    return out


def pack_lens(width,height,*,pixel_max=4095,offset_y=0):
    cx=f32(width/2);cy=f32(height/2)
    radius=f32(math.sqrt(f32(f32(cx*cx)+f32(cy*cy))))
    return struct.pack('<ifi8fi',offset_y,pixel_max,1,0.,0.,0.,0.,cx,cy,radius,1.,0)


def aberration_rates(blob,width,height):
    """Two 1024-entry CA tables; width/height are the host active rectangle.

    This helper does not infer the camera-specific active rectangle.
    """
    if len(blob)!=64 or blob[29]!=1:raise ValueError('Enabled 64-byte aberration metadata required')
    if width<=0 or height<=0:raise ValueError('Positive active dimensions required')
    radius=math.sqrt(float(width)*width+float(height)*height)*.5
    distances=[struct.unpack_from('<H',blob,i)[0] for i in (34,32,8,22)]
    if any(d<=0 for d in distances) or distances!=sorted(set(distances)):
        raise ValueError('Expected four increasing positive CA radii')
    tables=[]
    for offsets in ((24,46,16,52),(54,20,40,58)):
        values=[struct.unpack_from('<h',blob,i)[0] for i in offsets]
        points=[(0.,0.)]+[(d/radius,(v/-1000.)/d) for d,v in zip(distances,values)]
        xx=[q[0] for q in points];table=[]
        for i in range(1024):
            x=i/1024.;j=max(0,min(len(points)-2,bisect_right(xx,x)-1))
            x0,y0=points[j];x1,y1=points[j+1]
            table.append(f32(y0+(x-x0)*(y1-y0)/(x1-x0)))
        tables.append(table)
    return tuple(tables)
