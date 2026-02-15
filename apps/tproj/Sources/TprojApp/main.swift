import SwiftUI
import Foundation
import AppKit
import CoreMIDI
import UniformTypeIdentifiers

// MARK: - Ghostty Theme

private extension Color {
    func brighten(_ amount: Double) -> Color {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        guard let c = NSColor(self).usingColorSpace(.sRGB) else { return self }
        c.getRed(&r, green: &g, blue: &b, alpha: &a)
        return Color(red: min(Double(r) + amount, 1.0),
                     green: min(Double(g) + amount, 1.0),
                     blue: min(Double(b) + amount, 1.0))
    }
}

struct GhosttyTheme {
    let background: Color
    let foreground: Color
    let cursorColor: Color
    let selectionBg: Color
    let selectionFg: Color
    let palette: [Color]
    let fontFamily: String?
    let fontSize: CGFloat
    let backgroundOpacity: Double

    var backgroundLighter: Color { background.brighten(0.10) }
    var cardBackground: Color { background.brighten(0.04) }
    var cardBorder: Color { foreground.opacity(0.06) }
    var textPrimary: Color { foreground }
    var textSecondary: Color { foreground.opacity(0.7) }
    var textTertiary: Color { foreground.opacity(0.35) }
    var accentBlue: Color { palette.indices.contains(4) ? palette[4] : .blue }
    var accentRed: Color { palette.indices.contains(1) ? palette[1] : .red }
    var accentGreen: Color { palette.indices.contains(2) ? palette[2] : .green }
    var accentYellow: Color { palette.indices.contains(3) ? palette[3] : .yellow }
    var accentCyan: Color { palette.indices.contains(6) ? palette[6] : .cyan }

    func font(size: CGFloat, weight: Font.Weight, monospaced: Bool = false) -> Font {
        if let family = fontFamily,
           NSFontManager.shared.availableMembers(ofFontFamily: family) != nil {
            return Font.custom(family, size: size).weight(weight)
        }
        return Font.system(size: size, weight: weight, design: monospaced ? .monospaced : .default)
    }

    static let current = GhosttyConfigParser.load()

    static let fallback = GhosttyTheme(
        background: Color(red: 0.05, green: 0.06, blue: 0.08),
        foreground: .white,
        cursorColor: .white,
        selectionBg: Color(red: 0.3, green: 0.3, blue: 0.3),
        selectionFg: .white,
        palette: [
            Color(red: 0.27, green: 0.27, blue: 0.27), .red, .green, .orange,
            .blue, .purple, .cyan, Color(red: 0.75, green: 0.75, blue: 0.75),
            Color(red: 0.5, green: 0.5, blue: 0.5), .red, .green, .yellow,
            .blue, .purple, .cyan, .white
        ],
        fontFamily: nil,
        fontSize: 14,
        backgroundOpacity: 1.0
    )
}

enum GhosttyConfigParser {
    private struct ParsedConfig {
        var settings: [String: String] = [:]
        var palette: [Int: String] = [:]
    }

    static func load() -> GhosttyTheme {
        let home = NSHomeDirectory()
        let configPath = "\(home)/.config/ghostty/config"

        guard let config = parseFile(configPath) else { return .fallback }

        var merged = ParsedConfig()
        if let themeName = config.settings["theme"],
           let themeConfig = loadTheme(themeName, home: home) {
            merged.settings = themeConfig.settings
            merged.palette = themeConfig.palette
        }

        for (key, value) in config.settings { merged.settings[key] = value }
        for (index, hex) in config.palette { merged.palette[index] = hex }

        return buildTheme(from: merged)
    }

    private static func parseFile(_ filePath: String) -> ParsedConfig? {
        guard let content = try? String(contentsOfFile: filePath, encoding: .utf8) else { return nil }
        var config = ParsedConfig()
        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix("#") { continue }
            guard let eqIdx = trimmed.firstIndex(of: "=") else { continue }
            let key = trimmed[..<eqIdx].trimmingCharacters(in: .whitespaces)
            let rawValue = String(trimmed[trimmed.index(after: eqIdx)...]).trimmingCharacters(in: .whitespaces)
            if key == "palette" {
                if let innerEq = rawValue.firstIndex(of: "=") {
                    let idxStr = rawValue[..<innerEq].trimmingCharacters(in: .whitespaces)
                    let colorHex = String(rawValue[rawValue.index(after: innerEq)...]).trimmingCharacters(in: .whitespaces)
                    if let idx = Int(idxStr) { config.palette[idx] = colorHex }
                }
            } else {
                config.settings[key] = rawValue
            }
        }
        return config
    }

    private static func loadTheme(_ name: String, home: String) -> ParsedConfig? {
        let candidates = [
            "\(home)/.config/ghostty/themes/\(name)",
            "/Applications/Ghostty.app/Contents/Resources/ghostty/themes/\(name)"
        ]
        for candidatePath in candidates {
            if let config = parseFile(candidatePath),
               !config.settings.isEmpty || !config.palette.isEmpty {
                return config
            }
        }
        return nil
    }

    private static func buildTheme(from config: ParsedConfig) -> GhosttyTheme {
        var palette = GhosttyTheme.fallback.palette
        for (index, hex) in config.palette {
            if palette.indices.contains(index), let color = parseHex(hex) {
                palette[index] = color
            }
        }

        let bg = config.settings["background"].flatMap(parseHex) ?? GhosttyTheme.fallback.background
        let fg = config.settings["foreground"].flatMap(parseHex) ?? GhosttyTheme.fallback.foreground

        return GhosttyTheme(
            background: bg,
            foreground: fg,
            cursorColor: config.settings["cursor-color"].flatMap(parseHex) ?? fg,
            selectionBg: config.settings["selection-background"].flatMap(parseHex) ?? GhosttyTheme.fallback.selectionBg,
            selectionFg: config.settings["selection-foreground"].flatMap(parseHex) ?? fg,
            palette: palette,
            fontFamily: config.settings["font-family"],
            fontSize: config.settings["font-size"].flatMap { CGFloat(Double($0) ?? 14) } ?? 14,
            backgroundOpacity: config.settings["background-opacity"].flatMap(Double.init) ?? 1.0
        )
    }

    private static func parseHex(_ hex: String) -> Color? {
        var h = hex.trimmingCharacters(in: .whitespaces)
        if h.hasPrefix("#") { h = String(h.dropFirst()) }
        guard h.count == 6, let val = UInt64(h, radix: 16) else { return nil }
        return Color(
            red: Double((val >> 16) & 0xFF) / 255.0,
            green: Double((val >> 8) & 0xFF) / 255.0,
            blue: Double(val & 0xFF) / 255.0
        )
    }
}

// MARK: - Data Models

struct WorkspaceProject: Identifiable {
    let id = UUID()
    var path: String
    var type: String
    var host: String
    var alias: String
    var enabled: Bool

    var effectiveAlias: String {
        if !alias.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return alias
        }
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "(unnamed)" }
        return URL(fileURLWithPath: trimmed).lastPathComponent
    }

    var projectName: String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "(no-path)" }
        return URL(fileURLWithPath: trimmed).lastPathComponent
    }
}

struct LiveColumn: Identifiable {
    let id = UUID()
    var column: Int
    var projectPath: String
    var hostLabel: String
    var width: Int
    var left: Int
    var claudePaneID: String?
    var codexPaneID: String?
    var yaziPaneID: String?
    var terminalPaneID: String?

    var projectName: String {
        if projectPath.isEmpty { return "unknown" }
        return URL(fileURLWithPath: projectPath).lastPathComponent
    }
}

struct CommandResult {
    var exitCode: Int32
    var stdout: String
    var stderr: String
}

