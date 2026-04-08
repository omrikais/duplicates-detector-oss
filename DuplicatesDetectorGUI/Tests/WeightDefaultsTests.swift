import Testing

@testable import DuplicatesDetector

@Suite("WeightDefaults")
struct WeightDefaultsTests {
    // MARK: - All weight tables sum to exactly 100

    @Test(
        "All 10 default weight tables sum to exactly 100",
        arguments: [
            ("videoDefault", WeightDefaults.videoDefault),
            ("videoContent", WeightDefaults.videoContent),
            ("videoAudio", WeightDefaults.videoAudio),
            ("videoContentAudio", WeightDefaults.videoContentAudio),
            ("imageDefault", WeightDefaults.imageDefault),
            ("imageContent", WeightDefaults.imageContent),
            ("audioDefault", WeightDefaults.audioDefault),
            ("audioFingerprint", WeightDefaults.audioFingerprint),
            ("documentDefault", WeightDefaults.documentDefault),
            ("documentContent", WeightDefaults.documentContent),
        ] as [(String, [String: Double])]
    )
    func weightTablesSumTo100(name: String, table: [String: Double]) {
        let sum = table.values.reduce(0, +)
        #expect(sum == 100, "Table \(name) sums to \(sum), expected 100")
    }

    // MARK: - rules(for:) returns correct ModeRules

    @Test("Video rules: correct baseKeys, forbidden, supportsContent, supportsAudio")
    func videoRules() {
        let rules = WeightDefaults.rules(for: .video)
        #expect(rules != nil)
        let r = rules!
        #expect(r.baseKeys == ["filename", "duration", "resolution", "filesize"])
        #expect(r.forbiddenKeys == Set(["exif", "tags"]))
        #expect(r.supportsContent == true)
        #expect(r.supportsAudio == true)
    }

    @Test("Image rules: correct baseKeys, forbidden, supportsContent, supportsAudio")
    func imageRules() {
        let rules = WeightDefaults.rules(for: .image)
        #expect(rules != nil)
        let r = rules!
        #expect(r.baseKeys == ["filename", "resolution", "filesize", "exif"])
        #expect(r.forbiddenKeys == Set(["duration", "audio", "tags"]))
        #expect(r.supportsContent == true)
        #expect(r.supportsAudio == false)
    }

    @Test("Audio rules: correct baseKeys, forbidden, supportsContent, supportsAudio")
    func audioRules() {
        let rules = WeightDefaults.rules(for: .audio)
        #expect(rules != nil)
        let r = rules!
        #expect(r.baseKeys == ["filename", "duration", "tags"])
        #expect(r.forbiddenKeys == Set(["resolution", "filesize", "exif", "content"]))
        #expect(r.supportsContent == false)
        #expect(r.supportsAudio == true)
    }

    @Test("Auto mode returns nil rules")
    func autoRulesNil() {
        let rules = WeightDefaults.rules(for: .auto)
        #expect(rules == nil)
    }

    // MARK: - requiredKeys

