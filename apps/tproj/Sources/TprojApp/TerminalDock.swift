import AppKit
import Darwin
import SwiftTerm
import SwiftUI
import TprojLogic

private final class TrackedTerminalView: LocalProcessTerminalView {
    var marker = ""
    var onCommandState: ((Bool, pid_t) -> Void)?
    private var markerBuffer = Data()

    override func dataReceived(slice: ArraySlice<UInt8>) {
        super.dataReceived(slice: slice)
        markerBuffer.append(contentsOf: slice)
        let prefix = Data("\u{1B}]777;tproj;\(marker);".utf8)
        while let start = markerBuffer.range(of: prefix) {
            let stateStart = start.upperBound
            guard let end = markerBuffer[stateStart...].firstIndex(of: 7) else {
                markerBuffer.removeSubrange(..<start.lowerBound)
                return
            }
            let parts = String(decoding: markerBuffer[stateStart..<end], as: UTF8.self).split(separator: ";")
            if parts.count == 2, (parts[0] == "running" || parts[0] == "idle"), let pid = pid_t(parts[1]) {
                DispatchQueue.main.async { [weak self] in self?.onCommandState?(parts[0] == "running", pid) }
            }
            markerBuffer.removeSubrange(..<markerBuffer.index(after: end))
        }
        if markerBuffer.count > 256 { markerBuffer.removeFirst(markerBuffer.count - 256) }
    }
}

private final class TerminalSession {
    let path: String
    let view: TrackedTerminalView
    let startupDirectory: URL
    var shellPID: pid_t?
    var shellStartSeconds: UInt64?

    init(path: String, view: TrackedTerminalView, startupDirectory: URL) {
        self.path = path
        self.view = view
        self.startupDirectory = startupDirectory
    }

    @discardableResult
    func release() -> Bool {
        if let shellPID, let shellStartSeconds, let info = Self.processInfo(shellPID),
           info.pbi_ppid == getpid(), info.pbi_start_tvsec == shellStartSeconds {
            kill(shellPID, SIGTERM)
            cleanup()
            return true
        }
        // A missing or changed binding is not permission to signal a guessed PID.
        view.send(source: view, data: ArraySlice("exit\n".utf8))
        return false
    }

    func cleanup() { try? FileManager.default.removeItem(at: startupDirectory) }

    static func processInfo(_ pid: pid_t) -> proc_bsdinfo? {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        let read = withUnsafeMutablePointer(to: &info) { proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, $0, size) }
        return read == size ? info : nil
    }
}

@MainActor
final class TerminalDockController: NSObject, ObservableObject, LocalProcessTerminalViewDelegate {
    @Published private(set) var visibleProjectPath: String?
    @Published private(set) var tabPaths: [String] = []
    @Published private(set) var sidebarWidth: CGFloat = 242
    private var sessions: [String: TerminalSession] = [:]
    private var titles: [String: String] = [:]
    private var closingPaths: Set<String> = []
    private weak var window: NSWindow?
    private var originalOrigin: NSPoint?
    private let dockWidth: CGFloat = 620

    func toggle(projectPath: String, title: String, in mainWindow: NSWindow?) {
        guard FileManager.default.fileExists(atPath: projectPath) else { return }
        if tabPaths.contains(projectPath) { closeTab(path: projectPath); return }
        guard !closingPaths.contains(projectPath) else { return }
        guard let session = sessions[projectPath] ?? createSession(path: projectPath) else { return }
        sessions[projectPath] = session
        titles[projectPath] = title
        if !tabPaths.contains(projectPath) { tabPaths.append(projectPath) }
        if visibleProjectPath == nil {
            window = mainWindow ?? NSApp.windows.first(where: { $0.title == "tproj" })
            sidebarWidth = window?.frame.width ?? sidebarWidth
            originalOrigin = window?.frame.origin
            resizeWindow(expanded: true)
        }
        visibleProjectPath = projectPath
        window?.makeKeyAndOrderFront(nil)
    }

