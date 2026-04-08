import Foundation

/// Structured error carrier for display in the UI with category-specific
/// recovery guidance.
struct ErrorInfo: Equatable, Sendable {
    enum Category: Equatable, Sendable {
        case binaryNotFound
        case dependencyMissing
        case permissionDenied
        case directoryNotFound
        case noFilesFound
        case invalidConfiguration
        case cliCrash(code: Int32)
        case unknown
    }

    let message: String
    let category: Category
    let recoverySuggestion: String?

    /// Backward-compatible convenience initializer.
    init(message: String, category: Category = .unknown, recoverySuggestion: String? = nil) {
        self.message = message
        self.category = category
        self.recoverySuggestion = recoverySuggestion
    }

    /// Classify an error thrown by the CLI bridge into a structured ``ErrorInfo``.
    nonisolated static func classify(_ error: any Error) -> ErrorInfo {
        if let bridgeError = error as? CLIBridgeError {
            switch bridgeError {
            case .binaryNotFound:
                return ErrorInfo(
                    message: "The duplicates-detector CLI was not found.",
                    category: .binaryNotFound,
                    recoverySuggestion: "Install it with \"pip install duplicates-detector\" or check the binary path in Settings \u{2192} Advanced."
                )
            case .processExitedWithError(let code):
                return ErrorInfo(
                    message: "The scan process exited unexpectedly (code \(code)).",
                    category: .cliCrash(code: code),
                    recoverySuggestion: "Try running the scan again. If the problem persists, check that your directories are accessible and the CLI is up to date."
                )
            case .processExitedWithErrorMessage(let code, let stderr):
                return classifyStderr(stderr, code: code)
            case .emptyOutput:
                return ErrorInfo(
                    message: "The CLI produced no output.",
                    category: .unknown,
                    recoverySuggestion: "Try running the scan again."
                )
            }
        }
        return ErrorInfo(message: error.localizedDescription)
    }

    // MARK: - Category display

    /// SF Symbol icon name for the error screen.
    var systemImageName: String {
        switch category {
        case .binaryNotFound: "puzzlepiece.extension"
        case .dependencyMissing: "wrench.and.screwdriver"
        case .noFilesFound: "doc.questionmark"
        case .directoryNotFound: "folder.badge.questionmark"
        case .permissionDenied: "lock.shield"
        case .invalidConfiguration: "gearshape.triangle"
        case .cliCrash, .unknown: "exclamationmark.triangle"
        }
    }

    /// Human-readable title for the error screen.
    var displayTitle: String {
        switch category {
        case .binaryNotFound: "CLI Not Found"
        case .dependencyMissing: "Missing Dependency"
        case .noFilesFound: "No Files Found"
        case .directoryNotFound: "Directory Not Found"
        case .permissionDenied: "Permission Denied"
        case .invalidConfiguration: "Configuration Error"
        case .cliCrash: "Scan Failed"
        case .unknown: "Scan Error"
        }
    }

    /// Parse known error patterns from CLI stderr output.
    nonisolated static func classifyStderr(_ stderr: String, code: Int32) -> ErrorInfo {
        let lower = stderr.lowercased()

        if lower.contains("no such file or directory") || lower.contains("directory not found") {
            return ErrorInfo(
                message: stderr,
                category: .directoryNotFound,
                recoverySuggestion: "Check that the scan directory exists and the path is correct."
            )
        }
        if lower.contains("permission denied") {
            return ErrorInfo(
                message: stderr,
                category: .permissionDenied,
                recoverySuggestion: "Grant the app Full Disk Access in System Settings \u{2192} Privacy & Security, or choose a directory you have read access to."
            )
        }
        if lower.contains("no video files found") || lower.contains("no image files found")
            || lower.contains("no audio files found") || lower.contains("no media files found")
            || lower.contains("no document files found") || lower.contains("no files found")
        {
            return ErrorInfo(
                message: stderr,
                category: .noFilesFound,
                recoverySuggestion: "Check that the directory contains files matching the selected mode, or try a different scan mode."
            )
        }
        if lower.contains("not found") && (lower.contains("ffprobe") || lower.contains("ffmpeg")
            || lower.contains("fpcalc") || lower.contains("chromaprint"))
        {
            return ErrorInfo(
                message: stderr,
                category: .dependencyMissing,
                recoverySuggestion: "Install the missing tool. ffprobe/ffmpeg: \"brew install ffmpeg\". fpcalc: \"brew install chromaprint\"."
            )
        }
        if lower.contains("requires pdfminer") || (lower.contains("pdfminer") && lower.contains("not installed")) {
            return ErrorInfo(
                message: stderr,
                category: .dependencyMissing,
                recoverySuggestion: "Install pdfminer for document mode: pip install \"duplicates-detector[document]\""
            )
        }
        // Match CLI argparse "error:" at start of output or start of line — avoids
        // catching Python exception classes like "RuntimeError:", "ValueError:", etc.
        if lower.hasPrefix("error:") || lower.contains("\nerror:") {
            return ErrorInfo(
                message: stderr,
                category: .invalidConfiguration,
                recoverySuggestion: "Review your scan settings and try again."
            )
        }

        return ErrorInfo(
            message: stderr.isEmpty ? "The scan process exited unexpectedly (code \(code))." : stderr,
            category: .cliCrash(code: code),
            recoverySuggestion: "Try running the scan again. If the problem persists, check the CLI version and logs."
        )
    }
}
