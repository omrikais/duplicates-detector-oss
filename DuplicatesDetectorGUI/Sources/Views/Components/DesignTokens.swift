import SwiftUI
import UniformTypeIdentifiers

// MARK: - Custom UTType

extension UTType {
    /// Custom UTI for Duplicates Detector scan result envelopes (`.ddscan` files).
    static let ddScanResults = UTType(exportedAs: "com.omrikaisari.duplicates-detector.scan-results")
}

// MARK: - Hex Color Initializer

extension Color {
    fileprivate init(hex: UInt, opacity: Double = 1.0) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: opacity
        )
    }
}

// MARK: - Spacing

/// Spacing constants for consistent layout throughout the app.
enum DDSpacing {
    /// Extra-extra-small spacing — tight label gaps, sub-element separation.
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32

    /// Hairline separator between stacked elements.
    static let hairline: CGFloat = 1

    /// Fixed width for monospacedDigit numeric readouts (e.g., threshold "50").
    static let numericReadoutWidth: CGFloat = 30

    /// Maximum width for mode segmented control.
    static let modePickerMaxWidth: CGFloat = 280

    /// Minimum width for primary action button (Start Scan).
    static let primaryActionMinWidth: CGFloat = 160

    /// Minimum height for the inline weights editor.
    static let weightsEditorMinHeight: CGFloat = 200

    /// Diameter of small status indicator dots.
    static let statusDotSize: CGFloat = 6

    /// Diameter of pulse indicator dot.
    static let pulseDotSize: CGFloat = 10
    /// Container frame for pulse dot (accommodates expanded ring).
    static let pulseDotContainer: CGFloat = 26

    /// Stroke width for selection/highlight borders.
    static let selectionStroke: CGFloat = 1.5

    /// Stroke width for drop target borders.
    static let dropTargetStroke: CGFloat = 2

    /// Width of feed-row left accent bars.
    static let accentBarWidth: CGFloat = 3

    /// Label column width in comparison diff tables and breakdown rows.
    static let labelColumnWidth: CGFloat = 80

    /// Label column width in inspector metadata grids.
    static let inspectorLabelWidth: CGFloat = 70

    /// Slider thumb diameter.
    static let sliderThumb: CGFloat = 16

    /// Width for zoom percentage readout.
    static let zoomReadoutWidth: CGFloat = 44

    /// Icon frame width for inline directory/file list icons.
    static let iconFrame: CGFloat = 20

    // MARK: Pipeline & Progress

    /// Pipeline node indicator circle diameter.
    static let pipelineIndicator: CGFloat = 28
    /// Pipeline active-stage pulse circle diameter.
    static let pipelinePulse: CGFloat = 12
    /// Minimum width for pipeline stage name labels.
    static let pipelineLabelMinWidth: CGFloat = 72
    /// Fixed height for pipeline stage detail area (counts/elapsed).
    static let pipelineStageDetailHeight: CGFloat = 28
    /// Height of pipeline connector bars between nodes.
    static let connectorHeight: CGFloat = 2
    /// Minimum width of pipeline connector bars.
    static let connectorMinWidth: CGFloat = 16
    /// Maximum width of pipeline connector bars.
    static let connectorMaxWidth: CGFloat = 40
    /// Maximum width for the linear progress bar below percentage text.
    static let progressBarMaxWidth: CGFloat = 280
    /// Maximum width for the active file path display.
    static let activeFileMaxWidth: CGFloat = 500

    // MARK: Breakdown & Score Layout

    /// Height for compact breakdown bars (queue rows).
    static let breakdownBarCompact: CGFloat = 8
    /// Height for detailed breakdown bars (comparison panel).
    static let breakdownBarDetail: CGFloat = 10
    /// Column width for raw score percentage.
    static let scoreColumnWidth: CGFloat = 50
    /// Column width for weight values.
    static let weightColumnWidth: CGFloat = 30
    /// Column width for contribution values.
    static let contributionColumnWidth: CGFloat = 40

    // MARK: Filmstrip

    /// Width of filmstrip tiles in group review.
    static let filmstripTileWidth: CGFloat = 120
    /// Height of filmstrip tile thumbnails in group review.
    static let filmstripTileHeight: CGFloat = 90

    // MARK: Thumbnails

