import SwiftUI
import Foundation
import AppKit
import CoreMIDI
import CryptoKit
import UniformTypeIdentifiers
import Darwin
import TprojLogic

extension Notification.Name {
    static let flipSnapSide = Notification.Name("flipSnapSide")
}

// MARK: - tmux target constants

// Session name and dev-window target used across tmux/Process calls (S-D2).
// Values unchanged from the former inline string literals.
enum TmuxTargets {
    static let session = "tproj-workspace"
    static let devWindow = "tproj-workspace:dev"
}

// MARK: - Ghostty Window Tracker

private struct GhosttyWindowInfo {
    let frame: NSRect
    let windowNumber: Int
}

private func currentGhosttyWindowInfo() -> GhosttyWindowInfo? {
    let options: CGWindowListOption = [.excludeDesktopElements, .optionOnScreenOnly]
    guard let list = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
        return nil
    }
    // CG origin is top-left of PRIMARY display; use screens[0] (not .main which follows focus)
    guard let screenHeight = NSScreen.screens.first?.frame.height else { return nil }

    for info in list {
        guard let name = info[kCGWindowOwnerName as String] as? String,
              name == "Ghostty",
              let layer = info[kCGWindowLayer as String] as? Int,
              layer == 0,   // normal windows only (skip menu bar, popups)
              let number = info[kCGWindowNumber as String] as? Int,
              let bounds = info[kCGWindowBounds as String] as? [String: NSNumber],
              let x = bounds["X"],
              let y = bounds["Y"],
              let w = bounds["Width"],
              let h = bounds["Height"] else {
            continue
        }
        let cgX = CGFloat(truncating: x)
        let cgY = CGFloat(truncating: y)
        let cgW = CGFloat(truncating: w)
        let cgH = CGFloat(truncating: h)
        // CG coords (top-left origin) -> Cocoa coords (bottom-left origin)
        let cocoaY = screenHeight - cgY - cgH
        return GhosttyWindowInfo(
            frame: NSRect(x: cgX, y: cocoaY, width: cgW, height: cgH),
            windowNumber: number
        )
    }
    return nil
}

private func currentGhosttyFrame() -> NSRect? {
    currentGhosttyWindowInfo()?.frame
}

private struct PaneBackgroundGrid: Decodable, Equatable {
    var width: Int
    var height: Int

    enum CodingKeys: String, CodingKey {
        case width
        case height
    }

    init(width: Int = 0, height: Int = 0) {
        self.width = width
        self.height = height
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        width = try c.decodeIfPresent(Int.self, forKey: .width) ?? 0
        height = try c.decodeIfPresent(Int.self, forKey: .height) ?? 0
    }
}

private struct PaneBackgroundPadding: Decodable, Equatable {
    var x: Double
    var y: Double

    enum CodingKeys: String, CodingKey {
        case x
        case y
    }

    init(x: Double = 0, y: Double = 0) {
        self.x = x
        self.y = y
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        x = try c.decodeIfPresent(Double.self, forKey: .x) ?? 0
        y = try c.decodeIfPresent(Double.self, forKey: .y) ?? 0
    }
}

private struct PaneBackgroundPane: Identifiable, Decodable, Equatable {
    var paneID: String
    var role: String
    var left: Int
    var top: Int
    var width: Int
    var height: Int
    var imagePath: String
    var opacity: Double
    var isActive: Bool

    var id: String { paneID }

    enum CodingKeys: String, CodingKey {
        case paneID = "pane_id"
        case role
        case left
        case top
        case width
        case height
        case imagePath = "image_path"
        case opacity
        case isActive = "active"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        paneID = try c.decodeIfPresent(String.self, forKey: .paneID) ?? ""
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        left = try c.decodeIfPresent(Int.self, forKey: .left) ?? 0
        top = try c.decodeIfPresent(Int.self, forKey: .top) ?? 0
        width = try c.decodeIfPresent(Int.self, forKey: .width) ?? 0
        height = try c.decodeIfPresent(Int.self, forKey: .height) ?? 0
        imagePath = try c.decodeIfPresent(String.self, forKey: .imagePath) ?? ""
        opacity = try c.decodeIfPresent(Double.self, forKey: .opacity) ?? 0.24
        isActive = try c.decodeIfPresent(Bool.self, forKey: .isActive) ?? false
    }
}

private struct PaneBackgroundManifest: Decodable, Equatable {
    var session: String
    var window: String
    var windowCells: PaneBackgroundGrid
    var clientCells: PaneBackgroundGrid?
    var windowPaddingPx: PaneBackgroundPadding?
    var panes: [PaneBackgroundPane]

    enum CodingKeys: String, CodingKey {
        case session
        case window
        case windowCells = "window_cells"
        case clientCells = "client_cells"
        case windowPaddingPx = "window_padding_px"
        case panes
    }

    init(
        session: String = "",
        window: String = "",
        windowCells: PaneBackgroundGrid = PaneBackgroundGrid(),
        clientCells: PaneBackgroundGrid? = nil,
        windowPaddingPx: PaneBackgroundPadding? = nil,
        panes: [PaneBackgroundPane] = []
    ) {
        self.session = session
        self.window = window
        self.windowCells = windowCells
        self.clientCells = clientCells
        self.windowPaddingPx = windowPaddingPx
        self.panes = panes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        session = try c.decodeIfPresent(String.self, forKey: .session) ?? ""
        window = try c.decodeIfPresent(String.self, forKey: .window) ?? ""
        windowCells = try c.decodeIfPresent(PaneBackgroundGrid.self, forKey: .windowCells) ?? PaneBackgroundGrid()
        clientCells = try c.decodeIfPresent(PaneBackgroundGrid.self, forKey: .clientCells)
        windowPaddingPx = try c.decodeIfPresent(PaneBackgroundPadding.self, forKey: .windowPaddingPx)
        panes = try c.decodeIfPresent([PaneBackgroundPane].self, forKey: .panes) ?? []
    }
}

private struct PaneBackgroundUnderlayView: View {
    let manifest: PaneBackgroundManifest
    private let imageBrightness = 0.025
    private let imageSaturation = 1.04
    private let imageContrast = 0.95
    private let textReadabilityScrim = 0.07
    private let edgeFadePx: CGFloat = 3
    private let activeTopLineHeight: CGFloat = 4

    private var edgeFadeMask: some View {
        VStack(spacing: 0) {
            LinearGradient(
                gradient: Gradient(colors: [.clear, .black]),
                startPoint: .top, endPoint: .bottom
            )
            .frame(height: edgeFadePx)
            Color.black
                .frame(maxHeight: .infinity)
            LinearGradient(
                gradient: Gradient(colors: [.black, .clear]),
                startPoint: .top, endPoint: .bottom
            )
            .frame(height: edgeFadePx)
        }
    }

    @ViewBuilder
    private func activeTopLine(isActive: Bool) -> some View {
        if isActive {
            VStack(spacing: 0) {
                LinearGradient(
                    gradient: Gradient(colors: [
                        Color(red: 0.3, green: 0.98, blue: 1.0).opacity(0.95),
                        Color(red: 0.3, green: 0.98, blue: 1.0).opacity(0.0)
                    ]),
                    startPoint: .top, endPoint: .bottom
                )
                .frame(height: activeTopLineHeight)
                .blendMode(.plusLighter)
                Spacer(minLength: 0)
            }
        } else {
            EmptyView()
        }
    }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.clear
                ForEach(manifest.panes) { pane in
                    if let image = NSImage(contentsOfFile: pane.imagePath) {
                        let rect = paneRect(for: pane, in: geo.size)
                        Image(nsImage: image)
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: rect.width, height: rect.height)
                            .clipped()
                            .brightness(imageBrightness)
                            .saturation(imageSaturation)
                            .contrast(imageContrast)
                            .overlay {
                                Color.black.opacity(textReadabilityScrim)
                            }
                            .mask(edgeFadeMask)
                            .overlay(activeTopLine(isActive: pane.isActive))
                            .opacity(pane.opacity)
                            .position(x: rect.midX, y: rect.midY)
                    }
                }
            }
        }
        .background(Color.clear)
    }

    // macOS native titlebar 相当の chrome 高さ。動的に計算（hardcode 値に賭けない）。
    // Ghostty は `.titled + fullSizeContentView` で contentView 全体に描画するが、terminal grid は
    // titlebar 領域の下から開始する。underlay window は `.borderless` で contentView == frame 全体
    // なので、画像配置を titlebar 分だけ下にオフセットする必要がある。
    private static let titlebarChromeHeight: CGFloat = {
        let contentRect = CGRect(x: 0, y: 0, width: 100, height: 100)
        let frameRect = NSWindow.frameRect(forContentRect: contentRect, styleMask: [.titled])
        return frameRect.height - contentRect.height
    }()

    private func paneRect(for pane: PaneBackgroundPane, in size: CGSize) -> CGRect {
        // pane area 正規化: ペイン占有領域 (topMost..bottomMost / leftMost..rightMost) を
        // underlay contentView 全体から Ghostty chrome (titlebar) を引いた領域に引き伸ばす。
        let fallbackCols = manifest.clientCells?.width ?? manifest.windowCells.width
        let fallbackRows = manifest.clientCells?.height ?? manifest.windowCells.height
        let leftMost = CGFloat(manifest.panes.map { $0.left }.min() ?? 0)
        let topMost = CGFloat(manifest.panes.map { $0.top }.min() ?? 0)
        let rightMost = CGFloat(manifest.panes.map { $0.left + $0.width }.max() ?? fallbackCols)
        let bottomMost = CGFloat(manifest.panes.map { $0.top + $0.height }.max() ?? fallbackRows)
        let paneAreaCols = max(rightMost - leftMost, 1)
        let paneAreaRows = max(bottomMost - topMost, 1)

        let padX = CGFloat(manifest.windowPaddingPx?.x ?? 0)
        let padY = CGFloat(manifest.windowPaddingPx?.y ?? 0)
        let chromeTop = Self.titlebarChromeHeight
        let innerW = max(size.width - 2 * padX, 1)
        let innerH = max(size.height - chromeTop - 2 * padY, 1)

        let x = padX + (CGFloat(pane.left) - leftMost) / paneAreaCols * innerW
        let y = chromeTop + padY + (CGFloat(pane.top) - topMost) / paneAreaRows * innerH
        let width = CGFloat(max(pane.width, 1)) / paneAreaCols * innerW
        let height = CGFloat(max(pane.height, 1)) / paneAreaRows * innerH
        return CGRect(x: x, y: y, width: width, height: height)
    }
}

@MainActor
final class PaneBackgroundUnderlayController: ObservableObject {
    private let manifestPath = "/tmp/tproj-pane-bg/current.json"
    private let fileManager = FileManager.default
    private weak var hostWindow: NSWindow?
    private var underlayWindow: NSWindow?
    private var pollTimer: DispatchSourceTimer?
    private var lastManifestDate: Date?
    private var cachedManifest: PaneBackgroundManifest?
    private var lastGhosttyWindowNumber: Int?

    func attach(to window: NSWindow) {
        guard hostWindow !== window else { return }
        hostWindow = window
        startPolling()
    }

    func detach() {
        stopPolling()
        hideUnderlay()
        hostWindow = nil
    }

    deinit {
        pollTimer?.cancel()
    }

    private func startPolling() {
        guard pollTimer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now(), repeating: .milliseconds(250))
        timer.setEventHandler { [weak self] in
            MainActor.assumeIsolated {
                self?.tick()
            }
        }
        timer.resume()
        pollTimer = timer
    }

    private func stopPolling() {
        pollTimer?.cancel()
        pollTimer = nil
    }

    private func tick() {
        guard hostWindow != nil else {
            hideUnderlay()
            return
        }

        guard GhosttyTheme.current.backgroundOpacity < 1.0 else {
            hideUnderlay()
            return
        }

        guard let ghosttyInfo = currentGhosttyWindowInfo() else {
            hideUnderlay()
            return
        }

        // macOS fullscreen creates an isolated Space where underlay windows
        // cannot appear behind the fullscreen app. Hide gracefully.
        let isFullscreen = NSScreen.screens.contains { screen in
            abs(ghosttyInfo.frame.width - screen.frame.width) < 2 &&
            ghosttyInfo.frame.height >= screen.frame.height * 0.95
        }
        if isFullscreen {
            hideUnderlay()
            return
        }

        guard let manifest = loadManifest(),
              manifest.windowCells.width > 0,
              manifest.windowCells.height > 0 else {
            hideUnderlay()
            return
        }

        let usablePanes = manifest.panes.filter {
            !$0.imagePath.isEmpty && fileManager.fileExists(atPath: $0.imagePath)
        }
        guard !usablePanes.isEmpty else {
            hideUnderlay()
            return
        }

        let filteredManifest = PaneBackgroundManifest(
            session: manifest.session,
            window: manifest.window,
            windowCells: manifest.windowCells,
            clientCells: manifest.clientCells,
            windowPaddingPx: manifest.windowPaddingPx,
            panes: usablePanes
        )

        let window = ensureUnderlayWindow()
        window.setFrame(ghosttyInfo.frame, display: true)
        updateContent(of: window, manifest: filteredManifest)
        window.order(.below, relativeTo: ghosttyInfo.windowNumber)
        lastGhosttyWindowNumber = ghosttyInfo.windowNumber
    }

    private func loadManifest() -> PaneBackgroundManifest? {
        guard let attrs = try? fileManager.attributesOfItem(atPath: manifestPath),
              let modifiedAt = attrs[.modificationDate] as? Date else {
            cachedManifest = nil
            lastManifestDate = nil
            return nil
        }

        if let cachedManifest, let lastManifestDate, lastManifestDate == modifiedAt {
            return cachedManifest
        }

        guard let data = try? Data(contentsOf: URL(fileURLWithPath: manifestPath)),
              let manifest = try? JSONDecoder().decode(PaneBackgroundManifest.self, from: data) else {
            cachedManifest = nil
            lastManifestDate = modifiedAt
            return nil
        }

        cachedManifest = manifest
        lastManifestDate = modifiedAt
        return manifest
    }

    private func ensureUnderlayWindow() -> NSWindow {
        if let underlayWindow {
            return underlayWindow
        }

        let window = NSWindow(
            contentRect: .zero,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.level = .normal
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        underlayWindow = window
        return window
    }

    private func updateContent(of window: NSWindow, manifest: PaneBackgroundManifest) {
        let view = PaneBackgroundUnderlayView(manifest: manifest)
        if let hosting = window.contentView as? NSHostingView<PaneBackgroundUnderlayView> {
            hosting.rootView = view
        } else {
            let hosting = NSHostingView(rootView: view)
            hosting.wantsLayer = true
            hosting.layer?.backgroundColor = NSColor.clear.cgColor
            window.contentView = hosting
        }
    }

    private func hideUnderlay() {
        cachedManifest = nil
        lastManifestDate = nil
        lastGhosttyWindowNumber = nil
        underlayWindow?.orderOut(nil)
    }
}

private enum SnapEdge {
    case right   // tproj is to the right of Ghostty
    case left    // tproj is to the left of Ghostty
}

// Proxy that intercepts windowWillResize to lock width while snapped to Ghostty.
// All other delegate calls are forwarded to the original SwiftUI-owned delegate.
@MainActor
final class SnapResizeProxy: NSObject, NSWindowDelegate {
    weak var original: (any NSWindowDelegate)?
    weak var tracker: GhosttyWindowTracker?

    func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
        let proposed = original?.windowWillResize?(sender, to: frameSize) ?? frameSize
        guard let tracker = tracker, tracker.isSnapped else { return proposed }

        // When snapped, make corners ungrabbable (block diagonal resize entirely)
        let mouse = sender.mouseLocationOutsideOfEventStream
        let frame = sender.frame
        let cornerSize: CGFloat = 80
        let nearLeft   = mouse.x < cornerSize
        let nearRight  = mouse.x > frame.width - cornerSize
        let nearBottom = mouse.y < cornerSize
        let nearTop    = mouse.y > frame.height - cornerSize
        let isCorner = (nearLeft || nearRight) && (nearBottom || nearTop)

        if isCorner {
            return frame.size
        }
        return proposed
    }

    override func responds(to aSelector: Selector!) -> Bool {
        if super.responds(to: aSelector) { return true }
        return original?.responds(to: aSelector) ?? false
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? {
        if let orig = original, (orig as AnyObject).responds(to: aSelector) {
            return orig
        }
        return super.forwardingTarget(for: aSelector)
    }
}

@MainActor
final class GhosttyWindowTracker: ObservableObject {
    @Published var isSnapped = false
    @Published var isDragSuspended = false
    var suspendDriftDetection = false

    private var pollTimer: DispatchSourceTimer?
    private weak var appWindow: NSWindow?
    private var resizeProxy: SnapResizeProxy?

    private let snapThreshold: CGFloat = 12
    private let snapYAlignThreshold: CGFloat = 100
    private let snapGap: CGFloat = 2
    private var snapEdge: SnapEdge = .right
    private var lastGhosttyFrame: CGRect?
    // After detach, suppress re-snap for a short period
    private var detachCooldownUntil: Date?

    func attach(to window: NSWindow) {
        guard appWindow !== window else { return }
        detach()
        appWindow = window
        // Install delegate proxy to intercept resize while snapped
        let proxy = SnapResizeProxy()
        proxy.original = window.delegate
        proxy.tracker = self
        resizeProxy = proxy
        window.delegate = proxy
        startPolling()
    }

    func detach() {
        stopPolling()
        // Restore original delegate before releasing the proxy
        if let proxy = resizeProxy, let window = appWindow {
            window.delegate = proxy.original
        }
        resizeProxy = nil
        appWindow = nil
        isSnapped = false
        lastGhosttyFrame = nil
        detachCooldownUntil = nil
    }

    func flipSide() {
        guard let window = appWindow, let ghosttyFrame = findGhosttyFrame(), isSnapped else { return }
        snapEdge = (snapEdge == .right) ? .left : .right
        let target = anchoredOrigin(for: ghosttyFrame, windowSize: window.frame.size, preferredSide: snapEdge)
        window.setFrameOrigin(target.origin)
        snapEdge = target.side
        lastGhosttyFrame = ghosttyFrame
    }

    deinit {
        pollTimer?.cancel()
    }

    // MARK: Polling