    @Test("Video default required keys are the 4 base keys")
    func videoDefaultRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .video, content: false, audio: false)
        #expect(keys == ["filename", "duration", "resolution", "filesize"])
    }

    @Test("Video + content includes content key")
    func videoContentRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .video, content: true, audio: false)
        #expect(keys != nil)
        #expect(keys!.contains("content"))
        #expect(keys!.count == 5)
    }

    @Test("Video + audio includes audio key")
    func videoAudioRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .video, content: false, audio: true)
        #expect(keys != nil)
        #expect(keys!.contains("audio"))
        #expect(keys!.count == 5)
    }

    @Test("Video + content + audio includes both")
    func videoContentAudioRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .video, content: true, audio: true)
        #expect(keys != nil)
        #expect(keys!.contains("content"))
        #expect(keys!.contains("audio"))
        #expect(keys!.count == 6)
    }

    @Test("Auto mode returns nil required keys")
    func autoRequiredKeysNil() {
        let keys = WeightDefaults.requiredKeys(mode: .auto, content: false, audio: false)
        #expect(keys == nil)
    }

    @Test("Image + content includes content key")
    func imageContentRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .image, content: true, audio: false)
        #expect(keys != nil)
        #expect(keys!.contains("content"))
    }

    @Test("Image + audio does NOT add audio (unsupported)")
    func imageAudioUnsupported() {
        let keys = WeightDefaults.requiredKeys(mode: .image, content: false, audio: true)
        #expect(keys != nil)
        #expect(!keys!.contains("audio"))
    }

    @Test("Audio + content does NOT add content (unsupported)")
    func audioContentUnsupported() {
        let keys = WeightDefaults.requiredKeys(mode: .audio, content: true, audio: false)
        #expect(keys != nil)
        #expect(!keys!.contains("content"))
    }

    // MARK: - defaults(mode:content:audio:)

    @Test("Auto mode returns nil defaults")
    func autoDefaultsNil() {
        let d = WeightDefaults.defaults(mode: .auto, content: false, audio: false)
        #expect(d == nil)
    }

    @Test("Video default matches videoDefault table")
    func videoDefaultTable() {
        let d = WeightDefaults.defaults(mode: .video, content: false, audio: false)
        #expect(d == WeightDefaults.videoDefault)
    }

    @Test("Video + content matches videoContent table")
    func videoContentTable() {
        let d = WeightDefaults.defaults(mode: .video, content: true, audio: false)
        #expect(d == WeightDefaults.videoContent)
    }

    @Test("Video + audio matches videoAudio table")
    func videoAudioTable() {
        let d = WeightDefaults.defaults(mode: .video, content: false, audio: true)
        #expect(d == WeightDefaults.videoAudio)
    }

    @Test("Video + content + audio matches videoContentAudio table")
    func videoContentAudioTable() {
        let d = WeightDefaults.defaults(mode: .video, content: true, audio: true)
        #expect(d == WeightDefaults.videoContentAudio)
    }

    @Test("Image default matches imageDefault table")
    func imageDefaultTable() {
        let d = WeightDefaults.defaults(mode: .image, content: false, audio: false)
        #expect(d == WeightDefaults.imageDefault)
    }

    @Test("Image + content matches imageContent table")
    func imageContentTable() {
        let d = WeightDefaults.defaults(mode: .image, content: true, audio: false)
        #expect(d == WeightDefaults.imageContent)
    }

    @Test("Audio default matches audioDefault table")
    func audioDefaultTable() {
        let d = WeightDefaults.defaults(mode: .audio, content: false, audio: false)
        #expect(d == WeightDefaults.audioDefault)
    }

    @Test("Audio + fingerprint matches audioFingerprint table")
    func audioFingerprintTable() {
        let d = WeightDefaults.defaults(mode: .audio, content: false, audio: true)
        #expect(d == WeightDefaults.audioFingerprint)
    }

    // MARK: - Document mode

    @Test("Document rules: correct baseKeys, forbidden, supportsContent, supportsAudio")
    func documentRules() {
        let rules = WeightDefaults.rules(for: .document)
        #expect(rules != nil)
        let r = rules!
        #expect(r.baseKeys == ["filename", "filesize", "page_count", "doc_meta"])
        #expect(r.forbiddenKeys == Set(["duration", "resolution", "exif", "tags", "audio"]))
        #expect(r.supportsContent == true)
        #expect(r.supportsAudio == false)
    }

    @Test("Document default required keys are the 4 base keys")
    func documentDefaultRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .document, content: false, audio: false)
        #expect(keys == ["filename", "filesize", "page_count", "doc_meta"])
    }

    @Test("Document + content includes content key")
    func documentContentRequiredKeys() {
        let keys = WeightDefaults.requiredKeys(mode: .document, content: true, audio: false)
        #expect(keys != nil)
        #expect(keys!.contains("content"))
        #expect(keys!.count == 5)
    }

    @Test("Document default matches documentDefault table")
    func documentDefaultTable() {
        let d = WeightDefaults.defaults(mode: .document, content: false, audio: false)
        #expect(d == WeightDefaults.documentDefault)
    }

    @Test("Document + content matches documentContent table")
    func documentContentTable() {
        let d = WeightDefaults.defaults(mode: .document, content: true, audio: false)
        #expect(d == WeightDefaults.documentContent)
    }
}
