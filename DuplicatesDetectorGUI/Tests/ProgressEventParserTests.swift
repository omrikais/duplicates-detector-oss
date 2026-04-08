import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("ProgressEventParser")
struct ProgressEventParserTests {
    private func loadFixture(_ name: String) throws -> String {
        try FixtureLoader.string(named: name)
    }

    @Test("Parse stage_start event")
    func stageStart() {
        let line = #"{"type":"stage_start","stage":"scan","timestamp":"2025-01-15T10:30:00.000+00:00"}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .stageStart(let e) = event else {
            Issue.record("Expected stageStart")
            return
        }
        #expect(e.stage == "scan")
        #expect(e.total == nil)
    }

    @Test("Parse stage_start with total")
    func stageStartWithTotal() {
        let line = #"{"type":"stage_start","stage":"extract","timestamp":"2025-01-15T10:30:00.000+00:00","total":10}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .stageStart(let e) = event else {
            Issue.record("Expected stageStart")
            return
        }
        #expect(e.stage == "extract")
        #expect(e.total == 10)
    }

    @Test("Parse progress event")
    func progress() {
        let line = #"{"type":"progress","stage":"scan","current":5,"total":10,"timestamp":"2025-01-15T10:30:00.100+00:00","file":"/videos/clip1.mp4"}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .progress(let e) = event else {
            Issue.record("Expected progress")
            return
        }
        #expect(e.stage == "scan")
        #expect(e.current == 5)
        #expect(e.total == 10)
        #expect(e.file == "/videos/clip1.mp4")
    }

    @Test("Parse progress without optional fields")
    func progressMinimal() {
        let line = #"{"type":"progress","stage":"score","current":14,"timestamp":"2025-01-15T10:30:00.000+00:00"}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .progress(let e) = event else {
            Issue.record("Expected progress")
            return
        }
        #expect(e.total == nil)
        #expect(e.file == nil)
    }

    @Test("Parse stage_end event")
    func stageEnd() {
        let line = #"{"type":"stage_end","stage":"extract","total":10,"elapsed":1.234,"timestamp":"2025-01-15T10:30:01.385+00:00"}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .stageEnd(let e) = event else {
            Issue.record("Expected stageEnd")
            return
        }
        #expect(e.stage == "extract")
        #expect(e.total == 10)
        #expect(e.elapsed == 1.234)
        #expect(e.extras.isEmpty)
    }

    @Test("Parse stage_end with extras")
    func stageEndExtras() {
        let line = #"{"type":"stage_end","stage":"content_hash","total":8,"elapsed":1.5,"timestamp":"2025-01-15T10:30:02.889+00:00","hashed":6}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .stageEnd(let e) = event else {
            Issue.record("Expected stageEnd")
            return
        }
        #expect(e.extras["hashed"] == 6)
    }

    @Test("Malformed line returns nil")
    func malformed() {
        #expect(ProgressEventParser.parseLine("not json") == nil)
        #expect(ProgressEventParser.parseLine("{}") == nil)
        #expect(ProgressEventParser.parseLine(#"{"type":"unknown"}"#) == nil)
        #expect(ProgressEventParser.parseLine("") == nil)
    }

    @Test("Parse full pipeline from fixture")
    func fullPipeline() throws {
        let text = try loadFixture("progress-events.jsonl")
        let events = ProgressEventParser.parseLines(text)

        // 17 lines in the fixture
        #expect(events.count == 17)

        // First should be stage_start for scan
        guard case .stageStart(let first) = events[0] else {
            Issue.record("Expected stageStart")
            return
        }
        #expect(first.stage == "scan")

        // Last should be stage_end for report
        guard case .stageEnd(let last) = events[events.count - 1] else {
            Issue.record("Expected stageEnd")
            return
        }
        #expect(last.stage == "report")
    }

    @Test("Parse session_start event")
    func sessionStartEvent() {
        let json = #"{"type":"session_start","session_id":"abc123","wall_start":"2026-03-20T10:00:00.000Z","total_files":30000,"stages":["scan","extract","score"],"resumed_from":null}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .sessionStart(let e) = event {
            #expect(e.sessionId == "abc123")
            #expect(e.totalFiles == 30000)
            #expect(e.stages == ["scan", "extract", "score"])
            #expect(e.resumedFrom == nil)
        } else {
            Issue.record("Expected sessionStart")
        }
    }

    @Test("Parse session_start event with prior_elapsed_seconds")
    func sessionStartWithPriorElapsed() {
        let json = #"{"type":"session_start","session_id":"abc123","wall_start":"2026-03-20T10:00:00.000Z","total_files":30000,"stages":["scan","extract","score"],"resumed_from":"prev-session","prior_elapsed_seconds":42.5}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .sessionStart(let e) = event {
            #expect(e.priorElapsedSeconds == 42.5)
            #expect(e.resumedFrom == "prev-session")
            #expect(e.sessionId == "abc123")
            #expect(e.totalFiles == 30000)
            #expect(e.stages == ["scan", "extract", "score"])
        } else {
            Issue.record("Expected sessionStart")
        }
    }

    @Test("Parse session_start without prior_elapsed_seconds decodes as nil")
    func sessionStartWithoutPriorElapsed() {
        let json = #"{"type":"session_start","session_id":"abc123","wall_start":"2026-03-20T10:00:00.000Z","total_files":30000,"stages":["scan","extract","score"],"resumed_from":null}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .sessionStart(let e) = event {
            #expect(e.priorElapsedSeconds == nil)
            #expect(e.resumedFrom == nil)
        } else {
            Issue.record("Expected sessionStart")
        }
    }

    @Test("Parse session_end event")
    func sessionEndEvent() {
        let json = #"{"type":"session_end","session_id":"abc123","total_elapsed":380.5,"cache_time_saved":120.0,"timestamp":"2026-03-20T10:06:20.500Z"}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .sessionEnd(let e) = event {
            #expect(e.sessionId == "abc123")
            #expect(e.totalElapsed == 380.5)
            #expect(e.cacheTimeSaved == 120.0)
        } else {
            Issue.record("Expected sessionEnd")
        }
    }

    @Test("Parse pause event")
    func pauseEvent() {
        let json = #"{"type":"pause","session_id":"abc123","session_file":"/tmp/session.json","timestamp":"2026-03-20T10:03:00.000Z"}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .pause(let e) = event {
            #expect(e.sessionId == "abc123")
            #expect(e.sessionFile == "/tmp/session.json")
        } else {
            Issue.record("Expected pause")
        }
    }

    @Test("Parse resume event")
    func resumeEvent() {
        let json = #"{"type":"resume","session_id":"abc123","timestamp":"2026-03-20T10:04:00.000Z"}"#
        let event = ProgressEventParser.parseLine(json)
        #expect(event != nil)
        if case .resume(let e) = event {
            #expect(e.sessionId == "abc123")
        } else {
            Issue.record("Expected resume")
        }
    }

    @Test("All known stage names are valid PipelineStage values")
    func knownStages() {
        let knownStages = ["scan", "extract", "filter", "content_hash",
                           "ssim_extract", "audio_fingerprint", "score",
                           "thumbnail", "report", "replay"]
        for name in knownStages {
            #expect(PipelineStage(rawValue: name) != nil, "Unknown stage: \(name)")
        }
    }

    @Test("Score stage_end with cache stats decodes correctly")
    func scoreStageEndWithCacheStats() {
        let line = #"{"type":"stage_end","stage":"score","total":500,"elapsed":2.5,"pairs_found":15,"cache_hits":200,"cache_misses":300,"timestamp":"2026-03-20T10:35:00Z"}"#
        guard let event = ProgressEventParser.parseLine(line) else {
            Issue.record("Expected event")
            return
        }

        guard case .stageEnd(let e) = event else {
            Issue.record("Expected stageEnd")
            return
        }
        #expect(e.stage == "score")
        #expect(e.total == 500)
        #expect(e.elapsed == 2.5)
        #expect(e.cacheHits == 200)
        #expect(e.cacheMisses == 300)
        #expect(e.extras["pairsFound"] == 15)
    }
}
