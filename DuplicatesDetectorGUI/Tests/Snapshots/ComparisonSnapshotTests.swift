import AppKit
import SnapshotTesting
import SwiftUI
import Testing

@testable import DuplicatesDetector

@Suite("Comparison Component Snapshots")
@MainActor
struct ComparisonSnapshotTests {

    // MARK: - Score Ring Tests

    @Test("Score ring at 95 (high)")
    func scoreRingHigh() {
        let view = ScoreRing(score: 95, size: .regular)
            .padding()
        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 100, height: 100)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 100, height: 100)))
    }

    @Test("Score ring at 60 (medium)")
    func scoreRingMedium() {
        let view = ScoreRing(score: 60, size: .regular)
            .padding()
        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 100, height: 100)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 100, height: 100)))
    }

    @Test("Score ring at 30 (low)")
    func scoreRingLow() {
        let view = ScoreRing(score: 30, size: .regular)
            .padding()
        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 100, height: 100)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 100, height: 100)))
    }

    // MARK: - Breakdown Bar Tests

    @Test("Breakdown bar with video weights")
    func breakdownBarVideo() {
        let view = BreakdownBar(
            breakdown: [
                "filename": 48.0,
                "duration": 29.5,
                "resolution": 10.0,
                "fileSize": 8.0,
            ],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            totalScore: 95.5
        )
        .frame(height: 24)
        .padding()

        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 400, height: 60)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 400, height: 60)))
    }

    // MARK: - Metadata Diff Table

    @Test("Metadata diff table with mixed values")
    func metadataDiffTable() {
        let metaA = FileMetadata(
            duration: 125.3, width: 1920, height: 1080, fileSize: 52_400_000,
            codec: "h264", bitrate: 5_000_000, framerate: 29.97, audioChannels: 2,
            mtime: 1_700_000_000.0
        )
        let metaB = FileMetadata(
            duration: 124.8, width: 3840, height: 2160, fileSize: 98_200_000,
            codec: "hevc", bitrate: 12_800_000, framerate: 29.97, audioChannels: 6,
            mtime: 1_699_913_600.0
        )
        let view = MetadataDiffTable(
            metaA: metaA, metaB: metaB,
            labelA: "vacation_2024.mp4", labelB: "vacation_2024_copy.mp4"
        )
        .frame(width: 600)
        .padding()

        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 640, height: 400)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 640, height: 400)))
    }

    // MARK: - Score Breakdown Detail

    @Test("Score breakdown detail panel")
    func scoreBreakdownDetail() {
        let view = ScoreBreakdownDetail(
            breakdown: [
                "filename": 48.0,
                "duration": 29.5,
                "resolution": 10.0,
                "fileSize": 8.0,
            ],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            totalScore: 95.5
        )
        .frame(width: 600)
        .padding()

        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 640, height: 300)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 640, height: 300)))
    }

    // MARK: - Full Comparison Panel

    @Test("Comparison panel with high score pair")
    func comparisonPanelHighScore() {
        let metaA = FileMetadata(
            duration: 125.3, width: 1920, height: 1080, fileSize: 52_400_000,
            codec: "h264", bitrate: 5_000_000, framerate: 29.97, audioChannels: 2,
            mtime: 1_700_000_000.0
        )
        let metaB = FileMetadata(
            duration: 124.8, width: 3840, height: 2160, fileSize: 98_200_000,
            codec: "hevc", bitrate: 12_800_000, framerate: 29.97, audioChannels: 6,
            mtime: 1_699_913_600.0
        )
        let pair = PairResult(
            fileA: "/Users/demo/Videos/vacation_2024.mp4",
            fileB: "/Users/demo/Videos/vacation_2024_copy.mp4",
            score: 95.5,
            breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            fileAMetadata: metaA, fileBMetadata: metaB,
            fileAIsReference: false, fileBIsReference: false, keep: "a"
        )

        let view = ComparisonPanel(
            pair: pair,
            scanMode: .video,
            activeAction: .trash,
            currentPairIndex: 0,
            totalFilteredPairs: 5,
            onKeepA: {},
            onKeepB: {},
            onPrevious: {},
            onSkip: {},
            onSkipAndIgnore: {}
        )

        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 700, height: 900)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 700, height: 900)))
    }

    // MARK: - Inspector Pane

    @Test("Inspector pane with video metadata")
    func inspectorPane() {
        let metaA = FileMetadata(
            duration: 125.3, width: 1920, height: 1080, fileSize: 52_400_000,
            codec: "h264", bitrate: 5_000_000, framerate: 29.97, audioChannels: 2,
            mtime: 1_700_000_000.0
        )
        let metaB = FileMetadata(
            duration: 124.8, width: 3840, height: 2160, fileSize: 98_200_000,
            codec: "hevc", bitrate: 12_800_000, framerate: 29.97, audioChannels: 6,
            mtime: 1_699_913_600.0
        )
        let pair = PairResult(
            fileA: "/Users/demo/Videos/vacation_2024.mp4",
            fileB: "/Users/demo/Videos/vacation_2024_copy.mp4",
            score: 95.5,
            breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            fileAMetadata: metaA, fileBMetadata: metaB,
            fileAIsReference: false, fileBIsReference: true, keep: "a"
        )

        let view = PairInspectorPane(
            pair: pair,
            activeAction: .trash,
            onAction: { _ in }
        )

        let controller = NSHostingController(rootView: view)
        controller.view.frame = NSRect(x: 0, y: 0, width: 320, height: 700)

        assertSnapshot(of: controller, as: .image(size: CGSize(width: 320, height: 700)))
    }
}
