import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helper

/// Decode a `SessionInfo` from a JSON string for testing.
private func decodeSessionInfo(_ json: String) throws -> SessionInfo {
    let data = json.data(using: .utf8)!
    return try JSONDecoder().decode(SessionInfo.self, from: data)
}

/// Build a minimal SessionInfo JSON string with the given config dict entries.
///
/// Callers supply only the `config` portion as a JSON object string;
/// all other SessionInfo fields use fixed defaults.
private func sessionJSON(config: String, directories: String = #"["/videos"]"#) -> String {
    """
    {
        "session_id": "test-session",
        "directories": \(directories),
        "config": \(config),
        "completed_stages": ["scan", "extract"],
        "active_stage": "score",
        "total_files": 10,
        "elapsed_seconds": 5.0,
        "created_at": 1711100000.0,
        "paused_at": "2026-03-22T10:00:00.000+00:00",
        "progress_percent": 50
    }
    """
}

// MARK: - ScanConfig.fromPausedSession tests

@Suite("ScanConfig.fromPausedSession")
struct ScanConfigFromSessionTests {

    @Test("Maps all core fields from paused session config")
    func fromPausedSessionMapsAllCoreFields() throws {
        let json = sessionJSON(config: """
        {
            "mode": "image",
            "threshold": 70,
            "content": true,
            "audio": true,
            "keep": "newest",
            "action": "trash",
            "sort": "size",
            "group": true,
            "log": "/tmp/log.jsonl",
            "embed_thumbnails": true
        }
        """)
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        #expect(config.mode == .image)
        #expect(config.threshold == 70)
        #expect(config.content == true)
        #expect(config.audio == true)
        #expect(config.keep == .newest)
        #expect(config.action == .trash)
        #expect(config.sort == .size)
        #expect(config.group == true)
        #expect(config.log == "/tmp/log.jsonl")
        #expect(config.embedThumbnails == true)
        // Directories come from info.directories, not from config dict
        #expect(config.directories == ["/videos"])
    }

    @Test("Maps filter fields from paused session config")
    func fromPausedSessionMapsFilters() throws {
        let json = sessionJSON(config: """
        {
            "min_size": "10MB",
            "max_size": "1GB",
            "min_duration": 30,
            "max_duration": 3600,
            "codec": "h264"
        }
        """)
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        #expect(config.minSize == "10MB")
        #expect(config.maxSize == "1GB")
        #expect(config.minDuration == 30.0)
        #expect(config.maxDuration == 3600.0)
        #expect(config.codec == "h264")
    }

    @Test("Uses defaults when config dict is empty")
    func fromPausedSessionDefaultsForMissingFields() throws {
        let json = sessionJSON(config: "{}")
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        let defaults = ScanConfig()
        #expect(config.mode == defaults.mode)
        #expect(config.threshold == defaults.threshold)
        #expect(config.content == defaults.content)
        #expect(config.audio == defaults.audio)
        #expect(config.keep == defaults.keep)
        #expect(config.action == defaults.action)
        #expect(config.sort == defaults.sort)
        #expect(config.group == defaults.group)
        #expect(config.verbose == defaults.verbose)
        #expect(config.log == defaults.log)
        #expect(config.embedThumbnails == defaults.embedThumbnails)
        #expect(config.minSize == defaults.minSize)
        #expect(config.maxSize == defaults.maxSize)
        #expect(config.minDuration == defaults.minDuration)
        #expect(config.maxDuration == defaults.maxDuration)
        #expect(config.codec == defaults.codec)
        #expect(config.noMetadataCache == defaults.noMetadataCache)
        #expect(config.noContentCache == defaults.noContentCache)
        #expect(config.noAudioCache == defaults.noAudioCache)
        #expect(config.noRecursive == defaults.noRecursive)
    }

    @Test("Maps content hashing sub-fields from paused session config")
    func fromPausedSessionMapsContentFields() throws {
        let json = sessionJSON(config: """
        {
            "content": true,
            "rotation_invariant": true,
            "content_method": "ssim"
        }
        """)
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        #expect(config.content == true)
        #expect(config.rotationInvariant == true)
        #expect(config.contentMethod == .ssim)
    }

    @Test("Maps cache and misc fields from paused session config")
    func fromPausedSessionMapsCacheFields() throws {
        let json = sessionJSON(config: """
        {
            "cache_dir": "/tmp/cache",
            "no_metadata_cache": true,
            "no_content_cache": true,
            "no_audio_cache": true,
            "no_recursive": true,
            "thumbnail_size": "128x128",
            "ignore_file": "/tmp/ignore.json",
            "workers": 4,
            "extensions": "mp4,mkv"
        }
        """)
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        #expect(config.cacheDir == "/tmp/cache")
        #expect(config.noMetadataCache == true)
        #expect(config.noContentCache == true)
        #expect(config.noAudioCache == true)
        #expect(config.noRecursive == true)
        #expect(config.thumbnailSize == "128x128")
        #expect(config.ignoreFile == "/tmp/ignore.json")
        #expect(config.workers == 4)
        #expect(config.extensions == "mp4,mkv")
    }

    @Test("Directories come from SessionInfo.directories, not config dict")
    func fromPausedSessionUsesInfoDirectories() throws {
        let json = sessionJSON(
            config: "{}",
            directories: #"["/photos", "/music"]"#
        )
        let info = try decodeSessionInfo(json)
        let config = ScanConfig.fromPausedSession(info)

        #expect(config.directories == ["/photos", "/music"])
    }
}

// MARK: - AnyCodable accessor tests

@Suite("AnyCodable accessors")
struct AnyCodableAccessorTests {

    @Test("intValue returns value for .int, nil for other cases")
    func anyCodableIntValue() {
        #expect(AnyCodable.int(42).intValue == 42)
        #expect(AnyCodable.int(0).intValue == 0)
        #expect(AnyCodable.int(-1).intValue == -1)
        #expect(AnyCodable.string("x").intValue == nil)
        #expect(AnyCodable.double(3.14).intValue == nil)
        #expect(AnyCodable.bool(true).intValue == nil)
        #expect(AnyCodable.null.intValue == nil)
    }

    @Test("doubleValue returns value for .double, coerces .int, nil for others")
    func anyCodableDoubleValue() {
        #expect(AnyCodable.double(3.14).doubleValue == 3.14)
        #expect(AnyCodable.double(0.0).doubleValue == 0.0)
        // int-to-double coercion
        #expect(AnyCodable.int(5).doubleValue == 5.0)
        #expect(AnyCodable.int(0).doubleValue == 0.0)
        // Non-numeric cases return nil
        #expect(AnyCodable.string("x").doubleValue == nil)
        #expect(AnyCodable.bool(false).doubleValue == nil)
        #expect(AnyCodable.null.doubleValue == nil)
    }

    @Test("stringValue returns value for .string, nil for other cases")
    func anyCodableStringValue() {
        #expect(AnyCodable.string("hello").stringValue == "hello")
        #expect(AnyCodable.string("").stringValue == "")
        #expect(AnyCodable.int(42).stringValue == nil)
        #expect(AnyCodable.bool(true).stringValue == nil)
        #expect(AnyCodable.null.stringValue == nil)
    }

    @Test("boolValue returns value for .bool, nil for other cases")
    func anyCodableBoolValue() {
        #expect(AnyCodable.bool(true).boolValue == true)
        #expect(AnyCodable.bool(false).boolValue == false)
        #expect(AnyCodable.int(1).boolValue == nil)
        #expect(AnyCodable.string("true").boolValue == nil)
        #expect(AnyCodable.null.boolValue == nil)
    }
}
