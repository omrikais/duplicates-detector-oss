import Foundation
import System

/// Context for logging an action, derived from the pair/group where the action originates.
struct ActionContext: Equatable, Sendable {
    let score: Double
    let strategy: String?
    let keptPath: String?
}

/// A single action record to be written to the log file.
struct ActionLogRecord: Sendable {
    let action: String
    let path: String
    let score: Double
    let strategy: String?
    let kept: String?
    let bytesFreed: Int
    let destination: String?
}

/// Actor that appends CLI-compatible JSON-lines action log records to a file.
///
/// Matches the schema from ``duplicates_detector/actionlog.py`` so that
/// ``duplicates-detector --generate-undo`` can consume GUI-written records.
/// Log-writing failures are non-fatal — returns an error message instead of throwing.
actor ActionLogWriter {
    private let logPath: String
    private let formatter: ISO8601DateFormatter

    init(logPath: String) {
        self.logPath = logPath
        self.formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        // Ensure parent directory exists once at init rather than per-write.
        let directory = (logPath as NSString).deletingLastPathComponent
        if !directory.isEmpty {
            try? FileManager.default.createDirectory(
                atPath: directory, withIntermediateDirectories: true
            )
        }
    }

    /// Append one action record as a JSON line. Returns `nil` on success, error message on failure.
    func appendRecord(_ record: ActionLogRecord) -> String? {
        // Build JSON dict — .sortedKeys ensures deterministic key order matching the CLI.
        var dict: [String: Any] = [
            "timestamp": formatter.string(from: Date()),
            "action": record.action,
            "path": record.path,
            "score": record.score,
            "strategy": record.strategy as Any,
            "kept": record.kept as Any,
            "bytes_freed": record.bytesFreed,
            "dry_run": false,
            "source": "gui",
        ]
        if let destination = record.destination {
            dict["destination"] = destination
        }
        return writeJSONLine(dict)
    }

    /// Append a Photos Library trash action as a JSON line.
    ///
    /// Uses `action: "photos_trash"` to distinguish from filesystem trash operations,
    /// since Photos deletions go through PHPhotoLibrary and land in Recently Deleted.
    func logPhotosTrash(assetID: String, filename: String, score: Double, kept: String) -> String? {
        let dict: [String: Any] = [
            "timestamp": formatter.string(from: Date()),
            "action": "photos_trash",
            "path": "photos://asset/\(assetID)",
            "asset_id": assetID,
            "filename": filename,
            "score": score,
            "kept": kept,
            "bytes_freed": 0,
            "dry_run": false,
            "source": "gui",
        ]
        return writeJSONLine(dict)
    }

    /// Serialize a dictionary as a JSON line and append it to the log file.
    /// Returns `nil` on success, error message on failure.
    private func writeJSONLine(_ dict: [String: Any]) -> String? {
        let jsonData: Data
        do {
            jsonData = try JSONSerialization.data(withJSONObject: dict, options: [.sortedKeys])
        } catch {
            return "Failed to serialize log record: \(error.localizedDescription)"
        }

        guard var jsonString = String(data: jsonData, encoding: .utf8) else {
            return "Failed to encode log record as UTF-8"
        }
        jsonString += "\n"

        // Append to file using O_APPEND for atomic append semantics
        do {
            let fd = try FileDescriptor.open(
                FilePath(logPath),
                .writeOnly,
                options: [.append, .create],
                permissions: [.ownerReadWrite, .groupRead, .otherRead]
            )
            defer { try? fd.close() }
            guard let lineData = jsonString.data(using: .utf8) else {
                return "Failed to encode line as UTF-8"
            }
            try lineData.withUnsafeBytes { buffer in
                _ = try fd.write(UnsafeRawBufferPointer(buffer))
            }
        } catch {
            return "Failed to write action log: \(error.localizedDescription)"
        }

        return nil
    }

}
