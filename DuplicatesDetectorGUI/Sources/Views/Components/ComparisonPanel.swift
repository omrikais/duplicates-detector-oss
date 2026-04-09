import SwiftUI

// MARK: - Comparison Panel

/// Visual comparison surface for a selected pair: mode-aware media viewer,
/// action bar, metadata diff table, and score breakdown detail.
struct ComparisonPanel: View {
    let pair: PairResult
    let scanMode: ScanMode
    let activeAction: ActionType
    let currentPairIndex: Int?
    let totalFilteredPairs: Int
    var onAction: (PairAction) -> Void
    var onKeepA: () -> Void
    var onKeepB: () -> Void
    var onPrevious: () -> Void
    var onSkip: () -> Void
    var onSkipAndIgnore: () -> Void
    var isAtFirstPair: Bool = false
    var resolution: PairResolutionStatus = .active
    @Environment(\.ddColors) private var ddColors

    /// Build the score header accessibility label. Exposed for unit testing.
    nonisolated static func scoreHeaderAccessibilityText(score: Double) -> String {
        "Score \(ScoreRing.formattedScore(score)) percent"
    }

    /// Derive display labels for both files. When filenames are identical,
    /// disambiguate with the parent directory name.
    nonisolated static func fileLabels(fileA: String, fileB: String) -> (a: String, b: String) {
        let nameA = fileA.fileName
        let nameB = fileB.fileName
        if nameA == nameB {
            return (fileA.parentSlashFileName, fileB.parentSlashFileName)
        }
        return (nameA, nameB)
    }

    private var fileLabels: (a: String, b: String) {
        Self.fileLabels(fileA: pair.fileA, fileB: pair.fileB)
    }

    private enum MediaType {
        case image, video, audio, document
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: DDSpacing.lg) {
                    scoreHeader
                    mediaComparison
                    MetadataDiffTable(metaA: pair.fileAMetadata, metaB: pair.fileBMetadata,
                                      labelA: fileLabels.a, labelB: fileLabels.b)
                    ScoreBreakdownDetail(
                        breakdown: pair.breakdown,
                        detail: pair.detail,
                        totalScore: pair.score
                    )
                }
                .padding(DDDensity.regular)
            }
            Divider()
            ComparisonActionBar(
                pair: pair,
                activeAction: activeAction,
                currentIndex: currentPairIndex,
                totalPairs: totalFilteredPairs,
                onKeepA: onKeepA,
                onKeepB: onKeepB,
                onPrevious: onPrevious,
                onSkip: onSkip,
                onSkipAndIgnore: onSkipAndIgnore,
                isAtFirstPair: isAtFirstPair,
                resolution: resolution
            )
            .padding(.horizontal, DDDensity.regular.leading)
            if let index = currentPairIndex {
                ProgressView(value: Double(index + 1), total: Double(totalFilteredPairs))
                    .tint(DDColors.accent)
            }
        }
        .background(DDColors.surface1)
    }

    // MARK: - Mode-Aware Media Comparison

    @ViewBuilder
    private var mediaComparison: some View {
        switch resolvedMediaType {
        case .image:
            ImageComparisonView(pathA: pair.fileA, pathB: pair.fileB,
                                labelA: fileLabels.a, labelB: fileLabels.b)
                .frame(minHeight: 300, maxHeight: 600)
        case .video:
            VideoComparisonView(pathA: pair.fileA, pathB: pair.fileB,
                                labelA: fileLabels.a, labelB: fileLabels.b)
                .frame(minHeight: 300, maxHeight: 600)
        case .audio, .document:
            thumbnailComparison
        }
    }

    private static let imageExtensions: Set<String> = [
        "jpg", "jpeg", "png", "heic", "heif", "tiff", "tif", "bmp", "webp", "gif",
    ]

    private var resolvedMediaType: MediaType {
        switch scanMode {
        case .image: .image
        case .video: .video
        case .audio: .audio
        case .document: .document
        case .auto: detectMediaType()
        }
    }

    private func detectMediaType() -> MediaType {
        let ext = (pair.fileA as NSString).pathExtension.lowercased()
        if Self.imageExtensions.contains(ext) { return .image }
        if pair.fileAMetadata.duration != nil { return .video }
        if pair.fileAMetadata.width != nil { return .image }
        return .video
    }

    // MARK: - Score Header

    private var scoreHeader: some View {
        HStack(spacing: DDSpacing.md) {
            ScoreRing(score: pair.score, size: .regular)

            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                Text(pair.fileA)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.head)
                Text(pair.fileB)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.head)

                if let keepPath = pair.keepPath {
                    FileBadges(isKeep: true, isReference: false,
                               style: .label(keepText: "Keep: \(keepPath.fileName)", referenceText: ""))
                }
            }

            Spacer()

            // Indicators
            if pair.fileAIsReference || pair.fileBIsReference {
                HStack(spacing: DDSpacing.xs) {
                    FileBadges(isKeep: false, isReference: true,
                               style: .label(keepText: "", referenceText: "Reference"))
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Self.scoreHeaderAccessibilityText(score: pair.score))
    }

    // MARK: - Thumbnail Comparison

    private var thumbnailComparison: some View {
        HStack(alignment: .top, spacing: DDSpacing.md) {
            fileThumbnailColumn(
                path: pair.fileA,
                meta: pair.fileAMetadata,
                isReference: pair.fileAIsReference,
                isKeep: pair.keepPath == pair.fileA
            )
            fileThumbnailColumn(
                path: pair.fileB,
                meta: pair.fileBMetadata,
                isReference: pair.fileBIsReference,
                isKeep: pair.keepPath == pair.fileB
            )
        }
    }

    private func fileThumbnailColumn(
        path: String, meta: FileMetadata,
        isReference: Bool, isKeep: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            // File label with badges
            HStack(spacing: DDSpacing.xs) {
                FileBadges(isKeep: isKeep, isReference: isReference)
                Text(path.fileName)
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            // Large thumbnail
            ThumbnailView(
                path: path,
                base64: meta.thumbnail,
                maxWidth: DDSpacing.thumbnailLargeWidth,
                maxHeight: DDSpacing.thumbnailLargeHeight,
                contentMode: .fit,
                modificationDate: meta.mtime.map { Date(timeIntervalSince1970: $0) }
            )

            // Quick file size under thumbnail
            Text(DDFormatters.formatFileSize(meta.fileSize))
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }

}

