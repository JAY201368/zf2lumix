// Research-only: run the installed, unmodified Metal kernels on supplied research buffers.
// Manifest specifies kernel, buffer files, output size, and number of pixels.
import Foundation
import Metal

struct Job: Decodable {
    let name: String
    let kernel: String
    let buffers: [String]
    let output: String
    let outputBufferIndex: Int?
    let outputBytes: Int
    let pixels: Int
    let gridWidth: Int?
    let gridHeight: Int?
}
let root = URL(fileURLWithPath: CommandLine.arguments[2])
let jobs = try JSONDecoder().decode([Job].self, from: Data(contentsOf: root.appendingPathComponent("jobs.json")))
guard let device = MTLCreateSystemDefaultDevice(), let queue = device.makeCommandQueue() else {
    fatalError("Metal unavailable")
}
// '-' permits source-only runs without loading any manufacturer executable.
let library: MTLLibrary? = CommandLine.arguments[1] == "-" ? nil : try device.makeLibrary(URL: URL(fileURLWithPath: CommandLine.arguments[1]))
let referenceLibrary: MTLLibrary?
if CommandLine.arguments.count > 3 {
    let source = try String(contentsOfFile: CommandLine.arguments[3], encoding: .utf8)
    let options = MTLCompileOptions()
    options.fastMathEnabled = true
    referenceLibrary = try device.makeLibrary(source: source, options: options)
} else {
    referenceLibrary = nil
}
// Optional disk-bounded mode: only remove outputs produced by this manifest,
// after their final consumer finishes. Source buffers and terminal outputs stay.
let pruneIntermediates = CommandLine.arguments.dropFirst(4).contains("--prune-intermediates")
let generatedNames = Set(jobs.map { $0.output })
var remainingUses: [String: Int] = [:]
for job in jobs {
    for (index, name) in job.buffers.enumerated() where index != (job.outputBufferIndex ?? 1) {
        remainingUses[name, default: 0] += 1
    }
}
var pipelines: [String: MTLComputePipelineState] = [:]
for job in jobs {
    if pipelines[job.kernel] == nil {
        guard let function = (job.kernel.hasPrefix("recovered") ? referenceLibrary : library)?.makeFunction(name: job.kernel) else { fatalError("Kernel missing") }
        pipelines[job.kernel] = try device.makeComputePipelineState(function: function)
    }
    let pipeline = pipelines[job.kernel]!
    let outputIndex = job.outputBufferIndex ?? 1
    guard job.buffers.indices.contains(outputIndex) else { fatalError("Invalid output buffer index") }
    var buffers: [MTLBuffer] = []
    for (index, name) in job.buffers.enumerated() {
        if index == outputIndex {
            buffers.append(device.makeBuffer(length: job.outputBytes, options: .storageModeShared)!)
        } else {
            let data = try Data(contentsOf: root.appendingPathComponent(name))
            let buffer = data.withUnsafeBytes { bytes in
                device.makeBuffer(bytes: bytes.baseAddress!, length: data.count, options: .storageModeShared)!
            }
            buffers.append(buffer)
        }
    }
    let command = queue.makeCommandBuffer()!
    let encoder = command.makeComputeCommandEncoder()!
    encoder.setComputePipelineState(pipeline)
    for (index, buffer) in buffers.enumerated() { encoder.setBuffer(buffer, offset: 0, index: index) }
    let width = job.gridWidth ?? job.pixels
    let height = job.gridHeight ?? 1
    guard width > 0 && height > 0 && width * height == job.pixels else {
        fatalError("Invalid dispatch dimensions")
    }
    encoder.dispatchThreads(MTLSize(width: width, height: height, depth: 1),
                            threadsPerThreadgroup: MTLSize(width: min(64, pipeline.maxTotalThreadsPerThreadgroup), height: 1, depth: 1))
    encoder.endEncoding()
    command.commit()
    command.waitUntilCompleted()
    guard command.status == .completed else { fatalError("GPU failed: \(String(describing: command.error))") }
    try Data(bytes: buffers[outputIndex].contents(), count: job.outputBytes).write(to: root.appendingPathComponent(job.output))
    if pruneIntermediates {
        for (index, name) in job.buffers.enumerated() where index != outputIndex {
            remainingUses[name, default: 0] -= 1
            if remainingUses[name] == 0 && generatedNames.contains(name) && name != job.output {
                try FileManager.default.removeItem(at: root.appendingPathComponent(name))
            }
        }
    }
}
let recoveredCount = jobs.filter { $0.kernel.hasPrefix("recovered") }.count
print("Executed \(jobs.count - recoveredCount) original-kernel jobs and \(recoveredCount) independent-kernel jobs on \(device.name)")
