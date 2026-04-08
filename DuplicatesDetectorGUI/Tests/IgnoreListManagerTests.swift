import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - removePair

@Suite("IgnoreListManager — removePair")
struct IgnoreListRemovePairTests {
    /// Create a temp file URL with a unique name.
    private func tempFileURL() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-remove-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
    }

    /// Clean up a temp file and its parent directory.
    private func cleanup(_ url: URL) {
        let parent = url.deletingLastPathComponent()
        try? FileManager.default.removeItem(at: parent)
    }

    @Test("removePair removes the correct pair and preserves others")
    func removePairRemovesCorrectPair() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/e.mp4", "/file/f.mp4", to: url)

        // Remove the middle pair
        try await IgnoreListManager.shared.removePair("/file/c.mp4", "/file/d.mp4", from: url)

        let remaining = await IgnoreListManager.shared.load(from: url)
        #expect(remaining.count == 2)
        #expect(remaining[0] == ["/file/a.mp4", "/file/b.mp4"])
        #expect(remaining[1] == ["/file/e.mp4", "/file/f.mp4"])
    }

    @Test("removePair on a non-existent pair is a no-op")
    func removePairNonExistentPairIsNoOp() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        let beforeData = try Data(contentsOf: url)

        // Try to remove a pair that doesn't exist
        try await IgnoreListManager.shared.removePair("/file/x.mp4", "/file/y.mp4", from: url)

        // File should be unchanged
        let afterData = try Data(contentsOf: url)
        #expect(beforeData == afterData)

        let remaining = await IgnoreListManager.shared.load(from: url)
        #expect(remaining.count == 1)
    }

    @Test("removePair resolves paths and sorts before matching")
    func removePairResolvesAndSorts() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        // Add pair in sorted order
        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)

        // Remove with reversed argument order — should still match
        try await IgnoreListManager.shared.removePair("/file/b.mp4", "/file/a.mp4", from: url)

        let remaining = await IgnoreListManager.shared.load(from: url)
        #expect(remaining.isEmpty)
    }

    @Test("removePair on non-existent file is a no-op (no error)")
    func removePairOnNonExistentFile() async throws {
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-remove-nonexistent-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
        // File does not exist — load returns []
        // removePair loads the file, gets empty list, finds nothing to remove, returns early
        try await IgnoreListManager.shared.removePair("/file/a.mp4", "/file/b.mp4", from: url)
        // No error thrown, no file created
        #expect(!FileManager.default.fileExists(atPath: url.path))
    }
}

// MARK: - clearAll

@Suite("IgnoreListManager — clearAll")
struct IgnoreListClearAllTests {
    private func tempFileURL() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-clear-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
    }

    private func cleanup(_ url: URL) {
        let parent = url.deletingLastPathComponent()
        try? FileManager.default.removeItem(at: parent)
    }

    @Test("clearAll empties the file and count returns 0")
    func clearAllEmptiesFile() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        let beforeCount = await IgnoreListManager.shared.count(at: url)
        #expect(beforeCount == 2)

        try await IgnoreListManager.shared.clearAll(at: url)

        let afterCount = await IgnoreListManager.shared.count(at: url)
        #expect(afterCount == 0)
        let loaded = await IgnoreListManager.shared.load(from: url)
        #expect(loaded.isEmpty)
    }

    @Test("clearAll on nonexistent file is a no-op")
    func clearAllOnNonexistentFile() async throws {
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-clear-nonexistent-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
        // File does not exist — should not throw
        try await IgnoreListManager.shared.clearAll(at: url)
        // File was not created
        #expect(!FileManager.default.fileExists(atPath: url.path))
    }

    @Test("clearAll writes valid empty JSON array")
    func clearAllWritesValidEmptyJSON() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.clearAll(at: url)

        let data = try Data(contentsOf: url)
        let parsed = try JSONSerialization.jsonObject(with: data) as? [[String]]
        #expect(parsed != nil)
        #expect(parsed?.isEmpty == true)
    }
}

// MARK: - count

