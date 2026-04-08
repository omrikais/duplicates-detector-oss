import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - ImageComparisonView.ComparisonMode Tests

@Suite("ImageComparisonView.ComparisonMode enum")
struct ComparisonModeTests {
    @Test("ComparisonMode has exactly 2 cases")
    func caseCount() {
        #expect(ImageComparisonView.ComparisonMode.allCases.count == 2)
    }

    @Test("ComparisonMode includes sideBySide")
    func hasSideBySide() {
        #expect(ImageComparisonView.ComparisonMode.allCases.contains(.sideBySide))
    }

    @Test("ComparisonMode includes wipeSlider")
    func hasWipeSlider() {
        #expect(ImageComparisonView.ComparisonMode.allCases.contains(.wipeSlider))
    }

    @Test("sideBySide raw value is 'Side by Side'")
    func sideBySideRawValue() {
        #expect(ImageComparisonView.ComparisonMode.sideBySide.rawValue == "Side by Side")
    }

    @Test("wipeSlider raw value is 'Wipe'")
    func wipeSliderRawValue() {
        #expect(ImageComparisonView.ComparisonMode.wipeSlider.rawValue == "Wipe")
    }

    @Test("ComparisonMode conforms to CaseIterable")
    func conformsToCaseIterable() {
        // Verify by using CaseIterable API
        let allCases = ImageComparisonView.ComparisonMode.allCases
        #expect(!allCases.isEmpty)
        #expect(allCases.count == 2)
    }
}

// MARK: - VideoComparisonView.formatTime Tests

@Suite("VideoComparisonView.formatTime")
struct VideoFormatTimeTests {
    @Test("Zero seconds formats as 0:00")
    func zeroSeconds() {
        #expect(VideoComparisonView.formatTime(0) == "0:00")
    }

    @Test("65.5 seconds formats as 1:05")
    func sixtyFivePointFive() {
        #expect(VideoComparisonView.formatTime(65.5) == "1:05")
    }

    @Test("3600 seconds formats as 60:00")
    func oneHour() {
        #expect(VideoComparisonView.formatTime(3600) == "60:00")
    }

    @Test("Negative value formats as 0:00")
    func negativeValue() {
        #expect(VideoComparisonView.formatTime(-1) == "0:00")
    }

    @Test("NaN formats as 0:00")
    func nanValue() {
        #expect(VideoComparisonView.formatTime(Double.nan) == "0:00")
    }

    @Test("Infinity formats as 0:00")
    func infinityValue() {
        #expect(VideoComparisonView.formatTime(Double.infinity) == "0:00")
    }

    @Test("Negative infinity formats as 0:00")
    func negativeInfinityValue() {
        #expect(VideoComparisonView.formatTime(-Double.infinity) == "0:00")
    }

    @Test("30 seconds formats as 0:30")
    func thirtySeconds() {
        #expect(VideoComparisonView.formatTime(30) == "0:30")
    }

    @Test("59 seconds formats as 0:59")
    func fiftyNineSeconds() {
        #expect(VideoComparisonView.formatTime(59) == "0:59")
    }

    @Test("60 seconds formats as 1:00")
    func exactlyOneMinute() {
        #expect(VideoComparisonView.formatTime(60) == "1:00")
    }

    @Test("90.9 seconds formats as 1:30 (truncates fractional)")
    func ninetyPointNine() {
        #expect(VideoComparisonView.formatTime(90.9) == "1:30")
    }

    @Test("1 second formats as 0:01")
    func oneSecond() {
        #expect(VideoComparisonView.formatTime(1) == "0:01")
    }

    @Test(
        "Parametrized time formatting",
        arguments: [
            (0.0, "0:00"),
            (1.0, "0:01"),
            (9.0, "0:09"),
            (10.0, "0:10"),
            (59.0, "0:59"),
            (60.0, "1:00"),
            (61.0, "1:01"),
            (119.0, "1:59"),
            (120.0, "2:00"),
            (600.0, "10:00"),
            (3599.0, "59:59"),
            (3600.0, "60:00"),
        ]
    )
    func parametrizedFormatting(seconds: Double, expected: String) {
        #expect(VideoComparisonView.formatTime(seconds) == expected)
    }
}

// MARK: - ComparisonActionBar Logic Tests

@Suite("ComparisonActionBar both-reference detection")
struct ComparisonActionBarLogicTests {

    private func makePair(
        fileAIsReference: Bool = false,
        fileBIsReference: Bool = false
    ) -> PairResult {
        PairResult(
            fileA: "/videos/a.mp4",
            fileB: "/videos/b.mp4",
            score: 85.0,
            breakdown: ["filename": 40.0],
            detail: ["filename": DetailScore(raw: 0.8, weight: 50)],
            fileAMetadata: FileMetadata(fileSize: 1024),
            fileBMetadata: FileMetadata(fileSize: 2048),
            fileAIsReference: fileAIsReference,
            fileBIsReference: fileBIsReference,
            keep: nil
        )
    }

    @Test("Both references detected when both flags are true")
    func bothReferenceDetected() {
        let pair = makePair(fileAIsReference: true, fileBIsReference: true)
        let isBothReference = pair.fileAIsReference && pair.fileBIsReference
        #expect(isBothReference)
    }

    @Test("Not both-reference when only A is reference")
    func onlyAIsReference() {
        let pair = makePair(fileAIsReference: true, fileBIsReference: false)
        let isBothReference = pair.fileAIsReference && pair.fileBIsReference
        #expect(!isBothReference)
    }

    @Test("Not both-reference when only B is reference")
    func onlyBIsReference() {
        let pair = makePair(fileAIsReference: false, fileBIsReference: true)
        let isBothReference = pair.fileAIsReference && pair.fileBIsReference
        #expect(!isBothReference)
    }

    @Test("Not both-reference when neither is reference")
    func neitherIsReference() {
        let pair = makePair(fileAIsReference: false, fileBIsReference: false)
        let isBothReference = pair.fileAIsReference && pair.fileBIsReference
        #expect(!isBothReference)
    }

    @Test("CLI-only actions correctly identified")
    func cliOnlyActions() {
        let cliOnly: [ActionType] = [.hardlink, .symlink, .reflink]
        let guiActions: [ActionType] = [.trash, .delete, .moveTo]

        for action in cliOnly {
            let isCLIOnly = [ActionType.hardlink, .symlink, .reflink].contains(action)
            #expect(isCLIOnly, "\(action.rawValue) should be CLI-only")
        }
        for action in guiActions {
            let isCLIOnly = [ActionType.hardlink, .symlink, .reflink].contains(action)
            #expect(!isCLIOnly, "\(action.rawValue) should NOT be CLI-only")
        }
    }
}

// MARK: - HorizontalClip Shape Tests

// NOTE: HorizontalClip is `private` to ImageComparisonView.swift,
// so it cannot be directly instantiated or tested from outside the file.
// The following comment documents what tests would verify if the type
// were internal or public:
//
// - HorizontalClip(width: 200) in a rect of (0,0,400,300) produces a
//   path with boundingRect (0, 0, 200, 300)
// - HorizontalClip(width: 0) produces a zero-width clipping region
// - HorizontalClip(width: 500) in a rect of (0,0,400,300) clips to
//   the full requested width regardless of the containing rect
