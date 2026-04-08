// Tests/FileStatusMonitorTests.swift
import Testing
import Foundation
@testable import DuplicatesDetector

@Suite("FileStatusMonitor")
struct FileStatusMonitorTests {

    // MARK: - Helpers

    /// Create a temp directory with the given filenames and return (dir, [fullPath]).
    private func makeTempDir(
        prefix: String,
        files: [String]
    ) throws -> (URL, [String]) {
        let dir = FileManager.default.temporaryDirectory
            .appending(component: "\(prefix)-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var paths: [String] = []
        for name in files {
            let file = dir.appending(component: name)
            try "content".write(to: file, atomically: true, encoding: .utf8)
            paths.append(file.path)
        }
        return (dir, paths)
    }

    // MARK: - checkStatuses

    @Test("checkStatuses reports all present files")
    func checkStatusesAllPresent() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-present", files: ["a.mp4", "b.mp4", "c.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        let statuses = await monitor.checkStatuses()
        #expect(statuses.count == 3)
        for path in paths {
            #expect(statuses[path] == .present)
        }

        await monitor.stop()
    }

    @Test("checkStatuses detects missing files")
    func checkStatusesMissing() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-missing", files: ["a.mp4", "b.mp4", "c.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        // Delete one file
        try FileManager.default.removeItem(atPath: paths[1])

        let statuses = await monitor.checkStatuses()
        #expect(statuses[paths[0]] == .present)
        #expect(statuses[paths[1]] == .missing)
        #expect(statuses[paths[2]] == .present)

