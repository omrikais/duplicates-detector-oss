import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - ActionLogWriter Tests

@Suite("ActionLogWriter record serialization")
struct ActionLogWriterSerializationTests {
    /// Helper to create a temp directory and log path for each test.
    private func makeTempLogPath() -> (dir: String, path: String) {
        let dir = NSTemporaryDirectory() + "action-log-test-\(UUID().uuidString)"
        let path = "\(dir)/test.jsonl"
        return (dir, path)
    }

    /// Helper to parse a single JSON line from a log file.
    private func parseLogLine(at path: String) throws -> [String: Any] {
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let content = String(data: data, encoding: .utf8)!
        let firstLine = content.components(separatedBy: "\n").first { !$0.isEmpty }!
        let lineData = firstLine.data(using: .utf8)!
        return try JSONSerialization.jsonObject(with: lineData) as! [String: Any]
    }

    /// Helper to parse all JSON lines from a log file.
    private func parseAllLogLines(at path: String) throws -> [[String: Any]] {
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let content = String(data: data, encoding: .utf8)!
        return content.components(separatedBy: "\n")
            .filter { !$0.isEmpty }
            .map { line in
                let lineData = line.data(using: .utf8)!
                return try! JSONSerialization.jsonObject(with: lineData) as! [String: Any]
            }
    }

    @Test("Trashed record produces valid JSON with all CLI schema fields")
    func trashedRecordHasAllFields() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/videos/vacation.mp4",
            score: 85.0,
            strategy: "newest",
            kept: "/videos/vacation_hd.mp4",
            bytesFreed: 1_048_576,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        #expect(dict["timestamp"] != nil)
        #expect(dict["action"] as? String == "trashed")
        #expect(dict["path"] as? String == "/videos/vacation.mp4")
        #expect(dict["score"] as? Double == 85.0)
        #expect(dict["strategy"] as? String == "newest")
        #expect(dict["kept"] as? String == "/videos/vacation_hd.mp4")
        #expect(dict["bytes_freed"] as? Int == 1_048_576)
        #expect(dict["dry_run"] as? Bool == false)
        #expect(dict["source"] as? String == "gui")
    }

    @Test("Moved record includes destination field")
    func movedRecordHasDestination() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "moved",
            path: "/videos/dup.mp4",
            score: 72.0,
            strategy: "biggest",
            kept: "/videos/original.mp4",
            bytesFreed: 500_000,
            destination: "/tmp/duplicates/dup.mp4"
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        #expect(dict["action"] as? String == "moved")
        #expect(dict["destination"] as? String == "/tmp/duplicates/dup.mp4")
    }

    @Test("Deleted record includes bytes_freed")
    func deletedRecordHasBytesFreed() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "deleted",
            path: "/videos/duplicate.mp4",
            score: 92.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 2_097_152,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        #expect(dict["action"] as? String == "deleted")
        #expect(dict["bytes_freed"] as? Int == 2_097_152)
    }

    @Test("Records are appended, not overwritten, on successive writes")
    func appendsMultipleRecords() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)

        let record1 = ActionLogRecord(
            action: "trashed",
            path: "/videos/first.mp4",
            score: 80.0,
            strategy: "newest",
            kept: "/videos/kept.mp4",
            bytesFreed: 100,
            destination: nil
        )
        let record2 = ActionLogRecord(
            action: "deleted",
            path: "/videos/second.mp4",
            score: 90.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 200,
            destination: nil
        )

        let err1 = await writer.appendRecord(record1)
        let err2 = await writer.appendRecord(record2)
        #expect(err1 == nil)
        #expect(err2 == nil)

        let lines = try parseAllLogLines(at: path)
        #expect(lines.count == 2)
        #expect(lines[0]["path"] as? String == "/videos/first.mp4")
        #expect(lines[1]["path"] as? String == "/videos/second.mp4")
    }

    @Test("Timestamp is valid ISO 8601")
    func timestampIsISO8601() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/videos/test.mp4",
            score: 50.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 0,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        let timestamp = dict["timestamp"] as! String

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = formatter.date(from: timestamp)
        #expect(date != nil, "Timestamp '\(timestamp)' should be parseable as ISO 8601 with fractional seconds")
    }

    @Test("source field is 'gui' in every record")
    func sourceFieldIsGui() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/videos/any.mp4",
            score: 60.0,
            strategy: "oldest",
            kept: "/videos/kept.mp4",
            bytesFreed: 1000,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        #expect(dict["source"] as? String == "gui")
    }

    @Test("Non-existent log directory is created on first write")
    func createsDirectoryOnFirstWrite() async throws {
        let baseDir = NSTemporaryDirectory() + "action-log-test-\(UUID().uuidString)"
        let nestedDir = "\(baseDir)/sub/nested"
        let path = "\(nestedDir)/test.jsonl"
        defer { try? FileManager.default.removeItem(atPath: baseDir) }

        // Verify the directory does not exist before the write
        #expect(!FileManager.default.fileExists(atPath: nestedDir))

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/test.mp4",
            score: 50.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 0,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        // Verify the directory now exists and the file was written
        #expect(FileManager.default.fileExists(atPath: nestedDir))
        #expect(FileManager.default.fileExists(atPath: path))
    }

    @Test("strategy and kept fields are JSON null when nil is passed")
    func nullableFieldsAreNullWhenNil() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "deleted",
            path: "/videos/orphan.mp4",
            score: 55.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 512,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        // Read raw JSON to check for null values
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let content = String(data: data, encoding: .utf8)!
        let firstLine = content.components(separatedBy: "\n").first { !$0.isEmpty }!
        let lineData = firstLine.data(using: .utf8)!
        let dict = try JSONSerialization.jsonObject(with: lineData) as! [String: Any]

        // NSNull indicates JSON null value
        #expect(dict["strategy"] is NSNull, "strategy should be JSON null when nil is passed")
        #expect(dict["kept"] is NSNull, "kept should be JSON null when nil is passed")
    }

    @Test("Moved record without destination omits destination field")
    func noDestinationOmitted() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/videos/test.mp4",
            score: 65.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 0,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        // When destination is nil, the key should not be present
        #expect(dict["destination"] == nil, "destination key should be absent when nil")
    }

    @Test("dry_run field is always false for GUI records")
    func dryRunAlwaysFalse() async throws {
        let (dir, path) = makeTempLogPath()
        defer { try? FileManager.default.removeItem(atPath: dir) }

        let writer = ActionLogWriter(logPath: path)
        let record = ActionLogRecord(
            action: "trashed",
            path: "/videos/test.mp4",
            score: 70.0,
            strategy: nil,
            kept: nil,
            bytesFreed: 0,
            destination: nil
        )

        let error = await writer.appendRecord(record)
        #expect(error == nil)

        let dict = try parseLogLine(at: path)
        #expect(dict["dry_run"] as? Bool == false)
    }
}

