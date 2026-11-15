// Independent biased-difference blur and chroma reconstruction.
#include <metal_stdlib>
using namespace metal;
struct ChromaPixel { ushort b,g,r; };
struct ChromaParams { float a,b,c; int green,strength,radius,step; };
inline ChromaPixel chromaAt(device const ChromaPixel *p,int2 xy,uint2 size) {
    xy=clamp(xy,int2(0),int2(size)-1);return p[xy.y*size.x+xy.x];
}
inline ChromaPixel chromaBlur(device const ChromaPixel *p,int2 xy,uint2 size,
                            constant ChromaParams &v,bool vertical) {
    int2 axis=vertical?int2(0,1):int2(1,0);
    ChromaPixel q=chromaAt(p,xy,size);int green=q.g;
    if(v.green)green=int((v.a*float(chromaAt(p,xy-axis,size).g)+v.b*float(q.g))+
                        v.c*float(chromaAt(p,xy+axis,size).g));
    int b=q.b,r=q.r;
    if(v.strength>0) {
        b=0;r=0;
        for(int k=-v.radius;k<=v.radius;k++) {
            ChromaPixel t=chromaAt(p,xy+k*axis,size);b+=t.b;r+=t.r;
        }
        b/=v.step;r/=v.step;
    } else if(vertical) {b=clamp(green+32768-b,0,65535);r=clamp(green+32768-r,0,65535);}
    return {ushort(b),ushort(green),ushort(r)};
}
kernel void recoveredChromaH(device const ChromaPixel *p [[buffer(0)]],device ChromaPixel *out [[buffer(1)]],
 constant ChromaParams &v [[buffer(2)]],constant uint2 &size [[buffer(3)]],uint2 xy [[thread_position_in_grid]]) {
    if(any(xy>=size))return;out[xy.y*size.x+xy.x]=chromaBlur(p,int2(xy),size,v,false);
}
kernel void recoveredChromaV(device const ChromaPixel *p [[buffer(0)]],device ChromaPixel *out [[buffer(1)]],
 constant ChromaParams &v [[buffer(2)]],constant uint2 &size [[buffer(3)]],uint2 xy [[thread_position_in_grid]]) {
    if(any(xy>=size))return;out[xy.y*size.x+xy.x]=chromaBlur(p,int2(xy),size,v,true);
}
kernel void recoveredChromaFinish(device const ChromaPixel *p [[buffer(0)]],device const ChromaPixel *original [[buffer(1)]],
 device ChromaPixel *out [[buffer(2)]],constant ChromaParams &v [[buffer(3)]],constant uint2 &size [[buffer(4)]],
 uint2 xy [[thread_position_in_grid]]) {
    if(any(xy>=size))return;
    uint i=xy.y*size.x+xy.x;ChromaPixel q=p[i];int2 center=int2(q.b,q.r),total=center*2;int count=2;
    for(int direction=0;direction<2;direction++)for(int k=1;k<=3;k++) {
        int2 delta=direction?int2(0,k*v.step):int2(k*v.step,0);
        ChromaPixel a=chromaAt(p,int2(xy)-delta,size),b=chromaAt(p,int2(xy)+delta,size);
        int2 pair=int2(a.b+b.b,a.r+b.r),diff=abs(pair-2*center);
        if(diff.x+diff.y<256){total+=pair;count+=2;}
    }
    int2 local=total/count-32768,previous=int2(original[i].b,original[i].r)-32768;
    int2 difference=((256-v.strength)*previous+v.strength*local)>>8;
    int2 result=clamp(int(q.g)-difference,0,65535);out[i]={ushort(result.x),q.g,ushort(result.y)};
}
