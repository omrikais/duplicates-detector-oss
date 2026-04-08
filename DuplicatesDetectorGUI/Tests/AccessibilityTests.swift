import AVFoundation
import Foundation
import SwiftUI
import Testing

@testable import DuplicatesDetector

// MARK: - ScoreRing Size Constants Tests

@Suite("ScoreRing size constants")
struct ScoreRingSizeTests {
    // Actual accessibility attributes (.accessibilityLabel, .accessibilityValue)
    // are SwiftUI view modifiers that require XCUITest to verify at runtime.

    @Test("ScoreRing Size.compact diameter is 32")
    func compactDiameter() {
        #expect(ScoreRing.Size.compact.diameter == 32)
    }

    @Test("ScoreRing Size.regular diameter is 56")
    func regularDiameter() {
        #expect(ScoreRing.Size.regular.diameter == 56)
    }

    @Test("ScoreRing Size.compact lineWidth is 3")
    func compactLineWidth() {
        #expect(ScoreRing.Size.compact.lineWidth == 3)
    }

    @Test("ScoreRing Size.regular lineWidth is 5")
    func regularLineWidth() {
        #expect(ScoreRing.Size.regular.lineWidth == 5)
    }

    @Test("ScoreRing Size.compact uses scoreLabelCompact font")
    func compactFont() {
        #expect(ScoreRing.Size.compact.font == DDTypography.scoreLabelCompact)
    }

    @Test("ScoreRing Size.regular uses scoreLabelRegular font")
    func regularFont() {
        #expect(ScoreRing.Size.regular.font == DDTypography.scoreLabelRegular)
    }
}

// MARK: - BreakdownBar Accessibility Summary Tests

@Suite("BreakdownBar accessibility summary")
struct BreakdownBarAccessibilityTests {

    @Test("Summary with typical video breakdown lists segments descending by value")
    func typicalVideoBreakdown() {
        let breakdown: [String: Double?] = [
            "filename": 48.0,
            "duration": 29.5,
            "resolution": 10.0,
            "fileSize": 8.0,
        ]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "Score breakdown: Filename 48, Duration 29, Resolution 10, File Size 8")
    }

    @Test("Summary filters out nil values")
    func nilValuesFiltered() {
        let breakdown: [String: Double?] = [
            "filename": 40.0,
            "duration": nil,
            "resolution": 10.0,
        ]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "Score breakdown: Filename 40, Resolution 10")
    }

    @Test("Summary filters out zero values")
    func zeroValuesFiltered() {
        let breakdown: [String: Double?] = [
            "filename": 40.0,
            "duration": 0.0,
            "resolution": 10.0,
        ]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "Score breakdown: Filename 40, Resolution 10")
    }

    @Test("Summary with single segment has no comma separation")
    func singleSegment() {
        let breakdown: [String: Double?] = ["content": 95.0]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "Score breakdown: Content 95")
    }

    @Test("Summary with all nil/zero values produces empty breakdown list")
    func allFilteredOut() {
        let breakdown: [String: Double?] = [
            "filename": nil,
            "duration": 0.0,
        ]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "No score breakdown")
    }

    @Test("Summary uses displayName aliases correctly for filesize/fileSize")
    func fileSizeAlias() {
        let breakdown1: [String: Double?] = ["fileSize": 25.0]
        let breakdown2: [String: Double?] = ["filesize": 25.0]
        let summary1 = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown1)
        let summary2 = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown2)
        #expect(summary1 == "Score breakdown: File Size 25")
        #expect(summary2 == "Score breakdown: File Size 25")
    }

    @Test("Summary truncates fractional values via Int conversion")
    func fractionalTruncation() {
        let breakdown: [String: Double?] = ["filename": 48.9, "duration": 29.1]
        let summary = BreakdownBar.buildAccessibilitySummary(breakdown: breakdown)
        #expect(summary == "Score breakdown: Filename 48, Duration 29")
    }
}

// MARK: - DDTypography.statValue Token Tests

@Suite("DDTypography.statValue token")
struct StatValueTypographyTests {

    @Test("statValue token exists and is a Font")
    func statValueExists() {
        let font: Font = DDTypography.statValue
        #expect(font != DDTypography.body)
        #expect(font != DDTypography.metadata)
        #expect(font != DDTypography.label)
    }

