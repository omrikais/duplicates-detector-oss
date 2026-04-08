import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Stub provider for injecting XDG paths into ShellEnvironmentResolver

/// A test double that returns fixed XDG values without spawning a shell.
private struct StubEnvironmentProvider: EnvironmentProvider {
    var xdgConfigHome: String?
    var xdgCacheHome: String?
    var xdgDataHome: String?

    var processEnvironment: [String: String] {
        var env: [String: String] = [:]
        if let v = xdgConfigHome { env["XDG_CONFIG_HOME"] = v }
        if let v = xdgCacheHome { env["XDG_CACHE_HOME"] = v }
        if let v = xdgDataHome { env["XDG_DATA_HOME"] = v }
        return env
    }

    func runLoginShell(command: String) async throws -> String { "" }
}

// MARK: - ProfileManager.validateName

@Suite("ProfileManager name validation")
struct ProfileNameValidationTests {
    @Test("accepts alphanumeric names")
    func acceptsAlphanumeric() {
        #expect(ProfileManager.validateName("myProfile") == true)
        #expect(ProfileManager.validateName("test123") == true)
        #expect(ProfileManager.validateName("ABC") == true)
    }

    @Test("accepts names with hyphens")
    func acceptsHyphens() {
        #expect(ProfileManager.validateName("my-profile") == true)
        #expect(ProfileManager.validateName("a-b-c") == true)
    }

    @Test("accepts names with underscores")
    func acceptsUnderscores() {
        #expect(ProfileManager.validateName("test_123") == true)
        #expect(ProfileManager.validateName("a_b") == true)
    }

    @Test("accepts names with dots")
    func acceptsDots() {
        #expect(ProfileManager.validateName("v2.0") == true)
        #expect(ProfileManager.validateName("config.backup") == true)
    }

    @Test("accepts mixed valid characters")
    func acceptsMixed() {
        #expect(ProfileManager.validateName("my-profile_v2.0") == true)
        #expect(ProfileManager.validateName("Test-123_backup.1") == true)
    }

    @Test("rejects empty string")
    func rejectsEmpty() {
        #expect(ProfileManager.validateName("") == false)
    }

    @Test("rejects double dots (directory traversal)")
    func rejectsDoubleDots() {
        #expect(ProfileManager.validateName("..") == false)
        #expect(ProfileManager.validateName("a..b") == false)
        #expect(ProfileManager.validateName("..hidden") == false)
        #expect(ProfileManager.validateName("path..") == false)
    }

    @Test("rejects forward slashes")
    func rejectsSlashes() {
        #expect(ProfileManager.validateName("bad/name") == false)
        #expect(ProfileManager.validateName("/leading") == false)
        #expect(ProfileManager.validateName("trailing/") == false)
    }

    @Test("rejects backslashes")
    func rejectsBackslashes() {
        #expect(ProfileManager.validateName("bad\\name") == false)
    }

    @Test("rejects names with spaces")
    func rejectsSpaces() {
        #expect(ProfileManager.validateName(" spaces ") == false)
        #expect(ProfileManager.validateName("has space") == false)
        #expect(ProfileManager.validateName(" leading") == false)
        #expect(ProfileManager.validateName("trailing ") == false)
    }

    @Test("rejects special characters")
    func rejectsSpecialChars() {
        #expect(ProfileManager.validateName("name@here") == false)
        #expect(ProfileManager.validateName("name#1") == false)
        #expect(ProfileManager.validateName("name$1") == false)
        #expect(ProfileManager.validateName("name!") == false)
        #expect(ProfileManager.validateName("n&m") == false)
    }
}

// MARK: - ProfileManager XDG Path Resolution

