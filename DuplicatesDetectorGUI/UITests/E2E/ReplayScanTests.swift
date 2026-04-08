import XCTest

/// E2E tests that replay a pre-recorded JSON envelope through the GUI.
///
/// These tests verify the replay flow works end-to-end without needing
/// real media or ffmpeg. The envelope fixture (`envelope-pairs.json`)
/// is copied to a temp location and opened via environment variable.
///
/// **Note:** On macOS 26 (Tahoe) beta, the SwiftUI `Window` scene may
/// not expose its window in the XCUITest accessibility hierarchy. Tests
/// guard against this with `waitForMainWindow()` and `XCTSkipUnless`.
@MainActor
final class ReplayScanTests: XCTestCase {
    let app = XCUIApplication()
    var tempDir: URL?

    override func setUpWithError() throws {
        continueAfterFailure = false
        do {
            try TestMedia.requireCLI()
        } catch TestMedia.TestMediaError.cliNotFound {
            throw XCTSkip("duplicates-detector CLI not found — skipping replay tests")
        }
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("dd-replay-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir!, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let dir = tempDir {
            try? FileManager.default.removeItem(at: dir)
        }
    }

    func testReplayFromFixture_showsResults() throws {
        guard let dir = tempDir else { throw XCTSkip("No temp directory") }

        // Create real temp files so the session reducer's file-status checks
        // don't mark these paths as .probablySolved (which hides Keep buttons).
        let clipA = dir.appendingPathComponent("clip_a.mp4")
        let clipB = dir.appendingPathComponent("clip_b.mp4")
        FileManager.default.createFile(atPath: clipA.path, contents: Data(repeating: 0, count: 1024))
        FileManager.default.createFile(atPath: clipB.path, contents: Data(repeating: 0, count: 1024))

        // Locate the fixture in the UI test bundle.
        // The fixture is bundled with the main test target. For E2E tests,
        // we create a minimal envelope JSON inline since UI test bundles
        // don't carry unit test resources.
        let fixtureURL = dir.appendingPathComponent("envelope-pairs.json")
        let envelope = """
        {
          "version": "1.5.0",
          "generated_at": "2025-01-15T10:30:00+00:00",
          "args": {
            "directories": ["\(dir.path)"],
            "threshold": 50,
            "content": false,
            "keep": "newest",
            "action": "delete",
            "group": false,
            "sort": "score",
            "mode": "video",
            "embed_thumbnails": false
          },
          "stats": {
            "files_scanned": 4,
            "files_after_filter": 4,
            "total_pairs_scored": 6,
            "pairs_above_threshold": 1,
            "groups_count": null,
            "space_recoverable": 1048576,
            "scan_time": 0.1,
            "extract_time": 0.5,
            "filter_time": 0.001,
            "content_hash_time": 0.0,
            "scoring_time": 0.2,
            "total_time": 0.9
          },
          "pairs": [
            {
              "file_a": "\(clipA.path)",
              "file_b": "\(clipB.path)",
              "score": 85,
              "breakdown": {
                "filename": 45.0,
                "duration": 28.5,
                "resolution": 10.0,
                "filesize": 5.0
              },
              "detail": {
                "filename": [0.9, 50],
                "duration": [0.95, 30],
                "resolution": [1.0, 10],
                "filesize": [0.5, 10]
              },
              "file_a_metadata": {
                "file_size": 1048576,
                "duration": 10.0,
                "width": 1920,
                "height": 1080,
                "codec": "h264",
                "bitrate": 3500000,
                "framerate": 29.97,
                "audio_channels": 2,
                "mtime": 1705312200.0
              },
              "file_b_metadata": {
                "file_size": 1024000,
                "duration": 10.1,
                "width": 1920,
                "height": 1080,
                "codec": "h264",
                "bitrate": 3400000,
                "framerate": 29.97,
                "audio_channels": 2,
                "mtime": 1705312300.0
              }
            }
          ]
        }
        """
        try envelope.write(to: fixtureURL, atomically: true, encoding: .utf8)

        // Launch app with replay file path
        app.launchEnvironment["DD_UI_TEST_REPLAY"] = fixtureURL.path
        app.launch()

        try XCTSkipUnless(
            app.waitForMainWindow(),
            "macOS 26: Window scene not in accessibility hierarchy"
        )

        // Replay should bypass configuration and show results directly.
        // Wait for results screen indicators.
        let newScanButton = app.buttons["New Scan"]
        XCTAssertTrue(
            app.waitForElement(newScanButton, timeout: 30),
            "Results screen should appear after replay loads"
        )

        // Verify the pair is shown - at least a Keep button should be visible.
        let keepA = app.buttons["Keep A"]
        let keepB = app.buttons["Keep B"]
        let hasPair = keepA.waitForExistence(timeout: 5) || keepB.waitForExistence(timeout: 2)
        XCTAssertTrue(hasPair, "At least one pair should be displayed from replay data")
    }
}