    @Test("statValue is .title3.monospacedDigit().bold()")
    func statValueIsTitle3MonospacedDigitBold() {
        let expected: Font = .title3.monospacedDigit().bold()
        #expect(DDTypography.statValue == expected)
    }

    @Test("statValue differs from displayStat")
    func statValueDiffersFromDisplayStat() {
        #expect(DDTypography.statValue != DDTypography.displayStat)
    }

    @Test("statValue differs from monospaced token")
    func statValueDiffersFromMonospaced() {
        #expect(DDTypography.statValue != DDTypography.monospaced)
    }
}

// MARK: - DDStatCapsule Accessibility Tests

@Suite("DDStatCapsule accessibility label")
struct DDStatCapsuleAccessibilityTests {

    @Test("accessibilityText combines value and label")
    func accessibilityTextFormat() {
        #expect(DDStatCapsule.accessibilityText(value: "42", label: "pairs") == "42 pairs")
    }

    @Test("accessibilityText with formatted file size")
    func accessibilityTextFileSize() {
        #expect(DDStatCapsule.accessibilityText(value: "1.2 GB", label: "savings") == "1.2 GB savings")
    }

    @Test("accessibilityText with zero value")
    func accessibilityTextZero() {
        #expect(DDStatCapsule.accessibilityText(value: "0", label: "results") == "0 results")
    }

    @Test("accessibilityText returns non-empty for representative inputs")
    func accessibilityTextNonEmpty() {
        let result = DDStatCapsule.accessibilityText(value: "100", label: "scanned")
        #expect(!result.isEmpty)
    }
}

// MARK: - ScoreRing Formatting Tests

@Suite("ScoreRing score formatting")
struct ScoreRingFormattingTests {

    @Test("Fractional scores round to the nearest integer string")
    func fractionalScoreRounds() {
        #expect(ScoreRing.formattedScore(89.9) == "90")
        #expect(ScoreRing.formattedScore(49.9) == "50")
    }

    @Test("Whole scores preserve their integer value")
    func wholeScoresRemainStable() {
        #expect(ScoreRing.formattedScore(0.0) == "0")
        #expect(ScoreRing.formattedScore(100.0) == "100")
    }
}

// MARK: - PairQueueRow Accessibility Tests

@Suite("PairQueueRow accessibility label")
struct PairQueueRowAccessibilityTests {

    @Test("Normal case: filenames and score are included")
    func normalCase() {
        let text = PairQueueRow.accessibilityText(
            fileA: "/videos/clip_a.mp4",
            fileB: "/videos/clip_b.mp4",
            score: 87.3
        )
        #expect(text == "clip_a.mp4 versus clip_b.mp4, score 87")
    }

    @Test("Fractional scores round in accessibility text")
    func roundedFractionalScore() {
        let text = PairQueueRow.accessibilityText(
            fileA: "/videos/clip_a.mp4",
            fileB: "/videos/clip_b.mp4",
            score: 89.9
        )
        #expect(text == "clip_a.mp4 versus clip_b.mp4, score 90")
    }

    @Test("Score 0 produces 'score 0'")
    func scoreZero() {
        let text = PairQueueRow.accessibilityText(
            fileA: "/a.mp4", fileB: "/b.mp4", score: 0.0
        )
        #expect(text.contains("score 0"))
    }

    @Test("Score 100 produces 'score 100'")
    func scoreHundred() {
        let text = PairQueueRow.accessibilityText(
            fileA: "/a.mp4", fileB: "/b.mp4", score: 100.0
        )
        #expect(text.contains("score 100"))
    }

    @Test("Bare filenames without directory work correctly")
    func bareFilenames() {
        let text = PairQueueRow.accessibilityText(
            fileA: "video.mp4", fileB: "video_copy.mp4", score: 92.0
        )
        #expect(text == "video.mp4 versus video_copy.mp4, score 92")
    }
}

// MARK: - GroupQueueRow Accessibility Tests

@Suite("GroupQueueRow accessibility label")
struct GroupQueueRowAccessibilityTests {

