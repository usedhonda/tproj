import Foundation

/// Fast follow is useful during motion, not while two snapped windows sit idle.
/// Call after every observation, including absence and suspended drag handling.
public struct WindowFollowPollingCadence {
    public static let idleMilliseconds = 100
    public static let movingMilliseconds = 16
    public static let absentMilliseconds = 500

    private var previousTargetFrame: CGRect?
    private var previousFollowerFrame: CGRect?
    private var fastUntil: TimeInterval?

    public init() {}

    /// `now` is monotonic uptime, so wall-clock changes cannot extend a burst.
    public mutating func intervalMilliseconds(
        targetFrame: CGRect?,
        followerFrame: CGRect,
        isSnapped: Bool,
        isDragging: Bool,
        isSuspended: Bool,
        now: TimeInterval
    ) -> Int {
        defer {
            previousTargetFrame = targetFrame
            previousFollowerFrame = followerFrame
        }
        guard let targetFrame else {
            fastUntil = nil
            return Self.absentMilliseconds
        }
        guard !isSuspended else {
            fastUntil = nil
            return Self.idleMilliseconds
        }

        let moved = previousTargetFrame.map { $0 != targetFrame } ?? false
        let followerMoved = previousFollowerFrame.map { $0 != followerFrame } ?? false
        if moved || followerMoved || isDragging {
            fastUntil = now + 0.25
        }
        if isSnapped, let fastUntil, now < fastUntil {
            return Self.movingMilliseconds
        }
        return Self.idleMilliseconds
    }
}

/// Interpret the first observation after an idle interval before resuming fast
/// polling. Target motion must not look like the person detached the sidebar.
public struct SnappedWindowFollowDecision {
    public let shouldDetach: Bool
    public let shouldAlignTop: Bool

    public init(targetFrame: CGRect, previousTargetFrame: CGRect?,
                followerFrame: CGRect, previousFollowerFrame: CGRect?,
                anchoredOrigin: CGPoint, detachDistance: CGFloat,
                topAlignmentDistance: CGFloat) {
        let targetMotion = previousTargetFrame.map { previous in
            max(hypot(targetFrame.minX - previous.minX, targetFrame.minY - previous.minY),
                max(abs(targetFrame.maxX - previous.maxX), abs(targetFrame.maxY - previous.maxY)))
        } ?? 0
        let followerResized = previousFollowerFrame.map {
            abs(followerFrame.width - $0.width) >= 0.5 || abs(followerFrame.height - $0.height) >= 0.5
        } ?? false
        shouldDetach = abs(followerFrame.minX - anchoredOrigin.x) >= detachDistance &&
            targetMotion < 2 && !followerResized

        let topGap = abs(followerFrame.maxY - targetFrame.maxY)
        let retainedTopAlignment: Bool
        if let previousTargetFrame, let previousFollowerFrame {
            let wasAligned = abs(previousFollowerFrame.maxY - previousTargetFrame.maxY) < 0.5
            let followerTopUnchanged = abs(followerFrame.maxY - previousFollowerFrame.maxY) < 0.5
            let targetTopMoved = abs(targetFrame.maxY - previousTargetFrame.maxY) >= 0.5
            retainedTopAlignment = wasAligned && ((followerTopUnchanged && targetTopMoved) || followerResized)
        } else {
            retainedTopAlignment = false
        }
        shouldAlignTop = topGap <= topAlignmentDistance || retainedTopAlignment
    }
}
