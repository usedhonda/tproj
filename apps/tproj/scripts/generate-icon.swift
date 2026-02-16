#!/usr/bin/env swift
// generate-icon.swift — tproj sailboat icon generator
// Draws a stylized sailboat silhouette on a dark background
// Usage: swift generate-icon.swift <output-dir>

import AppKit
import Foundation

let size: CGFloat = 1024
let outputDir = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : FileManager.default.currentDirectoryPath

// --- Colors (Ghostty-inspired dark palette) ---
let bgColor = NSColor(red: 0.07, green: 0.08, blue: 0.12, alpha: 1.0)
let sailColor = NSColor(red: 0.85, green: 0.88, blue: 0.92, alpha: 1.0)
let hullColor = NSColor(red: 0.55, green: 0.42, blue: 0.30, alpha: 1.0)
let mastColor = NSColor(red: 0.70, green: 0.72, blue: 0.75, alpha: 1.0)
let waveColor = NSColor(red: 0.20, green: 0.45, blue: 0.65, alpha: 0.6)
let waveColor2 = NSColor(red: 0.15, green: 0.35, blue: 0.55, alpha: 0.4)
let accentCyan = NSColor(red: 0.30, green: 0.75, blue: 0.85, alpha: 1.0)
let glowCyan = NSColor(red: 0.30, green: 0.75, blue: 0.85, alpha: 0.15)