    @Test("Normal case: group ID, file count, score range")
    func normalCase() {
        let text = GroupQueueRow.accessibilityText(
            groupId: 3, fileCount: 5, minScore: 72.0, maxScore: 95.0
        )
        #expect(text == "Group 3, 5 files, score 72 to 95")
    }

    @Test("Single file group")
    func singleFile() {
        let text = GroupQueueRow.accessibilityText(
            groupId: 1, fileCount: 1, minScore: 88.0, maxScore: 88.0
        )
        #expect(text == "Group 1, 1 file, score 88 to 88")
    }

    @Test("Score range 0 to 100")
    func fullScoreRange() {
        let text = GroupQueueRow.accessibilityText(
            groupId: 7, fileCount: 10, minScore: 0.0, maxScore: 100.0
        )
        #expect(text == "Group 7, 10 files, score 0 to 100")
    }

    @Test("Fractional score bounds round in accessibility text")
    func fractionalBoundsRound() {
        let text = GroupQueueRow.accessibilityText(
            groupId: 4, fileCount: 3, minScore: 49.9, maxScore: 89.9
        )
        #expect(text == "Group 4, 3 files, score 50 to 90")
    }
}

// MARK: - PipelineNode Accessibility Tests

@Suite("PipelineNode accessibility label via StageState")
struct PipelineNodeAccessibilityTests {

    @Test("Pending stage label")
    func pendingStage() {
        let stage = ScanProgress.StageState(
            id: .scan, displayName: "Scanning files"
        )
        #expect(stage.accessibilityText == "Scanning files, pending")
    }

    @Test("Active stage with total")
    func activeWithTotal() {
        var stage = ScanProgress.StageState(
            id: .extract, displayName: "Extracting metadata"
        )
        stage.status = .active(current: 42, total: 100)
        #expect(stage.accessibilityText == "Extracting metadata, in progress, 42 of 100")
    }

    @Test("Active stage without total")
    func activeWithoutTotal() {
        var stage = ScanProgress.StageState(
            id: .scan, displayName: "Scanning files"
        )
        stage.status = .active(current: 10, total: nil)
        #expect(stage.accessibilityText == "Scanning files, in progress")
    }

    @Test("Completed stage includes count and elapsed time")
    func completedStage() {
        var stage = ScanProgress.StageState(
            id: .score, displayName: "Scoring pairs"
        )
        stage.status = .completed(elapsed: 2.5, total: 150, extras: [:])
        #expect(stage.accessibilityText == "Scoring pairs, completed, 150 items in 2.5s")
    }

    @Test("Completed stage with sub-second elapsed uses ms")
    func completedSubSecond() {
        var stage = ScanProgress.StageState(
            id: .filter, displayName: "Filtering"
        )
        stage.status = .completed(elapsed: 0.045, total: 80, extras: [:])
        #expect(stage.accessibilityText == "Filtering, completed, 80 items in 45ms")
    }
}

// MARK: - ComparisonPanel Score Header Accessibility Tests

@Suite("ComparisonPanel score header accessibility label")
struct ComparisonPanelScoreHeaderTests {

    @Test("Normal score")
    func normalScore() {
        #expect(ComparisonPanel.scoreHeaderAccessibilityText(score: 87.3) == "Score 87 percent")
    }

    @Test("Score 0")
    func scoreZero() {
        #expect(ComparisonPanel.scoreHeaderAccessibilityText(score: 0.0) == "Score 0 percent")
    }

    @Test("Score 100")
    func scoreHundred() {
        #expect(ComparisonPanel.scoreHeaderAccessibilityText(score: 100.0) == "Score 100 percent")
    }

    @Test("Fractional score rounds")
    func fractionalScore() {
        #expect(ComparisonPanel.scoreHeaderAccessibilityText(score: 49.9) == "Score 50 percent")
    }
}

// MARK: - ComparisonPanel File Labels Tests

@Suite("ComparisonPanel.fileLabels disambiguation")
struct ComparisonPanelFileLabelsTests {

    @Test("Different filenames return bare filenames")
    func differentFilenames() {
        let labels = ComparisonPanel.fileLabels(
            fileA: "/videos/clip_a.mp4",
            fileB: "/videos/clip_b.mp4"
        )
        #expect(labels.a == "clip_a.mp4")
        #expect(labels.b == "clip_b.mp4")
    }