    private func startPolling() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now(), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in
            MainActor.assumeIsolated {
                self?.tick()
            }
        }
        timer.resume()
        pollTimer = timer
    }

    private func stopPolling() {
        pollTimer?.cancel()
        pollTimer = nil
    }

    private func updatePollingInterval() {
        guard let timer = pollTimer else { return }
        let ms: Int
        if isSnapped {
            ms = 16      // 60 fps – smooth follow
        } else if lastGhosttyFrame != nil {
            ms = 100     // Ghostty visible – snap detection
        } else {
            ms = 500     // Ghostty absent – minimal resource
        }
        timer.schedule(deadline: .now() + .milliseconds(ms), repeating: .milliseconds(ms))
    }

    private func visibleUnionFrame() -> CGRect? {
        let frames = NSScreen.screens.map { $0.visibleFrame }
        guard var union = frames.first else { return nil }
        for frame in frames.dropFirst() {
            union = union.union(frame)
        }
        return union
    }

    private func clampedOrigin(_ origin: CGPoint, windowSize: CGSize) -> CGPoint {
        guard let union = visibleUnionFrame() else { return origin }
        let maxX = max(union.minX, union.maxX - windowSize.width)
        let maxY = max(union.minY, union.maxY - windowSize.height)
        return CGPoint(
            x: min(max(origin.x, union.minX), maxX),
            y: min(max(origin.y, union.minY), maxY)
        )
    }

    private func nearlyEqual(_ lhs: CGPoint, _ rhs: CGPoint) -> Bool {
        abs(lhs.x - rhs.x) < 0.5 && abs(lhs.y - rhs.y) < 0.5
    }

    // MARK: Anchored origin (anchor-based direct calculation)

    private func anchoredOrigin(
        for ghosttyFrame: CGRect,
        windowSize: CGSize,
        preferredSide: SnapEdge?
    ) -> (origin: CGPoint, side: SnapEdge) {
        let candidateScreen = NSScreen.screens.first(where: { $0.frame.intersects(ghosttyFrame) })
            ?? NSScreen.main ?? NSScreen.screens.first
        let visibleFrame = candidateScreen?.visibleFrame

        let rightX = ghosttyFrame.maxX + snapGap
        let leftX = ghosttyFrame.minX - windowSize.width - snapGap
        let y = ghosttyFrame.maxY - windowSize.height  // always top-align

        let fitsRight = visibleFrame.map { rightX + windowSize.width <= $0.maxX - 0.5 } ?? true
        let fitsLeft = visibleFrame.map { leftX >= $0.minX + 0.5 } ?? true

        var side = preferredSide ?? (fitsRight ? .right : .left)
        if side == .right && !fitsRight && fitsLeft { side = .left }
        else if side == .left && !fitsLeft && fitsRight { side = .right }

        let x = (side == .right) ? rightX : leftX
        let clamped = clampedOrigin(CGPoint(x: x, y: y), windowSize: windowSize)
        return (CGPoint(x: round(clamped.x), y: round(clamped.y)), side)
    }

    // MARK: Main loop

    private func tick() {
        guard let window = appWindow else { return }
        let currentOrigin = window.frame.origin
        let guardedOrigin = clampedOrigin(currentOrigin, windowSize: window.frame.size)
        if !nearlyEqual(currentOrigin, guardedOrigin) {
            window.setFrameOrigin(guardedOrigin)
        }

        guard let ghosttyFrame = findGhosttyFrame() else {
            let changed = isSnapped || lastGhosttyFrame != nil
            if isSnapped { isSnapped = false }
            lastGhosttyFrame = nil
            if changed { updatePollingInterval() }
            return
        }

        let prevSnapped = isSnapped
        let currentFrame = window.frame
        let target = anchoredOrigin(
            for: ghosttyFrame,
            windowSize: currentFrame.size,
            preferredSide: snapEdge
        )


        if isSnapped {
            if suspendDriftDetection {
                lastGhosttyFrame = ghosttyFrame
                return
            }

            if isDragSuspended {
                let dragPB = NSPasteboard(name: .drag)
                if dragPB.types == nil || dragPB.types?.isEmpty == true {
                    isDragSuspended = false
                } else {
                    lastGhosttyFrame = ghosttyFrame
                    return
                }
            }

            // Detach by X-only (Y movement never triggers detach)
            let xDrift = abs(currentOrigin.x - target.origin.x)
            let ghostMotion: CGFloat
            if let last = lastGhosttyFrame {
                ghostMotion = hypot(ghosttyFrame.origin.x - last.origin.x,
                                    ghosttyFrame.origin.y - last.origin.y)
            } else {
                ghostMotion = 0
            }

            if xDrift >= snapThreshold * 2 && ghostMotion < 2 {
                isSnapped = false
                detachCooldownUntil = Date().addingTimeInterval(0.4)
            } else {
                snapEdge = target.side
                let topGap = abs(currentFrame.maxY - ghosttyFrame.maxY)
                let snapY = (topGap <= snapYAlignThreshold)
                    ? target.origin.y       // top-align
                    : currentOrigin.y       // keep current Y
                let followOrigin = CGPoint(x: target.origin.x, y: snapY)
                if !nearlyEqual(currentOrigin, followOrigin) {
                    window.setFrameOrigin(followOrigin)
                }
            }
        } else {
            // Cooldown after detach
            if let cooldownEnd = detachCooldownUntil {
                if Date() < cooldownEnd {
                    lastGhosttyFrame = ghosttyFrame
                    return
                }
                detachCooldownUntil = nil
            }

            checkAndSnap(appFrame: currentFrame, ghosttyFrame: ghosttyFrame)
        }

        lastGhosttyFrame = ghosttyFrame
        if isSnapped != prevSnapped {
            updatePollingInterval()
        }
    }

    // MARK: Snap logic

    private func checkAndSnap(appFrame: NSRect, ghosttyFrame: NSRect) {
        let leftToRight = abs(appFrame.minX - ghosttyFrame.maxX)
        let rightToLeft = abs(appFrame.maxX - ghosttyFrame.minX)
        let yOverlap = appFrame.maxY > ghosttyFrame.minY && appFrame.minY < ghosttyFrame.maxY

        guard yOverlap else { return }
        guard leftToRight <= snapThreshold || rightToLeft <= snapThreshold else { return }

        snapEdge = leftToRight <= rightToLeft ? .right : .left
        let snapTarget = anchoredOrigin(for: ghosttyFrame, windowSize: appFrame.size, preferredSide: snapEdge)
        let topGap = abs(appFrame.maxY - ghosttyFrame.maxY)
        let snapOrigin = (topGap <= snapYAlignThreshold)
            ? snapTarget.origin
            : CGPoint(x: snapTarget.origin.x, y: appFrame.origin.y)
        appWindow?.setFrameOrigin(snapOrigin)
        snapEdge = snapTarget.side
        isSnapped = true
    }

    // MARK: Snap state recalculation (called after collapse/expand animation)

    func updateSnapOffset() {
        guard let window = appWindow, let ghosttyFrame = findGhosttyFrame(), isSnapped else { return }
        // anchoredOrigin computes position directly; just update lastGhosttyFrame
        lastGhosttyFrame = ghosttyFrame
        // Re-snap to correct position after size change
        let target = anchoredOrigin(for: ghosttyFrame, windowSize: window.frame.size, preferredSide: snapEdge)
        let topGap = abs(window.frame.maxY - ghosttyFrame.maxY)
        let followOrigin = (topGap <= snapYAlignThreshold)
            ? target.origin
            : CGPoint(x: target.origin.x, y: window.frame.origin.y)
        window.setFrameOrigin(followOrigin)
        snapEdge = target.side
    }

    // MARK: Ghostty window discovery

    private func findGhosttyFrame() -> NSRect? {
        currentGhosttyFrame()
    }
}

// MARK: - Window Collapse Controller

@MainActor
final class WindowCollapseController: ObservableObject {
    @Published var isCollapsed = false
    private weak var window: NSWindow?
    private var normalWidth: CGFloat = 275
    private var normalOrigin: NSPoint = .zero
    static let collapsedWidth: CGFloat = 14

    func attach(to window: NSWindow) {
        self.window = window
        // Detect collapsed state restored by macOS
        if !isCollapsed && window.frame.width <= Self.collapsedWidth {
            isCollapsed = true
            window.isMovable = false
            window.isMovableByWindowBackground = false
            setTrafficLightsHidden(true)
        }
    }

    func toggle(ghosttyTracker: GhosttyWindowTracker) {
        if isCollapsed {
            expand(ghosttyTracker: ghosttyTracker)
        } else {
            collapse(ghosttyTracker: ghosttyTracker)
        }
    }

    private func shouldAnchorLeft(window: NSWindow) -> Bool {
        guard let ghostty = currentGhosttyFrame() else { return false }
        return abs(window.frame.minX - ghostty.maxX) < abs(window.frame.maxX - ghostty.minX)
    }

    private func setTrafficLightsHidden(_ hidden: Bool) {
        guard let window = window else { return }
        for buttonType: NSWindow.ButtonType in [.closeButton, .miniaturizeButton, .zoomButton] {
            window.standardWindowButton(buttonType)?.isHidden = hidden
        }
    }

    private func collapse(ghosttyTracker: GhosttyWindowTracker) {
        guard let window = window else { return }
        normalWidth = window.frame.width
        normalOrigin = window.frame.origin
        ghosttyTracker.suspendDriftDetection = true

        let targetWidth = Self.collapsedWidth
        window.minSize = NSSize(width: targetWidth, height: window.minSize.height)

        let ghostty = currentGhosttyFrame()
        let anchorLeft = shouldAnchorLeft(window: window)

        // X: stick to Ghostty's nearest edge
        let newX: CGFloat
        if let g = ghostty {
            newX = anchorLeft ? g.maxX : g.minX - targetWidth
        } else {
            newX = anchorLeft ? window.frame.origin.x : window.frame.maxX - targetWidth
        }
        // Y: align with Ghostty (top-align if similar height, keep current Y otherwise)
        let snapYAlignThreshold: CGFloat = 100
        let newY: CGFloat
        if let g = ghostty {
            let heightDiff = g.height - window.frame.height
            if heightDiff <= snapYAlignThreshold {
                newY = g.maxY - window.frame.height  // top-align
            } else {
                newY = window.frame.origin.y          // keep current Y
            }
        } else {
            newY = window.frame.origin.y
        }

        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.2
            ctx.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            let newOrigin = NSPoint(x: newX, y: newY)
            let newFrame = NSRect(origin: newOrigin, size: NSSize(width: targetWidth, height: window.frame.height))
            window.animator().setFrame(newFrame, display: true)
        }, completionHandler: { [weak self] in
            DispatchQueue.main.async {
                ghosttyTracker.updateSnapOffset()
                ghosttyTracker.suspendDriftDetection = false
                self?.setTrafficLightsHidden(true)
                window.isMovable = false
                window.isMovableByWindowBackground = false
                self?.isCollapsed = true
            }
        })
    }

    private func expand(ghosttyTracker: GhosttyWindowTracker) {
        guard let window = window else { return }
        ghosttyTracker.suspendDriftDetection = true

        let targetWidth = normalWidth

        // Fallback: compute origin from Ghostty frame when normalOrigin was not saved
        if normalOrigin == .zero, let g = currentGhosttyFrame() {
            normalOrigin = NSPoint(x: g.minX - targetWidth, y: g.maxY - window.frame.height)
        }

        setTrafficLightsHidden(false)
        window.isMovable = true
        window.isMovableByWindowBackground = true

        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.2
            ctx.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            let newFrame = NSRect(origin: normalOrigin, size: NSSize(width: targetWidth, height: window.frame.height))
            window.animator().setFrame(newFrame, display: true)
        }, completionHandler: { [weak self] in
            DispatchQueue.main.async {
                window.minSize = NSSize(width: 200, height: window.minSize.height)
                ghosttyTracker.updateSnapOffset()
                ghosttyTracker.suspendDriftDetection = false
                self?.isCollapsed = false
            }
        })
    }
}

@MainActor
final class WindowLevelController: ObservableObject {
    private weak var appWindow: NSWindow?
    private var activationObserver: NSObjectProtocol?
    private var lastAppliedLevel: NSWindow.Level?

    private let ghosttyBundleID = "com.mitchellh.ghostty"

    init() {
        activationObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            let bundleID = app?.bundleIdentifier
            Task { @MainActor [weak self] in
                self?.applyWindowLevel(frontmostBundleID: bundleID)
            }
        }
    }

    deinit {
        if let activationObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(activationObserver)
        }
    }

    func attach(to window: NSWindow) {
        if appWindow !== window {
            appWindow = window
            lastAppliedLevel = nil
        }
        applyWindowLevel(frontmostBundleID: NSWorkspace.shared.frontmostApplication?.bundleIdentifier)
    }

    private func applyWindowLevel(frontmostBundleID: String?) {
        guard let window = appWindow else { return }
        let desiredLevel: NSWindow.Level = (frontmostBundleID == ghosttyBundleID) ? .floating : .normal
        guard desiredLevel != lastAppliedLevel else { return }
        window.level = desiredLevel
        lastAppliedLevel = desiredLevel
    }
}

// MARK: - Data Models

struct WorkspaceProject: Identifiable {
    let id = UUID()
    var path: String
    var type: String
    var host: String
    var alias: String
    var enabled: Bool
    var lastActiveAt: Int = 0

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

final class WorkspaceYamlWatcher {
    private struct WatchEntry {
        let path: String
        let fileDescriptor: CInt
        let source: DispatchSourceFileSystemObject
    }

    private let paths: [String]
    private let queue = DispatchQueue(label: "tproj.workspace-yaml-watcher")
    private let onChange: () -> Void
    private var entries: [WatchEntry] = []
    private var debounceWork: DispatchWorkItem?

    init(paths: [String], onChange: @escaping () -> Void) {
        self.paths = paths
        self.onChange = onChange
    }

    func start() {
        queue.async { [weak self] in
            guard let self else { return }
            if !self.entries.isEmpty { return }
            self.installWatchers()
        }
    }

    func cancel() {
        queue.async { [weak self] in
            guard let self else { return }
            self.debounceWork?.cancel()
            self.debounceWork = nil
            for entry in self.entries {
                entry.source.cancel()
            }
            self.entries = []
        }
    }

    private func installWatchers() {
        for watchPath in paths {
            installWatcher(for: watchPath)
        }
    }

    private func installWatcher(for watchPath: String) {
        let url = URL(fileURLWithPath: watchPath)
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if !FileManager.default.fileExists(atPath: watchPath),
           url.lastPathComponent == ".tmux-state-sentinel" {
            FileManager.default.createFile(atPath: watchPath, contents: nil)
        }
        guard FileManager.default.fileExists(atPath: watchPath) else { return }

        var fd = open(watchPath, O_EVTONLY)
        if fd < 0 {
            fd = open(watchPath, O_RDONLY)
        }
        guard fd >= 0 else { return }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd,
            eventMask: [.write, .delete, .rename],
            queue: queue
        )
        source.setEventHandler { [weak self] in
            guard let self else { return }
            let flags = source.data
            self.scheduleChange()
            if flags.contains(.delete) || flags.contains(.rename) {
                self.reinstallWatchers()
            }
        }
        source.setCancelHandler {
            close(fd)
        }
        entries.append(WatchEntry(path: watchPath, fileDescriptor: fd, source: source))
        source.resume()
    }

    private func reinstallWatchers() {
        for entry in entries {
            entry.source.cancel()
        }
        entries = []
        queue.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            self?.installWatchers()
        }
    }

    private func scheduleChange() {
        debounceWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.onChange()
        }
        debounceWork = work
        queue.asyncAfter(deadline: .now() + 0.3, execute: work)
    }
}

struct LiveColumn: Identifiable {
    let id = UUID()
    var column: Int
    var projectPath: String
    var hostLabel: String
    var width: Int
    var left: Int
    var claudePaneIDs: [String]
    var codexPaneIDs: [String]
    var agentPaneIDs: [String]
    var agentNames: [String]
    var yaziPaneID: String?
    var terminalPaneID: String?

    var primaryClaudePaneID: String? {
        claudePaneIDs.first
    }

    var primaryCodexPaneID: String? {
        codexPaneIDs.first
    }

    var hasCorePanes: Bool {
        !claudePaneIDs.isEmpty || !codexPaneIDs.isEmpty
    }

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

struct MonitorSystem: Codable {
    var totalMB: Int
    var usedMB: Int
    var freeMB: Int

    enum CodingKeys: String, CodingKey {
        case totalMB = "total_mb"
        case usedMB = "used_mb"
        case freeMB = "free_mb"
    }

    init(totalMB: Int = 0, usedMB: Int = 0, freeMB: Int = 0) {
        self.totalMB = totalMB
        self.usedMB = usedMB
        self.freeMB = freeMB
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        totalMB = try c.decodeIfPresent(Int.self, forKey: .totalMB) ?? 0
        usedMB = try c.decodeIfPresent(Int.self, forKey: .usedMB) ?? 0
        freeMB = try c.decodeIfPresent(Int.self, forKey: .freeMB) ?? 0
    }
}

struct MonitorCategory: Codable {
    var mb: Int
    var count: Int?

    init(mb: Int = 0, count: Int? = nil) {
        self.mb = mb
        self.count = count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mb = try c.decodeIfPresent(Int.self, forKey: .mb) ?? 0
        count = try c.decodeIfPresent(Int.self, forKey: .count)
    }
}

struct MonitorCCProcess: Codable {
    var pid: Int
    var rssMB: Int
    var cpu: Double
    var state: String
    var project: String

    enum CodingKeys: String, CodingKey {
        case pid
        case rssMB = "rss_mb"
        case cpu
        case state
        case project
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pid = try c.decodeIfPresent(Int.self, forKey: .pid) ?? 0
        rssMB = try c.decodeIfPresent(Int.self, forKey: .rssMB) ?? 0
        cpu = try c.decodeIfPresent(Double.self, forKey: .cpu) ?? 0
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
    }
}

struct MonitorPane: Identifiable, Codable {
    var session: String
    var window: String
    var paneID: String
    var paneIndex: Int
    var role: String
    var column: Int?
    var project: String
    var rssMB: Int
    var cpu: Double
    var bucketCMB: Int
    var bucketMMB: Int
    var bucketXMB: Int
    var bucketOMB: Int
    var state: String
    var agentType: String

    var id: String { paneID }

