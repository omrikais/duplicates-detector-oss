import Testing

@testable import DuplicatesDetector

@Suite("DesignTokens")
struct DesignTokensTests {

    // MARK: - DDSpacing

    @Test("Spacing values are strictly ascending: xxs < xs < sm < md < lg < xl")
    func spacingAscending() {
        #expect(DDSpacing.xxs < DDSpacing.xs)
        #expect(DDSpacing.xs < DDSpacing.sm)
        #expect(DDSpacing.sm < DDSpacing.md)
        #expect(DDSpacing.md < DDSpacing.lg)
        #expect(DDSpacing.lg < DDSpacing.xl)
    }

    @Test("Spacing values are all positive")
    func spacingPositive() {
        #expect(DDSpacing.xxs > 0)
        #expect(DDSpacing.xs > 0)
        #expect(DDSpacing.sm > 0)
        #expect(DDSpacing.md > 0)
        #expect(DDSpacing.lg > 0)
        #expect(DDSpacing.xl > 0)
    }

    @Test("New spacing tokens have correct exact values: xxs=2, sliderThumb=16, iconFrame=20")
    func spacingNewTokenValues() {
        #expect(DDSpacing.xxs == 2)
        #expect(DDSpacing.sliderThumb == 16)
        #expect(DDSpacing.iconFrame == 20)
    }

    // MARK: - DDRadius

    @Test("Radius values are strictly ascending: small < medium < large < panel")
    func radiusAscending() {
        #expect(DDRadius.small < DDRadius.medium)
        #expect(DDRadius.medium < DDRadius.large)
        #expect(DDRadius.large < DDRadius.panel)
    }

    @Test("Radius values are all positive")
    func radiusPositive() {
        #expect(DDRadius.small > 0)
        #expect(DDRadius.medium > 0)
        #expect(DDRadius.large > 0)
        #expect(DDRadius.panel > 0)
    }

    // MARK: - DDMotion durations

    @Test("Motion durations are all positive")
    func motionDurationsPositive() {
        #expect(DDMotion.durationFast > 0)
        #expect(DDMotion.durationMedium > 0)
        #expect(DDMotion.durationSlow > 0)
    }

    @Test("Motion durations are strictly ascending: fast < medium < slow")
    func motionDurationsAscending() {
        #expect(DDMotion.durationFast < DDMotion.durationMedium)
        #expect(DDMotion.durationMedium < DDMotion.durationSlow)
    }

    // MARK: - DDDensity

    @Test("Compact top inset is smaller than or equal to regular top inset")
    func densityCompactTopSmallerOrEqual() {
        #expect(DDDensity.compact.top <= DDDensity.regular.top)
    }

    @Test("Compact leading inset is smaller than or equal to regular leading inset")
    func densityCompactLeadingSmallerOrEqual() {
        #expect(DDDensity.compact.leading <= DDDensity.regular.leading)
    }

    @Test("Compact bottom inset is smaller than or equal to regular bottom inset")
    func densityCompactBottomSmallerOrEqual() {
        #expect(DDDensity.compact.bottom <= DDDensity.regular.bottom)
    }

    @Test("Compact trailing inset is smaller than or equal to regular trailing inset")
    func densityCompactTrailingSmallerOrEqual() {
        #expect(DDDensity.compact.trailing <= DDDensity.regular.trailing)
    }

    // MARK: - DDPillSize

    @Test("DDPillSize.small has correct horizontal and vertical values")
    func pillSizeSmall() {
        #expect(DDPillSize.small.horizontal == DDSpacing.sm)
        #expect(DDPillSize.small.vertical == DDSpacing.xxs)
    }

    @Test("DDPillSize.medium has correct horizontal and vertical values")
    func pillSizeMedium() {
        #expect(DDPillSize.medium.horizontal == DDSpacing.sm)
        #expect(DDPillSize.medium.vertical == DDSpacing.xs)
    }

    @Test("DDPillSize.large has correct horizontal and vertical values")
    func pillSizeLarge() {
        #expect(DDPillSize.large.horizontal == DDSpacing.md)
        #expect(DDPillSize.large.vertical == DDSpacing.sm)
    }

    @Test("DDPillSize tiers are strictly ascending by vertical padding")
    func pillSizeVerticalAscending() {
        #expect(DDPillSize.small.vertical < DDPillSize.medium.vertical)
        #expect(DDPillSize.medium.vertical < DDPillSize.large.vertical)
    }

    // MARK: - DDColors.scoreColor(for:)

    @Test(
        "scoreColor returns scoreCritical for scores >= 90",
        arguments: [100.0, 95.0, 90.0, 90.1, 99.9]
    )
    func scoreColorCritical(score: Double) {
        #expect(DDColors.scoreColor(for: score) == DDColors.scoreCritical)
    }

    @Test(
        "scoreColor returns scoreHigh for scores in [70, 90)",
        arguments: [89.0, 89.9, 85.0, 70.0, 70.1, 75.5]
    )
    func scoreColorHigh(score: Double) {
        #expect(DDColors.scoreColor(for: score) == DDColors.scoreHigh)
    }

    @Test(
        "scoreColor returns scoreMedium for scores in [50, 70)",
        arguments: [69.0, 69.9, 60.0, 50.0, 50.1, 55.0]
    )
    func scoreColorMedium(score: Double) {
        #expect(DDColors.scoreColor(for: score) == DDColors.scoreMedium)
    }

