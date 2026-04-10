import os
import SwiftUI

private let diagLog = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "ProgressScreen")

// MARK: - Pipeline Alignment

extension VerticalAlignment {
    /// Aligns pipeline node circles and connectors on the same horizontal line.
    private enum PipelineCenter: AlignmentID {
        static func defaultValue(in context: ViewDimensions) -> CGFloat {
            context[VerticalAlignment.center]
        }
    }

    static let pipelineCenter = VerticalAlignment(PipelineCenter.self)
}

/// Contextual scan dashboard with pipeline visualization and adaptive density.
///
/// Takes the `SessionStore` directly so that `store.session.scan` is accessed
/// in `body`, creating a direct `@Observable` tracking. This ensures the view
/// re-renders whenever the reducer updates stage progress — without relying on
/// the parent view's re-evaluation and SwiftUI's non-Equatable struct diffing.
///
/// Context (mode, directories, etc.) is derived from `store.progressContext`
/// inside this view — NOT passed as parameters from the parent — so the parent
/// view (`ScanFlowView`) never accesses scan state, keeping its observation
/// limited to `store.phase`.
struct ProgressScreen: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors
    @State private var showPausedInfo = false

    /// Navigation title derived from current state. Exposed for unit testing.
    nonisolated static func navigationTitleText(
        isCancelling: Bool, isPaused: Bool, isPausing: Bool, activeStageDisplayName: String?
    ) -> String {
        if isCancelling { return "Cancelling\u{2026}" }
        if isPaused { return "Paused" }
        if isPausing { return "Pausing\u{2026}" }
        if let name = activeStageDisplayName { return name.appending("\u{2026}") }
        return "Scanning\u{2026}"
    }

    var body: some View {
        // TimelineView forces body re-evaluation at 10 Hz, bypassing @Observable
        // tracking which is unreliable for high-frequency struct replacement.
        // This is Apple's recommended pattern for live-updating displays.
        TimelineView(.periodic(from: .now, by: 0.1)) { _ in
            let scan = store.session.scan
            let context = store.progressContext
            #if DEBUG
            let _ = diagLog.notice("[body] oid=\(ObjectIdentifier(store).debugDescription, privacy: .public) seq=\(store.session.scanSequence) progress=\(scan?.overallProgress ?? 0, privacy: .public), pause=\(String(describing: scan?.pause), privacy: .public), stages=\(scan?.stages.map { "\($0.id.rawValue):\($0.status)" } ?? [], privacy: .public)")
            #endif

            progressContent(scan: scan, context: context)
        }
    }

    @ViewBuilder
    private func progressContent(
        scan: ScanProgress?,
        context: SessionStore.ProgressContext
    ) -> some View {
        let stages = scan?.stages ?? []
        let isPaused = scan?.pause.isPaused ?? false
        let isPausing = scan?.pause.isPausing ?? false

        ScrollView {
            VStack(spacing: DDSpacing.lg) {
                ScanContextHeader(
                    mode: context.mode,
                    entries: context.directoryEntries,
                    contentEnabled: context.contentEnabled,
                    contentMethod: context.contentMethod,
                    audioEnabled: context.audioEnabled,
                    sourceLabel: context.sourceLabel
                )

                if scan?.photosLimitedWarning == true {
                    Label(
                        "Limited access \u{2014} only selected photos are visible. Grant full access in System Settings.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(DDTypography.label)
                    .foregroundStyle(.orange)
                    .padding(.horizontal, DDSpacing.md)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Warning: Limited Photos access. Only selected photos are visible. Grant full access in System Settings.")
                }

                PipelineBar(stages: stages)

                PrimaryProgressDisplay(
                    progress: scan?.overallProgress ?? 0,
                    scan: scan,
                    throughput: scan?.currentThroughput
                )

                if let active = scan?.activeStage, active.currentFile != nil {
                    ActiveFileDetail(stage: active)
                }

                if let cache = scan?.cache, cache.cacheHits > 0 {
                    CacheEfficiencyRow(
                        hits: cache.cacheHits,
                        misses: cache.cacheMisses,
                        cacheTimeSaved: cache.cacheTimeSaved,
                        metadataHits: cache.metadataCacheHits,
                        metadataMisses: cache.metadataCacheMisses,
                        contentHits: cache.contentCacheHits,
                        contentMisses: cache.contentCacheMisses,
                        audioHits: cache.audioCacheHits,
                        audioMisses: cache.audioCacheMisses,
                        scoreHits: cache.scoreCacheHits,
                        scoreMisses: cache.scoreCacheMisses
                    )
                }

                StageStatCounters(stages: stages)
            }
            .padding(DDSpacing.lg)
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .scrollContentBackground(.hidden)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            HStack {
                if scan?.timing.isResumed == true {
                    resumedPill
                }
                Spacer()
                cancelPill
            }
            .padding(DDSpacing.lg)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle(Self.navigationTitleText(
            isCancelling: scan?.isCancelling ?? false,
            isPaused: isPaused,
            isPausing: isPausing,
            activeStageDisplayName: scan?.activeStage?.displayName
        ))
    }

    private var resumedPill: some View {
        HStack(spacing: DDSpacing.sm) {
            Image(systemName: "arrow.clockwise")
                .font(DDTypography.label)
            Text("Resumed from paused session")
                .font(DDTypography.label)
        }
        .foregroundStyle(DDColors.success)
        .ddGlassPill(size: .large)
        .accessibilityLabel("Resumed from paused session")
    }

    private var cancelPill: some View {
        let scan = store.session.scan
        let isComplete = scan?.isComplete ?? false
        let isCancelling = scan?.isCancelling ?? false
        let isPhotosLibrary = store.session.metadata.sourceLabel == SessionMetadata.photosLibraryLabel
        let isPaused = scan?.pause.isPaused ?? false
        let isPausing = scan?.pause.isPausing ?? false

        return HStack(spacing: DDSpacing.sm) {
            if !isComplete {
                if isCancelling {
                    HStack(spacing: DDSpacing.sm) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Cancelling\u{2026}")
                            .font(DDTypography.label)
                            .foregroundStyle(ddColors.textSecondary)
                    }
                    .ddGlassPill(size: .large)
                } else {
                    // Pause/resume only for CLI scans — Photos scans have no subprocess or pause file
                    if !isPhotosLibrary {
                        if isPaused {
                            HStack(spacing: DDSpacing.xs) {
                                Button("Resume") { store.send(.resumeScan) }
                                    .buttonStyle(.plain)
                                Image(systemName: "info.circle")
                                    .foregroundStyle(ddColors.textSecondary)
                                    .onHover { showPausedInfo = $0 }
                                    .popover(isPresented: $showPausedInfo, arrowEdge: .top) {
                                        Text("Session saved. You can quit and resume later.")
                                            .font(DDTypography.body)
                                            .foregroundStyle(ddColors.textPrimary)
                                            .padding(DDSpacing.md)
                                    }
                            }
                            .font(DDTypography.body)
                            .foregroundStyle(.white)
                            .ddGlassPill(size: .large, tint: DDColors.accent)
                            .accessibilityLabel("Resume scan. Session saved, you can quit and resume later.")
                        } else if isPausing {
                            HStack(spacing: DDSpacing.sm) {
                                ProgressView()
                                    .controlSize(.small)
                                Text("Pausing\u{2026}")
                                    .font(DDTypography.body)
                                    .foregroundStyle(ddColors.textSecondary)
                            }
                            .ddGlassPill(size: .large)
                            .accessibilityLabel("Pausing, waiting for scan to quiesce")
                        } else {
                            Button("Pause") { store.send(.pauseScan) }
                                .font(DDTypography.body)
                                .foregroundStyle(ddColors.textSecondary)
                                .ddGlassInteractivePill(size: .large)
                                .accessibilityLabel("Pause scan")
                        }
                    }

                    Button("Cancel Scan", role: .destructive) { store.send(.cancelScan) }
                        .font(DDTypography.body)
                        .foregroundStyle(.white)
                        .ddGlassInteractivePill(size: .large, tint: DDColors.destructive.opacity(0.6))
                }
            }
        }
    }

}

