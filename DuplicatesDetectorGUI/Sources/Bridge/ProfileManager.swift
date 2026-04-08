import Foundation
import TOMLKit

/// Manages CLI-compatible TOML profiles and the global CLI config file.
///
/// Profiles live at `$XDG_CONFIG_HOME/duplicates-detector/profiles/<name>.toml`.
/// The global config lives at `$XDG_CONFIG_HOME/duplicates-detector/config.toml`.
/// This actor performs all file I/O off the main thread.
actor ProfileManager {
    static let shared = ProfileManager()

    private let environmentResolver: ShellEnvironmentResolver

    init(environmentResolver: ShellEnvironmentResolver = .shared) {
        self.environmentResolver = environmentResolver
    }

    // MARK: - Path resolution (matching CLI config.py)

    /// Profiles directory resolved from the user's login shell XDG environment.
    func resolvedProfilesDirectory() async -> URL {
        await resolvedConfigBaseDirectory().appendingPathComponent("profiles")
    }

    /// Global config file resolved from the user's login shell XDG environment.
    func resolvedConfigFilePath() async -> URL {
        await resolvedConfigBaseDirectory().appendingPathComponent("config.toml")
    }

    /// Base config directory resolved via ``ShellEnvironmentResolver``.
    private func resolvedConfigBaseDirectory() async -> URL {
        await environmentResolver.configBaseDirectory()
    }

    /// Sync fallback for non-async contexts (reads process environment only).
    nonisolated static var profilesDirectory: URL {
        configBaseDirectory.appendingPathComponent("profiles")
    }

    /// Sync fallback for non-async contexts (reads process environment only).
    nonisolated static var configFilePath: URL {
        configBaseDirectory.appendingPathComponent("config.toml")
    }

    /// Sync fallback — process environment only.
    nonisolated private static var configBaseDirectory: URL {
        let base: String
        if let xdg = ProcessInfo.processInfo.environment["XDG_CONFIG_HOME"], !xdg.isEmpty {
            base = xdg
        } else {
            base = (NSHomeDirectory() as NSString).appendingPathComponent(".config")
        }
        return URL(fileURLWithPath: base).appendingPathComponent("duplicates-detector")
    }

    // MARK: - Profile name validation

    /// Allowed characters matching CLI's `_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")`.
    private nonisolated static let allowedCharacters = CharacterSet.alphanumerics
        .union(CharacterSet(charactersIn: "_.-"))

    /// Validate a profile name. Rejects empty, whitespace-padded, `..`, and special characters.
    nonisolated static func validateName(_ name: String) -> Bool {
        guard !name.isEmpty,
              name == name.trimmingCharacters(in: .whitespaces),
              !name.contains(".."),
              name.unicodeScalars.allSatisfy({ allowedCharacters.contains($0) })
        else { return false }
        return true
    }

    // MARK: - CRUD

    /// List all `.toml` files in the profiles directory, sorted by name.
    func listProfiles() async throws -> [ProfileEntry] {
        let dir = await resolvedProfilesDirectory()
        guard FileManager.default.fileExists(atPath: dir.path) else { return [] }

        let contents = try FileManager.default.contentsOfDirectory(
            at: dir, includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        )

        return contents
            .filter { $0.pathExtension == "toml" }
            .compactMap { url -> ProfileEntry? in
                let name = url.deletingPathExtension().lastPathComponent
                guard Self.validateName(name) else { return nil }
                let mtime = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
                return ProfileEntry(name: name, url: url, lastModified: mtime)
            }
            .sorted()
    }

    /// Load and parse a named profile.
    func loadProfile(name: String) async throws -> ProfileData {
        guard Self.validateName(name) else {
            throw ProfileManagerError.invalidName(name)
        }
        let url = await resolvedProfilesDirectory().appendingPathComponent("\(name).toml")
        let text: String
        do {
            text = try String(contentsOf: url, encoding: .utf8)
        } catch {
            throw ProfileManagerError.notFound(name)
        }
        let table = try TOMLTable(string: text)
        return Self.profileData(from: table)
    }

    /// Save a profile. Creates the profiles directory if needed.
    func saveProfile(name: String, data: ProfileData) async throws {
        guard Self.validateName(name) else {
            throw ProfileManagerError.invalidName(name)
        }
        let url = await resolvedProfilesDirectory().appendingPathComponent("\(name).toml")
        try writeTOML(data, to: url, comment: "duplicates-detector profile")
    }

    /// Delete a named profile.
    func deleteProfile(name: String) async throws {
        guard Self.validateName(name) else {
            throw ProfileManagerError.invalidName(name)
        }
        let url = await resolvedProfilesDirectory().appendingPathComponent("\(name).toml")
        do {
            try FileManager.default.removeItem(at: url)
        } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
            throw ProfileManagerError.notFound(name)
        }
    }

    // MARK: - CLI global config

    /// Whether the CLI's global `config.toml` exists on disk.
    func cliConfigExists() async -> Bool {
        let url = await resolvedConfigFilePath()
        return FileManager.default.fileExists(atPath: url.path)
    }

    /// Read the CLI's global `config.toml`.
    ///
    /// Returns an empty `ProfileData` both when the file is missing and when
    /// it contains no non-default keys. Use ``cliConfigExists()`` to
    /// distinguish the two cases before calling this.
    func loadCLIConfig() async throws -> ProfileData {
        let url = await resolvedConfigFilePath()
        guard FileManager.default.fileExists(atPath: url.path) else {
            return ProfileData()
        }
        let text = try String(contentsOf: url, encoding: .utf8)
        let table = try TOMLTable(string: text)
        return Self.profileData(from: table)
    }

    /// Write the CLI's global `config.toml`.
    func saveCLIConfig(_ data: ProfileData) async throws {
        let url = await resolvedConfigFilePath()
        try writeTOML(data, to: url, comment: "duplicates-detector configuration")
    }

    // MARK: - Shared write helper

    /// Serialize `data` as TOML and write atomically to `url`.
    private func writeTOML(_ data: ProfileData, to url: URL, comment: String) throws {
        let dir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        let table = Self.tomlTable(from: data)
        let header = "# \(comment)\n# Generated by: Duplicates Detector GUI\n# Location: \(url.path)\n\n"
        let content = header + table.convert()

        let tempURL = dir.appendingPathComponent(UUID().uuidString + ".tmp")
        try Data(content.utf8).write(to: tempURL)
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try FileManager.default.replaceItemAt(url, withItemAt: tempURL)
        } else {
            try FileManager.default.moveItem(at: tempURL, to: url)
        }
    }

    // MARK: - TOML -> ProfileData

    /// CLI TOML keys use snake_case: `hash_algo`, `content_strategy`, `no_metadata_cache`, etc.
    private static func profileData(from table: TOMLTable) -> ProfileData {
        var data = ProfileData()
        data.mode = table["mode"]?.string
        data.threshold = table["threshold"]?.int
        data.keep = table["keep"]?.string
        data.action = table["action"]?.string
        data.moveToDir = table["move_to_dir"]?.string
        data.content = table["content"]?.bool
        data.audio = table["audio"]?.bool
        data.workers = table["workers"]?.int
        data.sort = table["sort"]?.string
        data.limit = table["limit"]?.int
        data.minScore = table["min_score"]?.int
        data.group = table["group"]?.bool
        data.verbose = table["verbose"]?.bool
        data.embedThumbnails = table["embed_thumbnails"]?.bool
        data.contentMethod = table["content_method"]?.string
        data.rotationInvariant = table["rotation_invariant"]?.bool
        data.noMetadataCache = table["no_metadata_cache"]?.bool
        data.noContentCache = table["no_content_cache"]?.bool
        data.noAudioCache = table["no_audio_cache"]?.bool
        data.noRecursive = table["no_recursive"]?.bool
        data.cacheDir = table["cache_dir"]?.string
        data.extensions = table["extensions"]?.string
        data.ignoreFile = table["ignore_file"]?.string
        data.log = table["log"]?.string
        data.thumbnailSize = table["thumbnail_size"]?.string
        data.minSize = table["min_size"]?.string
        data.maxSize = table["max_size"]?.string
        data.minDuration = table["min_duration"]?.double ?? table["min_duration"]?.int.map(Double.init)
        data.maxDuration = table["max_duration"]?.double ?? table["max_duration"]?.int.map(Double.init)
        data.minResolution = table["min_resolution"]?.string
        data.maxResolution = table["max_resolution"]?.string
        data.minBitrate = table["min_bitrate"]?.string
        data.maxBitrate = table["max_bitrate"]?.string
        data.codec = table["codec"]?.string

        // CLI-only fields (round-tripped, not editable in GUI)
        data.format = table["format"]?.string
        data.jsonEnvelope = table["json_envelope"]?.bool
        data.quiet = table["quiet"]?.bool
        data.noColor = table["no_color"]?.bool
        data.machineProgress = table["machine_progress"]?.bool

        // Exclude: TOML array of strings
        if let arr = table["exclude"]?.array {
            data.exclude = (0..<arr.count).compactMap { arr[$0].string }
        }

        // Weights: TOML table
        // CLI canonical key is "file_size"; GUI uses "filesize" everywhere.
        if let weightsTable = table["weights"]?.table {
            var weights: [String: Double] = [:]
            for key in weightsTable.keys {
                if let val = weightsTable[key]?.double ?? weightsTable[key]?.int.map(Double.init) {
                    let guiKey = key == "file_size" ? "filesize" : key
                    weights[guiKey] = val
                }
            }
            if !weights.isEmpty { data.weights = weights }
        }

        return data
    }

    // MARK: - ProfileData -> TOML

    private static func tomlTable(from data: ProfileData) -> TOMLTable {
        let table = TOMLTable()

        if let v = data.mode { table["mode"] = v }
        if let v = data.threshold { table["threshold"] = v }
        if let v = data.keep { table["keep"] = v }
        if let v = data.action { table["action"] = v }
        if data.action == "move-to", let v = data.moveToDir, !v.isEmpty { table["move_to_dir"] = v }
        if let v = data.content { table["content"] = v }
        if let v = data.audio { table["audio"] = v }
        if let v = data.workers { table["workers"] = v }
        if let v = data.sort { table["sort"] = v }
        if let v = data.limit { table["limit"] = v }
        if let v = data.minScore { table["min_score"] = v }
        if let v = data.group { table["group"] = v }
        if let v = data.verbose { table["verbose"] = v }
        if let v = data.embedThumbnails { table["embed_thumbnails"] = v }
        if let v = data.contentMethod { table["content_method"] = v }
        if let v = data.rotationInvariant { table["rotation_invariant"] = v }
        if let v = data.noMetadataCache { table["no_metadata_cache"] = v }
        if let v = data.noContentCache { table["no_content_cache"] = v }
        if let v = data.noAudioCache { table["no_audio_cache"] = v }
        if let v = data.noRecursive { table["no_recursive"] = v }
        if let v = data.cacheDir { table["cache_dir"] = v }
        if let v = data.extensions { table["extensions"] = v }
        if let v = data.ignoreFile { table["ignore_file"] = v }
        if let v = data.log { table["log"] = v }
        if let v = data.thumbnailSize { table["thumbnail_size"] = v }
        if let v = data.minSize { table["min_size"] = v }
        if let v = data.maxSize { table["max_size"] = v }
        if let v = data.minDuration { table["min_duration"] = v }
        if let v = data.maxDuration { table["max_duration"] = v }
        if let v = data.minResolution { table["min_resolution"] = v }
        if let v = data.maxResolution { table["max_resolution"] = v }
        if let v = data.minBitrate { table["min_bitrate"] = v }
        if let v = data.maxBitrate { table["max_bitrate"] = v }
        if let v = data.codec { table["codec"] = v }

        // CLI-only fields (round-tripped, not editable in GUI)
        if let v = data.format { table["format"] = v }
        if let v = data.jsonEnvelope { table["json_envelope"] = v }
        if let v = data.quiet { table["quiet"] = v }
        if let v = data.noColor { table["no_color"] = v }
        if let v = data.machineProgress { table["machine_progress"] = v }

        if let excludes = data.exclude {
            table["exclude"] = excludes
        }

        if let weights = data.weights, !weights.isEmpty {
            let weightsTable = TOMLTable()
            for (key, value) in weights.sorted(by: { $0.key < $1.key }) {
                // GUI uses "filesize"; CLI canonical TOML key is "file_size".
                let tomlKey = key == "filesize" ? "file_size" : key
                if value.isWholeNumber {
                    weightsTable[tomlKey] = Int(value)
                } else {
                    weightsTable[tomlKey] = value
                }
            }
            table["weights"] = weightsTable
        }

        return table
    }
}

// MARK: - Errors

enum ProfileManagerError: Error, LocalizedError {
    case invalidName(String)
    case notFound(String)

    var errorDescription: String? {
        switch self {
        case .invalidName(let name):
            "Invalid profile name: \"\(name)\". Use letters, digits, underscores, hyphens, or dots."
        case .notFound(let name):
            "Profile \"\(name)\" not found."
        }
    }
}