@Suite("ProfileManager XDG path resolution")
struct ProfileManagerPathTests {
    @Test("profilesDirectory uses XDG_CONFIG_HOME when set")
    func profilesDirUsesXDG() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CONFIG_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CONFIG_HOME", old, 1) } else { unsetenv("XDG_CONFIG_HOME") }
        }

        setenv("XDG_CONFIG_HOME", "/tmp/test-xdg-config", 1)
        let dir = ProfileManager.profilesDirectory
        #expect(dir.path.contains("/tmp/test-xdg-config/duplicates-detector/profiles"))
    }

    @Test("configFilePath uses XDG_CONFIG_HOME when set")
    func configFilePathUsesXDG() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CONFIG_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CONFIG_HOME", old, 1) } else { unsetenv("XDG_CONFIG_HOME") }
        }

        setenv("XDG_CONFIG_HOME", "/tmp/test-xdg-config", 1)
        let path = ProfileManager.configFilePath
        #expect(path.path.contains("/tmp/test-xdg-config/duplicates-detector/config.toml"))
    }

    @Test("profilesDirectory falls back to ~/.config when XDG_CONFIG_HOME is empty")
    func profilesDirFallsBackNoXDG() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CONFIG_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CONFIG_HOME", old, 1) } else { unsetenv("XDG_CONFIG_HOME") }
        }

        setenv("XDG_CONFIG_HOME", "", 1)
        let dir = ProfileManager.profilesDirectory
        #expect(dir.path.contains(".config/duplicates-detector/profiles"))
    }
}

// MARK: - ProfileManager CRUD

@Suite("ProfileManager CRUD operations")
struct ProfileManagerCRUDTests {
    /// Create a ProfileManager pointing at a unique temp directory via an injected resolver.
    private func withTempProfileManager(_ body: (_ mgr: ProfileManager, _ tempDir: String) async throws -> Void) async throws {
        let tempDir = NSTemporaryDirectory() + "profile-test-\(UUID().uuidString)"
        defer { try? FileManager.default.removeItem(atPath: tempDir) }
        let resolver = ShellEnvironmentResolver(provider: StubEnvironmentProvider(
            xdgConfigHome: tempDir
        ))
        let mgr = ProfileManager(environmentResolver: resolver)
        try await body(mgr, tempDir)
    }

    @Test("listProfiles returns empty for nonexistent directory")
    func listProfilesEmptyDir() async throws {
        try await withTempProfileManager { mgr, _ in
            let profiles = try await mgr.listProfiles()
            #expect(profiles.isEmpty)
        }
    }

    @Test("saveProfile creates directory and file")
    func saveCreatesDirectoryAndFile() async throws {
        try await withTempProfileManager { mgr, tempDir in
            var data = ProfileData()
            data.mode = "video"
            data.threshold = 60

            try await mgr.saveProfile(name: "test-profile", data: data)

            let profilesDir = tempDir + "/duplicates-detector/profiles"
            #expect(FileManager.default.fileExists(atPath: profilesDir))
            #expect(FileManager.default.fileExists(atPath: profilesDir + "/test-profile.toml"))
        }
    }