// MARK: - Scan Context Header

struct ScanContextHeader: View {
    let mode: ScanMode
    let entries: [DirectoryEntry]
    let contentEnabled: Bool
    let contentMethod: ContentMethod
    let audioEnabled: Bool
    var sourceLabel: String?
    @Environment(\.ddColors) private var ddColors

    /// Compute display labels for directory entries, disambiguating when
    /// last-component names collide among non-reference directories.
    nonisolated static func directoryLabels(for entries: [DirectoryEntry]) -> [UUID: String] {
        let scanDirs = entries.filter { !$0.isReference }
        let names = scanDirs.map { $0.path.fileName }
        var nameCounts: [String: Int] = [:]
        for name in names { nameCounts[name, default: 0] += 1 }

        var labels: [UUID: String] = [:]
        for entry in scanDirs {
            let name = entry.path.fileName
            if nameCounts[name, default: 0] > 1 {
                labels[entry.id] = entry.path.parentSlashFileName
            } else {
                labels[entry.id] = name
            }
        }
        return labels
    }

    /// Accessibility label for the scan context header. Exposed for unit testing.
    nonisolated static func accessibilityText(
        mode: ScanMode, entries: [DirectoryEntry],
        contentEnabled: Bool, contentMethod: ContentMethod, audioEnabled: Bool,
        sourceLabel: String? = nil
    ) -> String {
        if sourceLabel == SessionMetadata.photosLibraryLabel {
            var parts = ["Photos Library scan"]
            if contentEnabled {
                parts.append(contentMethod == .ssim ? "SSIM comparison" : "content hashing")
            }
            if audioEnabled { parts.append("audio fingerprinting") }
            return parts.joined(separator: ", ")
        }
        let scanDirs = entries.filter { !$0.isReference }
        let labels = directoryLabels(for: entries)
        let dirDesc: String
        switch scanDirs.count {
        case 0: dirDesc = "scan"
        case 1: dirDesc = "scanning \(labels[scanDirs[0].id] ?? scanDirs[0].path.fileName)"
        default: dirDesc = "scanning \(scanDirs.count) directories"
        }
        var parts = ["\(mode.rawValue.capitalized) mode", dirDesc]
        if contentEnabled {
            parts.append(contentMethod == .ssim ? "SSIM comparison" : "content hashing")
        }
        if audioEnabled { parts.append("audio fingerprinting") }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        GlassEffectContainer(spacing: DDSpacing.md) {
            HStack(spacing: DDSpacing.md) {
                modeBadge

                directoryList

                Spacer()

                if contentEnabled {
                    let label = contentMethod == .ssim ? "SSIM Comparison" : "Content Hashing"
                    featurePill(label, icon: "number.circle")
                }
                if audioEnabled {
                    featurePill("Audio Fingerprinting", icon: "waveform.badge.magnifyingglass")
                }
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Self.accessibilityText(
            mode: mode, entries: entries, contentEnabled: contentEnabled,
            contentMethod: contentMethod, audioEnabled: audioEnabled,
            sourceLabel: sourceLabel
        ))
    }

    private var modeBadge: some View {
        HStack(spacing: DDSpacing.xs) {
            Image(systemName: modeIcon)
                .font(DDTypography.label)
            Text(mode.rawValue.capitalized)
                .font(DDTypography.label)
        }
        .foregroundStyle(DDColors.accent)
        .ddGlassPill(size: .medium)
    }

    private var modeIcon: String { mode.systemImageName }

    @ViewBuilder
    private var directoryList: some View {
        if sourceLabel == SessionMetadata.photosLibraryLabel {
            HStack(spacing: DDSpacing.xs) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                Text("Photos Library")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }
        } else {
            let scanDirs = entries.filter { !$0.isReference }
            let maxVisible = min(scanDirs.count, 3)
            let visible = Array(scanDirs.prefix(maxVisible))
            let overflow = scanDirs.count - maxVisible
            let labels = Self.directoryLabels(for: entries)

            HStack(spacing: DDSpacing.xs) {
                Image(systemName: "folder")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                ForEach(Array(visible.enumerated()), id: \.element.id) { index, entry in
                    if index > 0 {
                        Text("\u{2022}")
                            .foregroundStyle(ddColors.textMuted)
                            .font(DDTypography.label)
                    }
                    Text(labels[entry.id] ?? entry.path.fileName)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                        .lineLimit(1)
                }
                if overflow > 0 {
                    Text("+\(overflow) more")
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textMuted)
                }
            }
        }
    }

    private func featurePill(_ text: String, icon: String) -> some View {
        HStack(spacing: DDSpacing.xs) {
            Image(systemName: icon)
                .font(DDTypography.label)
            Text(text)
                .font(DDTypography.label)
        }
        .foregroundStyle(DDColors.info)
        .ddGlassPill(size: .medium)
    }
}

