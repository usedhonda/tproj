import Foundation
import Darwin

/// Process runner with bounded output and deadlines. It never uses a global
/// dispatch pool, and only terminates the process it created.
public struct BoundedCommandRunner: Sendable {
    public var timeout: TimeInterval
    public var eofGrace: TimeInterval
    public var maxOutput: Int

    public init(timeout: TimeInterval = 30, eofGrace: TimeInterval = 0.5, maxOutput: Int = 65536) {
        self.timeout = timeout; self.eofGrace = eofGrace; self.maxOutput = maxOutput
    }

    public func run(_ launchPath: String, _ args: [String], env extra: [String: String] = [:]) -> CommandResult {
        let p = Process(); p.executableURL = URL(fileURLWithPath: launchPath); p.arguments = args
        var env = ProcessInfo.processInfo.environment; extra.forEach { env[$0.key] = $0.value }; p.environment = env
        let out = Pipe(), err = Pipe(); p.standardOutput = out; p.standardError = err
        do { try p.run() } catch { return CommandResult(exitCode: 1, stdout: "", stderr: error.localizedDescription) }
        let fds = [out.fileHandleForReading.fileDescriptor, err.fileHandleForReading.fileDescriptor]
        fds.forEach { _ = fcntl($0, F_SETFL, O_NONBLOCK) }
        var buffers = [Data(), Data()]; let started = Date(); var exitDate: Date?; var eof = [false, false]; var terminated = false
        while p.isRunning || !eof.allSatisfy({ $0 }) {
            if p.isRunning && Date().timeIntervalSince(started) > timeout { p.terminate(); terminated = true }
            if !p.isRunning && exitDate == nil { exitDate = Date() }
            var polls = fds.map { pollfd(fd: $0, events: Int16(POLLIN), revents: 0) }
            _ = Darwin.poll(&polls, nfds_t(polls.count), 20)
            for i in 0..<2 where !eof[i] {
                var chunk = [UInt8](repeating: 0, count: 4096); let n = read(fds[i], &chunk, chunk.count)
                if n > 0 { let room = max(0, maxOutput - buffers[i].count); buffers[i].append(contentsOf: chunk.prefix(min(n, room))) }
                else if n == 0 { eof[i] = true }
            }
            if let exitDate, Date().timeIntervalSince(exitDate) > eofGrace { break }
            if terminated && Date().timeIntervalSince(started) > timeout + eofGrace { break }
        }
        if p.isRunning { kill(p.processIdentifier, SIGKILL); _ = waitpid(p.processIdentifier, nil, 0) }
        return CommandResult(exitCode: p.terminationStatus, stdout: String(data: buffers[0], encoding: .utf8) ?? "", stderr: String(data: buffers[1], encoding: .utf8) ?? "")
    }
}