    func hide() {
        guard visibleProjectPath != nil else { return }
        visibleProjectPath = nil
        resizeWindow(expanded: false)
    }

    func end() {
        guard let path = visibleProjectPath else { return }
        closeTab(path: path)
    }

    func selectTab(path: String) {
        guard tabPaths.contains(path) else { return }
        visibleProjectPath = path
    }

    func closeTab(path: String) {
        guard let index = tabPaths.firstIndex(of: path) else { return }
        tabPaths.remove(at: index)
        titles.removeValue(forKey: path)
        closingPaths.insert(path)
        if visibleProjectPath == path {
            if tabPaths.isEmpty { hide() }
            else { visibleProjectPath = tabPaths[min(index, tabPaths.count - 1)] }
        }
        release(path: path)
    }

    func title(for path: String) -> String { titles[path] ?? URL(fileURLWithPath: path).lastPathComponent }

    func openFinder() {
        guard let path = visibleProjectPath else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path, isDirectory: true))
    }

    func terminalView(for path: String) -> NSView? { sessions[path]?.view }

    nonisolated func sizeChanged(source: LocalProcessTerminalView, newCols: Int, newRows: Int) {}
    nonisolated func setTerminalTitle(source: LocalProcessTerminalView, title: String) {}
    nonisolated func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}
    nonisolated func processTerminated(source: TerminalView, exitCode: Int32?) {
        Task { @MainActor [weak self] in self?.handleTermination(source: source) }
    }

    private func handleTermination(source: TerminalView) {
        guard let path = sessions.first(where: { $0.value.view === source })?.key else { return }
        if tabPaths.contains(path) { closeTab(path: path) }
        closingPaths.remove(path)
        sessions.removeValue(forKey: path)?.cleanup()
    }

    private func resizeWindow(expanded: Bool) {
        guard let window else { return }
        var frame = window.frame
        frame.size.width = sidebarWidth + (expanded ? dockWidth : 0)
        if expanded {
            let visible = window.screen?.visibleFrame ?? NSScreen.main?.visibleFrame
            if let visible, frame.maxX > visible.maxX {
                frame.origin.x = max(visible.minX, visible.maxX - frame.width)
            }
        } else if let originalOrigin {
            frame.origin = originalOrigin
        }
        window.setFrame(frame, display: true, animate: false)
    }

    private func createSession(path: String) -> TerminalSession? {
        let nonce = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        guard let startup = makeZshStartup(nonce: nonce, projectPath: path) else { return nil }
        let view = TrackedTerminalView(frame: NSRect(x: 0, y: 0, width: dockWidth, height: 520))
        view.nativeForegroundColor = .white
        view.nativeBackgroundColor = NSColor(GhosttyTheme.current.background)
            .withAlphaComponent(GhosttyTheme.current.appBackgroundOpacity)
        view.processDelegate = self
        view.marker = nonce
        let session = TerminalSession(path: path, view: view, startupDirectory: startup)
        view.onCommandState = { [weak session] _, pid in
            guard let session else { return }
            if session.shellPID == nil, let info = TerminalSession.processInfo(pid), info.pbi_ppid == getpid() {
                session.shellPID = pid
                session.shellStartSeconds = info.pbi_start_tvsec
            }
            guard session.shellPID == pid else { return }
        }
        var environment = ProcessInfo.processInfo.environment
        environment["TERM"] = "xterm-256color"
        environment["ZDOTDIR"] = startup.path
        view.startProcess(
            executable: "/bin/zsh",
            args: ["-i"],
            environment: environment.map { "\($0.key)=\($0.value)" }
        )
        return session
    }

    private func makeZshStartup(nonce: String, projectPath: String) -> URL? {
        let original = ProcessInfo.processInfo.environment["ZDOTDIR"] ?? NSHomeDirectory()
        let originalConfig = URL(fileURLWithPath: original).appendingPathComponent(".zshrc").path
        func quote(_ value: String) -> String {
            "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("tproj-term-\(nonce)")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            let script = """
            if [[ -f \(quote(originalConfig)) ]]; then source \(quote(originalConfig)); fi
            builtin cd -- \(quote(projectPath)) || return
            autoload -Uz add-zsh-hook
            _tproj_preexec() { print -n -- $'\\e]777;tproj;\(nonce);running;'"$$"$'\\a' }
            _tproj_precmd() { if [[ -z "$(jobs -p)" ]]; then print -n -- $'\\e]777;tproj;\(nonce);idle;'"$$"$'\\a'; fi }
            add-zsh-hook preexec _tproj_preexec
            add-zsh-hook precmd _tproj_precmd
            """
            try script.write(to: directory.appendingPathComponent(".zshrc"), atomically: true, encoding: .utf8)
            return directory
        } catch {
            try? FileManager.default.removeItem(at: directory)
            return nil
        }
    }

    private func release(path: String) {
        guard let session = sessions[path] else { return }
        if session.release() {
            sessions.removeValue(forKey: path)
            closingPaths.remove(path)
        }
    }
}

private struct TerminalHostView: NSViewRepresentable {
    let controller: TerminalDockController
    let path: String

    func makeNSView(context: Context) -> NSView { NSView() }

    func updateNSView(_ host: NSView, context: Context) {
        guard let terminal = controller.terminalView(for: path) else { return }
        if terminal.superview === host { return }
        host.subviews.forEach { $0.removeFromSuperview() }
        terminal.translatesAutoresizingMaskIntoConstraints = false
        host.addSubview(terminal)
        NSLayoutConstraint.activate([
            terminal.leadingAnchor.constraint(equalTo: host.leadingAnchor),
            terminal.trailingAnchor.constraint(equalTo: host.trailingAnchor),
            terminal.topAnchor.constraint(equalTo: host.topAnchor),
            terminal.bottomAnchor.constraint(equalTo: host.bottomAnchor)
        ])
    }
}

struct TerminalDockView: View {
    @ObservedObject var controller: TerminalDockController
    let path: String

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(controller.tabPaths, id: \.self) { tabPath in
                    let selected = tabPath == path
                    HStack(spacing: 0) {
                        Button { controller.selectTab(path: tabPath) } label: {
                            Text(controller.title(for: tabPath))
                                .font(.system(size: 12, weight: selected ? .semibold : .medium))
                                .foregroundStyle(selected ? GhosttyTheme.current.textPrimary : GhosttyTheme.current.textSecondary)
                                .lineLimit(1)
                                .frame(minWidth: 80, maxWidth: 135, alignment: .leading)
                                .padding(.leading, 9)
                                .frame(height: 32)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        Button { controller.closeTab(path: tabPath) } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 9, weight: .semibold))
                                .frame(width: 26, height: 32)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                        .accessibilityLabel("Close \(controller.title(for: tabPath))")
                    }
                    .frame(height: 32)
                    .background {
                        RoundedRectangle(cornerRadius: 6)
                            .fill(selected ? GhosttyTheme.current.background : GhosttyTheme.current.foreground.opacity(0.06))
                        if selected {
                            GhosttyTheme.current.background
                                .frame(height: 6)
                                .frame(maxHeight: .infinity, alignment: .bottom)
                        }
                    }
                    .overlay(alignment: .top) {
                        if selected {
                            GhosttyTheme.current.accentCyan.frame(height: 2)
                        }
                    }
                }
                Spacer(minLength: 0)
                Button("Finder") { controller.openFinder() }
                Button("Hide") { controller.hide() }
            }
            .font(.system(size: 11, weight: .medium))
            .padding(.horizontal, 8)
            .frame(height: 36, alignment: .bottom)
            .background(GhosttyTheme.current.backgroundLighter.opacity(GhosttyTheme.current.appBackgroundOpacity))
            TerminalHostView(controller: controller, path: path)
                .overlay {
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(GhosttyTheme.current.cardBorder, lineWidth: 1)
                        .allowsHitTesting(false)
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 8)
        }
        .background(GhosttyTheme.current.background.opacity(GhosttyTheme.current.appBackgroundOpacity))
    }
}
