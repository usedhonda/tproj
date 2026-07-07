import XCTest
import SwiftUI
import AppKit
@testable import TprojLogic

final class GhosttyConfigParserTests: XCTestCase {
    // Valid 6-digit hex (with or without leading '#') parses to a color.
    func testParseHexValid() {
        XCTAssertNotNil(GhosttyConfigParser.parseHex("#ff0000"))
        XCTAssertNotNil(GhosttyConfigParser.parseHex("00ff00"))
    }

    // Wrong length / non-hex / empty input returns nil (falls back to defaults).
    func testParseHexInvalid() {
        XCTAssertNil(GhosttyConfigParser.parseHex("fff"))      // 3 digits
        XCTAssertNil(GhosttyConfigParser.parseHex("gggggg"))   // non-hex
        XCTAssertNil(GhosttyConfigParser.parseHex(""))
    }

    // Channel mapping: high byte -> red, mid -> green, low -> blue.
    func testParseHexChannelMapping() {
        guard let color = GhosttyConfigParser.parseHex("#ff8000"),
              let ns = NSColor(color).usingColorSpace(.sRGB) else {
            return XCTFail("expected a color in sRGB space")
        }
        XCTAssertEqual(Double(ns.redComponent), 1.0, accuracy: 0.01)
        XCTAssertEqual(Double(ns.greenComponent), 128.0 / 255.0, accuracy: 0.01)
        XCTAssertEqual(Double(ns.blueComponent), 0.0, accuracy: 0.01)
    }
}
