import Foundation

public struct WeeklyPaceSnapshot: Equatable, Sendable {
    public let provider: String
    public let capturedAt: Date
    public let resetsAt: Date
    public let usedPercent: Double
    public let windowMinutes: Int

    public init(provider: String, capturedAt: Date, resetsAt: Date, usedPercent: Double, windowMinutes: Int) {
        self.provider = provider
        self.capturedAt = capturedAt
        self.resetsAt = resetsAt
        self.usedPercent = usedPercent
        self.windowMinutes = windowMinutes
    }

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

public enum WeeklyPaceSeverity: String, Codable, Equatable, Sendable {
    case advisory
    case critical
}

public enum WeeklyPaceReason: String, Codable, Equatable, Sendable {
    case exhaustion
    case absoluteHigh = "absolute-high"
    case peerHeadroom = "peer-headroom"
}

public enum WeeklyPaceNoticeStatus: String, Codable, Equatable, Sendable {
    case alert
    case healthy
    case hold
    case unavailable
}

public struct WeeklyPaceNoticeSide: Codable, Equatable, Sendable {
    public let status: WeeklyPaceNoticeStatus
    public let main: String
    public let other: String
    public let severity: WeeklyPaceSeverity?
    public let reason: WeeklyPaceReason?
    public let mainRemainingPercent: Int?
    public let otherRemainingPercent: Int?
    public let mainProjectedPercent: Int?
    public let otherProjectedPercent: Int?
    public let mainResetsAt: Int?
    public let otherResetsAt: Int?

    enum CodingKeys: String, CodingKey {
        case status, main, other, severity, reason
        case mainRemainingPercent = "main_remaining_percent"
        case otherRemainingPercent = "other_remaining_percent"
        case mainProjectedPercent = "main_projected_percent"
        case otherProjectedPercent = "other_projected_percent"
        case mainResetsAt = "main_resets_at"
        case otherResetsAt = "other_resets_at"
    }
}

public struct WeeklyPaceNoticeState: Codable, Equatable, Sendable {
    public let version: Int
    public let generatedAt: Int
    public let sides: [String: WeeklyPaceNoticeSide]

    enum CodingKeys: String, CodingKey {
        case version, sides
        case generatedAt = "generated_at"
    }
}

public struct WeeklyPaceAdvisory: Equatable, Sendable {
    public let main: String
    public let other: String
    public let mainRemainingPercent: Int
    public let otherRemainingPercent: Int
    public let mainProjectedPercent: Int
    public let otherProjectedPercent: Int
    public let mainResetsAt: Date
    public let otherResetsAt: Date
    public let severity: WeeklyPaceSeverity
    public let reason: WeeklyPaceReason

    public init(
        main: String,
        other: String,
        mainRemainingPercent: Int,
        otherRemainingPercent: Int,
        mainProjectedPercent: Int,
        otherProjectedPercent: Int,
        mainResetsAt: Date,
        otherResetsAt: Date,
        severity: WeeklyPaceSeverity,
        reason: WeeklyPaceReason = .absoluteHigh
    ) {
        self.main = main
        self.other = other
        self.mainRemainingPercent = mainRemainingPercent
        self.otherRemainingPercent = otherRemainingPercent
        self.mainProjectedPercent = mainProjectedPercent
        self.otherProjectedPercent = otherProjectedPercent
        self.mainResetsAt = mainResetsAt
        self.otherResetsAt = otherResetsAt
        self.severity = severity
        self.reason = reason
    }

    public var signature: String { "\(main):\(severity.rawValue):\(reason.rawValue)" }

    public var mainProjectedRemainingPercent: Int { max(0, 100 - mainProjectedPercent) }
    public var otherProjectedRemainingPercent: Int { max(0, 100 - otherProjectedPercent) }