// MARK: - Pipeline Bar

private struct PipelineBar: View {
    let stages: [ScanProgress.StageState]
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var activeStageID: PipelineStage? {
        stages.first(where: \.isActive)?.id
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                GlassEffectContainer(spacing: 0) {
                    HStack(alignment: .pipelineCenter, spacing: 0) {
                        ForEach(Array(stages.enumerated()), id: \.element.id) { index, stage in
                            PipelineNode(stage: stage)
                                .id(stage.id)
                            if index < stages.count - 1 {
                                PipelineConnector(
                                    leftDone: stage.isCompleted,
                                    rightActive: stages[index + 1].isActive || stages[index + 1].isCompleted
                                )
                            }
                        }
                    }
                    .padding(.horizontal, DDSpacing.lg)
                }
            }
            .onAppear {
                if let id = activeStageID {
                    proxy.scrollTo(id, anchor: .center)
                }
            }
            .onChange(of: activeStageID) { _, newID in
                if let newID {
                    withAnimation(reduceMotion ? nil : DDMotion.smooth) {
                        proxy.scrollTo(newID, anchor: .center)
                    }
                }
            }
        }
    }
}

private struct PipelineNode: View {
    let stage: ScanProgress.StageState
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulseScale: CGFloat = 1.0

    var body: some View {
        VStack(spacing: DDSpacing.xs) {
            ZStack {
                switch stage.status {
                case .completed:
                    Image(systemName: "checkmark")
                        .font(DDTypography.label)
                        .fontWeight(.bold)
                        .foregroundStyle(DDColors.surface0)
                case .active:
                    Circle()
                        .fill(DDColors.surface0.opacity(0.3))
                        .frame(width: DDSpacing.pipelinePulse, height: DDSpacing.pipelinePulse)
                        .scaleEffect(pulseScale)
                        .onAppear {
                            guard !reduceMotion else { return }
                            withAnimation(nil) { pulseScale = 1.0 }
                            withAnimation(.easeInOut(duration: DDMotion.durationSlow).repeatForever(autoreverses: true)) {
                                pulseScale = 1.3
                            }
                        }
                        .onDisappear { withAnimation(nil) { pulseScale = 1.0 } }
                        .onChange(of: stage.isActive) { wasActive, isActive in
                            if wasActive && !isActive {
                                withAnimation(nil) { pulseScale = 1.0 }
                            }
                        }
                case .pending:
                    EmptyView()
                }
            }
            .frame(width: DDSpacing.pipelineIndicator, height: DDSpacing.pipelineIndicator)
            .glassEffect(.regular.tint(fillColor), in: .circle)
            .alignmentGuide(.pipelineCenter) { d in d[VerticalAlignment.center] }

            Text(stage.displayName)
                .font(DDTypography.label)
                .foregroundStyle(stage.status == .pending ? ddColors.textMuted : ddColors.textSecondary)
                .lineLimit(1)
                .frame(minWidth: DDSpacing.pipelineLabelMinWidth)

            stageDetail
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(stage.accessibilityText)
    }

    @ViewBuilder
    private var stageDetail: some View {
        switch stage.status {
        case .completed(let elapsed, let total, _):
            VStack(spacing: DDSpacing.hairline) {
                Text("\(total)")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .contentTransition(.numericText())
                Text(ScanProgress.formatElapsed(elapsed))
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }
            .frame(height: DDSpacing.pipelineStageDetailHeight, alignment: .top)
        case .active(let current, let total):
            if let total, total > 0 {
                VStack(spacing: DDSpacing.hairline) {
                    Text("\(current)/\(total)")
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                        .contentTransition(.numericText())
                    ProgressView(value: Double(current), total: Double(total))
                        .tint(DDColors.accent)
                        .frame(width: DDSpacing.pipelineLabelMinWidth)
                        .scaleEffect(y: 0.5)
                }
                .frame(height: DDSpacing.pipelineStageDetailHeight, alignment: .top)
            } else if let total, total == 0 {
                Spacer()
                    .frame(height: DDSpacing.pipelineStageDetailHeight)
            } else if current > 0 {
                Text("\(current)")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .contentTransition(.numericText())
                    .frame(height: DDSpacing.pipelineStageDetailHeight, alignment: .top)
            } else {
                Text("Starting\u{2026}")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textSecondary)
                    .transition(reduceMotion ? .identity : .opacity.animation(DDMotion.smooth))
                    .frame(height: DDSpacing.pipelineStageDetailHeight, alignment: .top)
            }
        case .pending:
            Spacer()
                .frame(height: DDSpacing.pipelineStageDetailHeight)
        }
    }