// MARK: - Metadata Diff Table

/// Three-column grid comparing metadata fields between two files.
/// Differing values are highlighted; matching values are muted.
struct MetadataDiffTable: View {
    let metaA: FileMetadata
    let metaB: FileMetadata
    var labelA: String = "File A"
    var labelB: String = "File B"
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Metadata Comparison")
                .font(DDTypography.body.weight(.semibold))
                .foregroundStyle(ddColors.textPrimary)

            Grid(alignment: .leading, horizontalSpacing: DDSpacing.md, verticalSpacing: DDSpacing.sm) {
                // Header row
                GridRow {
                    Text("")
                        .frame(width: DDSpacing.labelColumnWidth, alignment: .leading)
                    Text(labelA)
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Text(labelB)
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                // Size (always present)
                diffRow(
                    "Size",
                    DDFormatters.formatFileSize(metaA.fileSize),
                    DDFormatters.formatFileSize(metaB.fileSize),
                    differs: metaA.fileSize != metaB.fileSize
                )

                // Duration
                if metaA.duration != nil || metaB.duration != nil {
                    let durA = metaA.duration.map { DDFormatters.formatDuration($0) } ?? "\u{2014}"
                    let durB = metaB.duration.map { DDFormatters.formatDuration($0) } ?? "\u{2014}"
                    diffRow("Duration", durA, durB, differs: durA != durB)
                }

                // Resolution
                if metaA.width != nil || metaB.width != nil {
                    diffRow(
                        "Resolution",
                        DDFormatters.formatResolution(width: metaA.width, height: metaA.height) ?? "\u{2014}",
                        DDFormatters.formatResolution(width: metaB.width, height: metaB.height) ?? "\u{2014}",
                        differs: metaA.width != metaB.width || metaA.height != metaB.height
                    )
                }

                // Codec
                if metaA.codec != nil || metaB.codec != nil {
                    diffRow(
                        "Codec",
                        metaA.codec ?? "\u{2014}",
                        metaB.codec ?? "\u{2014}",
                        differs: metaA.codec != metaB.codec
                    )
                }

                // Bitrate
                if metaA.bitrate != nil || metaB.bitrate != nil {
                    let brA = metaA.bitrate.map { DDFormatters.formatBitrate($0) } ?? "\u{2014}"
                    let brB = metaB.bitrate.map { DDFormatters.formatBitrate($0) } ?? "\u{2014}"
                    diffRow("Bitrate", brA, brB, differs: brA != brB)
                }

                // Framerate
                if metaA.framerate != nil || metaB.framerate != nil {
                    let fpsA = metaA.framerate.map { DDFormatters.formatFramerate($0) } ?? "\u{2014}"
                    let fpsB = metaB.framerate.map { DDFormatters.formatFramerate($0) } ?? "\u{2014}"
                    diffRow("FPS", fpsA, fpsB, differs: fpsA != fpsB)
                }

                // Audio channels
                if metaA.audioChannels != nil || metaB.audioChannels != nil {
                    diffRow(
                        "Audio",
                        metaA.audioChannels.map { DDFormatters.formatAudioChannels($0) } ?? "\u{2014}",
                        metaB.audioChannels.map { DDFormatters.formatAudioChannels($0) } ?? "\u{2014}",
                        differs: metaA.audioChannels != metaB.audioChannels
                    )
                }

                // Modified
                if metaA.mtime != nil || metaB.mtime != nil {
                    let mtA = metaA.mtime.map { DDFormatters.formatRelativeDate($0) } ?? "\u{2014}"
                    let mtB = metaB.mtime.map { DDFormatters.formatRelativeDate($0) } ?? "\u{2014}"
                    diffRow("Modified", mtA, mtB, differs: mtA != mtB)
                }

                // Audio tags
                if metaA.tagTitle != nil || metaB.tagTitle != nil {
                    diffRow("Title",
                            metaA.tagTitle ?? "\u{2014}",
                            metaB.tagTitle ?? "\u{2014}",
                            differs: metaA.tagTitle != metaB.tagTitle)
                }

                if metaA.tagArtist != nil || metaB.tagArtist != nil {
                    diffRow("Artist",
                            metaA.tagArtist ?? "\u{2014}",
                            metaB.tagArtist ?? "\u{2014}",
                            differs: metaA.tagArtist != metaB.tagArtist)
                }

                if metaA.tagAlbum != nil || metaB.tagAlbum != nil {
                    diffRow("Album",
                            metaA.tagAlbum ?? "\u{2014}",
                            metaB.tagAlbum ?? "\u{2014}",
                            differs: metaA.tagAlbum != metaB.tagAlbum)
                }

                // Document metadata
                if metaA.pageCount != nil || metaB.pageCount != nil {
                    diffRow(
                        "Pages",
                        metaA.pageCount.map(String.init) ?? "\u{2014}",
                        metaB.pageCount.map(String.init) ?? "\u{2014}",
                        differs: metaA.pageCount != metaB.pageCount
                    )
                }

                if metaA.docTitle != nil || metaB.docTitle != nil {
                    diffRow("Title",
                            metaA.docTitle ?? "\u{2014}",
                            metaB.docTitle ?? "\u{2014}",
                            differs: metaA.docTitle != metaB.docTitle)
                }

                if metaA.docAuthor != nil || metaB.docAuthor != nil {
                    diffRow("Author",
                            metaA.docAuthor ?? "\u{2014}",
                            metaB.docAuthor ?? "\u{2014}",
                            differs: metaA.docAuthor != metaB.docAuthor)
                }

                if metaA.docCreated != nil || metaB.docCreated != nil {
                    diffRow("Created",
                            metaA.docCreated ?? "\u{2014}",
                            metaB.docCreated ?? "\u{2014}",
                            differs: metaA.docCreated != metaB.docCreated)
                }
            }
        }
        .padding(DDDensity.regular)
        .background(DDColors.surface2, in: RoundedRectangle(cornerRadius: DDRadius.medium))
    }

    private func diffRow(_ label: String, _ valueA: String, _ valueB: String, differs: Bool) -> some View {
        GridRow {
            Text(label)
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textSecondary)
                .frame(width: DDSpacing.labelColumnWidth, alignment: .leading)
            diffCell(valueA, differs: differs)
                .frame(maxWidth: .infinity, alignment: .leading)
            diffCell(valueB, differs: differs)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label): \(labelA) \(valueA), \(labelB) \(valueB)")
    }

    private func diffCell(_ value: String, differs: Bool) -> some View {
        Text(value)
            .font(DDTypography.monospaced)
            .foregroundStyle(differs ? ddColors.textPrimary : ddColors.textMuted)
            .padding(DDDensity.compact)
            .background(
                differs ? DDColors.accent.opacity(0.1) : .clear,
                in: RoundedRectangle(cornerRadius: DDRadius.small)
            )
    }
}

