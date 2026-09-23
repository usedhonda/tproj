import XCTest
@testable import TprojLogic

final class KeepWarmTests: XCTestCase {
    func testLocalObservationRequiresExactFreshPaneBindingAndCannotPoke() throws {
        let data = Data("""
        {"version":1,"session_id":"claude-session","pane_id":"%12","tty":"/dev/ttys001",\
        "pane_pid":123,"role":"claude-p1","alias":"project","owner_session":"tproj-workspace",\
        "observed_at":1800000000,"cache_expires_at":1800000060,\
        "last_user_prompt_at":1799999900,"recache_tokens_if_cold":42}
        """.utf8)
        let observation = try ClaudeCacheObservation.decode(data)
        let now = Date(timeIntervalSince1970: 1_800_000_001)
        func matches(alias: String = "project", tty: String = "/dev/ttys001",
                     now: Date = Date(timeIntervalSince1970: 1_800_000_001)) -> Bool {
            observation.matches(paneID: "%12", tty: tty, panePID: 123,
                                role: "claude-p1", alias: alias,
                                ownerSession: "tproj-workspace", now: now)
        }
        XCTAssertTrue(matches())
        XCTAssertFalse(matches(alias: "other"))
        XCTAssertFalse(matches(tty: "/dev/ttys002"))
        XCTAssertFalse(matches(now: now.addingTimeInterval(301)))
        XCTAssertFalse(observation.displaySession.pokeable)
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: observation.displaySession, now: now, hours: 1))
    }

    func testPokeEligibilityBoundaries() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        func session(
            tty: String? = "/dev/ttys001",
            remaining: TimeInterval? = 90,
            idle: TimeInterval? = 3_599,
            pokeable: Bool = true
        ) -> KeepWarmSession {
            KeepWarmSession(
                tty: tty,
                cacheExpiresAt: remaining.map { now.addingTimeInterval($0) },
                lastUserPromptAt: idle.map { now.addingTimeInterval(-$0) },
                pokeable: pokeable
            )
        }

        XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: 1))
        XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(idle: 0), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: 90.001), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: 0), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: 3_600), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: -1), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(pokeable: false), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(tty: "  "), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: nil), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: nil), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: nil))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: 2))
        for hours in [1, 3, 6, 12] {
            XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(idle: Double(hours * 3600 - 1)), now: now, hours: hours))
        }
    }

    func testCodexPaneStateBlocksPokeUnlessIdleQuietAndNotTyping() throws {
        let data = Data("""
        {"%21":{"turn":"idle","quiet_seconds":45,"prompt_state":"idle",
          "last_token_sample":{"at":"2026-09-24T02:00:00Z","input_tokens":12000,"cached_input_tokens":9000}},
         "%22":{"turn":"working","quiet_seconds":1,"prompt_state":"idle","last_token_sample":null},
         "%23":{"turn":"idle","quiet_seconds":5,"prompt_state":"idle","last_token_sample":null},
         "%24":{"turn":"idle","quiet_seconds":45,"prompt_state":"typing","last_token_sample":null}}
        """.utf8)
        let states = try CodexPaneCacheState.decodeMap(data)
        XCTAssertNil(states["%21"]?.pokeBlockReason)
        XCTAssertEqual(states["%21"]?.lastTokenSample?.cachedInputTokens, 9_000)
        XCTAssertEqual(states["%22"]?.pokeBlockReason, "turn working")
        XCTAssertEqual(states["%23"]?.pokeBlockReason, "log still active")
        XCTAssertNil(states["%24"]?.pokeBlockReason, "typing is checked by the helper at send time")
    }
}