    private var fillColor: Color {
        switch stage.status {
        case .completed: DDColors.success
        case .active: DDColors.accent
        case .pending: DDColors.surface2
        }
    }
}

private struct PipelineConnector: View {
    let leftDone: Bool
    let rightActive: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Rectangle()
            .fill(leftDone ? DDColors.success : DDColors.surface2)
            .frame(height: DDSpacing.connectorHeight)
            .frame(minWidth: DDSpacing.connectorMinWidth, maxWidth: DDSpacing.connectorMaxWidth)
            .alignmentGuide(.pipelineCenter) { d in d[VerticalAlignment.center] }
            .animation(reduceMotion ? nil : DDMotion.smooth, value: leftDone)
    }
}

#if DEBUG
#Preview("Mid-Scan") {
    let store = PreviewFixtures.progressSessionStore()
    ProgressScreen(store: store)
        .frame(width: 900, height: 700)
}

#Preview("Pausing") {
    let store = PreviewFixtures.progressSessionStore(pauseState: .pausing(sessionId: nil))
    ProgressScreen(store: store)
        .frame(width: 900, height: 700)
}
#endif

// MARK: - Segmented Progress Bar

/// A progress bar that shows completed stages in green, the active stage in blue,
/// and remaining stages in gray, matching the Penpot design mockup.
struct SegmentedProgressBar: View {
    enum VisualState: Equatable {
        case standard
        case paused(animates: Bool)

