import Testing

@testable import DuplicatesDetector

@Suite("FlagAssembler")
struct FlagAssemblerTests {
    @Test("Default config includes required flags")
    func defaultFlags() {
        var config = ScanConfig()
        config.directories = ["/videos"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("scan"))
        #expect(flags.contains("--no-config"))
        #expect(flags.contains("--format"))
        #expect(flags.contains("json"))
        #expect(flags.contains("--json-envelope"))
        #expect(flags.contains("--machine-progress"))
        #expect(flags.contains("--no-color"))
        // Default mode (video) should NOT be emitted
        #expect(!flags.contains("--mode"))
        // Directories should be last
        #expect(flags.last == "/videos")
    }

    @Test("Mode flag emitted for non-default")
    func modeFlag() {
        var config = ScanConfig()
        config.mode = .image
        config.directories = ["/photos"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--mode"))
        let modeIdx = flags.firstIndex(of: "--mode")!
        #expect(flags[modeIdx + 1] == "image")
    }

    @Test("Threshold emitted only when non-default")
    func thresholdFlag() {
        var config = ScanConfig()
        config.threshold = 70
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--threshold"))
        let idx = flags.firstIndex(of: "--threshold")!
        #expect(flags[idx + 1] == "70")
    }

    @Test("Threshold not emitted for default value")
    func thresholdDefault() {
        var config = ScanConfig()
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--threshold"))
    }

    @Test("Keep flag emitted; action and move-to-dir not emitted (GUI-side only)")
    func keepAction() {
        var config = ScanConfig()
        config.keep = .newest
        config.action = .trash
        config.moveToDir = "/tmp/dups"
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--keep"))
        let keepIdx = flags.firstIndex(of: "--keep")!
        #expect(flags[keepIdx + 1] == "newest")

        // --action and --move-to-dir are NOT sent to the CLI;
        // the GUI handles file operations locally.
        #expect(!flags.contains("--action"))
        #expect(!flags.contains("--move-to-dir"))
    }

    @Test("Content sub-options only emitted when content enabled")
    func contentSubOptions() {
        var config = ScanConfig()
        config.content = true
        config.contentMethod = .ssim
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--content"))
        #expect(flags.contains("--content-method"))
    }

    @Test("Content sub-options not emitted when content disabled")
    func contentSubOptionsDisabled() {
        var config = ScanConfig()
        config.content = false
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--content"))
        #expect(!flags.contains("--content-method"))
    }

    @Test("Multiple exclude patterns")
    func multipleExcludes() {
        var config = ScanConfig()
        config.exclude = ["*.tmp", "thumbs/**"]
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        let excludeIndices = flags.indices.filter { flags[$0] == "--exclude" }
        #expect(excludeIndices.count == 2)
        #expect(flags[excludeIndices[0] + 1] == "*.tmp")
        #expect(flags[excludeIndices[1] + 1] == "thumbs/**")
    }

    @Test("Multiple reference directories")
    func multipleReferences() {
        var config = ScanConfig()
        config.reference = ["/ref1", "/ref2"]
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        let refIndices = flags.indices.filter { flags[$0] == "--reference" }
        #expect(refIndices.count == 2)
    }

    @Test("Filter flags")
    func filterFlags() {
        var config = ScanConfig()
        config.minSize = "10MB"
        config.maxSize = "1GB"
        config.minDuration = 30
        config.maxDuration = 3600
        config.codec = "h264"
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--min-size"))
        #expect(flags.contains("--max-size"))
        #expect(flags.contains("--min-duration"))
        #expect(flags.contains("--max-duration"))
        #expect(flags.contains("--codec"))
    }

    @Test("Directories are always last")
    func directoriesLast() {
        var config = ScanConfig()
        config.verbose = true
        config.content = true
        config.directories = ["/dir1", "/dir2"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.suffix(2) == ["/dir1", "/dir2"])
    }

    @Test("Group and verbose flags")
    func groupVerbose() {
        var config = ScanConfig()
        config.group = true
        config.verbose = true
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--group"))
        #expect(flags.contains("--verbose"))
    }

    @Test("Highest-res keep strategy uses hyphenated raw value")
    func highestResKeep() {
        var config = ScanConfig()
        config.keep = .highestRes
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        let keepIdx = flags.firstIndex(of: "--keep")!
        #expect(flags[keepIdx + 1] == "highest-res")
    }

    // MARK: - Weights flag tests

    @Test("Weights flag emitted with sorted keys")
    func weightsFlagSortedKeys() {
        var config = ScanConfig()
        config.weights = ["duration": 20, "filename": 50, "resolution": 20, "filesize": 10]
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--weights"))
        let idx = flags.firstIndex(of: "--weights")!
        #expect(flags[idx + 1] == "duration=20,filename=50,filesize=10,resolution=20")
    }

    @Test("Empty weights dict not emitted")
    func emptyWeightsNotEmitted() {
        var config = ScanConfig()
        config.weights = [:]
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--weights"))
    }

    @Test("Nil weights not emitted")
    func nilWeightsNotEmitted() {
        var config = ScanConfig()
        config.directories = ["/dir"]
        // weights defaults to nil
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--weights"))
    }



    @Test("Fractional weights preserved in serialization")
    func fractionalWeights() {
        var config = ScanConfig()
        config.weights = ["filename": 33.34, "duration": 33.33, "resolution": 33.33]
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        let idx = flags.firstIndex(of: "--weights")!
        #expect(flags[idx + 1] == "duration=33.33,filename=33.34,resolution=33.33")
    }

    // MARK: - Replay mode tests

    @Test("Replay path nil produces scan flags (existing behavior)")
    func replayNilProducesScanFlags() {
        var config = ScanConfig()
        config.replayPath = nil
        config.directories = ["/videos"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("scan"))
        #expect(!flags.contains("--replay"))
        #expect(flags.last == "/videos")
    }

    @Test("Replay path set emits --replay with the path")
    func replayPathEmitted() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--replay"))
        let idx = flags.firstIndex(of: "--replay")!
        #expect(flags[idx + 1] == "/tmp/results.json")
    }

