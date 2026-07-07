import Foundation

// Shell and YAML string quoting, extracted verbatim from AppViewModel (S-D3).
// Pure string transforms with no view/model coupling, so they are unit-testable.

// POSIX single-quote: wrap in '...' and escape embedded single quotes via the
// standard '\'' close/reopen dance.
public func shellSingleQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
}

// Escape a value for insertion inside a double-quoted shell string.
public func shellDoubleQuote(_ value: String) -> String {
    value
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
        .replacingOccurrences(of: "$", with: "\\$")
        .replacingOccurrences(of: "`", with: "\\`")
}

// YAML single-quoted scalar: wrap in '...' and double any embedded single quote.
public func yamlQuote(_ value: String) -> String {
    let escaped = value.replacingOccurrences(of: "'", with: "''")
    return "'\(escaped)'"
}
