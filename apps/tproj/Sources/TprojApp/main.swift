import SwiftUI
import Foundation
import AppKit
import UniformTypeIdentifiers

struct WorkspaceProject: Identifiable {
    let id = UUID()
    var path: String
    var type: String
    var host: String
    var alias: String
    var enabled: Bool

    var effectiveAlias: String {
        if !alias.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return alias
        }
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "(unnamed)" }
        return URL(fileURLWithPath: trimmed).lastPathComponent
    }

    var projectName: String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "(no-path)" }
        return URL(fileURLWithPath: trimmed).lastPathComponent
    }
}

struct LiveColumn: Identifiable {
    let id = UUID()
    var column: Int
    var projectPath: String
    var hostLabel: String
    var width: Int
    var left: Int
    var claudePaneID: String?
    var codexPaneID: String?
    var yaziPaneID: String?
    var terminalPaneID: String?

    var projectName: String {
        if projectPath.isEmpty { return "unknown" }
        return URL(fileURLWithPath: projectPath).lastPathComponent
    }
}

struct CommandResult {
    var exitCode: Int32
    var stdout: String
    var stderr: String
}

@MainActor
final class AppViewModel: ObservableObject {
    @Published var workspaceProjects: [WorkspaceProject] = []
    @Published var liveColumns: [LiveColumn] = []
    @Published var selectedAlias: String = ""
    @Published var statusText: String = "Ready"
    @Published var isBusy: Bool = false

    private let fileManager = FileManager.default

    var workspacePath: String {
        let home = NSHomeDirectory()
        return "\(home)/.config/tproj/workspace.yaml"
    }

    var canAddColumn: Bool {
        !selectedAlias.isEmpty && !isBusy
    }

    var inactiveProjects: [WorkspaceProject] {
        let livePaths = Set(liveColumns.map { $0.projectPath })
        return workspaceProjects.filter { !livePaths.contains($0.path) }
    }

    private struct PaneInfo {
        var paneID: String
        var role: String
        var column: Int?
    }

    func onAppear() {
        Task {
            await refreshAll()
        }
    }

    func refreshAll() async {
        isBusy = true
        defer { isBusy = false }

        loadWorkspaceProjects()
        loadLiveColumns()
        normalizeSelection()
        statusText = "Reloaded: \(DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium))"
    }

    func addWorkspaceRow() {
        workspaceProjects.append(
            WorkspaceProject(path: "", type: "local", host: "", alias: "", enabled: true)
        )
    }

    func deleteWorkspaceRow(_ projectID: UUID) {
        workspaceProjects.removeAll { $0.id == projectID }
        normalizeSelection()
    }

    func addColumn() async {
        guard !selectedAlias.isEmpty else {
            statusText = "No project selected"
            return
        }
        await addColumnByAlias(selectedAlias)
    }

    func addColumnByAlias(_ alias: String) async {
        isBusy = true
        defer { isBusy = false }

        let result = await runCommandAsync("/usr/bin/env", ["tproj", "--add", alias])
        if result.exitCode == 0 {
            statusText = "Added column: \(alias)"
            loadLiveColumns()
        } else {
            statusText = "Add failed: \(trimmedError(result))"
        }
    }

    func toggleYazi(for column: LiveColumn) async {
        guard let pane = column.codexPaneID ?? column.claudePaneID else {
            statusText = "No pane found for column \(column.column)"
            return
        }

        isBusy = true
        defer { isBusy = false }

        let scriptPath = "\(NSHomeDirectory())/bin/tproj-toggle-yazi"
        let result = await runCommandAsync("/usr/bin/env", [scriptPath, "tproj-workspace", pane])
        if result.exitCode == 0 {
            statusText = "Toggled Yazi for #\(column.column)"
        } else {
            statusText = "Yazi toggle failed: \(trimmedError(result))"
        }
        loadLiveColumns()
    }

    func toggleTerminal(for column: LiveColumn) async {
        isBusy = true
        defer { isBusy = false }

        let sessionTarget = "tproj-workspace:dev"
        let listResult = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_id}:#{@role}"])
        guard listResult.exitCode == 0 else {
            statusText = "Term: \(trimmedError(listResult))"
            loadLiveColumns()
            return
        }

