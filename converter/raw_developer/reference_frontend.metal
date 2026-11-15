// Independently expressed front-end formula, compiled with Metal fast math.
// Parameters remain explicit; this is not a RAW decoder or host-state loader.
#include <metal_stdlib>
using namespace metal;
struct FrontParameters {
    float epsilon, logEpsilon, scale, redGain, blueGain;
    int clip;
    float redMax, greenMax, blueMax;
};
kernel void recoveredFrontEnd(device const ushort *input [[buffer(0)]],
                              device ushort *output [[buffer(1)]],
                              constant FrontParameters &p [[buffer(2)]],
                              constant uint2 &size [[buffer(3)]],
                              uint index [[thread_position_in_grid]]) {
    if (index >= size.x * size.y) return;
    uint x = index % size.x;
    uint y = index / size.x;
    float level = float(input[index]);
    float maximum = p.greenMax;
    if ((y & 1) == 0 && (x & 1) == 0) {
        level *= p.redGain;
        maximum = p.redMax;
    } else if ((y & 1) != 0 && (x & 1) != 0) {
        level *= p.blueGain;
        maximum = p.blueMax;
    }
    if (p.clip == 1) level = min(level, maximum);
    float encoded = floor((log(level + p.epsilon) - p.logEpsilon) * p.scale + 0.5f);
    output[index] = ushort(clamp(encoded, 0.0f, 65535.0f));
}
