import AppKit
import SwiftUI
import SwiftTerm

struct ContainerSample: Sendable {
    var state: String
    var cpuUsec: Double?
    var memory: Int64?
    var processes: Int?
    var error: String?
    var time = ProcessInfo.processInfo.systemUptime
}

extension Runtime {
    func sample() -> ContainerSample {
        guard ownsService else { return ContainerSample(state: "unavailable", error: "ArchiveBox does not own a running container service.") }
        do {
            let output = try command(["list", "--all", "--format", "json"], logOutput: false)
            let rows = try JSONSerialization.jsonObject(with: Data(output.utf8)) as? [[String: Any]] ?? []
            guard let row = rows.first(where: { $0["id"] as? String == name }) else {
                return ContainerSample(state: "stopped")
            }
            let state = (row["status"] as? [String: Any])?["state"] as? String ?? "unknown"
            guard state == "running" else { return ContainerSample(state: state) }
            let statsOutput = try command(["stats", "--no-stream", "--format", "json", name], logOutput: false)
            let stats = try JSONSerialization.jsonObject(with: Data(statsOutput.utf8)) as? [[String: Any]]
            guard let values = stats?.first else {
                return ContainerSample(state: state, error: "Runtime returned no resource statistics.")
            }
            return ContainerSample(state: state,
                cpuUsec: (values["cpuUsageUsec"] as? NSNumber)?.doubleValue,
                memory: (values["memoryUsageBytes"] as? NSNumber)?.int64Value,
                processes: (values["numProcesses"] as? NSNumber)?.intValue)
        } catch { return ContainerSample(state: "unavailable", error: error.localizedDescription) }
    }

    func collectionSize() throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/du")
        process.arguments = ["-sk", home.appendingPathComponent("data").path]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let result = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        guard process.terminationStatus == 0,
              let first = result.split(whereSeparator: { $0.isWhitespace }).first,
              let kib = Int64(first) else { throw CommandFailure(message: result) }
        return ByteCountFormatter.string(fromByteCount: kib * 1024, countStyle: .file)
    }
}

@MainActor
final class SettingsModel: ObservableObject {
    @Published var state = "Starting"
    @Published var cpu = "—"
    @Published var ram = "—"
    @Published var processes = "—"
    @Published var disk = "Calculating…"
    @Published var detail = ""
    @Published var ready = false
    @Published var terminalConnected = false
    let runtime: Runtime
    let terminal = LocalProcessTerminalView(frame: NSRect(x: 0, y: 0, width: 1000, height: 350))
    private var polling: Task<Void, Never>?
    private var sizing: Task<Void, Never>?
    private var previous: ContainerSample?
    private var expectedRunning = false
    private var startupFinished = false
    private var startupError: String?
    private var lastSizeRefresh = Date.distantPast
    var terminalDelegate: TerminalDelegate!

    init(runtime: Runtime) {
        self.runtime = runtime
        terminal.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
        terminal.nativeForegroundColor = .textColor
        terminal.nativeBackgroundColor = .textBackgroundColor
        terminalDelegate = TerminalDelegate(model: self)
        terminal.processDelegate = terminalDelegate
    }

    func didStart(error: String? = nil) {
        startupFinished = true
        startupError = error
        expectedRunning = error == nil
        state = error == nil ? "Running" : "Failed to start"
        ready = error == nil
        detail = error ?? ""
    }

