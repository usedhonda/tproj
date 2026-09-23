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

public struct CodexTokenSample: Decodable, Sendable, Equatable {
    public let at: String?
    public let inputTokens: Int
    public let cachedInputTokens: Int

    enum CodingKeys: String, CodingKey {
        case at
        case inputTokens = "input_tokens"
        case cachedInputTokens = "cached_input_tokens"
    }

    public init(at: String?, inputTokens: Int, cachedInputTokens: Int) {
        self.at = at
        self.inputTokens = inputTokens
        self.cachedInputTokens = cachedInputTokens
    }
}

/// Read-only diagnostic state written by the local Codex cache observer.
/// It is not an expiry signal, human-turn signal, or Poke authorization.
public struct CodexCacheObservation: Decodable, Sendable {
    public let version: Int
    public let paneID: String
    public let panePID: Int
    public let role: String
    public let observedAt: Date
    public let lastTokenSample: CodexTokenSample?

    enum CodingKeys: String, CodingKey {
        case version
        case paneID = "pane_id"
        case panePID = "pane_pid"
        case role
        case observedAt = "observed_at"
        case lastTokenSample = "last_token_sample"
    }

    public static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return try decoder.decode(Self.self, from: data)
    }

    public func matches(paneID: String, panePID: Int, role: String, now: Date) -> Bool {
        version == 1 && !self.paneID.isEmpty && self.paneID == paneID &&
        self.panePID == panePID && self.role == role && role.hasPrefix("codex-p") &&
        observedAt <= now && now.timeIntervalSince(observedAt) <= 300 &&
        (lastTokenSample.map { $0.inputTokens >= 0 && $0.cachedInputTokens >= 0 &&
            $0.cachedInputTokens <= $0.inputTokens } ?? true)
    }
}