        var showsPausedAffordance: Bool {
            if case .paused = self { return true }
            return false
        }

        var pausedAffordanceAnimates: Bool {
            if case .paused(let animates) = self { return animates }
            return false
        }
    }

    private static let pausedOverlayBaseOpacity = 0.14
    private static let pausedOverlayPeakOpacity = 0.34

    let completedFraction: Double
    let activeFraction: Double
    var visualState: VisualState = .standard
    @State private var pausedOverlayOpacity: Double = 0

    var body: some View {
        GeometryReader { geometry in
            let totalWidth = geometry.size.width
            let greenWidth = totalWidth * completedFraction
            let blueWidth = totalWidth * activeFraction

            ZStack(alignment: .leading) {
                // Background (gray)
                Capsule()
                    .fill(DDColors.surface2)

                // Completed stages (green) — extends under the blue segment
                if greenWidth + blueWidth > 0 {
                    Capsule()
                        .fill(DDColors.success)
                        .frame(width: greenWidth + blueWidth)
                }

                // Active stage overlay (blue, on top of green)
                if blueWidth > 0 {
                    Capsule()
                        .fill(DDColors.accent)
                        .frame(width: blueWidth)
                        .offset(x: greenWidth)
                }

                if blueWidth > 0, visualState.showsPausedAffordance {
                    Capsule()
                        .fill(DDColors.surface0)
                        .frame(width: blueWidth)
                        .offset(x: greenWidth)
                        .opacity(pausedOverlayOpacity)
                        .allowsHitTesting(false)
                }
            }
        }
        .frame(height: 6)
        .accessibilityHidden(true)
        .onAppear { updatePausedAffordance() }
        .onChange(of: visualState) { _, _ in
            updatePausedAffordance()
        }
        .onDisappear {
            pausedOverlayOpacity = 0
        }
    }

