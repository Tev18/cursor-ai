import ReplayKit
import CoreImage
import CoreMedia
import ImageIO

/// Runs while the system screen broadcast is on. Keeps only the newest frame in memory (no recording, no
/// flash, no sound); when the app/Shortcut posts the capture signal it sends that frame to Claude.
class SampleHandler: RPBroadcastSampleHandler {
    private var latest: CVPixelBuffer?
    private var orientation: CGImagePropertyOrientation = .up
    private let lock = NSLock()
    private var busy = false
    private var observer: DarwinObserver?
    private let ctx = CIContext()

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        Shared.broadcastRunning = true
        observer = DarwinObserver(name: Shared.captureName) { [weak self] in self?.capture() }
    }

    override func broadcastFinished() {
        Shared.broadcastRunning = false
        observer = nil
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video, let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        var o = CGImagePropertyOrientation.up
        if let n = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil) as? NSNumber,
           let v = CGImagePropertyOrientation(rawValue: n.uint32Value) {
            o = v
        }
        lock.lock()
        latest = pixels
        orientation = o
        lock.unlock()
    }

    private func capture() {
        lock.lock()
        let pixels = latest
        let o = orientation
        let already = busy
        if !already { busy = true }
        lock.unlock()
        if already { return }
        guard let pixels else {
            finish(answer: nil, error: "No screen frame yet - wait a second after starting the broadcast, then try again.")
            return
        }
        Shared.state = "thinking"
        DarwinNotify.post(Shared.answerName)
        guard let jpeg = encode(pixels, orientation: o) else {
            finish(answer: nil, error: "Could not read the screen frame.")
            return
        }
        let key = Shared.apiKey, model = Shared.model, instruction = Shared.instruction
        Task {
            do {
                let text = try await ClaudeClient.ask(jpeg: jpeg, apiKey: key, model: model, instruction: instruction)
                self.finish(answer: text, error: nil)
            } catch {
                self.finish(answer: nil, error: error.localizedDescription)
            }
        }
    }

    private func finish(answer: String?, error: String?) {
        Shared.publish(answer: answer, error: error)
        Shared.notify(answer != nil ? "Cursor AI" : "Cursor AI - problem", answer ?? error ?? "")
        lock.lock(); busy = false; lock.unlock()
    }

    /// Orient, downscale to <= 1568 px on the long edge (keeps memory small), JPEG.
    private func encode(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation) -> Data? {
        var image = CIImage(cvPixelBuffer: pixels).oriented(orientation)
        let longest = max(image.extent.width, image.extent.height)
        if longest > 1568 {
            let s = 1568 / longest
            image = image.transformed(by: CGAffineTransform(scaleX: s, y: s))
        }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        return ctx.jpegRepresentation(of: image, colorSpace: space,
                                      options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.7])
    }
}
