import Foundation

// Per-project role mode. `auto` is the default and is represented ON DISK by the
// ABSENCE of `<project>/.local/role-mode.json`; `advisor` and `solo` are written
// as a small JSON object. Pure parse/serialize/cycle logic lives here so it can
// be unit-tested without touching the filesystem; the app layer keeps file IO
// thin. See docs/reference/role-mode.md.
public enum RoleMode: String, CaseIterable {
    case auto
    case advisor
    case solo

    public var displayName: String {
        self == .auto ? "Team" : rawValue.capitalized
    }

    // Badge click cycle order: auto -> advisor -> solo -> auto.
    public var next: RoleMode {
        switch self {
        case .auto: return .advisor
        case .advisor: return .solo
        case .solo: return .auto
        }
    }

    // Parse the on-disk file contents. Absent (nil data), unreadable/corrupt
    // JSON, and an unrecognized mode value all resolve to `auto`, matching the
    // contract's "absent means auto" rule.
    public static func parse(_ data: Data?) -> RoleMode {
        guard let data else { return .auto }
        guard let record = try? JSONDecoder().decode(Record.self, from: data),
              let mode = RoleMode(rawValue: record.mode) else {
            return .auto
        }
        return mode
    }

    // Serialize a declared mode to the file's JSON shape (mode/set_at/set_by/
    // source, sorted keys). Returns nil for `auto`, since declaring auto deletes
    // the file rather than writing one.
    public func fileContents(setBy: String, source: String, setAt: Int) -> Data? {
        guard self != .auto else { return nil }
        let record = Record(mode: rawValue, setAt: setAt, setBy: setBy, source: source)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try? encoder.encode(record)
    }

    private struct Record: Codable {
        var mode: String
        var setAt: Int
        var setBy: String
        var source: String

        enum CodingKeys: String, CodingKey {
            case mode
            case setAt = "set_at"
            case setBy = "set_by"
            case source
        }
    }

    // Parse `model-role-router mode --json` output into mode + lead + main. Any failure
    // (nil, corrupt, unrecognized mode) resolves to auto with no lead, matching
    // the "treat unreadable as auto" rule. `lead` is passed through verbatim
    // ("cc" / "cdx" / "" when no pane has resolved a role yet).
    public static func parseStatus(_ data: Data?) -> RoleModeStatus {
        guard let data,
              let record = try? JSONDecoder().decode(StatusRecord.self, from: data) else {
            return RoleModeStatus(mode: .auto, lead: "")
        }
        let mode = RoleMode(rawValue: record.mode ?? "") ?? .auto
        let main = ["cc", "cdx"].contains(record.main ?? "") ? record.main ?? "" : ""
        return RoleModeStatus(mode: mode, lead: record.lead ?? "", main: main)
    }

    private struct StatusRecord: Codable {
        var mode: String?
        var lead: String?
        var main: String?
    }
}

// One project's derived role state: the declared mode plus which side leads.
public struct RoleModeStatus: Equatable {
    public var mode: RoleMode
    public var lead: String   // "cc", "cdx", or "" (no pane resolved yet)
    public var main: String   // User's preferred conversation side; never role authority.

    public init(mode: RoleMode, lead: String, main: String = "") {
        self.mode = mode
        self.lead = lead
        self.main = main
    }
}

// The explicit conversation preference wins for display and pane choice. With
// no preference, use the derived lead, then Cdx as the GUI's stable default so
// one conversation side is always selected.
public func roleModeConversationMain(mode: RoleMode, main: String, lead: String) -> String {
    if main == "cc" || main == "cdx" { return main }
    if lead == "cc" || lead == "cdx" { return lead }
    return "cdx"
}

// Keep command construction pure and testable. The router remains the only
// writer/interpreter of the per-project role-mode document.
public func roleModeSetArguments(mode: RoleMode, main: String, projectPath: String) -> [String] {
    let mainValue = (main == "cc" || main == "cdx") ? main : "derived"
    return [
        "mode", mode.rawValue,
        "--main", mainValue,
        "--json",
        "--project", projectPath,
        "--set-by", "gui",
        "--source", "tproj-gui",
    ]
}

// Display form of a lead side, capitalized to match the row's CC / Cdx action
// buttons. Anything unrecognized (including the empty "unknown" lead) is blank.
public func roleModeLeadDisplay(_ lead: String) -> String {
    switch lead {
    case "cc": return "CC"
    case "cdx": return "Cdx"
    default: return ""
    }
}

// Keep the always-visible badge compact: mode + selected conversation main.
// The menu exposes the detailed mode/main choices when clicked.
public func roleModeBadgeLabel(mode: RoleMode, main: String) -> String {
    let side = roleModeLeadDisplay(main)
    let modeLabel = mode.displayName
    return side.isEmpty ? "\(modeLabel)\u{00B7}Main ?" : "\(modeLabel)\u{00B7}Main \(side)"
}