        let roleName = "terminal-p\(column.column)"
        let paneRoles: [(id: String, role: String)] = listResult.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard parts.count == 2 else { return nil }
                return (id: parts[0], role: parts[1])
            }

        // Toggle off: kill existing terminal
        if let existing = paneRoles.first(where: { $0.role == roleName }) {
            let killResult = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", existing.id])
            statusText = killResult.exitCode == 0
                ? "Terminal off for #\(column.column)"
                : "Term off failed: \(trimmedError(killResult))"
            loadLiveColumns()
            return
        }

        // Toggle on: find target pane from fresh list (codex preferred, claude fallback)
        guard let targetPane = paneRoles.first(where: { $0.role == "codex-p\(column.column)" })?.id
                ?? paneRoles.first(where: { $0.role == "claude-p\(column.column)" })?.id else {
            statusText = "Term: no pane for #\(column.column)"
            return
        }

        let createResult = await runCommandAsync("/usr/bin/env", [
            "tmux", "split-window", "-v", "-b", "-t", targetPane,
            "-c", "/tmp", "-l", "25%", "-P", "-F", "#{pane_id}"
        ])
        guard createResult.exitCode == 0 else {
            statusText = "Term[\(createResult.exitCode)]: \(trimmedError(createResult))"
            return
        }

        let newPane = createResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newPane.isEmpty else {
            statusText = "Term: empty pane id"
            return
        }

        // Set @role immediately to prevent reflow-agent-pane hook from misidentifying this pane
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@role", roleName])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@column", "\(column.column)"])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@project", column.projectPath])

        if let host = hostForColumn(column) {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_host", host])
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_path", column.projectPath])
            let remoteCmd = "ssh -t \(shellSingleQuote(host)) \"cd \(shellDoubleQuote(column.projectPath)) && exec \\$SHELL -l\""
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, remoteCmd, "C-m"])
        } else {
            let localDir = column.projectPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? NSHomeDirectory() : column.projectPath
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, "cd \(shellSingleQuote(localDir)) && exec $SHELL -l", "C-m"])
        }

        statusText = "Terminal on for #\(column.column)"
        loadLiveColumns()
    }

    func removeColumn(_ column: LiveColumn) async {
        guard column.claudePaneID != nil || column.codexPaneID != nil else {
            statusText = "Missing pane info for column \(column.column)"
            return
        }

        isBusy = true
        defer { isBusy = false }

        var errors: [String] = []

        if let codex = column.codexPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", codex])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let claude = column.claudePaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", claude])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let yazi = column.yaziPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", yazi])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        if let terminal = column.terminalPaneID {
            let res = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", terminal])
            if res.exitCode != 0 { errors.append(trimmedError(res)) }
        }

        _ = await runCommandAsync("\(NSHomeDirectory())/bin/rebalance-workspace-columns", ["tproj-workspace"])
        _ = await normalizeColumnsByVisualOrderAsync()

        if errors.isEmpty {
            statusText = "Removed column \(column.column)"
        } else {
            statusText = "Drop failed: \(errors.joined(separator: " | "))"
        }

        loadLiveColumns()
    }

    func moveColumn(from sourceColumn: Int, to targetColumn: Int) async {
        guard sourceColumn != targetColumn else { return }
        guard !isBusy else { return }

        // Optimistic UI swap: build new array locally to avoid intermediate duplicate IDs
        // (swapAt + column reassign fires @Published 3 times; the 2nd has duplicate id → SwiftUI hang)
        if let srcIdx = liveColumns.firstIndex(where: { $0.column == sourceColumn }),
           let tgtIdx = liveColumns.firstIndex(where: { $0.column == targetColumn }) {
            var updated = liveColumns
            updated.swapAt(srcIdx, tgtIdx)
            updated[srcIdx].column = sourceColumn
            updated[tgtIdx].column = targetColumn
            liveColumns = updated  // single atomic @Published fire
        }

        isBusy = true
        defer { isBusy = false }

        let agentsActive = await runCommandAsync("/usr/bin/env", ["tmux", "show-environment", "-t", "tproj-workspace", "TPROJ_AGENTS_ACTIVE"])
        if agentsActive.exitCode == 0 {
            statusText = "Reorder disabled while agent panes are active"
            loadLiveColumns()
            return
        }

        let panes = await listWorkspacePanesAsync()
        guard !panes.isEmpty else {
            statusText = "Reorder failed: workspace panes not found"
            loadLiveColumns()
            return
        }

        guard let claudeSource = paneID(forRole: "claude-p\(sourceColumn)", panes: panes),
              let claudeTarget = paneID(forRole: "claude-p\(targetColumn)", panes: panes),
              let codexSource = paneID(forRole: "codex-p\(sourceColumn)", panes: panes),
              let codexTarget = paneID(forRole: "codex-p\(targetColumn)", panes: panes) else {
            statusText = "Reorder failed: required panes not found"
            loadLiveColumns()
            return
        }

        // Gather pre-swap metadata from claude panes
        let srcMeta = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeSource, "-p", "#{@project}|#{@remote_host}|#{@remote_path}|#{pane_left}"])
        let tgtMeta = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeTarget, "-p", "#{@project}|#{@remote_host}|#{@remote_path}"])

        let srcParts = srcMeta.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        let tgtParts = tgtMeta.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: "|", omittingEmptySubsequences: false).map(String.init)

        let sourceProject = srcParts.count > 0 ? srcParts[0] : ""
        let sourceRemoteHost = srcParts.count > 1 ? srcParts[1] : ""
        let sourceRemotePath = srcParts.count > 2 ? srcParts[2] : ""
        let sourceOriginalLeft = srcParts.count > 3 ? (Int(srcParts[3]) ?? -1) : -1

        let targetProject = tgtParts.count > 0 ? tgtParts[0] : ""
        let targetRemoteHost = tgtParts.count > 1 ? tgtParts[1] : ""
        let targetRemotePath = tgtParts.count > 2 ? tgtParts[2] : ""

        let yaziSource = paneID(forRole: "yazi-p\(sourceColumn)", panes: panes)
        let yaziTarget = paneID(forRole: "yazi-p\(targetColumn)", panes: panes)
        let terminalSource = paneID(forRole: "terminal-p\(sourceColumn)", panes: panes)
        let terminalTarget = paneID(forRole: "terminal-p\(targetColumn)", panes: panes)

        // Perform swap-pane operations
        let mainSwap1 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", claudeSource, "-t", claudeTarget])
        guard mainSwap1.exitCode == 0 else {
            statusText = "Reorder failed: \(trimmedError(mainSwap1))"
            loadLiveColumns()
            return
        }
        let mainSwap2 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", codexSource, "-t", codexTarget])
        guard mainSwap2.exitCode == 0 else {
            statusText = "Reorder failed: \(trimmedError(mainSwap2))"
            loadLiveColumns()
            return
        }

        if let ys = yaziSource, let yt = yaziTarget {
            let s = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", ys, "-t", yt])
            if s.exitCode != 0 {
                statusText = "Reorder warning (yazi): \(trimmedError(s))"
            }
        } else if let ys = yaziSource {
            _ = await relocatePaneAboveCodexAsync(paneID: ys, codexPaneID: codexSource)
        } else if let yt = yaziTarget {
            _ = await relocatePaneAboveCodexAsync(paneID: yt, codexPaneID: codexTarget)
        }

        if let ts = terminalSource, let tt = terminalTarget {
            let s = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", ts, "-t", tt])
            if s.exitCode != 0 {
                statusText = "Reorder warning (term): \(trimmedError(s))"
            }
        } else if let ts = terminalSource {
            _ = await relocatePaneAboveCodexAsync(paneID: ts, codexPaneID: codexSource)
        } else if let tt = terminalTarget {
            _ = await relocatePaneAboveCodexAsync(paneID: tt, codexPaneID: codexTarget)
        }

        // Detect if swap-pane moved panes physically (Case A) or just swapped content (Case B)
        let check = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeSource, "-p", "#{pane_left}"])
        let srcLeftAfter = Int(check.stdout.trimmingCharacters(in: .whitespacesAndNewlines)) ?? -1
        let panesMoved = (srcLeftAfter != sourceOriginalLeft) && srcLeftAfter >= 0 && sourceOriginalLeft >= 0

        if !panesMoved {
            // Case B: content swapped but pane IDs stayed at original positions.
            // @project tags are still at their original positions, explicitly swap them.
            await swapProjectTagsAsync(
                sourceColumn: sourceColumn, targetColumn: targetColumn,
                sourceProject: sourceProject, sourceRemoteHost: sourceRemoteHost, sourceRemotePath: sourceRemotePath,
                targetProject: targetProject, targetRemoteHost: targetRemoteHost, targetRemotePath: targetRemotePath
            )
        }

        // normalizeColumnsByVisualOrderAsync handles @column/@role for both cases
        _ = await runCommandAsync("\(NSHomeDirectory())/bin/rebalance-workspace-columns", ["tproj-workspace"])
        let normalized = await normalizeColumnsByVisualOrderAsync()
        if !normalized {
            statusText = "Reorder warning: visual normalize failed"
        }
        loadLiveColumns()
        refreshColumnIdentities()
        statusText = "Swapped #\(sourceColumn) and #\(targetColumn)"
    }

    func saveWorkspace() async {
        isBusy = true
        defer { isBusy = false }

        do {
            let content = renderWorkspaceYAML()
            let parent = URL(fileURLWithPath: workspacePath).deletingLastPathComponent()
            try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
            try content.write(toFile: workspacePath, atomically: true, encoding: .utf8)
            statusText = "Saved workspace.yaml"
            loadWorkspaceProjects()
            normalizeSelection()
        } catch {
            statusText = "Save failed: \(error.localizedDescription)"
        }
    }

    func openWorkspaceYAML() {
        let path = workspacePath
        guard fileManager.fileExists(atPath: path) else {
            statusText = "workspace.yaml not found"
            return
        }
        let url = URL(fileURLWithPath: path)
        if NSWorkspace.shared.open(url) {
            statusText = "Opened workspace.yaml"
        } else {
            statusText = "Failed to open workspace.yaml"
        }
    }

    func stopSession() async {
        isBusy = true
        defer { isBusy = false }

        let sessions = await getTprojSessions()
        guard !sessions.isEmpty else {
            statusText = "No tproj sessions found"
            liveColumns = []
            return
        }

        // Collect descendant PIDs before stopping (to clean up MCP servers)
        let descendantPids = await collectSessionDescendants(sessions: sessions)

        // Phase 1: Send graceful exit signals to each pane by role
        for session in sessions {
            let listResult = await runCommandAsync("/usr/bin/env", [
                "tmux", "list-panes", "-s", "-t", session, "-F", "#{pane_id}:#{@role}"
            ])
            guard listResult.exitCode == 0 else { continue }

            let paneRoles: [(id: String, role: String)] = listResult.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .map(String.init)
                .compactMap { line in
                    let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                    guard parts.count == 2 else { return nil }
                    return (id: parts[0], role: parts[1])
                }

            // Send C-c to claude/codex/agent panes, q to yazi panes
            for pane in paneRoles {
                if pane.role.hasPrefix("claude") || pane.role.hasPrefix("codex") || pane.role.hasPrefix("agent") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "C-c", ""])
                } else if pane.role.hasPrefix("yazi") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "q", ""])
                }
            }

            // Brief pause for C-c to take effect
            try? await Task.sleep(nanoseconds: 300_000_000) // 0.3s

            // Send /exit to claude/agent panes
            for pane in paneRoles {
                if pane.role.hasPrefix("claude") || pane.role.hasPrefix("agent") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "/exit", "Enter"])
                }
            }
        }

        // Phase 2: Poll has-session for up to 3 seconds
        let deadline = Date().addingTimeInterval(3.0)
        while Date() < deadline {
            let allGone = await withTaskGroup(of: Bool.self, returning: Bool.self) { group in
                for session in sessions {
                    group.addTask {
                        let r = await self.runCommandAsync("/usr/bin/env", ["tmux", "has-session", "-t", session])
                        return r.exitCode != 0 // true = session gone
                    }
                }
                var results: [Bool] = []
                for await result in group { results.append(result) }
                return results.allSatisfy { $0 }
            }
            if allGone { break }
            try? await Task.sleep(nanoseconds: 300_000_000) // 0.3s
        }

        // Kill team-watcher
        _ = await runCommandAsync("/usr/bin/env", ["pkill", "-TERM", "-f", "bin/team-watcher"])

        // Phase 3: Force kill remaining sessions
        for session in sessions {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-session", "-t", session])
        }

        // Clean up surviving MCP server processes
        await killSurvivingDescendants(descendantPids)
        await cleanupOrphanedMcp()

        // Clean up dead-agents file
        try? FileManager.default.removeItem(atPath: "/tmp/tproj-dead-agents")

        statusText = "Session stopped"
        liveColumns = []
    }

    func killSession() async {
        isBusy = true
        defer { isBusy = false }

        let sessions = await getTprojSessions()
        guard !sessions.isEmpty else {
            statusText = "No tproj sessions found"
            liveColumns = []
            return
        }

        // Collect descendant PIDs before killing (to clean up MCP servers)
        let descendantPids = await collectSessionDescendants(sessions: sessions)

        // Kill team-watcher first
        _ = await runCommandAsync("/usr/bin/env", ["pkill", "-TERM", "-f", "bin/team-watcher"])

        // Kill all tproj sessions
        for session in sessions {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-session", "-t", session])
        }

        // Clean up surviving MCP server processes
        await killSurvivingDescendants(descendantPids)
        await cleanupOrphanedMcp()

        // Clean up dead-agents file
        try? FileManager.default.removeItem(atPath: "/tmp/tproj-dead-agents")

        statusText = "Session killed"
        liveColumns = []
    }

    /// Get all tmux sessions with @tproj=true tag
    private func getTprojSessions() async -> [String] {
        let result = await runCommandAsync("/usr/bin/env", [
            "tmux", "list-sessions", "-F", "#{session_name}:#{@tproj}"
        ])
        guard result.exitCode == 0 else { return [] }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard parts.count == 2, parts[1] == "true" else { return nil }
                return parts[0]
            }
    }

    /// Collect all descendant PIDs from panes of given sessions (BFS via pgrep -P)
    private func collectSessionDescendants(sessions: [String]) async -> Set<Int32> {
        var panePids: [Int32] = []
        for session in sessions {
            let result = await runCommandAsync("/usr/bin/env", [
                "tmux", "list-panes", "-s", "-t", session, "-F", "#{pane_pid}"
            ])
            guard result.exitCode == 0 else { continue }
            let pids = result.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap { Int32($0) }
            panePids.append(contentsOf: pids)
        }

        // BFS: collect all descendants
        var allDescendants = Set<Int32>()
        var queue = panePids
        while !queue.isEmpty {
            let current = queue.removeFirst()
            let pgrepResult = await runCommandAsync("/usr/bin/env", ["pgrep", "-P", "\(current)"])
            guard pgrepResult.exitCode == 0 else { continue }
            let children = pgrepResult.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .compactMap { Int32($0) }
            for child in children {
                if allDescendants.insert(child).inserted {
                    queue.append(child)
                }
            }
        }
        return allDescendants
    }

    /// Kill surviving descendant processes after session termination
    private func killSurvivingDescendants(_ pids: Set<Int32>) async {
        for pid in pids {
            kill(pid, SIGTERM)
        }
    }

    /// Kill orphaned MCP server processes (PPID=1, reparented to launchd)
    private func cleanupOrphanedMcp() async {
        let result = await runCommandAsync("/usr/bin/env", [
            "sh", "-c",
            "ps -eo pid=,ppid=,command= 2>/dev/null | awk '$2 == 1' | grep -E '(context7-mcp|playwright-mcp|chrome-ai-bridge|claude-in-chrome-mcp|@playwright/mcp|@upstash/context7)' | awk '{print $1}'"
        ])
        guard result.exitCode == 0 else { return }
        let orphanPids = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .compactMap { Int32($0) }
        for pid in orphanPids {
            kill(pid, SIGTERM)
        }
    }

    /// Replace all LiveColumns with fresh instances (new UUIDs) to reset macOS drag registrations.
    private func refreshColumnIdentities() {
        liveColumns = liveColumns.map {
            LiveColumn(
                column: $0.column, projectPath: $0.projectPath, hostLabel: $0.hostLabel,
                width: $0.width, left: $0.left, claudePaneID: $0.claudePaneID,
                codexPaneID: $0.codexPaneID, yaziPaneID: $0.yaziPaneID, terminalPaneID: $0.terminalPaneID
            )
        }
    }

    private func normalizeSelection() {
        let aliases = workspaceProjects.map { $0.effectiveAlias }
        if aliases.isEmpty {
            selectedAlias = ""
            return
        }
        if !aliases.contains(selectedAlias) {
            selectedAlias = aliases[0]
        }
    }

    private func loadWorkspaceProjects() {
        let url = URL(fileURLWithPath: workspacePath)
        guard fileManager.fileExists(atPath: workspacePath) else {
            workspaceProjects = []
            return
        }

        let query = ".projects[]? | [(.path // \"\"),(.type // \"local\"),(.host // \"\"),(.alias // \"\"),((.enabled // true)|tostring)] | @tsv"
        let result = runCommand("/usr/bin/env", ["yq", "-r", query, url.path])

        guard result.exitCode == 0 else {
            statusText = "workspace.yaml read failed (yq): \(trimmedError(result))"
            workspaceProjects = []
            return
        }

        let rows = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)

        var parsed: [WorkspaceProject] = []
        for row in rows {
            let parts = row.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            if parts.count < 5 { continue }

            let enabledRaw = parts[4].lowercased()
            let enabled = enabledRaw == "true"

            parsed.append(
                WorkspaceProject(
                    path: parts[0],
                    type: parts[1].isEmpty ? "local" : parts[1],
                    host: parts[2],
                    alias: parts[3],
                    enabled: enabled
                )
            )
        }

        workspaceProjects = parsed
    }

    private func loadLiveColumns() {
        let format = "#{@column}|#{@role}|#{@project}|#{@remote_host}|#{@remote_path}|#{pane_width}|#{pane_left}|#{pane_id}"
        let result = runCommand("/usr/bin/env", ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", format])

        guard result.exitCode == 0 else {
            liveColumns = []
            return
        }

        struct Builder {
            var column: Int
            var projectPath: String = ""
            var hostLabel: String = "local"
            var width: Int = 0
            var left: Int = Int.max
            var claudePaneID: String?
            var codexPaneID: String?
            var yaziPaneID: String?
            var terminalPaneID: String?
        }

        var grouped: [Int: Builder] = [:]

        let lines = result.stdout.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
        for line in lines {
            let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
            if parts.count < 8 { continue }

            guard let col = Int(parts[0]), col > 0 else { continue }
            let role = parts[1]
            let project = parts[2]
            let remoteHost = parts[3]
            let remotePath = parts[4]
            let width = Int(parts[5]) ?? 0
            let left = Int(parts[6]) ?? Int.max
            let paneID = parts[7]
            let isPrimaryPane = role.hasPrefix("claude-p") || role.hasPrefix("codex-p")

            var entry = grouped[col] ?? Builder(column: col)
            if width > 0 { entry.width = width }
            if isPrimaryPane, left < entry.left { entry.left = left }

            // Keep column identity tied to claude/codex panes to avoid stale yazi/term metadata overriding UI.
            if isPrimaryPane || entry.projectPath.isEmpty {
                let isRemote = project.hasPrefix("ssh://") || !remoteHost.isEmpty || !remotePath.isEmpty
                if isRemote {
                    entry.hostLabel = remoteHost.isEmpty ? "remote" : "remote@\(remoteHost)"
                    if !remotePath.isEmpty {
                        entry.projectPath = remotePath
                    } else if project.hasPrefix("ssh://") {
                        let stripped = project.replacingOccurrences(of: "ssh://", with: "")
                        if let slash = stripped.firstIndex(of: "/") {
                            entry.projectPath = "/" + stripped[slash...].dropFirst()
                        }
                    }
                } else {
                    entry.hostLabel = "local"
                    entry.projectPath = project
                }
            }

            if role.hasPrefix("claude-p") { entry.claudePaneID = paneID }
            if role.hasPrefix("codex-p") { entry.codexPaneID = paneID }
            if role.hasPrefix("yazi-p") { entry.yaziPaneID = paneID }
            if role.hasPrefix("terminal-p") { entry.terminalPaneID = paneID }

            grouped[col] = entry
        }

        let newData = grouped
            .values
            .sorted(by: {
                if $0.left != $1.left { return $0.left < $1.left }
                return $0.column < $1.column
            })
            .map {
                LiveColumn(
                    column: $0.column,
                    projectPath: $0.projectPath,
                    hostLabel: $0.hostLabel,
                    width: $0.width,
                    left: $0.left == Int.max ? 0 : $0.left,
                    claudePaneID: $0.claudePaneID,
                    codexPaneID: $0.codexPaneID,
                    yaziPaneID: $0.yaziPaneID,
                    terminalPaneID: $0.terminalPaneID
                )
            }

        // Merge: match by projectPath to preserve existing UUIDs (stable SwiftUI identity)
        var used = Set<UUID>()
        var merged: [LiveColumn] = []
        for data in newData {
            if !data.projectPath.isEmpty,
               var existing = liveColumns.first(where: {
                   $0.projectPath == data.projectPath && !used.contains($0.id)
               }) {
                used.insert(existing.id)
                existing.column = data.column
                existing.hostLabel = data.hostLabel
                existing.width = data.width
                existing.left = data.left
                existing.claudePaneID = data.claudePaneID
                existing.codexPaneID = data.codexPaneID
                existing.yaziPaneID = data.yaziPaneID
                existing.terminalPaneID = data.terminalPaneID
                merged.append(existing)
            } else {
                merged.append(data)
            }
        }
        liveColumns = merged
    }

    private func normalizeColumnsByVisualOrderAsync() async -> Bool {
        let result = await runCommandAsync(
            "/usr/bin/env",
            ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", "#{pane_id}|#{pane_left}|#{@column}|#{@role}"]
        )
        guard result.exitCode == 0 else { return false }

        struct Row {
            var paneID: String
            var left: Int
            var column: Int
            var role: String
        }

        let rows: [Row] = result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                guard parts.count >= 4,
                      let left = Int(parts[1]),
                      let column = Int(parts[2]),
                      column > 0 else {
                    return nil
                }
                return Row(paneID: parts[0], left: left, column: column, role: parts[3])
            }

        guard !rows.isEmpty else { return false }

        var leftByColumn: [Int: Int] = [:]
        for row in rows where row.role.hasPrefix("claude-p") || row.role.hasPrefix("codex-p") {
            let cur = leftByColumn[row.column] ?? Int.max
            if row.left < cur {
                leftByColumn[row.column] = row.left
            }
        }
        if leftByColumn.isEmpty {
            for row in rows {
                let cur = leftByColumn[row.column] ?? Int.max
                if row.left < cur {
                    leftByColumn[row.column] = row.left
                }
            }
        }

        let orderedColumns = leftByColumn.keys.sorted { (leftByColumn[$0] ?? Int.max) < (leftByColumn[$1] ?? Int.max) }
        guard !orderedColumns.isEmpty else { return false }

        var remap: [Int: Int] = [:]
        for (idx, oldCol) in orderedColumns.enumerated() {
            remap[oldCol] = idx + 1
        }

        var ok = true
        for row in rows {
            guard let newCol = remap[row.column] else { continue }

            if newCol != row.column {
                let c = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", row.paneID, "@column", "\(newCol)"])
                if c.exitCode != 0 { ok = false }
            }

            let newRole = remappedRoleColumnSuffix(row.role, remap: remap)
            if newRole != row.role {
                let r = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", row.paneID, "@role", newRole])
                if r.exitCode != 0 { ok = false }
            }
        }
        return ok
    }

    private func remappedRoleColumnSuffix(_ role: String, remap: [Int: Int]) -> String {
        let pattern = "^(.*-p)(\\d+)(.*)$"
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return role }
        let range = NSRange(role.startIndex..<role.endIndex, in: role)
        guard let match = regex.firstMatch(in: role, options: [], range: range),
              match.numberOfRanges == 4,
              let prefixRange = Range(match.range(at: 1), in: role),
              let numberRange = Range(match.range(at: 2), in: role),
              let suffixRange = Range(match.range(at: 3), in: role),
              let old = Int(role[numberRange]),
              let mapped = remap[old] else {
            return role
        }
        return "\(role[prefixRange])\(mapped)\(role[suffixRange])"
    }

    private func listWorkspacePanesAsync() async -> [PaneInfo] {
        let result = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", "tproj-workspace:dev", "-F", "#{pane_id}|#{@role}|#{@column}"])
        guard result.exitCode == 0 else { return [] }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                guard parts.count >= 3 else { return nil }
                let col = Int(parts[2])
                return PaneInfo(paneID: parts[0], role: parts[1], column: col)
            }
    }

    private func paneID(forRole role: String, panes: [PaneInfo]) -> String? {
        panes.first(where: { $0.role == role })?.paneID
    }

    private func relocatePaneAboveCodexAsync(paneID: String, codexPaneID: String) async -> Bool {
        let create = await runCommandAsync("/usr/bin/env", ["tmux", "split-window", "-v", "-b", "-t", codexPaneID, "-c", "/tmp", "-l", "25%", "-P", "-F", "#{pane_id}"])
        guard create.exitCode == 0 else { return false }
        let placeholder = create.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !placeholder.isEmpty else { return false }
        let swap = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", paneID, "-t", placeholder])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "kill-pane", "-t", placeholder])
        return swap.exitCode == 0
    }

    private func swapProjectTagsAsync(
        sourceColumn: Int, targetColumn: Int,
        sourceProject: String, sourceRemoteHost: String, sourceRemotePath: String,
        targetProject: String, targetRemoteHost: String, targetRemotePath: String
    ) async {
        let panes = await listWorkspacePanesAsync()
        for pane in panes {
            guard let col = pane.column, col == sourceColumn || col == targetColumn else { continue }
            if col == sourceColumn {
                // Pane at source position -> should now reflect target's project data
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@project", targetProject])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_host", targetRemoteHost])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_path", targetRemotePath])
            } else {
                // Pane at target position -> should now reflect source's project data
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@project", sourceProject])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_host", sourceRemoteHost])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", pane.paneID, "@remote_path", sourceRemotePath])
            }
        }
    }

    private func hostForColumn(_ column: LiveColumn) -> String? {
        guard column.hostLabel != "local" else { return nil }
        if let project = workspaceProjects.first(where: { $0.path == column.projectPath }) {
            let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
            if !host.isEmpty { return host }
        }
        if column.hostLabel.hasPrefix("remote@") {
            return String(column.hostLabel.dropFirst("remote@".count))
        }
        return nil
    }

    private func shellSingleQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
    }

    private func shellDoubleQuote(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "$", with: "\\$")
            .replacingOccurrences(of: "`", with: "\\`")
    }

    private func renderWorkspaceYAML() -> String {
        var lines: [String] = []
        lines.append("projects:")

        for project in workspaceProjects {
            lines.append("  - path: \(yamlQuote(project.path))")

            // type: only write when remote (local is default)
            if project.type == "remote" {
                lines.append("    type: remote")
                let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
                lines.append("    host: \(yamlQuote(host))")
            }

            let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
            if !alias.isEmpty {
                lines.append("    alias: \(yamlQuote(alias))")
            }

            // enabled: only write when false (true is default)
            if !project.enabled {
                lines.append("    enabled: false")
            }
        }

        return lines.joined(separator: "\n") + "\n"
    }

    private func yamlQuote(_ value: String) -> String {
        let escaped = value.replacingOccurrences(of: "'", with: "''")
        return "'\(escaped)'"
    }

    private func runCommand(_ launchPath: String, _ arguments: [String]) -> CommandResult {
        Self.executeCommand(launchPath, arguments)
    }

    private func runCommandAsync(_ launchPath: String, _ arguments: [String]) async -> CommandResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let result = Self.executeCommand(launchPath, arguments)
                continuation.resume(returning: result)
            }
        }
    }

    nonisolated private static func executeCommand(_ launchPath: String, _ arguments: [String]) -> CommandResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        do {
            try process.run()
            process.waitUntilExit()

            let out = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let err = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

            return CommandResult(exitCode: process.terminationStatus, stdout: out, stderr: err)
        } catch {
            return CommandResult(exitCode: 1, stdout: "", stderr: error.localizedDescription)
        }
    }

    private func trimmedError(_ result: CommandResult) -> String {
        let text = result.stderr.isEmpty ? result.stdout : result.stderr
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct Card<Content: View>: View {
    var compact: Bool = false
    var chrome: Bool = true
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 4 : 8) {
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(chrome ? (compact ? 2 : 6) : 0)
        .background {
            if chrome {
                RoundedRectangle(cornerRadius: compact ? 5 : 8, style: .continuous)
                    .fill(.black.opacity(0.28))
                    .overlay(
                        RoundedRectangle(cornerRadius: compact ? 5 : 8, style: .continuous)
                            .stroke(Color.white.opacity(0.08), lineWidth: 1)
                    )
            }
        }
    }
}

