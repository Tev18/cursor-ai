import SwiftUI
import ReplayKit

let gold = Color(red: 0.831, green: 0.686, blue: 0.216)

struct BroadcastPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let v = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 56, height: 56))
        v.preferredExtension = (Bundle.main.bundleIdentifier ?? "com.yousef.cursorai") + ".broadcast"
        v.showsMicrophoneButton = false
        return v
    }
    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}

struct ContentView: View {
    @State private var apiKey = Shared.apiKey
    @State private var showKey = false
    @State private var model = Shared.model
    @State private var instruction = Shared.instruction
    @State private var scale = Shared.popupScale
    @State private var answer = Shared.lastAnswer
    @State private var error = Shared.lastError
    @State private var answeredAt = Shared.lastAnswerAt
    @State private var thinking = Shared.state == "thinking"
    @State private var running = Shared.broadcastRunning
    @State private var observer: DarwinObserver?

    var body: some View {
        NavigationStack {
            Form {
                Section("Answer") {
                    if thinking {
                        HStack { ProgressView(); Text("Asking Claude…").foregroundStyle(.secondary) }
                    } else if !error.isEmpty && answer.isEmpty {
                        Text(error).foregroundStyle(.red)
                    } else if answer.isEmpty {
                        Text("No answer yet. Start the broadcast, then run “Ask about screen”.").foregroundStyle(.secondary)
                    } else {
                        Text(answer)
                            .font(.system(size: 22 * scale, weight: .bold))
                            .textSelection(.enabled)
                        if !error.isEmpty { Text(error).font(.footnote).foregroundStyle(.red) }
                        if answeredAt > 0 {
                            Text(Date(timeIntervalSince1970: answeredAt).formatted(date: .omitted, time: .standard))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        Button("Copy answer") { UIPasteboard.general.string = answer }
                    }
                    Button {
                        if Shared.broadcastRunning { DarwinNotify.post(Shared.captureName) }
                        else { error = "Start the broadcast first." }
                    } label: { Label("Ask about the screen now", systemImage: "viewfinder") }
                        .disabled(thinking)
                }

                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Screen broadcast")
                            Text(running ? "Running (red indicator shows)" : "Off - tap the icon, then Start Broadcast")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        Spacer()
                        BroadcastPicker().frame(width: 56, height: 56)
                    }
                } header: { Text("Capture") } footer: {
                    Text("While it runs, the newest screen frame is kept in memory only. There is no flash and no sound. Add the “Ask about screen” Shortcut to Control Center, the Home Screen, or the Action Button to trigger it from any app. Open this app in Slide Over or Stage Manager to see answers floating over other apps.")
                }

                Section("Claude") {
                    HStack {
                        Group {
                            if showKey { TextField("API key", text: $apiKey) } else { SecureField("API key", text: $apiKey) }
                        }
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button(showKey ? "Hide" : "Show") { showKey.toggle() }.buttonStyle(.borderless)
                    }
                    Picker("Model", selection: $model) {
                        ForEach(Shared.models, id: \.self) { Text($0).tag($0) }
                    }
                    VStack(alignment: .leading) {
                        Text("Prompt").font(.footnote).foregroundStyle(.secondary)
                        TextEditor(text: $instruction).frame(minHeight: 90)
                    }
                    Button("Reset prompt") { instruction = Shared.defaultInstruction }
                }

                Section("Appearance") {
                    HStack {
                        Text("Popup Size")
                        Spacer()
                        Text("\(Int((scale * 100).rounded()))%").foregroundStyle(gold).bold()
                    }
                    Slider(value: $scale, in: 0.5...1.5, step: 0.05)
                }
            }
            .navigationTitle("Cursor AI")
            .tint(gold)
        }
        .onChange(of: apiKey) { _, v in Shared.apiKey = v }
        .onChange(of: model) { _, v in Shared.model = v }
        .onChange(of: instruction) { _, v in Shared.instruction = v }
        .onChange(of: scale) { _, v in Shared.popupScale = (v * 20).rounded() / 20 }
        .onAppear {
            refresh()
            observer = DarwinObserver(name: Shared.answerName) { DispatchQueue.main.async { refresh() } }
        }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in refresh() }
    }

    private func refresh() {
        answer = Shared.lastAnswer
        error = Shared.lastError
        answeredAt = Shared.lastAnswerAt
        thinking = Shared.state == "thinking"
        running = Shared.broadcastRunning
    }
}
