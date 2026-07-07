import Foundation

// One dev-window pane as reported by `tmux list-panes`. Moved here from
// AppViewModel (S-D2c) so TmuxService.listPanes can return it and the parse can
// be unit-tested.
public struct PaneInfo: Equatable {
    public var paneID: String
    public var role: String
    public var column: Int?

    public init(paneID: String, role: String, column: Int?) {
        self.paneID = paneID
        self.role = role
        self.column = column
    }
}

// Thin tmux verb wrapper over a CommandRunning (S-D2b). It hides the
// `/usr/bin/env tmux <verb> ...` argv assembly so call sites read as verbs, and
// so the assembly + output parsing can be unit-tested with a fake runner
// instead of a live tmux. Session/dev-window are injected: the values come from
// TprojApp's TmuxTargets, which this library cannot import.
public struct TmuxService {
    public let runner: CommandRunning
    public let session: String
    public let devWindow: String

    public init(runner: CommandRunning, session: String, devWindow: String) {
        self.runner = runner
        self.session = session
        self.devWindow = devWindow
    }

    // list-panes on the dev window formatted as `pane_id|@role|@column`, parsed
    // into PaneInfo. argv and parse are verbatim from the former inline
    // listWorkspacePanesAsync (S-D2c); the window is the injected devWindow.
    public func listPanes() async -> [PaneInfo] {
        let result = await runner.runAsync("/usr/bin/env", ["tmux", "list-panes", "-t", devWindow, "-F", "#{pane_id}|#{@role}|#{@column}"], env: [:])
        guard result.exitCode == 0 else { return [] }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                guard parts.count >= 3 else { return nil }
                let col = Int(parts[2])
                return PaneInfo(paneID: parts[0], role: parts[1], column: col)
            }
    }

    // set-option -pt <target> <key> <value>. argv verbatim from the former
    // inline `tmux set-option -pt ...` calls (S-D2d). Returns the runner result
    // so call sites keep their existing `_ = await ...` discard.
    public func setOption(_ key: String, _ value: String, pane target: String) async -> CommandResult {
        await runner.runAsync("/usr/bin/env", ["tmux", "set-option", "-pt", target, key, value], env: [:])
    }
}