struct SectionHeader: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 16, weight: .semibold, design: .rounded))
            .foregroundStyle(.white)
            .padding(.leading, 1)
    }
}

enum ActionButtonTone {
    case neutral
    case primary
    case danger
}

struct ActionButtonStyle: ButtonStyle {
    let tone: ActionButtonTone
    let isHovered: Bool
    let isEnabled: Bool
    let dense: Bool

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed && isEnabled

        return configuration.label
            .font(.system(size: dense ? 11 : 13, weight: .semibold, design: .rounded))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, dense ? 4 : 12)
            .padding(.vertical, dense ? 2 : 8)
            .frame(minHeight: dense ? 18 : 32)
            .background(
                RoundedRectangle(cornerRadius: dense ? 5 : 9, style: .continuous)
                    .fill(backgroundColor(pressed: pressed))
            )
            .overlay(
                RoundedRectangle(cornerRadius: dense ? 5 : 9, style: .continuous)
                    .stroke(borderColor(pressed: pressed), lineWidth: 1)
            )
            .scaleEffect(pressed ? 0.98 : (isHovered && isEnabled ? 1.02 : 1.0))
            .animation(.easeOut(duration: 0.12), value: pressed)
            .animation(.easeOut(duration: 0.14), value: isHovered)
            .opacity(isEnabled ? 1.0 : 0.45)
    }

    private var foregroundColor: Color {
        switch tone {
        case .neutral:
            return .white.opacity(0.92)
        case .primary:
            return .white
        case .danger:
            return .red.opacity(0.95)
        }
    }

    private func backgroundColor(pressed: Bool) -> Color {
        switch tone {
        case .neutral:
            if pressed { return .white.opacity(0.22) }
            return isHovered ? .white.opacity(0.16) : .white.opacity(0.08)
        case .primary:
            if pressed { return .blue.opacity(0.75) }
            return isHovered ? .blue.opacity(0.62) : .blue.opacity(0.46)
        case .danger:
            if pressed { return .red.opacity(0.26) }
            return isHovered ? .red.opacity(0.20) : .red.opacity(0.12)
        }
    }

    private func borderColor(pressed: Bool) -> Color {
        switch tone {
        case .neutral:
            return pressed ? .white.opacity(0.55) : .white.opacity(isHovered ? 0.44 : 0.20)
        case .primary:
            return pressed ? .blue.opacity(0.95) : .blue.opacity(isHovered ? 0.88 : 0.72)
        case .danger:
            return pressed ? .red.opacity(0.82) : .red.opacity(isHovered ? 0.74 : 0.52)
        }
    }
}

