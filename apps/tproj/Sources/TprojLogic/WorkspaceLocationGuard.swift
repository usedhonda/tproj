import Foundation

/// Compares location records while ignoring ordering and non-location fields.
public enum WorkspaceLocationGuard {
    public static func record(projectID: String, path: String, type: String, host: String,
                              localPath: String, remotePath: String) -> [String]? {
        guard !path.isEmpty else { return nil }
        let normalizedType = type.isEmpty ? "local" : type
        let normalizedLocal = localPath.isEmpty && normalizedType != "remote" ? path : localPath
        let normalizedRemote = remotePath.isEmpty && normalizedType == "remote" ? path : remotePath
        return [projectID, path, normalizedType, host, normalizedLocal, normalizedRemote]
    }

    public static func canonical(_ records: [[String]]) -> [[String]] {
        records.sorted { $0.lexicographicallyPrecedes($1) }
    }

    public static func matches(_ lhs: [[String]], _ rhs: [[String]]) -> Bool {
        canonical(lhs) == canonical(rhs)
    }
}
