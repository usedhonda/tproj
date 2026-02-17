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

// MARK: - Ghostty Window Tracker

@MainActor
final class GhosttyWindowTracker: ObservableObject {
    @Published var isSnapped = false

    private var pollTimer: DispatchSourceTimer?
    private weak var appWindow: NSWindow?

    private let snapThreshold: CGFloat = 12
    // Snap-time offset: tproj.origin - ghostty.origin
    private var snapOffset: CGPoint = .zero
    private var lastGhosttyFrame: CGRect?
    // After detach, suppress re-snap for a short period
    private var detachCooldownUntil: Date?

    func attach(to window: NSWindow) {
        guard appWindow !== window else { return }
        detach()
        appWindow = window
        startPolling()
    }

    func detach() {
        stopPolling()
        appWindow = nil
        isSnapped = false
        lastGhosttyFrame = nil
        detachCooldownUntil = nil
    }

    deinit {
        pollTimer?.cancel()
    }

    // MARK: Polling

    private func startPolling() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now(), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in
            self?.tick()
        }
        timer.resume()
        pollTimer = timer
    }

    private func stopPolling() {
        pollTimer?.cancel()
        pollTimer = nil
    }

    private func updatePollingInterval() {
        guard let timer = pollTimer else { return }
        let ms: Int
        if isSnapped {
            ms = 16      // 60 fps – smooth follow
        } else if lastGhosttyFrame != nil {
            ms = 100     // Ghostty visible – snap detection
        } else {
            ms = 500     // Ghostty absent – minimal resource
        }
        timer.schedule(deadline: .now() + .milliseconds(ms), repeating: .milliseconds(ms))
    }

    private func visibleUnionFrame() -> CGRect? {
        let frames = NSScreen.screens.map { $0.visibleFrame }
        guard var union = frames.first else { return nil }
        for frame in frames.dropFirst() {
            union = union.union(frame)
        }
        return union
    }

    private func clampedOrigin(_ origin: CGPoint, windowSize: CGSize) -> CGPoint {
        guard let union = visibleUnionFrame() else { return origin }
        let maxX = max(union.minX, union.maxX - windowSize.width)
        let maxY = max(union.minY, union.maxY - windowSize.height)
        return CGPoint(
            x: min(max(origin.x, union.minX), maxX),
            y: min(max(origin.y, union.minY), maxY)
        )
    }

    private func nearlyEqual(_ lhs: CGPoint, _ rhs: CGPoint) -> Bool {
        abs(lhs.x - rhs.x) < 0.5 && abs(lhs.y - rhs.y) < 0.5
    }

    // MARK: Main loop

    private func tick() {
        guard let window = appWindow else { return }
        let currentOrigin = window.frame.origin
        let guardedOrigin = clampedOrigin(currentOrigin, windowSize: window.frame.size)
        if !nearlyEqual(currentOrigin, guardedOrigin) {
            window.setFrameOrigin(guardedOrigin)
        }

        guard let ghosttyFrame = findGhosttyFrame() else {
            let changed = isSnapped || lastGhosttyFrame != nil
            if isSnapped { isSnapped = false }
            lastGhosttyFrame = nil
            if changed { updatePollingInterval() }
            return
        }

        let prevSnapped = isSnapped

        if isSnapped {
            guard let last = lastGhosttyFrame else {
                lastGhosttyFrame = ghosttyFrame
                return
            }

            // Drift check: has the user dragged tproj away?
            let expectedX = last.origin.x + snapOffset.x
            let expectedY = last.origin.y + snapOffset.y
            let actual = window.frame.origin
            let drift = hypot(actual.x - expectedX, actual.y - expectedY)

            if drift > snapThreshold * 2 {
                // User moved the window -> detach
                isSnapped = false
                detachCooldownUntil = Date().addingTimeInterval(0.4)
                lastGhosttyFrame = ghosttyFrame
            } else {
                // Follow Ghostty movement
                let dx = ghosttyFrame.origin.x - last.origin.x
                let dy = ghosttyFrame.origin.y - last.origin.y
                if dx != 0 || dy != 0 {
                    var newOrigin = actual
                    newOrigin.x += dx
                    newOrigin.y += dy
                    newOrigin = clampedOrigin(newOrigin, windowSize: window.frame.size)
                    window.setFrameOrigin(newOrigin)
                    // Re-derive offset to absorb rounding
                    snapOffset = CGPoint(x: newOrigin.x - ghosttyFrame.origin.x,
                                         y: newOrigin.y - ghosttyFrame.origin.y)
                }
                lastGhosttyFrame = ghosttyFrame
            }
        } else {
            lastGhosttyFrame = ghosttyFrame

            // Cooldown after detach
            if let cooldownEnd = detachCooldownUntil {
                if Date() < cooldownEnd { return }
                detachCooldownUntil = nil
            }

            checkAndSnap(appFrame: window.frame, ghosttyFrame: ghosttyFrame)
        }

        if isSnapped != prevSnapped {
            updatePollingInterval()
        }
    }

    // MARK: Snap logic

    private func checkAndSnap(appFrame: NSRect, ghosttyFrame: NSRect) {
        // Horizontal edge distances
        let leftToRight = abs(appFrame.minX - ghosttyFrame.maxX)   // tproj left ~ Ghostty right
        let rightToLeft = abs(appFrame.maxX - ghosttyFrame.minX)   // tproj right ~ Ghostty left
        let hDist = min(leftToRight, rightToLeft)

        // Vertical edge distances (Cocoa: minY = bottom, maxY = top)
        let bottomToTop = abs(appFrame.minY - ghosttyFrame.maxY)   // tproj bottom ~ Ghostty top
        let topToBottom = abs(appFrame.maxY - ghosttyFrame.minY)   // tproj top ~ Ghostty bottom
        let vDist = min(bottomToTop, topToBottom)

        // Overlap checks (edges must be parallel-ish)
        let yOverlap = appFrame.maxY > ghosttyFrame.minY && appFrame.minY < ghosttyFrame.maxY
        let xOverlap = appFrame.maxX > ghosttyFrame.minX && appFrame.minX < ghosttyFrame.maxX

        let horizontalSnap = hDist <= snapThreshold && yOverlap
        let verticalSnap = vDist <= snapThreshold && xOverlap

        if horizontalSnap || verticalSnap {
            snapOffset = CGPoint(
                x: appFrame.origin.x - ghosttyFrame.origin.x,
                y: appFrame.origin.y - ghosttyFrame.origin.y
            )
            isSnapped = true
        }
    }

    // MARK: Ghostty window discovery

    private func findGhosttyFrame() -> NSRect? {
        let options: CGWindowListOption = [.excludeDesktopElements, .optionOnScreenOnly]
        guard let list = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }
        guard let screenHeight = NSScreen.main?.frame.height else { return nil }

        for info in list {
            guard let name = info[kCGWindowOwnerName as String] as? String,
                  name == "Ghostty",
                  let layer = info[kCGWindowLayer as String] as? Int,
                  layer == 0,   // normal windows only (skip menu bar, popups)
                  let bounds = info[kCGWindowBounds as String] as? [String: NSNumber],
                  let x = bounds["X"],
                  let y = bounds["Y"],
                  let w = bounds["Width"],
                  let h = bounds["Height"] else {
                continue
            }
            let cgX = CGFloat(truncating: x)
            let cgY = CGFloat(truncating: y)
            let cgW = CGFloat(truncating: w)
            let cgH = CGFloat(truncating: h)
            // CG coords (top-left origin) -> Cocoa coords (bottom-left origin)
            let cocoaY = screenHeight - cgY - cgH
            return NSRect(x: cgX, y: cocoaY, width: cgW, height: cgH)
        }
        return nil
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