    public var message: String {
        let mainName = displayName(main)
        let otherName = displayName(other)
        let mainReset = resetCountdown(mainResetsAt)
        let otherReset = resetCountdown(otherResetsAt)
        switch reason {
        case .exhaustion:
            return "利用枠警告: 主\(mainName)は週\(mainRemainingPercent)%残り、\(mainReset)リセットですが、このペースではリセット前に使い切る予測です。\(otherName)は週\(otherRemainingPercent)%残り、\(otherReset)リセットです。長い作業は\(otherName)を検討してください。"
        case .absoluteHigh:
            return "利用ペース補足: 主\(mainName)は週\(mainRemainingPercent)%残り、\(mainReset)リセット時に約\(mainProjectedRemainingPercent)%残る予測です。\(otherName)は週\(otherRemainingPercent)%残り、\(otherReset)リセット時に約\(otherProjectedRemainingPercent)%残る予測です。長い作業は\(otherName)を検討してください。"
        case .peerHeadroom:
            return "利用配分のご案内: 主\(mainName)は週\(mainRemainingPercent)%残り、\(mainReset)リセット時に約\(mainProjectedRemainingPercent)%残る予測です。\(otherName)は週\(otherRemainingPercent)%残り、\(otherReset)リセット時に約\(otherProjectedRemainingPercent)%残る予測です。次の長い作業は\(otherName)を推奨します。"
        }
    }

    private func displayName(_ side: String) -> String { side == "cc" ? "CC" : "Cdx" }

    private func resetCountdown(_ date: Date) -> String {
        let seconds = max(0, Int(date.timeIntervalSinceNow))
        let days = seconds / 86_400
        let hours = (seconds % 86_400) / 3_600
        if days > 0 { return "\(days)日\(hours)時間後" }
        if hours > 0 { return "\(hours)時間後" }
        return "1時間以内"
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
        let capturedAt: String?
        let resetsAt: String?
        let usedPercent: Double?

        enum CodingKeys: String, CodingKey {
            case capturedAt, resetsAt, usedPercent
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            capturedAt = try? container.decode(String.self, forKey: .capturedAt)
            resetsAt = try? container.decode(String.self, forKey: .resetsAt)
            usedPercent = try? container.decode(Double.self, forKey: .usedPercent)
        }
    }

    public static func latestWeeklySnapshot(from data: Data, provider: String) -> WeeklyPaceSnapshot? {
        guard let history = try? JSONDecoder().decode(History.self, from: data),
              let key = history.preferredAccountKey,
              let windows = history.accounts[key],
              let weekly = windows.first(where: { $0.windowMinutes == 10_080 || $0.name == "weekly" }) else {
            return nil
        }
        for entry in weekly.entries.reversed() {
            guard let capturedAtValue = entry.capturedAt,
                  let resetsAtValue = entry.resetsAt,
                  let usedPercent = entry.usedPercent,
                  let capturedAt = parseDate(capturedAtValue),
                  let resetsAt = parseDate(resetsAtValue),
                  resetsAt > capturedAt,
                  (0...100).contains(usedPercent) else {
                continue
            }
            return WeeklyPaceSnapshot(
                provider: provider,
                capturedAt: capturedAt,
                resetsAt: resetsAt,
                usedPercent: usedPercent,
                windowMinutes: weekly.windowMinutes
            )
        }
        return nil
    }

    public static func noticeState(
        snapshots: [String: WeeklyPaceSnapshot],
        now: Date,
        staleAfter: TimeInterval = 30 * 60
    ) -> WeeklyPaceNoticeState {
        WeeklyPaceNoticeState(
            version: 1,
            generatedAt: Int(now.timeIntervalSince1970),
            sides: [
                "cc": noticeSide(main: "cc", snapshots: snapshots, now: now, staleAfter: staleAfter),
                "cdx": noticeSide(main: "cdx", snapshots: snapshots, now: now, staleAfter: staleAfter)
            ]
        )
    }

    public static func encodedNoticeState(
        snapshots: [String: WeeklyPaceSnapshot],
        now: Date,
        staleAfter: TimeInterval = 30 * 60
    ) -> Data? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try? encoder.encode(noticeState(snapshots: snapshots, now: now, staleAfter: staleAfter))
    }

    public static func advisory(
        main: String,
        snapshots: [String: WeeklyPaceSnapshot],
        now: Date,
        staleAfter: TimeInterval = 30 * 60
    ) -> WeeklyPaceAdvisory? {
        let value = noticeSide(main: main, snapshots: snapshots, now: now, staleAfter: staleAfter)
        guard value.status == .alert,
              let severity = value.severity,
              let reason = value.reason,
              let mainRemaining = value.mainRemainingPercent,
              let otherRemaining = value.otherRemainingPercent,
              let mainProjected = value.mainProjectedPercent,
              let otherProjected = value.otherProjectedPercent,
              let mainReset = value.mainResetsAt,
              let otherReset = value.otherResetsAt else { return nil }
        return WeeklyPaceAdvisory(
            main: value.main,
            other: value.other,
            mainRemainingPercent: mainRemaining,
            otherRemainingPercent: otherRemaining,
            mainProjectedPercent: mainProjected,
            otherProjectedPercent: otherProjected,
            mainResetsAt: Date(timeIntervalSince1970: TimeInterval(mainReset)),
            otherResetsAt: Date(timeIntervalSince1970: TimeInterval(otherReset)),
            severity: severity,
            reason: reason
        )
    }