struct ActionButton: View {
    let title: String
    let tone: ActionButtonTone
    let isEnabled: Bool
    let expand: Bool
    let dense: Bool
    let action: () -> Void

    @State private var isHovered = false

    init(
        _ title: String,
        tone: ActionButtonTone = .neutral,
        isEnabled: Bool = true,
        expand: Bool = false,
        dense: Bool = false,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.tone = tone
        self.isEnabled = isEnabled
        self.expand = expand
        self.dense = dense
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Text(title)
                .frame(maxWidth: expand ? .infinity : nil)
        }
        .buttonStyle(ActionButtonStyle(tone: tone, isHovered: isHovered, isEnabled: isEnabled, dense: dense))
        .disabled(!isEnabled)
        .onHover { hover in
            isHovered = hover
        }
    }
}

struct ContentView: View {
    @StateObject private var vm = AppViewModel()
    @State private var draggingColumnID: Int?

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(red: 0.08, green: 0.10, blue: 0.13),
                    Color(red: 0.05, green: 0.06, blue: 0.08)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    SectionHeader(title: "Current Workspace")
                    Card(compact: true, chrome: false) {
                        HStack(spacing: 4) {
                            Text(compactStatus(vm.statusText))
                                .font(.system(size: 11, weight: .medium, design: .rounded))
                                .foregroundStyle(.white.opacity(0.74))
                                .lineLimit(1)
                                .truncationMode(.tail)
                            Spacer()
                            if !vm.liveColumns.isEmpty {
                                ActionButton("End", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                    Task { await vm.stopSession() }
                                }
                                .fixedSize()
                                ActionButton("Force", tone: .danger, isEnabled: !vm.isBusy, dense: true) {
                                    Task { await vm.killSession() }
                                }
                                .fixedSize()
                            }
                            ActionButton("Sync", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                Task { await vm.refreshAll() }
                            }
                            .fixedSize()
                        }

                        if vm.liveColumns.isEmpty {
                            Text("No active columns in tproj-workspace")
                                .font(.system(size: 12, weight: .medium, design: .rounded))
                                .foregroundStyle(.white.opacity(0.68))
                        } else {
                            ForEach(vm.liveColumns) { column in
                                liveColumnRow(column)
                                    .onDrop(
                                        of: [UTType.text],
                                        delegate: ColumnDropDelegate(
                                            targetColumn: column.column,
                                            draggingColumnID: $draggingColumnID,
                                            viewModel: vm
                                        )
                                    )
                            }
                        }
                        ForEach(vm.inactiveProjects) { project in
                            inactiveProjectRow(project)
                        }
                    }

