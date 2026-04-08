// Tests/DirectoryWatcherTests.swift
import Testing
import Foundation
@testable import DuplicatesDetector

@Suite("DirectoryWatcher")
struct DirectoryWatcherTests {

    @Test("FileEvent enum cases")
    func fileEventCases() {
        let url = URL(filePath: "/tmp/test.mp4")
        let created = DirectoryWatcher.FileEvent.created(url)
        let renamed = DirectoryWatcher.FileEvent.renamed(url)

        if case .created(let u) = created {
            #expect(u == url)
        } else {
            Issue.record("Expected .created")
        }

        if case .renamed(let u) = renamed {
            #expect(u == url)
        } else {
            Issue.record("Expected .renamed")
        }
    }

    @Test("FileEvent.directoryChanged holds the correct URL")
    func directoryChangedEventHoldsURL() {
        let url = URL(filePath: "/Volumes/External/Movies", directoryHint: .isDirectory)
        let event = DirectoryWatcher.FileEvent.directoryChanged(url)

        if case .directoryChanged(let u) = event {
            #expect(u == url)
        } else {
            Issue.record("Expected .directoryChanged")
        }
    }

    @Test("extensionsForMode returns correct sets")
    func extensionsForMode() {
        let video = DirectoryWatcher.extensionsForMode(.video)
        #expect(video.contains("mp4"))
        #expect(video.contains("mkv"))
        #expect(!video.contains("jpg"))

        let image = DirectoryWatcher.extensionsForMode(.image)
        #expect(image.contains("jpg"))
        #expect(image.contains("png"))
        #expect(!image.contains("mp4"))

        let audio = DirectoryWatcher.extensionsForMode(.audio)
        #expect(audio.contains("mp3"))
        #expect(audio.contains("flac"))
    }

    @Test("extensionsForMode auto returns union of video and image extensions")
    func extensionsForModeAuto() {
        let extensions = DirectoryWatcher.extensionsForMode(.auto)
        let video = DirectoryWatcher.extensionsForMode(.video)
        let image = DirectoryWatcher.extensionsForMode(.image)
        #expect(extensions == video.union(image))
        #expect(extensions.contains("mp4"))
        #expect(extensions.contains("jpg"))
        #expect(!extensions.isEmpty)
    }

    @Test("shouldInclude filters by extension and ignores dotfiles")
    func shouldIncludeFiltering() {
        let extensions: Set<String> = ["mp4", "mkv"]

        #expect(DirectoryWatcher.shouldInclude(
            URL(filePath: "/tmp/video.mp4"), extensions: extensions))
        #expect(DirectoryWatcher.shouldInclude(
            URL(filePath: "/tmp/video.MKV"), extensions: extensions))
        #expect(!DirectoryWatcher.shouldInclude(
            URL(filePath: "/tmp/photo.jpg"), extensions: extensions))
        #expect(!DirectoryWatcher.shouldInclude(
            URL(filePath: "/tmp/.hidden.mp4"), extensions: extensions))
        #expect(!DirectoryWatcher.shouldInclude(
            URL(filePath: "/tmp/.DS_Store"), extensions: extensions))
    }

    @Test("start and stop lifecycle")
    func startStopLifecycle() async {
        let watcher = DirectoryWatcher()
        let dir = FileManager.default.temporaryDirectory
            .appending(component: "watcher-test-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let _ = await watcher.start(
            directories: [dir], latency: 0.1, extensions: Set(["txt"]))
        let isRunning = await watcher.isRunning
        #expect(isRunning)

        await watcher.stop()
        let isStoppedNow = await watcher.isRunning
        #expect(!isStoppedNow)
    }

    @Test("detects file creation")
    func detectsFileCreation() async throws {
        let watcher = DirectoryWatcher()
        let dir = FileManager.default.temporaryDirectory
            .appending(component: "watcher-create-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let stream = await watcher.start(
            directories: [dir], latency: 0.1, extensions: Set(["txt"]))

        // Give FSEvents time to set up
        try await Task.sleep(for: .milliseconds(200))

        // Create a file
        let file = dir.appending(component: "test.txt")
        try "hello".write(to: file, atomically: true, encoding: .utf8)

        // Collect events with timeout
        var events: [DirectoryWatcher.FileEvent] = []
        let deadline = ContinuousClock.now + .seconds(3)
        for await event in stream {
            events.append(event)
            if ContinuousClock.now >= deadline || events.count >= 1 { break }
        }

        await watcher.stop()

        #expect(!events.isEmpty, "Should detect at least one file event")
        if case .created(let url) = events[0] {
            #expect(url.lastPathComponent == "test.txt")
        }
    }

    @Test("detects file creation in subdirectory")
    func detectsFileCreationInSubdirectory() async throws {
        let watcher = DirectoryWatcher()
        let dir = FileManager.default.temporaryDirectory
            .appending(component: "watcher-subdir-\(UUID().uuidString)")
        let subdir = dir.appending(component: "nested")
        try FileManager.default.createDirectory(at: subdir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let stream = await watcher.start(
            directories: [dir], latency: 0.1, extensions: Set(["txt"]))

        // Give FSEvents time to set up
        try await Task.sleep(for: .milliseconds(200))

        // Create a file in the subdirectory
        let file = subdir.appending(component: "nested_file.txt")
        try "hello nested".write(to: file, atomically: true, encoding: .utf8)

        // Collect events with timeout — may be .created or .directoryChanged
        // depending on the volume type and FSEvents coalescing behavior.
        var events: [DirectoryWatcher.FileEvent] = []
        let deadline = ContinuousClock.now + .seconds(3)
        for await event in stream {
            events.append(event)
            if ContinuousClock.now >= deadline || events.count >= 1 { break }
        }

        await watcher.stop()

        #expect(!events.isEmpty, "Should detect at least one event for subdirectory file creation")

        // The event should reference either the file directly (.created) or
        // a directory (.directoryChanged) — both are valid depending on
        // the volume's FSEvents behavior. On APFS, we typically get .created;
        // on external/non-APFS volumes, we may get .directoryChanged for the
        // parent or the subdirectory.
        let firstEvent = events[0]
        switch firstEvent {
        case .created(let url):
            #expect(url.lastPathComponent == "nested_file.txt")
        case .directoryChanged:
            // Any directory-level event is acceptable — FSEvents may report
            // the parent directory or the changed subdirectory itself.
            break
        case .renamed:
            // A rename event is unlikely but acceptable — FSEvents may
            // combine create+rename in some edge cases.
            break
        }
    }
}