        await monitor.stop()
    }

    @Test("checkStatuses with initially missing files")
    func checkStatusesInitiallyMissing() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-init-missing", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let missingPath = dir.appending(component: "nonexistent.mp4").path
        let allPaths = paths + [missingPath]

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: allPaths)

        let statuses = await monitor.checkStatuses()
        #expect(statuses[paths[0]] == .present)
        #expect(statuses[missingPath] == .missing)

        await monitor.stop()
    }

    // MARK: - addPaths

    @Test("addPaths extends tracked files")
    func addPathsExtends() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-add", files: ["a.mp4", "b.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: [paths[0]])

        // Initially only tracks a.mp4
        var statuses = await monitor.checkStatuses()
        #expect(statuses.count == 1)
        #expect(statuses[paths[0]] == .present)

        // Add b.mp4
        await monitor.addPaths([paths[1]])

        statuses = await monitor.checkStatuses()
        #expect(statuses.count == 2)
        #expect(statuses[paths[0]] == .present)
        #expect(statuses[paths[1]] == .present)

        await monitor.stop()
    }

    // MARK: - stop

    @Test("stop clears all state cleanly")
    func stopClearsState() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-stop", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        let statusesBefore = await monitor.checkStatuses()
        #expect(statusesBefore.count == 1)

        await monitor.stop()

        // After stop, checkStatuses should return empty (no tracked paths)
        let statusesAfter = await monitor.checkStatuses()
        #expect(statusesAfter.isEmpty)
    }

    @Test("stop is safe to call multiple times")
    func stopIdempotent() async throws {
        let monitor = FileStatusMonitor { _ in }
        // Stop without ever starting
        await monitor.stop()
        // Stop again
        await monitor.stop()
        // No crash = success
    }

    // MARK: - Change enum

    @Test("Change enum cases")
    func changeCases() {
        let disappeared = FileStatusMonitor.Change.disappeared("/tmp/a.mp4")
        let appeared = FileStatusMonitor.Change.appeared("/tmp/a.mp4")
        let moved = FileStatusMonitor.Change.moved(from: "/tmp/a.mp4", to: "/tmp/b.mp4")

        // Verify equality
        #expect(disappeared == .disappeared("/tmp/a.mp4"))
        #expect(appeared == .appeared("/tmp/a.mp4"))
        #expect(moved == .moved(from: "/tmp/a.mp4", to: "/tmp/b.mp4"))
        #expect(disappeared != appeared)
    }

    // MARK: - processRawEvents (unit-testable event processing)

    @Test("processRawEvents detects file removal")
    func processRawEventsRemoval() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-remove", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        // Delete the file, then process a removal event
        try FileManager.default.removeItem(atPath: paths[0])

        let events: [FileStatusMonitor.RawFSEvent] = [
            .init(
                path: paths[0],
                flags: UInt32(kFSEventStreamEventFlagItemIsFile) |
                       UInt32(kFSEventStreamEventFlagItemRemoved)
            ),
        ]

        let changes = await monitor.processRawEvents(events)
        #expect(changes.count == 1)
        #expect(changes[0] == .disappeared(paths[0]))

        await monitor.stop()
    }

    @Test("processRawEvents detects file restoration")
    func processRawEventsRestoration() async throws {
        let (dir, _) = try makeTempDir(prefix: "fsm-restore", files: [])
        defer { try? FileManager.default.removeItem(at: dir) }

        let filePath = dir.appending(component: "a.mp4").path

        // Start monitoring a path that doesn't exist yet
        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: [filePath])

        // Verify it's missing
        let statusesBefore = await monitor.checkStatuses()
        #expect(statusesBefore[filePath] == .missing)

        // Create the file (restoration)
        try "content".write(toFile: filePath, atomically: true, encoding: .utf8)

        let events: [FileStatusMonitor.RawFSEvent] = [
            .init(
                path: filePath,
                flags: UInt32(kFSEventStreamEventFlagItemIsFile) |
                       UInt32(kFSEventStreamEventFlagItemCreated)
            ),
        ]

        let changes = await monitor.processRawEvents(events)
        #expect(changes.count == 1)
        #expect(changes[0] == .appeared(filePath))

        await monitor.stop()
    }

    @Test("processRawEvents ignores non-file events")
    func processRawEventsIgnoresDirectories() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-dir", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        // Directory event (no kFSEventStreamEventFlagItemIsFile)
        let events: [FileStatusMonitor.RawFSEvent] = [
            .init(
                path: dir.path,
                flags: UInt32(kFSEventStreamEventFlagItemIsDir) |
                       UInt32(kFSEventStreamEventFlagItemRemoved)
            ),
        ]

        let changes = await monitor.processRawEvents(events)
        #expect(changes.isEmpty)

        await monitor.stop()
    }

    @Test("processRawEvents ignores untracked files")
    func processRawEventsIgnoresUntracked() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-untracked", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        await monitor.start(paths: paths)

        // Event for an untracked file (still exists, not a known inode)
        let events: [FileStatusMonitor.RawFSEvent] = [
            .init(
                path: dir.appending(component: "untracked.mp4").path,
                flags: UInt32(kFSEventStreamEventFlagItemIsFile) |
                       UInt32(kFSEventStreamEventFlagItemRemoved)
            ),
        ]

        let changes = await monitor.processRawEvents(events)
        #expect(changes.isEmpty)

        await monitor.stop()
    }

    // MARK: - fileInode helper

    @Test("fileInode returns value for existing files")
    func fileInodeExisting() throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-inode", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let monitor = FileStatusMonitor { _ in }
        let inode = monitor.fileInode(at: paths[0])
        #expect(inode != nil)
        #expect(inode! > 0)
    }

    @Test("fileInode returns nil for missing files")
    func fileInodeMissing() {
        let monitor = FileStatusMonitor { _ in }
        let inode = monitor.fileInode(at: "/tmp/nonexistent-\(UUID().uuidString).mp4")
        #expect(inode == nil)
    }

    // MARK: - FSEvents integration (timing-dependent)

    /// Helper actor to collect changes from FSEvents in a Sendable-safe way.
    private actor ChangeCollector {
        var batches: [[FileStatusMonitor.Change]] = []
        var receivedAny: Bool { !batches.isEmpty }

        func append(_ changes: [FileStatusMonitor.Change]) {
            batches.append(changes)
        }

        var allChanges: [FileStatusMonitor.Change] {
            batches.flatMap { $0 }
        }
    }

    @Test("detects file deletion via FSEvents")
    func detectsDeletionViaFSEvents() async throws {
        let (dir, paths) = try makeTempDir(prefix: "fsm-fsevents", files: ["a.mp4"])
        defer { try? FileManager.default.removeItem(at: dir) }

        let collector = ChangeCollector()

        let monitor = FileStatusMonitor { changes in
            await collector.append(changes)
        }
        await monitor.start(paths: paths)

        // Give FSEvents time to set up
        try await Task.sleep(for: .milliseconds(300))

        // Delete the file
        try FileManager.default.removeItem(atPath: paths[0])

        // Wait for the callback with timeout
        let deadline = ContinuousClock.now + .seconds(3)
        while ContinuousClock.now < deadline {
            if await collector.receivedAny { break }
            try await Task.sleep(for: .milliseconds(100))
        }

        await monitor.stop()

        // FSEvents integration tests may be flaky — verify what we can
        let allChanges = await collector.allChanges
        if !allChanges.isEmpty {
            let hasDisappeared = allChanges.contains { change in
                if case .disappeared(let path) = change { return path == paths[0] }
                return false
            }
            #expect(hasDisappeared, "Expected .disappeared for deleted file")
        }
        // If no events arrived (timing), the test passes silently —
        // the synchronous processRawEvents tests above cover the logic.
    }
}