                    SectionHeader(title: "Workspace YAML")
                    Card {
                        HStack(spacing: 0) {
                            ActionButton("Open workspace.yaml", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                                vm.openWorkspaceYAML()
                            }
                            Spacer(minLength: 0)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 4)
                .padding(.top, 4)
            }
            .frame(maxWidth: .infinity)
        }
        .preferredColorScheme(.dark)
        .task {
            vm.onAppear()
        }
        .background(
            WindowAccessor { window in
                window.level = .floating
            }
        )
    }

    private func liveColumnRow(_ column: LiveColumn) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            // Drag handle: only this header row is draggable
            HStack(spacing: 4) {
                Text("#\(column.column)")
                    .font(.system(size: 11, weight: .heavy, design: .monospaced))
                    .foregroundStyle(.white)
                pill(liveHostLabel(column), tint: column.hostLabel == "local" ? .green : .orange)
                Text(columnPrimaryName(column))
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                Spacer()
            }
            .contentShape(Rectangle())
            .opacity(draggingColumnID == column.column ? 0.7 : 1.0)
            .onDrag {
                draggingColumnID = column.column
                return NSItemProvider(object: NSString(string: "\(column.column)"))
            }

            // Buttons: outside onDrag so clicks always work
            HStack(spacing: 1) {
                Spacer()
                ActionButton("Yazi", tone: column.yaziPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleYazi(for: column) }
                }
                .frame(width: 38)
                ActionButton("Term", tone: column.terminalPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleTerminal(for: column) }
                }
                .frame(width: 38)
                ActionButton("Drop", tone: .danger, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.removeColumn(column) }
                }
                .frame(width: 38)
            }
        }
        .padding(2)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color.white.opacity(0.05))
        )
    }

    private func inactiveProjectRow(_ project: WorkspaceProject) -> some View {
        HStack(spacing: 4) {
            pill(project.type == "remote" ? "@\(project.host)" : "lcl",
                 tint: project.type == "remote" ? .orange : .green)
            Text(project.effectiveAlias)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(.white.opacity(0.5))
                .lineLimit(1)
            Spacer()
            ActionButton("Add", tone: .primary, isEnabled: !vm.isBusy, dense: true) {
                Task { await vm.addColumnByAlias(project.effectiveAlias) }
            }
            .frame(width: 34)
        }
        .padding(2)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color.white.opacity(0.02))
        )
    }

    private func compactStatus(_ text: String) -> String {
        if let t = text.split(separator: ": ").last, t.contains(":") {
            return String(t)
        }
        return text
    }

    private func projectPrimaryName(_ project: WorkspaceProject) -> String {
        let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = project.projectName
        if !alias.isEmpty && alias != projectName {
            return alias
        }
        return projectName
    }

    private func projectDetail(_ project: WorkspaceProject) -> String? {
        let alias = project.alias.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = project.projectName
        if project.type == "remote" {
            let host = project.host.trimmingCharacters(in: .whitespacesAndNewlines)
            if !host.isEmpty {
                if !alias.isEmpty && alias != projectName {
                    return "\(projectName) · @\(host)"
                }
                return "@\(host)"
            }
        }
        if !alias.isEmpty && alias != projectName {
            return projectName
        }
        return nil
    }

    private func columnPrimaryName(_ column: LiveColumn) -> String {
        if let exact = vm.workspaceProjects.first(where: { $0.path == column.projectPath }) {
            let alias = exact.alias.trimmingCharacters(in: .whitespacesAndNewlines)
            if !alias.isEmpty && alias != exact.projectName {
                return alias
            }
            return exact.projectName
        }
        return column.projectName
    }

    private func columnMeta(_ column: LiveColumn) -> String? {
        guard column.hostLabel != "local" else {
            return nil
        }
        let host = column.hostLabel.replacingOccurrences(of: "remote@", with: "")
        if host.isEmpty || host == "remote" {
            return "@remote"
        }
        return "@\(host)"
    }

    private func liveHostLabel(_ column: LiveColumn) -> String {
        if let host = columnMeta(column) {
            return host
        }
        return "lcl"
    }

    private func pill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.system(size: 9, weight: .bold, design: .rounded))
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(
                Capsule(style: .circular)
                    .fill(tint.opacity(0.24))
            )
            .foregroundStyle(tint.opacity(0.95))
    }
}

struct WindowAccessor: NSViewRepresentable {
    let onResolve: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            if let window = view.window {
                onResolve(window)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            if let window = nsView.window {
                onResolve(window)
            }
        }
    }
}

struct ColumnDropDelegate: DropDelegate {
    let targetColumn: Int
    @Binding var draggingColumnID: Int?
    let viewModel: AppViewModel

    func dropEntered(info: DropInfo) {
    }

    func performDrop(info: DropInfo) -> Bool {
        defer { draggingColumnID = nil }
        guard let source = draggingColumnID, source != targetColumn else { return false }
        Task {
            await viewModel.moveColumn(from: source, to: targetColumn)
        }
        return true
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }
}

@main
struct TprojApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 200, minHeight: 520, idealHeight: 980, maxHeight: 2200)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 275, height: 980)
        .windowResizability(.contentMinSize)
    }
}