    @Test("Identical filenames in different parents disambiguate with parent directory")
    func sameNameDifferentParents() {
        let labels = ComparisonPanel.fileLabels(
            fileA: "/media/originals/video.mp4",
            fileB: "/media/copies/video.mp4"
        )
        #expect(labels.a == "originals/video.mp4")
        #expect(labels.b == "copies/video.mp4")
    }

    @Test("Identical filenames and identical parents still produce parent/name labels without crash")
    func sameNameSameParent() {
        let labels = ComparisonPanel.fileLabels(
            fileA: "/media/folder/video.mp4",
            fileB: "/media/folder/video.mp4"
        )
        #expect(labels.a == "folder/video.mp4")
        #expect(labels.b == "folder/video.mp4")
    }

    @Test("Bare filenames with no directory return names directly when different")
    func bareFilenamesDifferent() {
        let labels = ComparisonPanel.fileLabels(fileA: "alpha.mp4", fileB: "beta.mp4")
        #expect(labels.a == "alpha.mp4")
        #expect(labels.b == "beta.mp4")
    }

    @Test("Bare identical filenames with no directory return just the filename")
    func bareFilenamesSame() {
        let labels = ComparisonPanel.fileLabels(fileA: "video.mp4", fileB: "video.mp4")
        #expect(labels.a == "video.mp4")
        #expect(labels.b == "video.mp4")
    }

    @Test("Deeply nested paths with identical leaf names use immediate parent only")
    func deeplyNestedSameLeaf() {
        let labels = ComparisonPanel.fileLabels(
            fileA: "/a/b/c/d/original/clip.mp4",
            fileB: "/x/y/z/backup/clip.mp4"
        )
        #expect(labels.a == "original/clip.mp4")
        #expect(labels.b == "backup/clip.mp4")
    }
}

// MARK: - ComparisonActionBar Pair Counter Accessibility Tests

@Suite("ComparisonActionBar pair counter accessibility label")
struct ComparisonActionBarPairCounterTests {

    @Test("Normal pair counter")
    func normalCounter() {
        #expect(ComparisonActionBar.pairCounterAccessibilityText(index: 2, total: 12) == "Pair 3 of 12")
    }

    @Test("First pair")
    func firstPair() {
        #expect(ComparisonActionBar.pairCounterAccessibilityText(index: 0, total: 5) == "Pair 1 of 5")
    }

    @Test("Last pair")
    func lastPair() {
        #expect(ComparisonActionBar.pairCounterAccessibilityText(index: 4, total: 5) == "Pair 5 of 5")
    }

    @Test("Single pair")
    func singlePair() {
        #expect(ComparisonActionBar.pairCounterAccessibilityText(index: 0, total: 1) == "Pair 1 of 1")
    }
}

// MARK: - AVPlayerPool Tests

@MainActor
@Suite("AVPlayerPool acquire and release lifecycle")
struct AVPlayerPoolTests {

    @Test("acquire returns an AVPlayer with a currentItem loaded")
    func acquireReturnsPlayerWithItem() {
        let pool = AVPlayerPool()
        let url = URL(fileURLWithPath: "/tmp/test-video.mp4")
        let player = pool.acquire(for: url)
        #expect(player.currentItem != nil)
    }

    @Test("release pauses the player")
    func releasePausesPlayer() {
        let pool = AVPlayerPool()
        let url = URL(fileURLWithPath: "/tmp/test-video.mp4")
        let player = pool.acquire(for: url)
        pool.release(player)
        #expect(player.rate == 0)
    }

    @Test("release sets currentItem to nil")
    func releaseClearsCurrentItem() {
        let pool = AVPlayerPool()
        let url = URL(fileURLWithPath: "/tmp/test-video.mp4")
        let player = pool.acquire(for: url)
        pool.release(player)
        #expect(player.currentItem == nil)
    }

    @Test("acquire reuses a released player from the pool")
    func acquireReusesReleasedPlayer() {
        let pool = AVPlayerPool()
        let url1 = URL(fileURLWithPath: "/tmp/video1.mp4")
        let url2 = URL(fileURLWithPath: "/tmp/video2.mp4")

        let player1 = pool.acquire(for: url1)
        pool.release(player1)

        let player2 = pool.acquire(for: url2)
        #expect(player2 === player1)
    }