    /// Thumbnail width in queue rows and fallback placeholders.
    static let thumbnailCompactWidth: CGFloat = 48
    /// Thumbnail height in queue rows and fallback placeholders.
    static let thumbnailCompactHeight: CGFloat = 36
    /// Thumbnail width for side-by-side pair queue row thumbnails.
    static let thumbnailMiniWidth: CGFloat = 32
    /// Thumbnail height for side-by-side pair queue row thumbnails.
    static let thumbnailMiniHeight: CGFloat = 24
    /// Thumbnail width in inspector identity sections.
    static let thumbnailDetailWidth: CGFloat = 240
    /// Thumbnail height in inspector identity sections.
    static let thumbnailDetailHeight: CGFloat = 160
    /// Thumbnail width in comparison panel side-by-side view.
    static let thumbnailLargeWidth: CGFloat = 400
    /// Thumbnail height in comparison panel side-by-side view.
    static let thumbnailLargeHeight: CGFloat = 240

    // MARK: Configuration Layout

    /// Maximum content width for configuration/launcher screens.
    static let contentMaxWidth: CGFloat = 780
}

// MARK: - Corner Radii

/// Named corner radius values. Never use raw numbers for corner radii.
enum DDRadius {
    /// Thumbnails, small badges.
    static let small: CGFloat = 6
    /// Stat capsules, input fields.
    static let medium: CGFloat = 10
    /// Glass containers, cards.
    static let large: CGFloat = 16
    /// Modal panels, popovers.
    static let panel: CGFloat = 20
}

// MARK: - Colors

/// Color palette — Graphite Forge.
///
/// Cool graphite surfaces, steel-blue accent, clinical semantic signals.
/// Dark-mode primary. All values are specific hex colors, not system-adaptive.
enum DDColors {

    // MARK: Accent & Emphasis

    /// Primary accent — steel blue (#4A90D9).
    static let accent = Color(hex: 0x4A90D9)

    /// Destructive actions — delete, remove (#FF453A).
    static let destructive = Color(hex: 0xFF453A)

    /// Warning / caution states (#FF9F0A).
    static let warning = Color(hex: 0xFF9F0A)

    /// Completed, safe, success states (#30D158).
    static let success = Color(hex: 0x30D158)

    /// Neutral informational callouts (#5AC8FA).
    static let info = Color(hex: 0x5AC8FA)

    // MARK: Surfaces

    /// Level 0 — window/app background. Deepest layer (#1C1C1E).
    static let surface0 = Color(hex: 0x1C1C1E)

    /// Level 1 — panel/sidebar background (#2C2C2E).
    static let surface1 = Color(hex: 0x2C2C2E)

    /// Level 2 — card/elevated content within a panel (#3A3A3C).
    static let surface2 = Color(hex: 0x3A3A3C)

    /// Level 3 — overlay, popover, tooltip (#48484A).
    static let surface3 = Color(hex: 0x48484A)

    // MARK: Score Colors

    /// Near-certain duplicate (90–100). Urgent, demands attention (#FF453A).
    static let scoreCritical = Color(hex: 0xFF453A)

    /// Likely duplicate (70–89). High confidence, review recommended (#FF9F0A).
    static let scoreHigh = Color(hex: 0xFF9F0A)

    /// Possible duplicate (50–69). Moderate confidence (#FFD60A).
    static let scoreMedium = Color(hex: 0xFFD60A)

    /// Unlikely duplicate (below 50). Low confidence, probably distinct (#30D158).
    static let scoreLow = Color(hex: 0x30D158)

    /// Returns the semantic color for a similarity score.
    static func scoreColor(for score: Double) -> Color {
        switch score {
        case 90...: scoreCritical
        case 70..<90: scoreHigh
        case 50..<70: scoreMedium
        default: scoreLow
        }
    }

    /// Returns the color for a comparator key, falling back to muted text.
    static func comparatorColor(for key: String) -> Color {
        comparatorColors[key] ?? textMuted
    }

    // MARK: Text Hierarchy

    /// Primary text — full-weight content (#FFFFFF @ 85%).
    static let textPrimary = Color(hex: 0xFFFFFF, opacity: 0.85)

    /// Secondary text — descriptions, subtitles, supporting copy (#FFFFFF @ 55%).
    static let textSecondary = Color(hex: 0xFFFFFF, opacity: 0.55)