    private func updatePausedAffordance() {
        switch visualState {
        case .standard:
            withAnimation(nil) { pausedOverlayOpacity = 0 }
        case .paused(let animates):
            if animates {
                pausedOverlayOpacity = Self.pausedOverlayBaseOpacity
                withAnimation(.easeInOut(duration: DDMotion.durationSlow * 1.8).repeatForever(autoreverses: true)) {
                    pausedOverlayOpacity = Self.pausedOverlayPeakOpacity
                }
            } else {
                pausedOverlayOpacity = Self.pausedOverlayPeakOpacity
            }
        }
    }
}

// MARK: - Primary Progress Display

struct PrimaryProgressDisplay: View {
    let progress: Double
    let scan: ScanProgress?
    let throughput: Double?
    @ScaledMetric(relativeTo: .largeTitle) private var displayStatSize: CGFloat = 48
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Accessibility label summarizing progress state. Exposed for unit testing.
    nonisolated static func accessibilityText(
        progress: Double, elapsed: TimeInterval, throughput: Double?
    ) -> String {
        var parts = ["\(Int(progress * 100)) percent complete"]
        if elapsed > 0 { parts.append("elapsed \(ScanProgress.formatElapsed(elapsed))") }
        if let t = throughput, t > 0 { parts.append(String(format: "%.1f items per second", t)) }
        return parts.joined(separator: ", ")
    }

