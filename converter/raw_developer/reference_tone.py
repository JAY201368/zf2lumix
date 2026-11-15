"""Recovered low-ISO precurve sampling from explicit 49-point uint16 tables."""
from bisect import bisect_right
from .reference_frontend import f32


def tone_curve(x_values,y_values):
    if len(x_values)!=49 or len(y_values)!=49 or any(not isinstance(v,int) or not 0<=v<=65535 for v in (*x_values,*y_values)):
        raise ValueError('Expected 49 uint16 coordinate pairs')
    points=sorted((f32(x/65535),f32(y/65535)) for x,y in zip(x_values,y_values))
    # SetPoint flattens repeated first/last abscissae to the endpoint extrema.
    first=points[0][0];last=points[-1][0]
    low=min(y for x,y in points if x==first)
    high=max(y for x,y in points if x==last)
    points=[(x,low if x==first else y) for x,y in points]
    points=[(x,high if x==last else y) for x,y in points]
    xx=[p[0] for p in points];out=[]
    for i in range(2048):
        value=i/2047
        segment=max(0,min(47,bisect_right(xx,value)-1))
        x0,y0=points[segment];x1,y1=points[segment+1]
        out.append(f32(y0+(value-x0)*(y1-y0)/(x1-x0)) if x1!=x0 else f32(y0))
    return tuple(out)