struct MonitorSystem: Codable {
    var totalMB: Int
    var usedMB: Int
    var freeMB: Int

    enum CodingKeys: String, CodingKey {
        case totalMB = "total_mb"
        case usedMB = "used_mb"
        case freeMB = "free_mb"
    }

    init(totalMB: Int = 0, usedMB: Int = 0, freeMB: Int = 0) {
        self.totalMB = totalMB
        self.usedMB = usedMB
        self.freeMB = freeMB
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        totalMB = try c.decodeIfPresent(Int.self, forKey: .totalMB) ?? 0
        usedMB = try c.decodeIfPresent(Int.self, forKey: .usedMB) ?? 0
        freeMB = try c.decodeIfPresent(Int.self, forKey: .freeMB) ?? 0
    }
}

struct MonitorCategory: Codable {
    var mb: Int
    var count: Int?

    init(mb: Int = 0, count: Int? = nil) {
        self.mb = mb
        self.count = count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mb = try c.decodeIfPresent(Int.self, forKey: .mb) ?? 0
        count = try c.decodeIfPresent(Int.self, forKey: .count)
    }
}

struct MonitorCCProcess: Codable {
    var pid: Int
    var rssMB: Int
    var cpu: Double
    var state: String
    var project: String

    enum CodingKeys: String, CodingKey {
        case pid
        case rssMB = "rss_mb"
        case cpu
        case state
        case project
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pid = try c.decodeIfPresent(Int.self, forKey: .pid) ?? 0
        rssMB = try c.decodeIfPresent(Int.self, forKey: .rssMB) ?? 0
        cpu = try c.decodeIfPresent(Double.self, forKey: .cpu) ?? 0
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
    }
}

struct MonitorPane: Identifiable, Codable {
    var session: String
    var window: String
    var paneID: String
    var paneIndex: Int
    var role: String
    var column: Int?
    var project: String
    var rssMB: Int
    var cpu: Double
    var bucketCMB: Int
    var bucketMMB: Int
    var bucketXMB: Int
    var bucketOMB: Int
    var state: String
    var agentType: String

    var id: String { paneID }