private struct MIDIBinding: Codable, Equatable {
    var statusNibble: UInt8
    var data1: UInt8
    var channel: UInt8
}

private struct StoredMIDIBinding: Codable {
    var slot: Int
    var binding: MIDIBinding
}

private enum MIDILearnStore {
    private static let key = "tproj.midi.learn.bindings.v1"

    static func load() -> [Int: MIDIBinding] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let items = try? JSONDecoder().decode([StoredMIDIBinding].self, from: data) else {
            return [:]
        }
        var result: [Int: MIDIBinding] = [:]
        for item in items where (1...16).contains(item.slot) {
            result[item.slot] = item.binding
        }
        return result
    }

    static func save(_ bindings: [Int: MIDIBinding]) {
        let items = bindings.keys.sorted().compactMap { slot -> StoredMIDIBinding? in
            guard let binding = bindings[slot] else { return nil }
            return StoredMIDIBinding(slot: slot, binding: binding)
        }
        guard let data = try? JSONEncoder().encode(items) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }
}

private final class MIDIPaneActivator {
    var onStatus: ((String) -> Void)?
    var onLearnStateChanged: ((Bool) -> Void)?
    var onSlotTriggered: ((Int) -> Void)?

    private var client = MIDIClientRef()
    private var inputPort = MIDIPortRef()
    private var connectedSources: [MIDIEndpointRef] = []
    private var bindings: [Int: MIDIBinding] = MIDILearnStore.load()
    private var isRunning = false
    private var learnStep = 1
    private var learning = false {
        didSet { onLearnStateChanged?(learning) }
    }
    private var lastLearnEventAt: Date = .distantPast
    private var lastLearnBinding: MIDIBinding?

    var isLearning: Bool { learning }

    func start() {
        guard !isRunning else { return }

        var createdClient = MIDIClientRef()
        let clientStatus = MIDIClientCreate("tproj-midi-client" as CFString, nil, nil, &createdClient)
        guard clientStatus == noErr else {
            onStatus?("MIDI init failed (client: \(clientStatus))")
            return
        }
        client = createdClient

        var createdPort = MIDIPortRef()
        let portStatus = MIDIInputPortCreateWithBlock(client, "tproj-midi-input" as CFString, &createdPort) { [weak self] packetList, _ in
            self?.handle(packetList: packetList)
        }
        guard portStatus == noErr else {
            onStatus?("MIDI init failed (port: \(portStatus))")
            MIDIClientDispose(client)
            client = 0
            return
        }
        inputPort = createdPort

        connectSources()
        isRunning = true
        if connectedSources.isEmpty {
            onStatus?("MIDI: no input source found")
        } else {
            onStatus?("MIDI connected (\(connectedSources.count) source)")
        }
    }

    func stop() {
        guard isRunning else { return }
        connectedSources.forEach { MIDIPortDisconnectSource(inputPort, $0) }
        connectedSources.removeAll()
        if inputPort != 0 {
            MIDIPortDispose(inputPort)
            inputPort = 0
        }
        if client != 0 {
            MIDIClientDispose(client)
            client = 0
        }
        learning = false
        isRunning = false
    }

    deinit {
        stop()
    }

    func toggleLearn() -> Bool {
        if learning {
            learning = false
            learnStep = 1
            onStatus?("MIDI Learn canceled")
            return false
        }
        learning = true
        learnStep = 1
        lastLearnBinding = nil
        lastLearnEventAt = .distantPast
        onStatus?("MIDI Learn 1/16: press button")
        return true
    }

    private func connectSources() {
        connectedSources.removeAll()
        let sourceCount = MIDIGetNumberOfSources()
        if sourceCount == 0 { return }

        var sourceNames: [String] = []
        for i in 0..<sourceCount {
            let source = MIDIGetSource(i)
            guard source != 0 else { continue }
            let name = displayName(for: source) ?? "(unknown)"
            sourceNames.append(name)
            let status = MIDIPortConnectSource(inputPort, source, nil)
            if status == noErr {
                connectedSources.append(source)
            }
        }
        onStatus?("MIDI sources: \(sourceNames.joined(separator: ", "))")
    }

    private func handle(packetList: UnsafePointer<MIDIPacketList>) {
        let count = Int(packetList.pointee.numPackets)
        guard count > 0 else { return }

        var packet = packetList.pointee.packet
        for i in 0..<count {
            packet.withBytes { bytes in
                guard bytes.count >= 3 else { return }
                self.handleMessage(status: bytes[0], data1: bytes[1], data2: bytes[2])
            }
            if i < count - 1 {
                packet = MIDIPacketNext(&packet).pointee
            }
        }
    }

    private func handleMessage(status: UInt8, data1: UInt8, data2: UInt8) {
        let nibble = status & 0xF0
        // Accept Note On and Control Change. Ignore zero-value (release/off) events.
        guard (nibble == 0x90 || nibble == 0xB0), data2 > 0 else { return }

        let channel = status & 0x0F
        let incoming = MIDIBinding(statusNibble: nibble, data1: data1, channel: channel)

        if learning {
            let now = Date()
            if incoming == lastLearnBinding, now.timeIntervalSince(lastLearnEventAt) < 0.12 {
                return
            }
            lastLearnBinding = incoming
            lastLearnEventAt = now

            bindings[learnStep] = incoming
            let kind = nibble == 0xB0 ? "CC" : "Note"
            onStatus?("Learned \(kind) data1=\(data1) ch=\(Int(channel) + 1) -> slot \(learnStep)")
            if learnStep >= 16 {
                MIDILearnStore.save(bindings)
                learning = false
                learnStep = 1
                onStatus?("MIDI learn saved (16)")
            } else {
                learnStep += 1
                onStatus?("MIDI Learn \(learnStep)/16: press button")
            }
            return
        }

        guard let slot = bindings.first(where: { $0.value == incoming })?.key else { return }
        onSlotTriggered?(slot)
    }

    private func displayName(for endpoint: MIDIEndpointRef) -> String? {
        var name: Unmanaged<CFString>?
        let status = MIDIObjectGetStringProperty(endpoint, kMIDIPropertyDisplayName, &name)
        guard status == noErr, let retained = name?.takeRetainedValue() else {
            return nil
        }
        return retained as String
    }
}

private extension MIDIPacket {
    func withBytes(_ body: (UnsafeBufferPointer<UInt8>) -> Void) {
        let len = Int(length)
        guard len > 0 else {
            body(UnsafeBufferPointer(start: nil, count: 0))
            return
        }
        withUnsafePointer(to: data) { ptr in
            ptr.withMemoryRebound(to: UInt8.self, capacity: len) { bytePtr in
                body(UnsafeBufferPointer(start: bytePtr, count: len))
            }
        }
    }
}

@MainActor
final class AppViewModel: ObservableObject {
    @Published var workspaceProjects: [WorkspaceProject] = []
    @Published var liveColumns: [LiveColumn] = []
    @Published var selectedAlias: String = ""
    @Published var statusText: String = "Ready"
    @Published var isBusy: Bool = false
    @Published var isMIDILearning: Bool = false

    private let fileManager = FileManager.default
    private var midiActivator: MIDIPaneActivator?
    private var startupRetryTask: Task<Void, Never>?

    var workspacePath: String {
        let home = NSHomeDirectory()
        return "\(home)/.config/tproj/workspace.yaml"
    }

    var canAddColumn: Bool {
        !selectedAlias.isEmpty && !isBusy
    }

    var inactiveProjects: [WorkspaceProject] {
        let livePaths = Set(liveColumns.map { $0.projectPath })
        return workspaceProjects.filter { !livePaths.contains($0.path) }
    }

    private struct PaneInfo {
        var paneID: String
        var role: String
        var column: Int?
    }