    enum CodingKeys: String, CodingKey {
        case session
        case window
        case paneID = "pane_id"
        case paneIndex = "pane_index"
        case role
        case column
        case project
        case rssMB = "rss_mb"
        case cpu
        case bucketCMB = "bucket_c_mb"
        case bucketMMB = "bucket_m_mb"
        case bucketXMB = "bucket_x_mb"
        case bucketOMB = "bucket_o_mb"
        case state
        case agentType = "agent_type"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        session = try c.decodeIfPresent(String.self, forKey: .session) ?? ""
        window = try c.decodeIfPresent(String.self, forKey: .window) ?? ""
        paneID = try c.decodeIfPresent(String.self, forKey: .paneID) ?? ""
        paneIndex = try c.decodeIfPresent(Int.self, forKey: .paneIndex) ?? -1
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        column = try c.decodeIfPresent(Int.self, forKey: .column)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        rssMB = try c.decodeIfPresent(Int.self, forKey: .rssMB) ?? 0
        cpu = try c.decodeIfPresent(Double.self, forKey: .cpu) ?? 0
        bucketCMB = try c.decodeIfPresent(Int.self, forKey: .bucketCMB) ?? 0
        bucketMMB = try c.decodeIfPresent(Int.self, forKey: .bucketMMB) ?? 0
        bucketXMB = try c.decodeIfPresent(Int.self, forKey: .bucketXMB) ?? 0
        bucketOMB = try c.decodeIfPresent(Int.self, forKey: .bucketOMB) ?? 0
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        agentType = try c.decodeIfPresent(String.self, forKey: .agentType) ?? "other"
    }
}

struct MonitorColumn: Identifiable, Codable {
    var column: Int
    var project: String
    var ccMB: Int
    var codexMB: Int
    var totalMB: Int
    var ccActive: Int
    var codexActive: Int

    var id: Int { column }

    enum CodingKeys: String, CodingKey {
        case column
        case project
        case ccMB = "cc_mb"
        case codexMB = "codex_mb"
        case totalMB = "total_mb"
        case ccActive = "cc_active"
        case codexActive = "codex_active"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        column = try c.decodeIfPresent(Int.self, forKey: .column) ?? 0
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        ccMB = try c.decodeIfPresent(Int.self, forKey: .ccMB) ?? 0
        codexMB = try c.decodeIfPresent(Int.self, forKey: .codexMB) ?? 0
        totalMB = try c.decodeIfPresent(Int.self, forKey: .totalMB) ?? 0
        ccActive = try c.decodeIfPresent(Int.self, forKey: .ccActive) ?? 0
        codexActive = try c.decodeIfPresent(Int.self, forKey: .codexActive) ?? 0
    }
}

struct MonitorCollector: Codable {
    var version: String
    var source: String
    var errors: [String]

    init(version: String = "", source: String = "", errors: [String] = []) {
        self.version = version
        self.source = source
        self.errors = errors
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decodeIfPresent(String.self, forKey: .version) ?? ""
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        errors = try c.decodeIfPresent([String].self, forKey: .errors) ?? []
    }
}

struct MonitorStatus: Codable {
    var timestamp: String
    var system: MonitorSystem
    var categories: [String: MonitorCategory]
    var ccProcesses: [MonitorCCProcess]
    var guardState: String
    var panes: [MonitorPane]
    var columns: [MonitorColumn]
    var collector: MonitorCollector

    enum CodingKeys: String, CodingKey {
        case timestamp
        case system
        case categories
        case ccProcesses = "cc_processes"
        case guardState = "guard"
        case panes
        case columns
        case collector
    }

    init(
        timestamp: String = "",
        system: MonitorSystem = MonitorSystem(),
        categories: [String: MonitorCategory] = [:],
        ccProcesses: [MonitorCCProcess] = [],
        guardState: String = "unknown",
        panes: [MonitorPane] = [],
        columns: [MonitorColumn] = [],
        collector: MonitorCollector = MonitorCollector()
    ) {
        self.timestamp = timestamp
        self.system = system
        self.categories = categories
        self.ccProcesses = ccProcesses
        self.guardState = guardState
        self.panes = panes
        self.columns = columns
        self.collector = collector
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp) ?? ""
        system = try c.decodeIfPresent(MonitorSystem.self, forKey: .system) ?? MonitorSystem()
        categories = try c.decodeIfPresent([String: MonitorCategory].self, forKey: .categories) ?? [:]
        ccProcesses = try c.decodeIfPresent([MonitorCCProcess].self, forKey: .ccProcesses) ?? []
        guardState = try c.decodeIfPresent(String.self, forKey: .guardState) ?? "unknown"
        panes = try c.decodeIfPresent([MonitorPane].self, forKey: .panes) ?? []
        columns = try c.decodeIfPresent([MonitorColumn].self, forKey: .columns) ?? []
        collector = try c.decodeIfPresent(MonitorCollector.self, forKey: .collector) ?? MonitorCollector()
    }
}

private final class MIDIPaneActivator {
    var onStatus: ((String) -> Void)?
    var onLearnStateChanged: ((Bool) -> Void)?
    // Jog wheel (relative CC): +1 = focus next pane, -1 = focus previous pane.
    var onJogStep: ((Int) -> Void)?

    private var client = MIDIClientRef()
    private var inputPort = MIDIPortRef()
    private var connectedSources: [MIDIEndpointRef] = []
    private var isRunning = false
    private var learning = false {
        didSet { onLearnStateChanged?(learning) }
    }
    // Jog-learn state: count consecutive identical CCs while learning.
    private var learnJogChannel: Int?
    private var learnJogCC: Int?
    private var learnJogCount = 0

    // Jog wheel quantizer (relative-CC accumulation + rate limit). Its config is
    // refreshed from the live computed vars before each feed (see handleJog).
    private var jogQuantizer = JogQuantizer(ticksPerStep: 30, minStepInterval: 0.15)

    // Jog config (UserDefaults, standard suite). object(forKey:) != nil check so a
    // missing key falls back to the documented default rather than 0.
    private func intDefault(_ key: String, _ fallback: Int) -> Int {
        UserDefaults.standard.object(forKey: key) == nil ? fallback : UserDefaults.standard.integer(forKey: key)
    }
    private func doubleDefault(_ key: String, _ fallback: Double) -> Double {
        UserDefaults.standard.object(forKey: key) == nil ? fallback : UserDefaults.standard.double(forKey: key)
    }
    private var jogChannel: Int { intDefault("tproj.midi.jog.channel", 0) }
    private var jogCC: Int { intDefault("tproj.midi.jog.cc", 6) }
    private var jogTicksPerStep: Int { max(1, intDefault("tproj.midi.jog.ticksPerStep", 30)) }
    private var jogMinStepInterval: Double { doubleDefault("tproj.midi.jog.minStepInterval", 0.15) }

    var isLearning: Bool { learning }

    func start() {
        guard !isRunning else { return }

        var createdClient = MIDIClientRef()
        let clientStatus = MIDIClientCreateWithBlock("tproj-midi-client" as CFString, &createdClient) { [weak self] notification in
            guard notification.pointee.messageID == .msgSetupChanged else { return }
            self?.reconnectSources()
        }
        guard clientStatus == noErr else {
            onStatus?("MIDI init failed (client: \(clientStatus))")
            return
        }
        client = createdClient

        var createdPort = MIDIPortRef()
        let portStatus = MIDIInputPortCreateWithBlock(client, "tproj-midi-input" as CFString, &createdPort) { [weak self] packetList, _ in
            self?.handlePacketList(packetList)
        }
        guard portStatus == noErr else {
            onStatus?("MIDI init failed (port: \(portStatus))")
            MIDIClientDispose(client)
            client = 0
            return
        }
        inputPort = createdPort

        connectSources()
        isRunning = true
        if connectedSources.isEmpty {
            onStatus?("MIDI: no input source found")
        } else {
            onStatus?("MIDI connected (\(connectedSources.count) source)")
        }
    }

    func stop() {
        guard isRunning else { return }
        connectedSources.forEach { MIDIPortDisconnectSource(inputPort, $0) }
        connectedSources.removeAll()
        if inputPort != 0 {
            MIDIPortDispose(inputPort)
            inputPort = 0
        }
        if client != 0 {
            MIDIClientDispose(client)
            client = 0
        }
        learning = false
        isRunning = false
    }

    deinit {
        stop()
    }

    func toggleLearn() -> Bool {
        if learning {
            learning = false
            onStatus?("MIDI Learn canceled")
            return false
        }
        learning = true
        learnJogChannel = nil
        learnJogCC = nil
        learnJogCount = 0
        onStatus?("MIDI Learn: rotate the jog")
        return true
    }

    private func connectSources() {
        connectedSources.removeAll()
        let sourceCount = MIDIGetNumberOfSources()
        if sourceCount == 0 { return }

        var sourceNames: [String] = []
        for i in 0..<sourceCount {
            let source = MIDIGetSource(i)
            guard source != 0 else { continue }
            let name = displayName(for: source) ?? "(unknown)"
            sourceNames.append(name)
            let status = MIDIPortConnectSource(inputPort, source, nil)
            if status == noErr {
                connectedSources.append(source)
            }
        }
        onStatus?("MIDI sources: \(sourceNames.joined(separator: ", "))")
    }

    private func reconnectSources() {
        guard isRunning else { return }
        connectedSources.forEach { MIDIPortDisconnectSource(inputPort, $0) }
        connectedSources.removeAll()
        connectSources()
        if connectedSources.isEmpty {
            onStatus?("MIDI: device disconnected")
        } else {
            onStatus?("MIDI: reconnected (\(connectedSources.count) source)")
        }
    }

    private func handlePacketList(_ packetList: UnsafePointer<MIDIPacketList>) {
        let numPackets = Int(packetList.pointee.numPackets)
        guard numPackets > 0, numPackets < 256 else { return }

        // Get a stable pointer to the first packet inside the packet list
        let firstPktPtr = UnsafeRawPointer(packetList).advanced(
            by: MemoryLayout<UInt32>.size  // skip numPackets field
        ).assumingMemoryBound(to: MIDIPacket.self)

        var pktPtr = firstPktPtr
        for _ in 0..<numPackets {
            let statusByte = pktPtr.pointee.data.0
            let data1 = pktPtr.pointee.data.1
            let data2 = pktPtr.pointee.data.2
            handleMessage(status: statusByte, data1: data1, data2: data2)
            pktPtr = UnsafePointer(MIDIPacketNext(pktPtr))
        }
    }

    private func handleMessage(status: UInt8, data1: UInt8, data2: UInt8) {
        let nibble = status & 0xF0
        // Accept Note On and Control Change. Ignore zero-value (release/off) events.
        guard (nibble == 0x90 || nibble == 0xB0), data2 > 0 else { return }

        let channel = status & 0x0F

        // Jog wheel: relative CC on a dedicated channel/CC. Consume it for focus
        // stepping only when not learning; during learn the matching CC must fall
        // through so the jog can be re-learned.
        if !learning && nibble == 0xB0 && Int(channel) == jogChannel && Int(data1) == jogCC {
            handleJog(data2: data2)
            return
        }

        if learning {
            // Learn the jog wheel: rotation fires the same CC repeatedly, so require
            // the same (channel, data1) CC 8 times in a row before committing. Notes
            // (jog top-touch) and stray one-off knob CCs are thereby ignored.
            guard nibble == 0xB0 else { return }
            let ch = Int(channel)
            let cc = Int(data1)
            if ch == learnJogChannel && cc == learnJogCC {
                learnJogCount += 1
            } else {
                learnJogChannel = ch
                learnJogCC = cc
                learnJogCount = 1
            }
            guard learnJogCount >= 8 else { return }
            UserDefaults.standard.set(ch, forKey: "tproj.midi.jog.channel")
            UserDefaults.standard.set(cc, forKey: "tproj.midi.jog.cc")
            learning = false
            onStatus?("Jog learned: ch\(ch + 1) cc\(cc)")
            return
        }
    }

    private func handleJog(data2: UInt8) {
        // Refresh config from live defaults so a mid-session change is honored,
        // exactly as the former inline computed-var reads did.
        jogQuantizer.ticksPerStep = jogTicksPerStep
        jogQuantizer.minStepInterval = jogMinStepInterval
        if let direction = jogQuantizer.feed(data2: data2, now: Date()) {
            onJogStep?(direction)
        }
    }

    private func displayName(for endpoint: MIDIEndpointRef) -> String? {
        var name: Unmanaged<CFString>?
        let status = MIDIObjectGetStringProperty(endpoint, kMIDIPropertyDisplayName, &name)
        guard status == noErr, let retained = name?.takeRetainedValue() else {
            return nil
        }
        return retained as String
    }
}

@MainActor
final class AppViewModel: ObservableObject {
    @Published var workspaceProjects: [WorkspaceProject] = []
    @Published var liveColumns: [LiveColumn] = []
    @Published var selectedAlias: String = ""
    @Published var statusText: String = "Ready"
    @Published var isBusy: Bool = false
    @Published var isMIDILearning: Bool = false
    @Published var memoryStatus: MonitorStatus?
    @Published var memoryErrorText: String?
    @Published var memoryLastUpdatedAt: Date?
    @Published var pendingDropColumns: Set<Int> = []
    @Published var pendingSessionAction: SessionAction? = nil

    enum SessionAction {
        case stop
        var title: String { "Stop Session" }
        var message: String { "All panes will be stopped." }
    }

    private let fileManager = FileManager.default
    private let monitorStatusPath = "/tmp/tproj-monitor-status.json"
    private let layoutLogPath = "/tmp/tproj-layout-actions.log"
    private var memoryPollTask: Task<Void, Never>?
    private var workspaceWatcher: WorkspaceYamlWatcher?

    // MARK: - PATH & Dependency Resolution

    nonisolated private static let builtinExtraPaths: [String] = {
        let home = NSHomeDirectory()
        return [
            "\(home)/bin",
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
        ]
    }()

    nonisolated(unsafe) private static var resolvedPATH: String = buildPATH(extraPaths: [])

    nonisolated private static func buildPATH(extraPaths: [String]) -> String {
        let all = builtinExtraPaths + extraPaths
        let existing = ProcessInfo.processInfo.environment["PATH"]
            ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        let existingSet = Set(existing.split(separator: ":").map(String.init))
        let extras = all.filter { !existingSet.contains($0) }
        return (extras + [existing]).joined(separator: ":")
    }
    private var midiActivator: MIDIPaneActivator?
    private var startupRetryTask: Task<Void, Never>?
    private var layoutMutationInProgress = false
    private var dropTasks: [Int: Task<Void, Never>] = [:]

    struct StartupDiag {
        struct Dep {
            let name: String
            let hint: String
            let found: Bool
            let required: Bool
        }
        let deps: [Dep]
        let sessionExists: Bool
        let yamlExists: Bool
        var hasCriticalMissing: Bool { deps.contains { $0.required && !$0.found } }
    }

    @Published var startupDiag: StartupDiag?

    var workspacePath: String {
        let home = NSHomeDirectory()
        return "\(home)/.config/tproj/workspace.yaml"
    }

    private var tmuxStateSentinelPath: String {
        let home = NSHomeDirectory()
        return "\(home)/.config/tproj/.tmux-state-sentinel"
    }

    private var bundledRuntimeSeedName: String { "tproj-runtime-seed" }

    private var appSupportRootURL: URL {
        fileManager.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/tproj", isDirectory: true)
    }

    private var stagedRuntimeRootURL: URL {
        appSupportRootURL.appendingPathComponent("runtime/current", isDirectory: true)
    }

    private var stagedRuntimeHashURL: URL {
        stagedRuntimeRootURL.appendingPathComponent(".seed-sha256", isDirectory: false)
    }

    var canAddColumn: Bool {
        !selectedAlias.isEmpty && !isBusy
    }

    func isDropPending(_ column: Int) -> Bool {
        pendingDropColumns.contains(column)
    }

    var inactiveProjects: [WorkspaceProject] {
        let livePaths = Set(liveColumns.map { $0.projectPath })
        return workspaceProjects
            .filter { !livePaths.contains($0.path) }
            .sorted { lhs, rhs in
                if lhs.lastActiveAt != rhs.lastActiveAt {
                    return lhs.lastActiveAt > rhs.lastActiveAt
                }
                return lhs.effectiveAlias.localizedCaseInsensitiveCompare(rhs.effectiveAlias) == .orderedAscending
            }
    }

    private struct PaneInfo {
        var paneID: String
        var role: String
        var column: Int?
    }

    // MARK: - GUI Config & Dependency Check

    private func bundledRuntimeSeedURL() -> URL? {
        Bundle.main.url(forResource: bundledRuntimeSeedName, withExtension: "tar.gz")
    }

