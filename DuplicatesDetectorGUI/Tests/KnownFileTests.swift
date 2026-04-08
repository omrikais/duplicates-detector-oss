import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("KnownFile Equatable")
struct KnownFileEquatableTests {

    @Test("Two KnownFiles with identical fields are equal")
    func equalWhenFieldsMatch() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(
            path: "/tmp/a.mp4",
            metadata: meta,
            contentHash: "abc",
            audioFingerprint: Data([0x01, 0x02]),
            effectiveMode: .video
        )
        let b = KnownFile(
            path: "/tmp/a.mp4",
            metadata: meta,
            contentHash: "abc",
            audioFingerprint: Data([0x01, 0x02]),
            effectiveMode: .video
        )
        #expect(a == b)
    }

    @Test("KnownFiles with different paths are not equal")
    func notEqualDifferentPath() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta)
        let b = KnownFile(path: "/tmp/b.mp4", metadata: meta)
        #expect(a != b)
    }

    @Test("KnownFiles with different metadata are not equal")
    func notEqualDifferentMetadata() {
        let a = KnownFile(path: "/tmp/a.mp4", metadata: FileMetadata(fileSize: 1024))
        let b = KnownFile(path: "/tmp/a.mp4", metadata: FileMetadata(fileSize: 2048))
        #expect(a != b)
    }

    @Test("KnownFiles with different contentHash are not equal")
    func notEqualDifferentContentHash() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta, contentHash: "abc")
        let b = KnownFile(path: "/tmp/a.mp4", metadata: meta, contentHash: "xyz")
        #expect(a != b)
    }

    @Test("KnownFiles with different audioFingerprint are not equal")
    func notEqualDifferentFingerprint() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta, audioFingerprint: Data([0x01]))
        let b = KnownFile(path: "/tmp/a.mp4", metadata: meta, audioFingerprint: Data([0x02]))
        #expect(a != b)
    }

    @Test("KnownFiles with different effectiveMode are not equal")
    func notEqualDifferentEffectiveMode() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta, effectiveMode: .video)
        let b = KnownFile(path: "/tmp/a.mp4", metadata: meta, effectiveMode: .image)
        #expect(a != b)
    }

    @Test("KnownFiles with nil vs non-nil optional fields are not equal")
    func notEqualNilVsNonNil() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta, contentHash: nil)
        let b = KnownFile(path: "/tmp/a.mp4", metadata: meta, contentHash: "abc")
        #expect(a != b)
    }

    @Test("KnownFiles with all nil optionals are equal")
    func equalWithAllNilOptionals() {
        let meta = FileMetadata(fileSize: 1024)
        let a = KnownFile(path: "/tmp/a.mp4", metadata: meta)
        let b = KnownFile(path: "/tmp/a.mp4", metadata: meta)
        #expect(a == b)
    }
}