    func monitor() {
        guard polling == nil else { return }
        refreshSize()
        polling = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if Date().timeIntervalSince(lastSizeRefresh) >= 30 { refreshSize() }
                if startupFinished {
                    let value = await Task.detached { [runtime] in runtime.sample() }.value
                    if Task.isCancelled { return }
                    apply(value)
                }
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func pauseMonitoring() { polling?.cancel(); polling = nil; previous = nil }

    private func apply(_ sample: ContainerSample) {
        ready = sample.state == "running"
        if ready {
            state = "Running"
            detail = sample.error ?? "CPU: 100% = one core · RAM is container usage, not total host VM memory."
        } else if expectedRunning {
            state = "Crashed / stopped unexpectedly"
            detail = sample.error ?? "The container was running but is now \(sample.state). The runtime does not report an exit reason."
        } else {
            state = startupError == nil ? "Stopped" : "Failed to start"
            detail = startupError ?? sample.error ?? ""
        }
        cpu = "—"
        if ready, let before = previous, before.state == "running",
           let old = before.cpuUsec, let now = sample.cpuUsec, now >= old, sample.time > before.time {
            cpu = String(format: "%.1f%%", (now - old) / 1_000_000 / (sample.time - before.time) * 100)
        }
        ram = sample.memory.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .memory) } ?? "—"
        processes = sample.processes.map(String.init) ?? "—"
        previous = sample
    }

    func refreshSize() {
        guard sizing == nil else { return }
        lastSizeRefresh = Date()
        sizing = Task {
            do { disk = try await Task.detached { [runtime] in try runtime.collectionSize() }.value }
            catch { disk = "Unavailable" }
            sizing = nil
        }
    }

    func connectTerminal() {
        guard ready, !terminalConnected else { return }
        terminalConnected = true
        // The existing image entrypoint selects its writable unprivileged user and
        // environment. A PTY on both sides preserves password prompts and signals.
        terminal.startProcess(executable: runtime.cli.path,
            args: ["exec", "--interactive", "--tty", "--env", "TERM=xterm-256color",
                   "--workdir", "/data", runtime.name, "/app/bin/docker_entrypoint.sh",
                   "/bin/bash", "--noprofile", "--norc", "-i"],
            environment: ProcessInfo.processInfo.environment.map { "\($0.key)=\($0.value)" })
        terminal.window?.makeFirstResponder(terminal)
    }

    func shutdown() { pauseMonitoring(); sizing?.cancel(); terminal.terminate() }
}

final class TerminalDelegate: LocalProcessTerminalViewDelegate {
    weak var model: SettingsModel?
    init(model: SettingsModel) { self.model = model }
    func sizeChanged(source: LocalProcessTerminalView, newCols: Int, newRows: Int) {}
    func setTerminalTitle(source: LocalProcessTerminalView, title: String) {}
    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}
    func processTerminated(source: TerminalView, exitCode: Int32?) {
        Task { @MainActor [weak self] in self?.model?.terminalConnected = false }
    }
}

struct EmbeddedTerminal: NSViewRepresentable {
    let terminal: LocalProcessTerminalView
    func makeNSView(context: Context) -> LocalProcessTerminalView { terminal }
    func updateNSView(_ nsView: LocalProcessTerminalView, context: Context) {}
}

struct SettingsView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Settings").font(.largeTitle.bold())
            GroupBox {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Label(model.state, systemImage: model.ready ? "checkmark.circle.fill" : "exclamationmark.circle")
                            .foregroundStyle(model.ready ? Color.green : Color.secondary)
                        Spacer()
                        metric("CPU", model.cpu)
                        Spacer()
                        metric("RAM", model.ram)
                        Spacer()
                        metric("Processes", model.processes)
                    }
                    Text(model.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }.padding(8)
            } label: { Label("Container", systemImage: "shippingbox") }
            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("Size on disk: \(model.disk)")
                        Button("Refresh", systemImage: "arrow.clockwise") { model.refreshSize() }
                            .labelStyle(.iconOnly).help("Refresh collection disk usage")
                        Spacer()
                        Button("Open in Finder", systemImage: "folder") {
                            NSWorkspace.shared.open(model.runtime.home.appendingPathComponent("data"))
                        }
                    }
                    Text(model.runtime.home.appendingPathComponent("data").path)
                        .font(.system(.body, design: .monospaced)).textSelection(.enabled)
                }.padding(8)
            } label: { Label("Collection", systemImage: "externaldrive") }
            HStack {
                Label("Container Terminal", systemImage: "terminal").font(.headline)
                Spacer()
                Text(model.terminalConnected ? "Connected" : "Disconnected").foregroundStyle(.secondary)
                Button(model.terminalConnected ? "Connected" : "Connect") { model.connectTerminal() }
                    .disabled(!model.ready || model.terminalConnected)
            }
            Text("Create an admin: archivebox manage createsuperuser")
                .font(.system(.callout, design: .monospaced)).textSelection(.enabled)
            EmbeddedTerminal(terminal: model.terminal)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .textBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(.separator, lineWidth: 1))
                .accessibilityLabel("Container terminal")
        }
        .padding(24)
        .frame(minWidth: 760, minHeight: 650)
        .background(Color(nsColor: .windowBackgroundColor))
    }
    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.system(.title3, design: .monospaced)).monospacedDigit()
        }
    }
}
