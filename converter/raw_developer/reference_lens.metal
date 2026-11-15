// Distortion-only resampling of explicit 101-entry radial displacement table.
#include <metal_stdlib>
using namespace metal;
struct LensPixel { ushort b,g,r; };
struct LensParameters { int offsetY; float maximum; int enabled; float g0,g2,g4,g6,cx,cy,radius,scale; int aberration; };
inline float3 lensValue(device const LensPixel *a,uint index) {
    LensPixel q=a[index];return float3(q.b,q.g,q.r);
}
kernel void recoveredLensD(device const LensPixel *a [[buffer(0)]],
 device LensPixel *out [[buffer(1)]],constant LensParameters &p [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],constant float *rates [[buffer(4)]],
 uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    float x=float(id.x)-p.cx,y=float(id.y+uint(p.offsetY))-p.cy;
    float at=sqrt(x*x+y*y)*100.0f/p.radius;
    uint i=uint(floor(at));
    float factor=1.0f+mix(rates[i],rates[min(i+1,100u)],at-float(i));
    float sx=x*factor+p.cx,sy=y*factor+(p.cy-float(p.offsetY));
    uint ix=min(uint(floor(sx)),s.x-1),iy=min(uint(floor(sy)),s.y-1);
    uint jx=min(ix+1,s.x-1),jy=min(iy+1,s.y-1);
    float fx=sx-float(ix),fy=sy-float(iy);
    float3 top=mix(lensValue(a,iy*s.x+ix),lensValue(a,iy*s.x+jx),fx);
    float3 bottom=mix(lensValue(a,jy*s.x+ix),lensValue(a,jy*s.x+jx),fx);
    ushort3 q=ushort3(clamp(mix(top,bottom,fy),0.0f,p.maximum));
    out[id.y*s.x+id.x]={q.x,q.y,q.z};
}

inline float lensChannel(device const LensPixel *a,constant LensParameters &p,uint2 size,
                         constant float *rates,float x,float y,uint i,uint j,float fraction,bool red) {
    float factor=1.0f+mix(rates[i],rates[j],fraction);
    float sx=x*factor+p.cx,sy=(y*factor+p.cy)-float(p.offsetY);
    uint ix=min(uint(floor(sx)),size.x-1),iy=min(uint(floor(sy)),size.y-1);
    uint jx=min(ix+1,size.x-1),jy=min(iy+1,size.y-1);
    LensPixel a0=a[iy*size.x+ix],a1=a[iy*size.x+jx],b0=a[jy*size.x+ix],b1=a[jy*size.x+jx];
    float top=mix(float(red?a0.r:a0.b),float(red?a1.r:a1.b),sx-float(ix));
    float bottom=mix(float(red?b0.r:b0.b),float(red?b1.r:b1.b),sx-float(ix));
    return mix(top,bottom,sy-float(iy));
}
kernel void recoveredLensA(device const LensPixel *a [[buffer(0)]],device LensPixel *out [[buffer(1)]],
 constant LensParameters &p [[buffer(2)]],constant uint2 &size [[buffer(3)]],
 constant float *red [[buffer(4)]],constant float *blue [[buffer(5)]],uint2 xy [[thread_position_in_grid]]) {
    if(any(xy>=size))return;
    uint index=xy.y*size.x+xy.x;LensPixel q=a[index];
    if(p.aberration==1) {
        float x=float(xy.x)-p.cx,y=float(xy.y+uint(p.offsetY))-p.cy;
        float at=sqrt(y*y+x*x)*1023.0f/p.radius;
        uint i=uint(floor(at)),j=min(i+1,1023u);float f=at-float(i);
        q.r=ushort(clamp(lensChannel(a,p,size,red,x,y,i,j,f,true),0.0f,p.maximum));
        q.b=ushort(clamp(lensChannel(a,p,size,blue,x,y,i,j,f,false),0.0f,p.maximum));
        q.g=ushort(min(float(q.g),p.maximum));
    }
    out[index]=q;
}
