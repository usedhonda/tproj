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
    var hasRunCommand = false
    var commandRunning = false
    var hidden = false
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
    @Published private(set) var displayName = ""
    @Published private(set) var sidebarWidth: CGFloat = 242
    private var sessions: [String: TerminalSession] = [:]
    private weak var window: NSWindow?
    private var originalOrigin: NSPoint?
    private let dockWidth: CGFloat = 620

    func toggle(projectPath: String, title: String, in mainWindow: NSWindow?) {
        guard FileManager.default.fileExists(atPath: projectPath) else { return }
        if visibleProjectPath == projectPath { hide(); return }
        if visibleProjectPath != nil { hide() }
        guard let session = sessions[projectPath] ?? createSession(path: projectPath) else { return }
        sessions[projectPath] = session
        session.hidden = false
        window = mainWindow ?? NSApp.windows.first(where: { $0.title == "tproj" })
        sidebarWidth = window?.frame.width ?? sidebarWidth
        originalOrigin = window?.frame.origin
        displayName = title
        visibleProjectPath = projectPath
        resizeWindow(expanded: true)
        window?.makeKeyAndOrderFront(nil)
    }

    func hide() {
        guard let path = visibleProjectPath else { return }
        visibleProjectPath = nil
        sessions[path]?.hidden = true
        resizeWindow(expanded: false)
        if let session = sessions[path], session.hasRunCommand && !session.commandRunning {
            release(path: path)
        }
    }

    func end() {
        guard let path = visibleProjectPath else { return }
        hide()
        release(path: path)
    }

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
        if visibleProjectPath == path { hide() }
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
        view.onCommandState = { [weak self, weak session] running, pid in
            guard let self, let session else { return }
            if session.shellPID == nil, let info = TerminalSession.processInfo(pid), info.pbi_ppid == getpid() {
                session.shellPID = pid
                session.shellStartSeconds = info.pbi_start_tvsec
            }
            guard session.shellPID == pid else { return }
            if running { session.hasRunCommand = true }
            session.commandRunning = running
            if !running && session.hidden && session.hasRunCommand { self.release(path: path) }
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
        if session.release() { sessions.removeValue(forKey: path) }
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
            HStack(spacing: 8) {
                Text(controller.displayName)
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(1)
                Spacer()
                Button("Finder") { controller.openFinder() }
                Button("Hide") { controller.hide() }
                Button("End") { controller.end() }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(GhosttyTheme.current.background.opacity(GhosttyTheme.current.appBackgroundOpacity))
            TerminalHostView(controller: controller, path: path)
        }
        .background(GhosttyTheme.current.background.opacity(GhosttyTheme.current.appBackgroundOpacity))
    }
}
