import Foundation

/// Server process state and a closed local view are independent facts.
public enum RemoteAgentLifecycle {
    public static func action(serverState: String?, viewClosed: Bool) -> String? {
        if serverState == "stopped" { return "Resume" }
        if viewClosed { return "Reconnect" }
        return serverState == "running" ? nil : "Check"
    }
}
