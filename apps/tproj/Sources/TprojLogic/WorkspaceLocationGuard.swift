import Foundation

/// Compares location records while ignoring ordering and non-location fields.
public enum WorkspaceLocationGuard {
    public struct ProjectIdentity: Equatable {
        public let projectID: String
        public let hostID: String
        public let path: String

        public init(projectID: String, hostID: String, path: String) {
            self.projectID = projectID
            self.hostID = hostID
            self.path = path
        }
    }

    /// Returns an error when a supplied ID is registered to a different
    /// host/path. An empty ID, or an unknown ID with an exact location match,
    /// is intentionally accepted for location lookup.
    public static func projectIDError(_ projectID: String, intendedHostID: String,
                                      intendedPath: String, existingByID: ProjectIdentity?,
                                      existingByLocation: ProjectIdentity? = nil) -> String? {
        guard !projectID.isEmpty else { return nil }
        guard let existingByID else {
            return existingByLocation == nil
                ? "Project ID is no longer registered; refresh before saving"
                : nil
        }
        guard existingByID.hostID == intendedHostID && existingByID.path == intendedPath else {
            return "Project ID belongs to a different host/path; refresh before saving"
        }
        return nil
    }

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
