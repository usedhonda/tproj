import Foundation

/// Display polling only; never role or execution authority.
public struct RoleQuerySchedule {
    private var running: Set<String> = []
    private var next: [String: Date] = [:]

    public init() {}

    public mutating func begin(_ key: String, now: Date = Date()) -> Bool {
        guard !running.contains(key), now >= (next[key] ?? .distantPast) else { return false }
        running.insert(key)
        return true
    }

    public mutating func finish(_ key: String, succeeded: Bool, interval: TimeInterval, now: Date = Date()) {
        running.remove(key)
        next[key] = now.addingTimeInterval(succeeded ? interval : 30)
    }
}
