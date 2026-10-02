import XCTest
@testable import TprojLogic

final class WorkspaceLocationGuardTests: XCTestCase {
    func testProjectIDCannotCrossHostAtSamePath() {
        let error = WorkspaceLocationGuard.projectIDError(
            "old", intendedHostID: "host-b", intendedPath: "/work",
            existingByID: .init(projectID: "old", hostID: "host-a", path: "/work")
        )
        XCTAssertEqual(error, "Project ID belongs to a different host/path; refresh before saving")
    }

    func testProjectIDAtExactLocationRemainsValid() {
        XCTAssertNil(WorkspaceLocationGuard.projectIDError(
            "local", intendedHostID: "local-host", intendedPath: "/work",
            existingByID: .init(projectID: "local", hostID: "local-host", path: "/work")
        ))
    }

    func testUnknownProjectIDCanReuseUnambiguousLocation() {
        XCTAssertNil(WorkspaceLocationGuard.projectIDError(
            "stale", intendedHostID: "host-b", intendedPath: "/work", existingByID: nil,
            existingByLocation: .init(projectID: "current", hostID: "host-b", path: "/work")
        ))
    }

    func testStaleLocalModelDoesNotMatchRemoteDiskLocation() {
        let local = [["id", "/work", "local", "", "/work", ""]]
        let remote = [["id", "/work", "remote", "host", "", "/work"]]
        XCTAssertFalse(WorkspaceLocationGuard.matches(local, remote))
    }

    func testUnchangedLocationMatchesRegardlessOfOrdering() {
        let before = [["a", "/a", "local", "", "/a", ""], ["b", "/b", "remote", "h", "", "/b"]]
        let after = [["b", "/b", "remote", "h", "", "/b"], ["a", "/a", "local", "", "/a", ""]]
        XCTAssertTrue(WorkspaceLocationGuard.matches(before, after))
    }

    func testLegacyLocationFieldsDefaultFromActivePath() {
        XCTAssertEqual(
            WorkspaceLocationGuard.record(projectID: "id", path: "/local", type: "", host: "", localPath: "", remotePath: ""),
            ["id", "/local", "local", "", "/local", ""]
        )
        XCTAssertEqual(
            WorkspaceLocationGuard.record(projectID: "id", path: "/remote", type: "remote", host: "h", localPath: "", remotePath: ""),
            ["id", "/remote", "remote", "h", "", "/remote"]
        )
        XCTAssertNil(WorkspaceLocationGuard.record(projectID: "id", path: "", type: "local", host: "", localPath: "", remotePath: ""))
    }
}
