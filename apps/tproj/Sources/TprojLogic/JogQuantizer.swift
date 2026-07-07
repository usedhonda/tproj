import Foundation

// Relative-CC jog-wheel quantizer, extracted verbatim from
// MIDIPaneActivator.handleJog (S-D3). Pure value type so the firing timing/count
// can be unit-tested without CoreMIDI or the executable target.
//
// `now` is injected (rather than reading Date() internally) so tests can drive
// deterministic timelines. The caller sets ticksPerStep / minStepInterval from
// its live config before each feed, preserving the original read-fresh semantics.
public struct JogQuantizer {
    // Fire one step per this many accumulated ticks of rotation.
    public var ticksPerStep: Int
    // Minimum wall-clock gap between fired steps (rate limit).
    public var minStepInterval: Double

    private var accumulator = 0
    private var lastDirection = 0
    private var lastStepAt: Date = .distantPast

    public init(ticksPerStep: Int, minStepInterval: Double) {
        self.ticksPerStep = ticksPerStep
        self.minStepInterval = minStepInterval
    }

    // Feed one relative-CC data byte. Returns +1 / -1 when a focus step should
    // fire, or nil when the rotation is still accumulating / rate-limited.
    public mutating func feed(data2: UInt8, now: Date) -> Int? {
        // Two's-complement relative encoding: 1..63 = clockwise (+), 65..127 = ccw (-).
        let delta = data2 <= 63 ? Int(data2) : Int(data2) - 128
        if delta == 0 { return nil }

        let direction = delta > 0 ? 1 : -1
        // Direction reversal: drop stale accumulation so a flick-back reacts promptly.
        if direction != lastDirection {
            accumulator = 0
            lastDirection = direction
        }
        accumulator += delta

        // Quantize: fire one focus step per ticksPerStep of accumulated rotation,
        // rate-limited by minStepInterval. Reset the accumulator only when firing.
        guard abs(accumulator) >= max(1, ticksPerStep) else { return nil }
        guard now.timeIntervalSince(lastStepAt) >= minStepInterval else { return nil }
        lastStepAt = now
        accumulator = 0
        return direction
    }
}
