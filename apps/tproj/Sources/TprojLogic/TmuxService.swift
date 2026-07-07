import Foundation

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
}