    /// Muted text — tertiary info like file paths, timestamps, disabled labels (#FFFFFF @ 35%).
    static let textMuted = Color(hex: 0xFFFFFF, opacity: 0.35)

    // MARK: State Colors

    /// Selected row/item highlight background.
    static let selection = Color(hex: 0x4A90D9, opacity: 0.15)

    /// Pointer hover state background.
    static let hover = Color(hex: 0xFFFFFF, opacity: 0.05)

    /// Active/pressed state background.
    static let active = Color(hex: 0x4A90D9, opacity: 0.25)

    /// Keyboard focus ring stroke color.
    static let focusRing = Color(hex: 0x4A90D9)

    // MARK: Comparator Colors

    static let comparatorColors: [String: Color] = [
        "filename": .blue,
        "duration": .purple,
        "resolution": .orange,
        "fileSize": .teal,
        "filesize": .teal,     // CLI weight key alias
        "exif": .pink,
        "content": .green,
        "audio": .indigo,
        "tags": .mint,
        "page_count": .brown,
        "pageCount": .brown,
        "doc_meta": .cyan,
        "docMeta": .cyan,
    ]
}

// MARK: - Adaptive Colors

/// Provides contrast-adaptive color variants for high-contrast accessibility.
///
/// Standard contrast delegates to `DDColors` statics. Increased contrast boosts
/// text and semantic colors for improved visibility.
///
/// **WCAG 2.1 AA contrast ratios (against surface0 #1C1C1E, luminance ~0.012):**
///
/// | Token         | Standard       | Ratio vs surface0 | Increased      | Ratio vs surface0 |
/// |---------------|----------------|-------------------|----------------|-------------------|
/// | textPrimary   | white @ 85%    | ~13.2:1 ✓ AA      | white @ 100%   | ~17.4:1 ✓         |
/// | textSecondary | white @ 55%    | ~7.5:1 ✓ AA       | white @ 85%    | ~13.2:1 ✓         |
/// | textMuted     | white @ 35%    | ~3.8:1 ✗ AA       | white @ 70%    | ~9.7:1 ✓          |
/// | separator     | white @ 15%    | ~1.5:1 (non-text) | white @ 40%    | ~4.4:1 ✓ 3:1      |
/// | scoreCritical | #FF453A        | ~4.6:1 ✓ 3:1      | (no boost — already meets 3:1)    |
/// | scoreHigh     | #FF9F0A        | ~7.8:1 ✓ 3:1      | (no boost — already meets 3:1)    |
/// | scoreMedium   | #FFD60A        | ~11.9:1 ✓ 3:1     | boosted yellow | ✓                 |
/// | scoreLow      | #30D158        | ~6.4:1 ✓ 3:1      | boosted green  | ✓                 |
///
/// Ratios computed via WCAG relative luminance formula. Text requires 4.5:1 (AA),
/// non-text UI components require 3:1 (1.4.11). `textMuted` fails in standard mode
/// — this is acceptable because muted text is supplementary; high-contrast mode
/// provides the compliant alternative.
struct DDAdaptiveColors {
    let contrast: ColorSchemeContrast

    var textPrimary: Color {
        contrast == .increased ? .white : DDColors.textPrimary
    }

    var textSecondary: Color {
        contrast == .increased ? Color(white: 1.0, opacity: 0.85) : DDColors.textSecondary
    }

    var textMuted: Color {
        contrast == .increased ? Color(white: 1.0, opacity: 0.70) : DDColors.textMuted
    }

    var scoreLow: Color {
        contrast == .increased ? Color(red: 0.25, green: 0.9, blue: 0.4) : DDColors.scoreLow
    }

    var scoreMedium: Color {
        contrast == .increased ? Color(red: 1.0, green: 0.82, blue: 0.0) : DDColors.scoreMedium
    }

    var separator: Color {
        contrast == .increased ? Color(white: 1.0, opacity: 0.40) : Color(white: 1.0, opacity: 0.15)
    }

    /// Returns the semantic color for a similarity score, boosted for high contrast.
    func scoreColor(for score: Double) -> Color {
        switch score {
        case 90...: DDColors.scoreCritical
        case 70..<90: DDColors.scoreHigh
        case 50..<70: scoreMedium
        default: scoreLow
        }
    }
}

