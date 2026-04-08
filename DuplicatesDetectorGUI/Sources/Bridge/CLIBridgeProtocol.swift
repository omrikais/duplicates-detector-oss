import Foundation
import Subprocess

/// Protocol abstracting the CLI bridge surface used by production consumers.
///
/// Enables mock injection for UI tests while keeping ``CLIBridge`` as the
/// concrete implementation for production builds. Only methods actually called
/// by ``SessionStore``, views, and other production consumers are included.
protocol CLIBridgeProtocol: Actor, Sendable {

    // MARK: - Binary Location

    /// Path to the CLI binary, set after locating it.
    var binaryPath: String? { get }

    // MARK: - Dependency Validation

    /// Check availability of all required tools.
    func validateDependencies(
        userConfiguredPath: String?,
        refreshShellEnvironment: Bool
    ) async -> DependencyStatus

    // MARK: - Scan

    /// Run a scan and stream progress events, concluding with the result.
    func runScan(config: ScanConfig) -> AsyncThrowingStream<CLIOutput, any Error>

    /// Cancel the currently running subprocess.
    func cancelCurrentTask()

    // MARK: - Session Management

    /// List saved scan sessions as structured data.
    func listSessionsJSON() async -> [SessionInfo]?

    /// Delete a specific saved scan session.
    func deleteSession(_ sessionId: String) async

    // MARK: - Export & Undo

    /// Generate an undo script from an action log file.
    func generateUndoScript(logPath: String) async throws -> String

    /// Export scan results in a specific format using the CLI's replay pipeline.
    func exportAsFormat(
        envelopePath: String,
        format: String,
        outputPath: String,
        keep: String?,
        embedThumbnails: Bool,
        group: Bool,
        ignoreFile: String?
    ) async throws

    // MARK: - Installer Support

    /// The resolved shell environment for subprocess calls.
    func resolvedEnvironment() async -> Environment

    /// The Python interpreter path used by the CLI entry-point.
    func cliPythonPath() -> String?

    // MARK: - Configuration

    /// Remove the persisted manual CLI override.
    func clearPersistedUserConfiguredPath()

    /// Whether the app bundle contains an embedded CLI.
    nonisolated func hasBundledCLI() -> Bool

    /// Kill any orphaned CLI subprocess left behind by a previous crash.
    func cleanupOrphanedProcess()
}

// MARK: - Default Parameter Convenience Overloads

extension CLIBridgeProtocol {

    /// Convenience: validate dependencies with default arguments.
    func validateDependencies() async -> DependencyStatus {
        await validateDependencies(userConfiguredPath: nil, refreshShellEnvironment: false)
    }

    /// Convenience: validate dependencies with only `userConfiguredPath`.
    func validateDependencies(userConfiguredPath: String?) async -> DependencyStatus {
        await validateDependencies(userConfiguredPath: userConfiguredPath, refreshShellEnvironment: false)
    }

    /// Convenience: validate dependencies with only `refreshShellEnvironment`.
    func validateDependencies(refreshShellEnvironment: Bool) async -> DependencyStatus {
        await validateDependencies(userConfiguredPath: nil, refreshShellEnvironment: refreshShellEnvironment)
    }
}
