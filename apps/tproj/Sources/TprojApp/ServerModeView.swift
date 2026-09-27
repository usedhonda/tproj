import SwiftUI
import CryptoKit
import TprojLogic

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
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = [NSHomeDirectory() + "/bin", "/opt/homebrew/bin", "/usr/local/bin", environment["PATH"] ?? "/usr/bin:/bin"]
            .joined(separator: ":")
        process.environment = environment
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
    @State private var memoryStatus: MonitorStatus?
    @State private var memoryError: String?
    @State private var memoryUpdatedAt: Date?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Tproj")
                            .font(GhosttyTheme.current.font(size: 20, weight: .bold))
                        Text("SERVER  ·  This Mac")
                            .font(GhosttyTheme.current.font(size: 11, weight: .semibold, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.accentCyan)
                    }
                    Spacer()
                    ActionButton("Refresh", isEnabled: !busy, dense: true) { refresh() }
                }

                SectionHeader(title: "Memory")
                Card { memoryContent }

                SectionHeader(title: "Server Projects")
                Card {
                    HStack {
                        TextField("Absolute project path", text: $path)
                            .textFieldStyle(.roundedBorder)
                        ActionButton("Add", tone: .primary, isEnabled: !busy && path.hasPrefix("/"), dense: true) {
                            addProject()
                        }
                    }
                }

                if let errorMessage {
                    Text(errorMessage)
                        .foregroundStyle(GhosttyTheme.current.accentRed)
                        .textSelection(.enabled)
                }

                if projects.isEmpty && !busy {
                    Card { Text("No projects. Add an absolute path.").foregroundStyle(GhosttyTheme.current.textSecondary) }
                }
                ForEach(projects) { project in
                    Card { projectContent(project) }
                }
            }
            .foregroundStyle(GhosttyTheme.current.textPrimary)
            .padding(16)
        }
        .background(GhosttyTheme.current.background.ignoresSafeArea())
        .onAppear { refresh() }
        .onReceive(Timer.publish(every: 8, on: .main, in: .common).autoconnect()) { _ in
            refreshMemory()
        }
    }

    @ViewBuilder
    private var memoryContent: some View {
        if let status = memoryStatus, status.system.totalMB > 0 {
            let system = status.system
            let usedFraction = min(1, max(0, Double(system.usedMB) / Double(system.totalMB)))
            HStack {
                Text("Free \(system.freeMB) MB")
                    .foregroundStyle(system.freeMB < 1024 ? GhosttyTheme.current.accentRed : GhosttyTheme.current.accentGreen)
                Spacer()
                Text("Used \(system.usedMB) / \(system.totalMB) MB")
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            }
            .font(GhosttyTheme.current.font(size: 12, weight: .semibold, monospaced: true))
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    GhosttyTheme.current.foreground.opacity(0.1)
                    GhosttyTheme.current.accentCyan.frame(width: geometry.size.width * usedFraction)
                }
            }
            .frame(height: 5)
            .clipShape(RoundedRectangle(cornerRadius: 3))

            let hasPaneData = !status.collector.errors.contains { $0.contains("tmux list-panes failed") }
            let ccMB = status.panes.filter { $0.agentType == "cc" }.reduce(0) { $0 + $1.rssMB }
            let cdxMB = status.panes.filter { $0.agentType == "codex" }.reduce(0) { $0 + $1.rssMB }
            HStack {
                Text(hasPaneData ? "CC \(ccMB) MB  ·  Cdx \(cdxMB) MB" : "CC / Cdx pane data unavailable")
                Spacer()
                if let memoryUpdatedAt {
                    Text(memoryUpdatedAt, style: .time)
                }
            }
            .font(GhosttyTheme.current.font(size: 11, weight: .medium, monospaced: true))
            .foregroundStyle(GhosttyTheme.current.textSecondary)
            if !status.collector.errors.isEmpty {
                Text(status.collector.errors.joined(separator: " · "))
                    .foregroundStyle(GhosttyTheme.current.accentYellow)
                    .textSelection(.enabled)
            }
        } else {
            Text(memoryError ?? "Loading memory monitor...")
                .foregroundStyle(GhosttyTheme.current.textSecondary)
                .textSelection(.enabled)
        }
    }

    private func projectContent(_ project: ServerProject) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(URL(fileURLWithPath: project.path).lastPathComponent)
                    .font(GhosttyTheme.current.font(size: 14, weight: .semibold))
                Spacer()
                ActionButton("Unregister", tone: .danger, isEnabled: !busy, dense: true) {
                    perform(["unregister", "--path", project.path])
                }
            }
            Text(project.path)
                .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                .foregroundStyle(GhosttyTheme.current.textTertiary)
                .textSelection(.enabled)

            let projectName = URL(fileURLWithPath: project.path).lastPathComponent
            let nameIsUnique = projects.filter { URL(fileURLWithPath: $0.path).lastPathComponent == projectName }.count == 1
            let panes = nameIsUnique ? (memoryStatus?.panes.filter { $0.project == projectName } ?? []) : []
            if nameIsUnique && memoryStatus != nil && memoryStatus?.collector.errors.contains(where: { $0.contains("tmux list-panes failed") }) == false {
                let ccMB = panes.filter { $0.agentType == "cc" }.reduce(0) { $0 + $1.rssMB }
                let cdxMB = panes.filter { $0.agentType == "codex" }.reduce(0) { $0 + $1.rssMB }
                Text("Memory  CC \(ccMB) MB  ·  Cdx \(cdxMB) MB")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            }
            HStack {
                Text("CC cache: \(cacheState[project.path] ?? "unobserved")")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
                Spacer()
                Menu("Keep warm \(cacheHours[project.path] ?? 0)h") {
                    ForEach([0, 1, 3, 6, 12], id: \.self) { hours in
                        Button(hours == 0 ? "Off" : "\(hours) hours") {
                            setCacheHours(path: project.path, hours: hours)
                        }
                    }
                }
            }
            HStack(spacing: 12) {
                roleControls("CC", role: "cc", status: project.cc, path: project.path)
                roleControls("Cdx", role: "cdx", status: project.cdx, path: project.path)
            }
        }
    }

    private func roleControls(_ title: String, role: String, status: String, path: String) -> some View {
        HStack(spacing: 4) {
            Text("\(title): \(status)")
                .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                .foregroundStyle(status == "running" ? GhosttyTheme.current.accentGreen : GhosttyTheme.current.textSecondary)
            ActionButton("Start", isEnabled: !busy && status != "running" && status != "occupied", dense: true) {
                perform(["ensure", "--path", path, "--role", role])
            }
            ActionButton("Stop", tone: .danger, isEnabled: !busy && status != "stopped", dense: true) {
                perform(["stop", "--path", path, "--role", role])
            }
            ActionButton("Attach", tone: .primary, isEnabled: !busy && status == "running", dense: true) {
                attach(path: path, role: role)
            }
        }
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
        refreshMemory()
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

    private func refreshMemory() {
        DispatchQueue.global(qos: .utility).async {
            let result = Result {
                let output = try ServerCommand.run(["--json"], helper: NSHomeDirectory() + "/bin/tproj-mem-json")
                return try JSONDecoder().decode(MonitorStatus.self, from: Data(output.utf8))
            }
            DispatchQueue.main.async {
                switch result {
                case .success(let status):
                    memoryStatus = status
                    memoryUpdatedAt = Date()
                    memoryError = nil
                case .failure(let error):
                    memoryError = error.localizedDescription
                    memoryStatus = nil
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