// MARK: - Score Breakdown Detail

/// Full score breakdown: stacked bar + per-comparator detail rows.
struct ScoreBreakdownDetail: View {
    let breakdown: [String: Double?]
    let detail: [String: DetailScore]
    let totalScore: Double
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Score Breakdown")
                .font(DDTypography.body.weight(.semibold))
                .foregroundStyle(ddColors.textPrimary)

            BreakdownBar(breakdown: breakdown, detail: detail, totalScore: totalScore)
                .frame(height: DDSpacing.breakdownBarDetail)

            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                ForEach(sortedComparators, id: \.key) { key, detailScore in
                    ComparatorRow(
                        key: key,
                        raw: detailScore.raw,
                        contribution: breakdown[key] ?? nil
                    )
                }
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private var sortedComparators: [(key: String, value: DetailScore)] {
        detail.sorted {
            if $0.value.weight != $1.value.weight { return $0.value.weight > $1.value.weight }
            return $0.key < $1.key
        }
    }
}

// MARK: - Comparator Row

/// Single row in the score breakdown: color dot, name, raw%, contribution.
private struct ComparatorRow: View {
    let key: String
    let raw: Double
    let contribution: Double?
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        HStack(spacing: DDSpacing.sm) {
            Circle()
                .fill(DDColors.comparatorColor(for: key))
                .frame(width: DDSpacing.statusDotSize + 2, height: DDSpacing.statusDotSize + 2)

            Text(DDComparators.displayName(for: key))
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textPrimary)
                .frame(width: DDSpacing.labelColumnWidth, alignment: .leading)