    private func runtimeSeedDigest(for url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private func ensureBundledRuntimeStaged(reportError: Bool) -> String? {
        guard let seedURL = bundledRuntimeSeedURL() else { return nil }
        guard let digest = runtimeSeedDigest(for: seedURL) else {
            if reportError {
                statusText = "Runtime seed digest failed"
            }
            return nil
        }

        let runtimeBin = stagedRuntimeRootURL.appendingPathComponent("bin/tproj", isDirectory: false)
        if fileManager.isExecutableFile(atPath: runtimeBin.path),
           let existingDigest = try? String(contentsOf: stagedRuntimeHashURL, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines),
           existingDigest == digest {
            return stagedRuntimeRootURL.path
        }

        let runtimeParent = appSupportRootURL.appendingPathComponent("runtime", isDirectory: true)
        let stageURL = runtimeParent.appendingPathComponent("stage-\(UUID().uuidString)", isDirectory: true)
        let nextURL = runtimeParent.appendingPathComponent("current.next-\(UUID().uuidString)", isDirectory: true)
        let backupURL = runtimeParent.appendingPathComponent("current.prev-\(UUID().uuidString)", isDirectory: true)

        do {
            try fileManager.createDirectory(at: runtimeParent, withIntermediateDirectories: true)
            if fileManager.fileExists(atPath: stageURL.path) {
                try fileManager.removeItem(at: stageURL)
            }
            try fileManager.createDirectory(at: stageURL, withIntermediateDirectories: true)

            let extractResult = runCommand("/usr/bin/env", ["tar", "-xzf", seedURL.path, "-C", stageURL.path])
            guard extractResult.exitCode == 0 else {
                if reportError {
                    statusText = "Runtime extract failed: \(trimmedError(extractResult))"
                }
                try? fileManager.removeItem(at: stageURL)
                return nil
            }

            let extractedRoot = stageURL.appendingPathComponent("tproj-runtime", isDirectory: true)
            guard fileManager.fileExists(atPath: extractedRoot.path) else {
                if reportError {
                    statusText = "Runtime extract missing payload"
                }
                try? fileManager.removeItem(at: stageURL)
                return nil
            }

            if fileManager.fileExists(atPath: nextURL.path) {
                try fileManager.removeItem(at: nextURL)
            }
            try fileManager.moveItem(at: extractedRoot, to: nextURL)
            try digest.write(to: nextURL.appendingPathComponent(".seed-sha256"), atomically: true, encoding: .utf8)

            if fileManager.fileExists(atPath: stagedRuntimeRootURL.path) {
                if fileManager.fileExists(atPath: backupURL.path) {
                    try fileManager.removeItem(at: backupURL)
                }
                try fileManager.moveItem(at: stagedRuntimeRootURL, to: backupURL)
            }

            try fileManager.moveItem(at: nextURL, to: stagedRuntimeRootURL)
            try? fileManager.removeItem(at: backupURL)
            try? fileManager.removeItem(at: stageURL)
            return stagedRuntimeRootURL.path
        } catch {
            try? fileManager.removeItem(at: stageURL)
            try? fileManager.removeItem(at: nextURL)
            if reportError {
                statusText = "Runtime stage failed: \(error.localizedDescription)"
            }
            return nil
        }
    }

    private func bundledRuntimeCommand(commandName: String) -> String? {
        guard bundledRuntimeSeedURL() != nil else { return nil }
        guard let runtimeRoot = ensureBundledRuntimeStaged(reportError: false) else { return nil }
        let candidate = URL(fileURLWithPath: runtimeRoot, isDirectory: true)
            .appendingPathComponent("bin/\(commandName)", isDirectory: false).path
        return fileManager.isExecutableFile(atPath: candidate) ? candidate : nil
    }

    private func resolveCommandPath(commandName: String) -> String? {
        if let bundled = bundledRuntimeCommand(commandName: commandName) {
            return bundled
        }
        if bundledRuntimeSeedURL() != nil {
            return nil
        }
        if let repoCommand = locateInAncestorBin(commandName: commandName) {
            return repoCommand
        }
        let homeCommand = "\(NSHomeDirectory())/bin/\(commandName)"
        if fileManager.isExecutableFile(atPath: homeCommand) {
            return homeCommand
        }
        return nil
    }

    private func runtimeLaunchCommand(commandName: String, arguments: [String]) -> (launchPath: String, arguments: [String])? {
        guard let path = resolveCommandPath(commandName: commandName) else { return nil }
        return (path, arguments)
    }

    private func fallbackLaunchCommand(commandName: String, arguments: [String]) -> (launchPath: String, arguments: [String])? {
        guard bundledRuntimeSeedURL() == nil else { return nil }
        return ("/usr/bin/env", [commandName] + arguments)
    }

    private func loadGUIConfig() {
        // Try reading gui.extra_paths from workspace.yaml using yq on builtin PATH
        let result = runCommand("/usr/bin/env", ["yq", "-r",
            ".gui.extra_paths[]? // empty", workspacePath])
        if result.exitCode == 0 {
            let paths = result.stdout
                .split(separator: "\n", omittingEmptySubsequences: true)
                .map(String.init)
                .filter { !$0.isEmpty }
            if !paths.isEmpty {
                Self.resolvedPATH = Self.buildPATH(extraPaths: paths)
            }
        }
    }

    private func checkDependencies() -> StartupDiag {
        // Load custom dependencies from workspace.yaml, or use builtin defaults
        var depDefs: [(name: String, required: Bool, hint: String)] = []

        let depResult = runCommand("/usr/bin/env", ["yq", "-r",
            ".gui.dependencies[]? | [.name, (.required // true | tostring), (.hint // \"\")] | @tsv",
            workspacePath])
        if depResult.exitCode == 0 && !depResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            for line in depResult.stdout.split(separator: "\n", omittingEmptySubsequences: true) {
                let parts = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
                if parts.count >= 3 {
                    depDefs.append((name: parts[0], required: parts[1].lowercased() == "true", hint: parts[2]))
                }
            }
        }

        // Builtin defaults if YAML had nothing
        if depDefs.isEmpty {
            depDefs = [
                (name: "tmux", required: true, hint: "brew install tmux"),
                (name: "yq", required: false, hint: "brew install yq"),
            ]
        }

        // Search PATH directories for each dependency
        let pathDirs = Self.resolvedPATH.split(separator: ":").map(String.init)
        var deps: [StartupDiag.Dep] = []
        for def in depDefs {
            let found = pathDirs.contains { dir in
                fileManager.isExecutableFile(atPath: "\(dir)/\(def.name)")
            }
            deps.append(StartupDiag.Dep(name: def.name, hint: def.hint, found: found, required: def.required))
        }

        // Check tmux session existence
        var sessionExists = false
        if deps.contains(where: { $0.name == "tmux" && $0.found }) {
            let sesResult = runCommand("/usr/bin/env", ["tmux", "has-session", "-t", TmuxTargets.session])
            sessionExists = sesResult.exitCode == 0
        }

        let yamlExists = fileManager.fileExists(atPath: workspacePath)

        return StartupDiag(deps: deps, sessionExists: sessionExists, yamlExists: yamlExists)
    }

    func onAppear() {
        Task {
            if bundledRuntimeSeedURL() != nil && ensureBundledRuntimeStaged(reportError: true) == nil {
                return
            }
            loadGUIConfig()
            let diag = checkDependencies()
            startupDiag = diag

            if diag.hasCriticalMissing {
                let missing = diag.deps.filter { $0.required && !$0.found }
                    .map { "\($0.name) (\($0.hint))" }
                    .joined(separator: ", ")
                statusText = "Missing: \(missing)"
                return
            }

            await refreshAll()
            await refreshMemoryStatus()
            startMemoryPolling()
            startWorkspaceWatcher()
            startMIDIIfNeeded()

            if liveColumns.isEmpty {
                if !diag.sessionExists {
                    statusText = "Waiting for tproj session..."
                }
                startStartupRetry()
            }
        }
    }

