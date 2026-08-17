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

    // Badge stays compact while naming both the mode and conversation main.
    func testBadgeLabelComposition() {
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "cc"), "Team\u{00B7}Main CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "cdx"), "Team\u{00B7}Main Cdx")
        XCTAssertEqual(roleModeBadgeLabel(mode: .advisor, main: "cc"), "Advisor\u{00B7}Main CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .advisor, main: "cdx"), "Advisor\u{00B7}Main Cdx")
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: "cc"), "Solo\u{00B7}Main CC")
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: "cdx"), "Solo\u{00B7}Main Cdx")
        XCTAssertEqual(roleModeBadgeLabel(mode: .solo, main: ""), "Solo\u{00B7}Main ?")
        XCTAssertEqual(roleModeBadgeLabel(mode: .auto, main: "other"), "Team\u{00B7}Main ?")
    }

    func testConversationMainIsIndependentAndBuildsCanonicalCommand() {
        XCTAssertEqual(roleModeConversationMain(mode: .advisor, main: "cc", lead: "cdx"), "cc")
        XCTAssertEqual(roleModeConversationMain(mode: .advisor, main: "", lead: "cdx"), "cdx")
        XCTAssertEqual(roleModeConversationMain(mode: .auto, main: "", lead: "cc"), "cc")
        XCTAssertEqual(roleModeConversationMain(mode: .auto, main: "", lead: ""), "cdx")
        XCTAssertEqual(
            roleModeSetArguments(mode: .advisor, main: "cc", projectPath: "/project"),
            ["mode", "advisor", "--main", "cc", "--json", "--project", "/project", "--set-by", "gui", "--source", "tproj-gui"]
        )
    }

    func testWeeklyPaceAlertUsesFreshPreferredSnapshotsOnly() throws {
        func history(usedPercent: Int) -> Data {
            Data("""
            {"preferredAccountKey":"active","accounts":{"active":[
              {"name":"session","windowMinutes":300,"entries":[
                {"capturedAt":"legacy-bad","usedPercent":"unknown"}
              ]},
              {"name":"weekly","windowMinutes":10080,"entries":[
                {"capturedAt":"2026-08-13T23:00:00Z","usedPercent":"unknown"},
                {"capturedAt":"2026-08-14T00:00:00Z","resetsAt":"2026-08-17T00:00:00Z","usedPercent":\(usedPercent)}
              ]}
            ]}}
            """.utf8)
        }

        let codex = try XCTUnwrap(CodexBarPace.latestWeeklySnapshot(from: history(usedPercent: 80), provider: "codex"))
        let claude = try XCTUnwrap(CodexBarPace.latestWeeklySnapshot(from: history(usedPercent: 50), provider: "claude"))
        let scopedCLI = Data("""
        [{"provider":"claude","usage":{"updatedAt":"2026-08-14T00:00:00Z","identity":{"email":"private@example.com"},"extraRateWindows":[
          {"id":"claude-weekly-scoped-fable","title":"Fable only","window":{"usedPercent":40,"windowMinutes":10080,"resetsAt":"2026-08-17T00:00:00Z"}}
        ]}}]
        """.utf8)
        let fable = try XCTUnwrap(CodexBarPace.latestScopedWeeklySnapshot(
            fromCodexBarCLI: scopedCLI,
            id: "claude-weekly-scoped-fable",
            provider: "fable"
        ))
        let snapshots = ["codex": codex, "claude": claude, "fable": fable]
        let freshNow = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-08-14T00:10:00Z"))
        let staleNow = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-08-14T01:00:00Z"))
        let resetsAt = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-08-17T00:00:00Z"))

        XCTAssertEqual(
            CodexBarPace.advisory(main: "cdx", snapshots: snapshots, now: freshNow),
            WeeklyPaceAdvisory(
                main: "cdx",
                other: "cc",
                mainRemainingPercent: 20,
                otherRemainingPercent: 50,
                mainProjectedPercent: 140,
                otherProjectedPercent: 88,
                mainResetsAt: resetsAt,
                otherResetsAt: resetsAt,
                severity: .critical,
                reason: .exhaustion
            )
        )
        XCTAssertNil(CodexBarPace.advisory(main: "cc", snapshots: snapshots, now: freshNow))
        XCTAssertNil(CodexBarPace.advisory(main: "cdx", snapshots: snapshots, now: staleNow))
        XCTAssertNil(CodexBarPace.latestWeeklySnapshot(from: Data("{}".utf8), provider: "codex"))

        let state = CodexBarPace.noticeState(snapshots: snapshots, now: freshNow)
        XCTAssertEqual(state.sides["cdx"]?.status, .alert)
        XCTAssertEqual(state.sides["cdx"]?.reason, .exhaustion)
        XCTAssertEqual(state.sides["cdx"]?.mainRemainingPercent, 20)
        XCTAssertEqual(state.sides["cdx"]?.otherRemainingPercent, 50)
        let encoded = try XCTUnwrap(CodexBarPace.encodedNoticeState(snapshots: snapshots, now: freshNow))
        let encodedText = String(decoding: encoded, as: UTF8.self)
        XCTAssertTrue(encodedText.contains("main_remaining_percent"))
        XCTAssertFalse(encodedText.contains("preferredAccountKey"))
        XCTAssertFalse(encodedText.contains("active"))

        let lowUse = try XCTUnwrap(CodexBarPace.latestWeeklySnapshot(from: history(usedPercent: 9), provider: "codex"))
        let lowUseState = CodexBarPace.noticeState(
            snapshots: ["codex": lowUse, "claude": claude],
            now: freshNow
        )
        XCTAssertEqual(lowUseState.sides["cdx"]?.status, .unavailable)

        let balance = try XCTUnwrap(CodexBarPace.balance(snapshots: snapshots, now: freshNow))
        XCTAssertEqual(balance.cdx.remainingPercent, 20)
        XCTAssertEqual(balance.cc.projectedRemainingPercent, 12)
        XCTAssertEqual(balance.cdx.pacePercent, 140)
        XCTAssertEqual(balance.fable?.remainingPercent, 60)
        XCTAssertEqual(balance.recommendedMain, "cc")
    }
}