    func onAppear() {
        Task {
            await refreshAll()
            startMIDIIfNeeded()
            if liveColumns.isEmpty {
                startStartupRetry()
            }
        }
    }

    private func startStartupRetry() {
        startupRetryTask = Task {
            for _ in 0..<10 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }
                await refreshAll()
                if !liveColumns.isEmpty {
                    return
                }
            }
        }
    }

    deinit {
        midiActivator?.stop()
        startupRetryTask?.cancel()
    }

    func refreshAll() async {
        isBusy = true
        defer { isBusy = false }

        loadWorkspaceProjects()
        loadLiveColumns()
        normalizeSelection()
        statusText = "Reloaded: \(DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium))"
    }

    func addWorkspaceRow() {
        workspaceProjects.append(
            WorkspaceProject(path: "", type: "local", host: "", alias: "", enabled: true)
        )
    }

    func deleteWorkspaceRow(_ projectID: UUID) {
        workspaceProjects.removeAll { $0.id == projectID }
        normalizeSelection()
    }

    func addColumn() async {
        guard !selectedAlias.isEmpty else {
            statusText = "No project selected"
            return
        }
        await addColumnByAlias(selectedAlias)
    }

    func addColumnByAlias(_ alias: String) async {
        isBusy = true
        defer { isBusy = false }

        let result = await runCommandAsync("/usr/bin/env", ["tproj", "--add", alias])
        if result.exitCode == 0 {
            statusText = "Added column: \(alias)"
            loadLiveColumns()
        } else {
            statusText = "Add failed: \(trimmedError(result))"
        }
    }

    func toggleMIDILearn() {
        startMIDIIfNeeded()
        guard let midiActivator else {
            statusText = "MIDI unavailable"
            return
        }
        isMIDILearning = midiActivator.toggleLearn()
    }

    func toggleYazi(for column: LiveColumn) async {
        guard let pane = column.codexPaneID ?? column.claudePaneID else {
            statusText = "No pane found for column \(column.column)"
            return
        }

        isBusy = true
        defer { isBusy = false }

        let scriptPath = "\(NSHomeDirectory())/bin/tproj-toggle-yazi"
        let result = await runCommandAsync("/usr/bin/env", [scriptPath, "tproj-workspace", pane])
        if result.exitCode == 0 {
            statusText = "Toggled Yazi for #\(column.column)"
        } else {
            statusText = "Yazi toggle failed: \(trimmedError(result))"
        }
        loadLiveColumns()
    }

    func toggleTerminal(for column: LiveColumn) async {
        isBusy = true
        defer { isBusy = false }

        let sessionTarget = "tproj-workspace:dev"
        let listResult = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_id}:#{@role}"])
        guard listResult.exitCode == 0 else {
            statusText = "Term: \(trimmedError(listResult))"
            loadLiveColumns()
            return
        }

        let roleName = "terminal-p\(column.column)"
        let paneRoles: [(id: String, role: String)] = listResult.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard parts.count == 2 else { return nil }
                return (id: parts[0], role: parts[1])
            }

        // Toggle off: kill existing terminal
        if let existing = paneRoles.first(where: { $0.role == roleName }) {
            let killResult = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", existing.id])
            statusText = killResult.exitCode == 0
                ? "Terminal off for #\(column.column)"
                : "Term off failed: \(trimmedError(killResult))"
            loadLiveColumns()
            return
        }

        // Toggle on: find target pane from fresh list (codex preferred, claude fallback)
        guard let targetPane = paneRoles.first(where: { $0.role == "codex-p\(column.column)" })?.id
                ?? paneRoles.first(where: { $0.role == "claude-p\(column.column)" })?.id else {
            statusText = "Term: no pane for #\(column.column)"
            return
        }

        let createResult = await runCommandAsync("/usr/bin/env", [
            "tmux", "split-window", "-v", "-b", "-t", targetPane,
            "-c", "/tmp", "-l", "25%", "-P", "-F", "#{pane_id}"
        ])
        guard createResult.exitCode == 0 else {
            statusText = "Term[\(createResult.exitCode)]: \(trimmedError(createResult))"
            return
        }

        let newPane = createResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newPane.isEmpty else {
            statusText = "Term: empty pane id"
            return
        }

        // Set @role immediately to prevent reflow-agent-pane hook from misidentifying this pane
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@role", roleName])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@column", "\(column.column)"])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@project", column.projectPath])

        if let host = hostForColumn(column) {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_host", host])
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_path", column.projectPath])
            let remoteCmd = "ssh -t \(shellSingleQuote(host)) \"cd \(shellDoubleQuote(column.projectPath)) && exec \\$SHELL -l\""
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, remoteCmd, "C-m"])
        } else {
            let localDir = column.projectPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? NSHomeDirectory() : column.projectPath
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, "cd \(shellSingleQuote(localDir)) && exec $SHELL -l", "C-m"])
        }

        statusText = "Terminal on for #\(column.column)"
        loadLiveColumns()
    }

    func removeColumn(_ column: LiveColumn) async {
        guard column.claudePaneID != nil || column.codexPaneID != nil else {
            statusText = "Missing pane info for column \(column.column)"
            return
        }

        isBusy = true
        defer { isBusy = false }

        var errors: [String] = []

        if let codex = column.codexPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", codex])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let claude = column.claudePaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", claude])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let yazi = column.yaziPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", yazi])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let terminal = column.terminalPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", terminal])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        _ = await runCommandAsync("\(NSHomeDirectory())/bin/rebalance-workspace-columns", ["tproj-workspace"])
        _ = await normalizeColumnsByVisualOrderAsync()

        if errors.isEmpty {
            statusText = "Removed column \(column.column)"
        } else {
            statusText = "Drop failed: \(errors.joined(separator: " | "))"
        }

        loadLiveColumns()
    }

    func moveColumn(from sourceColumn: Int, to targetColumn: Int) async {
        guard sourceColumn != targetColumn else { return }
        guard !isBusy else { return }

        // Optimistic UI swap: build new array locally to avoid intermediate duplicate IDs
        // (swapAt + column reassign fires @Published 3 times; the 2nd has duplicate id → SwiftUI hang)
        if let srcIdx = liveColumns.firstIndex(where: { $0.column == sourceColumn }),
           let tgtIdx = liveColumns.firstIndex(where: { $0.column == targetColumn }) {
            var updated = liveColumns
            updated.swapAt(srcIdx, tgtIdx)
            updated[srcIdx].column = sourceColumn
            updated[tgtIdx].column = targetColumn
            liveColumns = updated  // single atomic @Published fire
        }

        isBusy = true
        defer { isBusy = false }

        let agentsActive = await runCommandAsync("/usr/bin/env", ["tmux", "show-environment", "-t", "tproj-workspace", "TPROJ_AGENTS_ACTIVE"])
        if agentsActive.exitCode == 0 {
            statusText = "Reorder disabled while agent panes are active"
            loadLiveColumns()
            return
        }

        let panes = await listWorkspacePanesAsync()
        guard !panes.isEmpty else {
            statusText = "Reorder failed: workspace panes not found"
            loadLiveColumns()
            return
        }

        guard let claudeSource = paneID(forRole: "claude-p\(sourceColumn)", panes: panes),
              let claudeTarget = paneID(forRole: "claude-p\(targetColumn)", panes: panes),
              let codexSource = paneID(forRole: "codex-p\(sourceColumn)", panes: panes),
              let codexTarget = paneID(forRole: "codex-p\(targetColumn)", panes: panes) else {
            statusText = "Reorder failed: required panes not found"
            loadLiveColumns()
            return
        }

        // Gather pre-swap metadata from claude panes
        let srcMeta = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeSource, "-p", "#{@project}|#{@remote_host}|#{@remote_path}|#{pane_left}"])
        let tgtMeta = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeTarget, "-p", "#{@project}|#{@remote_host}|#{@remote_path}"])

        let srcParts = srcMeta.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        let tgtParts = tgtMeta.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "|", omittingEmptySubsequences: false).map(String.init)

        let sourceProject = srcParts.count > 0 ? srcParts[0] : ""
        let sourceRemoteHost = srcParts.count > 1 ? srcParts[1] : ""
        let sourceRemotePath = srcParts.count > 2 ? srcParts[2] : ""
        let sourceOriginalLeft = srcParts.count > 3 ? (Int(srcParts[3]) ?? -1) : -1

        let targetProject = tgtParts.count > 0 ? tgtParts[0] : ""
        let targetRemoteHost = tgtParts.count > 1 ? tgtParts[1] : ""
        let targetRemotePath = tgtParts.count > 2 ? tgtParts[2] : ""

        let yaziSource = paneID(forRole: "yazi-p\(sourceColumn)", panes: panes)
        let yaziTarget = paneID(forRole: "yazi-p\(targetColumn)", panes: panes)
        let terminalSource = paneID(forRole: "terminal-p\(sourceColumn)", panes: panes)
        let terminalTarget = paneID(forRole: "terminal-p\(targetColumn)", panes: panes)

        // Perform swap-pane operations
        let mainSwap1 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", claudeSource, "-t", claudeTarget])
        guard mainSwap1.exitCode == 0 else {
            statusText = "Reorder failed: \(trimmedError(mainSwap1))"
            loadLiveColumns()
            return
        }
        let mainSwap2 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", codexSource, "-t", codexTarget])
        guard mainSwap2.exitCode == 0 else {
            statusText = "Reorder failed: \(trimmedError(mainSwap2))"
            loadLiveColumns()
            return
        }

        if let ys = yaziSource, let yt = yaziTarget {
            let s = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", ys, "-t", yt])
            if s.exitCode != 0 {
                statusText = "Reorder warning (yazi): \(trimmedError(s))"
            }
        } else if let ys = yaziSource {
            _ = await relocatePaneAboveCodexAsync(paneID: ys, codexPaneID: codexSource)
        } else if let yt = yaziTarget {
            _ = await relocatePaneAboveCodexAsync(paneID: yt, codexPaneID: codexTarget)
        }

        if let ts = terminalSource, let tt = terminalTarget {
            let s = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", ts, "-t", tt])
            if s.exitCode != 0 {
                statusText = "Reorder warning (term): \(trimmedError(s))"
            }
        } else if let ts = terminalSource {
            _ = await relocatePaneAboveCodexAsync(paneID: ts, codexPaneID: codexSource)
        } else if let tt = terminalTarget {
            _ = await relocatePaneAboveCodexAsync(paneID: tt, codexPaneID: codexTarget)
        }

        // Detect if swap-pane moved panes physically (Case A) or just swapped content (Case B)
        let check = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeSource, "-p", "#{pane_left}"])
        let srcLeftAfter = Int(check.stdout.trimmingCharacters(in: .whitespacesAndNewlines)) ?? -1
        let panesMoved = (srcLeftAfter != sourceOriginalLeft) && srcLeftAfter >= 0 && sourceOriginalLeft >= 0

        if !panesMoved {
            // Case B: content swapped but pane IDs stayed at original positions.
            // @project tags are still at their original positions, explicitly swap them.
            await swapProjectTagsAsync(
                sourceColumn: sourceColumn, targetColumn: targetColumn,
                sourceProject: sourceProject, sourceRemoteHost: sourceRemoteHost, sourceRemotePath: sourceRemotePath,
                targetProject: targetProject, targetRemoteHost: targetRemoteHost, targetRemotePath: targetRemotePath
            )
        }

        // normalizeColumnsByVisualOrderAsync handles @column/@role for both cases
        _ = await runCommandAsync("\(NSHomeDirectory())/bin/rebalance-workspace-columns", ["tproj-workspace"])
        let normalized = await normalizeColumnsByVisualOrderAsync()
        if !normalized {
            statusText = "Reorder warning: visual normalize failed"
        }
        loadLiveColumns()
        refreshColumnIdentities()
        statusText = "Swapped #\(sourceColumn) and #\(targetColumn)"
    }

    func saveWorkspace() async {
        isBusy = true
        defer { isBusy = false }

        do {
            let content = renderWorkspaceYAML()
            let parent = URL(fileURLWithPath: workspacePath).deletingLastPathComponent()
            try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
            try content.write(toFile: workspacePath, atomically: true, encoding: .utf8)
            statusText = "Saved workspace.yaml"
            loadWorkspaceProjects()
            normalizeSelection()
        } catch {
            statusText = "Save failed: \(error.localizedDescription)"
        }
    }

    func openWorkspaceYAML() {
        let path = workspacePath
        guard fileManager.fileExists(atPath: path) else {
            statusText = "workspace.yaml not found"
            return
        }
        let url = URL(fileURLWithPath: path)
        if NSWorkspace.shared.open(url) {
            statusText = "Opened workspace.yaml"
        } else {
            statusText = "Failed to open workspace.yaml"
        }
    }

    private func startMIDIIfNeeded() {
        guard midiActivator == nil else { return }
        let activator = MIDIPaneActivator()
        activator.onStatus = { [weak self] message in
            Task { @MainActor in
                self?.statusText = message
            }
        }
        activator.onLearnStateChanged = { [weak self] isLearning in
            Task { @MainActor in
                self?.isMIDILearning = isLearning
            }
        }
        activator.onSlotTriggered = { [weak self] slot in
            Task { [weak self] in
                await self?.activatePaneForMIDISlot(slot)
            }
        }
        activator.start()
        midiActivator = activator
    }

    private func activatePaneForMIDISlot(_ slot: Int) async {
        guard (1...16).contains(slot) else { return }

        let sessionTarget = "tproj-workspace:dev"
        let list = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_index}"])
        guard list.exitCode == 0 else {
            statusText = "MIDI activate failed: \(trimmedError(list))"
            return
        }

        let available = Set(
            list.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
        )
        guard available.contains(slot) else {
            statusText = "MIDI: pane #\(slot) not found"
            return
        }

        _ = await runCommandAsync("/usr/bin/env", ["tmux", "select-window", "-t", sessionTarget])
        let select = await runCommandAsync("/usr/bin/env", ["tmux", "select-pane", "-t", "\(sessionTarget).\(slot)"])
        if select.exitCode == 0 {
            statusText = "MIDI: #\(slot) activated"
        } else {
            statusText = "MIDI activate failed: \(trimmedError(select))"
        }
    }

    func stopSession() async {
        isBusy = true
        defer { isBusy = false }

        let sessions = await getTprojSessions()
        guard !sessions.isEmpty else {
            statusText = "No tproj sessions found"
            liveColumns = []
            return
        }

        // Collect descendant PIDs before stopping (to clean up MCP servers)
        let descendantPids = await collectSessionDescendants(sessions: sessions)

        // Phase 1: Send graceful exit signals to each pane by role
        for session in sessions {
            let listResult = await runCommandAsync("/usr/bin/env", [
                "tmux", "list-panes", "-s", "-t", session, "-F", "#{pane_id}:#{@role}"
            ])
            guard listResult.exitCode == 0 else { continue }

            let paneRoles: [(id: String, role: String)] = listResult.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .map(String.init)
                .compactMap { line in
                    let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                    guard parts.count == 2 else { return nil }
                    return (id: parts[0], role: parts[1])
                }

            // Send C-c to claude/codex/agent panes, q to yazi panes
            for pane in paneRoles {
                if pane.role.hasPrefix("claude") || pane.role.hasPrefix("codex") || pane.role.hasPrefix("agent") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "C-c", ""])
                } else if pane.role.hasPrefix("yazi") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "q", ""])
                }
            }

            // Brief pause for C-c to take effect
            try? await Task.sleep(nanoseconds: 300_000_000) // 0.3s

            // Send /exit to claude/agent panes
            for pane in paneRoles {
                if pane.role.hasPrefix("claude") || pane.role.hasPrefix("agent") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "/exit", "Enter"])
                }
            }
        }

        // Phase 2: Poll has-session for up to 3 seconds
        let deadline = Date().addingTimeInterval(3.0)
        while Date() < deadline {
            let allGone = await withTaskGroup(of: Bool.self, returning: Bool.self) { group in
                for session in sessions {
                    group.addTask {
                        let r = await self.runCommandAsync("/usr/bin/env", ["tmux", "has-session", "-t", session])
                        return r.exitCode != 0 // true = session gone
                    }
                }
                var results: [Bool] = []
                for await result in group { results.append(result) }
                return results.allSatisfy { $0 }
            }
            if allGone { break }
            try? await Task.sleep(nanoseconds: 300_000_000) // 0.3s
        }

        // Kill team-watcher
        _ = await runCommandAsync("/usr/bin/env", ["pkill", "-TERM", "-f", "bin/team-watcher"])

        // Phase 3: Force kill remaining sessions
        for session in sessions {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-session", "-t", session])
        }

        // Clean up surviving MCP server processes
        await killSurvivingDescendants(descendantPids)
        await cleanupOrphanedMcp()

        // Clean up dead-agents file
        try? FileManager.default.removeItem(atPath: "/tmp/tproj-dead-agents")

        statusText = "Session stopped"
        liveColumns = []
    }

    func killSession() async {
        isBusy = true
        defer { isBusy = false }

        let sessions = await getTprojSessions()
        guard !sessions.isEmpty else {
            statusText = "No tproj sessions found"
            liveColumns = []
            return
        }

        // Collect descendant PIDs before killing (to clean up MCP servers)
        let descendantPids = await collectSessionDescendants(sessions: sessions)

        // Kill team-watcher first
        _ = await runCommandAsync("/usr/bin/env", ["pkill", "-TERM", "-f", "bin/team-watcher"])

        // Kill all tproj sessions
        for session in sessions {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-session", "-t", session])
        }

        // Clean up surviving MCP server processes
        await killSurvivingDescendants(descendantPids)
        await cleanupOrphanedMcp()

        // Clean up dead-agents file
        try? FileManager.default.removeItem(atPath: "/tmp/tproj-dead-agents")

        statusText = "Session killed"
        liveColumns = []
    }

    /// Get all tmux sessions with @tproj=true tag
    private func getTprojSessions() async -> [String] {
        let result = await runCommandAsync("/usr/bin/env", [
            "tmux", "list-sessions", "-F", "#{session_name}:#{@tproj}"
        ])
        guard result.exitCode == 0 else { return [] }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard parts.count == 2, parts[1] == "true" else { return nil }
                return parts[0]
            }
    }

    /// Collect all descendant PIDs from panes of given sessions (BFS via pgrep -P)
    private func collectSessionDescendants(sessions: [String]) async -> Set<Int32> {
        var panePids: [Int32] = []
        for session in sessions {
            let result = await runCommandAsync("/usr/bin/env", [
                "tmux", "list-panes", "-s", "-t", session, "-F", "#{pane_pid}"
            ])
            guard result.exitCode == 0 else { continue }
            let pids = result.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap { Int32($0) }
            panePids.append(contentsOf: pids)
        }

        // BFS: collect all descendants
        var allDescendants = Set<Int32>()
        var queue = panePids
        while !queue.isEmpty {
            let current = queue.removeFirst()
            let pgrepResult = await runCommandAsync("/usr/bin/env", ["pgrep", "-P", "\(current)"])
            guard pgrepResult.exitCode == 0 else { continue }
            let children = pgrepResult.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap { Int32($0) }
            for child in children {
                if allDescendants.insert(child).inserted {
                    queue.append(child)
                }
            }
        }
        return allDescendants
    }

    /// Kill surviving descendant processes after session termination
    private func killSurvivingDescendants(_ pids: Set<Int32>) async {
        for pid in pids {
            kill(pid, SIGTERM)
        }
    }

    /// Kill orphaned MCP server processes (PPID=1, reparented to launchd)
    private func cleanupOrphanedMcp() async {
        let result = await runCommandAsync("/usr/bin/env", [
            "sh", "-c",
            "ps -eo pid=,ppid=,command= 2>/dev/null | awk '$2 == 1' | grep -E '(context7-mcp|playwright-mcp|chrome-ai-bridge|claude-in-chrome-mcp|@playwright/mcp|@upstash/context7)' | awk '{print $1}'"
        ])
        guard result.exitCode == 0 else { return }
        let orphanPids = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .compactMap { Int32($0) }
        for pid in orphanPids {
            kill(pid, SIGTERM)
        }
    }

    /// Replace all LiveColumns with fresh instances (new UUIDs) to reset macOS drag registrations.
    private func refreshColumnIdentities() {
        liveColumns = liveColumns.map {
            LiveColumn(
                column: $0.column, projectPath: $0.projectPath, hostLabel: $0.hostLabel,
                width: $0.width, left: $0.left, claudePaneID: $0.claudePaneID,
                codexPaneID: $0.codexPaneID, yaziPaneID: $0.yaziPaneID, terminalPaneID: $0.terminalPaneID
            )
        }
    }

    private func normalizeSelection() {
        let aliases = workspaceProjects.map { $0.effectiveAlias }
        if aliases.isEmpty {
            selectedAlias = ""
            return
        }
        if !aliases.contains(selectedAlias) {
            selectedAlias = aliases[0]
        }
    }

    private func loadWorkspaceProjects() {
        let url = URL(fileURLWithPath: workspacePath)
        guard fileManager.fileExists(atPath: workspacePath) else {
            workspaceProjects = []
            return
        }

        let query = ".projects[]? | [(.path // \"\"),(.type // \"local\"),(.host // \"\"),(.alias // \"\"),((.enabled // true)|tostring)] | @tsv"
        let result = runCommand("/usr/bin/env", ["yq", "-r", query, url.path])

        guard result.exitCode == 0 else {
            statusText = "workspace.yaml read failed (yq): \(trimmedError(result))"
            workspaceProjects = []
            return
        }

        let rows = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)

        var parsed: [WorkspaceProject] = []
        for row in rows {
            let parts = row.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            if parts.count < 5 { continue }

            let enabledRaw = parts[4].lowercased()
            let enabled = enabledRaw == "true"

            parsed.append(
                WorkspaceProject(
                    path: parts[0],
                    type: parts[1].isEmpty ? "local" : parts[1],
                    host: parts[2],
                    alias: parts[3],
                    enabled: enabled
                )
            )
        }

        workspaceProjects = parsed
    }

    private func loadLiveColumns() {
        let format = "#{@column}|#{@role}|#{@project}|#{@remote_host}|#{@remote_path}|#{pane_width}|#{pane_left}|#{pane_id}"
        let result = runCommand("/usr/bin/env", ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", format])

        guard result.exitCode == 0 else {
            liveColumns = []
            return
        }

        struct Builder {
            var column: Int
            var projectPath: String = ""
            var hostLabel: String = "local"
            var width: Int = 0
            var left: Int = Int.max
            var claudePaneID: String?
            var codexPaneID: String?
            var yaziPaneID: String?
            var terminalPaneID: String?
        }

        var grouped: [Int: Builder] = [:]

        let lines = result.stdout.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
        for line in lines {
            let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
            if parts.count < 8 { continue }

            guard let col = Int(parts[0]), col > 0 else { continue }
            let role = parts[1]
            let project = parts[2]
            let remoteHost = parts[3]
            let remotePath = parts[4]
            let width = Int(parts[5]) ?? 0
            let left = Int(parts[6]) ?? Int.max
            let paneID = parts[7]
            let isPrimaryPane = role.hasPrefix("claude-p") || role.hasPrefix("codex-p")

            var entry = grouped[col] ?? Builder(column: col)
            if width > 0 { entry.width = width }
            if isPrimaryPane, left < entry.left { entry.left = left }

            // Keep column identity tied to claude/codex panes to avoid stale yazi/term metadata overriding UI.
            if isPrimaryPane || entry.projectPath.isEmpty {
                let isRemote = project.hasPrefix("ssh://") || !remoteHost.isEmpty || !remotePath.isEmpty
                if isRemote {
                    entry.hostLabel = remoteHost.isEmpty ? "remote" : "remote@\(remoteHost)"
                    if !remotePath.isEmpty {
                        entry.projectPath = remotePath
                    } else if project.hasPrefix("ssh://") {
                        let stripped = project.replacingOccurrences(of: "ssh://", with: "")
                        if let slash = stripped.firstIndex(of: "/") {
                            entry.projectPath = "/" + stripped[slash...].dropFirst()
                        }
                    }
                } else {
                    entry.hostLabel = "local"
                    entry.projectPath = project
                }
            }

            if role.hasPrefix("claude-p") { entry.claudePaneID = paneID }
            if role.hasPrefix("codex-p") { entry.codexPaneID = paneID }
            if role.hasPrefix("yazi-p") { entry.yaziPaneID = paneID }
            if role.hasPrefix("terminal-p") { entry.terminalPaneID = paneID }

            grouped[col] = entry
        }

        let newData = grouped
            .values
            .sorted(by: {
                if $0.left != $1.left { return $0.left < $1.left }
                return $0.column < $1.column
            })
            .map {
                LiveColumn(
                    column: $0.column,
                    projectPath: $0.projectPath,
                    hostLabel: $0.hostLabel,
                    width: $0.width,
                    left: $0.left == Int.max ? 0 : $0.left,
                    claudePaneID: $0.claudePaneID,
                    codexPaneID: $0.codexPaneID,
                    yaziPaneID: $0.yaziPaneID,
                    terminalPaneID: $0.terminalPaneID
                )
            }

        // Merge: match by projectPath to preserve existing UUIDs (stable SwiftUI identity)
        var used = Set<UUID>()
        var merged: [LiveColumn] = []
        for data in newData {
            if !data.projectPath.isEmpty,
               var existing = liveColumns.first(where: {
                   $0.projectPath == data.projectPath && !used.contains($0.id)
               }) {
                used.insert(existing.id)
                existing.column = data.column
                existing.hostLabel = data.hostLabel
                existing.width = data.width
                existing.left = data.left
                existing.claudePaneID = data.claudePaneID
                existing.codexPaneID = data.codexPaneID
                existing.yaziPaneID = data.yaziPaneID
                existing.terminalPaneID = data.terminalPaneID
                merged.append(existing)
            } else {
                merged.append(data)
            }
        }
        liveColumns = merged
    }

    private func normalizeColumnsByVisualOrderAsync() async -> Bool {
        let result = await runCommandAsync(
            "/usr/bin/env",
            ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", "#{pane_id}|#{pane_left}|#{@column}|#{@role}"]
        )
        guard result.exitCode == 0 else { return false }

        struct Row {
            var paneID: String
            var left: Int
            var column: Int
            var role: String
        }

        let rows: [Row] = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                guard parts.count >= 4,
                      let left = Int(parts[1]),
                      let column = Int(parts[2]),
                      column > 0 else {
                    return nil
                }
                return Row(paneID: parts[0], left: left, column: column, role: parts[3])
            }

        guard !rows.isEmpty else { return false }

        var leftByColumn: [Int: Int] = [:]
        for row in rows where row.role.hasPrefix("claude-p") || row.role.hasPrefix("codex-p") {
            let cur = leftByColumn[row.column] ?? Int.max
            if row.left < cur {
                leftByColumn[row.column] = row.left
            }
        }
        if leftByColumn.isEmpty {
            for row in rows {
                let cur = leftByColumn[row.column] ?? Int.max
                if row.left < cur {
                    leftByColumn[row.column] = row.left
                }
            }
        }

        let orderedColumns = leftByColumn.keys.sorted { (leftByColumn[$0] ?? Int.max) < (leftByColumn[$1] ?? Int.max) }
        guard !orderedColumns.isEmpty else { return false }

        var remap: [Int: Int] = [:]
        for (idx, oldCol) in orderedColumns.enumerated() {
            remap[oldCol] = idx + 1
        }

        var ok = true
        for row in rows {
            guard let newCol = remap[row.column] else { continue }

            if newCol != row.column {
                let c = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", row.paneID, "@column", "\(newCol)"])
                if c.exitCode != 0 { ok = false }
            }

            let newRole = remappedRoleColumnSuffix(row.role, remap: remap)
            if newRole != row.role {
                let r = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", row.paneID, "@role", newRole])
                if r.exitCode != 0 { ok = false }
            }
        }
        return ok
    }

    private func remappedRoleColumnSuffix(_ role: String, remap: [Int: Int]) -> String {
        let pattern = "^(.*-p)(\\d+)(.*)$"
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return role }
        let range = NSRange(role.startIndex..<role.endIndex, in: role)
        guard let match = regex.firstMatch(in: role, options: [], range: range),
              match.numberOfRanges == 4,
              let prefixRange = Range(match.range(at: 1), in: role),
              let numberRange = Range(match.range(at: 2), in: role),
              let suffixRange = Range(match.range(at: 3), in: role),
              let old = Int(role[numberRange]),
              let mapped = remap[old] else {
            return role
        }
        return "\(role[prefixRange])\(mapped)\(role[suffixRange])"
    }

    private func listWorkspacePanesAsync() async -> [PaneInfo] {
        let result = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", "#{pane_id}|#{@role}|#{@column}"])
        guard result.exitCode == 0 else { return [] }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                guard parts.count >= 3 else { return nil }
                let col = Int(parts[2])
                return PaneInfo(paneID: parts[0], role: parts[1], column: col)
            }
    }

    private func paneID(forRole role: String, panes: [PaneInfo]) -> String? {
        panes.first(where: { $0.role == role })?.paneID
    }

    private func relocatePaneAboveCodexAsync(paneID: String, codexPaneID: String) async -> Bool {
        let create = await runCommandAsync("/usr/bin/env", ["tmux", "split-window", "-v", "-b", "-t", codexPaneID, "-c", "/tmp", "-l", "25%", "-P", "-F", "#{pane_id}"])
        guard create.exitCode == 0 else { return false }
        let placeholder = create.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !placeholder.isEmpty else { return false }
        let swap = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", paneID, "-t", placeholder])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", placeholder])
        return swap.exitCode == 0
    }

    private func swapProjectTagsAsync(
        sourceColumn: Int, targetColumn: Int,
        sourceProject: String, sourceRemoteHost: String, sourceRemotePath: String,
        targetProject: String, targetRemoteHost: String, targetRemotePath: String
    ) async {
        let panes = await listWorkspacePanesAsync()
        for pane in panes {
            guard let col = pane.column, col == sourceColumn || col == targetColumn else { continue }
            if col == sourceColumn {
                // Pane at source position -> should now reflect target's project data
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@project", targetProject])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_host", targetRemoteHost])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_path", targetRemotePath])
            } else {
                // Pane at target position -> should now reflect source's project data
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@project", sourceProject])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_host", sourceRemoteHost])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_path", sourceRemotePath])
            }
        }
    }

    private func hostForColumn(_ column: LiveColumn) -> String? {
        guard column.hostLabel != "local" else { return nil }
        if let project = workspaceProjects.first(where: { $0.path == column.projectPath }) {
            let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
            if !host.isEmpty { return host }
        }
        if column.hostLabel.hasPrefix("remote@") {
            return String(column.hostLabel.dropFirst("remote@".count))
        }
        return nil
    }

    private func shellSingleQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
    }

    private func shellDoubleQuote(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "$", with: "\\$")
            .replacingOccurrences(of: "`", with: "\\`")
    }

    private func renderWorkspaceYAML() -> String {
        var lines: [String] = []
        lines.append("projects:")

        for project in workspaceProjects {
            lines.append("  - path: \(yamlQuote(project.path))")

            // type: only write when remote (local is default)
            if project.type == "remote" {
                lines.append("    type: remote")
                let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
                lines.append("    host: \(yamlQuote(host))")
            }

            let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
            if !alias.isEmpty {
                lines.append("    alias: \(yamlQuote(alias))")
            }

            // enabled: only write when false (true is default)
            if !project.enabled {
                lines.append("    enabled: false")
            }
        }

        return lines.joined(separator: "\n") + "\n"
    }

    private func yamlQuote(_ value: String) -> String {
        let escaped = value.replacingOccurrences(of: "'", with: "''")
        return "'\(escaped)'"
    }

    private func runCommand(_ launchPath: String, _ arguments: [String]) -> CommandResult {
        Self.executeCommand(launchPath, arguments)
    }

    private func runCommandAsync(_ launchPath: String, _ arguments: [String]) async -> CommandResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let result = Self.executeCommand(launchPath, arguments)
                continuation.resume(returning: result)
            }
        }
    }

    nonisolated private static func executeCommand(_ launchPath: String, _ arguments: [String]) -> CommandResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        do {
            try process.run()
            process.waitUntilExit()

            let out = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let err = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

            return CommandResult(exitCode: process.terminationStatus, stdout: out, stderr: err)
        } catch {
            return CommandResult(exitCode: 1, stdout: "", stderr: error.localizedDescription)
        }
    }

    private func trimmedError(_ result: CommandResult) -> String {
        let text = result.stderr.isEmpty ? result.stdout : result.stderr
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct Card<Content: View>: View {
    var compact: Bool = false
    var chrome: Bool = true
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 4 : 8) {
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(chrome ? (compact ? 2 : 6) : 0)
        .background {
            if chrome {
                RoundedRectangle(cornerRadius: compact ? 2 : 3, style: .continuous)
                    .fill(GhosttyTheme.current.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: compact ? 2 : 3, style: .continuous)
                            .stroke(GhosttyTheme.current.cardBorder, lineWidth: 1)
                    )
            }
        }
    }
}

