import XCTest
@testable import TprojLogic

// Records every argv it is handed and returns a canned CommandResult, so
// TmuxService's argv assembly and output parsing can be verified without a live
// tmux (S-D2).
private final class RecordingRunner: CommandRunning {
    struct Call: Equatable {
        let launchPath: String
        let args: [String]
        let env: [String: String]
    }
    private(set) var calls: [Call] = []
    var response: CommandResult

    init(response: CommandResult) {
        self.response = response
    }

    func run(_ launchPath: String, _ args: [String], env: [String: String]) -> CommandResult {
        calls.append(Call(launchPath: launchPath, args: args, env: env))
        return response
    }

    func runAsync(_ launchPath: String, _ args: [String], env: [String: String]) async -> CommandResult {
        run(launchPath, args, env: env)
    }
}

final class TmuxServiceTests: XCTestCase {
    private func makeService(_ runner: CommandRunning) -> TmuxService {
        TmuxService(runner: runner, session: "test-workspace", devWindow: "test-workspace:dev")
    }

    func testListPanesSendsExpectedArgv() async {
        let runner = RecordingRunner(response: CommandResult(exitCode: 0, stdout: "", stderr: ""))
        let service = makeService(runner)
        _ = await service.listPanes()
        XCTAssertEqual(runner.calls.count, 1)
        XCTAssertEqual(runner.calls.first?.launchPath, "/usr/bin/env")
        XCTAssertEqual(runner.calls.first?.args,
                       ["tmux", "list-panes", "-t", "test-workspace:dev", "-F", "#{pane_id}|#{@role}|#{@column}"])
    }

    func testListPanesParsesOutput() async {
        let stdout = "%1|codex|0\n%2|claude|1\n%3|other|\n"
        let runner = RecordingRunner(response: CommandResult(exitCode: 0, stdout: stdout, stderr: ""))
        let service = makeService(runner)
        let panes = await service.listPanes()
        XCTAssertEqual(panes, [
            PaneInfo(paneID: "%1", role: "codex", column: 0),
            PaneInfo(paneID: "%2", role: "claude", column: 1),
            PaneInfo(paneID: "%3", role: "other", column: nil),
        ])
    }

    func testListPanesReturnsEmptyOnNonZeroExit() async {
        let runner = RecordingRunner(response: CommandResult(exitCode: 1, stdout: "%1|codex|0\n", stderr: "boom"))
        let service = makeService(runner)
        let panes = await service.listPanes()
        XCTAssertTrue(panes.isEmpty)
    }

    func testSetOptionSendsExpectedArgv() async {
        let runner = RecordingRunner(response: CommandResult(exitCode: 0, stdout: "", stderr: ""))
        let service = makeService(runner)
        _ = await service.setOption("@project", "/path/to/proj", pane: "%5")
        XCTAssertEqual(runner.calls.count, 1)
        XCTAssertEqual(runner.calls.first?.launchPath, "/usr/bin/env")
        XCTAssertEqual(runner.calls.first?.args,
                       ["tmux", "set-option", "-pt", "%5", "@project", "/path/to/proj"])
    }

    func testGetOptionSendsExpectedArgvAndTrimsValue() async {
        let runner = RecordingRunner(response: CommandResult(exitCode: 0, stdout: "cc-general\n", stderr: ""))
        let service = makeService(runner)
        let value = await service.getOption("@alias", pane: "%5")
        XCTAssertEqual(value, "cc-general")
        XCTAssertEqual(runner.calls.count, 1)
        XCTAssertEqual(runner.calls.first?.launchPath, "/usr/bin/env")
        XCTAssertEqual(runner.calls.first?.args,
                       ["tmux", "show-options", "-pv", "-t", "%5", "@alias"])
    }

    func testGetOptionReturnsNilForMissingValue() async {
        let runner = RecordingRunner(response: CommandResult(exitCode: 1, stdout: "", stderr: "missing"))
        let service = makeService(runner)
        let value = await service.getOption("@alias", pane: "%5")
        XCTAssertNil(value)
    }
}
