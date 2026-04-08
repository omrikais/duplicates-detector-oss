import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("SetupReducer")
struct SetupReducerTests {

    // MARK: - Helpers

    /// Convenience: reduce a single action and return the resulting state + effects.
    private func reduce(
        _ state: SetupState,
        _ action: SetupAction
    ) -> (SetupState, [SetupEffect]) {
        SetupReducer.reduce(state: state, action: action)
    }

    /// A basic state with video mode and default weights, ready to use.
    private func makeDefaultState() -> SetupState {
        SetupState.fromDefaults()
    }

    /// Helper: creates a DependencyStatus with specified capabilities.
    private func makeDeps(
        cli: Bool = true,
        ffprobe: Bool = true,
        ffmpeg: Bool = true,
        fpcalc: Bool = true,
        mutagen: Bool = true,
        skimage: Bool = true,
        pdfminer: Bool = true
    ) -> DependencyStatus {
        DependencyStatus(
            cli: ToolStatus(name: "duplicates-detector", isAvailable: cli, isRequired: true),
            ffmpeg: ToolStatus(name: "ffmpeg", isAvailable: ffmpeg, isRequired: false),
            ffprobe: ToolStatus(name: "ffprobe", isAvailable: ffprobe, isRequired: false),
            fpcalc: ToolStatus(name: "fpcalc", isAvailable: fpcalc, isRequired: false),
            hasMutagen: mutagen,
            hasSkimage: skimage,
            hasPdfminer: pdfminer
        )
    }

    // MARK: - Initial state / factory

