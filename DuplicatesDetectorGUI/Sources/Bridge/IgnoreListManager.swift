import Foundation

/// Reads and writes the CLI's ignore-list JSON file.
///
/// All file-mutating operations are serialized by the actor's executor,
/// preventing read-modify-write races during rapid keyboard-driven
/// ignore actions.
///
/// The Python `ignorelist.py` stores a flat JSON array of sorted two-element
/// arrays of resolved absolute paths:
/// ```json
/// [
///   ["/absolute/path/a", "/absolute/path/b"],
///   ["/absolute/path/c", "/absolute/path/d"]
/// ]
/// ```
///
/// File location: `$XDG_DATA_HOME/duplicates-detector/ignored-pairs.json`
/// (fallback: `~/.local/share/duplicates-detector/ignored-pairs.json`).
actor IgnoreListManager {
    static let shared = IgnoreListManager()

    /// Default path resolved from the user's login shell XDG environment.
    func resolvedDefaultPath() async -> URL {
        await ShellEnvironmentResolver.shared.dataBaseDirectory()
            .appendingPathComponent("ignored-pairs.json")
    }

    /// Sync fallback (reads process environment only — may be wrong for Finder-launched apps).
    nonisolated static var defaultPath: URL {
        let base: String
        if let xdg = ProcessInfo.processInfo.environment["XDG_DATA_HOME"], !xdg.isEmpty {
            base = xdg
        } else {
            base = (NSHomeDirectory() as NSString).appendingPathComponent(".local/share")
        }
        return URL(fileURLWithPath: base)
            .appendingPathComponent("duplicates-detector")
            .appendingPathComponent("ignored-pairs.json")
    }

    /// Read the ignore list. Returns empty array if file doesn't exist or is corrupt.
    func load(from url: URL? = nil) -> [[String]] {
        let path = url ?? Self.defaultPath
        guard FileManager.default.fileExists(atPath: path.path) else { return [] }
        guard let data = try? Data(contentsOf: path) else { return [] }
        guard let parsed = try? JSONSerialization.jsonObject(with: data) as? [[String]] else { return [] }
        return parsed.filter { $0.count == 2 }
    }

    /// Append a pair and write atomically. Reads existing entries first.
    func addPair(_ pathA: String, _ pathB: String, to url: URL? = nil) throws {
        let dest = url ?? Self.defaultPath
        let sorted = normalizedPair(pathA, pathB)

        var entries = load(from: dest)
        if entries.contains(where: { $0 == sorted }) { return }

        entries.append(sorted)
        entries.sort { a, b in
            if a[0] != b[0] { return a[0] < b[0] }
            return a[1] < b[1]
        }

        try writeAtomically(entries, to: dest)
    }

    /// Remove a specific pair from the ignore list. No-op if the pair is not present.
    func removePair(_ pathA: String, _ pathB: String, from url: URL? = nil) throws {
        let dest = url ?? Self.defaultPath
        let sorted = normalizedPair(pathA, pathB)

        var entries = load(from: dest)
        let before = entries.count
        entries.removeAll { $0 == sorted }
        guard entries.count < before else { return }

        try writeAtomically(entries, to: dest)
    }

    /// Remove all entries from the ignore list.
    func clearAll(at url: URL? = nil) throws {
        let dest = url ?? Self.defaultPath
        guard FileManager.default.fileExists(atPath: dest.path) else { return }
        try writeAtomically([], to: dest)
    }

    /// Return the number of ignored pairs.
    func count(at url: URL? = nil) -> Int {
        load(from: url).count
    }

    // MARK: - Private

    /// Resolve symlinks and sort a pair of paths for ignore-list storage.
    /// Photos URIs (`photos://asset/…`) are kept verbatim — `URL(fileURLWithPath:)`
    /// would treat the scheme as a relative path component, corrupting the URI.
    private func normalizedPair(_ pathA: String, _ pathB: String) -> [String] {
        let a = pathA.isPhotosAssetURI
            ? pathA
            : URL(fileURLWithPath: pathA).resolvingSymlinksInPath().path
        let b = pathB.isPhotosAssetURI
            ? pathB
            : URL(fileURLWithPath: pathB).resolvingSymlinksInPath().path
        return a <= b ? [a, b] : [b, a]
    }

    /// Serialize entries as JSON and write atomically (temp file + replace).
    private func writeAtomically(_ entries: [[String]], to dest: URL) throws {
        let jsonData = try JSONSerialization.data(
            withJSONObject: entries,
            options: [.prettyPrinted, .sortedKeys]
        )
        let directory = dest.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let tempURL = directory.appendingPathComponent(UUID().uuidString + ".tmp")
        try jsonData.write(to: tempURL, options: .atomic)
        if FileManager.default.fileExists(atPath: dest.path) {
            _ = try FileManager.default.replaceItemAt(dest, withItemAt: tempURL)
        } else {
            try FileManager.default.moveItem(at: tempURL, to: dest)
        }
    }
}
