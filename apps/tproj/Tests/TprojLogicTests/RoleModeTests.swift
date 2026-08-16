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

    // Router --json output parses into mode + lead; failures fall back to auto.
    func testParseStatus() {
        let ok = Data(#"{"mode":"advisor","lead":"cc","main":"cdx","project":"/x"}"#.utf8)
        XCTAssertEqual(RoleMode.parseStatus(ok), RoleModeStatus(mode: .advisor, lead: "cc", main: "cdx"))
        XCTAssertEqual(RoleMode.parseStatus(nil), RoleModeStatus(mode: .auto, lead: ""))
        XCTAssertEqual(RoleMode.parseStatus(Data("{".utf8)), RoleModeStatus(mode: .auto, lead: ""))
        let unknown = Data(#"{"mode":"bogus","lead":"cc"}"#.utf8)
        XCTAssertEqual(RoleMode.parseStatus(unknown), RoleModeStatus(mode: .auto, lead: "cc"))
    }

    // Badge label for the six mode/lead combinations plus the empty-lead form.
    func testBadgeLabelComposition() {
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "cc"), "auto\u{00B7}CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "cdx"), "auto\u{00B7}Cdx")
        XCTAssertEqual(roleModeBadgeLabel(mode: .advisor, main: "cc"), "advisor\u{00B7}CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .advisor, main: "cdx"), "advisor\u{00B7}Cdx")
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: "cc"), "solo\u{00B7}CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: "cdx"), "solo\u{00B7}Cdx")
        // Empty / unknown lead collapses to just the mode name.
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: ""), "solo")
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "other"), "auto")
    }

    func testConversationMainIsIndependentAndBuildsCanonicalCommand() {
        XCTAssertEqual(roleModeConversationMain(main: "cc", lead: "cdx"), "cc")
        XCTAssertEqual(roleModeConversationMain(main: "", lead: "cdx"), "cdx")
        XCTAssertEqual(
            roleModeSetArguments(mode: .advisor, main: "cc", projectPath: "/project"),
            ["mode", "advisor", "--main", "cc", "--json", "--project", "/project", "--set-by", "gui", "--source", "tproj-gui"]
        )
    }
}