    private static func noticeSide(
        main: String,
        snapshots: [String: WeeklyPaceSnapshot],
        now: Date,
        staleAfter: TimeInterval
    ) -> WeeklyPaceNoticeSide {
        let mainProvider: String
        let otherProvider: String
        let other: String
        switch main {
        case "cdx": (mainProvider, otherProvider, other) = ("codex", "claude", "cc")
        case "cc": (mainProvider, otherProvider, other) = ("claude", "codex", "cdx")
        default: return unavailableSide(main: main, other: "")
        }

        guard let mainSnapshot = snapshots[mainProvider],
              let otherSnapshot = snapshots[otherProvider],
              isFresh(mainSnapshot, now: now, staleAfter: staleAfter),
              isFresh(otherSnapshot, now: now, staleAfter: staleAfter),
              mainSnapshot.usedPercent >= 10,
              otherSnapshot.usedPercent >= 10,
              let mainProjected = mainSnapshot.projectedUsedPercentAtReset,
              let otherProjected = otherSnapshot.projectedUsedPercentAtReset else {
            return unavailableSide(main: main, other: other)
        }

        let common = (
            main: main,
            other: other,
            mainRemaining: max(0, min(100, Int((100 - mainSnapshot.usedPercent).rounded()))),
            otherRemaining: max(0, min(100, Int((100 - otherSnapshot.usedPercent).rounded()))),
            mainProjected: min(999, Int(mainProjected.rounded())),
            otherProjected: min(999, Int(otherProjected.rounded())),
            mainReset: Int(mainSnapshot.resetsAt.timeIntervalSince1970),
            otherReset: Int(otherSnapshot.resetsAt.timeIntervalSince1970)
        )
        if mainProjected >= 100 {
            return side(status: .alert, severity: .critical, reason: .exhaustion, common: common)
        }
        if mainProjected >= 90 {
            return side(status: .alert, severity: .advisory, reason: .absoluteHigh, common: common)
        }
        if mainProjected >= 75, otherProjected <= 60, mainProjected - otherProjected >= 20 {
            return side(status: .alert, severity: .advisory, reason: .peerHeadroom, common: common)
        }

        let absoluteRecovered = mainProjected < 80
        let relativeRecovered = mainProjected < 65 || otherProjected > 70 || mainProjected - otherProjected < 10
        if absoluteRecovered && relativeRecovered {
            return side(status: .healthy, severity: nil, reason: nil, common: common)
        }
        return side(status: .hold, severity: nil, reason: nil, common: common)
    }

    private static func unavailableSide(main: String, other: String) -> WeeklyPaceNoticeSide {
        WeeklyPaceNoticeSide(
            status: .unavailable,
            main: main,
            other: other,
            severity: nil,
            reason: nil,
            mainRemainingPercent: nil,
            otherRemainingPercent: nil,
            mainProjectedPercent: nil,
            otherProjectedPercent: nil,
            mainResetsAt: nil,
            otherResetsAt: nil
        )
    }

    private static func side(
        status: WeeklyPaceNoticeStatus,
        severity: WeeklyPaceSeverity?,
        reason: WeeklyPaceReason?,
        common: (
            main: String,
            other: String,
            mainRemaining: Int,
            otherRemaining: Int,
            mainProjected: Int,
            otherProjected: Int,
            mainReset: Int,
            otherReset: Int
        )
    ) -> WeeklyPaceNoticeSide {
        WeeklyPaceNoticeSide(
            status: status,
            main: common.main,
            other: common.other,
            severity: severity,
            reason: reason,
            mainRemainingPercent: common.mainRemaining,
            otherRemainingPercent: common.otherRemaining,
            mainProjectedPercent: common.mainProjected,
            otherProjectedPercent: common.otherProjected,
            mainResetsAt: common.mainReset,
            otherResetsAt: common.otherReset
        )
    }

    private static func isFresh(_ snapshot: WeeklyPaceSnapshot, now: Date, staleAfter: TimeInterval) -> Bool {
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
