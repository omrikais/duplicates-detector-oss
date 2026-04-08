import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - CacheManager Default Directory

@Suite("CacheManager default directory resolution")
struct CacheManagerDirectoryTests {
    @Test("defaultCacheDirectory uses XDG_CACHE_HOME when set")
    func usesXDGCacheHome() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CACHE_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CACHE_HOME", old, 1) } else { unsetenv("XDG_CACHE_HOME") }
        }

        setenv("XDG_CACHE_HOME", "/tmp/test-xdg-cache", 1)
        let dir = CacheManager.defaultCacheDirectory
        #expect(dir.path.contains("/tmp/test-xdg-cache/duplicates-detector"))
    }

    @Test("defaultCacheDirectory falls back to ~/.cache when XDG_CACHE_HOME is empty")
    func fallsBackToHomeDotCache() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CACHE_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CACHE_HOME", old, 1) } else { unsetenv("XDG_CACHE_HOME") }
        }

        setenv("XDG_CACHE_HOME", "", 1)
        let dir = CacheManager.defaultCacheDirectory
        #expect(dir.path.contains(".cache/duplicates-detector"))
    }

    @Test("defaultCacheDirectory falls back to ~/.cache when XDG_CACHE_HOME is unset")
    func fallsBackToHomeDotCacheUnset() {
        let oldXDG = ProcessInfo.processInfo.environment["XDG_CACHE_HOME"]
        defer {
            if let old = oldXDG { setenv("XDG_CACHE_HOME", old, 1) } else { unsetenv("XDG_CACHE_HOME") }
        }

        unsetenv("XDG_CACHE_HOME")
        let dir = CacheManager.defaultCacheDirectory
        #expect(dir.path.contains(".cache/duplicates-detector"))
    }
}

// MARK: - CacheManager File Constants

@Suite("CacheManager filename constants")
struct CacheManagerConstantsTests {
    @Test("metadataFilename matches CLI cache.py")
    func metadataFilename() {
        #expect(CacheManager.metadataFilename == "metadata.json")
    }

    @Test("contentHashFilename matches CLI cache.py")
    func contentHashFilename() {
        #expect(CacheManager.contentHashFilename == "content-hashes.json")
    }

    @Test("audioFingerprintFilename matches CLI cache.py")
    func audioFingerprintFilename() {
        #expect(CacheManager.audioFingerprintFilename == "audio-fingerprints.json")
    }
}

// MARK: - CacheManager cacheSizes

@Suite("CacheManager cacheSizes behavior")
struct CacheManagerSizesTests {
    private func makeTempCacheDir() -> URL {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cache-test-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test("cacheSizes returns nil for all files in nonexistent directory")
    func allNilForNonexistentDir() {
        let fakeDir = URL(fileURLWithPath: "/tmp/nonexistent-\(UUID().uuidString)")
        let sizes = CacheManager.cacheSizes(directory: fakeDir)
        #expect(sizes.metadata == nil)
        #expect(sizes.content == nil)
        #expect(sizes.audio == nil)
    }

    @Test("cacheSizes returns nil for missing files in existing directory")
    func nilForMissingFiles() {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let sizes = CacheManager.cacheSizes(directory: dir)
        #expect(sizes.metadata == nil)
        #expect(sizes.content == nil)
        #expect(sizes.audio == nil)
    }

    @Test("cacheSizes returns correct size for present files")
    func correctSizeForPresentFiles() {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Create a metadata cache file with known content
        let content = Data("{\"version\": 2}".utf8)
        let metaPath = dir.appendingPathComponent(CacheManager.metadataFilename)
        FileManager.default.createFile(atPath: metaPath.path, contents: content)

        let sizes = CacheManager.cacheSizes(directory: dir)
        #expect(sizes.metadata == Int64(content.count))
        #expect(sizes.content == nil)
        #expect(sizes.audio == nil)
    }

    @Test("cacheSizes returns sizes for all three files when present")
    func allThreeFilesPresent() {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let metaContent = Data("{\"meta\": true}".utf8)
        let contentContent = Data("{\"hashes\": []}".utf8)
        let audioContent = Data("{\"fingerprints\": []}".utf8)

        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path,
            contents: metaContent
        )
        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.contentHashFilename).path,
            contents: contentContent
        )
        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.audioFingerprintFilename).path,
            contents: audioContent
        )

        let sizes = CacheManager.cacheSizes(directory: dir)
        #expect(sizes.metadata == Int64(metaContent.count))
        #expect(sizes.content == Int64(contentContent.count))
        #expect(sizes.audio == Int64(audioContent.count))
    }
}

// MARK: - CacheManager totalCacheSize

