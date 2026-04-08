import Foundation
import os

/// Manages security-scoped bookmarks for directories selected via NSOpenPanel.
///
/// Stores bookmark data in UserDefaults keyed by path. On app launch,
/// restores bookmarks and calls startAccessingSecurityScopedResource().
@Observable @MainActor
final class BookmarkManager {
    private static let bookmarkKey = "dd.securityScopedBookmarks"
    private let log = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "BookmarkManager")

    /// Paths currently being accessed via security-scoped bookmarks.
    private var accessedPaths: Set<String> = []

    /// Save a security-scoped bookmark for a URL obtained from NSOpenPanel.
    func saveBookmark(for url: URL) {
        do {
            let data = try url.bookmarkData(
                options: .withSecurityScope,
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            var bookmarks = storedBookmarks()
            bookmarks[url.path] = data
            UserDefaults.standard.set(bookmarks, forKey: Self.bookmarkKey)
        } catch {
            log.error("Failed to create bookmark for \(url.path): \(error)")
        }
    }

    /// Restore all saved bookmarks on launch.
    func restoreBookmarks() {
        let bookmarks = storedBookmarks()
        for (path, data) in bookmarks {
            var stale = false
            guard let url = try? URL(
                resolvingBookmarkData: data,
                options: .withSecurityScope,
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            ) else { continue }
            if stale {
                saveBookmark(for: url)
            }
            if url.startAccessingSecurityScopedResource() {
                accessedPaths.insert(path)
            }
        }
    }

    /// Stop accessing and remove the bookmark for a specific path.
    func removeBookmark(for path: String) {
        if accessedPaths.contains(path) {
            let bookmarks = storedBookmarks()
            if let data = bookmarks[path] {
                var stale = false
                if let url = try? URL(
                    resolvingBookmarkData: data,
                    options: .withSecurityScope,
                    relativeTo: nil,
                    bookmarkDataIsStale: &stale
                ) {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            accessedPaths.remove(path)
        }
        var bookmarks = storedBookmarks()
        bookmarks.removeValue(forKey: path)
        UserDefaults.standard.set(bookmarks, forKey: Self.bookmarkKey)
    }

    /// Stop accessing all security-scoped resources.
    func releaseAll() {
        let bookmarks = storedBookmarks()
        for (path, data) in bookmarks where accessedPaths.contains(path) {
            var stale = false
            if let url = try? URL(
                resolvingBookmarkData: data,
                options: .withSecurityScope,
                relativeTo: nil,
                bookmarkDataIsStale: &stale
            ) {
                url.stopAccessingSecurityScopedResource()
            }
        }
        accessedPaths.removeAll()
    }

    private func storedBookmarks() -> [String: Data] {
        UserDefaults.standard.dictionary(forKey: Self.bookmarkKey) as? [String: Data] ?? [:]
    }
}