    @Test("Replay mode includes required base flags")
    func replayBaseFlags() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("scan"))
        #expect(flags.contains("--no-config"))
        #expect(flags.contains("--format"))
        #expect(flags.contains("json"))
        #expect(flags.contains("--json-envelope"))
        #expect(flags.contains("--machine-progress"))
        #expect(flags.contains("--no-color"))
    }

    @Test("Replay mode emits --keep when strategy is set")
    func replayKeepFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.keep = .newest
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--keep"))
        let idx = flags.firstIndex(of: "--keep")!
        #expect(flags[idx + 1] == "newest")
    }

    @Test("Replay mode omits --keep when nil")
    func replayKeepNil() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        // keep defaults to nil
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--keep"))
    }

    @Test("Replay mode does NOT emit directories")
    func replayNoDirectories() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.directories = ["/videos", "/photos"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("/videos"))
        #expect(!flags.contains("/photos"))
    }

    @Test("Replay mode does NOT emit scan-specific flags")
    func replayNoScanFlags() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.mode = .image
        config.content = true
        config.audio = true
        config.contentMethod = .ssim
        config.weights = ["filename": 50, "duration": 50]
        config.minSize = "10MB"
        config.maxSize = "1GB"
        config.minDuration = 30
        config.maxDuration = 3600
        config.codec = "h264"
        config.exclude = ["*.tmp"]
        config.cacheDir = "/tmp/cache"
        config.noMetadataCache = true
        config.noContentCache = true
        config.noAudioCache = true
        config.noRecursive = true
        config.verbose = true
        config.workers = 4
        config.extensions = "mp4,mkv"
        config.threshold = 70
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--mode"))
        #expect(!flags.contains("--content"))
        #expect(!flags.contains("--audio"))
        #expect(!flags.contains("--content-method"))
        #expect(!flags.contains("--weights"))
        #expect(!flags.contains("--min-size"))
        #expect(!flags.contains("--max-size"))
        #expect(!flags.contains("--min-duration"))
        #expect(!flags.contains("--max-duration"))
        #expect(!flags.contains("--codec"))
        #expect(!flags.contains("--exclude"))
        #expect(!flags.contains("--cache-dir"))
        #expect(!flags.contains("--no-metadata-cache"))
        #expect(!flags.contains("--no-content-cache"))
        #expect(!flags.contains("--no-audio-cache"))
        #expect(!flags.contains("--no-recursive"))
        #expect(!flags.contains("--verbose"))
        #expect(!flags.contains("--workers"))
        #expect(!flags.contains("--extensions"))
        #expect(!flags.contains("--threshold"))
    }

    @Test("Replay mode emits --sort when non-default")
    func replaySortFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.sort = .size
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--sort"))
        let idx = flags.firstIndex(of: "--sort")!
        #expect(flags[idx + 1] == "size")
    }

    @Test("Replay mode omits --sort for default value (score)")
    func replaySortDefault() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.sort = .score
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--sort"))
    }

    @Test("Replay mode emits --limit")
    func replayLimitFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.limit = 25
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--limit"))
        let idx = flags.firstIndex(of: "--limit")!
        #expect(flags[idx + 1] == "25")
    }

    @Test("Replay mode emits --min-score")
    func replayMinScoreFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.minScore = 80
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--min-score"))
        let idx = flags.firstIndex(of: "--min-score")!
        #expect(flags[idx + 1] == "80")
    }

    @Test("Replay mode emits --group")
    func replayGroupFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.group = true
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--group"))
    }

    @Test("Replay mode emits --reference for each reference directory")
    func replayReferenceFlags() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.reference = ["/ref1", "/ref2"]
        let flags = FlagAssembler.assembleFlags(from: config)

        let refIndices = flags.indices.filter { flags[$0] == "--reference" }
        #expect(refIndices.count == 2)
        #expect(flags[refIndices[0] + 1] == "/ref1")
        #expect(flags[refIndices[1] + 1] == "/ref2")
    }

    @Test("Replay mode emits --embed-thumbnails and --thumbnail-size")
    func replayThumbnailFlags() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.embedThumbnails = true
        config.thumbnailSize = "128x128"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--embed-thumbnails"))
        #expect(flags.contains("--thumbnail-size"))
        let idx = flags.firstIndex(of: "--thumbnail-size")!
        #expect(flags[idx + 1] == "128x128")
    }

    @Test("Replay mode does not emit --thumbnail-size when embedThumbnails is false")
    func replayNoThumbnailSizeWhenDisabled() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.embedThumbnails = false
        config.thumbnailSize = "128x128"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--embed-thumbnails"))
        #expect(!flags.contains("--thumbnail-size"))
    }

    @Test("Replay mode emits --ignore-file")
    func replayIgnoreFileFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.ignoreFile = "/home/user/.local/share/dd/ignored.json"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--ignore-file"))
        let idx = flags.firstIndex(of: "--ignore-file")!
        #expect(flags[idx + 1] == "/home/user/.local/share/dd/ignored.json")
    }

    @Test("Replay mode emits --log")
    func replayLogFlag() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.log = "/tmp/actions.jsonl"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--log"))
        let idx = flags.firstIndex(of: "--log")!
        #expect(flags[idx + 1] == "/tmp/actions.jsonl")
    }

    @Test("Replay mode with all output-shaping flags set")
    func replayAllOutputFlags() {
        var config = ScanConfig()
        config.replayPath = "/tmp/results.json"
        config.sort = .mtime
        config.limit = 10
        config.minScore = 90
        config.group = true
        config.reference = ["/ref"]
        config.embedThumbnails = true
        config.thumbnailSize = "256x256"
        config.ignoreFile = "/tmp/ignore.json"
        config.log = "/tmp/log.jsonl"
        let flags = FlagAssembler.assembleFlags(from: config)

        // All output-shaping flags should be present
        #expect(flags.contains("--sort"))
        #expect(flags.contains("--limit"))
        #expect(flags.contains("--min-score"))
        #expect(flags.contains("--group"))
        #expect(flags.contains("--reference"))
        #expect(flags.contains("--embed-thumbnails"))
        #expect(flags.contains("--thumbnail-size"))
        #expect(flags.contains("--ignore-file"))
        #expect(flags.contains("--log"))
        // But no scan-specific flags
        #expect(!flags.contains("--mode"))
        #expect(!flags.contains("--content"))
        #expect(!flags.contains("--audio"))
        #expect(!flags.contains("--weights"))
    }

    // MARK: - Dry run flag tests

    @Test("Dry run flag emitted when dryRun is true")
    func dryRunFlagEmitted() {
        var config = ScanConfig()
        config.dryRun = true
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--dry-run"))
    }

    @Test("Dry run flag NOT emitted when dryRun is false")
    func dryRunFlagNotEmitted() {
        var config = ScanConfig()
        config.dryRun = false
        config.directories = ["/dir"]
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(!flags.contains("--dry-run"))
    }

    // MARK: - Resume mode tests

    @Test("Resume config emits --resume and omits directories and scan-config flags")
    func resumeEmitsResumeOmitsScanFlags() {
        var config = ScanConfig()
        config.resume = "abc-123"
        config.directories = ["/videos", "/photos"]
        config.mode = .image
        config.threshold = 70
        config.content = true
        config.audio = true
        config.weights = ["filename": 50, "duration": 50]
        config.contentMethod = .ssim
        config.minSize = "10MB"
        config.maxSize = "1GB"
        config.minDuration = 30
        config.maxDuration = 3600
        config.codec = "h264"
        config.exclude = ["*.tmp"]
        config.workers = 4
        config.extensions = "mp4,mkv"
        let flags = FlagAssembler.assembleFlags(from: config)

        // Must contain --resume with the session ID
        #expect(flags.contains("--resume"))
        let idx = flags.firstIndex(of: "--resume")!
        #expect(flags[idx + 1] == "abc-123")

        // Must contain always-on base flags
        #expect(flags.contains("scan"))
        #expect(flags.contains("--no-config"))
        #expect(flags.contains("--format"))
        #expect(flags.contains("json"))
        #expect(flags.contains("--json-envelope"))
        #expect(flags.contains("--machine-progress"))
        #expect(flags.contains("--no-color"))

        // Must NOT contain directories
        #expect(!flags.contains("/videos"))
        #expect(!flags.contains("/photos"))

        // Must NOT contain scan-config flags
        #expect(!flags.contains("--mode"))
        #expect(!flags.contains("--threshold"))
        #expect(!flags.contains("--content"))
        #expect(!flags.contains("--audio"))
        #expect(!flags.contains("--weights"))
        #expect(!flags.contains("--hash-size"))
        #expect(!flags.contains("--hash-algo"))
        #expect(!flags.contains("--content-strategy"))
        #expect(!flags.contains("--scene-threshold"))
        #expect(!flags.contains("--content-method"))
        #expect(!flags.contains("--min-size"))
        #expect(!flags.contains("--max-size"))
        #expect(!flags.contains("--min-duration"))
        #expect(!flags.contains("--max-duration"))
        #expect(!flags.contains("--codec"))
        #expect(!flags.contains("--exclude"))
        #expect(!flags.contains("--workers"))
        #expect(!flags.contains("--extensions"))
    }

    @Test("Resume config with verbose includes --verbose")
    func resumeVerbose() {
        var config = ScanConfig()
        config.resume = "sess-42"
        config.verbose = true
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--resume"))
        #expect(flags.contains("--verbose"))
    }

    @Test("Resume config with cacheStats includes --cache-stats")
    func resumeCacheStats() {
        var config = ScanConfig()
        config.resume = "sess-42"
        config.cacheStats = true
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--resume"))
        #expect(flags.contains("--cache-stats"))
    }

    @Test("Resume config with pauseFile includes --pause-file")
    func resumePauseFile() {
        var config = ScanConfig()
        config.resume = "sess-42"
        config.pauseFile = "/tmp/dd-pause"
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--resume"))
        #expect(flags.contains("--pause-file"))
        let idx = flags.firstIndex(of: "--pause-file")!
        #expect(flags[idx + 1] == "/tmp/dd-pause")
    }

    @Test("Resume config without presentation overrides omits them")
    func resumeNoPresentationOverrides() {
        var config = ScanConfig()
        config.resume = "sess-42"
        // verbose, cacheStats, pauseFile all at defaults
        let flags = FlagAssembler.assembleFlags(from: config)

        #expect(flags.contains("--resume"))
        #expect(!flags.contains("--verbose"))
        #expect(!flags.contains("--cache-stats"))
        #expect(!flags.contains("--pause-file"))
    }

    // MARK: - Document mode tests

    @Test("Document mode emits --mode document")
    func documentModeFlag() {
        var config = ScanConfig()
        config.mode = .document
        config.directories = ["/tmp/docs"]
        let flags = FlagAssembler.assembleFlags(from: config)
        #expect(flags.contains("--mode"))
        #expect(flags.contains("document"))
    }

    @Test("Document mode with simhash content method emits --content-method simhash")
    func documentContentSimhash() {
        var config = ScanConfig()
        config.mode = .document
        config.content = true
        config.contentMethod = .simhash
        config.directories = ["/tmp/docs"]
        let flags = FlagAssembler.assembleFlags(from: config)
        #expect(flags.contains("--content"))
        #expect(flags.contains("--content-method"))
        #expect(flags.contains("simhash"))
    }

    @Test("Document mode with tfidf emits --content-method tfidf")
    func documentContentTfidf() {
        var config = ScanConfig()
        config.mode = .document
        config.content = true
        config.contentMethod = .tfidf
        config.directories = ["/tmp/docs"]
        let flags = FlagAssembler.assembleFlags(from: config)
        #expect(flags.contains("--content-method"))
        #expect(flags.contains("tfidf"))
    }

}