// MARK: - ActionContext Tests

@Suite("ActionContext struct")
struct ActionContextTests {
    @Test("ActionContext stores score, strategy, and keptPath")
    func storesAllFields() {
        let ctx = ActionContext(score: 85.0, strategy: "newest", keptPath: "/videos/kept.mp4")
        #expect(ctx.score == 85.0)
        #expect(ctx.strategy == "newest")
        #expect(ctx.keptPath == "/videos/kept.mp4")
    }

    @Test("ActionContext with nil optional fields")
    func nilOptionalFields() {
        let ctx = ActionContext(score: 50.0, strategy: nil, keptPath: nil)
        #expect(ctx.score == 50.0)
        #expect(ctx.strategy == nil)
        #expect(ctx.keptPath == nil)
    }
}

// MARK: - ActionLogRecord Tests

@Suite("ActionLogRecord struct")
struct ActionLogRecordTests {
    @Test("ActionLogRecord stores all fields correctly")
    func storesAllFields() {
        let record = ActionLogRecord(
            action: "moved",
            path: "/videos/dup.mp4",
            score: 75.0,
            strategy: "biggest",
            kept: "/videos/original.mp4",
            bytesFreed: 1024,
            destination: "/tmp/moved/dup.mp4"
        )
        #expect(record.action == "moved")
        #expect(record.path == "/videos/dup.mp4")
        #expect(record.score == 75.0)
        #expect(record.strategy == "biggest")
        #expect(record.kept == "/videos/original.mp4")
        #expect(record.bytesFreed == 1024)
        #expect(record.destination == "/tmp/moved/dup.mp4")
    }
}
