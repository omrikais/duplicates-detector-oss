import AppIntents
import Foundation

/// Shortcuts intent that retrieves the most recent scan results.
///
/// Returns a `LastScanEntity` with summary information and the top 5 pairs.
/// If no scan history exists, returns nil with a descriptive dialog.
struct GetLastScanResultsIntent: AppIntent {
    nonisolated(unsafe) static var title: LocalizedStringResource = "Get Last Scan Results"
    nonisolated(unsafe) static var description = IntentDescription(
        "Get the results from the most recent duplicate scan.",
        categoryName: "History"
    )

    func perform() async throws -> some ReturnsValue<LastScanEntity?> & ProvidesDialog {
        guard let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() else {
            return .result(value: nil, dialog: "No scans found. Run a scan first.")
        }

        let entries = try await registry.listEntries()
        guard let entry = entries.first else {
            return .result(value: nil, dialog: "No scans found. Run a scan first.")
        }

        // Try to load the envelope for top pairs.
        var topPairs: [PairSummaryEntity] = []
        if let envelopeData = try? await registry.loadEnvelopeData(entry.id) {
            if let envelope = try? CLIDecoder.shared.decode(ScanEnvelope.self, from: envelopeData) {
                switch envelope.content {
                case .pairs(let pairs):
                    topPairs = Array(pairs.prefix(5)).map {
                        PairSummaryEntity(fileA: $0.fileA, fileB: $0.fileB, score: $0.score)
                    }
                case .groups(let groups):
                    // Flatten group pairs, sort by score descending, take top 5.
                    let sorted = groups.flatMap(\.pairs).sorted { $0.score > $1.score }
                    topPairs = Array(sorted.prefix(5)).map {
                        PairSummaryEntity(fileA: $0.fileA, fileB: $0.fileB, score: $0.score)
                    }
                }
            }
        }

        let lastScan = LastScanEntity(
            pairCount: entry.pairCount,
            scanDate: entry.createdAt,
            directories: entry.directories,
            mode: entry.mode.rawValue,
            topPairs: topPairs
        )

        let dirNames = entry.directories.map { ($0 as NSString).lastPathComponent }.joined(separator: ", ")
        return .result(
            value: lastScan,
            dialog: "Found \(entry.pairCount) duplicate pairs in \(dirNames)."
        )
    }
}