    @Test("saveProfile + loadProfile round-trips all ProfileData fields")
    func saveLoadRoundTrip() async throws {
        try await withTempProfileManager { mgr, _ in
            var data = ProfileData()
            data.mode = "image"
            data.threshold = 75
            data.keep = "newest"
            data.action = "trash"
            data.content = true
            data.audio = false
            data.workers = 4
            data.sort = "size"
            data.group = true
            data.verbose = true
            data.embedThumbnails = false
            data.contentMethod = "ssim"
            data.rotationInvariant = true
            data.noMetadataCache = true
            data.noContentCache = true
            data.noAudioCache = false
            data.noRecursive = true
            data.cacheDir = "/tmp/cache"
            data.extensions = "jpg,png"
            data.ignoreFile = "/tmp/ignore.json"
            data.log = "/tmp/log.jsonl"
            data.thumbnailSize = "160x90"
            data.exclude = ["*.tmp", "cache/**"]
            data.weights = ["filename": 30, "resolution": 20, "filesize": 15, "exif": 35]
            data.minSize = "1MB"
            data.maxSize = "1GB"
            data.minDuration = 5.0
            data.maxDuration = 3600.0
            data.minResolution = "640x480"
            data.maxResolution = "3840x2160"
            data.minBitrate = "500kbps"
            data.maxBitrate = "50Mbps"
            data.codec = "h264"
            data.format = "json"
            data.jsonEnvelope = true
            data.quiet = false
            data.noColor = true
            data.machineProgress = false

            try await mgr.saveProfile(name: "full-test", data: data)
            let loaded = try await mgr.loadProfile(name: "full-test")

            #expect(loaded.mode == "image")
            #expect(loaded.threshold == 75)
            #expect(loaded.keep == "newest")
            #expect(loaded.action == "trash")
            #expect(loaded.content == true)
            #expect(loaded.audio == false)
            #expect(loaded.workers == 4)
            #expect(loaded.sort == "size")
            #expect(loaded.group == true)
            #expect(loaded.verbose == true)
            #expect(loaded.embedThumbnails == false)
            #expect(loaded.contentMethod == "ssim")
            #expect(loaded.rotationInvariant == true)
            #expect(loaded.noMetadataCache == true)
            #expect(loaded.noContentCache == true)
            #expect(loaded.noAudioCache == false)
            #expect(loaded.noRecursive == true)
            #expect(loaded.cacheDir == "/tmp/cache")
            #expect(loaded.extensions == "jpg,png")
            #expect(loaded.ignoreFile == "/tmp/ignore.json")
            #expect(loaded.log == "/tmp/log.jsonl")
            #expect(loaded.thumbnailSize == "160x90")
            #expect(loaded.exclude == ["*.tmp", "cache/**"])
            #expect(loaded.minSize == "1MB")
            #expect(loaded.maxSize == "1GB")
            #expect(loaded.minDuration == 5.0)
            #expect(loaded.maxDuration == 3600.0)
            #expect(loaded.minResolution == "640x480")
            #expect(loaded.maxResolution == "3840x2160")
            #expect(loaded.minBitrate == "500kbps")
            #expect(loaded.maxBitrate == "50Mbps")
            #expect(loaded.codec == "h264")
            #expect(loaded.format == "json")
            #expect(loaded.jsonEnvelope == true)
            #expect(loaded.quiet == false)
            #expect(loaded.noColor == true)
            #expect(loaded.machineProgress == false)

            // Weight values
            #expect(loaded.weights?["filename"] == 30)
            #expect(loaded.weights?["resolution"] == 20)
            #expect(loaded.weights?["filesize"] == 15)
            #expect(loaded.weights?["exif"] == 35)
        }
    }

    @Test("saveProfile with fractional weights preserves them")
    func fractionalWeightsRoundTrip() async throws {
        try await withTempProfileManager { mgr, _ in
            var data = ProfileData()
            data.weights = ["filename": 33.3, "duration": 33.4, "resolution": 33.3]

            try await mgr.saveProfile(name: "frac", data: data)
            let loaded = try await mgr.loadProfile(name: "frac")

            #expect(loaded.weights?["filename"] == 33.3)
            #expect(loaded.weights?["duration"] == 33.4)
            #expect(loaded.weights?["resolution"] == 33.3)
        }
    }

    @Test("listProfiles returns saved profiles sorted by name")
    func listProfilesSorted() async throws {
        try await withTempProfileManager { mgr, _ in
            try await mgr.saveProfile(name: "zebra", data: ProfileData())
            try await mgr.saveProfile(name: "alpha", data: ProfileData())
            try await mgr.saveProfile(name: "middle", data: ProfileData())

            let profiles = try await mgr.listProfiles()
            #expect(profiles.count == 3)
            #expect(profiles[0].name == "alpha")
            #expect(profiles[1].name == "middle")
            #expect(profiles[2].name == "zebra")
        }
    }

    @Test("listProfiles entries have correct URLs")
    func listProfilesURLs() async throws {
        try await withTempProfileManager { mgr, _ in
            try await mgr.saveProfile(name: "test", data: ProfileData())

            let profiles = try await mgr.listProfiles()
            #expect(profiles.count == 1)
            #expect(profiles[0].url.lastPathComponent == "test.toml")
        }
    }