    enum CodingKeys: String, CodingKey {
        case session
        case window
        case paneID = "pane_id"
        case paneIndex = "pane_index"
        case role
        case column
        case project
        case rssMB = "rss_mb"
        case cpu
        case bucketCMB = "bucket_c_mb"
        case bucketMMB = "bucket_m_mb"
        case bucketXMB = "bucket_x_mb"
        case bucketOMB = "bucket_o_mb"
        case state
        case agentType = "agent_type"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        session = try c.decodeIfPresent(String.self, forKey: .session) ?? ""
        window = try c.decodeIfPresent(String.self, forKey: .window) ?? ""
        paneID = try c.decodeIfPresent(String.self, forKey: .paneID) ?? ""
        paneIndex = try c.decodeIfPresent(Int.self, forKey: .paneIndex) ?? -1
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        column = try c.decodeIfPresent(Int.self, forKey: .column)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        rssMB = try c.decodeIfPresent(Int.self, forKey: .rssMB) ?? 0
        cpu = try c.decodeIfPresent(Double.self, forKey: .cpu) ?? 0
        bucketCMB = try c.decodeIfPresent(Int.self, forKey: .bucketCMB) ?? 0
        bucketMMB = try c.decodeIfPresent(Int.self, forKey: .bucketMMB) ?? 0
        bucketXMB = try c.decodeIfPresent(Int.self, forKey: .bucketXMB) ?? 0
        bucketOMB = try c.decodeIfPresent(Int.self, forKey: .bucketOMB) ?? 0
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        agentType = try c.decodeIfPresent(String.self, forKey: .agentType) ?? "other"
    }
}

struct MonitorColumn: Identifiable, Codable {
    var column: Int
    var project: String
    var ccMB: Int
    var codexMB: Int
    var totalMB: Int
    var ccActive: Int
    var codexActive: Int

    var id: Int { column }

    enum CodingKeys: String, CodingKey {
        case column
        case project
        case ccMB = "cc_mb"
        case codexMB = "codex_mb"
        case totalMB = "total_mb"
        case ccActive = "cc_active"
        case codexActive = "codex_active"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        column = try c.decodeIfPresent(Int.self, forKey: .column) ?? 0
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        ccMB = try c.decodeIfPresent(Int.self, forKey: .ccMB) ?? 0
        codexMB = try c.decodeIfPresent(Int.self, forKey: .codexMB) ?? 0
        totalMB = try c.decodeIfPresent(Int.self, forKey: .totalMB) ?? 0
        ccActive = try c.decodeIfPresent(Int.self, forKey: .ccActive) ?? 0
        codexActive = try c.decodeIfPresent(Int.self, forKey: .codexActive) ?? 0
    }
}

struct MonitorCollector: Codable {
    var version: String
    var source: String
    var errors: [String]

    init(version: String = "", source: String = "", errors: [String] = []) {
        self.version = version
        self.source = source
        self.errors = errors
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decodeIfPresent(String.self, forKey: .version) ?? ""
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        errors = try c.decodeIfPresent([String].self, forKey: .errors) ?? []
    }
}

struct MonitorStatus: Codable {
    var timestamp: String
    var system: MonitorSystem
    var categories: [String: MonitorCategory]
    var ccProcesses: [MonitorCCProcess]
    var guardState: String
    var panes: [MonitorPane]
    var columns: [MonitorColumn]
    var collector: MonitorCollector

    enum CodingKeys: String, CodingKey {
        case timestamp
        case system
        case categories
        case ccProcesses = "cc_processes"
        case guardState = "guard"
        case panes
        case columns
        case collector
    }

