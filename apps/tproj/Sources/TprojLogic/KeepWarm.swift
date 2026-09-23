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

public struct ClaudeCacheObservation: Decodable, Sendable {
    public let version: Int
    public let sessionID: String
    public let paneID: String
    public let tty: String
    public let panePID: Int
    public let role: String
    public let alias: String
    public let ownerSession: String
    public let observedAt: Date
    public let cacheExpiresAt: Date?
    public let lastUserPromptAt: Date?
    public let recacheTokensIfCold: Int?

    enum CodingKeys: String, CodingKey {
        case version, tty, role, alias
        case sessionID = "session_id", paneID = "pane_id", panePID = "pane_pid"
        case ownerSession = "owner_session", observedAt = "observed_at"
        case cacheExpiresAt = "cache_expires_at", lastUserPromptAt = "last_user_prompt_at"
        case recacheTokensIfCold = "recache_tokens_if_cold"
    }

    public static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return try decoder.decode(Self.self, from: data)
    }

    public func matches(paneID: String, tty: String, panePID: Int, role: String,
                        alias: String, ownerSession: String, now: Date) -> Bool {
        version == 1 && !sessionID.isEmpty && !tty.isEmpty && !alias.isEmpty &&
        self.paneID == paneID && self.tty == tty && self.panePID == panePID &&
        self.role == role && role.hasPrefix("claude-p") && self.alias == alias &&
        self.ownerSession == ownerSession && observedAt <= now &&
        now.timeIntervalSince(observedAt) <= 300
    }

    public var displaySession: KeepWarmSession {
        KeepWarmSession(tty: tty, cacheExpiresAt: cacheExpiresAt,
                        lastUserPromptAt: lastUserPromptAt, pokeable: false,
                        recacheTokensIfCold: recacheTokensIfCold)
    }
}