    /// Resolve the segmented progress bar's paused styling from the current scan state.
    nonisolated static func progressBarVisualState(
        isPaused: Bool,
        isPausing: Bool,
        isCancelling: Bool,
        isComplete: Bool,
        reduceMotion: Bool
    ) -> SegmentedProgressBar.VisualState {
        guard !isCancelling, !isComplete else { return .standard }
        if isPaused { return .paused(animates: !reduceMotion) }
        if isPausing { return .paused(animates: !reduceMotion) }
        return .standard
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let elapsed = scan?.liveElapsed(at: context.date) ?? 0
            let isPaused = scan?.pause.isPaused ?? false
            let isPausing = scan?.pause.isPausing ?? false
            let barVisualState = Self.progressBarVisualState(
                isPaused: isPaused,
                isPausing: isPausing,
                isCancelling: scan?.isCancelling ?? false,
                isComplete: scan?.isComplete ?? false,
                reduceMotion: reduceMotion
            )

            VStack(spacing: DDSpacing.sm) {
                Text("\(Int(progress * 100))%")
                    .font(.system(size: displayStatSize, weight: .bold, design: .rounded).monospacedDigit())
                    .foregroundStyle(ddColors.textPrimary)
                    .contentTransition(.numericText())

                SegmentedProgressBar(
                    completedFraction: scan?.completedProgress ?? 0,
                    activeFraction: scan?.activeProgress ?? 0,
                    visualState: barVisualState
                )
                .frame(maxWidth: DDSpacing.progressBarMaxWidth)

                HStack(spacing: DDSpacing.lg) {
                    metricLabel(
                        value: ScanProgress.formatElapsed(elapsed),
                        label: "elapsed",
                        icon: "clock"
                    )
                    .opacity(elapsed > 0 ? 1 : 0)

                    metricLabel(
                        value: throughput.map { String(format: "%.1f/sec", $0) } ?? "0.0/sec",
                        label: "throughput",
                        icon: "gauge.with.dots.needle.33percent"
                    )
                    .opacity((throughput ?? 0) > 0 ? 1 : 0)

                }
                .animation(reduceMotion ? nil : DDMotion.smooth, value: elapsed > 0)
                .animation(reduceMotion ? nil : DDMotion.smooth, value: throughput != nil)
            }
            .padding(.vertical, DDSpacing.md)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Self.accessibilityText(
                progress: progress, elapsed: elapsed, throughput: throughput
            ))
        }
    }

    private func metricLabel(value: String, label: String, icon: String) -> some View {
        HStack(spacing: DDSpacing.xs) {
            Image(systemName: icon)
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
            VStack(alignment: .leading, spacing: 0) {
                Text(value)
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textSecondary)
                Text(label)
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
            }
        }
    }
}

// MARK: - Cache Efficiency Row

private struct CacheEfficiencyRow: View {
    let hits: Int
    let misses: Int
    let cacheTimeSaved: Double?
    @Environment(\.ddColors) private var ddColors
    var metadataHits: Int = 0
    var metadataMisses: Int = 0
    var contentHits: Int = 0
    var contentMisses: Int = 0
    var audioHits: Int = 0
    var audioMisses: Int = 0
    var scoreHits: Int = 0
    var scoreMisses: Int = 0

    private var total: Int { hits + misses }
    private var hitRate: Double {
        guard total > 0 else { return 0 }
        return Double(hits) / Double(total)
    }

    var body: some View {
        HStack(spacing: DDSpacing.md) {
            // Mini hit-rate bar
            ProgressView(value: hitRate)
                .tint(DDColors.success)
                .frame(width: 60)

            // Stats text
            VStack(alignment: .leading, spacing: DDSpacing.hairline) {
                Text("\(hits) cache hits (\(Int(hitRate * 100))%)")
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textSecondary)
                if !perCacheChips.isEmpty {
                    HStack(spacing: DDSpacing.sm) {
                        ForEach(perCacheChips, id: \.label) { chip in
                            Text("\(chip.hits) \(chip.label) (\(chip.rate)%)")
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textSecondary)
                        }
                    }
                }
                if let saved = cacheTimeSaved, saved > 0 {
                    Text("Saved ~\(ScanProgress.formatElapsed(saved))")
                        .font(DDTypography.metadata)
                        .foregroundStyle(DDColors.success)
                }
            }

            Spacer()

            Image(systemName: "cylinder.split.1x2")
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
        }
        .padding(DDDensity.compact)
        .ddGlassCard()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private struct CacheChip {
        let label: String
        let hits: Int
        let rate: Int
    }

    private var perCacheChips: [CacheChip] {
        let sources: [(String, Int, Int)] = [
            ("metadata", metadataHits, metadataMisses),
            ("content", contentHits, contentMisses),
            ("audio", audioHits, audioMisses),
            ("score", scoreHits, scoreMisses),
        ]
        return sources.compactMap { label, hits, misses in
            guard hits > 0 else { return nil }
            let total = hits + misses
            let rate = total > 0 ? Int(Double(hits) / Double(total) * 100) : 0
            return CacheChip(label: label, hits: hits, rate: rate)
        }
    }

    private var accessibilityText: String {
        var text = "Cache efficiency \(Int(hitRate * 100)) percent, \(hits) hits, \(misses) misses"
        for chip in perCacheChips {
            text += ", \(chip.hits) \(chip.label) at \(chip.rate) percent"
        }
        if let saved = cacheTimeSaved, saved > 0 {
            text += ", saved approximately \(ScanProgress.formatElapsed(saved))"
        }
        return text
    }
}

