import Foundation

/// Generates test media files in a temp directory for E2E tests.
enum TestMedia {
    static func createVideoDirectory() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("dd-e2e-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        // Locate ffmpeg via `which` (works on both ARM and Intel Macs)
        let ffmpeg = try locateFFmpeg()

        // Generate 3 small videos: 2 near-duplicates + 1 different
        // video_a.mp4 - base
        try run(ffmpeg, args: ["-y", "-f", "lavfi", "-i",
                               "testsrc=duration=2:size=320x240:rate=24",
                               "-c:v", "libx264", "-preset", "ultrafast",
                               dir.appendingPathComponent("video_a.mp4").path])

        // video_b.mp4 - near duplicate (re-encode at different CRF)
        try run(ffmpeg, args: ["-y", "-i", dir.appendingPathComponent("video_a.mp4").path,
                               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                               dir.appendingPathComponent("video_b.mp4").path])

        // video_c.mp4 - different content
        try run(ffmpeg, args: ["-y", "-f", "lavfi", "-i",
                               "color=c=blue:size=320x240:duration=2:rate=24",
                               "-c:v", "libx264", "-preset", "ultrafast",
                               dir.appendingPathComponent("video_c.mp4").path])

        return dir
    }

    static func cleanup(_ dir: URL) {
        try? FileManager.default.removeItem(at: dir)
    }

    /// Check that the `duplicates-detector` CLI is available.
    ///
    /// The XCUITest runner may not inherit the CI shell's PATH, so we also
    /// check known installation paths (Homebrew, CI venv, pip --user).
    /// Throws `TestMediaError.cliNotFound` if it cannot be located.
    static func requireCLI() throws {
        // 1. Try PATH (works when run from terminal or inherited environment)
        if (try? locate("duplicates-detector", error: .cliNotFound)) != nil {
            return
        }
        // 2. Check known paths (XCUITest runner may have a stripped PATH)
        let knownPaths = [
            "/opt/homebrew/bin/duplicates-detector",
            "/usr/local/bin/duplicates-detector",
            "/tmp/dd-venv/bin/duplicates-detector",
        ]
        for path in knownPaths where FileManager.default.isExecutableFile(atPath: path) {
            return
        }
        throw TestMediaError.cliNotFound
    }

    private static func locateFFmpeg() throws -> String {
        try locate("ffmpeg", error: .ffmpegNotFound)
    }

    private static func locate(_ tool: String, error: TestMediaError) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["which", tool]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw error
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !path.isEmpty else {
            throw error
        }
        return path
    }

    private static func run(_ executable: String, args: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw TestMediaError.generationFailed
        }
    }

    enum TestMediaError: Error {
        case ffmpegNotFound
        case cliNotFound
        case generationFailed
    }
}
