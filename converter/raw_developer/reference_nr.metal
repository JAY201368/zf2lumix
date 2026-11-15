// Independently expressed NR preparation; host defaults remain explicit.
#include <metal_stdlib>
using namespace metal;
struct NRInput { ushort b,g,r; };
struct NRPrepared { ushort b,g,r,l; short cb,cr; ushort over; };
struct NRFirstParameters { float maximum,bgain,ggain,rgain,gamma; int radius,limit; };
kernel void recoveredNRFirst(device const NRInput *a [[buffer(0)]],
 device NRPrepared *out [[buffer(1)]],constant NRFirstParameters &p [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint index=id.y*s.x+id.x;NRInput q=a[index];
    float l=(float(q.b)*p.bgain+float(q.g)*p.ggain)+float(q.r)*p.rgain;
    float result=l;
    if(p.gamma!=1.0f) {
        float value=l/p.maximum,exponent=1.0f/p.gamma;
        float power=pow(value,exponent),linear=value*8.0f;
        result=(exponent>1.0f?max(power,linear):min(power,linear))*p.maximum;
    }
    out[index]={q.b,q.g,q.r,ushort(result),short((int(q.b)-int(q.g))/2),
        short((int(q.r)-int(q.g))/2),p.radius>0?ushort(l-float(p.limit)):ushort(0)};
}
struct NRSecond { ushort v[11]; };
struct NRLowPass { ushort v[10]; };
struct NRSecondParameters { float maximum; int rpfL,rpfM,rpfS,sizeL,chroma,sizeC,overRPF,overHLPF; };
inline float3 nrLCC(NRPrepared q) {return float3(q.l,q.cb,q.cr);}
inline float3 nrAverage(device const NRPrepared *a,int side,constant uint2 &s,uint2 id,
 constant float *weights,bool weighted) {
    int radius=side/2;float3 sum=0;float weight=0;
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++) {
        uint x=id.x+uint(dx),y=id.y+uint(dy);
        if(x>=s.x||y>=s.y)continue;
        float w=weighted?weights[(dy+radius)*side+dx+radius]:1.0f;
        sum+=nrLCC(a[y*s.x+x])*w;weight+=w;
    }
    return weight>0?sum/weight:nrLCC(a[id.y*s.x+id.x]);
}
inline int nrOverAverage(device const NRPrepared *a,int side,constant uint2 &s,uint2 id) {
    int radius=side/2;float sum=0;uint count=0;
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++) {
        uint x=id.x+uint(dx),y=id.y+uint(dy);
        if(x<s.x&&y<s.y){sum+=float(a[y*s.x+x].over);count++;}
    }
    return count?int(sum/float(count)):int(a[id.y*s.x+id.x].over);
}
kernel void recoveredNRSecond(device const NRPrepared *a [[buffer(0)]],
 device NRSecond *out [[buffer(1)]],constant NRSecondParameters &p [[buffer(2)]],
 constant float *weightsL [[buffer(3)]],constant float *weightsC [[buffer(4)]],
 constant uint2 &s [[buffer(5)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint index=id.y*s.x+id.x;NRPrepared q=a[index];
    ushort lowL=p.sizeL>0?ushort(int(nrAverage(a,p.sizeL,s,id,weightsL,true).x)):q.l;
    ushort l=q.l;short cb=q.cb,cr=q.cr;ushort hilight=0;
    if(p.chroma!=0&&p.sizeC>0) {
        float3 average=nrAverage(a,p.sizeC,s,id,weightsC,true);
        l=ushort(average.x);cb=short(average.y);cr=short(average.z);
    }
    if(p.rpfL>0) {
        int overL=nrOverAverage(a,p.rpfL,s,id),overM=nrOverAverage(a,p.rpfM,s,id),overS=nrOverAverage(a,p.rpfS,s,id);
        hilight=min(ushort(uint(p.overHLPF*overS)>>6),ushort(256));
        int product=p.overRPF*max(max(overL,overM),overS),level=product>>6;
        if(product>63) {
            float3 v=nrAverage(a,p.rpfL,s,id,weightsL,false);
            if(v.x!=0){v.yz*=float(l)/v.x;v.x=float(l);}else v.x=0;
            if(uint(product)<16384u) {
                int remaining=256-level;
                v=(float(level)*v+float3(remaining*int(l),remaining*int(cb),remaining*int(cr)))*0.003906f;
            }
            l=ushort(v.x);cb=short(v.y);cr=short(v.z);
        }
    }
    out[index]={{q.b,q.g,q.r,q.l,ushort(q.cb),ushort(q.cr),lowL,l,ushort(cb),ushort(cr),hilight}};
}
kernel void recoveredNRHLPF(device const NRSecond *a [[buffer(0)]],
 device NRLowPass *out [[buffer(1)]],constant float &unused [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint index=id.y*s.x+id.x;NRSecond q=a[index];NRLowPass result;
    for(int c=0;c<10;c++)result.v[c]=q.v[c];
    int level=q.v[10];
    if(level!=0)for(int c=3;c<=6;c+=3) {
        int sum=8;
        for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++) {
            uint x=min(id.x+uint(dx),s.x-1),y=min(id.y+uint(dy),s.y-1);
            int weight=(dx==0?2:1)*(dy==0?2:1);
            sum+=int(a[y*s.x+x].v[c])*weight;
        }
        result.v[c]=ushort((sum*level+(4096-level*16)*int(q.v[c]))/4096);
    }
    out[index]=result;
}
struct NRDirectionalParameters {
    float maximum;uint thresholdL,centerL;int sizeL,stepL;uint retriesL,thresholdC,centerC;
    int chroma,sizeC,stepC;uint retriesC;float sumMinL,sumMinC;
};
struct NRFourth { ushort v[12]; };
inline NRLowPass nrAt(device const NRLowPass *a,int2 at,uint2 s) {
    uint2 p=min(uint2(at),s-1);return a[p.y*s.x+p.x];
}
inline int nrDirection(uint plus,uint center,uint minus,int step) {
    return minus<center?(minus<plus?-step:step):(plus<center?step:0);
}
inline uint nrMinimum(uint threshold,float factor) {
    float v=floor(float(threshold)*factor-0.5f);
    // Preserve the observed shader's unusual conversion branches.
    return v<4294967296.0f?0xffffffffu:(v>0?0u:uint(v));
}
inline uint nrPairL(device const NRLowPass *a,int2 id,int2 offset,uint2 s,
 int center,uint threshold,thread ulong &sum,thread uint &weight) {
    int u=nrAt(a,id-offset,s).v[6],v=nrAt(a,id+offset,s).v[6];
    uint du=uint(abs(center-u)),dv=uint(abs(center-v));
    int wu=int(threshold)-int(du),wv=int(threshold)-int(dv);
    if(wu>0&&wv>0){uint w=uint(wu+wv+1)>>1;sum+=ulong(w)*ulong(u+v);weight+=w*2;}
    return du+dv;
}
inline ushort nrDirectionalL(device const NRLowPass *a,uint2 id,uint2 s,constant NRDirectionalParameters &p,bool updateCenter) {
    int center=a[id.y*s.x+id.x].v[6];
    if(p.sizeL<=0||p.thresholdL==0)return ushort(center);
    uint weight=p.centerL;ulong sum=ulong(p.centerL*uint(center));
    uint minimum=nrMinimum(p.thresholdL,p.sumMinL),threshold=p.thresholdL;
    int step=p.stepL;
    for(uint attempt=0;threshold<4096u;attempt++,threshold+=p.thresholdL) {
        uint retryWeight=weight;
        if(step<=p.sizeL) {
            uint before=weight;
            uint plus=nrPairL(a,int2(id),int2(step,step),s,center,threshold,sum,weight);
            uint mid=nrPairL(a,int2(id),int2(step,0),s,center,threshold,sum,weight);
            uint minus=nrPairL(a,int2(id),int2(step,-step),s,center,threshold,sum,weight);
            nrPairL(a,int2(id),int2(0,step),s,center,threshold,sum,weight);
            if(before!=weight&&2*step<=p.sizeL) {
                if(updateCenter)center=int(sum/weight);
                int off=nrDirection(plus,mid,minus,step);
                for(int x=2*step;x<p.sizeL;x+=step) {
                    before=weight;
                    plus=nrPairL(a,int2(id),int2(x,off+step),s,center,threshold,sum,weight);
                    mid=nrPairL(a,int2(id),int2(x,off),s,center,threshold,sum,weight);
                    minus=nrPairL(a,int2(id),int2(x,off-step),s,center,threshold,sum,weight);
                    if(retryWeight==weight)break;
                    off+=nrDirection(plus,mid,minus,step);
                }
            }
        }
        int off=0;
        for(int y=2*step;y<=p.sizeL;y+=step) {
            uint before=weight;
            uint plus=nrPairL(a,int2(id),int2(off+step,y),s,center,threshold,sum,weight);
            uint mid=nrPairL(a,int2(id),int2(off,y),s,center,threshold,sum,weight);
            uint minus=nrPairL(a,int2(id),int2(off-step,y),s,center,threshold,sum,weight);
            if(before==weight)break;
            off+=nrDirection(plus,mid,minus,step);
        }
        if(attempt+1>p.retriesL||weight>minimum)break;
    }
    return ushort(min(sum/weight,ulong(65535)));
}
inline int3 nrOriginalLCC(NRLowPass q) {return int3(q.v[3],short(q.v[4]),short(q.v[5]));}
inline long3 nrFilteredLCC(NRLowPass q) {return long3(q.v[7],short(q.v[8]),short(q.v[9]));}
inline uint nrPairC(device const NRLowPass *a,int2 id,int2 offset,uint2 s,
 int3 center,uint threshold,thread long3 &sum,thread uint &weight) {
    NRLowPass u=nrAt(a,id-offset,s),v=nrAt(a,id+offset,s);
    int3 d1=abs(center-nrOriginalLCC(u)),d2=abs(center-nrOriginalLCC(v));
    uint du=d1.x+d1.y+d1.z,dv=d2.x+d2.y+d2.z;
    int wu=int(threshold)-int(du),wv=int(threshold)-int(dv);
    if(wu>0&&wv>0){uint w=uint(wu+wv+1)>>1;sum+=long(w)*(nrFilteredLCC(u)+nrFilteredLCC(v));weight+=w*2;}
    return du+dv;
}
inline long3 nrDirectionalC(device const NRLowPass *a,uint2 id,uint2 s,constant NRDirectionalParameters &p) {
    NRLowPass q=a[id.y*s.x+id.x];long3 value=nrFilteredLCC(q);
    if(!p.chroma||p.sizeC<=0||p.thresholdC==0)return value;
    uint weight=p.centerC;long3 sum=long(weight)*value;
    uint minimum=nrMinimum(p.thresholdC,p.sumMinC),threshold=p.thresholdC;int step=p.stepC;
    int3 center=nrOriginalLCC(q);
    for(uint attempt=0;threshold<4096;attempt++,threshold+=p.thresholdC) {
        int off=0,x=step;bool first=true;
        for(;x<=p.sizeC;x+=step) {
            uint before=weight;
            uint plus=nrPairC(a,int2(id),int2(x,off+step),s,center,threshold,sum,weight);
            uint mid=nrPairC(a,int2(id),int2(x,off),s,center,threshold,sum,weight);
            uint minus=nrPairC(a,int2(id),int2(x,off-step),s,center,threshold,sum,weight);
            if(first){nrPairC(a,int2(id),int2(0,x),s,center,threshold,sum,weight);if(before==weight)break;first=false;}
            off+=nrDirection(plus,mid,minus,step);
        }
        off=0;
        for(int y=x+2*step;y<=p.sizeC;y+=step) {
            uint before=weight;
            uint plus=nrPairC(a,int2(id),int2(off+step,y),s,center,threshold,sum,weight);
            uint mid=nrPairC(a,int2(id),int2(off,y),s,center,threshold,sum,weight);
            uint minus=nrPairC(a,int2(id),int2(off-step,y),s,center,threshold,sum,weight);
            if(before==weight)break;
            off+=nrDirection(plus,mid,minus,step);
        }
        if(attempt+1>p.retriesC||weight>minimum)break;
    }
    return sum/long(weight);
}
kernel void recoveredNRThird(device const NRLowPass *a [[buffer(0)]],device NRLowPass *out [[buffer(1)]],
 constant NRDirectionalParameters &p [[buffer(2)]],constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint i=id.y*s.x+id.x;NRLowPass q=a[i];q.v[6]=nrDirectionalL(a,id,s,p,true);
    long3 c=nrDirectionalC(a,id,s,p);q.v[7]=ushort(c.x);q.v[8]=ushort(c.y);q.v[9]=ushort(c.z);out[i]=q;
}
kernel void recoveredNRFourth(device const NRLowPass *a [[buffer(0)]],device NRFourth *out [[buffer(1)]],
 constant NRDirectionalParameters &p [[buffer(2)]],constant uint2 &s [[buffer(3)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint i=id.y*s.x+id.x;NRLowPass q=a[i];NRFourth r;
    for(int j=0;j<10;j++)r.v[j]=q.v[j];
    r.v[6]=nrDirectionalL(a,id,s,p,false);long3 c=nrDirectionalC(a,id,s,p);
    r.v[7]=ushort(c.x);r.v[8]=ushort(c.y);r.v[9]=ushort(c.z);
    r.v[10]=r.v[11]=ushort(short(clamp(int(r.v[6])-int(q.v[3]),-32768,32767)));out[i]=r;
}
struct NRFifthParameters { float maximum,gamma;int absSize,absMax,sizeL,chroma,sizeC;float cbGain,crGain; };
inline float4 nrFinalAverage(device const NRFourth *a,int side,uint2 s,uint2 id,
 constant float *weights) {
    float4 sum=0;float total=0;int radius=side/2;
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++) {
        uint x=id.x+uint(dx),y=id.y+uint(dy);if(x>=s.x||y>=s.y)continue;
        NRFourth q=a[y*s.x+x];float w=weights[(dy+radius)*side+dx+radius];
        sum+=float4(q.v[7],short(q.v[8]),short(q.v[9]),short(q.v[10]))*w;total+=w;
    }
    NRFourth q=a[id.y*s.x+id.x];
    return total>0?sum/total:float4(q.v[7],short(q.v[8]),short(q.v[9]),short(q.v[10]));
}
inline int nrAverageAbsolute(device const NRFourth *a,int side,uint2 s,uint2 id) {
    float sum=0;uint count=0;int radius=side/2;
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++) {
        uint x=id.x+uint(dx),y=id.y+uint(dy);if(x>=s.x||y>=s.y)continue;
        sum+=float(short(abs(short(a[y*s.x+x].v[11]))));count++;
    }
    return count?int(sum/float(count)):int(short(a[id.y*s.x+id.x].v[11]));
}
inline NRInput nrToBGR(ushort l,short cb,short cr,ushort newL,constant NRFifthParameters &p) {
    float y=float(newL);
    if(p.gamma!=1.0f){float v=y/p.maximum,power=pow(v,p.gamma),linear=v*.125f;y=(p.gamma>1?max(power,linear):min(power,linear))*p.maximum;}
    float scale=float(newL)/(float(l)+1.0f),b=scale*float(cb),r=scale*float(cr);
    float g=(b*p.cbGain+y)+r*p.crGain;
    return {ushort(clamp(int(g+2.0f*b),0,65535)),ushort(clamp(int(g),0,65535)),ushort(clamp(int(g+2.0f*r),0,65535))};
}
kernel void recoveredNRFifth(device const NRFourth *a [[buffer(0)]],device NRInput *out [[buffer(1)]],
 constant NRFifthParameters &p [[buffer(2)]],constant float *weightsL [[buffer(3)]],
 constant float *weightsC [[buffer(4)]],constant uint2 &s [[buffer(5)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint index=id.y*s.x+id.x;NRFourth q=a[index];
    int diff=short(q.v[10]);
    if(p.sizeL>0) {
        diff=int(nrFinalAverage(a,p.sizeL,s,id,weightsL).w);
        if(p.absSize>0) {
            int average=nrAverageAbsolute(a,p.absSize,s,id);
            int blend=average<p.absMax?max(64,int(float(int(float(average)*256.0f))/float(p.absMax))):256;
            diff=(blend*diff+(256-blend)*int(short(q.v[11])))/256;
        }
    }
    ushort newL=ushort(clamp(int(q.v[3])+diff,0,65535));
    ushort l=q.v[7];short cb=short(q.v[8]),cr=short(q.v[9]);
    if(p.sizeC>0&&(p.sizeL<=0||p.chroma!=0)) {
        float3 v=nrFinalAverage(a,p.sizeC,s,id,weightsC).xyz;
        l=ushort(v.x);cb=short(v.y);cr=short(v.z);
    }
    out[index]=nrToBGR(l,cb,cr,newL,p);
}
