// Independent neutral style and dual-LUT expressions with explicit parameters.
#include <metal_stdlib>
using namespace metal;
struct ColorPixel { ushort b,g,r; };
inline float recoveredCurve(float value,device const float *table) {
    float position=value*2047.0f;uint i=min(uint(position),2046u);
    return mix(table[i],table[i+1],position-float(i));
}
inline float3 recoveredCube(float3 rgb,device const float4 *table) {
    float3 position=rgb*32.0f;uint3 cell=min(uint3(position),uint3(31));
    float3 f=position-float3(cell);
    uint index=cell.z*1089+cell.y*33+cell.x;
    float3 row00=table[index].xyz+(table[index+1].xyz-table[index].xyz)*f.x;
    float3 row10=table[index+33].xyz+(table[index+34].xyz-table[index+33].xyz)*f.x;
    float3 row01=table[index+1089].xyz+(table[index+1090].xyz-table[index+1089].xyz)*f.x;
    float3 row11=table[index+1122].xyz+(table[index+1123].xyz-table[index+1122].xyz)*f.x;
    float3 plane0=row00+(row10-row00)*f.y;
    float3 plane1=row01+(row11-row01)*f.y;
    return plane0+(plane1-plane0)*f.z;
}
kernel void recoveredCnv2Neutral(device const ColorPixel *a [[buffer(0)]],
 device ColorPixel *out [[buffer(1)]],constant uint *words [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],device const float *gamma [[buffer(4)]],
 device const float4 *correction [[buffer(5)]],device const float *tone [[buffer(6)]],
 uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint i=id.y*s.x+id.x;ColorPixel q=a[i];
    float maximum=as_type<float>(words[15]),brightness=as_type<float>(words[0]);
    float3 gains=float3(as_type<float>(words[1]),1,as_type<float>(words[2]));
    float3 rgb=clamp(clamp(float3(q.r,q.g,q.b)/maximum*gains,0.0f,1.0f)*brightness,0.0f,1.0f);
    if(words[14]) {
        if(words[13]==2) {
            rgb.r+=(rgb.r>=rgb.g?-.33984375f:-.46484375f)*(rgb.r-rgb.g)+(rgb.r>=rgb.b?.0234375f:.03125f)*(rgb.r-rgb.b);
            rgb.g+=(rgb.g>=rgb.r?.10546875f:.01171875f)*(rgb.g-rgb.r);
            rgb.b+=-.0078125f*(rgb.b-rgb.r)+(rgb.b>=rgb.g?-.04296875f:-.08984375f)*(rgb.b-rgb.g);
        }
        if(words[11]) {
            float y=dot(rgb,float3(.299f,.587f,.114f));
            rgb=clamp(rgb*(recoveredCurve(y,tone)/y),0.0f,1.0f);
        }
        rgb=clamp(float3(recoveredCurve(rgb.r,gamma),recoveredCurve(rgb.g,gamma),recoveredCurve(rgb.b,gamma)),0.0f,1.0f);
        rgb=clamp(recoveredCube(rgb,correction),0.0f,float(words[12])/4095.0f);
    }
    ushort3 v=ushort3(rgb*4095.0f);
    out[i]=words[43]?ColorPixel{ushort(ushort(v.g-v.b)^32768),v.g,ushort(ushort(v.g-v.r)^32768)}:ColorPixel{v.b,v.g,v.r};
}
kernel void recoveredDualNeutral(device const ColorPixel *a [[buffer(0)]],
 device ColorPixel *out [[buffer(1)]],constant uint *words [[buffer(2)]],
 constant uint2 &s [[buffer(3)]],device const float4 *first [[buffer(4)]],
 device const float *unusedL [[buffer(5)]],device const float *unusedR [[buffer(6)]],
 device const float *unusedG [[buffer(7)]],device const float *unusedB [[buffer(8)]],
 device const float4 *second [[buffer(9)]],uint2 id [[thread_position_in_grid]]) {
    if(any(id>=s))return;
    uint i=id.y*s.x+id.x;ColorPixel q=a[i];
    float3 rgb=clamp(float3(q.r,q.g,q.b)/as_type<float>(words[0]),0.0f,1.0f);
    float strength=as_type<float>(words[88]);
    if(strength>0)rgb=clamp(strength*recoveredCube(rgb,first)+(1-strength)*rgb,0.0f,1.0f);
    strength=as_type<float>(words[89]);
    if(strength>0)rgb=clamp(strength*recoveredCube(rgb,second)+(1-strength)*rgb,0.0f,1.0f);
    ushort3 v=ushort3(rgb*as_type<float>(words[1]));out[i]={v.b,v.g,v.r};
}
