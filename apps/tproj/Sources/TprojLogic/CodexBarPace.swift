import Foundation

public struct WeeklyPaceSnapshot: Equatable, Sendable {
    public let provider: String
    public let capturedAt: Date
    public let resetsAt: Date
    public let usedPercent: Double
    public let windowMinutes: Int

    public var projectedUsedPercentAtReset: Double? {
        let windowSeconds = Double(windowMinutes) * 60
        guard windowSeconds > 0 else { return nil }
        let startedAt = resetsAt.addingTimeInterval(-windowSeconds)
        let elapsed = capturedAt.timeIntervalSince(startedAt)
        guard elapsed >= 60 * 60, elapsed <= windowSeconds else { return nil }
        if usedPercent == 0 { return 0 }
        return usedPercent / (elapsed / windowSeconds)
    }
}

public enum WeeklyPaceSeverity: String, Equatable, Sendable {
    case advisory
    case critical
}

public struct WeeklyPaceAdvisory: Equatable, Sendable {
    public let main: String
    public let other: String
    public let mainProjectedPercent: Int
    public let otherProjectedPercent: Int
    public let mainResetsAt: Date
    public let otherResetsAt: Date
    public let severity: WeeklyPaceSeverity

    public var signature: String {
        "\(main):\(severity.rawValue)"
    }

    public var message: String {
        "週ペース: 主\(displayName(main)) \(resetDescription(mainResetsAt)) -> \(mainProjectedPercent)% / \(displayName(other)) \(resetDescription(otherResetsAt)) -> \(otherProjectedPercent)%"
    }

    private func displayName(_ side: String) -> String {
        side == "cc" ? "CC" : "Cdx"
    }

    private func resetDescription(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "M/d H:mm"
        return formatter.string(from: date)
    }
}

public enum CodexBarPace {
    private struct History: Decodable {
        let preferredAccountKey: String?
        let accounts: [String: [Window]]
    }

    private struct Window: Decodable {
        let name: String
        let windowMinutes: Int
        let entries: [Entry]
    }

    private struct Entry: Decodable {
        let capturedAt: String
        let resetsAt: String
        let usedPercent: Double
    }

    public static func latestWeeklySnapshot(from data: Data, provider: String) -> WeeklyPaceSnapshot? {
        guard let history = try? JSONDecoder().decode(History.self, from: data),
              let key = history.preferredAccountKey,
              let windows = history.accounts[key],
              let weekly = windows.first(where: { $0.windowMinutes == 10_080 || $0.name == "weekly" }),
              let entry = weekly.entries.last,
              let capturedAt = parseDate(entry.capturedAt),
              let resetsAt = parseDate(entry.resetsAt),
              resetsAt > capturedAt,
              (0...100).contains(entry.usedPercent) else {
            return nil
        }
        return WeeklyPaceSnapshot(
            provider: provider,
            capturedAt: capturedAt,
            resetsAt: resetsAt,
            usedPercent: entry.usedPercent,
            windowMinutes: weekly.windowMinutes
        )
    }

    public static func advisory(
        main: String,
        snapshots: [String: WeeklyPaceSnapshot],
        now: Date,
        staleAfter: TimeInterval = 30 * 60,
        minimumProjectedGapPercent: Double = 10
    ) -> WeeklyPaceAdvisory? {
        let mainProvider: String
        let otherProvider: String
        let other: String
        switch main {
        case "cdx":
            mainProvider = "codex"
            otherProvider = "claude"
            other = "cc"
        case "cc":
            mainProvider = "claude"
            otherProvider = "codex"
            other = "cdx"
        default:
            return nil
        }

        guard let mainSnapshot = snapshots[mainProvider],
              let otherSnapshot = snapshots[otherProvider],
              isFresh(mainSnapshot, now: now, staleAfter: staleAfter),
              isFresh(otherSnapshot, now: now, staleAfter: staleAfter) else {
            return nil
        }

        guard let mainProjected = mainSnapshot.projectedUsedPercentAtReset,
              let otherProjected = otherSnapshot.projectedUsedPercentAtReset else {
            return nil
        }
        let mainExhausts = mainProjected >= 100
        let otherExhausts = otherProjected >= 100
        let gap = mainProjected - otherProjected
        guard (mainExhausts && !otherExhausts) || gap >= minimumProjectedGapPercent else {
            return nil
        }
        return WeeklyPaceAdvisory(
            main: main,
            other: other,
            mainProjectedPercent: min(999, Int(mainProjected.rounded())),
            otherProjectedPercent: min(999, Int(otherProjected.rounded())),
            mainResetsAt: mainSnapshot.resetsAt,
            otherResetsAt: otherSnapshot.resetsAt,
            severity: mainExhausts ? .critical : .advisory
        )
    }

    private static func isFresh(
        _ snapshot: WeeklyPaceSnapshot,
        now: Date,
        staleAfter: TimeInterval
    ) -> Bool {
        let age = now.timeIntervalSince(snapshot.capturedAt)
        return age >= -5 * 60 && age <= staleAfter && snapshot.resetsAt > now
    }

    private static func parseDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}
