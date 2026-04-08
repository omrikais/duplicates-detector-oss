import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("HistoryAction — Codable")
struct HistoryActionCodableTests {
    private let encoder: JSONEncoder = {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        return enc
    }()
    private let decoder = JSONDecoder()

    @Test("Encode → decode round-trip preserves all fields")
    func roundTrip() throws {
        let action = HistoryAction(
            timestamp: "2026-03-19T14:30:00Z",
            action: "trashed",
            path: "/videos/b.mp4",
            kept: "/videos/a.mp4",
            bytesFreed: 1_073_741_824,
            score: 87.5,
            strategy: "biggest",
            destination: "/Users/omri/.Trash/b.mp4"
        )
        let data = try encoder.encode(action)
        let decoded = try decoder.decode(HistoryAction.self, from: data)

        #expect(decoded.timestamp == action.timestamp)
        #expect(decoded.action == action.action)
        #expect(decoded.path == action.path)
        #expect(decoded.kept == action.kept)
        #expect(decoded.bytesFreed == action.bytesFreed)
        #expect(decoded.score == action.score)
        #expect(decoded.strategy == action.strategy)
        #expect(decoded.destination == action.destination)
    }

    @Test("Nil optional fields encode and decode correctly")
    func nilOptionals() throws {
        let action = HistoryAction(
            timestamp: "2026-03-19T14:30:00Z",
            action: "deleted",
            path: "/videos/b.mp4",
            kept: nil,
            bytesFreed: 0,
            score: 60.0,
            strategy: nil,
            destination: nil
        )
        let data = try encoder.encode(action)
        let decoded = try decoder.decode(HistoryAction.self, from: data)

        #expect(decoded.kept == nil)
        #expect(decoded.strategy == nil)
        #expect(decoded.destination == nil)
        #expect(decoded.bytesFreed == 0)
    }
}

@Suite("HistoryActionSidecar — Codable")
struct HistoryActionSidecarTests {
    private let encoder: JSONEncoder = {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        return enc
    }()
    private let decoder = JSONDecoder()

    @Test("Sidecar round-trip with multiple actions")
    func sidecarRoundTrip() throws {
        let sidecar = HistoryActionSidecar(
            version: 1,
            actions: [
                HistoryAction(
                    timestamp: "2026-03-19T14:30:00Z",
                    action: "trashed",
                    path: "/videos/b.mp4",
                    kept: "/videos/a.mp4",
                    bytesFreed: 1024,
                    score: 85.0,
                    strategy: "biggest",
                    destination: nil
                ),
                HistoryAction(
                    timestamp: "2026-03-19T14:31:00Z",
                    action: "moved",
                    path: "/videos/d.mp4",
                    kept: "/videos/c.mp4",
                    bytesFreed: 0,
                    score: 72.0,
                    strategy: "newest",
                    destination: "/archive/d.mp4"
                ),
            ]
        )
        let data = try encoder.encode(sidecar)
        let decoded = try decoder.decode(HistoryActionSidecar.self, from: data)

        #expect(decoded.version == 1)
        #expect(decoded.actions.count == 2)
        #expect(decoded.actions[0].action == "trashed")
        #expect(decoded.actions[1].action == "moved")
    }

    @Test("Empty actions array")
    func emptyActions() throws {
        let sidecar = HistoryActionSidecar(version: 1, actions: [])
        let data = try encoder.encode(sidecar)
        let decoded = try decoder.decode(HistoryActionSidecar.self, from: data)
        #expect(decoded.actions.isEmpty)
    }
}
