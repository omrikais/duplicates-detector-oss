import XCTest

/// Visual regression tests that capture full-screen screenshots from the real app.
///
/// Unlike unit-level snapshot tests (which use `NSHostingController` offscreen),
/// these tests launch the actual app via XCUITest, giving SwiftUI a real window
/// scene. This is required for Liquid Glass effects and materials to render —
/// they produce transparent output in offscreen captures (see pointfreeco/swift-
/// snapshot-testing#1031).
///
/// Each test uses a mock scenario for deterministic data and captures key screens
/// via `XCUIScreenshot`. Screenshots are compared against reference PNGs stored
/// alongside this file in `__Screenshots__/`.
///
/// **First run**: reference images are recorded automatically and the test fails
/// with a message indicating the snapshot was recorded. Re-run to assert.
///
/// **To update references**: delete the corresponding PNG in `__Screenshots__/`
/// and re-run.
@MainActor
final class ScreenSnapshotTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Configuration Screen

    func testConfigurationScreen() throws {
        app.launchForUITesting(scenario: "pairs")
        XCTAssertTrue(app.waitForMainWindow())
        XCTAssertTrue(app.waitForElement(app.buttons["Start Scan"], timeout: 10))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "configuration")
    }

    // MARK: - Progress Screen

    func testProgressScreen() throws {
        app.launchForUITesting(scenario: "slow-pairs")
        XCTAssertTrue(app.waitForMainWindow())
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        let cancelButton = app.buttons["Cancel Scan"]
        XCTAssertTrue(app.waitForElement(cancelButton, timeout: 10))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "progress")

        cancelButton.click()
    }

    // MARK: - Results Screen (Pairs)

    func testResultsScreen_pairs() throws {
        app.launchForUITesting(scenario: "pairs")
        XCTAssertTrue(app.waitForMainWindow())
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        XCTAssertTrue(app.waitForElement(app.buttons["Keep A"], timeout: 15))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "results-pairs")
    }

    // MARK: - Results Screen (Groups)

    func testResultsScreen_groups() throws {
        app.launchForUITesting(scenario: "groups")
        XCTAssertTrue(app.waitForMainWindow())
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        XCTAssertTrue(app.waitForElement(app.buttons["New Scan"], timeout: 15))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "results-groups")
    }

    // MARK: - Empty Results Screen

    func testEmptyResultsScreen() throws {
        app.launchForUITesting(scenario: "empty")
        XCTAssertTrue(app.waitForMainWindow())
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        XCTAssertTrue(app.waitForElement(app.buttons["New Scan"], timeout: 15))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "results-empty")
    }

    // MARK: - Error Screen

    func testErrorScreen() throws {
        app.launchForUITesting(scenario: "error")
        XCTAssertTrue(app.waitForMainWindow())
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        XCTAssertTrue(app.waitForElement(app.buttons["Back to Configuration"], timeout: 15))
        Thread.sleep(forTimeInterval: 0.5)

        assertScreenshot(named: "error")
    }

    // MARK: - Screenshot Helper

    /// Compare the current app window against a reference screenshot.
    ///
    /// On first run (no reference exists), the screenshot is saved and the test
    /// fails with a record message. On subsequent runs, it compares pixel data
    /// and fails if they differ.
    private func assertScreenshot(
        named name: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let screenshot = app.windows.firstMatch.screenshot()
        let actual = screenshot.image

        // Reference directory: stored under ~/Library/Developer/DuplicatesDetector/
        // because the XCUITest runner is sandboxed and can't write to external
        // volumes or the source tree. References persist across test runs on the
        // same machine.
        let home = FileManager.default.homeDirectoryForCurrentUser
        let refDir = home
            .appendingPathComponent("Library/Developer/DuplicatesDetector/Screenshots")
            .appendingPathComponent("ScreenSnapshotTests")
        let refURL = refDir.appendingPathComponent("\(name).png")

        // Always attach the screenshot to the test result for inspection
        let attachment = XCTAttachment(image: actual)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)

        if FileManager.default.fileExists(atPath: refURL.path) {
            // Compare against reference with tolerance for subpixel antialiasing.
            guard let refData = try? Data(contentsOf: refURL),
                  let refImage = NSImage(data: refData)
            else {
                XCTFail("Failed to load reference image at \(refURL.path)", file: file, line: line)
                return
            }

            let result = compareImages(actual, refImage)
            switch result {
            case .match:
                break
            case .sizeMismatch(let actualSize, let refSize):
                let failURL = refDir.appendingPathComponent("\(name)_FAIL.png")
                savePNG(actual, to: failURL)
                XCTFail(
                    "Screenshot \"\(name)\" size mismatch: "
                        + "\(actualSize) vs reference \(refSize). "
                        + "Delete the reference and re-run to update.",
                    file: file, line: line
                )
            case .contentMismatch(let changedPercent):
                let failURL = refDir.appendingPathComponent("\(name)_FAIL.png")
                savePNG(actual, to: failURL)
                XCTFail(
                    "Screenshot \"\(name)\" differs from reference "
                        + "(\(String(format: "%.1f", changedPercent))% pixels changed). "
                        + "Failure image saved to: \(failURL.path). "
                        + "Delete the reference and re-run to update.",
                    file: file, line: line
                )
            }
        } else {
            // Record new reference
            try? FileManager.default.createDirectory(at: refDir, withIntermediateDirectories: true)
            savePNG(actual, to: refURL)
            XCTFail(
                "No reference found. Recorded screenshot to: \(refURL.path). "
                    + "Re-run to assert against this reference.",
                file: file,
                line: line
            )
        }
    }

    // MARK: - Image Comparison

    private enum ComparisonResult {
        case match
        case sizeMismatch(actual: NSSize, reference: NSSize)
        /// Percentage of pixels that differ beyond the tolerance.
        case contentMismatch(changedPercent: Double)
    }

    /// Compare two images with tolerance for subpixel antialiasing.
    ///
    /// The title bar (top 52px) is excluded because the Liquid Glass window
    /// chrome renders non-deterministically between runs.
    ///
    /// - `channelThreshold`: max per-channel difference to consider identical (default 5)
    /// - `pixelThreshold`: max percentage of changed pixels to consider a match (default 2%)
    /// - `titleBarHeight`: rows to skip from the top (default 52)
    private func compareImages(
        _ actual: NSImage,
        _ reference: NSImage,
        channelThreshold: Int = 5,
        pixelThreshold: Double = 2.0,
        titleBarHeight: Int = 52
    ) -> ComparisonResult {
        guard let actualBitmap = bitmapRep(for: actual),
              let refBitmap = bitmapRep(for: reference)
        else { return .contentMismatch(changedPercent: 100) }

        let actualSize = NSSize(
            width: actualBitmap.pixelsWide, height: actualBitmap.pixelsHigh
        )
        let refSize = NSSize(
            width: refBitmap.pixelsWide, height: refBitmap.pixelsHigh
        )
        guard actualSize == refSize else {
            return .sizeMismatch(actual: actualSize, reference: refSize)
        }

        let width = actualBitmap.pixelsWide
        let height = actualBitmap.pixelsHigh
        let startY = min(titleBarHeight, height)
        let totalPixels = width * (height - startY)
        guard totalPixels > 0 else { return .match }

        var changedPixels = 0
        for y in startY..<height {
            for x in 0..<width {
                let actualColor = actualBitmap.colorAt(x: x, y: y)
                let refColor = refBitmap.colorAt(x: x, y: y)
                guard let ac = actualColor, let rc = refColor else {
                    changedPixels += 1
                    continue
                }
                let dr = abs(Int(ac.redComponent * 255) - Int(rc.redComponent * 255))
                let dg = abs(Int(ac.greenComponent * 255) - Int(rc.greenComponent * 255))
                let db = abs(Int(ac.blueComponent * 255) - Int(rc.blueComponent * 255))
                if dr > channelThreshold || dg > channelThreshold || db > channelThreshold {
                    changedPixels += 1
                }
            }
        }

        let changedPercent = Double(changedPixels) / Double(totalPixels) * 100
        if changedPercent > pixelThreshold {
            return .contentMismatch(changedPercent: changedPercent)
        }
        return .match
    }

    private func bitmapRep(for image: NSImage) -> NSBitmapImageRep? {
        guard let tiff = image.tiffRepresentation else { return nil }
        return NSBitmapImageRep(data: tiff)
    }

    private func savePNG(_ image: NSImage, to url: URL) {
        guard let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:])
        else { return }
        do {
            try png.write(to: url)
        } catch {
            NSLog("ScreenSnapshotTests: failed to write \(url.path): \(error)")
        }
    }
}
