import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - ActionLogEntry Parser Tests

@Suite("ActionLogEntry.parseLogFile")
struct ActionLogEntryParserTests {
    /// Helper to write content to a temp file and return its path.
    private func writeTempFile(content: String) -> String {
        let path = NSTemporaryDirectory() + "action-log-entry-test-\(UUID().uuidString).jsonl"
        try! content.write(toFile: path, atomically: true, encoding: .utf8)
        return path
    }

    @Test("Parses valid JSON-lines into ActionLogEntry array")
    func parsesValidLines() {
        let line1 = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"trashed","path":"/videos/a.mp4","score":85.0,"strategy":"newest","kept":"/videos/b.mp4","bytes_freed":1024,"dry_run":false,"source":"gui"}
        """
        let line2 = """
        {"timestamp":"2026-03-14T10:01:00.000Z","action":"deleted","path":"/videos/c.mp4","score":90.0,"bytes_freed":2048,"dry_run":false,"source":"gui"}
        """
        let content = "\(line1)\n\(line2)\n"
        let path = writeTempFile(content: content)
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.count == 2)
        #expect(entries[0].action == "trashed")
        #expect(entries[0].path == "/videos/a.mp4")
        #expect(entries[0].score == 85.0)
        #expect(entries[0].strategy == "newest")
        #expect(entries[0].kept == "/videos/b.mp4")
        #expect(entries[0].bytesFreed == 1024)
        #expect(entries[0].dryRun == false)
        #expect(entries[0].source == "gui")
        #expect(entries[1].action == "deleted")
        #expect(entries[1].path == "/videos/c.mp4")
    }

    @Test("Skips malformed lines gracefully")
    func skipsMalformedLines() {
        let validLine = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"trashed","path":"/videos/a.mp4"}
        """
        let content = "this is not JSON\n\(validLine)\n{malformed: json}\n"
        let path = writeTempFile(content: content)
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.count == 1)
        #expect(entries[0].action == "trashed")
    }

    @Test("Empty file returns empty array")
    func emptyFileReturnsEmpty() {
        let path = writeTempFile(content: "")
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.isEmpty)
    }

    @Test("Nonexistent file returns empty array without crashing")
    func nonexistentFileReturnsEmpty() {
        let fakePath = "/tmp/nonexistent-action-log-\(UUID().uuidString).jsonl"
        let entries = ActionLogEntry.parseLogFile(at: fakePath)
        #expect(entries.isEmpty)
    }

    @Test("Blank lines between valid entries are skipped")
    func blankLinesSkipped() {
        let line = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"trashed","path":"/videos/a.mp4"}
        """
        let content = "\n\n\(line)\n\n\(line)\n\n"
        let path = writeTempFile(content: content)
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.count == 2)
    }

    @Test("Entries with optional fields missing parse correctly")
    func optionalFieldsMissing() {
        let line = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"deleted","path":"/videos/a.mp4"}
        """
        let path = writeTempFile(content: "\(line)\n")
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.count == 1)
        #expect(entries[0].score == nil)
        #expect(entries[0].strategy == nil)
        #expect(entries[0].kept == nil)
        #expect(entries[0].bytesFreed == nil)
        #expect(entries[0].destination == nil)
        #expect(entries[0].dryRun == nil)
        #expect(entries[0].source == nil)
    }

    @Test("Moved entry with destination field parses destination")
    func movedEntryHasDestination() {
        let line = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"moved","path":"/videos/a.mp4","destination":"/tmp/dups/a.mp4"}
        """
        let path = writeTempFile(content: "\(line)\n")
        defer { try? FileManager.default.removeItem(atPath: path) }

        let entries = ActionLogEntry.parseLogFile(at: path)
        #expect(entries.count == 1)
        #expect(entries[0].destination == "/tmp/dups/a.mp4")
    }
}

// MARK: - ActionLogEntry Computed Properties

@Suite("ActionLogEntry computed properties")
struct ActionLogEntryComputedTests {
    private func makeEntry(
        action: String = "trashed",
        path: String = "/videos/test.mp4"
    ) -> ActionLogEntry {
        // Parse from JSON to construct an entry via the Decodable path
        let json = """
        {"timestamp":"2026-03-14T10:00:00.000Z","action":"\(action)","path":"\(path)"}
        """
        let data = json.data(using: .utf8)!
        return try! JSONDecoder().decode(ActionLogEntry.self, from: data)
    }

    @Test("fileName extracts last path component")
    func fileNameExtractsLastComponent() {
        let entry = makeEntry(path: "/users/demo/Videos/vacation_2024.mp4")
        #expect(entry.fileName == "vacation_2024.mp4")
    }

    @Test("fileName from root path returns the filename")
    func fileNameFromRootPath() {
        let entry = makeEntry(path: "/file.mp4")
        #expect(entry.fileName == "file.mp4")
    }

    @Test("fileName from bare filename returns itself")
    func fileNameFromBareFile() {
        let entry = makeEntry(path: "bare_file.mp4")
        #expect(entry.fileName == "bare_file.mp4")
    }

    @Test("actionIcon returns 'trash' for trashed action")
    func actionIconTrashed() {
        let entry = makeEntry(action: "trashed")
        #expect(entry.actionIcon == "trash")
    }

    @Test("actionIcon returns 'trash.slash' for deleted action")
    func actionIconDeleted() {
        let entry = makeEntry(action: "deleted")
        #expect(entry.actionIcon == "trash.slash")
    }

    @Test("actionIcon returns 'folder.badge.plus' for moved action")
    func actionIconMoved() {
        let entry = makeEntry(action: "moved")
        #expect(entry.actionIcon == "folder.badge.plus")
    }

    @Test("actionIcon returns 'questionmark.circle' for unknown action")
    func actionIconUnknown() {
        let entry = makeEntry(action: "hardlinked")
        #expect(entry.actionIcon == "questionmark.circle")
    }

    @Test("id is a unique UUID per instance")
    func idUniqueness() {
        let a = makeEntry(path: "/videos/test.mp4")
        let b = makeEntry(path: "/videos/test.mp4")
        #expect(a.id != b.id)
    }

    @Test(
        "actionIcon mapping covers all documented action types",
        arguments: [
            ("trashed", "trash"),
            ("deleted", "trash.slash"),
            ("moved", "folder.badge.plus"),
        ]
    )
    func actionIconMapping(action: String, expectedIcon: String) {
        let entry = makeEntry(action: action)
        #expect(entry.actionIcon == expectedIcon)
    }

    @Test("fileAction returns nil for unknown action")
    func fileActionUnknown() {
        let entry = makeEntry(action: "hardlinked")
        #expect(entry.fileAction == nil)
        #expect(entry.actionIcon == "questionmark.circle")
    }
}

// MARK: - FileAction Enum Tests

@Suite("FileAction enum")
struct FileActionTests {
    @Test("Known actions produce correct FileAction", arguments: [
        ("trashed", FileAction.trashed),
        ("deleted", FileAction.deleted),
        ("moved", FileAction.moved),
    ])
    func knownActions(raw: String, expected: FileAction) {
        #expect(FileAction(rawValue: raw) == expected)
    }

    @Test("Unknown action returns nil")
    func unknownAction() {
        #expect(FileAction(rawValue: "hardlinked") == nil)
    }

    @Test("icon matches legacy actionIcon", arguments: [
        ("trashed", "trash"),
        ("deleted", "trash.slash"),
        ("moved", "folder.badge.plus"),
    ])
    func iconMapping(action: String, expectedIcon: String) {
        #expect(FileAction(rawValue: action)?.icon == expectedIcon)
    }

    @Test("pastTenseCapitalized values", arguments: [
        ("trashed", "Trashed"),
        ("deleted", "Deleted"),
        ("moved", "Moved"),
    ])
    func pastTense(action: String, expected: String) {
        #expect(FileAction(rawValue: action)?.pastTenseCapitalized == expected)
    }
}
