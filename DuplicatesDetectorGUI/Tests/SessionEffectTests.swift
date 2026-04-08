import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - BulkActionItem Tests

@Suite("BulkActionItem Equatable")
struct BulkActionItemTests {

    @Test("Two BulkActionItems with identical fields are equal")
    func equalWhenFieldsMatch() {
        let a = BulkActionItem(
            pairID: PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4"),
            filePath: "/b.mp4",
            action: .trash
        )
        let b = BulkActionItem(
            pairID: PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4"),
            filePath: "/b.mp4",
            action: .trash
        )
        #expect(a == b)
    }

    @Test("BulkActionItems with different pairIDs are not equal")
    func notEqualDifferentPairID() {
        let a = BulkActionItem(
            pairID: PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4"),
            filePath: "/b.mp4",
            action: .trash
        )
        let b = BulkActionItem(
            pairID: PairIdentifier(fileA: "/c.mp4", fileB: "/d.mp4"),
            filePath: "/b.mp4",
            action: .trash
        )
        #expect(a != b)
    }

    @Test("BulkActionItems with different actions are not equal")
    func notEqualDifferentAction() {
        let pairID = PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4")
        let a = BulkActionItem(pairID: pairID, filePath: "/b.mp4", action: .trash)
        let b = BulkActionItem(pairID: pairID, filePath: "/b.mp4", action: .delete)
        #expect(a != b)
    }

    @Test("BulkActionItems with different filePaths are not equal")
    func notEqualDifferentFilePath() {
        let pairID = PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4")
        let a = BulkActionItem(pairID: pairID, filePath: "/a.mp4", action: .trash)
        let b = BulkActionItem(pairID: pairID, filePath: "/b.mp4", action: .trash)
        #expect(a != b)
    }
}

// MARK: - SessionEffect Equatable Tests

@Suite("SessionEffect Equatable")
struct SessionEffectEquatableTests {

    @Test("executeBulk effects with same items are equal")
    func executeBulkEqual() {
        let items = [
            BulkActionItem(
                pairID: PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4"),
                filePath: "/b.mp4",
                action: .trash
            ),
        ]
        let a = SessionEffect.executeBulk(items)
        let b = SessionEffect.executeBulk(items)
        #expect(a == b)
    }

    @Test("executeBulk effects with different items are not equal")
    func executeBulkNotEqual() {
        let itemsA = [
            BulkActionItem(
                pairID: PairIdentifier(fileA: "/a.mp4", fileB: "/b.mp4"),
                filePath: "/b.mp4",
                action: .trash
            ),
        ]
        let itemsB = [
            BulkActionItem(
                pairID: PairIdentifier(fileA: "/c.mp4", fileB: "/d.mp4"),
                filePath: "/d.mp4",
                action: .delete
            ),
        ]
        let a = SessionEffect.executeBulk(itemsA)
        let b = SessionEffect.executeBulk(itemsB)
        #expect(a != b)
    }

    @Test("startWatch effects with same config and same files are equal")
    func startWatchEqualSameFiles() {
        var config = ScanConfig()
        config.directories = ["/videos"]
        config.mode = .video

        let meta = FileMetadata(fileSize: 1024)
        let files = [
            KnownFile(path: "/videos/a.mp4", metadata: meta),
            KnownFile(path: "/videos/b.mp4", metadata: meta),
        ]

        let a = SessionEffect.startWatch(config, files)
        let b = SessionEffect.startWatch(config, files)
        #expect(a == b)
    }

    @Test("startWatch effects with same config but different file lists (same count) are NOT equal")
    func startWatchNotEqualDifferentFilesSameCount() {
        /// This test verifies the bug fix: the old manual Equatable implementation
        /// only compared array counts, not contents. With auto-synthesized Equatable,
        /// arrays with different contents but the same count are correctly unequal.
        var config = ScanConfig()
        config.directories = ["/videos"]

        let filesA = [
            KnownFile(path: "/videos/a.mp4", metadata: FileMetadata(fileSize: 1024)),
            KnownFile(path: "/videos/b.mp4", metadata: FileMetadata(fileSize: 2048)),
        ]
        let filesB = [
            KnownFile(path: "/videos/c.mp4", metadata: FileMetadata(fileSize: 1024)),
            KnownFile(path: "/videos/d.mp4", metadata: FileMetadata(fileSize: 2048)),
        ]

        let a = SessionEffect.startWatch(config, filesA)
        let b = SessionEffect.startWatch(config, filesB)
        #expect(a != b, "startWatch effects with different files (same count) must not be equal")
    }

    @Test("startWatch effects with different configs are not equal")
    func startWatchNotEqualDifferentConfig() {
        let files = [KnownFile(path: "/videos/a.mp4", metadata: FileMetadata(fileSize: 1024))]

        var configA = ScanConfig()
        configA.mode = .video
        var configB = ScanConfig()
        configB.mode = .image

        let a = SessionEffect.startWatch(configA, files)
        let b = SessionEffect.startWatch(configB, files)
        #expect(a != b)
    }

    @Test("startWatch effects with empty file lists are equal")
    func startWatchEqualEmptyFiles() {
        let config = ScanConfig()
        let a = SessionEffect.startWatch(config, [])
        let b = SessionEffect.startWatch(config, [])
        #expect(a == b)
    }

    @Test("Different effect cases are not equal")
    func differentCasesNotEqual() {
        let a = SessionEffect.cancelCLI
        let b = SessionEffect.stopWatch
        #expect(a != b)
    }
}