            Text(String(format: "%.0f%%", raw * 100))
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
                .frame(width: DDSpacing.scoreColumnWidth, alignment: .trailing)

            if let c = contribution {
                Text(String(format: "%.1f pts", c))
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)
            } else {
                Text("\u{2014}")
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textMuted)
            }
        }
    }
}

#if DEBUG
#Preview("Comparison Panel — High Score") {
    let pair = PreviewFixtures.samplePairResults[0]
    ComparisonPanel(
        pair: pair, scanMode: .video, activeAction: .trash,
        currentPairIndex: 0, totalFilteredPairs: 2,
        onAction: { _ in }, onKeepA: {}, onKeepB: {}, onPrevious: {},
        onSkip: {}, onSkipAndIgnore: {}
    )
    .frame(width: 700, height: 700)
}

#Preview("Comparison Panel — Lower Score") {
    let pair = PreviewFixtures.samplePairResults[1]
    ComparisonPanel(
        pair: pair, scanMode: .video, activeAction: .trash,
        currentPairIndex: 1, totalFilteredPairs: 2,
        onAction: { _ in }, onKeepA: {}, onKeepB: {}, onPrevious: {},
        onSkip: {}, onSkipAndIgnore: {}
    )
    .frame(width: 700, height: 700)
}

#Preview("Metadata Diff Table") {
    let pair = PreviewFixtures.samplePairResults[0]
    MetadataDiffTable(metaA: pair.fileAMetadata, metaB: pair.fileBMetadata)
        .padding()
        .frame(width: 600)
}

#Preview("Score Breakdown Detail") {
    let pair = PreviewFixtures.samplePairResults[0]
    ScoreBreakdownDetail(
        breakdown: pair.breakdown,
        detail: pair.detail,
        totalScore: pair.score
    )
    .padding()
    .frame(width: 600)
}

#Preview("Thumbnail — Valid") {
    ThumbnailView(
        base64: "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAEUlEQVR4nGMICEjBihgGUgIARegwwWN1S5IAAAAASUVORK5CYII=",
        fixedWidth: 120, fixedHeight: 90
    )
    .padding()
}

#Preview("Thumbnail — Missing") {
    ThumbnailView(base64: nil, fixedWidth: 120, fixedHeight: 90)
        .padding()
}
#endif