struct SectionHeader: View {
    let title: String

    var body: some View {
        HStack(spacing: 4) {
            Rectangle()
                .fill(GhosttyTheme.current.foreground.opacity(0.15))
                .frame(width: 12, height: 1)
            Text(title)
                .font(GhosttyTheme.current.font(size: 16, weight: .semibold))
                .foregroundStyle(GhosttyTheme.current.textPrimary)
        }
        .padding(.leading, 1)
    }
}

enum ActionButtonTone {
    case neutral
    case primary
    case danger
}

struct ActionButtonStyle: ButtonStyle {
    let tone: ActionButtonTone
    let isHovered: Bool
    let isEnabled: Bool
    let dense: Bool

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed && isEnabled

        return configuration.label
            .font(GhosttyTheme.current.font(size: dense ? 11 : 13, weight: .semibold))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, dense ? 4 : 12)
            .padding(.vertical, dense ? 2 : 8)
            .frame(minHeight: dense ? 18 : 32)
            .background(
                RoundedRectangle(cornerRadius: dense ? 3 : 4, style: .continuous)
                    .fill(backgroundColor(pressed: pressed))
            )
            .overlay(
                RoundedRectangle(cornerRadius: dense ? 3 : 4, style: .continuous)
                    .stroke(borderColor(pressed: pressed), lineWidth: 1)
            )
            .scaleEffect(pressed ? 0.98 : (isHovered && isEnabled ? 1.02 : 1.0))
            .animation(.easeOut(duration: 0.12), value: pressed)
            .animation(.easeOut(duration: 0.14), value: isHovered)
            .opacity(isEnabled ? 1.0 : 0.45)
    }

    private var foregroundColor: Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            return t.textPrimary.opacity(0.92)
        case .primary:
            return t.textPrimary
        case .danger:
            return t.accentRed.opacity(0.95)
        }
    }

    private func backgroundColor(pressed: Bool) -> Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            if pressed { return t.selectionBg.opacity(0.6) }
            return isHovered ? t.selectionBg.opacity(0.4) : t.foreground.opacity(0.08)
        case .primary:
            if pressed { return t.accentBlue.opacity(0.75) }
            return isHovered ? t.accentBlue.opacity(0.62) : t.accentBlue.opacity(0.46)
        case .danger:
            if pressed { return t.accentRed.opacity(0.26) }
            return isHovered ? t.accentRed.opacity(0.20) : t.accentRed.opacity(0.12)
        }
    }

    private func borderColor(pressed: Bool) -> Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            return pressed ? t.foreground.opacity(0.55) : t.foreground.opacity(isHovered ? 0.44 : 0.20)
        case .primary:
            return pressed ? t.accentBlue.opacity(0.95) : t.accentBlue.opacity(isHovered ? 0.88 : 0.72)
        case .danger:
            return pressed ? t.accentRed.opacity(0.82) : t.accentRed.opacity(isHovered ? 0.74 : 0.52)
        }
    }
}