/// Environment key for injecting contrast-adaptive colors.
private struct DDAdaptiveColorsKey: EnvironmentKey {
    static let defaultValue = DDAdaptiveColors(contrast: .standard)
}

extension EnvironmentValues {
    /// Contrast-adaptive color palette, automatically set by ``DDAdaptiveColorsInjector``.
    var ddColors: DDAdaptiveColors {
        get { self[DDAdaptiveColorsKey.self] }
        set { self[DDAdaptiveColorsKey.self] = newValue }
    }
}

/// ViewModifier that reads the system contrast setting and injects
/// the appropriate ``DDAdaptiveColors`` into the environment.
public struct DDAdaptiveColorsInjector: ViewModifier {
    @Environment(\.colorSchemeContrast) private var contrast

    public init() {}

    public func body(content: Content) -> some View {
        content.environment(\.ddColors, DDAdaptiveColors(contrast: contrast))
    }
}

// MARK: - Comparators

/// Display names for CLI comparator keys.
enum DDComparators {
    private static let names: [String: String] = [
        "filename": "Filename",
        "duration": "Duration",
        "resolution": "Resolution",
        "fileSize": "File Size",
        "filesize": "File Size",   // CLI weight key alias
        "exif": "EXIF",
        "content": "Content",
        "audio": "Audio",
        "tags": "Tags",
        "directory": "Directory",
        "byte_identical": "Byte Identical",
        "byteIdentical": "Byte Identical",
        "page_count": "Page Count",
        "pageCount": "Page Count",
        "doc_meta": "Doc Meta",
        "docMeta": "Doc Meta",
    ]

    static func displayName(for key: String) -> String {
        names[key] ?? key.capitalized
    }
}

// MARK: - Typography

/// Typography roles for consistent text styling.
///
/// Each role maps to a specific context. Never use raw `.font()` modifiers — use these tokens.
enum DDTypography {
    /// Large numbers: progress percentage, prominent score values.
    static let displayStat: Font = .system(size: 48, weight: .bold, design: .rounded).monospacedDigit()

    /// Section and screen titles.
    static let heading: Font = .title2.bold()

    /// Primary content text.
    static let body: Font = .body

    /// Section titles within panels/inspectors — "Metadata", "Actions", "Members".
    static let sectionTitle: Font = .body.weight(.semibold)

    /// Sub-section titles in disclosure groups — "Detection", "Content Hashing".
    static let subsectionTitle: Font = .callout.weight(.semibold)

    /// Primary action labels: Start Scan, prominent buttons.
    static let action: Font = .body.weight(.semibold)

    /// Secondary information: file paths, timestamps, tool versions.
    static let metadata: Font = .caption.monospaced()

    /// Technical values: resolution, codec, bitrate, duration.
    static let monospaced: Font = .callout.monospaced()

    /// Small labels, badges, pipeline node names.
    static let label: Font = .caption2

    /// Score ring label — compact size (32pt ring).
    static let scoreLabelCompact: Font = .caption2.monospaced().bold()

    /// Score ring label — regular size (56pt ring).
    static let scoreLabelRegular: Font = .callout.monospaced().bold()

    /// Large header icons in onboarding/install screens.
    static let headerIcon: Font = .system(size: 40, weight: .medium)

    /// Stat card values and dashboard counters.
    static let statValue: Font = .title3.monospacedDigit().bold()

    /// Numeric readouts beside sliders and weight labels — fixed-width digits prevent layout jitter.
    static let sliderReadout: Font = .body.monospacedDigit()

    /// Wipe-slider handle icon — small, bold system font.
    static let wipeHandle: Font = .system(size: 10, weight: .bold)
}

// MARK: - Icons

/// SF Symbol rendering tokens for consistent icon treatment.
///
/// Provides weight, sizing, and rendering mode constants. Do NOT retroactively
/// apply to existing views — define the single source of truth for new icon usage.
enum DDIcon {
    /// Default SF Symbol weight for all icons.
    static let weight: Font.Weight = .medium
    /// Small inline icons (12pt) — badges, status dots.
    static let smallFont = Font.system(size: 12, weight: weight)
    /// Body-level icons (16pt) — list rows, toolbar items.
    static let bodyFont = Font.system(size: 16, weight: weight)
    /// Large decorative icons (24pt) — empty states, section headers.
    static let largeFont = Font.system(size: 24, weight: weight)
    /// Default rendering mode — hierarchical for depth with a single tint.
    static let renderingMode: SymbolRenderingMode = .hierarchical
}

