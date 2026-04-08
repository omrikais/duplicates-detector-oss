import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("SessionInfo decoding")
struct SessionInfoTests {
    /// Minimal valid JSON with all required fields and an explicit progress_percent.
    private static let fullJSON = """
    {
        "session_id": "abc-123",
        "directories": ["/videos"],
        "config": {"mode": "video"},
        "completed_stages": ["scan", "extract"],
        "active_stage": "score",
        "total_files": 42,
        "elapsed_seconds": 12.5,
        "created_at": 1711100000.0,
        "paused_at": "2026-03-22T10:00:00.000+00:00",
        "progress_percent": 42
    }
    """

    /// Same payload but WITHOUT progress_percent — tests backward compatibility.
    private static let jsonWithoutProgress = """
    {
        "session_id": "def-456",
        "directories": ["/photos", "/videos"],
        "config": {"mode": "image"},
        "completed_stages": ["scan"],
        "active_stage": "extract",
        "total_files": 100,
        "elapsed_seconds": 3.7,
        "created_at": 1711200000.0
    }
    """

    private func decode(_ json: String) throws -> SessionInfo {
        let data = json.data(using: .utf8)!
        return try JSONDecoder().decode(SessionInfo.self, from: data)
    }

    // MARK: - progressPercent decoding

    @Test("Decodes progressPercent from progress_percent key")
    func decodesProgressPercent() throws {
        let info = try decode(Self.fullJSON)
        #expect(info.progressPercent == 42)
    }

    @Test("Missing progress_percent defaults to 0")
    func missingProgressPercentDefaultsToZero() throws {
        let info = try decode(Self.jsonWithoutProgress)
        #expect(info.progressPercent == 0)
    }

    @Test("progressPercent of 0 when explicitly set")
    func explicitZeroProgressPercent() throws {
        let json = """
        {
            "session_id": "zero-pct",
            "directories": ["/music"],
            "config": {},
            "completed_stages": [],
            "active_stage": "scan",
            "total_files": 0,
            "elapsed_seconds": 0.0,
            "created_at": 1711300000.0,
            "progress_percent": 0
        }
        """
        let info = try decode(json)
        #expect(info.progressPercent == 0)
    }

    @Test("progressPercent at maximum boundary (100)")
    func maxProgressPercent() throws {
        let json = """
        {
            "session_id": "full-pct",
            "directories": ["/done"],
            "config": {"mode": "audio"},
            "completed_stages": ["scan", "extract", "filter", "score", "report"],
            "active_stage": "report",
            "total_files": 50,
            "elapsed_seconds": 120.0,
            "created_at": 1711400000.0,
            "progress_percent": 100
        }
        """
        let info = try decode(json)
        #expect(info.progressPercent == 100)
    }

    // MARK: - Other fields still decode correctly alongside progressPercent

    @Test("All required fields decode correctly when progressPercent is present")
    func allFieldsWithProgress() throws {
        let info = try decode(Self.fullJSON)
        #expect(info.sessionId == "abc-123")
        #expect(info.directories == ["/videos"])
        #expect(info.completedStages == ["scan", "extract"])
        #expect(info.activeStage == "score")
        #expect(info.totalFiles == 42)
        #expect(info.elapsedSeconds == 12.5)
        #expect(info.createdAt == 1711100000.0)
        #expect(info.pausedAt == "2026-03-22T10:00:00.000+00:00")
        #expect(info.mode == "video")
    }

    @Test("All required fields decode correctly when progressPercent is absent")
    func allFieldsWithoutProgress() throws {
        let info = try decode(Self.jsonWithoutProgress)
        #expect(info.sessionId == "def-456")
        #expect(info.directories == ["/photos", "/videos"])
        #expect(info.completedStages == ["scan"])
        #expect(info.activeStage == "extract")
        #expect(info.totalFiles == 100)
        #expect(info.elapsedSeconds == 3.7)
        #expect(info.pausedAt == nil)
        #expect(info.mode == "image")
    }

    @Test("Identifiable id matches sessionId")
    func identifiableId() throws {
        let info = try decode(Self.fullJSON)
        #expect(info.id == "abc-123")
    }
}
