// Independent expression of the three recovered Bayer reconstruction stages.
// Structs are scalar-packed to preserve the observed 14/6-byte storage layouts.
#include <metal_stdlib>
using namespace metal;
struct BayerParameters { float epsilon, logEpsilon, multiplier; uint color; };
struct PreparedPixel { ushort v[7]; };
struct DifferencePixel { ushort green; short blue, red; };
struct BGRPixel { ushort blue, green, red; };
inline uint wrappedIndex(int x, int y, uint2 size) {
    return min(uint(y),size.y-1)*size.x+min(uint(x),size.x-1);
}
inline int bayerAt(device const ushort *a, int x,int y,uint2 s) {
    return int(a[wrappedIndex(x,y,s)]);
}
inline ushort interpolated(device const ushort *a,int x,int y,uint2 s,bool vertical) {
    int dx=vertical?0:1,dy=vertical?1:0;
    int v0=bayerAt(a,x-3*dx,y-3*dy,s),v1=bayerAt(a,x-dx,y-dy,s);
    int v2=bayerAt(a,x+dx,y+dy,s),v3=bayerAt(a,x+3*dx,y+3*dy,s);
    return ushort(clamp((4*(v1+v2)+(v2-v0)/2+(v3-v1)/-2)/8,0,65535));
}
kernel void recoveredPreProcess(device const ushort *a [[buffer(0)]],
 device PreparedPixel *out [[buffer(1)]],constant BayerParameters &p [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    int x=int(id.x),y=int(id.y),eh=0,ev=0;
    for(int dy=-3;dy<=3;dy++)for(int dx=-3;dx<=3;dx++) {
        int xx=int(min(uint(x+dx),s.x-1)),yy=int(min(uint(y+dy),s.y-1));
        int weight=(4-abs(dx))*(4-abs(dy));
        eh+=weight*abs(bayerAt(a,xx-1,yy,s)-bayerAt(a,xx+1,yy,s));
        ev+=weight*abs(bayerAt(a,xx,yy-1,s)-bayerAt(a,xx,yy+1,s));
    }
    ushort h=interpolated(a,x,y,s,false),v=interpolated(a,x,y,s,true);
    ushort he=ushort(min(65535,eh/16)),ve=ushort(min(65535,ev/16));
    ushort selected=ve<he?v:h,err=min(he,ve),value=a[id.y*s.x+id.x];
    uint site=(((id.y&1)*2)+(id.x&1))^p.color;
    PreparedPixel q;
    if(site==0)q={{value,value,selected,err,0,0,65535}};
    else if(site==1)q={{value,h,value,he,v,value,ve}};
    else if(site==2)q={{value,v,value,ve,h,value,he}};
    else q={{value,0,0,65535,value,selected,err}};
    out[id.y*s.x+id.x]=q;
}
inline int adaptiveDifference(device const PreparedPixel *a,int x,int y,uint2 s,int base) {
    int minimum=65535;
    for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++)
        minimum=min(minimum,int(a[wrappedIndex(x+dx,y+dy,s)].v[base+2]));
    int threshold=333*minimum/256,total=0,count=0,best=65535,fallback=0;
    for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++) {
        PreparedPixel q=a[wrappedIndex(x+dx,y+dy,s)];
        int error=int(q.v[base+2]),delta=int(q.v[base])-int(q.v[base+1]);
        if(error<threshold){total+=delta;count++;}
        if(error<best){best=error;fallback=delta;}
    }
    return count?total/count:fallback;
}
inline ushort localLimit(device const PreparedPixel *a,int value,int x,int y,uint2 s,bool green) {
    int low=65535,high=0;
    for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++) {
        if((dx==0&&dy==0)||(green&&abs(dx)+abs(dy)!=1))continue;
        int xx=x+dx,yy=y+dy;
        int neighbor=(xx<0||yy<0||xx>=int(s.x)||yy>=int(s.y))?value:int(a[yy*int(s.x)+xx].v[0]);
        low=min(low,neighbor);high=max(high,neighbor);
    }
    if(green){int spread=high-low;low-=spread;high+=spread;}
    return ushort(clamp(value,low,high));
}
kernel void recoveredFirstProcess(device const PreparedPixel *a [[buffer(0)]],
 device DifferencePixel *out [[buffer(1)]],constant BayerParameters &p [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    int x=int(id.x),y=int(id.y);uint index=id.y*s.x+id.x;
    int dr=adaptiveDifference(a,x,y,s,1),db=adaptiveDifference(a,x,y,s,4),source=int(a[index].v[0]);
    uint site=(((id.y&1)*2)+(id.x&1))^p.color;
    ushort g,b,r;
    if(site==0){int green=clamp(source-dr,0,65535);g=localLimit(a,green,x,y,s,true);b=localLimit(a,clamp(green+db,0,65535),x,y,s,false);r=ushort(source);}
    else if(site==3){int green=clamp(source-db,0,65535);g=localLimit(a,green,x,y,s,true);b=ushort(source);r=localLimit(a,clamp(green+dr,0,65535),x,y,s,false);}
    else {g=ushort(source);b=localLimit(a,clamp(source+db,0,65535),x,y,s,false);r=localLimit(a,clamp(source+dr,0,65535),x,y,s,false);}
    // Express the observed exponent in two operations; GPU agreement is tested.
    float ge=float(g)*p.multiplier,be=float(short(b))*p.multiplier,re=float(short(r))*p.multiplier;
    float gl=exp(ge+p.logEpsilon)-p.epsilon;
    float bl=exp(be+p.logEpsilon)-p.epsilon,rl=exp(re+p.logEpsilon)-p.epsilon;
    out[index]={ushort(clamp(floor(gl+.5f),0.0f,65535.0f)),short(clamp(int(bl)-int(gl),-32768,32767)),short(clamp(int(rl)-int(gl),-32768,32767))};
}
kernel void recoveredSecondProcess(device const DifferencePixel *a [[buffer(0)]],
 device BGRPixel *out [[buffer(1)]],constant BayerParameters &p [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    const int weights[9]={1,2,0,2,5,2,1,2,1};
    int blue=0,red=0,k=0;
    for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++) {
        DifferencePixel q=a[wrappedIndex(int(id.x)+dx,int(id.y)+dy,s)];
        int weight=weights[k++];blue+=int(q.blue)*weight;red+=int(q.red)*weight;
    }
    uint index=id.y*s.x+id.x;ushort g=a[index].green;
    out[index]={ushort(clamp(int(g)+blue/16,0,65535)),g,ushort(clamp(int(g)+red/16,0,65535))};
}