// MARK: - Motion

/// Animation durations and presets.
///
/// Use named constants for all animations. Never use raw duration values.
enum DDMotion {
    /// 0.15s — micro-interactions, toggle states.
    static let durationFast: Double = 0.15

    /// 0.3s — standard transitions, panel reveals.
    static let durationMedium: Double = 0.3

    /// 0.5s — emphasis transitions, onboarding steps.
    static let durationSlow: Double = 0.5

    /// Quick, decisive feel. List selections, button presses.
    static let snappy: Animation = .snappy(duration: 0.3)

    /// Fluid, polished feel. Progress bars, panel slides.
    static let smooth: Animation = .smooth(duration: 0.3)

    /// Bouncy entrance. Modal presentations, score ring reveals.
    static let spring: Animation = .spring(duration: 0.5, bounce: 0.2)
}

// MARK: - Shadow

/// Shadow presets for elevated interactive elements.
enum DDShadow {
    /// Subtle drop shadow for slider thumbs and small controls.
    static let control = (color: Color.black.opacity(0.2), radius: CGFloat(2), y: CGFloat(1))
}

// MARK: - Density

/// Panel density variants for spacing in different contexts.
enum DDDensity {
    /// Tight padding — list rows, dense metadata displays.
    static let compact = EdgeInsets(top: 4, leading: 8, bottom: 4, trailing: 8)

    /// Standard padding — panels, cards, inspector content.
    static let regular = EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16)
}

// MARK: - Pill Size

/// Padding tiers for glass pill elements.
///
/// Three standard sizes cover all pill use cases in the app:
/// - `small`: Compact badges (mode labels in paused session cards)
/// - `medium`: Standard pills (mode badges, feature pills, stat capsules)
/// - `large`: Prominent status pills (pause/cancel controls, progress stats)
enum DDPillSize {
    case small
    case medium
    case large

    var horizontal: CGFloat {
        switch self {
        case .small: DDSpacing.sm
        case .medium: DDSpacing.sm
        case .large: DDSpacing.md
        }
    }

    var vertical: CGFloat {
        switch self {
        case .small: DDSpacing.xxs
        case .medium: DDSpacing.xs
        case .large: DDSpacing.sm
        }
    }
}

// MARK: - Glass

/// Glass effect styles for structural chrome.
///
/// Glass is for navigation chrome (toolbars, sidebars, stat capsules).
/// Content panels (comparison surfaces, metadata inspectors) stay solid using surface colors.
/// Deployment target is macOS 26+ — no availability guards needed.
enum DDGlass {
    /// Structural chrome — toolbars, sidebars, navigation bars.
    struct Chrome: ViewModifier {
        func body(content: Content) -> some View {
            content.glassEffect(.regular, in: .rect(cornerRadius: DDRadius.large))
        }
    }

    /// Elevated content cards within glass regions.
    struct Card: ViewModifier {
        func body(content: Content) -> some View {
            content.glassEffect(.regular, in: .rect(cornerRadius: DDRadius.medium))
        }
    }

    /// Stat capsules, badges, pills — optionally tinted.
    struct Pill: ViewModifier {
        var size: DDPillSize?
        var tint: Color?

        func body(content: Content) -> some View {
            let base = content
                .padding(.horizontal, size?.horizontal ?? 0)
                .padding(.vertical, size?.vertical ?? 0)
            if let tint {
                base.glassEffect(.regular.tint(tint), in: .capsule)
            } else {
                base.glassEffect(.regular, in: .capsule)
            }
        }
    }

    /// Interactive pill buttons — tappable capsule glass with optional tint.
    /// Strips default button chrome (`.buttonStyle(.plain)`) so the glass effect
    /// is the sole visual treatment — no inner rectangle artifact.
    struct InteractivePill: ViewModifier {
        var size: DDPillSize?
        var tint: Color?

        func body(content: Content) -> some View {
            let base = content
                .padding(.horizontal, size?.horizontal ?? 0)
                .padding(.vertical, size?.vertical ?? 0)
                .buttonStyle(.plain)
            if let tint {
                base.glassEffect(.regular.tint(tint).interactive(), in: .capsule)
            } else {
                base.glassEffect(.regular.interactive(), in: .capsule)
            }
        }
    }

