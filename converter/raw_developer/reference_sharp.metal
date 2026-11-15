// Independent sharpening with explicit settings, preserving signed residuals.
#include <metal_stdlib>
using namespace metal;
struct SharpInput { ushort v[3]; };
struct SharpPrepared { ushort v[3]; short d[3]; };
struct SharpParameters { float maximum,factor; };
inline uint sharpIndex(int x,int y,uint2 size) {
    return min(uint(y),size.y-1)*size.x+min(uint(x),size.x-1);
}
kernel void recoveredSharpPre(device const SharpInput *a [[buffer(0)]],
 device SharpPrepared *out [[buffer(1)]],constant SharpParameters &p [[buffer(2)]],
 constant uint2 &size [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=size))return;
    uint i=id.y*size.x+id.x;SharpPrepared result;
    for(int channel=0;channel<3;channel++) {
        int total=0;
        for(int dy=-2;dy<=2;dy++)for(int dx=-2;dx<=2;dx++) {
            if((dx==0&&dy==0)||(abs(dx)==2&&abs(dy)==2))continue;
            total+=a[sharpIndex(int(id.x)+dx,int(id.y)+dy,size)].v[channel];
        }
        result.v[channel]=a[i].v[channel];
        result.d[channel]=short(int(result.v[channel])-total/20);
    }
    out[i]=result;
}
kernel void recoveredSharp(device const SharpPrepared *a [[buffer(0)]],
 device SharpInput *out [[buffer(1)]],constant SharpParameters &p [[buffer(2)]],
 constant uint2 &size [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=size))return;
    int gain=int(p.factor*1024),low=int(p.maximum/512),high=int(p.maximum*22/1024),limit=int(p.maximum*20/1024);
    int base=(high-low)*gain/256;
    uint i=id.y*size.x+id.x;SharpInput result;
    for(int channel=0;channel<3;channel++) {
        int delta=a[i].d[channel],magnitude=abs(delta);
        if(magnitude>low) {
            int smallest=32768,secondSmallest=32768,largest=-32769,secondLargest=-32769;
            for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++) {
                if(dx==0&&dy==0)continue;
                int v=a[sharpIndex(int(id.x)+dx,int(id.y)+dy,size)].d[channel];
                secondSmallest=min(secondSmallest,max(smallest,v));smallest=min(smallest,v);
                secondLargest=max(secondLargest,min(largest,v));largest=max(largest,v);
            }
            if(delta>0) {
                if(secondLargest<delta){int gap=delta-secondLargest;delta=gap<limit?secondLargest:max(-delta,secondLargest+limit-gap);}
                magnitude=delta;
            } else {
                if(secondSmallest>delta){int gap=secondSmallest-delta;delta=gap<limit?secondSmallest:min(-delta,secondSmallest-limit+gap);}
                magnitude=-delta;
            }
        }
        if(magnitude>0) {
            int sign=delta<0?-1:1;
            if(magnitude<=low)delta=clamp(sign*((magnitude-low)/2),-magnitude,magnitude);
            else if(magnitude<=high)delta=sign*((magnitude-low)*gain/256);
            else delta=sign*max(0,(magnitude-high)/4+base);
        }
        result.v[channel]=ushort(clamp(int(a[i].v[channel])+delta,0,4095));
    }
    out[i]=result;
}
