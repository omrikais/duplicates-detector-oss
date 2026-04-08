import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("JSONEnvelopeParser")
struct JSONEnvelopeParserTests {
    private func loadFixture(_ name: String) throws -> Data {
        try FixtureLoader.data(named: name)
    }

    @Test("Parse pair envelope")
    func parsePairEnvelope() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        #expect(envelope.version == "1.5.0")
        #expect(envelope.generatedAt == "2025-01-15T10:30:00+00:00")

        // Args
        #expect(envelope.args.directories == ["/videos"])
        #expect(envelope.args.threshold == 50)
        #expect(envelope.args.content == false)
        #expect(envelope.args.mode == "video")
        #expect(envelope.args.keep == "newest")

        // Stats
        #expect(envelope.stats.filesScanned == 10)
        #expect(envelope.stats.filesAfterFilter == 8)
        #expect(envelope.stats.totalPairsScored == 28)
        #expect(envelope.stats.pairsAboveThreshold == 2)

        // Content should be pairs
        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs content")
            return
        }
        #expect(pairs.count == 2)
    }

    @Test("Pair with reference flag")
    func pairReference() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs")
            return
        }

        let first = pairs[0]
        #expect(first.fileAIsReference == true)
        #expect(first.fileBIsReference == false)
        #expect(first.keep == "b")
    }

    @Test("Nullable breakdown values")
    func nullableBreakdown() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs")
            return
        }

        let second = pairs[1]
        // "content": null in the breakdown
        #expect(second.breakdown.keys.contains("content"))
        #expect(second.breakdown["content"] as? Double == nil)
        // "filename" should have a value
        #expect(second.breakdown["filename"]! == 35.0)
    }

    @Test("Detail scores decoded as [raw, weight] arrays")
    func detailScores() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs")
            return
        }

        let detail = pairs[0].detail
        #expect(detail["filename"]?.raw == 0.9)
        #expect(detail["filename"]?.weight == 50)
        #expect(detail["duration"]?.raw == 0.9)
        #expect(detail["duration"]?.weight == 30)
    }

    @Test("Metadata with tag fields")
    func metadataWithTags() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs")
            return
        }

        let second = pairs[1]
        // file_b has tag_title and tag_artist
        #expect(second.fileBMetadata.tagTitle == "My Song")
        #expect(second.fileBMetadata.tagArtist == "Artist Name")
        #expect(second.fileBMetadata.tagAlbum == nil)

        // file_a has no tags
        #expect(second.fileAMetadata.tagTitle == nil)
    }

    @Test("Metadata numeric fields")
    func metadataFields() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .pairs(let pairs) = envelope.content else {
            Issue.record("Expected pairs")
            return
        }

        let meta = pairs[0].fileAMetadata
        #expect(meta.duration == 120.5)
        #expect(meta.width == 1920)
        #expect(meta.height == 1080)
        #expect(meta.fileSize == 52428800)
        #expect(meta.codec == "h264")
        #expect(meta.bitrate == 3500000)
        #expect(meta.framerate == 29.97)
        #expect(meta.audioChannels == 2)
    }

    @Test("Parse group envelope")
    func parseGroupEnvelope() throws {
        let data = try loadFixture("envelope-groups.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        #expect(envelope.args.group == true)

        guard case .groups(let groups) = envelope.content else {
            Issue.record("Expected groups content")
            return
        }
        #expect(groups.count == 1)

        let group = groups[0]
        #expect(group.groupId == 1)
        #expect(group.fileCount == 3)
        #expect(group.maxScore == 90.0)
        #expect(group.minScore == 60.0)
        #expect(group.avgScore == 75.0)
        #expect(group.files.count == 3)
        #expect(group.pairs.count == 3)
    }

    @Test("Group files have metadata")
    func groupFileMetadata() throws {
        let data = try loadFixture("envelope-groups.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .groups(let groups) = envelope.content else {
            Issue.record("Expected groups")
            return
        }

        let file = groups[0].files[0]
        #expect(file.path == "/videos/a.mp4")
        #expect(file.duration == 60.0)
        #expect(file.width == 1920)
        #expect(file.height == 1080)
        #expect(file.isReference == false)
    }

    @Test("Pair envelope includes analytics")
    func pairEnvelopeAnalytics() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        #expect(envelope.analytics != nil)
        #expect(envelope.analytics?.directoryStats.count == 1)
    }

    @Test("Group envelope has nil analytics")
    func groupEnvelopeAnalytics() throws {
        let data = try loadFixture("envelope-groups.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        #expect(envelope.analytics == nil)
    }

    @Test("Group pair detail scores")
    func groupPairDetail() throws {
        let data = try loadFixture("envelope-groups.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        guard case .groups(let groups) = envelope.content else {
            Issue.record("Expected groups")
            return
        }

        let pair = groups[0].pairs[0]
        #expect(pair.score == 90.0)
        #expect(pair.detail["filename"]?.raw == 0.8)
        #expect(pair.detail["filename"]?.weight == 50)
    }
}
