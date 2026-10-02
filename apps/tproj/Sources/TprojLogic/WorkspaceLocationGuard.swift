import Foundation

/// Compares location records while ignoring ordering and non-location fields.
public enum WorkspaceLocationGuard {
    public static func canonical(_ records: [[String]]) -> [[String]] {
        records.sorted { $0.lexicographicallyPrecedes($1) }
    }

    public static func matches(_ lhs: [[String]], _ rhs: [[String]]) -> Bool {
        canonical(lhs) == canonical(rhs)
    }
}