struct ActionButton: View {
    let title: String
    let tone: ActionButtonTone
    let isEnabled: Bool
    let expand: Bool
    let dense: Bool
    let action: () -> Void

    @State private var isHovered = false

    init(
        _ title: String,
        tone: ActionButtonTone = .neutral,
        isEnabled: Bool = true,
        expand: Bool = false,
        dense: Bool = false,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.tone = tone
        self.isEnabled = isEnabled
        self.expand = expand
        self.dense = dense
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Text(title)
                .frame(maxWidth: expand ? .infinity : nil)
        }
        .buttonStyle(ActionButtonStyle(tone: tone, isHovered: isHovered, isEnabled: isEnabled, dense: dense))
        .disabled(!isEnabled)
        .onHover { hover in
            isHovered = hover
        }
    }
}

struct ContentView: View {
    @StateObject private var vm = AppViewModel()
    @State private var draggingColumnID: Int?
    @State private var dropTargetColumnID: Int?

    var body: some View {
        ZStack {
            GhosttyTheme.current.background
                .opacity(GhosttyTheme.current.backgroundOpacity)
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    SectionHeader(title: "Current Workspace")
                    Card(compact: true, chrome: false) {
                        HStack(spacing: 4) {
                            Text(compactStatus(vm.statusText))
                                .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                                .foregroundStyle(GhosttyTheme.current.textSecondary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                            Spacer()
                            if !vm.liveColumns.isEmpty {
                                ActionButton("End", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                    Task { await vm.stopSession() }
                                }
                                .fixedSize()
                                ActionButton("Force", tone: .danger, isEnabled: !vm.isBusy, dense: true) {
                                    Task { await vm.killSession() }
                                }
                                .fixedSize()
                            }
                            ActionButton("Sync", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                Task { await vm.refreshAll() }
                            }
                            .fixedSize()
                            ActionButton("Learn", tone: vm.isMIDILearning ? .primary : .neutral, isEnabled: !vm.isBusy, dense: true) {
                                vm.toggleMIDILearn()
                            }
                            .fixedSize()
                        }

                        if vm.liveColumns.isEmpty {
                            Text("No active columns in tproj-workspace")
                                .font(GhosttyTheme.current.font(size: 12, weight: .medium))
                                .foregroundStyle(GhosttyTheme.current.textSecondary)
                        } else {
                            ForEach(vm.liveColumns) { column in
                                liveColumnRow(column)
                                    .onDrop(
                                        of: [UTType.text],
                                        delegate: ColumnDropDelegate(
                                            targetColumn: column.column,
                                            draggingColumnID: $draggingColumnID,
                                            dropTargetColumnID: $dropTargetColumnID,
                                            viewModel: vm
                                        )
                                    )
                            }
                        }
                        ForEach(vm.inactiveProjects) { project in
                            inactiveProjectRow(project)
                        }
                    }

                    SectionHeader(title: "Workspace YAML")
                    Card {
                        HStack(spacing: 0) {
                            ActionButton("Open workspace.yaml", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                vm.openWorkspaceYAML()
                            }
                            Spacer(minLength: 0)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 4)
                .padding(.top, 4)
            }
            .frame(maxWidth: .infinity)
        }
        .preferredColorScheme(.dark)
        .task {
            vm.onAppear()
        }
        .background(
            WindowAccessor { window in
                window.level = .floating
                if GhosttyTheme.current.backgroundOpacity < 1.0 {
                    window.backgroundColor = .clear
                    window.isOpaque = false
                }
            }
        )
    }

    private func liveColumnRow(_ column: LiveColumn) -> some View {
        let isDragging = draggingColumnID == column.column
        let isDropTarget = dropTargetColumnID == column.column

        return VStack(alignment: .leading, spacing: 3) {
            // Header row
            HStack(spacing: 4) {
                Text("#\(column.column)")
                    .font(GhosttyTheme.current.font(size: 11, weight: .heavy, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textPrimary)
                pill(liveHostLabel(column), tint: column.hostLabel == "local" ? GhosttyTheme.current.accentGreen : GhosttyTheme.current.accentYellow)
                Text(columnPrimaryName(column))
                    .font(GhosttyTheme.current.font(size: 12, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.textPrimary)
                    .lineLimit(1)
                Spacer()
            }

            // Buttons row
            HStack(spacing: 1) {
                Spacer()
                ActionButton("Yazi", tone: column.yaziPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleYazi(for: column) }
                }
                .frame(width: 38)
                ActionButton("Term", tone: column.terminalPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleTerminal(for: column) }
                }
                .frame(width: 38)
                ActionButton("Drop", tone: .danger, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.removeColumn(column) }
                }
                .frame(width: 38)
            }
        }
        .padding(.vertical, 2)
        .padding(.leading, 6)
        .padding(.trailing, 2)
        .background(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(isDragging ? GhosttyTheme.current.accentCyan.opacity(0.15)
                      : isDropTarget ? GhosttyTheme.current.accentCyan.opacity(0.10)
                      : GhosttyTheme.current.foreground.opacity(0.05))
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1)
                .fill(GhosttyTheme.current.accentCyan)
                .frame(width: 2)
        }
        .overlay(
            isDragging
                ? RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .strokeBorder(GhosttyTheme.current.accentCyan.opacity(0.4), lineWidth: 1)
                : nil
        )
        .padding(.vertical, 1)
        .contentShape(Rectangle())
        .opacity(isDragging ? 0.85 : 1.0)
        .onDrag {
            draggingColumnID = column.column
            return NSItemProvider(object: NSString(string: "\(column.column)"))
        }
    }

    private func inactiveProjectRow(_ project: WorkspaceProject) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            // Header row (same layout as liveColumnRow)
            HStack(spacing: 4) {
                Text("--")
                    .font(GhosttyTheme.current.font(size: 11, weight: .heavy, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                pill(project.type == "remote" ? "@\(project.host)" : "lcl",
                     tint: project.type == "remote" ? GhosttyTheme.current.accentYellow : GhosttyTheme.current.accentGreen)
                Text(project.effectiveAlias)
                    .font(GhosttyTheme.current.font(size: 12, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.foreground.opacity(0.5))
                    .lineLimit(1)
                Spacer()
            }

            // Button row (Yazi/Term disabled, Add enabled)
            HStack(spacing: 1) {
                Spacer()
                ActionButton("Yazi", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("Term", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("Add", tone: .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.addColumnByAlias(project.effectiveAlias) }
                }
                .frame(width: 34)
            }
        }
        .padding(2)
        .background(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(GhosttyTheme.current.foreground.opacity(0.03))
        )
    }

    private func compactStatus(_ text: String) -> String {
        if let t = text.split(separator: ": ").last, t.contains(":") {
            return String(t)
        }
        return text
    }

    private func projectPrimaryName(_ project: WorkspaceProject) -> String {
        let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = project.projectName
        if !alias.isEmpty && alias != projectName {
            return alias
        }
        return projectName
    }

    private func projectDetail(_ project: WorkspaceProject) -> String? {
        let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = project.projectName
        if project.type == "remote" {
            let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
            if !host.isEmpty {
                if !alias.isEmpty && alias != projectName {
                    return "\(projectName) · @\(host)"
                }
                return "@\(host)"
            }
        }
        if !alias.isEmpty && alias != projectName {
            return projectName
        }
        return nil
    }

    private func columnPrimaryName(_ column: LiveColumn) -> String {
        if let exact = vm.workspaceProjects.first(where: { $0.path == column.projectPath }) {
            let alias = exact.alias.trimmingCharacters(in: .whitespacesAndNewlines)
            if !alias.isEmpty && alias != exact.projectName {
                return alias
            }
            return exact.projectName
        }
        return column.projectName
    }

    private func columnMeta(_ column: LiveColumn) -> String? {
        guard column.hostLabel != "local" else {
            return nil
        }
        let host = column.hostLabel.replacingOccurrences(of: "remote@", with: "")
        if host.isEmpty || host == "remote" {
            return "@remote"
        }
        return "@\(host)"
    }

    private func liveHostLabel(_ column: LiveColumn) -> String {
        if let host = columnMeta(column) {
            return host
        }
        return "lcl"
    }

    private func pill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(GhosttyTheme.current.font(size: 9, weight: .bold))
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(
                Capsule(style: .circular)
                    .fill(tint.opacity(0.24))
            )
            .foregroundStyle(tint.opacity(0.95))
    }
}

struct WindowAccessor: NSViewRepresentable {
    let onResolve: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            if let window = view.window {
                onResolve(window)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            if let window = nsView.window {
                onResolve(window)
            }
        }
    }
}

struct ColumnDropDelegate: DropDelegate {
    let targetColumn: Int
    @Binding var draggingColumnID: Int?
    @Binding var dropTargetColumnID: Int?
    let viewModel: AppViewModel

    func dropEntered(info: DropInfo) {
        dropTargetColumnID = targetColumn
    }

    func dropExited(info: DropInfo) {
        if dropTargetColumnID == targetColumn {
            dropTargetColumnID = nil
        }
    }

    func performDrop(info: DropInfo) -> Bool {
        defer {
            draggingColumnID = nil
            dropTargetColumnID = nil
        }
        guard let source = draggingColumnID, source != targetColumn else { return false }
        Task {
            await viewModel.moveColumn(from: source, to: targetColumn)
        }
        return true
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }
}

@main
struct TprojApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 200, minHeight: 520, idealHeight: 980, maxHeight: 2200)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 275, height: 980)
        .windowResizability(.contentMinSize)
    }
}
