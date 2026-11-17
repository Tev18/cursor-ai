import Foundation
import UserNotifications

/// Settings and answer state shared by the app and the broadcast extension (App Group), plus helpers.
enum Shared {
    static let group = "group.com.yousef.cursorai"
    static let captureName = "com.yousef.cursorai.capture"   // app/Shortcut -> extension: "grab the screen and ask"
    static let answerName = "com.yousef.cursorai.answer"     // extension -> app: "new answer / status"
    static let defaultInstruction = "Reply with only the final answer — no explanation, no reasoning, no extra words. Answer this image:"
    static let models = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"]

    static var defaults: UserDefaults { UserDefaults(suiteName: group) ?? .standard }

    static var apiKey: String {
        get { defaults.string(forKey: "apiKey") ?? "" }
        set { defaults.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "apiKey") }
    }
    static var model: String {
        get { defaults.string(forKey: "model") ?? models[0] }
        set { defaults.set(newValue, forKey: "model") }
    }
    static var instruction: String {
        get { defaults.string(forKey: "instruction") ?? defaultInstruction }
        set { defaults.set(newValue, forKey: "instruction") }
    }
    /// Answer text size 0.5 ... 1.5 (the "Popup Size" setting).
    static var popupScale: Double {
        get { let v = defaults.double(forKey: "popupScale"); return v == 0 ? 1.0 : min(1.5, max(0.5, v)) }
        set { defaults.set(newValue, forKey: "popupScale") }
    }
    static var lastAnswer: String {
        get { defaults.string(forKey: "lastAnswer") ?? "" }
        set { defaults.set(newValue, forKey: "lastAnswer") }
    }
    static var lastError: String {
        get { defaults.string(forKey: "lastError") ?? "" }
        set { defaults.set(newValue, forKey: "lastError") }
    }
    static var lastAnswerAt: Double {
        get { defaults.double(forKey: "lastAnswerAt") }
        set { defaults.set(newValue, forKey: "lastAnswerAt") }
    }
    /// "idle" | "thinking"
    static var state: String {
        get { defaults.string(forKey: "state") ?? "idle" }
        set { defaults.set(newValue, forKey: "state") }
    }
    static var broadcastRunning: Bool {
        get { defaults.bool(forKey: "broadcastRunning") }
        set { defaults.set(newValue, forKey: "broadcastRunning") }
    }

    static func publish(answer: String?, error: String?) {
        if let answer { lastAnswer = answer; lastError = "" }
        if let error { lastError = error }
        lastAnswerAt = Date().timeIntervalSince1970
        state = "idle"
        DarwinNotify.post(answerName)
    }

    static func notify(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = String(body.prefix(900))
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}

enum DarwinNotify {
    static func post(_ name: String) {
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                                             CFNotificationName(name as CFString), nil, nil, true)
    }
}

/// Listens for a Darwin (cross-process) notification while this object is alive.
final class DarwinObserver {
    private let name: String
    let handler: () -> Void

    init(name: String, handler: @escaping () -> Void) {
        self.name = name
        self.handler = handler
        CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
                                        Unmanaged.passUnretained(self).toOpaque(),
                                        { _, observer, _, _, _ in
                                            guard let observer else { return }
                                            Unmanaged<DarwinObserver>.fromOpaque(observer).takeUnretainedValue().handler()
                                        },
                                        name as CFString, nil, .deliverImmediately)
    }

    deinit {
        CFNotificationCenterRemoveObserver(CFNotificationCenterGetDarwinNotifyCenter(),
                                           Unmanaged.passUnretained(self).toOpaque(),
                                           CFNotificationName(name as CFString), nil)
    }
}

enum ClaudeError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let m) = self { return m }; return nil }
}

enum ClaudeClient {
    static func ask(jpeg: Data, apiKey: String, model: String, instruction: String, maxTokens: Int = 4096) async throws -> String {
        guard !apiKey.isEmpty else { throw ClaudeError.message("Add your Claude API key in the Cursor AI app first.") }
        var req = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
        req.httpMethod = "POST"
        req.timeoutInterval = 90
        req.setValue(apiKey, forHTTPHeaderField: "x-api-key")
        req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        req.setValue("application/json", forHTTPHeaderField: "content-type")
        let body: [String: Any] = [
            "model": model,
            "max_tokens": maxTokens,
            "messages": [[
                "role": "user",
                "content": [
                    ["type": "image", "source": ["type": "base64", "media_type": "image/jpeg", "data": jpeg.base64EncodedString()]],
                    ["type": "text", "text": instruction],
                ],
            ]],
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await URLSession.shared.data(for: req)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code != 200 {
            let msg = ((json?["error"] as? [String: Any])?["message"] as? String) ?? "HTTP \(code)"
            throw ClaudeError.message(msg)
        }
        let blocks = (json?["content"] as? [[String: Any]]) ?? []
        let text = blocks.compactMap { $0["type"] as? String == "text" ? $0["text"] as? String : nil }.joined(separator: "\n")
        return text.isEmpty ? "(no answer)" : text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