    @Test("pool keeps at most 2 players (maxPooled)")
    func poolMaxIsTwo() {
        let pool = AVPlayerPool()
        let urls = (0..<3).map { URL(fileURLWithPath: "/tmp/video\($0).mp4") }

        let player0 = pool.acquire(for: urls[0])
        let player1 = pool.acquire(for: urls[1])
        let player2 = pool.acquire(for: urls[2])

        pool.release(player0)
        pool.release(player1)
        pool.release(player2)

        let reused1 = pool.acquire(for: urls[0])
        let reused2 = pool.acquire(for: urls[1])
        let fresh = pool.acquire(for: urls[2])

        let reusedSet: Set<ObjectIdentifier> = [ObjectIdentifier(reused1), ObjectIdentifier(reused2)]
        let originalSet: Set<ObjectIdentifier> = [
            ObjectIdentifier(player0), ObjectIdentifier(player1), ObjectIdentifier(player2),
        ]
        #expect(reusedSet.isSubset(of: originalSet))
        #expect(!originalSet.contains(ObjectIdentifier(fresh)))
    }

    @Test("double-release is guarded: pool has only 1 slot filled")
    func doubleReleaseIsGuarded() {
        let pool = AVPlayerPool()
        let url = URL(fileURLWithPath: "/tmp/test-video.mp4")
        let player = pool.acquire(for: url)

        // Release twice — second release is a no-op (identity guard)
        pool.release(player)
        pool.release(player)

        // Pool has only 1 ref (guard prevented duplicate entry)
        // First acquire returns the pooled player, second is fresh
        let first = pool.acquire(for: url)
        let second = pool.acquire(for: url)

        #expect(first === player)
        #expect(second !== player)
    }

    @Test("acquire for different URLs creates distinct players when pool is empty")
    func acquireCreatesDistinctPlayers() {
        let pool = AVPlayerPool()
        let url1 = URL(fileURLWithPath: "/tmp/video1.mp4")
        let url2 = URL(fileURLWithPath: "/tmp/video2.mp4")

        let player1 = pool.acquire(for: url1)
        let player2 = pool.acquire(for: url2)

        #expect(player1 !== player2)
    }
}

// MARK: - ScanMode systemImageName Tests

@Suite("ScanMode SF Symbol names")
struct ScanModeImageNameTests {

    @Test(
        "Each scan mode has the correct SF Symbol name",
        arguments: [
            (ScanMode.video, "film"),
            (ScanMode.image, "photo"),
            (ScanMode.audio, "music.note"),
            (ScanMode.auto, "sparkles"),
        ] as [(ScanMode, String)]
    )
    func scanModeSymbolName(mode: ScanMode, expected: String) {
        #expect(mode.systemImageName == expected)
    }
}

// MARK: - String.fileName Extension Tests

@Suite("String.fileName extension")
struct StringFileNameTests {

    @Test("fileName extracts last path component from absolute path")
    func absolutePath() {
        #expect("/videos/a.mp4".fileName == "a.mp4")
    }

    @Test("fileName returns the string itself when no directory separator")
    func noDirectory() {
        #expect("video.mp4".fileName == "video.mp4")
    }

    @Test("fileName handles trailing slash")
    func trailingSlash() {
        #expect("/videos/".fileName == "videos")
    }

    @Test("fileName handles nested path")
    func nestedPath() {
        #expect("/a/b/c/d.txt".fileName == "d.txt")
    }
}

// MARK: - ScanContextHeader Accessibility Label Tests

@Suite("ScanContextHeader accessibility label")
struct ScanContextHeaderAccessibilityTests {

    @Test("Single directory video mode")
    func singleDirectoryVideo() {
        let entries = [DirectoryEntry(path: "/Users/me/Videos", isReference: false)]
        let text = ScanContextHeader.accessibilityText(
            mode: .video, entries: entries,
            contentEnabled: false, contentMethod: .phash, audioEnabled: false
        )
        #expect(text == "Video mode, scanning Videos")
    }

