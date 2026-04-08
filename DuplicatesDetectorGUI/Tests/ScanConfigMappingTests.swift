import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - ScanConfig.hasFilters

@Suite("ScanConfig.hasFilters")
struct ScanConfigHasFiltersTests {

    @Test("returns false when all filter fields are nil or empty")
    func allFiltersNilOrEmpty() {
        let config = ScanConfig()
        #expect(config.hasFilters == false)
    }

    @Test("returns true when minSize is set")
    func minSizeSet() {
        var config = ScanConfig()
        config.minSize = "10MB"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when maxSize is set")
    func maxSizeSet() {
        var config = ScanConfig()
        config.maxSize = "1GB"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when minResolution is set")
    func minResolutionSet() {
        var config = ScanConfig()
        config.minResolution = "1920x1080"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when maxResolution is set")
    func maxResolutionSet() {
        var config = ScanConfig()
        config.maxResolution = "3840x2160"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when minBitrate is set")
    func minBitrateSet() {
        var config = ScanConfig()
        config.minBitrate = "1M"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when maxBitrate is set")
    func maxBitrateSet() {
        var config = ScanConfig()
        config.maxBitrate = "10M"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when codec is set")
    func codecSet() {
        var config = ScanConfig()
        config.codec = "h264"
        #expect(config.hasFilters == true)
    }

    @Test("returns true when minDuration is set")
    func minDurationSet() {
        var config = ScanConfig()
        config.minDuration = 30.0
        #expect(config.hasFilters == true)
    }

    @Test("returns true when maxDuration is set")
    func maxDurationSet() {
        var config = ScanConfig()
        config.maxDuration = 3600.0
        #expect(config.hasFilters == true)
    }

    @Test("returns false when string filter is empty")
    func emptyStringFilterIsFalse() {
        var config = ScanConfig()
        config.minSize = ""
        config.maxSize = ""
        config.codec = ""
        #expect(config.hasFilters == false)
    }

    @Test("returns true when multiple filters are set simultaneously")
    func multipleFiltersSet() {
        var config = ScanConfig()
        config.minSize = "1MB"
        config.maxDuration = 600.0
        config.codec = "hevc"
        #expect(config.hasFilters == true)
    }

    @Test("exclude patterns do not count as filters")
    func excludePatternsNotFilters() {
        var config = ScanConfig()
        config.exclude = ["*.tmp", "*.bak"]
        #expect(config.hasFilters == false)
    }
}

// MARK: - ScanConfig.fromEnvelopeArgs

@Suite("ScanConfig.fromEnvelopeArgs")
struct ScanConfigFromEnvelopeArgsTests {

    /// Build a minimal ScanArgs for testing.
    private func makeArgs(
        directories: [String] = ["/videos"],
        threshold: Int = 50,
        content: Bool = false,
        contentMethod: String? = nil,
        weights: ComparatorWeights? = nil,
        keep: String? = nil,
        action: String = "trash",
        group: Bool = false,
        sort: String = "score",
        limit: Int? = nil,
        minScore: Int? = nil,
        exclude: [String]? = nil,
        reference: [String]? = nil,
        mode: String = "video",
        embedThumbnails: Bool = false
    ) -> ScanArgs {
        ScanArgs(
            directories: directories,
            threshold: threshold,
            content: content,
            contentMethod: contentMethod,
            weights: weights,
            keep: keep,
            action: action,
            group: group,
            sort: sort,
            limit: limit,
            minScore: minScore,
            exclude: exclude,
            reference: reference,
            mode: mode,
            embedThumbnails: embedThumbnails
        )
    }

    @Test("Maps directories and mode from envelope args")
    func mapsDirectoriesAndMode() {
        let args = makeArgs(directories: ["/photos", "/music"], mode: "image")
        let config = ScanConfig.fromEnvelopeArgs(args)

        #expect(config.directories == ["/photos", "/music"])
        #expect(config.mode == .image)
    }

    @Test("Maps threshold from envelope args")
    func mapsThreshold() {
        let args = makeArgs(threshold: 75)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.threshold == 75)
    }

    @Test("Maps content and content method from envelope args")
    func mapsContentFields() {
        let args = makeArgs(content: true, contentMethod: "ssim")
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.content == true)
        #expect(config.contentMethod == .ssim)
    }

    @Test("Maps keep strategy from envelope args")
    func mapsKeepStrategy() {
        let args = makeArgs(keep: "newest")
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.keep == .newest)
    }

    @Test("Maps action with default fallback to trash")
    func mapsActionWithDefault() {
        let args = makeArgs(action: "delete")
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.action == .delete)
    }

    @Test("Maps unknown action to default .trash")
    func unknownActionFallsBackToTrash() {
        let args = makeArgs(action: "unknown_action")
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.action == .trash)
    }

    @Test("Maps group, sort, limit, and minScore from envelope args")
    func mapsOutputFields() {
        let args = makeArgs(group: true, sort: "size", limit: 100, minScore: 60)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.group == true)
        #expect(config.sort == .size)
        #expect(config.limit == 100)
        #expect(config.minScore == 60)
    }

