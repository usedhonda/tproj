import Foundation

public struct KeepWarmSession: Codable, Sendable {
    public let tty: String?
    public let cacheExpiresAt: Date?
    public let lastUserPromptAt: Date?
    public let pokeable: Bool
    public let recacheTokensIfCold: Int?

    public init(
        tty: String?,
        cacheExpiresAt: Date?,
        lastUserPromptAt: Date?,
        pokeable: Bool,
        recacheTokensIfCold: Int? = nil
    ) {
        self.tty = tty
        self.cacheExpiresAt = cacheExpiresAt
        self.lastUserPromptAt = lastUserPromptAt
        self.pokeable = pokeable
        self.recacheTokensIfCold = recacheTokensIfCold
    }

    enum CodingKeys: String, CodingKey {
        case tty
        case cacheExpiresAt = "cache_expires_at"
        case lastUserPromptAt = "last_user_prompt_at"
        case pokeable
        case recacheTokensIfCold = "recache_tokens_if_cold"
    }
}

public enum KeepWarmDecision {
    public static func shouldPoke(session: KeepWarmSession, now: Date, hours: Int?) -> Bool {
        guard let hours, [1, 3, 6, 12].contains(hours),
              let tty = session.tty, !tty.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let expiry = session.cacheExpiresAt,
              let lastPrompt = session.lastUserPromptAt,
              session.pokeable else { return false }

        let remaining = expiry.timeIntervalSince(now)
        let idle = now.timeIntervalSince(lastPrompt)
        return remaining > 0 && remaining <= 90 && idle >= 0 && idle < Double(hours * 3600)
    }
}
