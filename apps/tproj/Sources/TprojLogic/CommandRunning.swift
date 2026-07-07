import Foundation

// Result of running an external command. Moved here from TprojApp (S-D2a) so
// the CommandRunning protocol below and TmuxService can be unit-tested with a
// fake runner instead of being welded to the executable.
public struct CommandResult {
    public var exitCode: Int32
    public var stdout: String
    public var stderr: String

    public init(exitCode: Int32, stdout: String, stderr: String) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

// Abstraction over external command execution (S-D2a). The real GUI runner
// (ProcessCommandRunner in TprojApp) executes via Process; tests supply a fake
// runner that records the argv it is handed and returns a canned CommandResult.
public protocol CommandRunning {
    func run(_ launchPath: String, _ args: [String], env: [String: String]) -> CommandResult
    func runAsync(_ launchPath: String, _ args: [String], env: [String: String]) async -> CommandResult
}