func drawIcon(in ctx: NSGraphicsContext, size s: CGFloat) {
    let gc = ctx.cgContext
    let scale = s / 1024.0

    // --- Background: rounded rect ---
    let cornerRadius: CGFloat = s * 0.20
    let bgRect = NSRect(x: 0, y: 0, width: s, height: s)
    let bgPath = NSBezierPath(roundedRect: bgRect, xRadius: cornerRadius, yRadius: cornerRadius)
    bgColor.setFill()
    bgPath.fill()

    // --- Subtle radial gradient overlay (depth) ---
    let gradColors = [
        NSColor(white: 1.0, alpha: 0.06).cgColor,
        NSColor(white: 0.0, alpha: 0.0).cgColor,
    ] as CFArray
    if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                                  colors: gradColors, locations: [0.0, 1.0]) {
        gc.saveGState()
        // Clip to rounded rect
        let clipPath = CGPath(roundedRect: bgRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)
        gc.addPath(clipPath)
        gc.clip()
        gc.drawRadialGradient(gradient,
                              startCenter: CGPoint(x: s * 0.45, y: s * 0.65),
                              startRadius: 0,
                              endCenter: CGPoint(x: s * 0.45, y: s * 0.65),
                              endRadius: s * 0.55,
                              options: [])
        gc.restoreGState()
    }

    // --- Water waves (3 layers, bottom portion) ---
    func drawWave(yBase: CGFloat, amplitude: CGFloat, wavelength: CGFloat,
                  phase: CGFloat, color: NSColor, lineWidth: CGFloat) {
        let wave = NSBezierPath()
        wave.move(to: NSPoint(x: 0, y: yBase))
        var x: CGFloat = 0
        while x <= s {
            let y = yBase + sin((x / wavelength + phase) * .pi * 2) * amplitude
            wave.line(to: NSPoint(x: x, y: y))
            x += 2 * scale
        }
        // Close path below
        wave.line(to: NSPoint(x: s, y: 0))
        wave.line(to: NSPoint(x: 0, y: 0))
        wave.close()

        gc.saveGState()
        let clipPath = CGPath(roundedRect: bgRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)
        gc.addPath(clipPath)
        gc.clip()
        color.setFill()
        wave.fill()
        gc.restoreGState()
    }

    drawWave(yBase: s * 0.28, amplitude: s * 0.018, wavelength: s * 0.22,
             phase: 0.0, color: waveColor2, lineWidth: 2 * scale)
    drawWave(yBase: s * 0.25, amplitude: s * 0.022, wavelength: s * 0.18,
             phase: 0.3, color: waveColor, lineWidth: 2.5 * scale)
    drawWave(yBase: s * 0.22, amplitude: s * 0.015, wavelength: s * 0.25,
             phase: 0.7, color: waveColor2, lineWidth: 2 * scale)

    // --- Hull (curved bottom of ship) ---
    let hull = NSBezierPath()
    let hullLeft = s * 0.22
    let hullRight = s * 0.72
    let hullTop = s * 0.32
    let hullBottom = s * 0.22
    let hullMid = (hullLeft + hullRight) / 2

    hull.move(to: NSPoint(x: hullLeft, y: hullTop))
    hull.line(to: NSPoint(x: hullRight, y: hullTop))
    // Stern (right side, slightly raised)
    hull.curve(to: NSPoint(x: hullRight + s * 0.03, y: hullTop + s * 0.02),
               controlPoint1: NSPoint(x: hullRight + s * 0.02, y: hullTop),
               controlPoint2: NSPoint(x: hullRight + s * 0.03, y: hullTop + s * 0.01))
    // Bottom curve
    hull.curve(to: NSPoint(x: hullMid, y: hullBottom),
               controlPoint1: NSPoint(x: hullRight + s * 0.01, y: hullBottom + s * 0.02),
               controlPoint2: NSPoint(x: hullMid + s * 0.10, y: hullBottom))
    hull.curve(to: NSPoint(x: hullLeft - s * 0.02, y: hullTop + s * 0.02),
               controlPoint1: NSPoint(x: hullMid - s * 0.12, y: hullBottom),
               controlPoint2: NSPoint(x: hullLeft - s * 0.01, y: hullBottom + s * 0.04))
    // Bow (left side, pointed)
    hull.curve(to: NSPoint(x: hullLeft, y: hullTop),
               controlPoint1: NSPoint(x: hullLeft - s * 0.02, y: hullTop + s * 0.01),
               controlPoint2: NSPoint(x: hullLeft - s * 0.01, y: hullTop))
    hull.close()

    // Hull shadow
    gc.saveGState()
    let clipPath2 = CGPath(roundedRect: bgRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)
    gc.addPath(clipPath2)
    gc.clip()
    NSColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.3).setFill()
    let shadowHull = hull.copy() as! NSBezierPath
    let shadowTransform = AffineTransform(translationByX: 0, byY: -s * 0.008)
    shadowHull.transform(using: shadowTransform)
    shadowHull.fill()
    gc.restoreGState()

    hullColor.setFill()
    hull.fill()

    // Hull deck line
    let deckLine = NSBezierPath()
    deckLine.move(to: NSPoint(x: hullLeft + s * 0.02, y: hullTop - s * 0.005))
    deckLine.line(to: NSPoint(x: hullRight - s * 0.02, y: hullTop - s * 0.005))
    NSColor(red: 0.65, green: 0.52, blue: 0.40, alpha: 1.0).setStroke()
    deckLine.lineWidth = 2.5 * scale
    deckLine.stroke()

    // --- Mast (vertical line from hull center) ---
    let mastX = hullMid - s * 0.02
    let mastBottom = hullTop
    let mastTop = s * 0.82

    let mast = NSBezierPath()
    mast.move(to: NSPoint(x: mastX, y: mastBottom))
    mast.line(to: NSPoint(x: mastX, y: mastTop))
    mastColor.setStroke()
    mast.lineWidth = 4.5 * scale
    mast.lineCapStyle = .round
    mast.stroke()

    // --- Main sail (large triangle, billowing) ---
    let sail1 = NSBezierPath()
    let sailTop = mastTop - s * 0.02
    let sailBottom = hullTop + s * 0.04
    let sailRight = mastX + s * 0.28

    sail1.move(to: NSPoint(x: mastX + s * 0.01, y: sailTop))
    // Billowing curve to the right
    sail1.curve(to: NSPoint(x: sailRight, y: (sailTop + sailBottom) * 0.52),
                controlPoint1: NSPoint(x: mastX + s * 0.15, y: sailTop - s * 0.02),
                controlPoint2: NSPoint(x: sailRight + s * 0.04, y: (sailTop + sailBottom) * 0.6))
    sail1.curve(to: NSPoint(x: mastX + s * 0.01, y: sailBottom),
                controlPoint1: NSPoint(x: sailRight - s * 0.02, y: sailBottom + s * 0.08),
                controlPoint2: NSPoint(x: mastX + s * 0.04, y: sailBottom + s * 0.01))
    sail1.close()

    // Sail glow effect
    gc.saveGState()
    gc.addPath(clipPath2)
    gc.clip()
    glowCyan.setFill()
    let glowSail = sail1.copy() as! NSBezierPath
    let glowTransform = AffineTransform(scaleByX: 1.08, byY: 1.04)
    glowSail.transform(using: glowTransform)
    glowSail.fill()
    gc.restoreGState()

    sailColor.setFill()
    sail1.fill()

    // Sail subtle shading (gradient-like with overlapping shapes)
    let sailShade = NSBezierPath()
    sailShade.move(to: NSPoint(x: mastX + s * 0.01, y: sailTop))
    sailShade.curve(to: NSPoint(x: mastX + s * 0.12, y: (sailTop + sailBottom) * 0.55),
                    controlPoint1: NSPoint(x: mastX + s * 0.06, y: sailTop - s * 0.01),
                    controlPoint2: NSPoint(x: mastX + s * 0.12, y: (sailTop + sailBottom) * 0.6))
    sailShade.curve(to: NSPoint(x: mastX + s * 0.01, y: sailBottom),
                    controlPoint1: NSPoint(x: mastX + s * 0.10, y: sailBottom + s * 0.06),
                    controlPoint2: NSPoint(x: mastX + s * 0.03, y: sailBottom + s * 0.01))
    sailShade.close()
    NSColor(white: 0.0, alpha: 0.06).setFill()
    sailShade.fill()

    // --- Jib sail (smaller front triangle) ---
    let jib = NSBezierPath()
    let jibTop = mastTop - s * 0.06
    let jibBottom = hullTop + s * 0.06
    let jibLeft = mastX - s * 0.18

    jib.move(to: NSPoint(x: mastX - s * 0.01, y: jibTop))
    // Billowing curve to the left
    jib.curve(to: NSPoint(x: jibLeft, y: (jibTop + jibBottom) * 0.50),
              controlPoint1: NSPoint(x: mastX - s * 0.08, y: jibTop + s * 0.02),
              controlPoint2: NSPoint(x: jibLeft - s * 0.03, y: (jibTop + jibBottom) * 0.58))
    jib.curve(to: NSPoint(x: mastX - s * 0.01, y: jibBottom),
              controlPoint1: NSPoint(x: jibLeft + s * 0.02, y: jibBottom + s * 0.06),
              controlPoint2: NSPoint(x: mastX - s * 0.03, y: jibBottom + s * 0.01))
    jib.close()

    NSColor(red: 0.78, green: 0.82, blue: 0.88, alpha: 0.9).setFill()
    jib.fill()

    // --- Pennant/flag at the top of the mast ---
    let flag = NSBezierPath()
    let flagBase = mastTop
    let flagTip = mastX + s * 0.08
    let flagH = s * 0.035

    flag.move(to: NSPoint(x: mastX, y: flagBase + flagH))
    flag.curve(to: NSPoint(x: flagTip, y: flagBase + flagH * 0.5),
               controlPoint1: NSPoint(x: mastX + s * 0.03, y: flagBase + flagH * 1.1),
               controlPoint2: NSPoint(x: flagTip - s * 0.01, y: flagBase + flagH * 0.7))
    flag.curve(to: NSPoint(x: mastX, y: flagBase),
               controlPoint1: NSPoint(x: flagTip - s * 0.01, y: flagBase + flagH * 0.3),
               controlPoint2: NSPoint(x: mastX + s * 0.03, y: flagBase - flagH * 0.1))
    flag.close()
    accentCyan.setFill()
    flag.fill()

    // --- "tp" text at bottom right (subtle branding) ---
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: s * 0.065, weight: .bold),
        .foregroundColor: NSColor(red: 0.85, green: 0.88, blue: 0.92, alpha: 0.35),
    ]
    let label = NSAttributedString(string: "tp", attributes: attrs)
    let labelSize = label.size()
    let labelX = s - labelSize.width - s * 0.08
    let labelY = s * 0.06
    label.draw(at: NSPoint(x: labelX, y: labelY))

    // --- Subtle star dots (navigation theme) ---
    func drawStar(at point: NSPoint, radius: CGFloat, alpha: CGFloat) {
        let star = NSBezierPath(ovalIn: NSRect(
            x: point.x - radius, y: point.y - radius,
            width: radius * 2, height: radius * 2))
        NSColor(red: 0.85, green: 0.88, blue: 0.95, alpha: alpha).setFill()
        star.fill()
    }

    drawStar(at: NSPoint(x: s * 0.82, y: s * 0.88), radius: 2.5 * scale, alpha: 0.4)
    drawStar(at: NSPoint(x: s * 0.75, y: s * 0.92), radius: 1.8 * scale, alpha: 0.3)
    drawStar(at: NSPoint(x: s * 0.88, y: s * 0.82), radius: 1.5 * scale, alpha: 0.25)
    drawStar(at: NSPoint(x: s * 0.15, y: s * 0.90), radius: 2.0 * scale, alpha: 0.3)
    drawStar(at: NSPoint(x: s * 0.25, y: s * 0.85), radius: 1.5 * scale, alpha: 0.2)
    drawStar(at: NSPoint(x: s * 0.10, y: s * 0.78), radius: 1.8 * scale, alpha: 0.25)
}

// --- Render at 1024x1024 ---
let rep = NSBitmapImageRep(bitmapDataPlanes: nil,
                           pixelsWide: Int(size),
                           pixelsHigh: Int(size),
                           bitsPerSample: 8,
                           samplesPerPixel: 4,
                           hasAlpha: true,
                           isPlanar: false,
                           colorSpaceName: .deviceRGB,
                           bytesPerRow: 0,
                           bitsPerPixel: 0)!

NSGraphicsContext.saveGraphicsState()
let ctx = NSGraphicsContext(bitmapImageRep: rep)!
NSGraphicsContext.current = ctx
drawIcon(in: ctx, size: size)
NSGraphicsContext.restoreGraphicsState()

guard let pngData = rep.representation(using: .png, properties: [:]) else {
    fputs("Error: failed to create PNG\n", stderr)
    exit(1)
}

let outputPath = "\(outputDir)/tproj-icon-1024.png"
do {
    try pngData.write(to: URL(fileURLWithPath: outputPath))
    print("Generated: \(outputPath)")
} catch {
    fputs("Error writing \(outputPath): \(error)\n", stderr)
    exit(1)
}
