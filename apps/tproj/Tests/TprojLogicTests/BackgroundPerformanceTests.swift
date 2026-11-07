import Foundation
import XCTest
@testable import TprojLogic

final class BackgroundPerformanceTests: XCTestCase {
    func testResourceReuseAndSamePathAtomicReplacement() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let image = directory.appendingPathComponent("portrait")
        try Data("first".utf8).write(to: image)
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        try FileManager.default.setAttributes([.modificationDate: date], ofItemAtPath: image.path)
        var loads = 0
        let cache = FileResourceCache<Data> { path in
            loads += 1
            return try? Data(contentsOf: URL(fileURLWithPath: path))
        }

        XCTAssertTrue(cache.refresh(paths: [image.path, image.path]))
        XCTAssertEqual(loads, 1, "panes sharing art need only one load")
        // Layout, role changes and a hide/show cycle keep asking for the same art.
        for _ in 0..<100 {
            XCTAssertEqual(cache.value(atPath: image.path), Data("first".utf8))
        }
        XCTAssertFalse(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 1, "unchanged content must survive view reevaluation")

        // Same name, length and timestamp: the new inode must still invalidate it.
        try Data("other".utf8).write(to: image, options: .atomic)
        try FileManager.default.setAttributes([.modificationDate: date], ofItemAtPath: image.path)
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 2)
        XCTAssertEqual(cache.value(atPath: image.path), Data("other".utf8))
        XCTAssertFalse(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 2)
    }

    func testMissingCorruptAndUnusedResourcesRecoverAndRelease() throws {
        final class Resource {}
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let image = directory.appendingPathComponent("portrait")
        var loads = 0
        let cache = FileResourceCache<Resource> { path in
            loads += 1
            guard (try? String(contentsOfFile: path, encoding: .utf8)) == "valid" else { return nil }
            return Resource()
        }

        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertFalse(cache.containsFile(atPath: image.path))
        XCTAssertFalse(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 0)
        try Data("corrupt".utf8).write(to: image)
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertTrue(cache.containsFile(atPath: image.path))
        XCTAssertNil(cache.value(atPath: image.path))
        XCTAssertFalse(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 1, "do not repeatedly decode an unchanged corrupt file")

        try Data("valid".utf8).write(to: image, options: .atomic)
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        weak var resource = cache.value(atPath: image.path)
        XCTAssertNotNil(resource)
        XCTAssertTrue(cache.refresh(paths: []))
        XCTAssertNil(resource, "removed manifest paths must release their resources")
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 3, "reintroduced paths are loaded again after eviction")

        try FileManager.default.removeItem(at: image)
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertNil(cache.value(atPath: image.path))
        try Data("valid".utf8).write(to: image)
        XCTAssertTrue(cache.refresh(paths: [image.path]))
        XCTAssertEqual(loads, 4)
        resource = cache.value(atPath: image.path)
        cache.removeAll()
        XCTAssertNil(resource, "detach releases retained resources")
    }

    func testFollowCadenceSettlesAndRecoversAcrossLifecycle() {
        var cadence = WindowFollowPollingCadence()
        let frame = CGRect(x: 100, y: 100, width: 800, height: 600)
        let moved = frame.offsetBy(dx: 20, dy: 0)
        let resized = CGRect(x: 0, y: 0, width: 300, height: 600)
        func observe(_ time: TimeInterval, target: CGRect?, follower: CGRect = .zero,
                     snapped: Bool = true, dragging: Bool = false, suspended: Bool = false) -> Int {
            cadence.intervalMilliseconds(targetFrame: target, followerFrame: follower,
                                         isSnapped: snapped, isDragging: dragging,
                                         isSuspended: suspended, now: time)
        }

        XCTAssertEqual(observe(0, target: nil, snapped: false), 500, "initial absence backs off")
        XCTAssertEqual(observe(1, target: frame, snapped: false), 100, "unsnapped appearance restores discovery")
        XCTAssertEqual(observe(2, target: frame), 100, "snapping alone does not need 60 Hz")
        XCTAssertEqual(observe(3, target: frame, dragging: true), 16, "drag starts fast follow before motion")
        XCTAssertEqual(observe(3.2, target: frame), 16, "retain a short burst between motion samples")
        XCTAssertEqual(observe(3.3, target: frame), 100, "settle when stationary")
        XCTAssertEqual(observe(4, target: moved), 16, "target movement resumes fast follow")
        XCTAssertEqual(observe(5, target: moved, follower: resized), 16, "follower resize resumes fast follow")
        XCTAssertEqual(observe(6, target: moved, follower: resized, dragging: true, suspended: true), 100)
        XCTAssertEqual(observe(7, target: moved, follower: resized), 100, "suspension clears the burst")
        XCTAssertEqual(observe(8, target: frame, snapped: false, dragging: true), 100, "detached discovery stays bounded")
        XCTAssertEqual(observe(9, target: nil), 500, "absence or a hidden follower backs off")
        XCTAssertEqual(observe(10, target: frame, snapped: false), 100, "reappearance never gets stuck at 500 ms")
    }

    func testSparseFollowPreservesSnapAndIntentionalOffsets() {
        let target = CGRect(x: 100, y: 100, width: 800, height: 600)
        let follower = CGRect(x: 902, y: 100, width: 275, height: 600)
        func decision(target next: CGRect, follower current: CGRect = CGRect(x: 902, y: 100, width: 275, height: 600),
                      previousFollower: CGRect? = nil, leftSide: Bool = false) -> SnappedWindowFollowDecision {
            SnappedWindowFollowDecision(targetFrame: next, previousTargetFrame: target,
                                        followerFrame: current, previousFollowerFrame: previousFollower ?? follower,
                                        anchoredOrigin: CGPoint(x: leftSide ? next.minX - current.width - 2 : next.maxX + 2,
                                                                y: next.maxY - current.height),
                                        detachDistance: 24, topAlignmentDistance: 100)
        }

        let wider = CGRect(x: 100, y: 100, width: 830, height: 600)
        XCTAssertFalse(decision(target: wider).shouldDetach, "right-edge resize is target motion, not a 30pt detach")
        let raised = target.offsetBy(dx: 0, dy: 120)
        XCTAssertTrue(decision(target: raised).shouldAlignTop, "retain prior top alignment across the first idle sample")
        let offset = follower.offsetBy(dx: 0, dy: -150)
        XCTAssertFalse(decision(target: raised, follower: offset, previousFollower: offset).shouldAlignTop,
                       "an intentionally offset sidebar keeps its Y position")
        XCTAssertFalse(decision(target: raised, follower: offset).shouldAlignTop,
                       "a simultaneous independent sidebar Y drag overrides old alignment")
        XCTAssertTrue(decision(target: target, follower: follower.offsetBy(dx: 30, dy: 0)).shouldDetach,
                      "intentional X detach from a stationary target still works")
        XCTAssertFalse(decision(target: target, follower: offset).shouldDetach, "Y movement never detaches")

        let widenedRight = CGRect(x: 872, y: 100, width: 305, height: 600)
        XCTAssertFalse(decision(target: target, follower: widenedRight).shouldDetach,
                       "resizing a right sidebar's left edge keeps its snap")
        let left = CGRect(x: -177, y: 100, width: 275, height: 600)
        let widenedLeft = CGRect(x: -177, y: 100, width: 305, height: 600)
        XCTAssertFalse(decision(target: target, follower: widenedLeft, previousFollower: left, leftSide: true).shouldDetach,
                       "resizing a left sidebar's right edge keeps its snap")
        let taller = CGRect(x: 902, y: 100, width: 275, height: 720)
        XCTAssertTrue(decision(target: target, follower: taller).shouldAlignTop,
                      "a large native resize keeps prior top alignment")
    }
}