@Suite("CacheManager totalCacheSize")
struct CacheManagerTotalSizeTests {
    @Test("totalCacheSize is 0 for nonexistent directory")
    func zeroForNonexistentDir() {
        let fakeDir = URL(fileURLWithPath: "/tmp/nonexistent-\(UUID().uuidString)")
        #expect(CacheManager.totalCacheSize(directory: fakeDir) == 0)
    }

    @Test("totalCacheSize sums all present file sizes")
    func sumsAllFiles() {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cache-total-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let data1 = Data(repeating: 0x41, count: 100)
        let data2 = Data(repeating: 0x42, count: 200)

        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path,
            contents: data1
        )
        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.contentHashFilename).path,
            contents: data2
        )

        #expect(CacheManager.totalCacheSize(directory: dir) == 300)
    }
}

// MARK: - CacheManager clearCache

@Suite("CacheManager clearCache behavior")
struct CacheManagerClearTests {
    private func makeTempCacheDir() -> URL {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cache-clear-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test("clearCache on nonexistent file is a no-op (no throw)")
    func clearCacheNoOpForMissing() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Should not throw
        try CacheManager.clearCache(filename: CacheManager.metadataFilename, directory: dir)
    }

    @Test("clearCache removes the specified file")
    func clearCacheRemovesFile() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let filePath = dir.appendingPathComponent(CacheManager.metadataFilename)
        FileManager.default.createFile(atPath: filePath.path, contents: Data("test".utf8))
        #expect(FileManager.default.fileExists(atPath: filePath.path))

        try CacheManager.clearCache(filename: CacheManager.metadataFilename, directory: dir)

        #expect(!FileManager.default.fileExists(atPath: filePath.path))
    }

    @Test("clearCache does not remove other cache files")
    func clearCacheLeavesOtherFiles() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let metaPath = dir.appendingPathComponent(CacheManager.metadataFilename)
        let contentPath = dir.appendingPathComponent(CacheManager.contentHashFilename)
        FileManager.default.createFile(atPath: metaPath.path, contents: Data("meta".utf8))
        FileManager.default.createFile(atPath: contentPath.path, contents: Data("content".utf8))

        try CacheManager.clearCache(filename: CacheManager.metadataFilename, directory: dir)

        #expect(!FileManager.default.fileExists(atPath: metaPath.path))
        #expect(FileManager.default.fileExists(atPath: contentPath.path))
    }
}

// MARK: - CacheManager clearAllCaches

@Suite("CacheManager clearAllCaches behavior")
struct CacheManagerClearAllTests {
    private func makeTempCacheDir() -> URL {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cache-clearall-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test("clearAllCaches removes all three cache files")
    func removesAllThreeFiles() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        for name in [CacheManager.metadataFilename, CacheManager.contentHashFilename, CacheManager.audioFingerprintFilename] {
            FileManager.default.createFile(
                atPath: dir.appendingPathComponent(name).path,
                contents: Data("data".utf8)
            )
        }

        // Verify all exist
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path))
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.contentHashFilename).path))
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.audioFingerprintFilename).path))

        try CacheManager.clearAllCaches(directory: dir)

        // All should be gone
        #expect(!FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path))
        #expect(!FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.contentHashFilename).path))
        #expect(!FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.audioFingerprintFilename).path))
    }

    @Test("clearAllCaches is safe when no files exist")
    func clearAllNoOpWhenEmpty() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Should not throw
        try CacheManager.clearAllCaches(directory: dir)
    }

    @Test("clearAllCaches does not remove non-cache files in the directory")
    func preservesOtherFiles() throws {
        let dir = makeTempCacheDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let otherPath = dir.appendingPathComponent("other-file.txt")
        FileManager.default.createFile(atPath: otherPath.path, contents: Data("keep me".utf8))
        FileManager.default.createFile(
            atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path,
            contents: Data("meta".utf8)
        )

        try CacheManager.clearAllCaches(directory: dir)

        #expect(FileManager.default.fileExists(atPath: otherPath.path), "Non-cache files should not be removed")
        #expect(!FileManager.default.fileExists(atPath: dir.appendingPathComponent(CacheManager.metadataFilename).path))
    }
}

// MARK: - Photos Library Cache

@Suite("CacheManager Photos cache methods")
struct CacheManagerPhotosCacheTests {
    @Test("photosCacheSize returns non-negative value")
    func photosCacheSize() async {
        let size = await CacheManager.photosCacheSize()
        #expect(size >= 0)
    }

    @Test("thumbnailCacheSize returns non-negative value")
    func thumbnailCacheSize() {
        let size = CacheManager.thumbnailCacheSize()
        #expect(size >= 0)
    }

    @Test("clearThumbnailCache does not throw when directory is absent")
    func clearThumbnailCacheNoOp() throws {
        // Should not throw even if the thumbnails directory doesn't exist
        try CacheManager.clearThumbnailCache()
    }
}