    @Test(
        "scoreColor returns scoreLow for scores below 50",
        arguments: [49.0, 49.9, 25.0, 0.0, 1.0, -5.0]
    )
    func scoreColorLow(score: Double) {
        #expect(DDColors.scoreColor(for: score) == DDColors.scoreLow)
    }

    @Test("scoreColor at exact boundary 90 returns scoreCritical")
    func scoreColorBoundary90() {
        #expect(DDColors.scoreColor(for: 90) == DDColors.scoreCritical)
    }

    @Test("scoreColor at 89 (just below 90) returns scoreHigh")
    func scoreColorBoundary89() {
        #expect(DDColors.scoreColor(for: 89) == DDColors.scoreHigh)
    }

    @Test("scoreColor at exact boundary 70 returns scoreHigh")
    func scoreColorBoundary70() {
        #expect(DDColors.scoreColor(for: 70) == DDColors.scoreHigh)
    }

    @Test("scoreColor at 69 (just below 70) returns scoreMedium")
    func scoreColorBoundary69() {
        #expect(DDColors.scoreColor(for: 69) == DDColors.scoreMedium)
    }

    @Test("scoreColor at exact boundary 50 returns scoreMedium")
    func scoreColorBoundary50() {
        #expect(DDColors.scoreColor(for: 50) == DDColors.scoreMedium)
    }

    @Test("scoreColor at 49 (just below 50) returns scoreLow")
    func scoreColorBoundary49() {
        #expect(DDColors.scoreColor(for: 49) == DDColors.scoreLow)
    }

    @Test("scoreColor at 0 returns scoreLow")
    func scoreColorZero() {
        #expect(DDColors.scoreColor(for: 0) == DDColors.scoreLow)
    }

    @Test("scoreColor at 100 returns scoreCritical")
    func scoreColorMax() {
        #expect(DDColors.scoreColor(for: 100) == DDColors.scoreCritical)
    }

    // MARK: - DDColors.comparatorColors

    @Test("comparatorColors has entries for all comparator keys including CLI aliases")
    func comparatorColorsHasAllKeys() {
        let expectedKeys: Set<String> = [
            "filename", "duration", "resolution", "fileSize", "filesize",
            "exif", "content", "audio", "tags",
            "page_count", "pageCount", "doc_meta", "docMeta",
        ]
        let actualKeys = Set(DDColors.comparatorColors.keys)
        #expect(actualKeys == expectedKeys)
    }

    @Test("comparatorColors has exactly 13 entries (10 unique comparators + 3 aliases)")
    func comparatorColorsCount() {
        #expect(DDColors.comparatorColors.count == 13)
    }

    @Test("comparatorColors 'filesize' alias is non-nil and matches 'fileSize' color")
    func comparatorColorsFilesizeAlias() {
        let aliasColor = DDColors.comparatorColors["filesize"]
        let canonicalColor = DDColors.comparatorColors["fileSize"]
        #expect(aliasColor != nil)
        #expect(canonicalColor != nil)
        #expect(aliasColor == canonicalColor)
    }

    // MARK: - DDComparators.displayName(for:)

    @Test(
        "displayName returns correct names for known keys",
        arguments: [
            ("filename", "Filename"),
            ("duration", "Duration"),
            ("resolution", "Resolution"),
            ("fileSize", "File Size"),
            ("filesize", "File Size"),
            ("exif", "EXIF"),
            ("content", "Content"),
            ("audio", "Audio"),
            ("tags", "Tags"),
        ] as [(String, String)]
    )
    func displayNameKnown(key: String, expected: String) {
        #expect(DDComparators.displayName(for: key) == expected)
    }

    @Test("displayName for 'filesize' alias returns 'File Size' matching camelCase key")
    func displayNameFilesizeAlias() {
        #expect(DDComparators.displayName(for: "filesize") == DDComparators.displayName(for: "fileSize"))
    }

    @Test("displayName returns capitalized key for unknown key")
    func displayNameUnknown() {
        #expect(DDComparators.displayName(for: "unknownKey") == "Unknownkey")
    }

    @Test("displayName returns capitalized key for single-word unknown key")
    func displayNameUnknownSingleWord() {
        #expect(DDComparators.displayName(for: "custom") == "Custom")
    }

    @Test("displayName handles empty string")
    func displayNameEmpty() {
        // .capitalized on empty string returns empty string
        #expect(DDComparators.displayName(for: "") == "")
    }

    // MARK: - Document comparator keys

    @Test("DDComparators displays Page Count for page_count keys")
    func pageCountDisplayName() {
        #expect(DDComparators.displayName(for: "page_count") == "Page Count")
        #expect(DDComparators.displayName(for: "pageCount") == "Page Count")
    }

    @Test("DDComparators displays Doc Meta for doc_meta keys")
    func docMetaDisplayName() {
        #expect(DDComparators.displayName(for: "doc_meta") == "Doc Meta")
        #expect(DDComparators.displayName(for: "docMeta") == "Doc Meta")
    }

    @Test("Comparator colors include document keys")
    func documentComparatorColors() {
        #expect(DDColors.comparatorColor(for: "page_count") == .brown)
        #expect(DDColors.comparatorColor(for: "doc_meta") == .cyan)
    }
}
