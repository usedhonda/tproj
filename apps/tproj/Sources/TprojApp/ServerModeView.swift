import SwiftUI

private struct ServerProject: Identifiable {
    let alias: String
    let path: String
    let cc: String
    let cdx: String

    var id: String { path }
}

private enum ServerCommand {
    static let executable = NSHomeDirectory() + "/bin/tproj-remote-host"

    static func run(_ arguments: [String]) throws -> String {
        guard FileManager.default.isExecutableFile(atPath: executable) else {
            throw NSError(domain: "tproj server", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Install tproj-remote-host at ~/bin/tproj-remote-host"])
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
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
    @State private var alias = ""
    @State private var busy = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Server projects").font(.title2.bold())
                Spacer()
                Button("Refresh") { refresh() }.disabled(busy)
            }

            HStack {
                TextField("Absolute project path", text: $path)
                TextField("Alias", text: $alias).frame(width: 140)
                Button("Add") { addProject() }
                    .disabled(busy || !path.hasPrefix("/") || alias.isEmpty)
            }

            if let errorMessage {
                Text(errorMessage).foregroundStyle(.red).textSelection(.enabled)
            }

            List(projects) { project in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(project.alias).font(.headline)
                        Spacer()
                        Button("Unregister") {
                            perform(["unregister", "--path", project.path])
                        }.disabled(busy)
                    }
                    Text(project.path).font(.caption).foregroundStyle(.secondary)
                        .textSelection(.enabled)
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
                    Text("No projects. Add an absolute path and alias.")
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
        let newAlias = alias
        perform(["register", "--path", newPath, "--alias", newAlias]) {
            path = ""
            alias = ""
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
            DispatchQueue.main.async {
                busy = false
                switch result {
                case .success(let output):
                    projects = output.split(separator: "\n").dropFirst().compactMap { line in
                        let fields = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                        guard fields.count == 5 else { return nil }
                        return ServerProject(alias: fields[1], path: fields[2], cc: fields[3], cdx: fields[4])
                    }
                case .failure(let error):
                    errorMessage = error.localizedDescription
                }
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
