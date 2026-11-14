import XCTest
@testable import TprojLogic

final class RoleQueryScheduleTests: XCTestCase {
    func testOverlappingRefreshesAndFailedPollBackoff() {
        var schedule = RoleQuerySchedule()
        let now = Date()
        XCTAssertTrue(schedule.begin("project", now: now))
        XCTAssertFalse(schedule.begin("project", now: now.addingTimeInterval(10)))
        schedule.finish("project", succeeded: false, interval: 3, now: now)
        XCTAssertFalse(schedule.begin("project", now: now.addingTimeInterval(29)))
        XCTAssertTrue(schedule.begin("project", now: now.addingTimeInterval(30)))
        schedule.finish("project", succeeded: true, interval: 15, now: now.addingTimeInterval(30))
        XCTAssertFalse(schedule.begin("project", now: now.addingTimeInterval(44)))
        XCTAssertTrue(schedule.begin("project", now: now.addingTimeInterval(45)))
    }
}