    private func startStartupRetry() {
        startupRetryTask = Task {
            for attempt in 0..<10 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }

                // Re-check dependencies every 3rd attempt (user may install mid-retry)
                if attempt % 3 == 2 {
                    loadGUIConfig()
                    let diag = checkDependencies()
                    startupDiag = diag
                    if diag.hasCriticalMissing {
                        let missing = diag.deps.filter { $0.required && !$0.found }
                            .map { "\($0.name) (\($0.hint))" }
                            .joined(separator: ", ")
                        statusText = "Missing: \(missing)"
                        continue
                    }
                }

                await refreshAll()
                if !liveColumns.isEmpty {
                    // Wait for column count to stabilize (max 3 additional retries)
                    var stableCount = 0
                    var lastCount = liveColumns.count
                    for _ in 0..<3 {
                        try? await Task.sleep(nanoseconds: 1_000_000_000)
                        if Task.isCancelled { return }
                        await refreshAll()
                        if liveColumns.count == lastCount {
                            stableCount += 1
                            if stableCount >= 2 { return }
                        } else {
                            lastCount = liveColumns.count
                            stableCount = 0
                        }
                    }
                    return
                }
            }
        }
    }

    private func startWorkspaceWatcher() {
        guard workspaceWatcher == nil else { return }
        let watcher = WorkspaceYamlWatcher(paths: [workspacePath, tmuxStateSentinelPath]) { [weak self] in
            Task { @MainActor in
                await self?.refreshWorkspaceStateFromWatcher()
            }
        }
        workspaceWatcher = watcher
        watcher.start()
    }

    private func refreshWorkspaceStateFromWatcher() async {
        loadWorkspaceProjects()
        await loadLiveColumnsAsync()
        normalizeSelection()
    }

    deinit {
        memoryPollTask?.cancel()
        workspaceWatcher?.cancel()
        midiActivator?.stop()
        startupRetryTask?.cancel()
    }

    func refreshAll() async {
        isBusy = true
        defer { isBusy = false }

        loadWorkspaceProjects()
        await loadLiveColumnsAsync()
        normalizeSelection()
        statusText = "Reloaded: \(DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium))"
    }

    func syncUIAndRefreshAll() async {
        isBusy = true
        defer { isBusy = false }

        guard let launch = runtimeLaunchCommand(commandName: "tproj", arguments: ["--sync-ui"])
                ?? fallbackLaunchCommand(commandName: "tproj", arguments: ["--sync-ui"]) else {
            statusText = "UI sync unavailable"
            return
        }

        let result = await runCommandAsync(launch.launchPath, launch.arguments)

        loadWorkspaceProjects()
        await loadLiveColumnsAsync()
        normalizeSelection()

        if result.exitCode != 0 {
            let reason = trimmedError(result)
            statusText = reason.isEmpty ? "UI sync failed" : "UI sync failed: \(reason)"
            return
        }

        let detail = trimmedError(result)
        if !detail.isEmpty {
            statusText = detail
        } else {
            statusText = "UI synced: \(DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium))"
        }
    }

    private func startMemoryPolling() {
        guard memoryPollTask == nil else { return }
        memoryPollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                if Task.isCancelled { return }
                await self?.refreshMemoryStatus()
            }
        }
    }

    private func refreshMemoryStatus() async {
        let collectorCommand = monitorCollectorCommand()
        let result = await runCommandAsync(collectorCommand.launchPath, collectorCommand.arguments)

        guard result.exitCode == 0 else {
            let reason = trimmedError(result)
            let message = reason.isEmpty ? "Monitor command failed" : "Monitor: \(reason)"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
            return
        }

        guard let data = result.stdout.data(using: .utf8) else {
            let message = "Monitor: invalid output encoding"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
            return
        }

        do {
            let snapshot = try JSONDecoder().decode(MonitorStatus.self, from: data)
            memoryStatus = snapshot
            memoryLastUpdatedAt = Date()
            memoryErrorText = snapshot.collector.errors.first
            persistMonitorStatus(snapshot)

            // Auto-kill: if available memory < 1GB, drop newest column to prevent kernel panic
            let availMB = Self.availableMemoryMB()
            if availMB < 1024 {
                let cols = liveColumns.sorted(by: { $0.column < $1.column })
                if cols.count > 1, let newest = cols.last {
                    statusText = "Memory critical (\(availMB)MB available) - auto-removing column \(newest.column)"
                    await removeColumn(newest)
                }
            }
        } catch {
            let message = "Monitor decode failed: \(error.localizedDescription)"
            memoryErrorText = message
            persistMonitorErrorStatus(message)
        }
    }

    private func monitorCollectorCommand() -> (launchPath: String, arguments: [String]) {
        let command = "tproj-mem-json"
        let homeCollector = "\(NSHomeDirectory())/bin/\(command)"
        if fileManager.isExecutableFile(atPath: homeCollector) {
            return (homeCollector, ["--json"])
        }

        if let repoCollector = locateInAncestorBin(commandName: command) {
            return (repoCollector, ["--json"])
        }

        return ("/usr/bin/env", [command, "--json"])
    }

    private func locateInAncestorBin(commandName: String) -> String? {
        var startPaths: [URL] = []
        startPaths.append(URL(fileURLWithPath: fileManager.currentDirectoryPath, isDirectory: true))

        if let executablePath = Bundle.main.executablePath, !executablePath.isEmpty {
            startPaths.append(URL(fileURLWithPath: executablePath).deletingLastPathComponent())
        }

        startPaths.append(URL(fileURLWithPath: Bundle.main.bundlePath, isDirectory: true))

        var visited = Set<String>()
        for start in startPaths where !start.path.isEmpty {
            var cursor = start
            while true {
                let candidate = cursor.appendingPathComponent("bin/\(commandName)").path
                if visited.insert(candidate).inserted && fileManager.isExecutableFile(atPath: candidate) {
                    return candidate
                }

                let parent = cursor.deletingLastPathComponent()
                if parent.path == cursor.path {
                    break
                }
                cursor = parent
            }
        }

        return nil
    }

    private func persistMonitorStatus(_ snapshot: MonitorStatus) {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(snapshot)
            let url = URL(fileURLWithPath: monitorStatusPath)
            try data.write(to: url, options: .atomic)
        } catch {
            if memoryErrorText == nil {
                memoryErrorText = "Monitor cache write failed: \(error.localizedDescription)"
            }
        }
    }

    private func persistMonitorErrorStatus(_ message: String) {
        let snapshot = MonitorStatus(
            timestamp: currentISO8601Timestamp(),
            collector: MonitorCollector(version: "", source: "tproj-app", errors: [message])
        )
        persistMonitorStatus(snapshot)
    }

    private func currentISO8601Timestamp() -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: Date())
    }

    private func beginLayoutMutation(action: String) -> Bool {
        if layoutMutationInProgress {
            statusText = "Busy: layout operation in progress"
            logLayoutAction(action: action, before: -1, after: -1, elapsedMS: 0, result: "busy", note: "rejected")
            return false
        }
        layoutMutationInProgress = true
        isBusy = true
        return true
    }

    private func endLayoutMutation() {
        layoutMutationInProgress = false
        isBusy = false
    }

    private func workspacePaneCountSync() -> Int {
        let result = runCommand("/usr/bin/env", [
            "tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", "#{pane_id}"
        ])
        guard result.exitCode == 0 else { return -1 }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .count
    }

    private func workspacePaneCountAsync() async -> Int {
        let result = await runCommandAsync("/usr/bin/env", [
            "tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", "#{pane_id}"
        ])
        guard result.exitCode == 0 else { return -1 }
        return result.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .count
    }

    // MARK: - Layout Lock (PID-based lockfile, shared with bin/tproj)

    private let layoutLockfile = "/tmp/tproj-layout.lock"

    private func acquireLayoutLockAsync(timeout: TimeInterval = 10) async -> Bool {
        let myPID = ProcessInfo.processInfo.processIdentifier
        let start = Date()
        while Date().timeIntervalSince(start) < timeout {
            // Try atomic create with O_CREAT|O_EXCL
            let fd = open(layoutLockfile, O_WRONLY | O_CREAT | O_EXCL, 0o644)
            if fd >= 0 {
                let pidStr = "\(myPID)\n"
                pidStr.withCString { ptr in _ = write(fd, ptr, strlen(ptr)) }
                close(fd)
                return true
            }
            // File exists - check staleness
            if let content = try? String(contentsOfFile: layoutLockfile, encoding: .utf8),
               let holderPID = pid_t(content.trimmingCharacters(in: .whitespacesAndNewlines)) {
                if kill(holderPID, 0) != 0 {
                    // Stale lock from dead process
                    unlink(layoutLockfile)
                    continue
                }
            } else {
                // Corrupt lockfile
                unlink(layoutLockfile)
                continue
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    private func releaseLayoutLock() {
        unlink(layoutLockfile)
    }

    private func appendLayoutLogLine(_ line: String) {
        guard let data = (line + "\n").data(using: .utf8) else { return }
        let url = URL(fileURLWithPath: layoutLogPath)

        if !fileManager.fileExists(atPath: layoutLogPath) {
            try? data.write(to: url, options: .atomic)
            return
        }

        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        defer { try? handle.close() }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch {
            // best-effort logging only
        }
    }

    private func logLayoutAction(
        action: String,
        before: Int,
        after: Int,
        elapsedMS: Int64,
        result: String,
        note: String = ""
    ) {
        let compactNote = note
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        var fields = [
            "\(currentISO8601Timestamp())",
            "action=\(action)",
            "before=\(before)",
            "after=\(after)",
            "elapsed_ms=\(elapsedMS)",
            "result=\(result)",
        ]
        if !compactNote.isEmpty {
            fields.append("note=\(compactNote)")
        }
        appendLayoutLogLine(fields.joined(separator: " "))
    }

    private func logSessionSend(
        action: String,
        session: String,
        paneID: String,
        role: String,
        command: String
    ) {
        var fields = [
            "\(currentISO8601Timestamp())",
            "action=\(action)",
            "session=\(session)",
            "target=all",
            "pane=\(paneID)",
            "role=\(role)",
            "command=\(command)",
        ]
        if let col = extractColumn(fromRole: role) {
            fields.append("column=\(col)")
        }
        appendLayoutLogLine(fields.joined(separator: " "))
    }

    private func extractColumn(fromRole role: String) -> Int? {
        let pattern = "-p([0-9]+)"
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(role.startIndex..<role.endIndex, in: role)
        guard let match = regex.firstMatch(in: role, options: [], range: range),
              match.numberOfRanges >= 2,
              let numberRange = Range(match.range(at: 1), in: role) else {
            return nil
        }
        return Int(role[numberRange])
    }

    private func dropColumnCommand() -> (launchPath: String, arguments: [String])? {
        if let command = runtimeLaunchCommand(commandName: "tproj-drop-column", arguments: []) {
            return command
        }
        return fallbackLaunchCommand(commandName: "tproj-drop-column", arguments: [])
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

    /// Available memory in MB (free + inactive + purgeable).
    /// macOS keeps "free" artificially low due to aggressive caching, so we include reclaimable pages.
    private nonisolated static func availableMemoryMB() -> Int {
        var info = vm_statistics64()
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return Int.max }  // fail-open: don't block on error
        let pageSize = UInt64(vm_kernel_page_size)
        let availBytes = (UInt64(info.free_count) + UInt64(info.inactive_count) + UInt64(info.purgeable_count)) * pageSize
        return Int(availBytes / (1024 * 1024))
    }

    func addColumnByAlias(_ alias: String) async {
        // Memory gate: refuse if available memory < 2GB (CC + Cdx need ~1.5GB)
        let availMB = Self.availableMemoryMB()
        if availMB < 2048 {
            statusText = "Memory too low (\(availMB)MB available) - close apps or remove columns first"
            return
        }
        guard beginLayoutMutation(action: "add-column") else { return }
        let startedMS = Int64(Date().timeIntervalSince1970 * 1000)
        let beforeCount = await workspacePaneCountAsync()
        var resultTag = "ok"
        var note = "alias=\(alias)"

        if let launch = runtimeLaunchCommand(commandName: "tproj", arguments: ["--no-gui", "--add", alias])
                ?? fallbackLaunchCommand(commandName: "tproj", arguments: ["--no-gui", "--add", alias]) {
            let result = await runCommandAsync(launch.launchPath, launch.arguments)
            if result.exitCode == 0 {
                statusText = "Added column: \(alias)"
                await loadLiveColumnsAsync()
                if let projectPath = self.workspaceProjects.first(where: { $0.effectiveAlias == alias })?.path {
                    let helper = "\(NSHomeDirectory())/bin/voice-identity-sync"
                    if FileManager.default.isExecutableFile(atPath: helper) {
                        Task.detached(priority: .background) {
                            _ = Self.executeCommand(helper, [projectPath, "--alias", alias, "--ensure"])
                        }
                    }
                }
            } else {
                resultTag = "error"
                note = "alias=\(alias) error=\(trimmedError(result))"
                statusText = "Add failed: \(trimmedError(result))"
            }
        } else {
            resultTag = "error"
            note = "alias=\(alias) error=runtime_unavailable"
            statusText = "Bundled runtime unavailable"
        }

        let afterCount = await workspacePaneCountAsync()
        let elapsed = Int64(Date().timeIntervalSince1970 * 1000) - startedMS
        logLayoutAction(
            action: "add-column",
            before: beforeCount,
            after: afterCount,
            elapsedMS: elapsed,
            result: resultTag,
            note: note
        )
        endLayoutMutation()
    }

    func toggleMIDILearn() {
        startMIDIIfNeeded()
        guard let midiActivator else {
            statusText = "MIDI unavailable"
            return
        }
        isMIDILearning = midiActivator.toggleLearn()
    }

    func toggleYazi(for column: LiveColumn) async {
        guard let pane = column.primaryCodexPaneID ?? column.primaryClaudePaneID else {
            statusText = "No pane found for column \(column.column)"
            return
        }

        isBusy = true
        defer { isBusy = false }

        guard let launch = runtimeLaunchCommand(commandName: "tproj-toggle-yazi", arguments: [TmuxTargets.session, pane])
                ?? fallbackLaunchCommand(commandName: "tproj-toggle-yazi", arguments: [TmuxTargets.session, pane]) else {
            statusText = "Bundled runtime unavailable"
            return
        }
        let result = await runCommandAsync(launch.launchPath, launch.arguments)
        if result.exitCode == 0 {
            statusText = "Toggled Yazi for #\(column.column)"
        } else {
            statusText = "Yazi toggle failed: \(trimmedError(result))"
        }
        await loadLiveColumnsAsync()
    }

    func toggleAIPane(role: String, for column: LiveColumn) async {
        guard beginLayoutMutation(action: "toggle-\(role)") else { return }
        let startedMS = Int64(Date().timeIntervalSince1970 * 1000)
        let beforeCount = await workspacePaneCountAsync()
        var resultTag = "ok"
        var note = "column=\(column.column)"
        var lockHeld = false
        defer {
            if lockHeld { releaseLayoutLock() }
            let afterCount = workspacePaneCountSync()
            let elapsed = Int64(Date().timeIntervalSince1970 * 1000) - startedMS
            logLayoutAction(
                action: "toggle-\(role)",
                before: beforeCount,
                after: afterCount,
                elapsedMS: elapsed,
                result: resultTag,
                note: note
            )
            endLayoutMutation()
        }

        guard await acquireLayoutLockAsync() else {
            resultTag = "lock-error"
            note += " lock=acquire_failed"
            statusText = "\(role): failed to acquire layout lock"
            await loadLiveColumnsAsync()
            return
        }
        lockHeld = true

        let paneIDs: [String]
        let roleName: String
        switch role {
        case "claude":
            paneIDs = column.claudePaneIDs
            roleName = "claude-p\(column.column)"
        case "codex":
            paneIDs = column.codexPaneIDs
            roleName = "codex-p\(column.column)"
        default: return
        }

        // Toggle off: graceful exit + descendant cleanup via shared script
        if !paneIDs.isEmpty {
            for paneID in paneIDs {
                _ = await runCommandAsync("\(NSHomeDirectory())/bin/tproj-kill-pane",
                    [paneID, roleName])
            }
            note += " state=off"
            statusText = "\(role) off for #\(column.column)"
            await loadLiveColumnsAsync()
            return
        }

        // Toggle on: find sibling pane, split, configure, launch
        let sessionTarget = TmuxTargets.devWindow
        let listResult = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_id}:#{@role}"])
        guard listResult.exitCode == 0 else {
            resultTag = "error"
            note += " error=\(trimmedError(listResult))"
            statusText = "\(role): \(trimmedError(listResult))"
            await loadLiveColumnsAsync()
            return
        }

        let paneRoles: [(id: String, paneRole: String)] = listResult.stdout
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .compactMap { line in
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard parts.count == 2 else { return nil }
                return (id: parts[0], paneRole: parts[1])
            }

        // Find sibling: CC needs codex, Cdx needs claude, fallback to any pane in same column
        let siblingRole: String
        switch role {
        case "claude":
            siblingRole = "codex-p\(column.column)"
            // CC below codex, 70% height
        case "codex":
            siblingRole = "claude-p\(column.column)"
            // Cdx above claude, 30% height
        default: return
        }

        guard let targetPaneID = paneRoles.first(where: { $0.paneRole == siblingRole })?.id
                ?? paneRoles.first(where: { $0.paneRole.hasSuffix("-p\(column.column)") })?.id else {
            resultTag = "error"
            note += " error=no_target_pane"
            statusText = "\(role): no pane for #\(column.column)"
            return
        }

        let splitCommand: [String]
        switch role {
        case "claude":
            splitCommand = ["tmux", "split-window", "-v", "-t", targetPaneID, "-l", "70%", "-c", "/tmp", "-P", "-F", "#{pane_id}"]
        case "codex":
            splitCommand = ["tmux", "split-window", "-v", "-b", "-t", targetPaneID, "-l", "30%", "-c", "/tmp", "-P", "-F", "#{pane_id}"]
        default: return
        }

        let createResult = await runCommandAsync("/usr/bin/env", splitCommand)
        guard createResult.exitCode == 0 else {
            resultTag = "error"
            note += " create_error=\(trimmedError(createResult))"
            statusText = "\(role)[\(createResult.exitCode)]: \(trimmedError(createResult))"
            return
        }

        let newPane = createResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newPane.isEmpty else {
            resultTag = "error"
            note += " error=empty_pane_id"
            statusText = "\(role): empty pane id"
            return
        }

        // Set tags
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@role", roleName])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@column", "\(column.column)"])
        _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@project", column.projectPath])

        if let host = hostForColumn(column) {
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_host", host])
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "@remote_path", column.projectPath])

            let remoteCmd: String
            switch role {
            case "claude":
                let remotePath = shellDoubleQuote(column.projectPath)
                remoteCmd = "ssh -t \(shellSingleQuote(host)) \"cd \(remotePath) && claude --continue 2>/dev/null || claude\""
            case "codex":
                let remotePath = shellDoubleQuote(column.projectPath)
                remoteCmd = "ssh -t \(shellSingleQuote(host)) \"cd \(remotePath) && codex resume --last -s danger-full-access -a never --search\""
            default: return
            }
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, remoteCmd, "C-m"])
        } else {
            let projPath = column.projectPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? NSHomeDirectory() : column.projectPath
            let launchCmd: String
            switch role {
            case "claude":
                // Set title + prevent overwrite (CC only)
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "select-pane", "-t", newPane, "-T", "Claude Code"])
                _ = await runCommandAsync("/usr/bin/env", ["tmux", "set-option", "-pt", newPane, "allow-set-title", "off"])
                launchCmd = "cd \(shellSingleQuote(projPath)) && claude --continue 2>/dev/null || claude"
            case "codex":
                launchCmd = "cd \(shellSingleQuote(projPath)) && codex resume --last -s danger-full-access -a never --search"
            default: return
            }
            _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", newPane, launchCmd, "C-m"])
        }

        note += " state=on"
        statusText = "\(role) on for #\(column.column)"
        await loadLiveColumnsAsync()
    }

    func toggleTerminal(for column: LiveColumn) async {
        guard beginLayoutMutation(action: "toggle-terminal") else { return }
        let startedMS = Int64(Date().timeIntervalSince1970 * 1000)
        let beforeCount = await workspacePaneCountAsync()
        var resultTag = "ok"
        var note = "column=\(column.column)"
        var lockHeld = false
        defer {
            if lockHeld { releaseLayoutLock() }
            let afterCount = workspacePaneCountSync()
            let elapsed = Int64(Date().timeIntervalSince1970 * 1000) - startedMS
            logLayoutAction(
                action: "toggle-terminal",
                before: beforeCount,
                after: afterCount,
                elapsedMS: elapsed,
                result: resultTag,
                note: note
            )
            endLayoutMutation()
        }

        guard await acquireLayoutLockAsync() else {
            resultTag = "lock-error"
            note += " lock=acquire_failed"
            statusText = "Term: failed to acquire layout lock"
            await loadLiveColumnsAsync()
            return
        }
        lockHeld = true

        let sessionTarget = TmuxTargets.devWindow
        let listResult = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_id}:#{@role}"])
        guard listResult.exitCode == 0 else {
            resultTag = "error"
            note += " error=\(trimmedError(listResult))"
            statusText = "Term: \(trimmedError(listResult))"
            await loadLiveColumnsAsync()
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

        // Toggle off: graceful exit + descendant cleanup via shared script
        if let existing = paneRoles.first(where: { $0.role == roleName }) {
            let killResult = await runCommandAsync("\(NSHomeDirectory())/bin/tproj-kill-pane",
                [existing.id, roleName])
            if killResult.exitCode != 0 {
                resultTag = "error"
                note += " off_error=\(trimmedError(killResult))"
            } else {
                note += " state=off"
            }
            statusText = killResult.exitCode == 0
                ? "Terminal off for #\(column.column)"
                : "Term off failed: \(trimmedError(killResult))"
            await loadLiveColumnsAsync()
            return
        }

        // Toggle on: find target pane from fresh list (codex preferred, claude fallback)
        guard let targetPane = paneRoles.first(where: { $0.role == "codex-p\(column.column)" })?.id
                ?? paneRoles.first(where: { $0.role == "claude-p\(column.column)" })?.id else {
            resultTag = "error"
            note += " error=no_target_pane"
            statusText = "Term: no pane for #\(column.column)"
            return
        }

        let createResult = await runCommandAsync("/usr/bin/env", [
            "tmux", "split-window", "-v", "-b", "-t", targetPane,
            "-c", "/tmp", "-l", "25%", "-P", "-F", "#{pane_id}"
        ])
        guard createResult.exitCode == 0 else {
            resultTag = "error"
            note += " create_error=\(trimmedError(createResult))"
            statusText = "Term[\(createResult.exitCode)]: \(trimmedError(createResult))"
            return
        }

        let newPane = createResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newPane.isEmpty else {
            resultTag = "error"
            note += " error=empty_pane_id"
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

        note += " state=on"
        statusText = "Terminal on for #\(column.column)"
        await loadLiveColumnsAsync()
    }

    func removeColumn(_ column: LiveColumn) async {
        guard column.hasCorePanes else {
            statusText = "Missing pane info for column \(column.column)"
            return
        }

        let columnNumber = column.column
        if pendingDropColumns.contains(columnNumber) {
            statusText = "Drop already in progress for #\(columnNumber)"
            return
        }

        let startedMS = Int64(Date().timeIntervalSince1970 * 1000)
        let beforeCount = await workspacePaneCountAsync()
        guard let dropCommand = dropColumnCommand() else {
            statusText = "Bundled runtime unavailable"
            return
        }

        pendingDropColumns.insert(columnNumber)
        liveColumns.removeAll { $0.column == columnNumber }
        statusText = "Dropping #\(columnNumber) in background..."

        let task = Task { [weak self] in
            guard let self else { return }
            defer {
                self.pendingDropColumns.remove(columnNumber)
                self.dropTasks[columnNumber] = nil
            }

            var resultTag = "ok"
            var note = "mode=async column=\(columnNumber) grace_ms=200 max_ms=1200"

            let dropResult = await self.runCommandAsync(
                dropCommand.launchPath,
                dropCommand.arguments + ["--grace-ms", "200", "--max-ms", "1200", TmuxTargets.session, "\(columnNumber)"]
            )

            if dropResult.exitCode != 0 {
                resultTag = "error"
                note += " error=\(self.trimmedError(dropResult))"
                self.statusText = "Drop #\(columnNumber) failed: \(self.trimmedError(dropResult))"
            } else {
                let dropInfo = dropResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
                if !dropInfo.isEmpty {
                    note += " \(dropInfo)"
                }
                let normalized = await self.normalizeColumnsByVisualOrderAsync()
                if !normalized {
                    resultTag = "warning"
                    note += " normalized=0"
                    self.statusText = "Drop #\(columnNumber): normalize warning"
                } else {
                    note += " normalized=1"
                    self.statusText = "Removed column \(columnNumber)"
                }
            }

            await self.loadLiveColumnsAsync()
            let afterCount = await workspacePaneCountAsync()
            let elapsed = Int64(Date().timeIntervalSince1970 * 1000) - startedMS
            self.logLayoutAction(
                action: "drop-column",
                before: beforeCount,
                after: afterCount,
                elapsedMS: elapsed,
                result: resultTag,
                note: note
            )
        }
        dropTasks[columnNumber] = task
    }

    func moveColumn(from sourceColumn: Int, toInsertionIndex insertionIndex: Int) async {
        guard beginLayoutMutation(action: "reorder-column") else { return }

        let startedMS = Int64(Date().timeIntervalSince1970 * 1000)
        let beforeCount = await workspacePaneCountAsync()
        var resultTag = "ok"
        var note = "mode=insert from=\(sourceColumn) insertion=\(insertionIndex)"
        var lockHeld = false
        defer {
            if lockHeld { releaseLayoutLock() }
            let afterCount = workspacePaneCountSync()
            let elapsed = Int64(Date().timeIntervalSince1970 * 1000) - startedMS
            logLayoutAction(
                action: "reorder-column",
                before: beforeCount,
                after: afterCount,
                elapsedMS: elapsed,
                result: resultTag,
                note: note
            )
            endLayoutMutation()
        }

        guard await acquireLayoutLockAsync() else {
            resultTag = "lock-error"
            note += " lock=acquire_failed"
            statusText = "Reorder failed: lock"
            await loadLiveColumnsAsync()
            return
        }
        lockHeld = true

        let agentsActive = await runCommandAsync("/usr/bin/env", ["tmux", "show-environment", "-t", TmuxTargets.session, "TPROJ_AGENTS_ACTIVE"])
        if agentsActive.exitCode == 0 {
            resultTag = "blocked"
            note += " reason=agents_active"
            statusText = "Reorder disabled while agent panes are active"
            await loadLiveColumnsAsync()
            return
        }

        guard let sourceIndex = liveColumns.firstIndex(where: { $0.column == sourceColumn }) else {
            resultTag = "error"
            note += " error=source_column_missing"
            statusText = "Reorder failed: source column missing"
            await loadLiveColumnsAsync()
            return
        }

        let boundedInsertion = min(max(insertionIndex, 0), liveColumns.count)
        var targetIndex = boundedInsertion
        if targetIndex > sourceIndex {
            targetIndex -= 1
        }
        note += " resolved_insertion=\(boundedInsertion) source_idx=\(sourceIndex) dest_idx=\(targetIndex)"

        guard targetIndex != sourceIndex else {
            note += " noop=1 reason=same_index_resolved"
            statusText = "Reorder unchanged"
            await loadLiveColumnsAsync()
            return
        }

        var orderedColumns = liveColumns.map(\.column)
        guard sourceIndex < orderedColumns.count else {
            resultTag = "error"
            note += " error=source_index_out_of_range"
            statusText = "Reorder failed: source index out of range"
            await loadLiveColumnsAsync()
            return
        }

        var swapCount = 0
        if sourceIndex < targetIndex {
            for idx in sourceIndex..<targetIndex {
                let leftColumn = orderedColumns[idx]
                let rightColumn = orderedColumns[idx + 1]
                if let error = await swapColumnsWithoutNormalize(sourceColumn: leftColumn, targetColumn: rightColumn) {
                    resultTag = "error"
                    note += " pair=\(leftColumn)<->\(rightColumn) error=\(error)"
                    statusText = "Reorder failed: \(error)"
                    await loadLiveColumnsAsync()
                    return
                }
                orderedColumns.swapAt(idx, idx + 1)
                swapCount += 1
            }
        } else {
            for idx in stride(from: sourceIndex, to: targetIndex, by: -1) {
                let leftColumn = orderedColumns[idx - 1]
                let rightColumn = orderedColumns[idx]
                if let error = await swapColumnsWithoutNormalize(sourceColumn: leftColumn, targetColumn: rightColumn) {
                    resultTag = "error"
                    note += " pair=\(leftColumn)<->\(rightColumn) error=\(error)"
                    statusText = "Reorder failed: \(error)"
                    await loadLiveColumnsAsync()
                    return
                }
                orderedColumns.swapAt(idx - 1, idx)
                swapCount += 1
            }
        }
        note += " swaps=\(swapCount)"

        if let rebalance = runtimeLaunchCommand(commandName: "rebalance-workspace-columns", arguments: [TmuxTargets.session]) {
            _ = await runCommandAsync(rebalance.launchPath, rebalance.arguments)
        }
        let normalized = await normalizeColumnsByVisualOrderAsync()
        if !normalized {
            resultTag = "warning"
            note += " normalized=0"
            statusText = "Reorder warning: visual normalize failed"
        } else {
            note += " normalized=1"
            statusText = "Moved #\(sourceColumn) to position \(targetIndex + 1)"
        }
        await loadLiveColumnsAsync()
        refreshColumnIdentities()
    }

    private func swapColumnsWithoutNormalize(sourceColumn: Int, targetColumn: Int) async -> String? {
        guard sourceColumn != targetColumn else { return nil }

        let panes = await listWorkspacePanesAsync()
        guard !panes.isEmpty else {
            return "workspace panes not found"
        }

        guard let claudeSource = paneID(forRole: "claude-p\(sourceColumn)", panes: panes),
              let claudeTarget = paneID(forRole: "claude-p\(targetColumn)", panes: panes),
              let codexSource = paneID(forRole: "codex-p\(sourceColumn)", panes: panes),
              let codexTarget = paneID(forRole: "codex-p\(targetColumn)", panes: panes) else {
            return "required panes not found"
        }

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

        let mainSwap1 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", claudeSource, "-t", claudeTarget])
        guard mainSwap1.exitCode == 0 else {
            return trimmedError(mainSwap1)
        }
        let mainSwap2 = await runCommandAsync("/usr/bin/env", ["tmux", "swap-pane", "-s", codexSource, "-t", codexTarget])
        guard mainSwap2.exitCode == 0 else {
            return trimmedError(mainSwap2)
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

        let check = await runCommandAsync("/usr/bin/env",
            ["tmux", "display-message", "-t", claudeSource, "-p", "#{pane_left}"])
        let srcLeftAfter = Int(check.stdout.trimmingCharacters(in: .whitespacesAndNewlines)) ?? -1
        let panesMoved = (srcLeftAfter != sourceOriginalLeft) && srcLeftAfter >= 0 && sourceOriginalLeft >= 0

        if !panesMoved {
            await swapProjectTagsAsync(
                sourceColumn: sourceColumn, targetColumn: targetColumn,
                sourceProject: sourceProject, sourceRemoteHost: sourceRemoteHost, sourceRemotePath: sourceRemotePath,
                targetProject: targetProject, targetRemoteHost: targetRemoteHost, targetRemotePath: targetRemotePath
            )
        }
        return nil
    }

    func saveWorkspace() async {
        isBusy = true
        defer { isBusy = false }

        if let message = persistWorkspaceProjects(workspaceProjects, createIfMissing: true) {
            statusText = message
        } else {
            statusText = "Saved workspace.yaml"
            loadWorkspaceProjects()
            normalizeSelection()
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

    private func startMIDIIfNeeded() {
        guard midiActivator == nil else { return }
        let activator = MIDIPaneActivator()
        activator.onStatus = { [weak self] message in
            Task { @MainActor in
                self?.statusText = message
            }
        }
        activator.onLearnStateChanged = { [weak self] isLearning in
            Task { @MainActor in
                self?.isMIDILearning = isLearning
            }
        }
        activator.onJogStep = { [weak self] direction in
            Task { [weak self] in
                await self?.focusPaneByJog(direction)
            }
        }
        activator.start()
        midiActivator = activator
    }

    private func focusPaneByJog(_ direction: Int) async {
        // Cycle focus in role-major order: codex panes left->right, then claude
        // panes left->right (not tmux pane_index order). jog stays in the dev window.
        let sessionTarget = TmuxTargets.devWindow
        let list = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", sessionTarget, "-F", "#{pane_id}|#{@role}|#{pane_left}|#{pane_active}"])
        guard list.exitCode == 0 else {
            statusText = "MIDI jog failed: \(trimmedError(list))"
            return
        }

        var panes: [(paneId: String, role: String, left: Int)] = []
        var activePaneId: String?
        for line in list.stdout.split(separator: "\n", omittingEmptySubsequences: true) {
            let fields = line.split(separator: "|", omittingEmptySubsequences: false)
            guard fields.count >= 4 else { continue }
            let paneId = String(fields[0])
            let role = String(fields[1])
            guard let left = Int(fields[2].trimmingCharacters(in: .whitespaces)) else { continue }
            if fields[3] == "1" { activePaneId = paneId }
            panes.append((paneId, role, left))
        }

        let order = jogCycleOrder(panes: panes)
        guard !order.isEmpty else {
            statusText = "MIDI jog: no codex/claude panes"
            return
        }
        let nextPaneId = nextPaneInCycle(order: order, active: activePaneId, direction: direction) ?? order[0]

        let select = await runCommandAsync("/usr/bin/env", ["tmux", "select-pane", "-t", nextPaneId])
        if select.exitCode == 0 {
            statusText = direction > 0 ? "MIDI jog: next" : "MIDI jog: prev"
        } else {
            statusText = "MIDI jog failed: \(trimmedError(select))"
        }
    }

    private func shouldSendInterrupt(to role: String) -> Bool {
        if role.hasPrefix("claude") || role.hasPrefix("codex") || role.hasPrefix("terminal") {
            return true
        }
        if role.hasPrefix("agent") {
            return true
        }
        return false
    }

    private func exitCommand(for role: String) -> String? {
        if role.hasPrefix("claude") || role.hasPrefix("terminal") {
            return "exit"
        }
        if role.hasPrefix("codex") {
            return "/exit"
        }
        if role.hasPrefix("agent") {
            return "/exit"
        }
        return nil
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

        let workspaceSessionWasPresent = sessions.contains(TmuxTargets.session)
        let orderedActivePaths = liveColumns
            .sorted { $0.column < $1.column }
            .map { $0.projectPath.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let rememberedPaths = Set(orderedActivePaths)
        let shouldPersistWorkspaceSet =
            workspaceSessionWasPresent &&
            !rememberedPaths.isEmpty &&
            fileManager.fileExists(atPath: workspacePath)

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

            // Send C-c to selected interactive panes, q to yazi panes.
            for pane in paneRoles {
                if shouldSendInterrupt(to: pane.role) {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "C-c", ""])
                    logSessionSend(action: "stop-send", session: session, paneID: pane.id, role: pane.role, command: "C-c")
                } else if pane.role.hasPrefix("yazi") {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, "q", ""])
                    logSessionSend(action: "stop-send", session: session, paneID: pane.id, role: pane.role, command: "q")
                }
            }

            // Brief pause for C-c to take effect
            try? await Task.sleep(nanoseconds: 300_000_000) // 0.3s

            // Send role-specific exit commands.
            for pane in paneRoles {
                if let command = exitCommand(for: pane.role) {
                    _ = await runCommandAsync("/usr/bin/env", ["tmux", "send-keys", "-t", pane.id, command, "Enter"])
                    logSessionSend(action: "stop-send", session: session, paneID: pane.id, role: pane.role, command: command)
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

        liveColumns = []

        guard shouldPersistWorkspaceSet else {
            statusText = "Session stopped"
            return
        }

        // Build a lookup from workspaceProjects, update enabled flag
        var projectsByPath: [String: WorkspaceProject] = [:]
        for project in workspaceProjects {
            var updated = project
            let trimmedPath = project.path.trimmingCharacters(in: .whitespacesAndNewlines)
            updated.enabled = rememberedPaths.contains(trimmedPath)
            projectsByPath[trimmedPath] = updated
        }

        // Active projects in liveColumns order first, then inactive ones
        var updatedProjects: [WorkspaceProject] = []
        var usedPaths = Set<String>()
        for activePath in orderedActivePaths {
            if let project = projectsByPath[activePath], !usedPaths.contains(activePath) {
                updatedProjects.append(project)
                usedPaths.insert(activePath)
            }
        }
        for project in workspaceProjects {
            let trimmedPath = project.path.trimmingCharacters(in: .whitespacesAndNewlines)
            if !usedPaths.contains(trimmedPath) {
                var inactive = project
                inactive.enabled = false
                updatedProjects.append(inactive)
                usedPaths.insert(trimmedPath)
            }
        }

        if let message = persistWorkspaceProjects(updatedProjects, createIfMissing: false) {
            statusText = "Session stopped (\(message))"
        } else {
            workspaceProjects = updatedProjects
            loadWorkspaceProjects()
            normalizeSelection()
            statusText = "Session stopped (saved startup set)"
        }
    }



    private func killSession() async {
        let sessions = await getTprojSessions()
        guard !sessions.isEmpty else { return }

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
        guard !pids.isEmpty else { return }

        for pid in pids {
            kill(pid, SIGTERM)
        }

        try? await Task.sleep(nanoseconds: 800_000_000)

        for pid in pids {
            if kill(pid, 0) == 0 {
                kill(pid, SIGKILL)
            }
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
                width: $0.width, left: $0.left, claudePaneIDs: $0.claudePaneIDs,
                codexPaneIDs: $0.codexPaneIDs, agentPaneIDs: $0.agentPaneIDs, agentNames: $0.agentNames,
                yaziPaneID: $0.yaziPaneID, terminalPaneID: $0.terminalPaneID
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

        let query = ".projects[]? | [(.path // \"\"),(.type // \"local\"),(.host // \"\"),(.alias // \"\"),((.enabled // true)|tostring),((.lastActiveAt // 0)|tostring)] | @tsv"
        let result = runCommand("/usr/bin/env", ["yq", "-r", query, url.path])

        guard result.exitCode == 0 else {
            let errText = trimmedError(result)
            if errText.contains("No such file or directory") && errText.contains("yq") {
                statusText = "yq not installed (brew install yq)"
            } else {
                statusText = "workspace.yaml parse error: \(errText)"
            }
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
            let lastActiveAt = parts.count > 5 ? (Int(parts[5]) ?? 0) : 0

            parsed.append(
                WorkspaceProject(
                    path: parts[0],
                    type: parts[1].isEmpty ? "local" : parts[1],
                    host: parts[2],
                    alias: parts[3],
                    enabled: enabled,
                    lastActiveAt: lastActiveAt
                )
            )
        }

        workspaceProjects = parsed.sorted { lhs, rhs in
            if lhs.lastActiveAt != rhs.lastActiveAt {
                return lhs.lastActiveAt > rhs.lastActiveAt
            }
            return lhs.effectiveAlias.localizedCaseInsensitiveCompare(rhs.effectiveAlias) == .orderedAscending
        }
    }

    private func loadLiveColumns() {
        let format = "#{@column}|#{@role}|#{@project}|#{@remote_host}|#{@remote_path}|#{pane_width}|#{pane_left}|#{pane_id}"
        let result = runCommand("/usr/bin/env", ["tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", format])
        applyLiveColumnsResult(result)
    }

    private func loadLiveColumnsAsync() async {
        let format = "#{@column}|#{@role}|#{@project}|#{@remote_host}|#{@remote_path}|#{pane_width}|#{pane_left}|#{pane_id}"
        let result = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", format])
        applyLiveColumnsResult(result)
    }

    private func applyLiveColumnsResult(_ result: CommandResult) {
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
            var claudePaneIDs: [String] = []
            var codexPaneIDs: [String] = []
            var agentPaneIDs: [String] = []
            var agentNames: [String] = []
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

            if role.hasPrefix("claude-p"), !entry.claudePaneIDs.contains(paneID) {
                entry.claudePaneIDs.append(paneID)
            }
            if role.hasPrefix("codex-p"), !entry.codexPaneIDs.contains(paneID) {
                entry.codexPaneIDs.append(paneID)
            }
            if role.hasPrefix("agent-p"), !entry.agentPaneIDs.contains(paneID) {
                entry.agentPaneIDs.append(paneID)
                let agentPrefix = "agent-p\(col)-"
                if role.hasPrefix(agentPrefix) {
                    let agentName = String(role.dropFirst(agentPrefix.count))
                    if !agentName.isEmpty, !entry.agentNames.contains(agentName) {
                        entry.agentNames.append(agentName)
                    }
                }
            }
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
                    claudePaneIDs: $0.claudePaneIDs,
                    codexPaneIDs: $0.codexPaneIDs,
                    agentPaneIDs: $0.agentPaneIDs,
                    agentNames: $0.agentNames,
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
                existing.claudePaneIDs = data.claudePaneIDs
                existing.codexPaneIDs = data.codexPaneIDs
                existing.agentPaneIDs = data.agentPaneIDs
                existing.agentNames = data.agentNames
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
            ["tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", "#{pane_id}|#{pane_left}|#{@column}|#{@role}"]
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
        let result = await runCommandAsync("/usr/bin/env", ["tmux", "list-panes", "-t", TmuxTargets.devWindow, "-F", "#{pane_id}|#{@role}|#{@column}"])
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

    private func persistWorkspaceProjects(_ projects: [WorkspaceProject], createIfMissing: Bool) -> String? {
        do {
            let parent = URL(fileURLWithPath: workspacePath).deletingLastPathComponent()
            try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)

            let content = renderWorkspaceYAML(projects)
            if !fileManager.fileExists(atPath: workspacePath) {
                guard createIfMissing else {
                    return "workspace.yaml not found"
                }
                try content.write(toFile: workspacePath, atomically: true, encoding: .utf8)
                return nil
            }

            let tempURL = parent.appendingPathComponent(".tproj-projects-\(UUID().uuidString).yaml")
            try content.write(to: tempURL, atomically: true, encoding: .utf8)
            defer { try? fileManager.removeItem(at: tempURL) }

            let expression = ".projects = load(strenv(TPROJ_PROJECTS_TMP)).projects"
            let result = runCommand(
                "/usr/bin/env",
                ["yq", "eval", "-i", expression, workspacePath],
                environment: ["TPROJ_PROJECTS_TMP": tempURL.path]
            )

            guard result.exitCode == 0 else {
                let errText = trimmedError(result)
                if errText.contains("No such file or directory") && errText.contains("yq") {
                    return "yq not installed (brew install yq)"
                }
                return "Save failed: \(errText)"
            }

            return nil
        } catch {
            return "Save failed: \(error.localizedDescription)"
        }
    }

    private func renderWorkspaceYAML(_ projects: [WorkspaceProject]) -> String {
        var lines: [String] = []
        lines.append("projects:")

        for project in projects {
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
            if project.lastActiveAt > 0 {
                lines.append("    lastActiveAt: \(project.lastActiveAt)")
            }
        }

        return lines.joined(separator: "\n") + "\n"
    }

    private func yamlQuote(_ value: String) -> String {
        let escaped = value.replacingOccurrences(of: "'", with: "''")
        return "'\(escaped)'"
    }

    private func runCommand(_ launchPath: String, _ arguments: [String], environment: [String: String] = [:]) -> CommandResult {
        Self.executeCommand(launchPath, arguments, environment: environment)
    }

    func toggleAutoZoom(_ enabled: Bool) {
        let helper = "\(NSHomeDirectory())/bin/tproj-pane-autozoom"
        guard FileManager.default.isExecutableFile(atPath: helper) else { return }
        let arg = enabled ? "--enable" : "--disable"
        Task.detached(priority: .background) {
            _ = Self.executeCommand(helper, [arg])
        }
    }

    private func runCommandAsync(_ launchPath: String, _ arguments: [String], environment: [String: String] = [:]) async -> CommandResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let result = Self.executeCommand(launchPath, arguments, environment: environment)
                continuation.resume(returning: result)
            }
        }
    }

    nonisolated private static func executeCommand(
        _ launchPath: String,
        _ arguments: [String],
        environment extraEnvironment: [String: String] = [:]
    ) -> CommandResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = arguments

        // GUI apps don't inherit the user's shell PATH; use resolved PATH
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = Self.resolvedPATH
        for (key, value) in extraEnvironment {
            env[key] = value
        }
        process.environment = env

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        do {
            try process.run()

            // Read both pipes concurrently to avoid deadlock when pipe buffer (64KB) fills.
            // If we read sequentially or after waitUntilExit, the child can block on write.
            let maxBuffer = 65536
            var outData = Data()
            var errData = Data()

            let group = DispatchGroup()

            group.enter()
            DispatchQueue.global(qos: .utility).async {
                let d = outPipe.fileHandleForReading.readDataToEndOfFile()
                outData = d.count > maxBuffer ? d.prefix(maxBuffer) : d
                group.leave()
            }

            group.enter()
            DispatchQueue.global(qos: .utility).async {
                let d = errPipe.fileHandleForReading.readDataToEndOfFile()
                errData = d.count > maxBuffer ? d.prefix(maxBuffer) : d
                group.leave()
            }

            process.waitUntilExit()
            group.wait()

            let out = String(data: outData, encoding: .utf8) ?? ""
            let err = String(data: errData, encoding: .utf8) ?? ""

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

private struct ContentHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

private struct WorkspaceResizeDivider: View {
    @Binding var height: Double
    let maxHeight: Double
    private let minHeight: Double = 100
    @GestureState private var dragStartHeight: Double? = nil
    @State private var isHovered = false
    @State private var isDragging = false

    var body: some View {
        ZStack {
            // 1pt visual line
            Rectangle()
                .fill(isDragging
                    ? GhosttyTheme.current.accentCyan.opacity(0.6)
                    : GhosttyTheme.current.foreground.opacity(isHovered ? 0.2 : 0.08))
                .frame(height: 1)

            // Grip handle (3 capsules, visible on hover/drag)
            HStack(spacing: 2) {
                ForEach(0..<3, id: \.self) { _ in
                    Capsule()
                        .fill(isDragging
                            ? GhosttyTheme.current.accentCyan.opacity(0.5)
                            : GhosttyTheme.current.foreground.opacity(0.3))
                        .frame(width: 12, height: 2)
                }
            }
            .opacity(isHovered || isDragging ? 1 : 0)
        }
        .frame(height: 20)
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
        .onHover { inside in
            isHovered = inside
            if inside { NSCursor.resizeUpDown.push() }
            else { NSCursor.pop() }
        }
        .gesture(
            DragGesture(coordinateSpace: .global)
                .updating($dragStartHeight) { _, state, _ in
                    if state == nil { state = height }
                }
                .onChanged { value in
                    isDragging = true
                    let base = dragStartHeight ?? height
                    height = min(max(base + value.translation.height, minHeight), maxHeight)
                }
                .onEnded { _ in
                    isDragging = false
                }
        )
        .animation(.easeOut(duration: 0.14), value: isHovered)
        .animation(.easeOut(duration: 0.14), value: isDragging)
    }
}

// Functional resize handle at the window bottom edge
private struct WindowResizeGrip: View {
    @State private var isHovered = false

    var body: some View {
        ZStack {
            BottomEdgeResizeHandle(isHovered: $isHovered)
            HStack(spacing: 3) {
                ForEach(0..<3, id: \.self) { _ in
                    Circle()
                        .fill(GhosttyTheme.current.foreground.opacity(isHovered ? 0.5 : 0.2))
                        .frame(width: 4, height: 4)
                }
            }
            .allowsHitTesting(false)
            .animation(.easeOut(duration: 0.14), value: isHovered)
        }
        .frame(height: 20)
        .frame(maxWidth: .infinity)
    }
}

private struct BottomEdgeResizeHandle: NSViewRepresentable {
    @Binding var isHovered: Bool

    func makeNSView(context: Context) -> NSView {
        let view = ResizeHandleView()
        view.onHoverChange = { [weak view] hovering in
            guard view != nil else { return }
            DispatchQueue.main.async { isHovered = hovering }
        }
        return view
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

private final class ResizeHandleView: NSView {
    var onHoverChange: ((Bool) -> Void)?
    private var initialFrame: NSRect = .zero
    private var initialMouseY: CGFloat = 0
    private var trackingArea: NSTrackingArea?

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let existing = trackingArea { removeTrackingArea(existing) }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .resizeUpDown)
    }

    override func mouseEntered(with event: NSEvent) {
        onHoverChange?(true)
    }

    override func mouseExited(with event: NSEvent) {
        onHoverChange?(false)
    }

    override func mouseDown(with event: NSEvent) {
        guard let window = window else { return }
        initialFrame = window.frame
        initialMouseY = NSEvent.mouseLocation.y
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window = window else { return }
        let currentY = NSEvent.mouseLocation.y
        let deltaY = initialMouseY - currentY
        let minHeight: CGFloat = 520
        let newHeight = max(minHeight, initialFrame.height + deltaY)
        let newY = initialFrame.maxY - newHeight
        let newFrame = NSRect(
            x: initialFrame.minX, y: newY,
            width: initialFrame.width, height: newHeight
        )
        window.setFrame(newFrame, display: true)
    }

    override func mouseUp(with event: NSEvent) {
        guard let window = window else { return }
        NotificationCenter.default.post(
            name: .tprojUserResizeFinished, object: window
        )
    }
}

extension Notification.Name {
    static let tprojUserResizeFinished = Notification.Name("tprojUserResizeFinished")
}

struct ContentView: View {
    @StateObject private var vm = AppViewModel()
    @StateObject private var ghosttyTracker = GhosttyWindowTracker()
    @StateObject private var windowLevelController = WindowLevelController()
    @StateObject private var collapseController = WindowCollapseController()
    @StateObject private var underlayController = PaneBackgroundUnderlayController()
    @AppStorage("workspaceSectionHeight") private var workspaceHeight: Double = 480
    @AppStorage("monitorSectionHeight") private var monitorHeight: Double = -1
    @AppStorage("windowWidth") private var persistedWidth: Double = 242
    @AppStorage("windowHeight") private var persistedHeight: Double = 585
    @AppStorage("workspaceSectionCollapsed") private var workspaceCollapsed = false
    @AppStorage("memorySectionCollapsed") private var memoryCollapsed = false
    @AppStorage("ccCdxSectionCollapsed") private var ccCdxCollapsed = true
    @AppStorage("autoZoomEnabled") private var autoZoomEnabled = false
    @State private var draggingColumnID: Int?
    @State private var dropInsertionIndex: Int?
    @State private var isDragActive = false
    @State private var didRecoverWindowFrame = false

    private func setDragLock(_ locked: Bool) {
        ghosttyTracker.isDragSuspended = locked
        guard !collapseController.isCollapsed,
              let w = (NSApp.delegate as? AppDelegate)?.mainWindow else { return }
        w.isMovableByWindowBackground = !locked
        w.isMovable = !locked
    }

    var body: some View {
        if collapseController.isCollapsed {
            CollapsedBarView {
                collapseController.toggle(ghosttyTracker: ghosttyTracker)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(GhosttyTheme.current.background.ignoresSafeArea())
            .background(
                WindowAccessor { window in
                    (NSApp.delegate as? AppDelegate)?.mainWindow = window
                    collapseController.attach(to: window)
                    underlayController.attach(to: window)
                    ghosttyTracker.attach(to: window)
                    if !didRecoverWindowFrame {
                        disableWindowFrameRestoration(window)
                        observeWindowResize(window)
                        didRecoverWindowFrame = true
                    }
                }
            )
        } else {
            normalContentView
        }
    }

    private var workspaceRowCount: Int {
        vm.liveColumns.count + vm.inactiveProjects.count
    }

    @ViewBuilder
    private var workspaceControlHeader: some View {
        HStack(spacing: 4) {
            if ghosttyTracker.isSnapped {
                Circle()
                    .fill(GhosttyTheme.current.accentCyan)
                    .frame(width: 5, height: 5)
                    .shadow(color: GhosttyTheme.current.accentCyan.opacity(0.6), radius: 2)
            }
            Text(compactStatus(vm.statusText))
                .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                .foregroundStyle(GhosttyTheme.current.textSecondary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer()
            ActionButton("Stop", tone: .danger, isEnabled: !vm.isBusy && !vm.liveColumns.isEmpty, dense: true) {
                vm.pendingSessionAction = .stop
            }
            .fixedSize()
            ActionButton("Learn", tone: vm.isMIDILearning ? .primary : .neutral, isEnabled: !vm.isBusy, dense: true) {
                vm.toggleMIDILearn()
            }
            .fixedSize()
            ActionButton("Zoom", tone: autoZoomEnabled ? .primary : .neutral, isEnabled: !vm.isBusy, dense: true) {
                autoZoomEnabled.toggle()
                vm.toggleAutoZoom(autoZoomEnabled)
            }
            .frame(width: 38)
        }
        .padding(.trailing, 2)
    }

    @ViewBuilder
    private var workspaceListContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            if vm.liveColumns.isEmpty {
                startupDiagView()
                    .font(GhosttyTheme.current.font(size: 12, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            } else {
                ForEach(Array(vm.liveColumns.enumerated()), id: \.element.id) { indexedColumn in
                    let insertionIndex = indexedColumn.offset
                    let column = indexedColumn.element

                    dropInsertionGap(index: insertionIndex)
                        .onDrop(
                            of: [UTType.text],
                            delegate: GapDropDelegate(
                                insertionIndex: insertionIndex,
                                totalCount: vm.liveColumns.count,
                                draggingColumnID: $draggingColumnID,
                                dropInsertionIndex: $dropInsertionIndex,
                                isDragActive: $isDragActive,
                                viewModel: vm
                            )
                        )

                    liveColumnRow(column)
                        .onDrop(
                            of: [UTType.text],
                            delegate: RowDropFallbackDelegate(
                                rowIndex: insertionIndex,
                                totalCount: vm.liveColumns.count,
                                draggingColumnID: $draggingColumnID,
                                dropInsertionIndex: $dropInsertionIndex,
                                isDragActive: $isDragActive,
                                viewModel: vm
                            )
                        )
                }
                // Trailing drop gap
                dropInsertionGap(index: vm.liveColumns.count)
                    .onDrop(
                        of: [UTType.text],
                        delegate: GapDropDelegate(
                            insertionIndex: vm.liveColumns.count,
                            totalCount: vm.liveColumns.count,
                            draggingColumnID: $draggingColumnID,
                            dropInsertionIndex: $dropInsertionIndex,
                            isDragActive: $isDragActive,
                            viewModel: vm
                        )
                    )
            }
            ForEach(vm.inactiveProjects) { project in
                inactiveProjectRow(project)
            }
        }
    }

    @ViewBuilder
    private var upperRemainingSections: some View {
        SectionHeader(title: "Memory", isCollapsed: $memoryCollapsed)
        if !memoryCollapsed {
            Card(compact: true, chrome: false) {
                memorySection()
            }
        }

        SectionHeader(title: "CC & Codex", isCollapsed: $ccCdxCollapsed)
        if !ccCdxCollapsed {
            Card(compact: true, chrome: false) {
                monitorSection()
            }
        }
    }

    @ViewBuilder
    private var yamlFooter: some View {
        VStack(alignment: .leading, spacing: 4) {
            SectionHeader(title: "Workspace YAML")
            Card {
                HStack(spacing: 0) {
                    ActionButton("Open workspace.yaml", tone: .neutral, isEnabled: !vm.isBusy, dense: true) {
                        vm.openWorkspaceYAML()
                    }
                    Spacer(minLength: 0)
                }
            }
            // Bottom resize grip indicator
            WindowResizeGrip()
        }
        .padding(.horizontal, 4)
        .padding(.bottom, 2)
    }

    @ViewBuilder
    private var normalContentView: some View {
        ZStack {
            GhosttyTheme.current.background
                .opacity(GhosttyTheme.current.appBackgroundOpacity)
                .ignoresSafeArea()

            if workspaceRowCount < 10 {
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        SectionHeader(title: "Current Workspace", isCollapsed: $workspaceCollapsed)
                        if !workspaceCollapsed {
                            Card(compact: true, chrome: false) {
                                workspaceControlHeader
                                workspaceListContent
                            }
                        }
                        upperRemainingSections
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 4)
                    .padding(.top, 4)
                }
                .frame(maxWidth: .infinity)
                .safeAreaInset(edge: .bottom, spacing: 0) { yamlFooter }
            } else {
                GeometryReader { geo in
                    let maxH = geo.size.height * 0.8
                    VStack(alignment: .leading, spacing: 0) {
                        // -- Top: Current Workspace --
                        SectionHeader(title: "Current Workspace", isCollapsed: $workspaceCollapsed)
                            .padding(.horizontal, 4)
                            .padding(.top, 4)

                        if !workspaceCollapsed {
                            VStack(alignment: .leading, spacing: 4) {
                                Card(compact: true, chrome: false) {
                                    workspaceControlHeader
                                    ScrollView {
                                        workspaceListContent
                                    }
                                }
                            }
                            .frame(height: workspaceHeight)
                            .padding(.horizontal, 4)
                            .clipped()

                            WorkspaceResizeDivider(height: $workspaceHeight, maxHeight: maxH)
                        }

                        // -- Middle: Memory / CC & Codex (fills remaining space) --
                        ScrollView {
                            VStack(alignment: .leading, spacing: 4) {
                                upperRemainingSections
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 4)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                .safeAreaInset(edge: .bottom, spacing: 0) { yamlFooter }
            }
        }
        .overlay(alignment: .topTrailing) {
            Button(action: { collapseController.toggle(ghosttyTracker: ghosttyTracker) }) {
                Image(systemName: "chevron.compact.left")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
                    .frame(width: 20, height: 20)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.top, 5)
            .padding(.trailing, 4)
        }
        .preferredColorScheme(.dark)
        .task {
            vm.onAppear()
            vm.toggleAutoZoom(autoZoomEnabled)
        }
        .onChange(of: vm.isBusy) { busy in
            if !busy, draggingColumnID == nil {
                dropInsertionIndex = nil
                isDragActive = false
            }
        }
        .onChange(of: isDragActive) { dragging in
            setDragLock(dragging)
        }
        .onChange(of: ghosttyTracker.isDragSuspended) { suspended in
            if !suspended {
                setDragLock(false)
                isDragActive = false
                draggingColumnID = nil
            }
        }
        .background(
            WindowAccessor { window in
                (NSApp.delegate as? AppDelegate)?.mainWindow = window
                collapseController.attach(to: window)
                windowLevelController.attach(to: window)
                underlayController.attach(to: window)
                if GhosttyTheme.current.backgroundOpacity < 1.0 {
                    window.backgroundColor = .clear
                    window.isOpaque = false
                }
                if !didRecoverWindowFrame {
                    disableWindowFrameRestoration(window)
                    observeWindowResize(window)
                    recoverWindowFrameIfNeeded(window)
                    window.makeKeyAndOrderFront(nil)
                    NSApp.activate(ignoringOtherApps: true)
                    didRecoverWindowFrame = true
                }
                // Disable window-move-by-background so it does not steal
                // drag gestures from workspace column reordering.
                window.isMovableByWindowBackground = false
                ghosttyTracker.attach(to: window)
            }
        )
        .alert(
            "Stop Session",
            isPresented: Binding<Bool>(
                get: { vm.pendingSessionAction != nil },
                set: { if !$0 { vm.pendingSessionAction = nil } }
            )
        ) {
            Button("Cancel", role: .cancel) {
                vm.pendingSessionAction = nil
            }
            Button("Stop", role: .destructive) {
                vm.pendingSessionAction = nil
                Task { await vm.stopSession() }
            }
        } message: {
            Text("All panes will be stopped.")
        }
        .onReceive(NotificationCenter.default.publisher(for: .flipSnapSide)) { _ in
            ghosttyTracker.flipSide()
            if !collapseController.isCollapsed {
                collapseController.toggle(ghosttyTracker: ghosttyTracker)
            }
        }
    }

    private func disableWindowFrameRestoration(_ window: NSWindow) {
        // Prevent delayed scene/window restoration from overriding snap coordinates.
        _ = window.setFrameAutosaveName("")
        window.isRestorable = false
        // Apply persisted size (origin is handled by snap logic)
        let currentOrigin = window.frame.origin
        let targetSize = NSSize(width: max(14, persistedWidth), height: max(520, persistedHeight))
        window.setFrame(NSRect(origin: currentOrigin, size: targetSize), display: true)
    }

    private func persistWindowSize(_ window: NSWindow) {
        persistedWidth = Double(window.frame.width)
        persistedHeight = Double(window.frame.height)
    }

    private func observeWindowResize(_ window: NSWindow) {
        // Only save when user actually finished dragging the resize edge
        NotificationCenter.default.addObserver(
            forName: NSWindow.didEndLiveResizeNotification,
            object: window,
            queue: .main
        ) { [self] _ in
            self.persistWindowSize(window)
        }
        // Custom bottom grip drag end
        NotificationCenter.default.addObserver(
            forName: .tprojUserResizeFinished,
            object: window,
            queue: .main
        ) { [self] _ in
            self.persistWindowSize(window)
        }
    }

    private func recoverWindowFrameIfNeeded(_ window: NSWindow) {
        if let ghosttyFrame = currentGhosttyFrame() {
            let size = window.frame.size
            let x = ghosttyFrame.minX - size.width
            let y = ghosttyFrame.maxY - size.height
            let targetOrigin = clampedWindowOrigin(NSPoint(x: x, y: y), size: size)
            window.setFrameOrigin(targetOrigin)
            return
        }

        let current = window.frame
        let visibleScreens = NSScreen.screens.map { $0.visibleFrame }
        let isVisible = visibleScreens.contains { screen in
            current.intersects(screen.insetBy(dx: -40, dy: -40))
        }
        guard !isVisible else { return }

        guard let main = NSScreen.main?.visibleFrame ?? NSScreen.screens.first?.visibleFrame else { return }
        let x = main.minX + 24
        let y = max(main.minY + 24, main.maxY - current.height - 24)
        window.setFrameOrigin(NSPoint(x: x, y: y))
    }

    private func clampedWindowOrigin(_ origin: NSPoint, size: CGSize) -> NSPoint {
        let frames = NSScreen.screens.map { $0.visibleFrame }
        guard var union = frames.first else { return origin }
        for frame in frames.dropFirst() {
            union = union.union(frame)
        }
        let maxX = max(union.minX, union.maxX - size.width)
        let maxY = max(union.minY, union.maxY - size.height)
        return NSPoint(
            x: min(max(origin.x, union.minX), maxX),
            y: min(max(origin.y, union.minY), maxY)
        )
    }

    private func liveColumnRow(_ column: LiveColumn) -> some View {
        let isDragging = draggingColumnID == column.column

        return VStack(alignment: .leading, spacing: 3) {
            // Header row
            HStack(spacing: 4) {
                Text("#\(column.column)")
                    .font(GhosttyTheme.current.font(size: 11, weight: .heavy, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textPrimary)
                pill(liveHostLabel(column), tint: column.hostLabel == "local" ? GhosttyTheme.current.accentGreen : GhosttyTheme.current.accentYellow)
                Text(columnPrimaryName(column))
                    .font(GhosttyTheme.current.font(size: 12, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.textPrimary)
                    .lineLimit(1)
                Text(columnPaneCountsText(column))
                    .font(GhosttyTheme.current.font(size: 9, weight: .semibold, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                    .lineLimit(1)
                Spacer()
            }

            if let agents = columnAgentNamesText(column) {
                Text(agents)
                    .font(GhosttyTheme.current.font(size: 9, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }

            // Buttons row
            HStack(spacing: 1) {
                Spacer()
                ActionButton("Cdx", tone: column.codexPaneIDs.isEmpty ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleAIPane(role: "codex", for: column) }
                }
                .frame(width: 38)
                ActionButton("CC", tone: column.claudePaneIDs.isEmpty ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleAIPane(role: "claude", for: column) }
                }
                .frame(width: 38)
                ActionButton("Yazi", tone: column.yaziPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleYazi(for: column) }
                }
                .frame(width: 38)
                ActionButton("Term", tone: column.terminalPaneID == nil ? .neutral : .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.toggleTerminal(for: column) }
                }
                .frame(width: 38)
                ActionButton("Drop", tone: .danger, isEnabled: !vm.isBusy && !vm.isDropPending(column.column), dense: true) {
                    Task { await vm.removeColumn(column) }
                }
                .frame(width: 38)
            }
        }
        .padding(.vertical, 2)
        .padding(.leading, 10)   // accent bar との間隔確保
        .padding(.trailing, 2)
        .background(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(isDragging ? GhosttyTheme.current.accentCyan.opacity(0.15)
                      : GhosttyTheme.current.foreground.opacity(0.05))
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1)
                .fill(GhosttyTheme.current.accentCyan)
                .frame(width: 2)
                .shadow(color: GhosttyTheme.current.accentCyan.opacity(0.7), radius: 3, x: 0, y: 0)
        }
        .overlay(
            isDragging
                ? RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .strokeBorder(GhosttyTheme.current.accentCyan.opacity(0.4), lineWidth: 1)
                : nil
        )
        .padding(.vertical, 1)
        .contentShape(Rectangle())
        .opacity(isDragging ? 0.85 : 1.0)
        .onDrag {
            isDragActive = true
            draggingColumnID = column.column
            dropInsertionIndex = nil
            return NSItemProvider(object: NSString(string: "\(column.column)"))
        }
    }

    private func dropInsertionGap(index: Int) -> some View {
        let isActive = isDragActive && draggingColumnID != nil && dropInsertionIndex == index
        return RoundedRectangle(cornerRadius: 3, style: .continuous)
            .fill(Color.clear)
            .overlay {
                Capsule(style: .continuous)
                    .fill(GhosttyTheme.current.accentCyan.opacity(isActive ? 0.92 : 0.0))
                    .frame(height: 1)
                    .shadow(color: GhosttyTheme.current.accentCyan.opacity(isActive ? 0.55 : 0.0), radius: isActive ? 1.5 : 0, x: 0, y: 0)
            }
            .frame(height: 1)
            .padding(.leading, 10)
            .padding(.trailing, 2)
            .padding(.vertical, 0)
    }

    private func inactiveProjectRow(_ project: WorkspaceProject) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            // Header row (same layout as liveColumnRow)
            HStack(spacing: 4) {
                Text("--")
                    .font(GhosttyTheme.current.font(size: 11, weight: .heavy, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                pill(project.type == "remote" ? "@\(project.host)" : "lcl",
                     tint: project.type == "remote" ? GhosttyTheme.current.accentYellow : GhosttyTheme.current.accentGreen)
                Text(project.effectiveAlias)
                    .font(GhosttyTheme.current.font(size: 12, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.foreground.opacity(0.5))
                    .lineLimit(1)
                Spacer()
            }

            // Button row (Cdx/CC/Yazi/Term disabled, Add enabled)
            HStack(spacing: 1) {
                Spacer()
                ActionButton("Cdx", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("CC", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("Yazi", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("Term", tone: .neutral, isEnabled: false, dense: true) {}
                    .frame(width: 38)
                ActionButton("Add", tone: .primary, isEnabled: !vm.isBusy, dense: true) {
                    Task { await vm.addColumnByAlias(project.effectiveAlias) }
                }
                .frame(width: 38)
            }
        }
        .padding(.vertical, 2)
        .padding(.leading, 10)     // liveColumnRow と揃える
        .padding(.trailing, 2)
        .background(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(GhosttyTheme.current.foreground.opacity(0.03))
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1)
                .fill(GhosttyTheme.current.foreground.opacity(0.2))
                .frame(width: 2)
        }
    }

    @ViewBuilder
    private func startupDiagView() -> some View {
        if let diag = vm.startupDiag {
            let missingRequired = diag.deps.filter { $0.required && !$0.found }
            let missingOptional = diag.deps.filter { !$0.required && !$0.found }

            if !missingRequired.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(missingRequired, id: \.name) { dep in
                        Text("Missing: \(dep.name)  \u{2192}  \(dep.hint)")
                    }
                    if !missingOptional.isEmpty {
                        ForEach(missingOptional, id: \.name) { dep in
                            Text("Optional: \(dep.name)  \u{2192}  \(dep.hint)")
                        }
                    }
                }
            } else if !diag.sessionExists {
                Text("No tproj session  \u{2192}  Run: tproj")
            } else {
                Text("No active columns in tproj-workspace")
            }
        } else {
            Text("Checking dependencies...")
        }
    }

    @ViewBuilder
    private func memorySection() -> some View {
        VStack(alignment: .leading, spacing: 3) {
            if let status = vm.memoryStatus {
                let sys = status.system
                HStack(spacing: 4) {
                    Text("Free \(sys.freeMB)M")
                        .font(GhosttyTheme.current.font(size: 11, weight: .semibold, monospaced: true))
                        .foregroundStyle(memorySeverityColor(freeMB: sys.freeMB))
                    Text("Used \(sys.usedMB)M / \(sys.totalMB)M \(memoryBreakdownText(status.categories))")
                        .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                    if let updated = vm.memoryLastUpdatedAt {
                        Text(updatedTimeText(updated))
                            .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textTertiary)
                    }
                }

                usageBar(usedMB: sys.usedMB, totalMB: sys.totalMB, color: memorySeverityColor(freeMB: sys.freeMB))
                ecosystemBar(status.categories)

                HStack(spacing: 4) {
                    Text("Guard")
                        .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                    Text(status.guardState)
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                        .foregroundStyle(guardColor(status.guardState))
                    Spacer(minLength: 0)
                }

                let columnMap = status.columns.reduce(into: [Int: MonitorColumn]()) { acc, item in
                    acc[item.column] = item
                }
                ForEach(vm.liveColumns.sorted(by: { $0.column < $1.column })) { column in
                    let colMem = columnMap[column.column]
                    HStack(spacing: 4) {
                        Text("#\(column.column)")
                            .font(GhosttyTheme.current.font(size: 10, weight: .heavy, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textSecondary)
                        Text(columnPrimaryName(column))
                            .font(GhosttyTheme.current.font(size: 10, weight: .semibold))
                            .foregroundStyle(GhosttyTheme.current.textSecondary)
                            .lineLimit(1)
                        Spacer(minLength: 0)
                        Text("\(colMem?.ccMB ?? 0)/\(colMem?.codexMB ?? 0)")
                            .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textTertiary)
                        Text("\(colMem?.totalMB ?? 0)M")
                            .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                            .foregroundStyle(GhosttyTheme.current.textPrimary)
                    }
                }
            } else {
                Text("Loading monitor...")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            }

            if let error = vm.memoryErrorText, !error.isEmpty {
                Text(error)
                    .font(GhosttyTheme.current.font(size: 10, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.accentRed.opacity(0.92))
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func monitorSection() -> some View {
        VStack(alignment: .leading, spacing: 3) {
            let panes = vm.memoryStatus?.panes ?? []
            let categories = vm.memoryStatus?.categories ?? [:]
            let ccPanes = panes
                .filter { $0.agentType == "cc" }
                .sorted(by: monitorPaneSort)
            let codexPanes = panes
                .filter { $0.agentType == "codex" }
                .sorted(by: monitorPaneSort)

            monitorGroup(title: "CC", panes: ccPanes, summary: monitorSummaryText(title: "CC", panes: ccPanes, categories: categories))
            monitorGroup(title: "Codex", panes: codexPanes, summary: monitorSummaryText(title: "Codex", panes: codexPanes, categories: categories))

            if panes.isEmpty {
                Text("No pane monitor data")
                    .font(GhosttyTheme.current.font(size: 11, weight: .medium))
                    .foregroundStyle(GhosttyTheme.current.textSecondary)
            } else {
                Text("Legend: C=Claude/CC, M=MCP, X=Codex, O=Other")
                    .font(GhosttyTheme.current.font(size: 9, weight: .medium, monospaced: true))
                    .foregroundStyle(GhosttyTheme.current.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
    }

    @ViewBuilder
    private func monitorGroup(title: String, panes: [MonitorPane], summary: String) -> some View {
        HStack(spacing: 4) {
            Text(title)
                .font(GhosttyTheme.current.font(size: 11, weight: .bold))
                .foregroundStyle(GhosttyTheme.current.textPrimary)
            Text("(\(summary))")
                .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                .foregroundStyle(GhosttyTheme.current.textTertiary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: 0)
        }

        if panes.isEmpty {
            Text("none")
                .font(GhosttyTheme.current.font(size: 10, weight: .medium, monospaced: true))
                .foregroundStyle(GhosttyTheme.current.textTertiary)
        } else {
            ForEach(panes) { pane in
                HStack(spacing: 4) {
                    Text(pane.column.map { "#\($0)" } ?? "--")
                        .font(GhosttyTheme.current.font(size: 10, weight: .heavy, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                    Text(pane.project.isEmpty ? pane.window : pane.project)
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                    Text(paneMetricText(pane))
                        .font(GhosttyTheme.current.font(size: 10, weight: .semibold, monospaced: true))
                        .foregroundStyle(GhosttyTheme.current.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Circle()
                        .fill(paneStateColor(pane.state))
                        .frame(width: 5, height: 5)
                }
            }
        }
    }

    private func usageBar(usedMB: Int, totalMB: Int, color: Color) -> some View {
        let safeTotal = max(totalMB, 1)
        let ratio = min(max(CGFloat(usedMB) / CGFloat(safeTotal), 0), 1)

        return ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(GhosttyTheme.current.foreground.opacity(0.08))
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(color.opacity(0.9))
                .frame(maxWidth: .infinity, alignment: .leading)
                .mask(
                    GeometryReader { proxy in
                        Rectangle()
                            .frame(width: proxy.size.width * ratio, alignment: .leading)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    }
                )
        }
        .frame(height: 6)
    }

    private func ecosystemBar(_ categories: [String: MonitorCategory]) -> some View {
        let parts: [(String, Color)] = [
            ("cc_sessions", GhosttyTheme.current.accentGreen),
            ("mcp_servers", GhosttyTheme.current.accentYellow),
            ("codex", GhosttyTheme.current.accentBlue),
            ("chrome", GhosttyTheme.current.accentCyan),
            ("slack", GhosttyTheme.current.accentRed)
        ]
        let values = parts.map { max(Double(categories[$0.0]?.mb ?? 0), 0) }
        let total = max(values.reduce(0, +), 1)

        return GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(GhosttyTheme.current.foreground.opacity(0.08))
                ForEach(Array(parts.enumerated()), id: \.offset) { idx, pair in
                    let prefix = values.prefix(idx).reduce(0, +)
                    let x = geo.size.width * CGFloat(prefix / total)
                    let width = geo.size.width * CGFloat(values[idx] / total)
                    Rectangle()
                        .fill(pair.1.opacity(0.92))
                        .frame(width: width > 0 ? max(width, 1) : 0, height: 6)
                        .offset(x: x)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 2, style: .continuous))
        }
        .frame(height: 6)
    }

    private func memoryBreakdownText(_ categories: [String: MonitorCategory]) -> String {
        let cc = categories["cc_sessions"]?.mb ?? 0
        let mcp = categories["mcp_servers"]?.mb ?? 0
        let cdx = categories["codex"]?.mb ?? 0
        let chr = categories["chrome"]?.mb ?? 0
        let slk = categories["slack"]?.mb ?? 0
        return "(CC \(cc) | MCP \(mcp) | Cdx \(cdx) | Chr \(chr) | Slk \(slk))"
    }

    private func monitorSummaryText(title: String, panes: [MonitorPane], categories: [String: MonitorCategory]) -> String {
        let totalMB = panes.reduce(0) { $0 + $1.rssMB }
        let active = panes.filter { $0.state.lowercased() == "active" }.count

        if title == "CC" {
            let mcpMB = categories["mcp_servers"]?.mb ?? 0
            let mcpCount = categories["mcp_servers"]?.count ?? 0
            return "\(panes.count), \(totalMB)M, A\(active) | MCP \(mcpMB)/\(mcpCount)"
        }

        let chrMB = categories["chrome"]?.mb ?? 0
        let slkMB = categories["slack"]?.mb ?? 0
        return "\(panes.count), \(totalMB)M, A\(active) | Chr \(chrMB) Slk \(slkMB)"
    }

    private func paneMetricText(_ pane: MonitorPane) -> String {
        let c = pane.bucketCMB
        let m = pane.bucketMMB
        let x = pane.bucketXMB
        let o = pane.bucketOMB

        // Save horizontal space:
        // - CC rows omit X and fold it into O
        // - Codex rows omit C and fold it into O
        if pane.agentType == "cc" {
            return "\(pane.rssMB)M(C\(c)+M\(m)+O\(o + x))"
        }
        if pane.agentType == "codex" {
            return "\(pane.rssMB)M(X\(x)+M\(m)+O\(o + c))"
        }
        return "\(pane.rssMB)M(M\(m)+O\(o + c + x))"
    }

    private func monitorPaneSort(_ lhs: MonitorPane, _ rhs: MonitorPane) -> Bool {
        if lhs.rssMB != rhs.rssMB { return lhs.rssMB > rhs.rssMB }

        let lhsColumn = lhs.column ?? Int.max
        let rhsColumn = rhs.column ?? Int.max
        if lhsColumn != rhsColumn { return lhsColumn < rhsColumn }

        let lhsName = lhs.project.isEmpty ? lhs.window : lhs.project
        let rhsName = rhs.project.isEmpty ? rhs.window : rhs.project
        if lhsName != rhsName { return lhsName.localizedCaseInsensitiveCompare(rhsName) == .orderedAscending }

        return lhs.id < rhs.id
    }

    private func memorySeverityColor(freeMB: Int) -> Color {
        if freeMB <= 200 { return GhosttyTheme.current.accentRed }
        if freeMB <= 500 { return GhosttyTheme.current.accentYellow }
        return GhosttyTheme.current.accentGreen
    }

    private func guardColor(_ state: String) -> Color {
        switch state.lowercased() {
        case "running":
            return GhosttyTheme.current.accentGreen
        case "stopped":
            return GhosttyTheme.current.accentRed
        default:
            return GhosttyTheme.current.textTertiary
        }
    }

    private func paneStateColor(_ state: String) -> Color {
        switch state.lowercased() {
        case "active":
            return GhosttyTheme.current.accentGreen
        case "idle":
            return GhosttyTheme.current.accentYellow
        default:
            return GhosttyTheme.current.textTertiary
        }
    }

    private func updatedTimeText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: date)
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

    private func columnPaneCountsText(_ column: LiveColumn) -> String {
        "CC\(column.claudePaneIDs.count) Cdx\(column.codexPaneIDs.count) Ag\(column.agentPaneIDs.count)"
    }

    private func columnAgentNamesText(_ column: LiveColumn) -> String? {
        let names = column.agentNames.sorted()
        guard !names.isEmpty else { return nil }
        return "Agents: " + names.joined(separator: ", ")
    }

    private func pill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(GhosttyTheme.current.font(size: 9, weight: .bold))
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(
                Capsule(style: .circular)
                    .fill(tint.opacity(0.24))
            )
            .foregroundStyle(tint.opacity(0.95))
    }
}

// MARK: - Collapsed Bar View

struct CollapsedBarView: View {
    let onExpand: () -> Void
    @State private var isHovered = false

    var body: some View {
        Color.clear
            .overlay {
                ZStack {
                    GhosttyTheme.current.accentCyan.opacity(isHovered ? 0.5 : 0.3)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(GhosttyTheme.current.textSecondary)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { onExpand() }
            .onHover { hovering in
                isHovered = hovering
                if hovering {
                    NSCursor.resizeLeftRight.push()
                } else {
                    NSCursor.pop()
                }
            }
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

struct GapDropDelegate: DropDelegate {
    let insertionIndex: Int
    let totalCount: Int
    @Binding var draggingColumnID: Int?
    @Binding var dropInsertionIndex: Int?
    @Binding var isDragActive: Bool
    let viewModel: AppViewModel

    func dropEntered(info: DropInfo) {
        guard isDragActive, draggingColumnID != nil else {
            dropInsertionIndex = nil
            return
        }
        dropInsertionIndex = clampedInsertionIndex
    }

    func dropExited(info: DropInfo) {
        if dropInsertionIndex == clampedInsertionIndex {
            dropInsertionIndex = nil
        }
    }

    func performDrop(info: DropInfo) -> Bool {
        guard let source = draggingColumnID else {
            dropInsertionIndex = nil
            isDragActive = false
            return false
        }
        let destination = clampedInsertionIndex
        dropInsertionIndex = nil
        draggingColumnID = nil
        isDragActive = false
        Task {
            await viewModel.moveColumn(from: source, toInsertionIndex: destination)
        }
        return true
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        guard isDragActive, draggingColumnID != nil else {
            dropInsertionIndex = nil
            return DropProposal(operation: .cancel)
        }
        dropInsertionIndex = clampedInsertionIndex
        return DropProposal(operation: .move)
    }

    private var clampedInsertionIndex: Int {
        min(max(insertionIndex, 0), totalCount)
    }
}

struct RowDropFallbackDelegate: DropDelegate {
    let rowIndex: Int
    let totalCount: Int
    @Binding var draggingColumnID: Int?
    @Binding var dropInsertionIndex: Int?
    @Binding var isDragActive: Bool
    let viewModel: AppViewModel

    func dropEntered(info: DropInfo) {
        guard isDragActive, draggingColumnID != nil else {
            dropInsertionIndex = nil
            return
        }
        dropInsertionIndex = resolvedInsertionIndex(info: info)
    }

    func dropExited(info: DropInfo) {
        let upper = rowIndex
        let lower = min(rowIndex + 1, totalCount)
        if dropInsertionIndex == upper || dropInsertionIndex == lower {
            dropInsertionIndex = nil
        }
    }

    func performDrop(info: DropInfo) -> Bool {
        guard let source = draggingColumnID else {
            dropInsertionIndex = nil
            isDragActive = false
            return false
        }
        let destination = resolvedInsertionIndex(info: info)
        dropInsertionIndex = nil
        draggingColumnID = nil
        isDragActive = false
        Task {
            await viewModel.moveColumn(from: source, toInsertionIndex: destination)
        }
        return true
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        guard isDragActive, draggingColumnID != nil else {
            dropInsertionIndex = nil
            return DropProposal(operation: .cancel)
        }
        dropInsertionIndex = resolvedInsertionIndex(info: info)
        return DropProposal(operation: .move)
    }

    private func resolvedInsertionIndex(info: DropInfo) -> Int {
        let rowMidpoint: CGFloat = 20
        let candidate = info.location.y < rowMidpoint ? rowIndex : rowIndex + 1
        return min(max(candidate, 0), totalCount)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var mainWindow: NSWindow?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    private func logMainWindowEvent(_ event: String, window: NSWindow?) {
        guard let window else {
            NSLog("[main-window] event=%@ window=nil", event)
            return
        }
        NSLog(
            "[main-window] event=%@ number=%ld visible=%d mini=%d key=%d main=%d frame=%@",
            event,
            window.windowNumber,
            window.isVisible ? 1 : 0,
            window.isMiniaturized ? 1 : 0,
            window.isKeyWindow ? 1 : 0,
            window.isMainWindow ? 1 : 0,
            NSStringFromRect(window.frame)
        )
    }

    @discardableResult
    func presentMainWindow() -> Bool {
        guard let window = mainWindow else {
            logMainWindowEvent("present-main-window.missing", window: nil)
            return false
        }
        logMainWindowEvent("present-main-window.before", window: window)
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        logMainWindowEvent("present-main-window.after", window: window)
        return true
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        NSLog("[main-window] event=app-reopen hasVisibleWindows=%d", flag ? 1 : 0)
        if !flag {
            if presentMainWindow() {
                NSLog("[main-window] event=app-reopen action=reuse-existing")
                return false
            }
            NSApp.activate(ignoringOtherApps: true)
            NSLog("[main-window] event=app-reopen action=activate-without-window")
            return true
        }
        return false
    }
}

private struct FlipSideButton: View {
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Button("Flip Side") {
            // Ensure window is visible before flipping
            if (NSApp.delegate as? AppDelegate)?.presentMainWindow() != true {
                NSLog("[main-window] event=flip-side action=open-window")
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
            }
            // Post flip after a brief delay to let the window appear and snap
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                NotificationCenter.default.post(name: .flipSnapSide, object: nil)
            }
        }
        .keyboardShortcut("f", modifiers: [.command, .shift])
    }
}

@main
struct TprojApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        clearWindowFrameAutosave()
        loadAppIcon()
    }

    var body: some Scene {
        Window("tproj", id: "main") {
            ContentView()
                .frame(minWidth: 14, maxWidth: 550, minHeight: 520, idealHeight: 980, maxHeight: 2200)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 242, height: 585)
        .windowResizability(.contentMinSize)

        MenuBarExtra("tproj", systemImage: "rectangle.split.3x1") {
            FlipSideButton()
            Divider()
            Button("Quit tproj") { NSApp.terminate(nil) }
        }
    }

    private func loadAppIcon() {
        // 1. .app bundle (dist): icon registered via Info.plist CFBundleIconFile
        if let iconPath = Bundle.main.path(forResource: "AppIcon", ofType: "icns"),
           let icon = NSImage(contentsOfFile: iconPath) {
            NSApplication.shared.applicationIconImage = icon
            return
        }

        // 2. Development build: resolve from executable path
        //    .build/arm64-apple-macosx/debug/tproj -> ../../../Resources/AppIcon.icns
        let execURL = URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            .resolvingSymlinksInPath()
        let devIcon = execURL
            .deletingLastPathComponent()  // debug/
            .deletingLastPathComponent()  // arm64-apple-macosx/
            .deletingLastPathComponent()  // .build/
            .appendingPathComponent("Resources/AppIcon.icns")
        if let icon = NSImage(contentsOfFile: devIcon.path) {
            NSApplication.shared.applicationIconImage = icon
        }
    }

    private func clearWindowFrameAutosave() {
        let defaults = UserDefaults.standard
        let keys = defaults.dictionaryRepresentation().keys.filter { $0.hasPrefix("NSWindow Frame ") }
        guard !keys.isEmpty else { return }
        for key in keys {
            defaults.removeObject(forKey: key)
        }
    }
}