    /// Tappable/focusable glass elements with pointer/touch response.
    struct Interactive: ViewModifier {
        func body(content: Content) -> some View {
            content.glassEffect(.regular.interactive(), in: .rect(cornerRadius: DDRadius.medium))
        }
    }
}

extension View {
    /// Apply structural chrome glass (toolbars, sidebars).
    func ddGlassChrome() -> some View { modifier(DDGlass.Chrome()) }

    /// Apply card-level glass (elevated content).
    func ddGlassCard() -> some View { modifier(DDGlass.Card()) }

    /// Apply pill/capsule glass (stats, badges), optionally sized and tinted.
    func ddGlassPill(size: DDPillSize? = nil, tint: Color? = nil) -> some View { modifier(DDGlass.Pill(size: size, tint: tint)) }

    /// Apply interactive pill glass (tappable capsule buttons), optionally sized and tinted.
    func ddGlassInteractivePill(size: DDPillSize? = nil, tint: Color? = nil) -> some View { modifier(DDGlass.InteractivePill(size: size, tint: tint)) }

    /// Apply interactive glass (buttons, tappable elements).
    func ddGlassInteractive() -> some View { modifier(DDGlass.Interactive()) }
}

// MARK: - Focus Ring

/// Keyboard focus ring overlay for custom focusable elements.
///
/// Standard SwiftUI controls (Button, Toggle, Picker) show their own focus ring.
/// Use this modifier on custom interactive elements that use `.focusable()`.
struct DDFocusRing: ViewModifier {
    let isFocused: Bool
    var cornerRadius: CGFloat = DDRadius.medium

    func body(content: Content) -> some View {
        content.overlay(
            RoundedRectangle(cornerRadius: cornerRadius)
                .strokeBorder(DDColors.focusRing, lineWidth: isFocused ? 2 : 0)
        )
    }
}

extension View {
    /// Apply a visible keyboard focus ring. Pass the relevant `@FocusState` binding.
    func ddFocusRing(_ isFocused: Bool, cornerRadius: CGFloat = DDRadius.medium) -> some View {
        modifier(DDFocusRing(isFocused: isFocused, cornerRadius: cornerRadius))
    }
}

// MARK: - Shared Extensions

extension ScanMode {
    /// Canonical SF Symbol name for this scan mode — single source of truth.
    var systemImageName: String {
        switch self {
        case .video: "film"
        case .image: "photo"
        case .audio: "music.note"
        case .auto: "sparkles"
        case .document: "doc.text"
        }
    }
}

extension String {
    /// The last path component (filename) of a file path string.
    var fileName: String { (self as NSString).lastPathComponent }

    /// "parent/filename" display label, e.g. "/a/b/c.mp4" → "b/c.mp4".
    /// Returns bare `fileName` when there is no meaningful parent.
    var parentSlashFileName: String {
        let name = fileName
        let parent = ((self as NSString).deletingLastPathComponent as NSString).lastPathComponent
        if parent.isEmpty || parent == "/" { return name }
        return "\(parent)/\(name)"
    }
}

extension URL {
    /// Whether this URL points to an existing directory on disk.
    var isExistingDirectory: Bool {
        var isDir: ObjCBool = false
        return FileManager.default.fileExists(atPath: path, isDirectory: &isDir) && isDir.boolValue
    }
}

// MARK: - Settings Section

/// Transparent section container for customize-sheet tabs.
///
/// Replaces `Form { Section(...) { ... } }.formStyle(.grouped)` which draws
/// opaque section backgrounds that clash with custom sheet backgrounds.
func settingsSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
    VStack(alignment: .leading, spacing: DDSpacing.sm) {
        Text(title)
            .font(DDTypography.sectionTitle)
            .foregroundStyle(DDColors.textPrimary)
        content()
    }
}

// MARK: - Media Label

/// Translucent label pill for media comparison overlays (image/video panes).
struct DDMediaLabel: View {
    let text: String
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        Text(text)
            .font(DDTypography.label)
            .foregroundStyle(ddColors.textMuted)
            .padding(DDDensity.compact)
            .background(DDColors.surface0.opacity(0.7), in: RoundedRectangle(cornerRadius: DDRadius.small))
    }
}