    @Test("deleteProfile removes the file")
    func deleteRemovesFile() async throws {
        try await withTempProfileManager { mgr, _ in
            try await mgr.saveProfile(name: "doomed", data: ProfileData())

            let beforeDelete = try await mgr.listProfiles()
            #expect(beforeDelete.count == 1)

            try await mgr.deleteProfile(name: "doomed")

            let afterDelete = try await mgr.listProfiles()
            #expect(afterDelete.isEmpty)
        }
    }

    @Test("deleteProfile throws notFound for nonexistent profile")
    func deleteThrowsNotFound() async throws {
        try await withTempProfileManager { mgr, _ in
            await #expect(throws: ProfileManagerError.self) {
                try await mgr.deleteProfile(name: "nonexistent")
            }
        }
    }

    @Test("saveProfile with invalid name throws invalidName")
    func saveWithInvalidNameThrows() async throws {
        try await withTempProfileManager { mgr, _ in
            await #expect(throws: ProfileManagerError.self) {
                try await mgr.saveProfile(name: "bad/name", data: ProfileData())
            }
        }
    }

    @Test("loadProfile with invalid name throws invalidName")
    func loadWithInvalidNameThrows() async throws {
        try await withTempProfileManager { mgr, _ in
            await #expect(throws: ProfileManagerError.self) {
                try await mgr.loadProfile(name: "..")
            }
        }
    }

    @Test("loadProfile throws notFound for nonexistent profile")
    func loadThrowsNotFound() async throws {
        try await withTempProfileManager { mgr, _ in
            await #expect(throws: ProfileManagerError.self) {
                try await mgr.loadProfile(name: "missing")
            }
        }
    }

    @Test("saveProfile overwrites existing profile")
    func saveOverwrites() async throws {
        try await withTempProfileManager { mgr, _ in
            var data1 = ProfileData()
            data1.threshold = 30
            try await mgr.saveProfile(name: "mutable", data: data1)

            var data2 = ProfileData()
            data2.threshold = 90
            try await mgr.saveProfile(name: "mutable", data: data2)

            let loaded = try await mgr.loadProfile(name: "mutable")
            #expect(loaded.threshold == 90)
        }
    }

    @Test("saved TOML file contains expected header comment")
    func savedFileHasHeader() async throws {
        try await withTempProfileManager { mgr, tempDir in
            try await mgr.saveProfile(name: "header-test", data: ProfileData())

            let profilePath = tempDir + "/duplicates-detector/profiles/header-test.toml"
            let content = try String(contentsOfFile: profilePath, encoding: .utf8)
            #expect(content.hasPrefix("# duplicates-detector profile"))
            #expect(content.contains("Generated by: Duplicates Detector GUI"))
        }
    }
}

// MARK: - ProfileManager CLI Config

@Suite("ProfileManager CLI global config")
struct ProfileManagerCLIConfigTests {
    private func withTempProfileManager(_ body: (_ mgr: ProfileManager, _ tempDir: String) async throws -> Void) async throws {
        let tempDir = NSTemporaryDirectory() + "profile-test-\(UUID().uuidString)"
        defer { try? FileManager.default.removeItem(atPath: tempDir) }
        let resolver = ShellEnvironmentResolver(provider: StubEnvironmentProvider(
            xdgConfigHome: tempDir
        ))
        let mgr = ProfileManager(environmentResolver: resolver)
        try await body(mgr, tempDir)
    }

    @Test("loadCLIConfig returns empty ProfileData when file does not exist")
    func loadCLIConfigMissing() async throws {
        try await withTempProfileManager { mgr, _ in
            let data = try await mgr.loadCLIConfig()
            #expect(data.mode == nil)
            #expect(data.threshold == nil)
        }
    }

