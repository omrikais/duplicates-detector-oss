import AppKit
import SwiftUI

// MARK: - Behind-Window Vibrancy

/// Wraps `NSVisualEffectView` for real behind-window translucency on macOS.
/// SwiftUI's `.presentationBackground(.ultraThinMaterial)` only sets the
/// content background — it does not make the sheet window itself translucent.
struct VibrancyBackground: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    var opacity: Double = 1.0

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = .behindWindow
        view.state = .active
        view.alphaValue = CGFloat(opacity)
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.alphaValue = CGFloat(opacity)
    }
}

// MARK: - Floating Panel Presenter

/// Manages a floating `NSPanel` for the customize view.
///
/// Replaces `.sheet()` so the panel is independently movable and not locked
/// to the parent window. The panel has a transparent titlebar, vibrancy
/// background, and closes via Done/X/Escape.
@MainActor
final class CustomizePanelPresenter {
    private var panel: NSPanel?
    private var panelDelegate: PanelCloseDelegate?

    var isShowing: Bool { panel != nil }

    func show(store: SessionStore, onClose: @escaping () -> Void) {
        guard panel == nil else {
            panel?.makeKeyAndOrderFront(nil)
            return
        }

        let delegate = PanelCloseDelegate { [weak self] in
            self?.panel = nil
            self?.panelDelegate = nil
            onClose()
        }

        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 660, height: 560),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        p.isMovableByWindowBackground = true
        p.titlebarAppearsTransparent = true
        p.titleVisibility = .hidden
        p.appearance = NSAppearance(named: .darkAqua)
        p.isOpaque = false
        p.backgroundColor = NSColor(DDColors.surface0).withAlphaComponent(0.92)
        p.level = .floating
        p.isReleasedWhenClosed = false
        p.animationBehavior = .utilityWindow
        p.delegate = delegate

        // NSVisualEffectView as the base content view — covers the entire
        // window including the titlebar area for a uniform translucent look.
        let effectView = NSVisualEffectView()
        effectView.material = .hudWindow
        effectView.blendingMode = .behindWindow
        effectView.state = .active
        effectView.alphaValue = 1.0

        let content = CustomizeSheet(store: store, onDismiss: { [weak self] in
            self?.panel?.close()
        })
        .modifier(DDAdaptiveColorsInjector())
        let hostingView = NSHostingView(rootView: content)
        hostingView.translatesAutoresizingMaskIntoConstraints = false
        effectView.addSubview(hostingView)
        NSLayoutConstraint.activate([
            hostingView.topAnchor.constraint(equalTo: effectView.topAnchor),
            hostingView.bottomAnchor.constraint(equalTo: effectView.bottomAnchor),
            hostingView.leadingAnchor.constraint(equalTo: effectView.leadingAnchor),
            hostingView.trailingAnchor.constraint(equalTo: effectView.trailingAnchor),
        ])
        p.contentView = effectView

        // Center on the current key window
        if let parent = NSApp.keyWindow {
            let f = parent.frame
            p.setFrameOrigin(NSPoint(x: f.midX - 330, y: f.midY - 280))
        } else {
            p.center()
        }

        p.alphaValue = 0
        p.makeKeyAndOrderFront(nil)
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.25
            ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
            p.animator().alphaValue = 1
        }
        self.panel = p
        self.panelDelegate = delegate
    }

    func close() {
        panel?.close()
    }
}

/// Delegate that fires a callback when the panel closes (via title-bar X or programmatic close).
private final class PanelCloseDelegate: NSObject, NSWindowDelegate, @unchecked Sendable {
    let onClose: () -> Void

    init(onClose: @escaping () -> Void) {
        self.onClose = onClose
    }

    func windowWillClose(_ notification: Notification) {
        onClose()
    }
}

// MARK: - Customize Sheet

/// Tabbed modal sheet for advanced scan configuration.
///
/// Presents five tabs (Detection, Weights, Filters, Output, Advanced) in a custom
/// tab bar. Changes are applied live to the ``SessionStore`` setup state — there is no
/// explicit "Apply" step.
///
/// When presented via ``CustomizePanelPresenter``, pass an `onDismiss` closure.
/// When presented via `.sheet()`, leave `onDismiss` nil to use `@Environment(\.dismiss)`.
struct CustomizeSheet: View {
    let store: SessionStore
    var onDismiss: (() -> Void)?
    @Environment(\.dismiss) private var environmentDismiss
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selectedTab: Tab = .detection

