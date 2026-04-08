import AppIntents
import Foundation

/// Shortcuts intent that returns the duplicate pair count from the last scan.
///
/// Returns 0 if no scan history exists.
struct GetDuplicateCountIntent: AppIntent {
    nonisolated(unsafe) static var title: LocalizedStringResource = "Show Duplicate Count"
    nonisolated(unsafe) static var description = IntentDescription(
        "Get the number of duplicate pairs found in the most recent scan.",
        categoryName: "History"
    )

    func perform() async throws -> some ReturnsValue<Int> & ProvidesDialog {
        guard let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() else {
            return .result(value: 0, dialog: "No scans found yet.")
        }

        let count = (try await registry.listEntries().first)?.pairCount ?? 0

        if count > 0 {
            return .result(value: count, dialog: "Found \(count) duplicate pairs.")
        } else {
            return .result(value: 0, dialog: "No duplicates found in the last scan.")
        }
    }
}