    @Test("fromDefaults produces video mode with valid weights summing to 100")
    func fromDefaultsProducesValidState() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = SetupState.fromDefaults()
        #expect(state.mode == .video)
        #expect(state.threshold == 50)
        #expect(state.content == false)
        #expect(state.audio == false)
        #expect(state.isWeightSumValid)
        #expect(state.weightStrings["filename"] == "50")
        #expect(state.weightStrings["duration"] == "30")
        #expect(state.weightStrings["resolution"] == "10")
        #expect(state.weightStrings["filesize"] == "10")
        #expect(state.weightStrings.count == 4)
    }

    // MARK: - setMode

    @Test("setMode to image resets weights to image defaults and clears locked weights")
    func setModeImage() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.lockedWeights = ["filename"]

        let (newState, effects) = reduce(state, .setMode(.image))

        #expect(newState.mode == .image)
        #expect(newState.weightStrings["filename"] == "25")
        #expect(newState.weightStrings["resolution"] == "20")
        #expect(newState.weightStrings["filesize"] == "15")
        #expect(newState.weightStrings["exif"] == "40")
        #expect(newState.weightStrings.count == 4)
        #expect(newState.lockedWeights.isEmpty)
        #expect(newState.activePreset == nil)
        #expect(effects.contains(.detectPreset))
        #expect(effects.contains(.updateFileCount))
    }

    @Test("setMode to audio disables content if it was on")
    func setModeAudioDisablesContent() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.content = true

        let (newState, _) = reduce(state, .setMode(.audio))

        #expect(newState.mode == .audio)
        #expect(newState.content == false)
        #expect(newState.weightStrings["filename"] == "30")
        #expect(newState.weightStrings["duration"] == "30")
        #expect(newState.weightStrings["tags"] == "40")
        #expect(newState.weightStrings.count == 3)
    }

    @Test("setMode to image disables audio if it was on")
    func setModeImageDisablesAudio() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.audio = true

        let (newState, _) = reduce(state, .setMode(.image))

        #expect(newState.mode == .image)
        #expect(newState.audio == false)
    }

    @Test("setMode to same mode is a no-op")
    func setModeSameModeNoOp() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        let (newState, effects) = reduce(state, .setMode(.video))

        #expect(newState == state)
        #expect(effects.isEmpty)
    }

    @Test("setMode to auto clears longest keep strategy")
    func setModeAutoClearsLongest() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.keep = .longest

        let (newState, _) = reduce(state, .setMode(.auto))

        #expect(newState.keep == nil)
    }

    @Test("setMode to audio clears highestRes keep strategy")
    func setModeAudioClearsHighestRes() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.keep = .highestRes

        let (newState, _) = reduce(state, .setMode(.audio))

        #expect(newState.keep == nil)
    }

    // MARK: - setContent / setAudio

    @Test("setContent true disables audio")
    func setContentDisablesAudio() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.audio = true

        let (newState, effects) = reduce(state, .setContent(true))

        #expect(newState.content == true)
        #expect(newState.audio == false)
        #expect(effects.contains(.detectPreset))
    }

    @Test("setAudio true disables content")
    func setAudioDisablesContent() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.content = true

        let (newState, effects) = reduce(state, .setAudio(true))

        #expect(newState.audio == true)
        #expect(newState.content == false)
        #expect(effects.contains(.detectPreset))
    }

    @Test("setContent true resets weights to videoContent defaults")
    func setContentResetsWeights() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        let (newState, _) = reduce(state, .setContent(true))

        #expect(newState.weightStrings["content"] == "40")
        #expect(newState.weightStrings["filename"] == "20")
        #expect(newState.weightStrings["duration"] == "20")
        #expect(newState.weightStrings.count == 5)
    }

    @Test("setContent to same value is a no-op")
    func setContentSameNoOp() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()
        // content is already false
        let (newState, effects) = reduce(state, .setContent(false))

        #expect(newState == state)
        #expect(effects.isEmpty)
    }

    @Test("setAudio true resets weights to videoAudio defaults")
    func setAudioResetsWeights() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        let (newState, _) = reduce(state, .setAudio(true))

        #expect(newState.weightStrings["audio"] == "30")
        #expect(newState.weightStrings["filename"] == "25")
        #expect(newState.weightStrings.count == 5)
    }

    // MARK: - addDirectory

    @Test("addDirectory adds entry and emits updateFileCount")
    func addDirectory() {
        let state = SetupState()
        let url = URL(fileURLWithPath: "/videos")

        let (newState, effects) = reduce(state, .addDirectory(url))

        #expect(newState.entries.count == 1)
        #expect(newState.entries[0].path == "/videos")
        #expect(newState.entries[0].isReference == false)
        #expect(effects == [.updateFileCount])
    }

    @Test("addDirectory duplicate URL is ignored")
    func addDirectoryDuplicate() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        let url = URL(fileURLWithPath: "/videos")

        let (newState, effects) = reduce(state, .addDirectory(url))

        #expect(newState.entries.count == 1)
        #expect(effects.isEmpty)
    }

    @Test("addDirectory allows different paths")
    func addDirectoryDifferent() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        let url = URL(fileURLWithPath: "/photos")

        let (newState, effects) = reduce(state, .addDirectory(url))

        #expect(newState.entries.count == 2)
        #expect(effects == [.updateFileCount])
    }

    // MARK: - removeDirectory

    @Test("removeDirectory removes entry and emits updateFileCount")
    func removeDirectory() {
        var state = SetupState()
        state.entries = [
            DirectoryEntry(path: "/videos"),
            DirectoryEntry(path: "/photos"),
        ]
        let url = URL(fileURLWithPath: "/videos")

        let (newState, effects) = reduce(state, .removeDirectory(url))

        #expect(newState.entries.count == 1)
        #expect(newState.entries[0].path == "/photos")
        #expect(effects == [.updateFileCount])
    }

    // MARK: - toggleReference

    @Test("toggleReference toggles isReference flag")
    func toggleReference() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        let url = URL(fileURLWithPath: "/videos")

        let (state2, _) = reduce(state, .toggleReference(url))
        #expect(state2.entries[0].isReference == true)

        let (state3, _) = reduce(state2, .toggleReference(url))
        #expect(state3.entries[0].isReference == false)
    }

    // MARK: - applyPreset

    @Test("applyPreset quick sets expected video values")
    func applyPresetQuick() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.mode = .video

        let (newState, _) = reduce(state, .applyPreset(.quick))

        #expect(newState.content == false)
        #expect(newState.audio == false)
        #expect(newState.threshold == 50)
        #expect(newState.embedThumbnails == false)
        #expect(newState.group == false)
        #expect(newState.rotationInvariant == false)
        #expect(newState.weightStrings == ["filename": "50", "duration": "30", "resolution": "10", "filesize": "10"])
        #expect(newState.activePreset == .quick)
        #expect(newState.lockedWeights.isEmpty)
    }

    @Test("applyPreset thorough sets expected video values")
    func applyPresetThorough() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.mode = .video

        let (newState, _) = reduce(state, .applyPreset(.thorough))

        #expect(newState.content == true)
        #expect(newState.audio == true)
        #expect(newState.threshold == 30)
        #expect(newState.group == true)
        #expect(newState.weightStrings["content"] == "40")
        #expect(newState.weightStrings["audio"] == "10")
        #expect(newState.activePreset == .thorough)
    }

    @Test("applyPreset for auto mode is a no-op")
    func applyPresetAutoNoOp() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.mode = .auto

        let (newState, effects) = reduce(state, .applyPreset(.quick))

        #expect(newState.mode == .auto)
        #expect(effects.isEmpty)
    }

    @Test("applyPreset image standard sets correct values")
    func applyPresetImageStandard() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        let (stateImage, _) = reduce(state, .setMode(.image))
        state = stateImage

        let (newState, _) = reduce(state, .applyPreset(.standard))

        #expect(newState.content == true)
        #expect(newState.audio == false)
        #expect(newState.threshold == 50)
        #expect(newState.weightStrings["exif"] == "25")
        #expect(newState.weightStrings["content"] == "40")
        #expect(newState.embedThumbnails == true)
    }

    // MARK: - normalizeIncompatibilities

    @Test("normalizeIncompatibilities clears content in audio mode")
    func normalizeClears() {
        var state = SetupState()
        state.mode = .audio
        state.content = true
        state.minResolution = "1920x1080"

        SetupState.normalizeIncompatibilities(&state)

        #expect(state.content == false)
        #expect(state.minResolution == "")
        #expect(state.maxResolution == "")
    }

    @Test("normalizeIncompatibilities clears audio in image mode")
    func normalizeImageClearsAudio() {
        var state = SetupState()
        state.mode = .image
        state.audio = true
        state.minDuration = "10"
        state.minBitrate = "1Mbps"

        SetupState.normalizeIncompatibilities(&state)

        #expect(state.audio == false)
        #expect(state.minDuration == "")
        #expect(state.maxDuration == "")
        #expect(state.minBitrate == "")
        #expect(state.maxBitrate == "")
    }

    @Test("normalizeIncompatibilities clears longest keep for image/auto")
    func normalizeClearsLongestKeep() {
        var state = SetupState()
        state.mode = .image
        state.keep = .longest
        SetupState.normalizeIncompatibilities(&state)
        #expect(state.keep == nil)

        state.mode = .auto
        state.keep = .longest
        SetupState.normalizeIncompatibilities(&state)
        #expect(state.keep == nil)
    }

    // MARK: - buildConfig

    @Test("buildConfig produces correct SessionConfig")
    func buildConfigBasic() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [
            DirectoryEntry(path: "/videos"),
            DirectoryEntry(path: "/ref", isReference: true),
        ]
        state.threshold = 60
        state.minSize = "10MB"
        state.codec = "h264"

        let config = state.buildConfig()

        #expect(config.mode == .video)
        #expect(config.threshold == 60)
        #expect(config.directories == ["/videos"])
        #expect(config.reference == ["/ref"])
        #expect(config.minSize == "10MB")
        #expect(config.codec == "h264")
    }

    @Test("buildConfig does not emit weights when they match defaults")
    func buildConfigDefaultWeights() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]

        let config = state.buildConfig()

        #expect(config.weights == nil)
    }

    @Test("buildConfig emits weights when modified from defaults")
    func buildConfigCustomWeights() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.weightStrings["filename"] = "40"
        state.weightStrings["duration"] = "40"

        let config = state.buildConfig()

        #expect(config.weights != nil)
        #expect(config.weights?["filename"] == 40)
        #expect(config.weights?["duration"] == 40)
    }

    @Test("buildConfig omits extensions in auto mode")
    func buildConfigAutoOmitsExtensions() {
        var state = SetupState()
        state.mode = .auto
        state.extensions = "mp4,mkv"
        state.entries = [DirectoryEntry(path: "/media")]

        let config = state.buildConfig()

        #expect(config.extensions == nil)
    }

    @Test("buildConfig treats empty strings as nil")
    func buildConfigEmptyStringsNil() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.minSize = ""
        state.codec = "  "
        SetupState.resetWeightsToDefaults(&state)

        let config = state.buildConfig()

        #expect(config.minSize == nil)
        #expect(config.codec == nil)
    }

    @Test("buildConfig includes content options when content enabled")
    func buildConfigWithContent() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.content = true
        state.contentMethod = .ssim
        SetupState.resetWeightsToDefaults(&state)

        let config = state.buildConfig()

        #expect(config.content == true)
        #expect(config.contentMethod == .ssim)
    }

    @Test("buildConfig sets moveToDir only for moveTo action")
    func buildConfigMoveTo() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.action = .moveTo
        state.moveToDir = "/tmp/dups"
        SetupState.resetWeightsToDefaults(&state)

        let config = state.buildConfig()

        #expect(config.moveToDir == "/tmp/dups")
    }

    @Test("buildConfig does not set moveToDir for non-moveTo action")
    func buildConfigNonMoveTo() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.action = .trash
        state.moveToDir = "/tmp/dups"
        SetupState.resetWeightsToDefaults(&state)

        let config = state.buildConfig()

        #expect(config.moveToDir == nil)
    }

    @Test("buildConfig propagates dryRun flag")
    func buildConfigDryRun() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.dryRun = true
        SetupState.resetWeightsToDefaults(&state)

        let config = state.buildConfig()

        #expect(config.dryRun == true)
    }

    @Test("buildConfig actionExplicitlySet false for delete, true for non-delete")
    func buildConfigActionExplicit() {
        var state = SetupState()
        state.entries = [DirectoryEntry(path: "/videos")]
        SetupState.resetWeightsToDefaults(&state)

        state.action = .delete
        #expect(state.buildConfig().actionExplicitlySet == false)

        state.action = .trash
        #expect(state.buildConfig().actionExplicitlySet == true)

        state.action = .moveTo
        state.moveToDir = "/tmp"
        #expect(state.buildConfig().actionExplicitlySet == true)
    }

    // MARK: - Weight sum validation

    @Test("Weight sum valid with default video weights")
    func weightSumValid() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        #expect(state.isWeightSumValid)
        #expect(state.weightSum == 100)
    }

    @Test("Weight sum invalid when weight is changed")
    func weightSumInvalidAfterChange() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.weightStrings["filename"] = "0"

        #expect(!state.isWeightSumValid)
        #expect(state.weightSum == 50) // 0+30+10+10
    }

    @Test("Non-finite weight treated as 0 in sum")
    func nonFiniteWeightInSum() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.weightStrings["filename"] = "nan"

        // nan is treated as 0, so sum = 30+10+10 = 50
        #expect(state.weightSum == 50)
        #expect(state.weightSum.isFinite)
    }

    // MARK: - Filters

    @Test("setFilter updates the correct field")
    func setFilter() {
        let state = SetupState()

        let (s1, _) = reduce(state, .setFilter(.minSize, "10MB"))
        #expect(s1.minSize == "10MB")

        let (s2, _) = reduce(state, .setFilter(.codec, "h264"))
        #expect(s2.codec == "h264")

        let (s3, _) = reduce(state, .setFilter(.minDuration, "30"))
        #expect(s3.minDuration == "30")
    }

    @Test("hasFilters is true when any filter is set")
    func hasFilters() {
        var state = SetupState()
        #expect(state.hasFilters == false)
        #expect(state.activeFilterCount == 0)

        state.minSize = "10MB"
        #expect(state.hasFilters == true)
        #expect(state.activeFilterCount == 1)

        state.codec = "h264"
        #expect(state.activeFilterCount == 2)
    }

    // MARK: - Exclude patterns

    @Test("addExclude appends pattern, removeExclude removes by index")
    func excludePatterns() {
        let state = SetupState()

        let (s1, _) = reduce(state, .addExclude("*.tmp"))
        #expect(s1.exclude == ["*.tmp"])

        let (s2, _) = reduce(s1, .addExclude("thumbs/**"))
        #expect(s2.exclude == ["*.tmp", "thumbs/**"])

        let (s3, _) = reduce(s2, .removeExclude(0))
        #expect(s3.exclude == ["thumbs/**"])
    }

    @Test("addExclude ignores empty/whitespace patterns")
    func addExcludeIgnoresEmpty() {
        let state = SetupState()

        let (s1, _) = reduce(state, .addExclude(""))
        #expect(s1.exclude.isEmpty)

        let (s2, _) = reduce(state, .addExclude("   "))
        #expect(s2.exclude.isEmpty)
    }

    @Test("removeExclude with out-of-bounds index is a no-op")
    func removeExcludeOutOfBounds() {
        var state = SetupState()
        state.exclude = ["*.tmp"]

        let (newState, effects) = reduce(state, .removeExclude(5))

        #expect(newState.exclude == ["*.tmp"])
        #expect(effects.isEmpty)
    }

    // MARK: - setBool

    @Test("setBool noRecursive emits updateFileCount")
    func setBoolNoRecursive() {
        let state = SetupState()

        let (newState, effects) = reduce(state, .setBool(.noRecursive, true))

        #expect(newState.noRecursive == true)
        #expect(effects == [.updateFileCount])
    }

    @Test("setBool verbose does not emit effects")
    func setBoolVerbose() {
        let state = SetupState()

        let (newState, effects) = reduce(state, .setBool(.verbose, true))

        #expect(newState.verbose == true)
        #expect(effects.isEmpty)
    }

    // MARK: - fileCountUpdated

    @Test("fileCountUpdated sets count and clears counting flag")
    func fileCountUpdated() {
        var state = SetupState()
        state.isCountingFiles = true

        let (newState, _) = reduce(state, .fileCountUpdated(42))

        #expect(newState.estimatedFileCount == 42)
        #expect(newState.isCountingFiles == false)
    }

    @Test("fileCountUpdated with nil clears count")
    func fileCountUpdatedNil() {
        var state = SetupState()
        state.estimatedFileCount = 100
        state.isCountingFiles = true

        let (newState, _) = reduce(state, .fileCountUpdated(nil))

        #expect(newState.estimatedFileCount == nil)
        #expect(newState.isCountingFiles == false)
    }

    // MARK: - setDependencyStatus

    @Test("setDependencyStatus updates the status")
    func setDependencyStatus() {
        let state = SetupState()
        let deps = makeDeps()

        let (newState, _) = reduce(state, .setDependencyStatus(deps))

        #expect(newState.dependencyStatus != nil)
        #expect(newState.dependencyStatus?.canScanVideo == true)
    }

    // MARK: - setWeightString / toggleLockedWeight

    @Test("setWeightString updates a single weight")
    func setWeightString() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()

        let (newState, _) = reduce(state, .setWeightString(key: "filename", value: "99"))

        #expect(newState.weightStrings["filename"] == "99")
        // Other weights unchanged
        #expect(newState.weightStrings["duration"] == "30")
    }

    @Test("toggleLockedWeight toggles set membership")
    func toggleLockedWeight() {
        let state = SetupState()

        let (s1, _) = reduce(state, .toggleLockedWeight("filename"))
        #expect(s1.lockedWeights.contains("filename"))

        let (s2, _) = reduce(s1, .toggleLockedWeight("filename"))
        #expect(!s2.lockedWeights.contains("filename"))
    }

    // MARK: - setExtensions

    @Test("setExtensions emits updateFileCount")
    func setExtensionsEmitsEffect() {
        let state = SetupState()

        let (newState, effects) = reduce(state, .setExtensions("mp4,mkv"))

        #expect(newState.extensions == "mp4,mkv")
        #expect(effects == [.updateFileCount])
    }

    // MARK: - Validation

    @Test("No directories: isValid false, error mentions scan directory")
    func validationNoDirectories() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        #expect(state.isValid == false)
        #expect(state.validationErrors.contains { $0.contains("scan directory") })
    }

    @Test("Valid state: one directory with valid weights is valid")
    func validationValidState() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]

        #expect(state.isValid == true)
        #expect(state.validationErrors.isEmpty)
    }

    @Test("Bad weight sum: isValid false")
    func validationBadWeightSum() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.weightStrings["filename"] = "0"

        #expect(state.isValid == false)
        #expect(state.validationErrors.contains { $0.contains("sum to 100") })
    }

    @Test("Auto mode skips weight validation")
    func validationAutoSkipsWeights() {
        var state = SetupState()
        state.mode = .auto
        state.entries = [DirectoryEntry(path: "/media")]

        #expect(state.isValid == true)
    }

    @Test("Content in audio mode produces validation error")
    func validationContentInAudioMode() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/music")]
        state.mode = .audio
        state.content = true
        SetupState.resetWeightsToDefaults(&state)

        #expect(state.validationErrors.contains { $0.contains("Content hashing is not supported in audio mode") })
    }

    @Test("Audio in image mode produces validation error")
    func validationAudioInImageMode() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/photos")]
        state.mode = .image
        state.audio = true
        SetupState.resetWeightsToDefaults(&state)

        #expect(state.validationErrors.contains { $0.contains("Audio fingerprinting is not supported in image mode") })
    }

    @Test("Video mode without ffprobe triggers dependency error")
    func validationVideoNoFfprobe() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.entries = [DirectoryEntry(path: "/videos")]
        state.dependencyStatus = makeDeps(ffprobe: false)

        #expect(state.validationErrors.contains { $0.contains("ffprobe") })
    }

    @Test("Static validation helpers work correctly")
    func staticValidationHelpers() {
        // Size
        #expect(SetupState.isValidSize("") == true)
        #expect(SetupState.isValidSize("500") == true)
        #expect(SetupState.isValidSize("10MB") == true)
        #expect(SetupState.isValidSize("1.5GB") == true)
        #expect(SetupState.isValidSize("abc") == false)

        // Resolution
        #expect(SetupState.isValidResolution("") == true)
        #expect(SetupState.isValidResolution("1920x1080") == true)
        #expect(SetupState.isValidResolution("abc") == false)

        // Bitrate
        #expect(SetupState.isValidBitrate("") == true)
        #expect(SetupState.isValidBitrate("5000000") == true)
        #expect(SetupState.isValidBitrate("5Mbps") == true)
        #expect(SetupState.isValidBitrate("abc") == false)
    }

    // MARK: - toProfileData

    @Test("toProfileData round-trips key fields")
    func toProfileData() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.mode = .video
        state.threshold = 70
        state.keep = .newest
        state.action = .trash
        state.content = false
        state.audio = false

        let data = state.toProfileData()

        #expect(data.mode == "video")
        #expect(data.threshold == 70)
        #expect(data.keep == "newest")
        #expect(data.action == "trash")
        #expect(data.content == false)
        #expect(data.audio == false)
        #expect(data.weights != nil)
    }

    // MARK: - applyProfile

    @Test("applyProfile sets mode and fields from profile data")
    func applyProfile() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        let state = makeDefaultState()

        var profile = ProfileData()
        profile.mode = "image"
        profile.threshold = 75
        profile.content = true
        profile.weights = ["filename": 15, "resolution": 10, "filesize": 10, "exif": 25, "content": 40]

        let (newState, effects) = reduce(state, .applyProfile(profile))

        #expect(newState.mode == .image)
        #expect(newState.threshold == 75)
        #expect(newState.content == true)
        #expect(newState.weightStrings["content"] == "40")
        #expect(newState.weightStrings["exif"] == "25")
        #expect(effects.contains(.detectPreset))
        #expect(effects.contains(.updateFileCount))
    }

    // MARK: - Simple field setters

    @Test("setThreshold, setWorkers, setKeep, setAction, setSort, setGroup, setLimit, setMinScore")
    func simpleSetters() {
        let state = SetupState()

        let (s1, _) = reduce(state, .setThreshold(75))
        #expect(s1.threshold == 75)

        let (s2, _) = reduce(state, .setWorkers(4))
        #expect(s2.workers == 4)

        let (s3, _) = reduce(state, .setKeep(.newest))
        #expect(s3.keep == .newest)

        let (s4, _) = reduce(state, .setAction(.delete))
        #expect(s4.action == .delete)

        let (s5, _) = reduce(state, .setSort(.size))
        #expect(s5.sort == .size)

        let (s6, _) = reduce(state, .setGroup(true))
        #expect(s6.group == true)

        let (s7, _) = reduce(state, .setLimit("50"))
        #expect(s7.limit == "50")

        let (s8, _) = reduce(state, .setMinScore("30"))
        #expect(s8.minScore == "30")
    }

    @Test("setMoveToDir, setExcludeInput update their fields")
    func setMoveToAndExcludeInput() {
        let state = SetupState()

        let (s1, _) = reduce(state, .setMoveToDir("/tmp/dups"))
        #expect(s1.moveToDir == "/tmp/dups")

        let (s2, _) = reduce(state, .setExcludeInput("*.log"))
        #expect(s2.excludeInput == "*.log")
    }

    // MARK: - Content hashing field setters

    @Test("Content hashing field setters update their fields")
    func contentHashingSetters() {
        let state = SetupState()

        let (s1, _) = reduce(state, .setContentMethod(.ssim))
        #expect(s1.contentMethod == .ssim)

        let (s2, _) = reduce(state, .setThumbnailSize("160x90"))
        #expect(s2.thumbnailSize == "160x90")
    }

    @Test("setCacheDir, setIgnoreFile, setLog update their fields")
    func miscStringSetters() {
        let state = SetupState()

        let (s1, _) = reduce(state, .setCacheDir("/cache"))
        #expect(s1.cacheDir == "/cache")

        let (s2, _) = reduce(state, .setIgnoreFile("/ignore.json"))
        #expect(s2.ignoreFile == "/ignore.json")

        let (s3, _) = reduce(state, .setLog("/log.jsonl"))
        #expect(s3.log == "/log.jsonl")
    }

    // MARK: - Equatable

    @Test("SetupState is Equatable")
    func equatable() {
        let s1 = SetupState()
        let s2 = SetupState()
        #expect(s1 == s2)

        var s3 = SetupState()
        s3.mode = .image
        #expect(s1 != s3)
    }

    // MARK: - visibleWeightKeys

    @Test("visibleWeightKeys returns correct keys for each mode")
    func visibleWeightKeys() {
        var state = SetupState()

        state.mode = .video
        state.content = false
        state.audio = false
        #expect(state.visibleWeightKeys == ["filename", "duration", "resolution", "filesize"])

        state.mode = .image
        #expect(state.visibleWeightKeys == ["filename", "resolution", "filesize", "exif"])

        state.mode = .audio
        state.content = false
        #expect(state.visibleWeightKeys == ["filename", "duration", "tags"])

        state.mode = .auto
        #expect(state.visibleWeightKeys == [])
    }

    // MARK: - setScanSource (Photos Library)

    @Test("setScanSource to photosLibrary updates scanSource and forces auto mode")
    func setScanSourcePhotosLibrary() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        // Start with video mode and some content/audio flags
        state.content = true
        state.audio = true

        let (newState, effects) = reduce(state, .setScanSource(.photosLibrary(scope: .fullLibrary)))

        #expect(newState.scanSource == .photosLibrary(scope: .fullLibrary))
        #expect(newState.mode == .auto)
        #expect(newState.content == false)
        #expect(newState.audio == false)
        #expect(effects.contains(.detectPreset))
    }

    @Test("setScanSource to directory keeps existing mode and content/audio flags")
    func setScanSourceDirectory() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.mode = .image
        state.content = true

        let (newState, effects) = reduce(state, .setScanSource(.directory))

        #expect(newState.scanSource == .directory)
        // Mode and content/audio should remain unchanged
        #expect(newState.mode == .image)
        #expect(newState.content == true)
        #expect(effects.contains(.detectPreset))
    }

    @Test("validation skips directory-required error when scanSource is photosLibrary")
    func validationSkipsDirectoryErrorForPhotos() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.scanSource = .photosLibrary(scope: .fullLibrary)
        state.mode = .auto
        state.entries = [] // No directories
        state.dependencyStatus = makeDeps()

        // Should NOT contain "directory required" error
        let directoryErrors = state.validationErrors.filter { $0.contains("directory") }
        #expect(directoryErrors.isEmpty)
    }

    @Test("validation requires directory when scanSource is .directory and no entries")
    func validationRequiresDirectoryForDirectorySource() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = makeDefaultState()
        state.scanSource = .directory
        state.entries = []
        state.dependencyStatus = makeDeps()

        let directoryErrors = state.validationErrors.filter { $0.contains("directory") }
        #expect(!directoryErrors.isEmpty)
    }

    @Test("hasUserModifications detects scanSource change from directory to photosLibrary")
    func hasUserModificationsDetectsScanSourceChange() {
        AppDefaults.resetAll()
        AppDefaults.registerDefaults()
        var state = SetupState.fromDefaults()
        // Default scanSource is .directory
        #expect(state.hasUserModifications == false)

        state.scanSource = .photosLibrary(scope: .fullLibrary)
        state.mode = .auto
        #expect(state.hasUserModifications == true)
    }
}