    private var setup: SetupState { store.setupState }

    private func dismissAction() {
        if let onDismiss { onDismiss() } else { environmentDismiss() }
    }

    // MARK: - Tab Enum

    enum Tab: String, CaseIterable, Sendable {
        case detection = "Detection"
        case weights = "Weights"
        case filters = "Filters"
        case output = "Output"
        case advanced = "Advanced"

        var icon: String {
            switch self {
            case .detection: "waveform.circle"
            case .weights: "dial.low"
            case .filters: "line.3.horizontal.decrease"
            case .output: "arrow.up.doc"
            case .advanced: "gearshape.2"
            }
        }
    }

    // MARK: - Body

    var body: some View {
        VStack(spacing: 0) {
            // Tab bar (top padding clears the titlebar / traffic lights)
            tabBar
                .padding(.horizontal, DDSpacing.md)
                .padding(.top, DDSpacing.xl)

            Divider()
                .foregroundStyle(ddColors.textMuted.opacity(0.3))

            // Content area
            ScrollView {
                tabContent
                    .padding(.horizontal, DDSpacing.sm)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()
                .foregroundStyle(ddColors.textMuted.opacity(0.5))

            // Bottom bar
            bottomBar
                .padding(DDDensity.regular)
        }
        .frame(width: 660, height: 560)
        .background(DDColors.surface0.opacity(0.85))
    }

    // MARK: - Tab Bar

    private var tabBar: some View {
        HStack(spacing: DDSpacing.md) {
            ForEach(Tab.allCases, id: \.self) { tab in
                tabButton(for: tab)
            }
        }
        .focusable()
        .onKeyPress(.leftArrow) {
            let allTabs = Tab.allCases
            guard let idx = allTabs.firstIndex(of: selectedTab), idx > allTabs.startIndex else { return .ignored }
            selectedTab = allTabs[allTabs.index(before: idx)]
            return .handled
        }
        .onKeyPress(.rightArrow) {
            let allTabs = Tab.allCases
            guard let idx = allTabs.firstIndex(of: selectedTab) else { return .ignored }
            let next = allTabs.index(after: idx)
            guard next < allTabs.endIndex else { return .ignored }
            selectedTab = allTabs[next]
            return .handled
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Configuration tabs")
    }

    private func tabButton(for tab: Tab) -> some View {
        let isActive = selectedTab == tab
        return Button {
            selectedTab = tab
        } label: {
            VStack(spacing: DDSpacing.xs) {
                HStack(spacing: DDSpacing.xs) {
                    Image(systemName: tab.icon)
                        .font(DDIcon.smallFont)
                    Text(tabLabel(for: tab))
                        .font(DDTypography.label)
                }
                .foregroundStyle(isActive ? DDColors.accent : ddColors.textSecondary)
                .padding(.horizontal, DDSpacing.sm)
                .padding(.top, DDSpacing.sm)
                .padding(.bottom, DDSpacing.xs)

                Rectangle()
                    .fill(isActive ? DDColors.accent : Color.clear)
                    .frame(height: 2)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tabLabel(for: tab))
        .accessibilityHint("Shows \(tab.rawValue) settings")
        .accessibilityAddTraits(isActive ? .isSelected : [])
        .animation(reduceMotion ? nil : DDMotion.snappy, value: selectedTab)
    }

    private func tabLabel(for tab: Tab) -> String {
        if tab == .filters, setup.activeFilterCount > 0 {
            return "\(tab.rawValue) (\(setup.activeFilterCount))"
        }
        return tab.rawValue
    }

    // MARK: - Tab Content

    @ViewBuilder
    private var tabContent: some View {
        switch selectedTab {
        case .detection:
            DetectionTab(store: store)
        case .weights:
            WeightsTab(store: store)
        case .filters:
            FiltersTab(store: store)
        case .output:
            OutputTab(store: store)
        case .advanced:
            AdvancedTab(store: store)
        }
    }

    // MARK: - Bottom Bar

    private var bottomBar: some View {
        HStack {
            Button("Reset to Defaults") {
                resetActiveTab()
            }
            .buttonStyle(.plain)
            .foregroundStyle(ddColors.textSecondary)

            Spacer()

            Button("Done") {
                dismissAction()
            }
            .buttonStyle(.glassProminent)
            .tint(DDColors.accent)
        }
    }

    private func resetActiveTab() {
        store.sendSetup(.reloadDefaults)
    }
}