    @Test("saveCLIConfig + loadCLIConfig round-trips")
    func saveCLIConfigRoundTrip() async throws {
        try await withTempProfileManager { mgr, _ in
            var data = ProfileData()
            data.mode = "video"
            data.threshold = 60
            data.content = true
            data.workers = 2

            try await mgr.saveCLIConfig(data)
            let loaded = try await mgr.loadCLIConfig()

            #expect(loaded.mode == "video")
            #expect(loaded.threshold == 60)
            #expect(loaded.content == true)
            #expect(loaded.workers == 2)
        }
    }

    @Test("saveCLIConfig creates directory if needed")
    func saveCLIConfigCreatesDir() async throws {
        try await withTempProfileManager { mgr, tempDir in
            try await mgr.saveCLIConfig(ProfileData())

            let configPath = tempDir + "/duplicates-detector/config.toml"
            #expect(FileManager.default.fileExists(atPath: configPath))
        }
    }
}

// MARK: - CLI-only key preservation

@Suite("ProfileManager CLI-only key preservation")
struct ProfileManagerCLIKeyPreservationTests {
    private func withTempProfileManager(_ body: (_ mgr: ProfileManager, _ tempDir: String) async throws -> Void) async throws {
        let tempDir = NSTemporaryDirectory() + "profile-test-\(UUID().uuidString)"
        defer { try? FileManager.default.removeItem(atPath: tempDir) }
        let resolver = ShellEnvironmentResolver(provider: StubEnvironmentProvider(
            xdgConfigHome: tempDir
        ))
        let mgr = ProfileManager(environmentResolver: resolver)
        try await body(mgr, tempDir)
    }

    @Test("CLI-only fields survive load-edit-save round-trip")
    func cliOnlyFieldsSurviveRoundTrip() async throws {
        try await withTempProfileManager { mgr, _ in
            var data = ProfileData()
            data.mode = "video"
            data.threshold = 50
            data.format = "json"
            data.jsonEnvelope = true
            data.quiet = true
            data.noColor = true
            data.machineProgress = true

            try await mgr.saveProfile(name: "cli-keys", data: data)

            // Simulate an edit: load, change an editable field, save back
            var loaded = try await mgr.loadProfile(name: "cli-keys")
            #expect(loaded.format == "json")
            #expect(loaded.jsonEnvelope == true)
            #expect(loaded.quiet == true)
            #expect(loaded.noColor == true)
            #expect(loaded.machineProgress == true)

            loaded.threshold = 75
            try await mgr.saveProfile(name: "cli-keys", data: loaded)

            // Reload and verify CLI-only fields are preserved
            let reloaded = try await mgr.loadProfile(name: "cli-keys")
            #expect(reloaded.threshold == 75)
            #expect(reloaded.format == "json")
            #expect(reloaded.jsonEnvelope == true)
            #expect(reloaded.quiet == true)
            #expect(reloaded.noColor == true)
            #expect(reloaded.machineProgress == true)
        }
    }

    @Test("CLI-only fields are nil when absent from TOML")
    func cliOnlyFieldsNilWhenAbsent() async throws {
        try await withTempProfileManager { mgr, _ in
            var data = ProfileData()
            data.mode = "video"
            try await mgr.saveProfile(name: "minimal", data: data)

            let loaded = try await mgr.loadProfile(name: "minimal")
            #expect(loaded.format == nil)
            #expect(loaded.jsonEnvelope == nil)
            #expect(loaded.quiet == nil)
            #expect(loaded.noColor == nil)
            #expect(loaded.machineProgress == nil)
        }
    }
}

// MARK: - ProfileManagerError

@Suite("ProfileManagerError descriptions")
struct ProfileManagerErrorTests {
    @Test("invalidName error has descriptive message")
    func invalidNameDescription() {
        let error = ProfileManagerError.invalidName("bad/name")
        #expect(error.errorDescription?.contains("bad/name") == true)
        #expect(error.errorDescription?.contains("Invalid profile name") == true)
    }

    @Test("notFound error has descriptive message")
    func notFoundDescription() {
        let error = ProfileManagerError.notFound("missing")
        #expect(error.errorDescription?.contains("missing") == true)
        #expect(error.errorDescription?.contains("not found") == true)
    }
}
