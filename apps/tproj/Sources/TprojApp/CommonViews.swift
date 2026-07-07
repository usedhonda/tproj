import SwiftUI

// Reusable generic View components physically split out of TprojApp.swift (S-D7).
// Moved verbatim; no logic or access-modifier changes.

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
                RoundedRectangle(cornerRadius: compact ? 2 : 3, style: .continuous)
                    .fill(GhosttyTheme.current.cardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: compact ? 2 : 3, style: .continuous)
                            .stroke(GhosttyTheme.current.cardBorder, lineWidth: 1)
                    )
            }
        }
    }
}

struct SectionHeader: View {
    let title: String
    var isCollapsed: Binding<Bool>? = nil

    var body: some View {
        if let binding = isCollapsed {
            Button(action: { withAnimation(.easeInOut(duration: 0.2)) { binding.wrappedValue.toggle() } }) {
                HStack(spacing: 4) {
                    Image(systemName: binding.wrappedValue ? "chevron.right" : "chevron.down")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(GhosttyTheme.current.foreground.opacity(0.4))
                        .frame(width: 12)
                    Text(title)
                        .font(GhosttyTheme.current.font(size: 16, weight: .semibold))
                        .foregroundStyle(GhosttyTheme.current.textPrimary)
                }
                .padding(.leading, 1)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        } else {
            HStack(spacing: 4) {
                Rectangle()
                    .fill(GhosttyTheme.current.foreground.opacity(0.15))
                    .frame(width: 12, height: 1)
                Text(title)
                    .font(GhosttyTheme.current.font(size: 16, weight: .semibold))
                    .foregroundStyle(GhosttyTheme.current.textPrimary)
            }
            .padding(.leading, 1)
        }
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
            .font(GhosttyTheme.current.font(size: dense ? 11 : 13, weight: .semibold))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, dense ? 4 : 12)
            .padding(.vertical, dense ? 2 : 8)
            .frame(minHeight: dense ? 18 : 32)
            .background(
                RoundedRectangle(cornerRadius: dense ? 3 : 4, style: .continuous)
                    .fill(backgroundColor(pressed: pressed))
            )
            .overlay(
                RoundedRectangle(cornerRadius: dense ? 3 : 4, style: .continuous)
                    .stroke(borderColor(pressed: pressed), lineWidth: 1)
            )
            .scaleEffect(pressed ? 0.98 : (isHovered && isEnabled ? 1.02 : 1.0))
            .animation(.easeOut(duration: 0.12), value: pressed)
            .animation(.easeOut(duration: 0.14), value: isHovered)
            .opacity(isEnabled ? 1.0 : 0.45)
    }

    private var foregroundColor: Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            return t.textPrimary.opacity(0.92)
        case .primary:
            return t.textPrimary
        case .danger:
            return t.accentRed.opacity(0.95)
        }
    }

    private func backgroundColor(pressed: Bool) -> Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            if pressed { return t.selectionBg.opacity(0.6) }
            return isHovered ? t.selectionBg.opacity(0.4) : t.foreground.opacity(0.08)
        case .primary:
            if pressed { return t.accentBlue.opacity(0.75) }
            return isHovered ? t.accentBlue.opacity(0.62) : t.accentBlue.opacity(0.46)
        case .danger:
            if pressed { return t.accentRed.opacity(0.26) }
            return isHovered ? t.accentRed.opacity(0.20) : t.accentRed.opacity(0.12)
        }
    }

    private func borderColor(pressed: Bool) -> Color {
        let t = GhosttyTheme.current
        switch tone {
        case .neutral:
            return pressed ? t.foreground.opacity(0.55) : t.foreground.opacity(isHovered ? 0.44 : 0.20)
        case .primary:
            return pressed ? t.accentBlue.opacity(0.95) : t.accentBlue.opacity(isHovered ? 0.88 : 0.72)
        case .danger:
            return pressed ? t.accentRed.opacity(0.82) : t.accentRed.opacity(isHovered ? 0.74 : 0.52)
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
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
                .frame(maxWidth: expand ? .infinity : nil)
        }
        .buttonStyle(ActionButtonStyle(tone: tone, isHovered: isHovered, isEnabled: isEnabled, dense: dense))
        .disabled(!isEnabled)
        .onHover { hover in
            isHovered = hover
        }
    }
}