// MARK: - Active File Detail

private struct ActiveFileDetail: View {
    let stage: ScanProgress.StageState
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        if let file = stage.currentFile {
            HStack(spacing: DDSpacing.sm) {
                Image(systemName: "doc")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                Text(file.parentSlashFileName)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .frame(maxWidth: DDSpacing.activeFileMaxWidth)
            .accessibilityLabel("Processing \(file.fileName)")
        }
    }
}

// MARK: - Stage Stat Counters

private struct StageStatCounters: View {
    let stages: [ScanProgress.StageState]

    var body: some View {
        let stats = completedStats
        if !stats.isEmpty {
            GlassEffectContainer(spacing: DDSpacing.md) {
                HStack(spacing: DDSpacing.md) {
                    ForEach(stats, id: \.label) { stat in
                        DDStatCapsule(value: stat.value, label: stat.label, size: .large, isActive: stat.isActive)
                    }
                }
            }
        }
    }

    /// Stat entry with active/completed context for color coding.
    struct StatEntry: Equatable {
        let value: String
        let label: String
        let isActive: Bool
    }

    /// Builds stat entries for completed and active stages.
    var completedStats: [StatEntry] {
        var stats: [StatEntry] = []
        for stage in stages {
            switch stage.status {
            case .completed(_, let total, let extras):
                switch stage.id {
                case .authorize:
                    stats.append(StatEntry(value: "\u{2713}", label: "authorized", isActive: false))
                case .scan:
                    stats.append(StatEntry(value: "\(total)", label: "files scanned", isActive: false))
                case .extract:
                    stats.append(StatEntry(value: "\(total)", label: "metadata extracted", isActive: false))
                case .filter:
                    stats.append(StatEntry(value: "\(total)", label: "after filter", isActive: false))
                case .contentHash:
                    let hashed = extras["hashed"] ?? total
                    stats.append(StatEntry(value: "\(hashed)", label: "hashed", isActive: false))
                case .ssimExtract:
                    stats.append(StatEntry(value: "\(total)", label: "SSIM extracted", isActive: false))
                case .audioFingerprint:
                    let fp = extras["fingerprinted"] ?? total
                    stats.append(StatEntry(value: "\(fp)", label: "fingerprinted", isActive: false))
                case .score:
                    stats.append(StatEntry(value: "\(total)", label: "pairs scored", isActive: false))
                default:
                    break
                }
            case .active(let current, let total):
                // Show active stage stat in blue when there is progress data
                if current > 0 || total != nil {
                    let displayValue: String
                    if let total {
                        displayValue = "\(current)/\(total)"
                    } else {
                        displayValue = "\(current)"
                    }
                    switch stage.id {
                    case .scan:
                        stats.append(StatEntry(value: displayValue, label: "scanning", isActive: true))
                    case .extract:
                        stats.append(StatEntry(value: displayValue, label: "extracting", isActive: true))
                    case .contentHash:
                        stats.append(StatEntry(value: displayValue, label: "hashing", isActive: true))
                    case .ssimExtract:
                        stats.append(StatEntry(value: displayValue, label: "SSIM extracting", isActive: true))
                    case .audioFingerprint:
                        stats.append(StatEntry(value: displayValue, label: "fingerprinting", isActive: true))
                    case .score:
                        stats.append(StatEntry(value: displayValue, label: "scoring", isActive: true))
                    default:
                        break
                    }
                }
            case .pending:
                break
            }
        }
        return stats
    }

}
