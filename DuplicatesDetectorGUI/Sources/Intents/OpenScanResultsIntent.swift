import AppIntents
import Foundation

/// Shortcuts intent that opens the app and navigates to scan results.
///
/// Optionally accepts a specific scan history entry. If none is provided,
/// the app opens to its default state.
struct OpenScanResultsIntent: AppIntent {
    nonisolated(unsafe) static var title: LocalizedStringResource = "Open Scan Results"
    nonisolated(unsafe) static var description = IntentDescription(
        "Open the Duplicates Detector app and show scan results.",
        categoryName: "Navigation"
    )

    static let openAppWhenRun = true

    @Parameter(title: "Scan", optionsProvider: ScanHistoryOptionsProvider())
    var scan: ScanHistoryEntity?

    func perform() async throws -> some IntentResult {
        // Resolve which session to open: explicit parameter, or most recent.
        let sessionID: UUID?
        if let scan {
            sessionID = scan.id
        } else if let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() {
            sessionID = (try? await registry.listEntries().first)?.id
        } else {
            sessionID = nil
        }

        if let sessionID {
            await MainActor.run {
                NotificationCenter.default.post(
                    name: .openScanFromShortcut,
                    object: nil,
                    userInfo: ["sessionID": sessionID]
                )
            }
        }
        return .result()
    }
}

// MARK: - Options Provider

/// Provides recent scan history entries as parameter options.
struct ScanHistoryOptionsProvider: DynamicOptionsProvider {
    func results() async throws -> [ScanHistoryEntity] {
        guard let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() else { return [] }
        let entries = try await registry.listEntries()
        return Array(entries.prefix(10).map { ScanHistoryEntity(from: $0) })
    }
}

// MARK: - Notification Name

extension Notification.Name {
    /// Posted by `OpenScanResultsIntent` to navigate to a specific session.
    public static let openScanFromShortcut = Notification.Name("com.omrikaisari.DuplicatesDetector.openScanFromShortcut")
}
