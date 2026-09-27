import SwiftUI
import AppKit

private struct TopologyHost: Identifiable {
    let id: String
    let displayName: String
    let sshAlias: String
    let kind: String
    let capabilities: [String]
}

private enum TopologyCommand {
    static let executable = NSHomeDirectory() + "/bin/tproj"

    static func run(_ arguments: [String]) throws -> String {
        guard FileManager.default.isExecutableFile(atPath: executable) else {
            throw NSError(domain: "tproj topology", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Install tproj in ~/bin"])
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = [NSHomeDirectory() + "/bin", "/opt/homebrew/bin", "/usr/local/bin", environment["PATH"] ?? "/usr/bin:/bin"].joined(separator: ":")
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        guard process.terminationStatus == 0 else {
            throw NSError(domain: "tproj topology", code: Int(process.terminationStatus),
                          userInfo: [NSLocalizedDescriptionKey: output.isEmpty ? "Command failed" : output])
        }
        return output
    }
}

struct TopologyView: View {
    let onModeChanged: (String) -> Void
    @State private var mode = "standalone"
    @State private var effectiveMode = "standalone"
    @State private var hosts: [TopologyHost] = []
    @State private var host = ""
    @State private var hostName = ""
    @State private var busy = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Computers").font(.title3.bold())
                    Text("Choose whether this workspace uses this Mac only or multiple Macs.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Refresh") { refresh() }.disabled(busy)
            }
            Picker("Mode", selection: Binding(get: { mode }, set: { setMode($0) })) {
                Text("This Mac only").tag("standalone")
                Text("Multiple Macs").tag("multi")
            }
            .pickerStyle(.segmented)
            Text(effectiveMode == "standalone" ? "Remote computers stay configured but are not contacted." : "Remote computers are available for this workspace.")
                .font(.caption).foregroundStyle(.secondary)

            GroupBox("Remote computers") {
                VStack(alignment: .leading, spacing: 8) {
                    if mode == "standalone" {
                        Text(hosts.isEmpty ? "No remote computers saved." : "\(hosts.count) remote computer(s) saved. Switch to Multiple Macs to manage them.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 8) {
                    if hosts.isEmpty {
                        Text("No remote computers configured.").font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(hosts) { item in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(item.displayName.isEmpty ? item.sshAlias : item.displayName)
                                Text(item.sshAlias).font(.caption.monospaced()).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(item.kind == "remote" ? "Remote" : "Local").font(.caption).foregroundStyle(.secondary)
                            Button("Check") { check(item.sshAlias) }.disabled(busy)
                            Button("Remove", role: .destructive) { remove(item.sshAlias) }.disabled(busy)
                        }
                    }
                    Divider()
                    HStack {
                        TextField("SSH alias", text: $host)
                        TextField("Display name", text: $hostName)
                        Button("Add") { add() }.disabled(busy || host.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                            }
                        }
                        .frame(maxHeight: 190)
                    }
                }
                .padding(4)
            }
            if let errorMessage {
                Text(errorMessage).font(.caption).foregroundStyle(.red).textSelection(.enabled)
            }
            Spacer()
        }
        .padding(18)
        .frame(width: 560, height: 430)
        .onAppear { refresh() }
    }

    private func execute(_ arguments: [String], completion: @escaping (String) -> Void = { _ in }) {
        busy = true; errorMessage = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try TopologyCommand.run(arguments) }
            DispatchQueue.main.async {
                busy = false
                switch result {
                case .success(let output): completion(output)
                case .failure(let error): errorMessage = error.localizedDescription
                }
            }
        }
    }

    private func refresh() {
        execute(["topology", "status", "--json"]) { output in
            if let object = try? JSONSerialization.jsonObject(with: Data(output.utf8)) as? [String: Any] {
                mode = object["configured_mode"] as? String ?? object["mode"] as? String ?? "standalone"
                effectiveMode = object["effective_mode"] as? String ?? mode
            }
            execute(["host", "list", "--json"]) { parseHosts($0) }
        }
    }

    private func parseHosts(_ output: String) {
        guard let value = try? JSONSerialization.jsonObject(with: Data(output.utf8)) else { return }
        let rows: [[String: Any]]
        if let array = value as? [[String: Any]] { rows = array }
        else { rows = (value as? [String: Any])?["hosts"] as? [[String: Any]] ?? [] }
        hosts = rows.compactMap { row in
            let alias = row["ssh_alias"] as? String ?? row["id"] as? String ?? ""
            guard !alias.isEmpty else { return nil }
            return TopologyHost(id: row["id"] as? String ?? alias,
                                displayName: row["display_name"] as? String ?? "",
                                sshAlias: alias,
                                kind: row["kind"] as? String ?? "remote",
                                capabilities: row["capabilities"] as? [String] ?? [])
        }
    }

    private func setMode(_ value: String) {
        mode = value
        execute(["topology", "set", value]) { _ in
            effectiveMode = value
            onModeChanged(value)
            refresh()
        }
    }

    private func add() {
        let alias = host.trimmingCharacters(in: .whitespacesAndNewlines)
        var args = ["host", "add", alias]
        let name = hostName.trimmingCharacters(in: .whitespacesAndNewlines)
        if !name.isEmpty { args += ["--name", name] }
        execute(args) { _ in host = ""; hostName = ""; refresh() }
    }

    private func remove(_ alias: String) { execute(["host", "remove", alias]) { _ in refresh() } }
    private func check(_ alias: String) { execute(["host", "check", alias]) { _ in refresh() } }
}
