import XCTest

/// Tests the Photos Library scan flow: source switching, scanning, and
/// Photos-specific UI elements in results.
///
/// Each test launches the app with `launchForPhotosUITesting()` or
/// `launchForUITesting()` depending on whether it needs the Photos
/// source pre-selected. The mock Photos scan in ``SessionStore``
/// returns canned data with `photos://asset/` URIs.
@MainActor
final class PhotosFlowTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Source Switching

    func testSourceSwitching_photosLibrarySelected() throws {
        // Launch in directory mode (default) to test switching.
        app.launchForUITesting(scenario: "pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))

        // The segmented source picker renders differently across macOS versions.
        // Try buttons, radio buttons, and segmented control children.
        let clicked = clickPhotosLibrarySegment()
        guard clicked else {
            XCTFail("'Photos Library' segment not found in source picker")
            return
        }

        // After selecting Photos Library, the directory list is replaced.
        // Verify via the summary text which changes to mention Photos Library.
        // Also look for the Photos content view's combined accessibility label.
        let photosContent = app.descendants(matching: .any).matching(
            NSPredicate(format: "label CONTAINS 'Photos Library'")
        ).firstMatch
        XCTAssertTrue(
            photosContent.waitForExistence(timeout: 5),
            "Photos Library content should appear after selecting Photos source"
        )

        // Start Scan should still be enabled (no directories needed for Photos).
        XCTAssertTrue(
            startScan.isEnabled,
            "Start Scan should be enabled for Photos Library scans"
        )
    }

    /// Try multiple element types to find and click "Photos Library" in the segmented picker.
    private func clickPhotosLibrarySegment() -> Bool {
        // Button (most common rendering)
        let btn = app.buttons["Photos Library"]
        if btn.exists { btn.click(); return true }
        // Radio button (macOS 26 Liquid Glass)
        let radio = app.radioButtons["Photos Library"]
        if radio.exists { radio.click(); return true }
        // Segmented control child by value
        let seg = app.segmentedControls.firstMatch
        if seg.exists {
            let child = seg.buttons["Photos Library"]
            if child.exists { child.click(); return true }
        }
        return false
    }

    // MARK: - Photos Happy Path

    func testPhotosHappyPath_launchToResults() throws {
        app.launchForPhotosUITesting(scenario: "photos-pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(
            app.waitForElement(startScan, timeout: 10),
            "Start Scan button should appear on Photos setup screen"
        )

        // Start the Photos scan.
        startScan.click()

        // Wait for results: "New Scan" appears when results load.
        let newScan = app.buttons["New Scan"]
        XCTAssertTrue(
            app.waitForElement(newScan, timeout: 15),
            "New Scan button should appear once Photos results load"
        )

        // Verify the comparison action bar is visible (pairs loaded).
        let keepA = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepA, timeout: 5),
            "Keep A button should be visible on Photos results screen"
        )
    }

    // MARK: - Photos Results: Toolbar Restrictions

    func testPhotosResults_noHTMLOrShellExport() throws {
        try navigateToPhotosResults()

        // The export menu should exist.
        let exportMenu = app.descendants(matching: .any).matching(
            identifier: "exportMenu"
        ).firstMatch
        XCTAssertTrue(
            app.waitForElement(exportMenu, timeout: 5),
            "Export menu should exist on Photos results screen"
        )

        // Open the export menu.
        exportMenu.click()

        // JSON and CSV export should be available.
        let jsonExport = app.menuItems["Export as JSON…"]
        let csvExport = app.menuItems["Export as CSV…"]
        // HTML and Shell should NOT be available for Photos scans.
        let htmlExport = app.menuItems["Export as HTML Report…"]
        let shellExport = app.menuItems["Export as Shell Script…"]

        // Give menu items a moment to populate.
        _ = jsonExport.waitForExistence(timeout: 3)

        XCTAssertFalse(
            htmlExport.exists,
            "HTML Report export should be hidden for Photos scans"
        )
        XCTAssertFalse(
            shellExport.exists,
            "Shell Script export should be hidden for Photos scans"
        )

        // Dismiss menu by pressing Escape.
        app.typeKey(.escape, modifierFlags: [])
    }

    // MARK: - Photos Inspector: Labels

    func testPhotosInspector_showsPhotosLabels() throws {
        try navigateToPhotosResults()

        // "Reveal in Photos" should appear instead of "Reveal in Finder"
        // for Photos Library assets. This is the most reliable indicator
        // that Photos-specific inspector elements are active.
        let revealButton = app.buttons["Reveal in Photos"]
        XCTAssertTrue(
            revealButton.waitForExistence(timeout: 5),
            "'Reveal in Photos' button should appear for Photos Library assets"
        )

        // The filesystem "Reveal" button should NOT exist for Photos assets.
        let filesystemReveal = app.buttons["Reveal"]
        XCTAssertFalse(
            filesystemReveal.exists,
            "Filesystem 'Reveal' button should not appear for Photos assets"
        )
    }

    // MARK: - Photos Cancel Mid-Scan

    func testPhotosCancelMidScan_returnsToConfiguration() throws {
        app.launchForPhotosUITesting(scenario: "slow-photos")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        // Wait for the progress screen — cancel button should appear.
        let cancelButton = app.buttons["Cancel Scan"]
        XCTAssertTrue(
            app.waitForElement(cancelButton, timeout: 10),
            "Cancel Scan button should appear during Photos scanning"
        )

        // Cancel the scan.
        cancelButton.click()

        // Should return to configuration screen.
        let returnedToSetup = app.buttons["Start Scan"].waitForExistence(timeout: 10)
        XCTAssertTrue(
            returnedToSetup,
            "Should return to configuration screen after cancelling Photos scan"
        )
    }

    // MARK: - Photos Progress: No Pause Button

    func testPhotosProgress_noPauseButton() throws {
        app.launchForPhotosUITesting(scenario: "slow-photos")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))
        startScan.click()

        // Wait for progress screen.
        let cancelButton = app.buttons["Cancel Scan"]
        XCTAssertTrue(
            app.waitForElement(cancelButton, timeout: 10),
            "Cancel Scan should appear"
        )

        // Pause/Resume should NOT exist for Photos scans.
        let pauseButton = app.buttons["Pause"]
        let resumeButton = app.buttons["Resume"]
        XCTAssertFalse(
            pauseButton.exists,
            "Pause button should not exist for Photos Library scans"
        )
        XCTAssertFalse(
            resumeButton.exists,
            "Resume button should not exist for Photos Library scans"
        )

        // Clean up: cancel the scan.
        cancelButton.click()
        _ = app.buttons["Start Scan"].waitForExistence(timeout: 10)
    }

    // MARK: - Photos Cache Settings

    func testPhotosCacheSettings_sectionVisible() throws {
        app.launchForPhotosUITesting(scenario: "photos-pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        // Wait for the setup screen.
        let startScan = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScan, timeout: 10))

        // Open Settings via keyboard shortcut.
        app.typeKey(",", modifierFlags: .command)

        // Settings opens on the General tab. Navigate to the Cache tab.
        let cacheTab = app.buttons["Cache"]
        if !cacheTab.waitForExistence(timeout: 5) {
            // Fallback: try as toolbar button or radio button
            let cacheRadio = app.radioButtons["Cache"]
            guard cacheRadio.waitForExistence(timeout: 3) else {
                XCTFail("Cache tab not found in Settings — Cmd+, may not have opened Settings")
                return
            }
            cacheRadio.click()
        } else {
            cacheTab.click()
        }

        // Look for "Photos Library Cache" section or "Clear Photos DB" button.
        let clearPhotosButton = app.buttons["Clear Photos DB"]
        XCTAssertTrue(
            clearPhotosButton.waitForExistence(timeout: 5),
            "Photos Library Cache section should be visible in Cache settings tab"
        )
    }

    // MARK: - Helpers

    /// Navigate from launch through scan to the Photos results screen.
    private func navigateToPhotosResults() throws {
        app.launchForPhotosUITesting(scenario: "photos-pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScan = app.buttons["Start Scan"]
        guard app.waitForElement(startScan, timeout: 10) else {
            XCTFail("Start Scan button did not appear")
            return
        }
        startScan.click()

        let newScan = app.buttons["New Scan"]
        guard app.waitForElement(newScan, timeout: 15) else {
            XCTFail("Photos results screen did not load (New Scan button missing)")
            return
        }
    }
}