    @Test("Maps exclude and reference arrays from envelope args")
    func mapsExcludeAndReference() {
        let args = makeArgs(exclude: ["*.tmp"], reference: ["/ref"])
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.exclude == ["*.tmp"])
        #expect(config.reference == ["/ref"])
    }

    @Test("Maps embedThumbnails from envelope args")
    func mapsEmbedThumbnails() {
        let args = makeArgs(embedThumbnails: true)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.embedThumbnails == true)
    }

    @Test("Maps weights values from envelope args")
    func mapsWeights() {
        let weights = ComparatorWeights(values: ["filename": 50.0, "duration": 30.0])
        let args = makeArgs(weights: weights)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.weights == ["filename": 50.0, "duration": 30.0])
    }

    @Test("Nil weights in envelope args produces nil weights in config")
    func nilWeightsProducesNilConfig() {
        let args = makeArgs(weights: nil)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.weights == nil)
    }

    @Test("Nil keep in envelope args produces nil keep in config")
    func nilKeepProducesNilConfig() {
        let args = makeArgs(keep: nil)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.keep == nil)
    }

    @Test("Nil exclude and reference default to empty arrays")
    func nilExcludeReferenceDefaultToEmpty() {
        let args = makeArgs(exclude: nil, reference: nil)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.exclude == [])
        #expect(config.reference == [])
    }

    @Test("Nil contentMethod produces nil contentMethod in config")
    func nilContentMethodProducesNil() {
        let args = makeArgs(content: true, contentMethod: nil)
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.content == true)
        #expect(config.contentMethod == nil)
    }

    @Test("Presentation-only fields are not restored from envelope args")
    func presentationFieldsNotRestored() {
        // verbose, log, etc. are not in ScanArgs — verify they remain at defaults
        let args = makeArgs()
        let config = ScanConfig.fromEnvelopeArgs(args)
        #expect(config.verbose == false)
        #expect(config.log == nil)
        #expect(config.cacheDir == nil)
    }
}

// MARK: - ScanConfig scanSource Codable

@Suite("ScanConfig scanSource persistence")
struct ScanConfigScanSourcePersistenceTests {

    @Test("ScanConfig with photosLibrary scanSource round-trips through JSON")
    func photosLibraryScanSourceRoundTrips() throws {
        var config = ScanConfig()
        config.scanSource = .photosLibrary(scope: .fullLibrary)
        config.mode = .auto
        config.directories = []

        let encoder = JSONEncoder()
        let data = try encoder.encode(config)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(ScanConfig.self, from: data)

        #expect(decoded.scanSource == .photosLibrary(scope: .fullLibrary))
        #expect(decoded.mode == .auto)
        #expect(decoded.directories.isEmpty)
    }

    @Test("ScanConfig with directory scanSource round-trips through JSON")
    func directoryScanSourceRoundTrips() throws {
        var config = ScanConfig()
        config.scanSource = .directory
        config.directories = ["/videos"]

        let encoder = JSONEncoder()
        let data = try encoder.encode(config)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(ScanConfig.self, from: data)

        #expect(decoded.scanSource == .directory)
        #expect(decoded.directories == ["/videos"])
    }

    @Test("ScanSource.directory is the default for ScanConfig")
    func directoryIsDefault() {
        let config = ScanConfig()
        #expect(config.scanSource == .directory)
    }

    @Test("ScanConfig preserves all fields alongside photosLibrary scanSource")
    func preservesFieldsAlongsidePhotosSource() throws {
        var config = ScanConfig()
        config.scanSource = .photosLibrary(scope: .fullLibrary)
        config.mode = .auto
        config.threshold = 75
        config.group = true
        config.sort = .size

        let data = try JSONEncoder().encode(config)
        let decoded = try JSONDecoder().decode(ScanConfig.self, from: data)

        #expect(decoded.scanSource == .photosLibrary(scope: .fullLibrary))
        #expect(decoded.threshold == 75)
        #expect(decoded.group == true)
        #expect(decoded.sort == .size)
    }
}
