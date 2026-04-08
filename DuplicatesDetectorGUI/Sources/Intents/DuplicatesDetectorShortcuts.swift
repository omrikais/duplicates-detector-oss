import AppIntents
import Foundation

/// Registers app intents with the Shortcuts system and provides Siri phrases.
///
/// `sharedRegistry` must be set at app startup before any intents execute.
/// For intents that run before the UI has launched, `resolvedRegistry`
/// lazily creates a standalone registry so history queries always succeed.
public struct DuplicatesDetectorShortcuts: AppShortcutsProvider {
    /// Shared session registry instance. Set by the app at startup so intents
    /// can query scan history without creating their own registry.
    /// `nonisolated(unsafe)` because App Intents run off the main actor,
    /// but `SessionRegistry` is itself an actor (thread-safe).
    public nonisolated(unsafe) static var sharedRegistry: SessionRegistry?

    /// Fallback registry for intents that execute before app startup completes.
    private nonisolated(unsafe) static var _fallbackRegistry: SessionRegistry?

    /// Protects `_fallbackRegistry` creation against concurrent intent invocations.
    private static let _lock = NSLock()

    /// Returns the shared registry, or lazily creates a standalone one with
    /// the login-shell XDG path resolved so Finder-launched intents read
    /// the same session directory as the GUI.
    static func resolvedRegistry() async -> SessionRegistry? {
        if let sharedRegistry { return sharedRegistry }
        // Use scoped withLock (async-safe) to check-and-assign atomically.
        // The registry is assigned before the lock releases so concurrent
        // callers will find _fallbackRegistry already set.
        let registry = _lock.withLock { () -> SessionRegistry? in
            if let existing = _fallbackRegistry { return existing }
            let newRegistry = SessionRegistry()
            _fallbackRegistry = newRegistry
            return newRegistry
        }
        guard let registry else { return nil }
        let dataBase = await ShellEnvironmentResolver.shared.dataBaseDirectory()
        await registry.resolveStorageDirectory(dataBase: dataBase)
        return registry
    }

    public static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ScanDirectoryIntent(),
            phrases: [
                "Scan for duplicates with \(.applicationName)",
                "Find duplicate files with \(.applicationName)",
                "Check for duplicates in \(.applicationName)",
            ],
            shortTitle: "Scan for Duplicates",
            systemImageName: "doc.on.doc"
        )

        AppShortcut(
            intent: GetLastScanResultsIntent(),
            phrases: [
                "Get last scan results from \(.applicationName)",
                "Show recent duplicates from \(.applicationName)",
            ],
            shortTitle: "Last Scan Results",
            systemImageName: "clock.arrow.circlepath"
        )

        AppShortcut(
            intent: GetDuplicateCountIntent(),
            phrases: [
                "How many duplicates did \(.applicationName) find",
                "Show duplicate count from \(.applicationName)",
            ],
            shortTitle: "Duplicate Count",
            systemImageName: "number"
        )

        AppShortcut(
            intent: OpenScanResultsIntent(),
            phrases: [
                "Open scan results in \(.applicationName)",
                "Show results in \(.applicationName)",
            ],
            shortTitle: "Open Results",
            systemImageName: "arrow.right.circle"
        )
    }
}