@Suite("IgnoreListManager — count")
struct IgnoreListCountTests {
    private func tempFileURL() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-count-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
    }

    private func cleanup(_ url: URL) {
        let parent = url.deletingLastPathComponent()
        try? FileManager.default.removeItem(at: parent)
    }

    @Test("count returns 0 for nonexistent file")
    func countReturnsZeroForNonexistentFile() async {
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-count-nonexistent-\(UUID().uuidString).json")
        let count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)
    }

    @Test("count returns correct value after adding pairs")
    func countAfterAdding() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        var count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)

        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 2)
    }

    @Test("count reflects removals")
    func countAfterRemoval() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        var count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 2)

        try await IgnoreListManager.shared.removePair("/file/a.mp4", "/file/b.mp4", from: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)
    }

    @Test("count returns 0 after clearAll")
    func countAfterClearAll() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        try await IgnoreListManager.shared.clearAll(at: url)
        let count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)
    }
}

// MARK: - CRUD round-trip

@Suite("IgnoreListManager — CRUD round-trip")
struct IgnoreListCRUDRoundTripTests {
    private func tempFileURL() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-roundtrip-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
    }

    private func cleanup(_ url: URL) {
        let parent = url.deletingLastPathComponent()
        try? FileManager.default.removeItem(at: parent)
    }

    @Test("Full CRUD lifecycle: add → count=1 → remove → count=0 → re-add → count=1")
    func fullCRUDLifecycle() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        // Add
        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        var count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)

        // Remove
        try await IgnoreListManager.shared.removePair("/file/a.mp4", "/file/b.mp4", from: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)

        // Re-add
        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)
        let loaded = await IgnoreListManager.shared.load(from: url)
        #expect(loaded.count == 1)
        #expect(loaded[0] == ["/file/a.mp4", "/file/b.mp4"])
    }

    @Test("Add multiple → clear → count=0 → add → count=1")
    func clearAndReAdd() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/e.mp4", "/file/f.mp4", to: url)
        var count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 3)

        try await IgnoreListManager.shared.clearAll(at: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)

        try await IgnoreListManager.shared.addPair("/file/new.mp4", "/file/other.mp4", to: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)
    }

    @Test("Remove first, last, and middle entries independently")
    func removeVariousPositions() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        try await IgnoreListManager.shared.addPair("/file/a.mp4", "/file/b.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/c.mp4", "/file/d.mp4", to: url)
        try await IgnoreListManager.shared.addPair("/file/e.mp4", "/file/f.mp4", to: url)

        // Remove first
        try await IgnoreListManager.shared.removePair("/file/a.mp4", "/file/b.mp4", from: url)
        var count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 2)

        // Remove last
        try await IgnoreListManager.shared.removePair("/file/e.mp4", "/file/f.mp4", from: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 1)

        // Remove the remaining middle one
        try await IgnoreListManager.shared.removePair("/file/c.mp4", "/file/d.mp4", from: url)
        count = await IgnoreListManager.shared.count(at: url)
        #expect(count == 0)
    }
}

// MARK: - Concurrent serialization

@Suite("IgnoreListManager — Concurrent serialization")
struct IgnoreListConcurrentTests {
    private func tempFileURL() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("ignorelist-concurrent-\(UUID().uuidString)")
            .appendingPathComponent("ignored-pairs.json")
    }

    private func cleanup(_ url: URL) {
        let parent = url.deletingLastPathComponent()
        try? FileManager.default.removeItem(at: parent)
    }

    @Test("Concurrent addPair calls don't lose entries")
    func concurrentAddPairsPreserveAllEntries() async throws {
        let url = tempFileURL()
        defer { cleanup(url) }

        // Launch multiple concurrent addPair calls
        try await withThrowingTaskGroup(of: Void.self) { group in
            for i in 0..<10 {
                group.addTask {
                    try await IgnoreListManager.shared.addPair(
                        "/file/\(i)a.mp4", "/file/\(i)b.mp4", to: url
                    )
                }
            }
            try await group.waitForAll()
        }

        // All 10 pairs must be present — actor serialization prevents lost writes
        let loaded = await IgnoreListManager.shared.load(from: url)
        #expect(loaded.count == 10)
    }
}
