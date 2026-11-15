// File-based 33-grid LUTs with independent input domains and layer strengths.
// Requires reference_color.metal's pixel layout and trilinear sampler.
struct FileLUTParams {
    float inputMax,outputMax,firstStrength,secondStrength;
    float firstLow[3],firstHigh[3],secondLow[3],secondHigh[3];
};
inline float3 fileLUTDomain(float3 rgb,constant float *low,constant float *high) {
    float3 a=float3(low[0],low[1],low[2]),b=float3(high[0],high[1],high[2]);
    return clamp((rgb-a)/(b-a),0.0f,1.0f);
}
kernel void recoveredFileLUT(device const ColorPixel *source [[buffer(0)]],device ColorPixel *out [[buffer(1)]],
 constant FileLUTParams &p [[buffer(2)]],constant uint2 &size [[buffer(3)]],
 device const float4 *first [[buffer(4)]],device const float4 *second [[buffer(5)]],uint2 xy [[thread_position_in_grid]]) {
    if(any(xy>=size))return;
    uint i=xy.y*size.x+xy.x;ColorPixel q=source[i];
    float3 rgb=clamp(float3(q.r,q.g,q.b)/p.inputMax,0.0f,1.0f);
    if(p.firstStrength>0)rgb=clamp(p.firstStrength*recoveredCube(fileLUTDomain(rgb,p.firstLow,p.firstHigh),first)+(1.0f-p.firstStrength)*rgb,0.0f,1.0f);
    if(p.secondStrength>0)rgb=clamp(p.secondStrength*recoveredCube(fileLUTDomain(rgb,p.secondLow,p.secondHigh),second)+(1.0f-p.secondStrength)*rgb,0.0f,1.0f);
    ushort3 value=ushort3(rgb*p.outputMax);out[i]={value.b,value.g,value.r};
}
