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
}
