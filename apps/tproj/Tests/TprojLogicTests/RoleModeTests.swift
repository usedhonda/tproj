import XCTest
@testable import TprojLogic

final class RoleModeTests: XCTestCase {
    // Absent file (nil data) resolves to auto.
    func testParseAbsentIsAuto() {
        XCTAssertEqual(RoleMode.parse(nil), .auto)
    }

    // Corrupt / non-JSON contents resolve to auto.
    func testParseCorruptIsAuto() {
        let data = Data("not json {".utf8)
        XCTAssertEqual(RoleMode.parse(data), .auto)
    }

    // An unrecognized mode value resolves to auto (contract calls this out).
    func testParseUnknownModeIsAuto() {
        let data = Data(#"{"mode":"bogus","set_at":1,"set_by":"user","source":"x"}"#.utf8)
        XCTAssertEqual(RoleMode.parse(data), .auto)
    }

    // Valid advisor / solo parse to their modes.
    func testParseValidModes() {
        let advisor = Data(#"{"mode":"advisor","set_at":1,"set_by":"user","source":"x"}"#.utf8)
        XCTAssertEqual(RoleMode.parse(advisor), .advisor)
        let solo = Data(#"{"mode":"solo","set_at":1,"set_by":"gui","source":"tproj-gui"}"#.utf8)
        XCTAssertEqual(RoleMode.parse(solo), .solo)
    }

    // Cycle order is auto -> advisor -> solo -> auto.
    func testCycleOrder() {
        XCTAssertEqual(RoleMode.auto.next, .advisor)
        XCTAssertEqual(RoleMode.advisor.next, .solo)
        XCTAssertEqual(RoleMode.solo.next, .auto)
    }

    // auto serializes to nil (declaring auto deletes the file).
    func testAutoHasNoFileContents() {
        XCTAssertNil(RoleMode.auto.fileContents(setBy: "gui", source: "tproj-gui", setAt: 1))
    }

    // A declared mode serializes to the four-key shape; round-trip to verify
    // keys/values rather than asserting on string order.
    func testFileContentsShape() throws {
        let data = try XCTUnwrap(
            RoleMode.advisor.fileContents(setBy: "gui", source: "tproj-gui", setAt: 1786400000)
        )
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let dict = try XCTUnwrap(object)
        XCTAssertEqual(Set(dict.keys), ["mode", "set_at", "set_by", "source"])
        XCTAssertEqual(dict["mode"] as? String, "advisor")
        XCTAssertEqual(dict["set_at"] as? Int, 1786400000)
        XCTAssertEqual(dict["set_by"] as? String, "gui")
        XCTAssertEqual(dict["source"] as? String, "tproj-gui")
        // Serialized form round-trips back through parse.
        XCTAssertEqual(RoleMode.parse(data), .advisor)
    }
}