    @Test("Multiple directories with content hashing")
    func multipleDirectoriesWithContent() {
        let entries = [
            DirectoryEntry(path: "/a", isReference: false),
            DirectoryEntry(path: "/b", isReference: false),
            DirectoryEntry(path: "/c", isReference: false),
        ]
        let text = ScanContextHeader.accessibilityText(
            mode: .image, entries: entries,
            contentEnabled: true, contentMethod: .phash, audioEnabled: false
        )
        #expect(text.contains("Image mode"))
        #expect(text.contains("scanning 3 directories"))
        #expect(text.contains("content hashing"))
    }

    @Test("SSIM method shows SSIM comparison")
    func ssimMethod() {
        let entries = [DirectoryEntry(path: "/videos", isReference: false)]
        let text = ScanContextHeader.accessibilityText(
            mode: .video, entries: entries,
            contentEnabled: true, contentMethod: .ssim, audioEnabled: false
        )
        #expect(text.contains("SSIM comparison"))
        #expect(!text.contains("content hashing"))
    }

    @Test("Audio fingerprinting included")
    func audioFingerprinting() {
        let entries = [DirectoryEntry(path: "/videos", isReference: false)]
        let text = ScanContextHeader.accessibilityText(
            mode: .video, entries: entries,
            contentEnabled: false, contentMethod: .phash, audioEnabled: true
        )
        #expect(text.contains("audio fingerprinting"))
    }

    @Test("Reference directories excluded from count")
    func referenceExcluded() {
        let entries = [
            DirectoryEntry(path: "/scan1", isReference: false),
            DirectoryEntry(path: "/scan2", isReference: false),
            DirectoryEntry(path: "/ref", isReference: true),
        ]
        let text = ScanContextHeader.accessibilityText(
            mode: .video, entries: entries,
            contentEnabled: false, contentMethod: .phash, audioEnabled: false
        )
        #expect(text.contains("scanning 2 directories"))
    }

    @Test("All features enabled produces complete label")
    func allFeaturesEnabled() {
        let entries = [
            DirectoryEntry(path: "/a", isReference: false),
            DirectoryEntry(path: "/b", isReference: false),
        ]
        let text = ScanContextHeader.accessibilityText(
            mode: .auto, entries: entries,
            contentEnabled: true, contentMethod: .phash, audioEnabled: true
        )
        #expect(text.contains("Auto mode"))
        #expect(text.contains("content hashing"))
        #expect(text.contains("audio fingerprinting"))
    }
}

// MARK: - Inspector Metadata Row Accessibility Tests

@Suite("Inspector metadata row accessibility text")
struct InspectorMetadataAccessibilityTests {
    @Test("metadata row combines label and value")
    func metadataRowText() {
        let text = PairInspectorPane.metadataRowAccessibilityText(label: "Size", value: "1.5 MB")
        #expect(text == "Size: 1.5 MB")
    }

    @Test("metadata row with em dash value")
    func metadataRowEmDash() {
        let text = PairInspectorPane.metadataRowAccessibilityText(label: "Codec", value: "\u{2014}")
        #expect(text == "Codec: \u{2014}")
    }
}

// MARK: - WCAG Contrast Ratio Verification Tests

@Suite("WCAG contrast ratio verification")
struct ContrastRatioTests {
    /// Compute WCAG 2.1 relative luminance from linear RGB.
    private func relativeLuminance(r: Double, g: Double, b: Double) -> Double {
        func linearize(_ c: Double) -> Double {
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
    }

    private func contrastRatio(_ l1: Double, _ l2: Double) -> Double {
        let lighter = max(l1, l2)
        let darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)
    }

    // surface0 = #1C1C1E ~ RGB(0.11, 0.11, 0.118)
    private var surface0Luminance: Double {
        relativeLuminance(r: 0.11, g: 0.11, b: 0.118)
    }

    @Test("textPrimary (85% white) meets 4.5:1 against surface0")
    func textPrimaryContrast() {
        let textLum = relativeLuminance(r: 0.85, g: 0.85, b: 0.85)
        let ratio = contrastRatio(textLum, surface0Luminance)
        #expect(ratio >= 4.5, "textPrimary contrast ratio \(ratio) must be >= 4.5:1")
    }

