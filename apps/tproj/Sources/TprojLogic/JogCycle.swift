import Foundation

// Jog focus-cycle ordering + selection, extracted verbatim from
// focusPaneByJog (S-D3). Pure functions so the role-major order and the
// wrap / active-outside-list behavior can be unit-tested without tmux.

// Role-major cycle order: codex panes left->right, then claude panes
// left->right. Panes with any other role are excluded. Returns pane ids.
public func jogCycleOrder(panes: [(paneId: String, role: String, left: Int)]) -> [String] {
    var codex: [(left: Int, paneId: String)] = []
    var claude: [(left: Int, paneId: String)] = []
    for pane in panes {
        if pane.role.hasPrefix("codex") {
            codex.append((pane.left, pane.paneId))
        } else if pane.role.hasPrefix("claude") {
            claude.append((pane.left, pane.paneId))
        }
    }
    return (codex.sorted { $0.left < $1.left } + claude.sorted { $0.left < $1.left }).map { $0.paneId }
}

// Step one position through the cycle. `direction` is +1 (next) or -1 (prev),
// wrapping at the ends. If `active` is nil or not in `order` (e.g. the active
// pane is not a codex/claude pane), selection starts at the first entry.
// Returns nil only when `order` is empty.
public func nextPaneInCycle(order: [String], active: String?, direction: Int) -> String? {
    guard !order.isEmpty else { return nil }
    if let active, let idx = order.firstIndex(of: active) {
        return order[(idx + direction + order.count) % order.count]
    }
    return order[0]
}
