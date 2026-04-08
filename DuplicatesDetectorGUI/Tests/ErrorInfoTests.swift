import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - classifyStderr

@Suite("ErrorInfo — classifyStderr")
struct ErrorInfoClassifyStderrTests {

    @Test("Recognizes permission denied")
    func permissionDenied() {
        let info = ErrorInfo.classifyStderr("Permission denied: /private/folder", code: 1)
        #expect(info.category == .permissionDenied)
        #expect(info.recoverySuggestion != nil)
    }

    @Test("Recognizes directory not found via 'No such file or directory'")
    func directoryNotFoundNoSuch() {
        let info = ErrorInfo.classifyStderr("No such file or directory: /missing/path", code: 1)
        #expect(info.category == .directoryNotFound)
        #expect(info.recoverySuggestion != nil)
    }

    @Test("Recognizes directory not found via 'directory not found'")
    func directoryNotFoundExplicit() {
        let info = ErrorInfo.classifyStderr("directory not found at /missing/path", code: 1)
        #expect(info.category == .directoryNotFound)
    }

    @Test(
        "Recognizes no files found variants",
        arguments: [
            "no video files found in /videos",
            "no image files found in /photos",
            "no audio files found in /music",
            "no files found in /empty",
            "no media files found in /media",
        ] as [String]
    )
    func noFilesFoundVariants(stderr: String) {
        let info = ErrorInfo.classifyStderr(stderr, code: 1)
        #expect(info.category == .noFilesFound)
        #expect(info.recoverySuggestion != nil)
    }

    @Test(
        "Recognizes missing dependency tools",
        arguments: [
            "Error: ffprobe not found on PATH",
            "Error: ffmpeg not found on PATH",
            "Error: fpcalc not found on PATH",
            "chromaprint: not found",
        ] as [String]
    )
    func dependencyMissing(stderr: String) {
        let info = ErrorInfo.classifyStderr(stderr, code: 1)
        #expect(info.category == .dependencyMissing)
        #expect(info.recoverySuggestion != nil)
        #expect(info.recoverySuggestion?.contains("brew install") == true)
    }

    @Test("Dependency check takes priority over generic error: catch-all")
    func dependencyBeforeErrorCatchAll() {
        // This contains both "error:" AND "ffprobe" + "not found"
        let info = ErrorInfo.classifyStderr("Error: ffprobe not found on PATH", code: 1)
        #expect(info.category == .dependencyMissing)
    }

    @Test("Recognizes configuration errors at start of output")
    func invalidConfiguration() {
        let info = ErrorInfo.classifyStderr("error: --weights must sum to 100", code: 2)
        #expect(info.category == .invalidConfiguration)
        #expect(info.recoverySuggestion != nil)
    }

    @Test("Recognizes configuration errors at start of line")
    func invalidConfigurationMidStream() {
        let info = ErrorInfo.classifyStderr("usage: ...\nerror: --mode invalid", code: 2)
        #expect(info.category == .invalidConfiguration)
    }

    @Test("Python exceptions are NOT classified as configuration errors")
    func pythonExceptionNotConfig() {
        let info = ErrorInfo.classifyStderr("RuntimeError: out of memory", code: 1)
        #expect(info.category != .invalidConfiguration)
        #expect(info.category == .cliCrash(code: 1))
    }

    @Test("ValueError traceback is NOT classified as configuration error")
    func valueErrorNotConfig() {
        let info = ErrorInfo.classifyStderr("Traceback (most recent call last):\n  ...\nValueError: invalid literal", code: 1)
        #expect(info.category != .invalidConfiguration)
    }

    @Test("Falls back to cliCrash for unknown stderr")
    func unknownStderrFallback() {
        let info = ErrorInfo.classifyStderr("Segmentation fault", code: 139)
        #expect(info.category == .cliCrash(code: 139))
        #expect(info.message == "Segmentation fault")
    }

    @Test("Empty stderr falls back to cliCrash with generated message")
    func emptyStderrFallback() {
        let info = ErrorInfo.classifyStderr("", code: 42)
        #expect(info.category == .cliCrash(code: 42))
        #expect(info.message.contains("42"))
    }

