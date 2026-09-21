import AppKit
import WebKit

struct CommandFailure: Error, LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

// Reuse Apple's released runtime; this app only owns its lifecycle and UI.
final class Runtime: @unchecked Sendable {
    let resources = Bundle.main.resourceURL!
    let home = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/ArchiveBox Desktop")
    var root: URL { home.appendingPathComponent("runtime") }
    var cli: URL { resources.appendingPathComponent("runtime/bin/container") }
    let name = "archivebox-desktop-5797"
    let address = URL(string: "http://localhost:5797")!
    var ownsService = false

    func command(_ args: [String], allowFailure: Bool = false, logOutput: Bool = true) throws -> String {
        let process = Process()
        process.executableURL = cli
        process.arguments = args
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        try process.run()
        let bytes = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(decoding: bytes, as: UTF8.self)
        let log = home.appendingPathComponent("desktop.log")
        if logOutput, let handle = try? FileHandle(forWritingTo: log) {
            handle.seekToEndOfFile()
            handle.write(Data(("\n> container " + args.joined(separator: " ") + "\n" + output).utf8))
            try? handle.close()
        }
        if process.terminationStatus != 0 && !allowFailure {
            throw CommandFailure(message: "container \(args.joined(separator: " "))\n\(output)")
        }
        return output
    }

    func start(progress: @escaping @Sendable (String) -> Void) async throws {
        let fm = FileManager.default
        try fm.createDirectory(at: home.appendingPathComponent("data"), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: home.appendingPathComponent("desktop.log").path) {
            fm.createFile(atPath: home.appendingPathComponent("desktop.log").path, contents: nil)
        }
        let status = try command(["system", "status", "--format", "json"], allowFailure: true)
        if let json = status.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
           object["status"] as? String == "running" {
            let paths = object["paths"] as? [String: String]
            guard let path = paths?["appRoot"], URL(fileURLWithPath: path).standardizedFileURL == root.standardizedFileURL else {
                throw CommandFailure(message: "Apple Container is already running with another data directory. Quit its workloads and stop that service before opening this prototype. ArchiveBox has not changed it.")
            }
            ownsService = true
        } else {
            guard status.contains("\"unregistered\"") else {
                throw CommandFailure(message: "An Apple Container service is registered but unavailable. Resolve that service before starting ArchiveBox.\n\(status)")
            }
            progress("Starting the bundled Linux runtime…")
            _ = try command(["system", "start", "--app-root", root.path,
                             "--install-root", resources.appendingPathComponent("runtime").path,
                             "--disable-kernel-install"])
            ownsService = true
        }
        let marker = home.appendingPathComponent("imported-1.4.1-26cf885e")
        if !fm.fileExists(atPath: marker.path) {
            progress("Preparing ArchiveBox for its first launch…")
            _ = try command(["system", "kernel", "set", "--binary", resources.appendingPathComponent("vmlinux").path])
            _ = try command(["image", "load", "--input", resources.appendingPathComponent("images.tar").path])
            try Data().write(to: marker)
        }
        progress("Starting ArchiveBox…")
        let existing = try command(["list", "--all", "--format", "json"])
        let containers = (try JSONSerialization.jsonObject(with: Data(existing.utf8))) as? [[String: Any]] ?? []
        // Keep the legacy container and its root filesystem; both versions share /data.
        // Never run both against the same collection or stop the old app's runtime.
        if containers.contains(where: {
            ($0["configuration"] as? [String: Any])?["id"] as? String == "archivebox-desktop"
                && ($0["status"] as? [String: Any])?["state"] as? String != "stopped"
        }) {
            ownsService = false
            throw CommandFailure(message: "Quit the previous ArchiveBox prototype before opening this version. Your collection and previous container have been preserved.")
        }
        let container = containers.first { ($0["configuration"] as? [String: Any])?["id"] as? String == name }
        if let container {
            let config = container["configuration"] as? [String: Any] ?? [:]
            let ports = config["publishedPorts"] as? [[String: Any]] ?? []
            let mounts = config["mounts"] as? [[String: Any]] ?? []
            let process = config["initProcess"] as? [String: Any] ?? [:]
            let arguments = process["arguments"] as? [String] ?? []
            let environment = process["environment"] as? [String] ?? []
            guard ports.count == 1,
                  ports.first?["hostAddress"] as? String == "127.0.0.1",
                  ports.first?["hostPort"] as? Int == 5797,
                  ports.first?["containerPort"] as? Int == 5797,
                  ports.first?["proto"] as? String == "tcp",
                  ports.first?["count"] as? Int == 1,
                  mounts.contains(where: {
                      $0["destination"] as? String == "/data"
                          && $0["source"] as? String == home.appendingPathComponent("data").path
                  }),
                  Array(arguments.suffix(4)) == ["archivebox", "server", "--init", "0.0.0.0:5797"],
                  environment.contains("BASE_URL=http://localhost:5797") else {
                ownsService = false
                throw CommandFailure(message: "The existing ArchiveBox container has an unexpected configuration. It has not been started or changed. See desktop.log for details.")
            }
            if (container["status"] as? [String: Any])?["state"] as? String != "running" { _ = try command(["start", name]) }
        } else {
            _ = try command(["run", "--detach", "--name", name, "--cpus", "4", "--memory", "4G",
                             "--publish", "127.0.0.1:5797:5797",
                             "--volume", home.appendingPathComponent("data").path + ":/data",
                             "--env", "BASE_URL=http://localhost:5797", "archivebox/archivebox:dev",
                             "archivebox", "server", "--init", "0.0.0.0:5797"])
        }
        // Startup readiness, not a retry of failed operations. Surface the logs on timeout.
        let deadline = Date().addingTimeInterval(120)
        while Date() < deadline {
            var request = URLRequest(url: address)
            request.timeoutInterval = 2
            if let (_, response) = try? await URLSession.shared.data(for: request),
               let http = response as? HTTPURLResponse, (200..<400).contains(http.statusCode) { return }
            try await Task.sleep(for: .seconds(1))
        }
        throw CommandFailure(message: "ArchiveBox did not become ready.\n" + (try command(["logs", name], allowFailure: true)))
    }

    func stop() {
        guard ownsService else { return }
        _ = try? command(["stop", name], allowFailure: true)
        _ = try? command(["system", "stop"], allowFailure: true)
    }
}