    init(
        timestamp: String = "",
        system: MonitorSystem = MonitorSystem(),
        categories: [String: MonitorCategory] = [:],
        ccProcesses: [MonitorCCProcess] = [],
        guardState: String = "unknown",
        panes: [MonitorPane] = [],
        columns: [MonitorColumn] = [],
        collector: MonitorCollector = MonitorCollector()
    ) {
        self.timestamp = timestamp
        self.system = system
        self.categories = categories
        self.ccProcesses = ccProcesses
        self.guardState = guardState
        self.panes = panes
        self.columns = columns
        self.collector = collector
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp) ?? ""
        system = try c.decodeIfPresent(MonitorSystem.self, forKey: .system) ?? MonitorSystem()
        categories = try c.decodeIfPresent([String: MonitorCategory].self, forKey: .categories) ?? [:]
        ccProcesses = try c.decodeIfPresent([MonitorCCProcess].self, forKey: .ccProcesses) ?? []
        guardState = try c.decodeIfPresent(String.self, forKey: .guardState) ?? "unknown"
        panes = try c.decodeIfPresent([MonitorPane].self, forKey: .panes) ?? []
        columns = try c.decodeIfPresent([MonitorColumn].self, forKey: .columns) ?? []
        collector = try c.decodeIfPresent(MonitorCollector.self, forKey: .collector) ?? MonitorCollector()
    }
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
        let clientStatus = MIDIClientCreateWithBlock("tproj-midi-client" as CFString, &createdClient) { [weak self] notification in
            guard notification.pointee.messageID == .msgSetupChanged else { return }
            self?.reconnectSources()
        }
        guard clientStatus == noErr else {
            onStatus?("MIDI init failed (client: \(clientStatus))")
            return
        }
        client = createdClient

        var createdPort = MIDIPortRef()
        let portStatus = MIDIInputPortCreateWithBlock(client, "tproj-midi-input" as CFString, &createdPort) { [weak self] packetList, _ in
            self?.handlePacketList(packetList)
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

    private func reconnectSources() {
        guard isRunning else { return }
        connectedSources.forEach { MIDIPortDisconnectSource(inputPort, $0) }
        connectedSources.removeAll()
        connectSources()
        if connectedSources.isEmpty {
            onStatus?("MIDI: device disconnected")
        } else {
            onStatus?("MIDI: reconnected (\(connectedSources.count) source)")
        }
    }

    private func handlePacketList(_ packetList: UnsafePointer<MIDIPacketList>) {
        let numPackets = Int(packetList.pointee.numPackets)
        guard numPackets > 0 else { return }

        var packet = packetList.pointee.packet
        for i in 0..<numPackets {
            // Direct tuple access (same as dj_presenter)
            let statusByte = packet.data.0
            let data1 = packet.data.1
            let data2 = packet.data.2
            handleMessage(status: statusByte, data1: data1, data2: data2)
            if i < numPackets - 1 {
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

@MainActor
final class AppViewModel: ObservableObject {
    @Published var workspaceProjects: [WorkspaceProject] = []
    @Published var liveColumns: [LiveColumn] = []
    @Published var selectedAlias: String = ""
    @Published var statusText: String = "Ready"
    @Published var isBusy: Bool = false
    @Published var isMIDILearning: Bool = false
    @Published var memoryStatus: MonitorStatus?
    @Published var memoryErrorText: String?
    @Published var memoryLastUpdatedAt: Date?

    private let fileManager = FileManager.default
    private let monitorStatusPath = "/tmp/tproj-monitor-status.json"
    private var memoryPollTask: Task<Void, Never>?

    // MARK: - PATH & Dependency Resolution

    nonisolated private static let builtinExtraPaths: [String] = {
        let home = NSHomeDirectory()
        return [
            "\(home)/bin",
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
        ]
    }()

    nonisolated(unsafe) private static var resolvedPATH: String = buildPATH(extraPaths: [])

    nonisolated private static func buildPATH(extraPaths: [String]) -> String {
        let all = builtinExtraPaths + extraPaths
        let existing = ProcessInfo.processInfo.environment["PATH"]
            ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        let existingSet = Set(existing.split(separator: ":").map(String.init))
        let extras = all.filter { !existingSet.contains($0) }
        return (extras + [existing]).joined(separator: ":")
    }
    private var midiActivator: MIDIPaneActivator?
    private var startupRetryTask: Task<Void, Never>?

    struct StartupDiag {
        struct Dep {
            let name: String
            let hint: String
            let found: Bool
            let required: Bool
        }
        let deps: [Dep]
        let sessionExists: Bool
        let yamlExists: Bool
        var hasCriticalMissing: Bool { deps.contains { $0.required && !$0.found } }
    }

    @Published var startupDiag: StartupDiag?

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

    // MARK: - GUI Config & Dependency Check

    private func loadGUIConfig() {
        // Try reading gui.extra_paths from workspace.yaml using yq on builtin PATH
        let result = runCommand("/usr/bin/env", ["yq", "-r",
            ".gui.extra_paths[]? // empty", workspacePath])
        if result.exitCode == 0 {
            let paths = result.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .map(String.init)
                .filter { !$0.isEmpty }
            if !paths.isEmpty {
                Self.resolvedPATH = Self.buildPATH(extraPaths: paths)
            }
        }
    }

    private func checkDependencies() -> StartupDiag {
        // Load custom dependencies from workspace.yaml, or use builtin defaults
        var depDefs: [(name: String, required: Bool, hint: String)] = []

        let depResult = runCommand("/usr/bin/env", ["yq", "-r",
            ".gui.dependencies[]? | [.name, (.required // true | tostring), (.hint // \"\")] | @tsv",
            workspacePath])
        if depResult.exitCode == 0 && !depResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            for line in depResult.stdout.split(separator: "\n", omittingEmptySubsequences: true) {
                let parts = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
                if parts.count >= 3 {
                    depDefs.append((name: parts[0], required: parts[1].lowercased() == "true", hint: parts[2]))
                }
            }
        }

        // Builtin defaults if YAML had nothing
        if depDefs.isEmpty {
            depDefs = [
                (name: "tmux", required: true, hint: "brew install tmux"),
                (name: "yq", required: false, hint: "brew install yq"),
            ]
        }

        // Search PATH directories for each dependency
        let pathDirs = Self.resolvedPATH.split(separator: ":").map(String.init)
        var deps: [StartupDiag.Dep] = []
        for def in depDefs {
            let found = pathDirs.contains { dir in
                fileManager.isExecutableFile(atPath: "\(dir)/\(def.name)")
            }
            deps.append(StartupDiag.Dep(name: def.name, hint: def.hint, found: found, required: def.required))
        }

        // Check tmux session existence
        var sessionExists = false
        if deps.contains(where: { $0.name == "tmux" && $0.found }) {
            let sesResult = runCommand("/usr/bin/env", ["tmux", "has-session", "-t", "tproj-workspace"])
            sessionExists = sesResult.exitCode == 0
        }

        let yamlExists = fileManager.fileExists(atPath: workspacePath)

        return StartupDiag(deps: deps, sessionExists: sessionExists, yamlExists: yamlExists)
    }

    func onAppear() {
        Task {
            loadGUIConfig()
            let diag = checkDependencies()
            startupDiag = diag

            if diag.hasCriticalMissing {
                let missing = diag.deps.filter { $0.required && !$0.found }
                    .map { "\($0.name) (\($0.hint))" }
                    .joined(separator: ", ")
                statusText = "Missing: \(missing)"
                return
            }

            await refreshAll()
            await refreshMemoryStatus()
            startMemoryPolling()
            startMIDIIfNeeded()

            if liveColumns.isEmpty {
                if !diag.sessionExists {
                    statusText = "Waiting for tproj session..."
                }
                startStartupRetry()
            }
        }
    }

    private func startStartupRetry() {
        startupRetryTask = Task {
            for attempt in 0..<10 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }

                // Re-check dependencies every 3rd attempt (user may install mid-retry)
                if attempt % 3 == 2 {
                    loadGUIConfig()
                    let diag = checkDependencies()
                    startupDiag = diag
                    if diag.hasCriticalMissing {
                        let missing = diag.deps.filter { $0.required && !$0.found }
                            .map { "\($0.name) (\($0.hint))" }
                            .joined(separator: ", ")
                        statusText = "Missing: \(missing)"
                        continue
                    }
                }

                await refreshAll()
                if !liveColumns.isEmpty {
                    // Wait for column count to stabilize (max 3 additional retries)
                    var stableCount = 0
                    var lastCount = liveColumns.count
                    for _ in 0..<3 {
                        try? await Task.sleep(nanoseconds: 1_000_000_000)
                        if Task.isCancelled { return }
                        await refreshAll()
                        if liveColumns.count == lastCount {
                            stableCount += 1
                            if stableCount >= 2 { return }
                        } else {
                            lastCount = liveColumns.count
                            stableCount = 0
                        }
                    }
                    return
                }
            }
        }
    }

    deinit {
        memoryPollTask?.cancel()
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

    private func startMemoryPolling() {
        guard memoryPollTask == nil else { return }
        memoryPollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                if Task.isCancelled { return }
                await self?.refreshMemoryStatus()
            }
        }
    }

    private func refreshMemoryStatus() async {
        let collectorCommand = monitorCollectorCommand()
        let result = await runCommandAsync(collectorCommand.launchPath, collectorCommand.arguments)

        guard result.exitCode == 0 else {
            let reason = trimmedError(result)
            let message = reason.isEmpty ? "Monitor command failed" : "Monitor: \(reason)"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
            return
        }

        guard let data = result.stdout.data(using: .utf8) else {
            let message = "Monitor: invalid output encoding"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
            return
        }

        do {
            let snapshot = try JSONDecoder().decode(MonitorStatus.self, from: data)
            memoryStatus = snapshot
            memoryLastUpdatedAt = Date()
            memoryErrorText = snapshot.collector.errors.isEmpty ? nil : snapshot.collector.errors[0]
            persistMonitorStatus(snapshot)
        } catch {
            let message = "Monitor decode failed: \(error.localizedDescription)"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
        }
    }

    private func monitorCollectorCommand() -> (launchPath: String, arguments: [String]) {
        let command = "tproj-mem-json"
        let homeCollector = "\(NSHomeDirectory())/bin/\(command)"
        if fileManager.isExecutableFile(atPath: homeCollector) {
            return (homeCollector, ["--json"])
        }

        let bundledCollector = Bundle.main.resourceURL?.appendingPathComponent(command).path ?? ""
        if !bundledCollector.isEmpty && fileManager.isExecutableFile(atPath: bundledCollector) {
            return (bundledCollector, ["--json"])
        }

        if let repoCollector = locateInAncestorBin(commandName: command) {
            return (repoCollector, ["--json"])
        }

        return ("/usr/bin/env", [command, "--json"])
    }

    private func locateInAncestorBin(commandName: String) -> String? {
        var startPaths: [URL] = []
        startPaths.append(URL(fileURLWithPath: fileManager.currentDirectoryPath, isDirectory: true))

        if let executablePath = Bundle.main.executablePath, !executablePath.isEmpty {
            startPaths.append(URL(fileURLWithPath: executablePath).deletingLastPathComponent())
        }

        startPaths.append(URL(fileURLWithPath: Bundle.main.bundlePath, isDirectory: true))

        var visited = Set<String>()
        for start in startPaths where !start.path.isEmpty {
            var cursor = start
            while true {
                let candidate = cursor.appendingPathComponent("bin/\(commandName)").path
                if visited.insert(candidate).inserted && fileManager.isExecutableFile(atPath: candidate) {
                    return candidate
                }

                let parent = cursor.deletingLastPathComponent()
                if parent.path == cursor.path {
                    break
                }
                cursor = parent
            }
        }

        return nil
    }

    private func persistMonitorStatus(_ snapshot: MonitorStatus) {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(snapshot)
            let url = URL(fileURLWithPath: monitorStatusPath)
            try data.write(to: url, options: .atomic)
        } catch {
            if memoryErrorText == nil {
                memoryErrorText = "Monitor cache write failed: \(error.localizedDescription)"
            }
        }
    }

    private func persistMonitorErrorStatus(_ message: String) {
        let snapshot = MonitorStatus(
            timestamp: currentISO8601Timestamp(),
            collector: MonitorCollector(version: "", source: "tproj-app", errors: [message])
        )
        persistMonitorStatus(snapshot)
    }

    private func currentISO8601Timestamp() -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: Date())
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
            let errText = trimmedError(result)
            if errText.contains("No such file or directory") && errText.contains("yq") {
                statusText = "yq not installed (brew install yq)"
            } else {
                statusText = "workspace.yaml parse error: \(errText)"
            }
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

        // GUI apps don't inherit the user's shell PATH; use resolved PATH
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = Self.resolvedPATH
        process.environment = env

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
    @StateObject private var ghosttyTracker = GhosttyWindowTracker()
    @State private var draggingColumnID: Int?
    @State private var dropTargetColumnID: Int?
    @State private var didRecoverWindowFrame = false

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
                            if ghosttyTracker.isSnapped {
                                Circle()
                                    .fill(GhosttyTheme.current.accentCyan)
                                    .frame(width: 5, height: 5)
                                    .shadow(color: GhosttyTheme.current.accentCyan.opacity(0.6), radius: 2)
                            }
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
                            startupDiagView()
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

                    SectionHeader(title: "Memory")
                    Card(compact: true, chrome: false) {
                        memorySection()
                    }

                    SectionHeader(title: "CC & Codex")
                    Card(compact: true, chrome: false) {
                        monitorSection()
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
                if !didRecoverWindowFrame {
                    recoverWindowFrameIfNeeded(window)
                    window.makeKeyAndOrderFront(nil)
                    NSApp.activate(ignoringOtherApps: true)
                    didRecoverWindowFrame = true
                }
                ghosttyTracker.attach(to: window)
            }
        )
    }

    private func recoverWindowFrameIfNeeded(_ window: NSWindow) {
        let current = window.frame
        let visibleScreens = NSScreen.screens.map { $0.visibleFrame }
        let isVisible = visibleScreens.contains { screen in
            current.intersects(screen.insetBy(dx: -40, dy: -40))
        }
        guard !isVisible else { return }

        guard let main = NSScreen.main?.visibleFrame ?? NSScreen.screens.first?.visibleFrame else { return }
        let x = main.minX + 24
        let y = max(main.minY + 24, main.maxY - current.height - 24)
        window.setFrameOrigin(NSPoint(x: x, y: y))
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
        .padding(.leading, 10)   // accent bar との間隔確保
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
                .shadow(color: GhosttyTheme.current.accentCyan.opacity(0.7), radius: 3, x: 0, y: 0)
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
        .padding(.vertical, 2)
        .padding(.leading, 10)     // liveColumnRow と揃える
        .padding(.trailing, 2)
        .background(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(GhosttyTheme.current.foreground.opacity(0.03))
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1)
                .fill(GhosttyTheme.current.foreground.opacity(0.2))
                .frame(width: 2)
        }
    }

    @ViewBuilder
    private func startupDiagView() -> some View {
        if let diag = vm.startupDiag {
            let missingRequired = diag.deps.filter { $0.required && !$0.found }
            let missingOptional = diag.deps.filter { !$0.required && !$0.found }

            if !missingRequired.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(missingRequired, id: \.name) { dep in
                        Text("Missing: \(dep.name)  \u{2192}  \(dep.hint)")
                    }
                    if !missingOptional.isEmpty {
                        ForEach(missingOptional, id: \.name) { dep in
                            Text("Optional: \(dep.name)  \u{2192}  \(dep.hint)")
                        }
                    }
                }
            } else if !diag.sessionExists {
                Text("No tproj session  \u{2192}  Run: tproj")
            } else {
                Text("No active columns in tproj-workspace")
            }
        } else {
            Text("Checking dependencies...")
        }
    }

    @ViewBuilder
    private func memorySection() -> some View {
        VStack(alignment: .leading, spacing: 3) {
            if let status = vm.memoryStatus {
                let sys = status.system
                HStack(spacing: 4) {
                    Text("Free \(sys.freeMB)M")
                        .font(GhosttyTheme.current.font(size: 11, weight: .semibold, monospaced: true))
                        .foregroundStyle(memorySeverityColor(freeMB: sys.freeMB))
                    Text("Used \(sys.usedMB)M / \(sys.totalMB)M \(memoryBreakdownText(status.categories))")
                        .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                    if let updated = vm.memoryLastUpdatedAt {
                        Text(updatedTimeText(updated))
                            .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textTertiary)
                    }
                }

                usageBar(usedMB: sys.usedMB, totalMB: sys.totalMB, color: memorySeverityColor(freeMB: sys.freeMB))
                ecosystemBar(status.categories)

                HStack(spacing: 4) {
                    Text("Guard")
                        .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                    Text(status.guardState)
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                        .foregroundStyle(guardColor(status.guardState))
                    Spacer(minLength: 0)
                }

                let columnMap = status.columns.reduce(into: [Int: MonitorColumn]()) { acc, item in
                    acc[item.column] = item
                }
                ForEach(vm.liveColumns.sorted(by: { $0.column < $1.column })) { column in
                    let colMem = columnMap[column.column]
                    HStack(spacing: 4) {
                        Text("#\(column.column)")
                            .font(GhosttyTheme.current.font(size: 10, weight: .heavy, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textSecondary)
                        Text(columnPrimaryName(column))
                            .font(GhosttyTheme.current.font(size: 10, weight: .semibold))
                            .foregroundStyle(GhosttyTheme.current.textSecondary)
                            .lineLimit(1)
                        Spacer(minLength: 0)
                        Text("\(colMem?.ccMB ?? 0)/\(colMem?.codexMB ?? 0)")
                            .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textTertiary)
                        Text("\(colMem?.totalMB ?? 0)M")
                            .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textPrimary)
                    }
                }
            } else {
                Text("Loading monitor...")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            }

            if let error = vm.memoryErrorText, !error.isEmpty {
                Text(error)
                    .font(GhosttyTheme.current.font(size: 10, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.accentRed.opacity(0.92))
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func monitorSection() -> some View {
        VStack(alignment: .leading, spacing: 3) {
            let panes = vm.memoryStatus?.panes ?? []
            let categories = vm.memoryStatus?.categories ?? [:]
            let ccPanes = panes
                .filter { $0.agentType == "cc" }
                .sorted(by: monitorPaneSort)
            let codexPanes = panes
                .filter { $0.agentType == "codex" }
                .sorted(by: monitorPaneSort)

            monitorGroup(title: "CC", panes: ccPanes, summary: monitorSummaryText(title: "CC", panes: ccPanes, categories: categories))
            monitorGroup(title: "Codex", panes: codexPanes, summary: monitorSummaryText(title: "Codex", panes: codexPanes, categories: categories))

            if panes.isEmpty {
                Text("No pane monitor data")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            } else {
                Text("Legend: C=Claude/CC, M=MCP, X=Codex, O=Other")
                    .font(GhosttyTheme.current.font(size: 9, weight: .medium, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
    }

    @ViewBuilder
    private func monitorGroup(title: String, panes: [MonitorPane], summary: String) -> some View {
        HStack(spacing: 4) {
            Text(title)
                .font(GhosttyTheme.current.font(size: 11, weight: .bold))
                .foregroundStyle(GhosttyTheme.current.textPrimary)
            Text("(\(summary))")
                .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                .foregroundStyle(GhosttyTheme.current.textTertiary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: 0)
        }

        if panes.isEmpty {
            Text("none")
                .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                .foregroundStyle(GhosttyTheme.current.textTertiary)
        } else {
            ForEach(panes) { pane in
                HStack(spacing: 4) {
                    Text(pane.column.map { "#\($0)" } ?? "--")
                        .font(GhosttyTheme.current.font(size: 10, weight: .heavy, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                    Text(pane.project.isEmpty ? pane.window : pane.project)
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                    Text(paneMetricText(pane))
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Circle()
                        .fill(paneStateColor(pane.state))
                        .frame(width: 5, height: 5)
                }
            }
        }
    }

    private func usageBar(usedMB: Int, totalMB: Int, color: Color) -> some View {
        let safeTotal = max(totalMB, 1)
        let ratio = min(max(CGFloat(usedMB) / CGFloat(safeTotal), 0), 1)

        return ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(GhosttyTheme.current.foreground.opacity(0.08))
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(color.opacity(0.9))
                .frame(maxWidth: .infinity, alignment: .leading)
                .mask(
                    GeometryReader { proxy in
                        Rectangle()
                            .frame(width: proxy.size.width * ratio, alignment: .leading)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    }
                )
        }
        .frame(height: 6)
    }

    private func ecosystemBar(_ categories: [String: MonitorCategory]) -> some View {
        let parts: [(String, Color)] = [
            ("cc_sessions", GhosttyTheme.current.accentGreen),
            ("mcp_servers", GhosttyTheme.current.accentYellow),
            ("codex", GhosttyTheme.current.accentBlue),
            ("chrome", GhosttyTheme.current.accentCyan),
            ("slack", GhosttyTheme.current.accentRed)
        ]
        let values = parts.map { max(Double(categories[$0.0]?.mb ?? 0), 0) }
        let total = max(values.reduce(0, +), 1)

        return GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(GhosttyTheme.current.foreground.opacity(0.08))
                ForEach(Array(parts.enumerated()), id: \.offset) { idx, pair in
                    let prefix = values.prefix(idx).reduce(0, +)
                    let x = geo.size.width * CGFloat(prefix / total)
                    let width = geo.size.width * CGFloat(values[idx] / total)
                    Rectangle()
                        .fill(pair.1.opacity(0.92))
                        .frame(width: width > 0 ? max(width, 1) : 0, height: 6)
                        .offset(x: x)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 2, style: .continuous))
        }
        .frame(height: 6)
    }

    private func memoryBreakdownText(_ categories: [String: MonitorCategory]) -> String {
        let cc = categories["cc_sessions"]?.mb ?? 0
        let mcp = categories["mcp_servers"]?.mb ?? 0
        let cdx = categories["codex"]?.mb ?? 0
        let chr = categories["chrome"]?.mb ?? 0
        let slk = categories["slack"]?.mb ?? 0
        return "(CC \(cc) | MCP \(mcp) | Cdx \(cdx) | Chr \(chr) | Slk \(slk))"
    }

    private func monitorSummaryText(title: String, panes: [MonitorPane], categories: [String: MonitorCategory]) -> String {
        let totalMB = panes.reduce(0) { $0 + $1.rssMB }
        let active = panes.filter { $0.state.lowercased() == "active" }.count

        if title == "CC" {
            let mcpMB = categories["mcp_servers"]?.mb ?? 0
            let mcpCount = categories["mcp_servers"]?.count ?? 0
            return "\(panes.count), \(totalMB)M, A\(active) | MCP \(mcpMB)/\(mcpCount)"
        }

        let chrMB = categories["chrome"]?.mb ?? 0
        let slkMB = categories["slack"]?.mb ?? 0
        return "\(panes.count), \(totalMB)M, A\(active) | Chr \(chrMB) Slk \(slkMB)"
    }

    private func paneMetricText(_ pane: MonitorPane) -> String {
        let c = pane.bucketCMB
        let m = pane.bucketMMB
        let x = pane.bucketXMB
        let o = pane.bucketOMB

        // Save horizontal space:
        // - CC rows omit X and fold it into O
        // - Codex rows omit C and fold it into O
        if pane.agentType == "cc" {
            return "\(pane.rssMB)M(C\(c)+M\(m)+O\(o + x))"
        }
        if pane.agentType == "codex" {
            return "\(pane.rssMB)M(X\(x)+M\(m)+O\(o + c))"
        }
        return "\(pane.rssMB)M(M\(m)+O\(o + c + x))"
    }

    private func monitorPaneSort(_ lhs: MonitorPane, _ rhs: MonitorPane) -> Bool {
        if lhs.rssMB != rhs.rssMB { return lhs.rssMB > rhs.rssMB }

        let lhsColumn = lhs.column ?? Int.max
        let rhsColumn = rhs.column ?? Int.max
        if lhsColumn != rhsColumn { return lhsColumn < rhsColumn }

        let lhsName = lhs.project.isEmpty ? lhs.window : lhs.project
        let rhsName = rhs.project.isEmpty ? rhs.window : rhs.project
        if lhsName != rhsName { return lhsName.localizedCaseInsensitiveCompare(rhsName) == .orderedAscending }

        return lhs.id < rhs.id
    }

    private func memorySeverityColor(freeMB: Int) -> Color {
        if freeMB <= 200 { return GhosttyTheme.current.accentRed }
        if freeMB <= 500 { return GhosttyTheme.current.accentYellow }
        return GhosttyTheme.current.accentGreen
    }

    private func guardColor(_ state: String) -> Color {
        switch state.lowercased() {
        case "running":
            return GhosttyTheme.current.accentGreen
        case "stopped":
            return GhosttyTheme.current.accentRed
        default:
            return GhosttyTheme.current.textTertiary
        }
    }

    private func paneStateColor(_ state: String) -> Color {
        switch state.lowercased() {
        case "active":
            return GhosttyTheme.current.accentGreen
        case "idle":
            return GhosttyTheme.current.accentYellow
        default:
            return GhosttyTheme.current.textTertiary
        }
    }

    private func updatedTimeText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: date)
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
    init() {
        loadAppIcon()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 200, minHeight: 520, idealHeight: 980, maxHeight: 2200)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 275, height: 980)
        .windowResizability(.contentMinSize)
    }

    private func loadAppIcon() {
        // 1. .app bundle (dist): icon registered via Info.plist CFBundleIconFile
        if let iconPath = Bundle.main.path(forResource: "AppIcon", ofType: "icns"),
           let icon = NSImage(contentsOfFile: iconPath) {
            NSApplication.shared.applicationIconImage = icon
            return
        }

        // 2. Development build: resolve from executable path
        //    .build/arm64-apple-macosx/debug/tproj -> ../../../Resources/AppIcon.icns
        let execURL = URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            .resolvingSymlinksInPath()
        let devIcon = execURL
            .deletingLastPathComponent()  // debug/
            .deletingLastPathComponent()  // arm64-apple-macosx/
            .deletingLastPathComponent()  // .build/
            .appendingPathComponent("Resources/AppIcon.icns")
        if let icon = NSImage(contentsOfFile: devIcon.path) {
            NSApplication.shared.applicationIconImage = icon
        }
    }
}
