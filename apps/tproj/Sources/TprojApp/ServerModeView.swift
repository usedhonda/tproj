import SwiftUI
import CryptoKit

private struct ServerProject: Identifiable {
    let path: String
    let cc: String
    let cdx: String

    var id: String { path }
}

private enum ServerCommand {
    static let executable = NSHomeDirectory() + "/bin/tproj-remote-host"

    static func run(_ arguments: [String], helper: String = executable) throws -> String {
        guard FileManager.default.isExecutableFile(atPath: helper) else {
            throw NSError(domain: "tproj server", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Install \(URL(fileURLWithPath: helper).lastPathComponent) in ~/bin"])
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: helper)
        process.arguments = arguments
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let message = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        guard process.terminationStatus == 0 else {
            throw NSError(domain: "tproj server", code: Int(process.terminationStatus),
                          userInfo: [NSLocalizedDescriptionKey: message.isEmpty ? "Command failed" : message])
        }
        return message
    }

    static func attach(path: String, role: String) throws {
        // Let Terminal own the interactive tmux attachment; no shell is used for
        // catalog or lifecycle commands. Quote each shell argument separately.
        let command = ([executable, "attach", "--path", path, "--role", role])
            .map { "'" + $0.replacingOccurrences(of: "'", with: "'\\''") + "'" }
            .joined(separator: " ")
        let script = "tell application \"Terminal\" to do script \"" +
            command.replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "\"", with: "\\\"") + "\""
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        let output = Pipe()
        process.standardError = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let message = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            throw NSError(domain: "tproj server", code: Int(process.terminationStatus),
                          userInfo: [NSLocalizedDescriptionKey: message.isEmpty ? "Could not open Terminal" : message])
        }
    }
}

struct ServerModeView: View {
    @State private var projects: [ServerProject] = []
    @State private var path = ""
    @State private var busy = false
    @State private var errorMessage: String?
    @State private var cacheHours: [String: Int] = [:]
    @State private var cacheState: [String: String] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Server projects").font(.title2.bold())
                Spacer()
                Button("Refresh") { refresh() }.disabled(busy)
            }

            HStack {
                TextField("Absolute project path", text: $path)
                Button("Add") { addProject() }
                    .disabled(busy || !path.hasPrefix("/"))
            }

            if let errorMessage {
                Text(errorMessage).foregroundStyle(.red).textSelection(.enabled)
            }

            List(projects) { project in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(URL(fileURLWithPath: project.path).lastPathComponent).font(.headline)
                        Spacer()
                        Button("Unregister") {
                            perform(["unregister", "--path", project.path])
                        }.disabled(busy)
                    }
                    Text(project.path).font(.caption).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    HStack {
                        Text("CC cache: \(cacheState[project.path] ?? "unobserved")")
                            .font(.caption)
                        Spacer()
                        Menu("Keep warm \(cacheHours[project.path] ?? 0)h") {
                            ForEach([0, 1, 3, 6, 12], id: \.self) { hours in
                                Button(hours == 0 ? "Off" : "\(hours) hours") {
                                    setCacheHours(path: project.path, hours: hours)
                                }
                            }
                        }
                    }
                    HStack(spacing: 8) {
                        roleControls("CC", role: "cc", status: project.cc, path: project.path)
                        Spacer(minLength: 12)
                        roleControls("Cdx", role: "cdx", status: project.cdx, path: project.path)
                    }
                }
                .padding(.vertical, 5)
            }
            .overlay {
                if projects.isEmpty && !busy {
                    Text("No projects. Add an absolute path.")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(16)
        .onAppear { refresh() }
    }

    private func roleControls(_ title: String, role: String, status: String, path: String) -> some View {
        HStack(spacing: 5) {
            Text("\(title): \(status)").font(.caption)
            Button("Start") { perform(["ensure", "--path", path, "--role", role]) }
                .disabled(busy || status == "running" || status == "occupied")
            Button("Stop") { perform(["stop", "--path", path, "--role", role]) }
                .disabled(busy || status == "stopped")
            Button("Attach") { attach(path: path, role: role) }
                .disabled(busy || status != "running")
        }
        .buttonStyle(.borderless)
    }

    private func addProject() {
        let newPath = path
        perform(["register", "--path", newPath]) {
            path = ""
        }
    }

    private func perform(_ arguments: [String], onSuccess: (() -> Void)? = nil) {
        busy = true
        errorMessage = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try ServerCommand.run(arguments) }
            DispatchQueue.main.async {
                busy = false
                switch result {
                case .success:
                    onSuccess?()
                    refresh()
                case .failure(let error):
                    errorMessage = error.localizedDescription
                }
            }
        }
    }

    private func refresh() {
        busy = true
        errorMessage = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try ServerCommand.run(["list"]) }
            let cacheResult = Result {
                try ServerCommand.run(["status"], helper: NSHomeDirectory() + "/bin/tproj-remote-cache")
            }
            DispatchQueue.main.async {
                busy = false
                switch result {
                case .success(let output):
                    projects = output.split(separator: "\n").dropFirst().compactMap { line in
                        let fields = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                        guard fields.count == 5 else { return nil }
                        return ServerProject(path: fields[2], cc: fields[3], cdx: fields[4])
                    }
                    if case .success(let cacheOutput) = cacheResult,
                       let rows = try? JSONSerialization.jsonObject(with: Data(cacheOutput.utf8)) as? [[String: Any]] {
                        cacheHours = [:]
                        cacheState = [:]
                        for row in rows where row["role"] as? String == "cc" {
                            guard let id = row["id"] as? String,
                                  let path = projects.first(where: { ServerModeView.catalogID($0.path) == id })?.path else { continue }
                            cacheHours[path] = row["hours"] as? Int ?? 0
                            cacheState[path] = row["state"] as? String ?? "unobserved"
                        }
                    }
                case .failure(let error):
                    errorMessage = error.localizedDescription
                }
            }
        }
    }

    private static func catalogID(_ path: String) -> String {
        let digest = SHA256.hash(data: Data(path.utf8))
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
    }

    private func setCacheHours(path: String, hours: Int) {
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result {
                try ServerCommand.run(["set", "--path", path, "--role", "cc", "--hours", String(hours)],
                                      helper: NSHomeDirectory() + "/bin/tproj-remote-cache")
            }
            DispatchQueue.main.async {
                busy = false
                if case .failure(let error) = result { errorMessage = error.localizedDescription }
                else { refresh() }
            }
        }
    }

    private func attach(path: String, role: String) {
        busy = true
        errorMessage = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try ServerCommand.attach(path: path, role: role) }
            DispatchQueue.main.async {
                busy = false
                if case .failure(let error) = result { errorMessage = error.localizedDescription }
            }
        }
    }
}