    @Test("Case insensitive matching for permission denied")
    func caseInsensitivePermission() {
        let info = ErrorInfo.classifyStderr("PERMISSION DENIED on /root", code: 1)
        #expect(info.category == .permissionDenied)
    }

    @Test("Case insensitive matching for no such file")
    func caseInsensitiveNoSuchFile() {
        let info = ErrorInfo.classifyStderr("NO SUCH FILE OR DIRECTORY", code: 1)
        #expect(info.category == .directoryNotFound)
    }

    @Test("pdfminer missing error classified as dependencyMissing")
    func pdfminerMissingError() {
        let err = ErrorInfo.classifyStderr(
            "error: Document mode requires pdfminer.six. Install with: pip install 'duplicates-detector[document]'",
            code: 1
        )
        #expect(err.category == .dependencyMissing)
    }

    @Test("no document files found classified as noFilesFound")
    func noDocumentFilesFound() {
        let err = ErrorInfo.classifyStderr(
            "error: No document files found in the specified directories.",
            code: 1
        )
        #expect(err.category == .noFilesFound)
    }
}

// MARK: - classify

@Suite("ErrorInfo — classify")
struct ErrorInfoClassifyTests {

    @Test("Wraps binaryNotFound")
    func binaryNotFound() {
        let error: any Error = CLIBridgeError.binaryNotFound
        let info = ErrorInfo.classify(error)
        #expect(info.category == .binaryNotFound)
        #expect(info.recoverySuggestion != nil)
    }

    @Test("Wraps processExitedWithError")
    func processExitedWithError() {
        let error: any Error = CLIBridgeError.processExitedWithError(code: 1)
        let info = ErrorInfo.classify(error)
        #expect(info.category == .cliCrash(code: 1))
    }

    @Test("Wraps processExitedWithErrorMessage with stderr classification")
    func processExitedWithErrorMessageClassified() {
        let error: any Error = CLIBridgeError.processExitedWithErrorMessage(
            code: 1, stderr: "Permission denied"
        )
        let info = ErrorInfo.classify(error)
        #expect(info.category == .permissionDenied)
    }

    @Test("Wraps emptyOutput")
    func emptyOutput() {
        let error: any Error = CLIBridgeError.emptyOutput
        let info = ErrorInfo.classify(error)
        #expect(info.category == .unknown)
        #expect(info.recoverySuggestion != nil)
    }

    @Test("Wraps unknown error with default category")
    func unknownError() {
        let error: any Error = NSError(domain: "test", code: 42, userInfo: [
            NSLocalizedDescriptionKey: "Something went wrong",
        ])
        let info = ErrorInfo.classify(error)
        #expect(info.category == .unknown)
        #expect(info.message == "Something went wrong")
    }
}

// MARK: - Backward Compatibility

@Suite("ErrorInfo — backward compatibility")
struct ErrorInfoBackwardCompatibilityTests {

    @Test("Message-only init defaults to unknown category")
    func messageOnlyInit() {
        let info = ErrorInfo(message: "test error")
        #expect(info.category == .unknown)
        #expect(info.recoverySuggestion == nil)
    }

    @Test("Equatable compares all fields — same message different category are not equal")
    func equatableComparesAllFields() {
        let a = ErrorInfo(message: "test", category: .unknown)
        let b = ErrorInfo(message: "test", category: .permissionDenied)
        #expect(a != b)
    }

    @Test("Equatable — identical ErrorInfo values are equal")
    func equatableIdenticalValues() {
        let a = ErrorInfo(message: "test", category: .binaryNotFound, recoverySuggestion: "Install it")
        let b = ErrorInfo(message: "test", category: .binaryNotFound, recoverySuggestion: "Install it")
        #expect(a == b)
    }

    @Test("Equatable — different recoverySuggestion makes them unequal")
    func equatableDifferentSuggestion() {
        let a = ErrorInfo(message: "test", category: .unknown, recoverySuggestion: "Try again")
        let b = ErrorInfo(message: "test", category: .unknown, recoverySuggestion: nil)
        #expect(a != b)
    }
}