    @Test("textSecondary (55% white) meets 4.5:1 against surface0")
    func textSecondaryContrast() {
        let textLum = relativeLuminance(r: 0.55, g: 0.55, b: 0.55)
        let ratio = contrastRatio(textLum, surface0Luminance)
        #expect(ratio >= 4.5, "textSecondary contrast ratio \(ratio) must be >= 4.5:1")
    }

    @Test("textMuted (35% white) fails 4.5:1 in standard mode")
    func textMutedStandardContrast() {
        let textLum = relativeLuminance(r: 0.35, g: 0.35, b: 0.35)
        let ratio = contrastRatio(textLum, surface0Luminance)
        #expect(ratio < 4.5, "textMuted in standard mode should fail 4.5:1")
    }

    @Test("textMuted high-contrast (70% white) meets 4.5:1 against surface0")
    func textMutedHighContrastContrast() {
        let textLum = relativeLuminance(r: 0.70, g: 0.70, b: 0.70)
        let ratio = contrastRatio(textLum, surface0Luminance)
        #expect(ratio >= 4.5, "textMuted high-contrast ratio \(ratio) must be >= 4.5:1")
    }
}

// MARK: - DDAdaptiveColors High-Contrast Variants Tests

@Suite("DDAdaptiveColors high-contrast variants")
struct DDAdaptiveColorsTests {
    @Test("standard contrast returns DDColors originals")
    func standardContrastReturnsOriginals() {
        let colors = DDAdaptiveColors(contrast: .standard)
        #expect(colors.textPrimary == DDColors.textPrimary)
        #expect(colors.textSecondary == DDColors.textSecondary)
        #expect(colors.textMuted == DDColors.textMuted)
        #expect(colors.scoreLow == DDColors.scoreLow)
        #expect(colors.scoreMedium == DDColors.scoreMedium)
    }

    @Test("standard contrast separator differs from high contrast")
    func standardSeparator() {
        let colors = DDAdaptiveColors(contrast: .standard)
        #expect(colors.separator != DDAdaptiveColors(contrast: .increased).separator)
    }

    @Test("high contrast returns different values for all adaptive colors")
    func highContrastReturnsDifferentValues() {
        let standard = DDAdaptiveColors(contrast: .standard)
        let increased = DDAdaptiveColors(contrast: .increased)
        #expect(increased.textPrimary != standard.textPrimary)
        #expect(increased.textSecondary != standard.textSecondary)
        #expect(increased.textMuted != standard.textMuted)
        #expect(increased.separator != standard.separator)
    }

    @Test("high contrast textPrimary is fully opaque white")
    func highContrastTextPrimaryIsWhite() {
        let colors = DDAdaptiveColors(contrast: .increased)
        #expect(colors.textPrimary == Color.white)
    }
}

// MARK: - PrimaryProgressDisplay Accessibility Label Tests

@Suite("PrimaryProgressDisplay accessibility label")
struct PrimaryProgressDisplayAccessibilityTests {

    @Test("Basic progress percentage only")
    func basicProgressOnly() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 0.42, elapsed: 0, throughput: nil
        )
        #expect(text == "42 percent complete")
    }

    @Test("All metrics present")
    func allMetrics() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 0.75, elapsed: 90, throughput: 5.2
        )
        #expect(text.contains("75 percent complete"))
        #expect(text.contains("elapsed"))
        #expect(text.contains("5.2 items per second"))
    }

    @Test("Zero throughput excluded")
    func zeroThroughputExcluded() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 0.5, elapsed: 10, throughput: 0
        )
        #expect(!text.contains("items per second"))
    }

    @Test("Nil throughput excluded")
    func nilThroughputExcluded() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 0.5, elapsed: 10, throughput: nil
        )
        #expect(!text.contains("items per second"))
    }

    @Test("Zero elapsed excluded")
    func zeroElapsedExcluded() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 0.5, elapsed: 0, throughput: nil
        )
        #expect(!text.contains("elapsed"))
    }

    @Test("100 percent complete")
    func fullProgress() {
        let text = PrimaryProgressDisplay.accessibilityText(
            progress: 1.0, elapsed: 120, throughput: nil
        )
        #expect(text.contains("100 percent complete"))
    }
}
