import SwiftUI
import AppIntents
import UserNotifications

@main
struct CursorAIApp: App {
    init() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

/// "Ask Claude about the screen" - run it from a Shortcut, Control Center, the Home Screen, or the Action Button.
/// It does not open the app: it just signals the running broadcast to send its newest frame.
struct AskScreenIntent: AppIntent {
    static var title: LocalizedStringResource = "Ask Claude about the screen"
    static var description = IntentDescription("Sends the current screen to Claude and shows the answer.")
    static var openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult {
        if Shared.broadcastRunning {
            DarwinNotify.post(Shared.captureName)
        } else {
            Shared.notify("Cursor AI", "Start the broadcast first: open Cursor AI and tap the broadcast button.")
        }
        return .result()
    }
}

struct CursorAIShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AskScreenIntent(),
                    phrases: ["Ask \(.applicationName)", "\(.applicationName) screen"],
                    shortTitle: "Ask about screen",
                    systemImageName: "viewfinder")
    }
}
