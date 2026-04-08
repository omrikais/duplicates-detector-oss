// Sources/Bridge/BackgroundScanEngine.swift
import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ImageIO
import os

private let logger = Logger(subsystem: "com.dd.background-scan", category: "engine")

/// Consumes file events from DirectoryWatcher, extracts metadata via ffprobe,
/// scores new files against a known set, and emits DuplicateAlerts.
actor BackgroundScanEngine {

    // MARK: - Internal state

    private var knownFiles: [KnownFile] = []
    private var config: ScanConfig
    private var sessionID: UUID
    private var alertContinuation: AsyncStream<DuplicateAlert>.Continuation?
    private var processingTask: Task<Void, Never>?
    private var eventContinuation: AsyncStream<DirectoryWatcher.FileEvent>.Continuation?

    private let shellEnvironment: [String: String]

    // Stats counters
    private var filesDetected: Int = 0
    private var duplicatesFound: Int = 0

    // Dedup guard for FSEvents bursts
    private var processingPaths: Set<String> = []

    // Secondary indexes for fast rename detection — avoids O(n) linear scan
    // with filesystem stat per entry. Maintained by addToIndex/removeFromIndex.
    private var inodeIndex: [UInt64: String] = [:]   // inode → path
    private var sizeIndex: [Int: Set<String>] = [:]  // fileSize → paths

    /// O(1) set of all tracked file paths — used to skip already-known files
    /// during directory rescan (prevents re-scoring every file on each event).
    private var knownPaths: Set<String> = []

    /// Whether the full directory inventory has been merged into the engine.
    /// Directory rescan events are buffered until this is true — before it,
    /// `knownPaths` only contains scan-result pairs, so rescanning a directory
    /// would incorrectly treat every non-paired file as a new arrival.
    private var inventoryComplete: Bool = false

    /// Directory events received before the inventory completed. Replayed
    /// by `markInventoryComplete()` so files added during the crawl window
    /// are not silently dropped on directory-event-only volumes.
    private var pendingDirectoryEvents: [URL] = []

    // MARK: - Init

    init(
        config: ScanConfig,
        sessionID: UUID,
        knownFiles: [KnownFile] = [],
        shellEnvironment: [String: String] = [:]
    ) {
        self.config = config
        self.sessionID = sessionID
        self.knownFiles = knownFiles
        self.shellEnvironment = shellEnvironment
        // Build initial indexes from provided known files
        var inodes: [UInt64: String] = [:]
        var sizes: [Int: Set<String>] = [:]
        var paths: Set<String> = []
        for file in knownFiles {
            if let inode = file.inode {
                inodes[inode] = file.path
            }
            sizes[file.metadata.fileSize, default: []].insert(file.path)
            paths.insert(file.path)
        }
        self.inodeIndex = inodes
        self.sizeIndex = sizes
        self.knownPaths = paths
    }

    // MARK: - Lifecycle

    /// Starts the engine and returns a stream of duplicate alerts.
    func start() -> AsyncStream<DuplicateAlert> {
        let (alertStream, alertCont) = AsyncStream<DuplicateAlert>.makeStream()
        self.alertContinuation = alertCont

        let (eventStream, eventCont) = AsyncStream<DirectoryWatcher.FileEvent>.makeStream()
        self.eventContinuation = eventCont

        let weights = Self.resolveWeights(config.weights, mode: config.mode, content: config.content, audio: config.audio)
        let threshold = config.threshold
        let sid = sessionID

        processingTask = Task { [weak self] in
            for await event in eventStream {
                guard !Task.isCancelled else { break }
                guard let self else {
                    logger.warning("BackgroundScanEngine deallocated without stop() — dropping remaining events")
                    break
                }
                await self.processEvent(
                    event,
                    weights: weights,
                    threshold: threshold,
                    sessionID: sid
                )
            }
        }

        return alertStream
    }

    /// Ingests a file event into the processing queue.
    /// Deduplicates rapid FSEvents bursts for the same path.
    /// No-op if the engine is not running (avoids leaking paths into processingPaths).
    func ingest(_ event: DirectoryWatcher.FileEvent) {
        guard eventContinuation != nil else { return }

        switch event {
        case .created(let u):
            let path = u.path
            // The watcher now yields events for all file-level FSEvents (not
            // just ItemCreated) to handle volumes that report new files as
            // Modified. Filter out modifications of the SAME file (same inode)
            // to avoid full scoring cycles on every touch. But allow through
            // if the file was replaced (different inode) — delete-then-recreate
            // at the same path must be detected.
            if knownPaths.contains(path) {
                guard fileWasReplaced(at: path) else { return }
                evictKnownFile(at: path)
            }
            guard !processingPaths.contains(path) else { return }
            processingPaths.insert(path)
            eventContinuation?.yield(event)

        case .renamed(let u):
            let path = u.path
            guard !processingPaths.contains(path) else { return }
            processingPaths.insert(path)
            eventContinuation?.yield(event)

        case .directoryChanged:
            // Directory events are not deduped by path — each must trigger
            // a rescan to catch newly added files.
            eventContinuation?.yield(event)
        }
    }

    /// Stops the engine and finishes the alert stream.
    func stop() {
        processingTask?.cancel()
        processingTask = nil
        eventContinuation?.finish()
        eventContinuation = nil
        alertContinuation?.finish()
        alertContinuation = nil
        processingPaths.removeAll()
        knownPaths.removeAll()
        pendingDirectoryEvents.removeAll()
    }

    /// Merges additional known files into the baseline, skipping paths already tracked.
    /// Used to upgrade from a fast initial baseline (scan results) to a full directory inventory.
    ///
    /// Updates the seen-path set as it appends so that duplicate paths within the
    /// incoming batch (e.g. from overlapping watched directories) are also rejected.
    func mergeKnownFiles(_ files: [KnownFile]) {
        for file in files where !knownPaths.contains(file.path) {
            knownFiles.append(file)
            addToIndex(file)
        }
    }

    /// Marks the initial directory inventory as complete and replays any
    /// directory events that arrived during the crawl window.
    ///
    /// Before this is called, `.directoryChanged` events are buffered to
    /// avoid treating pre-existing files as new arrivals. After the full
    /// inventory populates `knownPaths`, the buffered events are processed
    /// so files added during the crawl are not silently missed.
    func markInventoryComplete() async {
        inventoryComplete = true
        // Deduplicate buffered directories — the same parent may have fired
        // multiple events during the crawl; only one rescan is needed since
        // it reads the final filesystem state.
        let unique = Set(pendingDirectoryEvents.map(\.path))
        pendingDirectoryEvents.removeAll()
        guard !unique.isEmpty else { return }
        let weights = Self.resolveWeights(
            config.weights, mode: config.mode, content: config.content, audio: config.audio)
        for dirPath in unique {
            guard !Task.isCancelled else { break }
            let dirURL = URL(filePath: dirPath, directoryHint: .isDirectory)
            await processDirectoryChange(
                dirURL, weights: weights, threshold: config.threshold,
                sessionID: self.sessionID)
        }
    }

    /// Current watch statistics.
    var stats: WatchStats {
        WatchStats(
            filesDetected: filesDetected,
            duplicatesFound: duplicatesFound,
            trackedFiles: knownFiles.count
        )
    }

    // MARK: - Index Maintenance

    private func addToIndex(_ file: KnownFile) {
        if let inode = file.inode {
            inodeIndex[inode] = file.path
        }
        sizeIndex[file.metadata.fileSize, default: []].insert(file.path)
        knownPaths.insert(file.path)
    }

    private func removeFromIndex(_ file: KnownFile) {
        if let inode = file.inode {
            if inodeIndex[inode] == file.path {
                inodeIndex.removeValue(forKey: inode)
            }
        }
        sizeIndex[file.metadata.fileSize]?.remove(file.path)
        knownPaths.remove(file.path)
    }

    /// Returns true if the file at `path` was replaced (different inode or
    /// file size) since it was first tracked, indicating a delete-then-recreate.
    /// Returns true when comparison is inconclusive (can't stat) so the caller
    /// errs on the side of processing the event.
    private func fileWasReplaced(at path: String) -> Bool {
        guard let knownFile = knownFiles.first(where: { $0.path == path }) else {
            return true
        }
        // Inode comparison is the strongest signal (O(1) stat).
        if let currentInode = Self.fileInode(at: path),
           let knownInode = knownFile.inode {
            return currentInode != knownInode
        }
        // Fallback: compare file size when inodes are unavailable.
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let currentSize = attrs[.size] as? Int else {
            return true
        }
        return currentSize != knownFile.metadata.fileSize
    }

    /// Removes the known-file entry at `path` from all indexes and the array.
    private func evictKnownFile(at path: String) {
        if let idx = knownFiles.firstIndex(where: { $0.path == path }) {
            removeFromIndex(knownFiles[idx])
            knownFiles.remove(at: idx)
        }
    }

    // MARK: - Rename detection

    /// Index-accelerated rename detection. Uses `inodeIndex` for O(1) inode
    /// lookup, falling back to `sizeIndex` for O(k) size-based matching where
    /// k is typically 1–3. Only calls `fileExists` on matched candidates, not
    /// the entire known-file set.
    private func findStaleEntryIndexed(
        forNewPath newPath: String,
        fileSize: Int,
        inode: UInt64?
    ) -> Int? {
        // Try inode match first (strongest signal, O(1) lookup + 1 stat)
        if let inode, let candidatePath = inodeIndex[inode],
           candidatePath != newPath,
           !FileManager.default.fileExists(atPath: candidatePath) {
            return knownFiles.firstIndex(where: { $0.path == candidatePath })
        }

        // Fall back to file size match (O(k) where k = files with same size)
        if let candidates = sizeIndex[fileSize] {
            for candidatePath in candidates {
                guard candidatePath != newPath,
                      !FileManager.default.fileExists(atPath: candidatePath) else { continue }
                return knownFiles.firstIndex(where: { $0.path == candidatePath })
            }
        }

        return nil
    }

    /// Finds a stale (non-existent) known-file entry matching the new file,
    /// indicating a rename/move rather than a new file.
    ///
    /// When both entries have inode numbers, matches on inode (strongest signal).
    /// Falls back to file size matching when inodes are unavailable.
    ///
    /// This is the linear-scan variant used by unit tests (injectable `fileExistsCheck`).
    /// Production code uses ``findStaleEntryIndexed`` for O(1) inode / O(k) size lookups.
    nonisolated static func findStaleEntry(
        forNewPath newPath: String,
        fileSize: Int,
        inode: UInt64? = nil,
        in known: [KnownFile],
        fileExistsCheck: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> Int? {
        for (index, entry) in known.enumerated() {
            guard entry.path != newPath,
                  !fileExistsCheck(entry.path) else { continue }
            // Prefer inode match (survives same-size collisions)
            if let knownInode = entry.inode, let newInode = inode {
                if knownInode == newInode { return index }
            } else if entry.metadata.fileSize == fileSize {
                return index
            }
        }
        return nil
    }

    /// Returns the inode number for a file, or nil on failure.
    nonisolated static func fileInode(at path: String) -> UInt64? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let inode = attrs[.systemFileNumber] as? UInt64 else { return nil }
        return inode
    }

    // MARK: - Event processing

    private func processEvent(
        _ event: DirectoryWatcher.FileEvent,
        weights: [String: Double],
        threshold: Int,
        sessionID: UUID
    ) async {
        // Directory-level events: rescan the directory for files not yet tracked.
        if case .directoryChanged(let dirURL) = event {
            await processDirectoryChange(
                dirURL, weights: weights, threshold: threshold, sessionID: sessionID)
            return
        }

        let url: URL
        let isRename: Bool
        switch event {
        case .created(let u):
            url = u
            isRename = false
        case .renamed(let u):
            url = u
            isRename = true
        case .directoryChanged:
            return // Already handled above
        }

        defer { processingPaths.remove(url.path) }

        filesDetected += 1

        // Retry metadata extraction up to 3 times with increasing delays.
        // FSEvents with kFSEventStreamCreateFlagNoDefer can fire before the
        // file is fully written; subsequent .modified events are not handled
        // by the watcher, so we must retry here.
        var metadata: FileMetadata?
        for attempt in 0..<3 {
            if attempt > 0 {
                try? await Task.sleep(for: .seconds(Double(attempt)))
            }
            metadata = await Self.extractMetadata(
                from: url,
                mode: self.config.mode,
                environment: self.shellEnvironment
            )
            if metadata != nil { break }
        }
        guard let metadata else { return }

        let inode = Self.fileInode(at: url.path)

        // In auto mode, determine whether this file is image, video, or audio
        // so we can prevent cross-type scoring.
        let effectiveMode: ScanMode? = Self.resolveEffectiveMode(
            metadata: metadata, configMode: self.config.mode)

        // For renames: check if this is an existing file that moved.
        // If so, update the known entry in-place and skip scoring.
        if isRename {
            if let staleIndex = findStaleEntryIndexed(
                forNewPath: url.path,
                fileSize: metadata.fileSize,
                inode: inode
            ) {
                let oldFile = self.knownFiles[staleIndex]
                let newFile = KnownFile(
                    path: url.path, metadata: metadata, inode: inode,
                    effectiveMode: effectiveMode)
                removeFromIndex(oldFile)
                self.knownFiles[staleIndex] = newFile
                addToIndex(newFile)
                return
            }
            // No stale match — fall through to treat as a new file
        }

        let candidates = Self.bucketCandidates(
            newDuration: metadata.duration,
            newEffectiveMode: effectiveMode,
            knownFiles: self.knownFiles
        )
        let alerts = Self.scoreNewFile(
            newPath: url.path,
            newMetadata: metadata,
            candidates: candidates,
            weights: weights,
            threshold: threshold,
            sessionID: sessionID
        )

        for alert in alerts {
            // Skip alerts where the matched file no longer exists — the inventory
            // may contain stale entries for files deleted/moved after the scan.
            guard FileManager.default.fileExists(atPath: alert.matchedFile.path) else { continue }
            duplicatesFound += 1
            alertContinuation?.yield(alert)
        }

        let newFile = KnownFile(
            path: url.path, metadata: metadata, inode: inode,
            effectiveMode: effectiveMode)
        self.knownFiles.append(newFile)
        addToIndex(newFile)
    }

    // MARK: - Directory rescan

    /// Rescans a directory tree for files not yet tracked by the engine.
    ///
    /// Called when FSEvents delivers a directory-level event instead of
    /// individual file events (common on external/non-APFS volumes, or
    /// when the kernel event queue overflows). Uses recursive enumeration
    /// because `kFSEventStreamEventFlagMustScanSubDirs` and parent-directory
    /// coalescing both require scanning the full subtree.
    ///
    /// Deferred until the initial directory inventory has been merged —
    /// before that, `knownPaths` only contains scan-result pairs, so a
    /// rescan would incorrectly treat every non-paired file as new.
    private func processDirectoryChange(
        _ dirURL: URL,
        weights: [String: Double],
        threshold: Int,
        sessionID: UUID
    ) async {
        guard inventoryComplete else {
            pendingDirectoryEvents.append(dirURL)
            return
        }

        let extensions = DirectoryWatcher.extensionsForMode(self.config.mode)
        let fm = FileManager.default

        // Collect candidate files up front — DirectoryEnumerator is not
        // usable across await suspension points (Sendable requirement).
        let candidates = Self.enumerateFiles(in: [dirURL], extensions: extensions)
            .filter { !knownPaths.contains($0.path) }

        for fileURL in candidates {
            guard !Task.isCancelled else { break }

            let path = fileURL.path

            // Retry metadata extraction — on directory-event-only volumes no
            // later file-level event is guaranteed, so we must tolerate files
            // that are still being written (same retry logic as processEvent).
            var metadata: FileMetadata?
            for attempt in 0..<3 {
                if attempt > 0 {
                    try? await Task.sleep(for: .seconds(Double(attempt)))
                }
                metadata = await Self.extractMetadata(
                    from: fileURL, mode: self.config.mode, environment: self.shellEnvironment)
                if metadata != nil { break }
            }
            guard let metadata else { continue }
            let inode = Self.fileInode(at: path)

            // Check for rename before treating as a new file. Directory-level
            // events don't distinguish creates from renames, so we use the
            // full rename detection (inode + size fallback) to detect moved
            // files on all volume types.
            if let staleIndex = findStaleEntryIndexed(
                forNewPath: path, fileSize: metadata.fileSize, inode: inode
            ) {
                let effectiveMode = Self.resolveEffectiveMode(
                    metadata: metadata, configMode: self.config.mode)
                let oldFile = knownFiles[staleIndex]
                let newFile = KnownFile(
                    path: path, metadata: metadata, inode: inode,
                    effectiveMode: effectiveMode)
                removeFromIndex(oldFile)
                knownFiles[staleIndex] = newFile
                addToIndex(newFile)
                continue
            }

            // No rename detected — score as a genuinely new file. Inlined
            // here (rather than delegating to processEvent) to reuse the
            // metadata we already extracted and avoid a redundant extraction.
            filesDetected += 1
            let effectiveMode = Self.resolveEffectiveMode(
                metadata: metadata, configMode: self.config.mode)
            let candidates = Self.bucketCandidates(
                newDuration: metadata.duration,
                newEffectiveMode: effectiveMode,
                knownFiles: self.knownFiles
            )
            let alerts = Self.scoreNewFile(
                newPath: path,
                newMetadata: metadata,
                candidates: candidates,
                weights: weights,
                threshold: threshold,
                sessionID: sessionID
            )
            for alert in alerts {
                guard FileManager.default.fileExists(atPath: alert.matchedFile.path) else { continue }
                duplicatesFound += 1
                alertContinuation?.yield(alert)
            }
            let newFile = KnownFile(
                path: path, metadata: metadata, inode: inode,
                effectiveMode: effectiveMode)
            knownFiles.append(newFile)
            addToIndex(newFile)
        }
    }

    // MARK: - Static scoring functions

    /// Levenshtein edit distance between two strings.
    nonisolated static func levenshteinDistance(_ a: String, _ b: String) -> Int {
        let a = Array(a)
        let b = Array(b)
        let m = a.count
        let n = b.count

        if m == 0 { return n }
        if n == 0 { return m }

        var prev = Array(0...n)
        var curr = [Int](repeating: 0, count: n + 1)

        for i in 1...m {
            curr[0] = i
            for j in 1...n {
                let cost = a[i - 1] == b[j - 1] ? 0 : 1
                curr[j] = min(
                    prev[j] + 1,       // deletion
                    curr[j - 1] + 1,   // insertion
                    prev[j - 1] + cost  // substitution
                )
            }
            swap(&prev, &curr)
        }
        return prev[n]
    }

    /// Filename similarity score (0.0–1.0). Case-insensitive, extensions stripped.
    nonisolated static func filenameSimilarity(_ pathA: String, _ pathB: String) -> Double {
        let nameA = URL(filePath: pathA).deletingPathExtension().lastPathComponent.lowercased()
        let nameB = URL(filePath: pathB).deletingPathExtension().lastPathComponent.lowercased()

        if nameA.isEmpty && nameB.isEmpty { return 1.0 }
        let maxLen = max(nameA.count, nameB.count)
        if maxLen == 0 { return 1.0 }

        let distance = levenshteinDistance(nameA, nameB)
        return 1.0 - Double(distance) / Double(maxLen)
    }

    /// Duration similarity score (0.0–1.0). Uses 10% tolerance of the larger value.
    /// Returns 0.0 if either input is nil.
    nonisolated static func durationScore(_ a: Double?, _ b: Double?) -> Double {
        guard let a, let b else { return 0.0 }
        if a == 0 && b == 0 { return 1.0 }
        let maxVal = max(a, b)
        if maxVal == 0 { return 1.0 }
        let maxDiff = maxVal * 0.1
        if maxDiff == 0 { return a == b ? 1.0 : 0.0 }
        let diff = abs(a - b)
        return max(0.0, min(1.0, 1.0 - diff / maxDiff))
    }

    /// Resolution similarity score (0.0–1.0). Compares pixel counts.
    /// Returns 0.0 if either dimension pair is nil.
    nonisolated static func resolutionScore(
        widthA: Int?, heightA: Int?,
        widthB: Int?, heightB: Int?
    ) -> Double {
        guard let wA = widthA, let hA = heightA,
              let wB = widthB, let hB = heightB else { return 0.0 }
        let pixelsA = Double(wA * hA)
        let pixelsB = Double(wB * hB)
        if pixelsA == 0 && pixelsB == 0 { return 1.0 }
        let maxPixels = max(pixelsA, pixelsB)
        if maxPixels == 0 { return 1.0 }
        let minPixels = min(pixelsA, pixelsB)
        return minPixels / maxPixels
    }

    /// File size similarity score (0.0–1.0). Ratio of smaller to larger.
    nonisolated static func fileSizeScore(_ a: Int, _ b: Int) -> Double {
        if a == 0 && b == 0 { return 1.0 }
        let maxSize = max(a, b)
        if maxSize == 0 { return 1.0 }
        let minSize = min(a, b)
        return Double(minSize) / Double(maxSize)
    }

    /// Resolves weights from config or returns mode-specific defaults.
    nonisolated static func resolveWeights(
        _ configWeights: [String: Double]?,
        mode: ScanMode,
        content: Bool = false,
        audio: Bool = false
    ) -> [String: Double] {
        if let w = configWeights { return w }
        return WeightDefaults.defaults(mode: mode, content: content, audio: audio)
            ?? WeightDefaults.videoDefault
    }

    /// Filters known files to those within ±2 seconds of the new file's duration.
    /// Returns all candidates if newDuration is nil.
    ///
    /// When `newEffectiveMode` is set (auto mode), candidates are first filtered to
    /// the same media type to prevent cross-type scoring (e.g. image vs video).
    nonisolated static func bucketCandidates(
        newDuration: Double?,
        newEffectiveMode: ScanMode? = nil,
        knownFiles: [KnownFile]
    ) -> [KnownFile] {
        // In auto mode, restrict to same media type
        let typed: [KnownFile]
        if let mode = newEffectiveMode {
            typed = knownFiles.filter { $0.effectiveMode == nil || $0.effectiveMode == mode }
        } else {
            typed = knownFiles
        }

        guard let dur = newDuration else { return typed }
        return typed.filter { known in
            guard let knownDur = known.metadata.duration else { return true }
            return abs(knownDur - dur) <= 2.0
        }
    }

    /// Scores a new file against candidate known files. Returns alerts for matches
    /// above the threshold.
    ///
    /// **Intentional divergence from CLI scoring:**
    /// - Uses Levenshtein distance for filename similarity (CLI uses rapidfuzz + normalize_filename).
    /// - Does not implement EXIF or audio-tag comparators — only `filename`, `duration`,
    ///   `resolution`, and `filesize` are scored. Unimplemented weight keys (e.g. `exif`, `tags`)
    ///   are excluded from the denominator so they do not depress scores.
    /// - No content hashing or audio fingerprinting (those require full CLI pipeline).
    nonisolated static func scoreNewFile(
        newPath: String,
        newMetadata: FileMetadata,
        candidates: [KnownFile],
        weights: [String: Double],
        threshold: Int,
        sessionID: UUID
    ) -> [DuplicateAlert] {
        let implementedKeys: Set<String> = ["filename", "duration", "resolution", "filesize"]
        let totalWeight = weights.filter { implementedKeys.contains($0.key) }.values.reduce(0, +)
        guard totalWeight > 0 else { return [] }

        var alerts: [DuplicateAlert] = []

        for candidate in candidates {
            var detail: [String: DetailScore] = [:]
            var weightedSum = 0.0

            if let w = weights["filename"], w > 0 {
                let raw = filenameSimilarity(newPath, candidate.path)
                detail["filename"] = DetailScore(raw: raw, weight: w)
                weightedSum += raw * w
            }

            if let w = weights["duration"], w > 0 {
                let raw = durationScore(newMetadata.duration, candidate.metadata.duration)
                detail["duration"] = DetailScore(raw: raw, weight: w)
                weightedSum += raw * w
            }

            if let w = weights["resolution"], w > 0 {
                let raw = resolutionScore(
                    widthA: newMetadata.width, heightA: newMetadata.height,
                    widthB: candidate.metadata.width, heightB: candidate.metadata.height
                )
                detail["resolution"] = DetailScore(raw: raw, weight: w)
                weightedSum += raw * w
            }

            if let w = weights["filesize"], w > 0 {
                let raw = fileSizeScore(newMetadata.fileSize, candidate.metadata.fileSize)
                detail["filesize"] = DetailScore(raw: raw, weight: w)
                weightedSum += raw * w
            }

            let score = Int(round(weightedSum / totalWeight * 100))

            if score >= threshold {
                alerts.append(DuplicateAlert(
                    newFile: URL(filePath: newPath),
                    matchedFile: URL(filePath: candidate.path),
                    score: score,
                    detail: detail,
                    timestamp: Date(),
                    sessionID: sessionID,
                    newMetadata: newMetadata,
                    matchedMetadata: candidate.metadata
                ))
            }
        }

        return alerts
    }

    // MARK: - Effective mode resolution

    /// Determines the effective media type for a file based on its metadata.
    ///
    /// In auto mode, images have no duration (extracted via CoreGraphics) while
    /// videos have a duration (extracted via ffprobe). Returns nil for non-auto
    /// modes where cross-type filtering is unnecessary.
    nonisolated static func resolveEffectiveMode(
        metadata: FileMetadata, configMode: ScanMode
    ) -> ScanMode? {
        guard configMode == .auto else { return nil }
        return metadata.duration == nil ? .image : .video
    }

    // MARK: - Directory inventory

    /// Enumerates all matching files in the given directories.
    ///
    /// Reuses `DirectoryWatcher.shouldInclude` for extension + dotfile filtering
    /// to ensure the inventory matches what the watcher will report.
    nonisolated static func enumerateFiles(
        in directories: [URL],
        extensions: Set<String>
    ) -> [URL] {
        var results: [URL] = []
        let fm = FileManager.default
        for dir in directories {
            guard let enumerator = fm.enumerator(
                at: dir,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            ) else { continue }
            for case let fileURL as URL in enumerator {
                guard let values = try? fileURL.resourceValues(forKeys: [.isRegularFileKey]),
                      values.isRegularFile == true else { continue }
                guard DirectoryWatcher.shouldInclude(fileURL, extensions: extensions) else {
                    continue
                }
                results.append(fileURL)
            }
        }
        return results
    }

    /// Maximum concurrent metadata extractions during inventory build.
    private static let inventoryConcurrency = 8

    /// Builds the initial known-file inventory by enumerating watched directories
    /// and extracting metadata for each file.
    ///
    /// This ensures ALL files in the watched directories become part of the
    /// baseline — not just those that appeared in duplicate pairs.
    /// Uses bounded concurrency to parallelise metadata extraction.
    nonisolated static func buildInventory(
        directories: [URL],
        mode: ScanMode,
        environment: [String: String]
    ) async -> [KnownFile] {
        let extensions = DirectoryWatcher.extensionsForMode(mode)
        let fileURLs = enumerateFiles(in: directories, extensions: extensions)

        return await withTaskGroup(of: KnownFile?.self, returning: [KnownFile].self) { group in
            var knownFiles: [KnownFile] = []
            var index = 0

            // Seed the group up to the concurrency limit.
            while index < min(fileURLs.count, inventoryConcurrency) {
                let url = fileURLs[index]
                group.addTask {
                    guard let metadata = await extractMetadata(
                        from: url, mode: mode, environment: environment
                    ) else { return nil }
                    let inode = fileInode(at: url.path)
                    let effective = resolveEffectiveMode(metadata: metadata, configMode: mode)
                    return KnownFile(
                        path: url.path, metadata: metadata, inode: inode,
                        effectiveMode: effective)
                }
                index += 1
            }

            // As each task completes, enqueue the next file.
            for await result in group {
                if let file = result {
                    knownFiles.append(file)
                }
                if index < fileURLs.count {
                    let url = fileURLs[index]
                    group.addTask {
                        guard let metadata = await extractMetadata(
                            from: url, mode: mode, environment: environment
                        ) else { return nil }
                        let inode = fileInode(at: url.path)
                        let effective = resolveEffectiveMode(metadata: metadata, configMode: mode)
                        return KnownFile(
                            path: url.path, metadata: metadata, inode: inode,
                            effectiveMode: effective)
                    }
                    index += 1
                }
            }

            return knownFiles
        }
    }

    // MARK: - Metadata extraction

    /// Returns the file size in bytes, or 0 on failure.
    nonisolated private static func fileSize(at path: String) -> Int {
        (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? Int ?? 0
    }

    /// Timeout in seconds for ffprobe subprocess.
    private static let ffprobeTimeout: TimeInterval = 10

    /// Extracts metadata from a file using the appropriate method for the scan mode.
    nonisolated static func extractMetadata(
        from url: URL,
        mode: ScanMode = .video,
        environment: [String: String] = [:]
    ) async -> FileMetadata? {
        switch mode {
        case .image:
            return extractImageMetadata(from: url)
        case .audio:
            return await extractAudioMetadata(from: url)
        case .document:
            return extractDocumentMetadata(from: url)
        case .auto:
            if let imageMeta = extractImageMetadata(from: url) {
                return imageMeta
            }
            return await extractVideoMetadata(from: url, environment: environment)
        case .video:
            return await extractVideoMetadata(from: url, environment: environment)
        }
    }

    /// Extracts image metadata using native CoreGraphics APIs (no ffprobe needed).
    nonisolated static func extractImageMetadata(from url: URL) -> FileMetadata? {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] else {
            return nil
        }
        guard let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int else {
            return nil
        }

        return FileMetadata(width: width, height: height, fileSize: fileSize(at: url.path))
    }

    /// Extracts basic metadata for a document file (file size only -- the CLI handles
    /// document-specific metadata like page count, title, author via pdfminer).
    nonisolated static func extractDocumentMetadata(from url: URL) -> FileMetadata? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? Int else { return nil }
        let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970
        return FileMetadata(fileSize: size, mtime: mtime)
    }

    /// Extracts audio metadata using AVFoundation (no ffprobe needed).
    nonisolated static func extractAudioMetadata(from url: URL) async -> FileMetadata? {
        let asset = AVURLAsset(url: url)

        let duration: Double?
        do {
            let cmDuration = try await asset.load(.duration)
            let seconds = CMTimeGetSeconds(cmDuration)
            duration = seconds.isFinite ? seconds : nil
        } catch {
            duration = nil
        }

        // No duration means AVFoundation couldn't parse the file as audio
        guard let duration else { return nil }

        return FileMetadata(duration: duration, fileSize: fileSize(at: url.path))
    }

    /// Extracts video metadata using ffprobe subprocess.
    /// Runs the subprocess off the cooperative thread pool to avoid blocking.
    /// Terminates ffprobe after 10 seconds if it hangs on a corrupt file.
    ///
    /// Uses a single-resume pattern: all paths converge on one `resume` call at the
    /// end of the block, eliminating any double-resume risk from timeout races.
    ///
    /// - Parameters:
    ///   - url: Path to the media file.
    ///   - environment: Shell environment to set on the subprocess (provides the
    ///     login-shell PATH so Homebrew-installed ffprobe is found in Finder-launched apps).
    nonisolated static func extractVideoMetadata(
        from url: URL,
        environment: [String: String] = [:]
    ) async -> FileMetadata? {
        let path = url.path

        return await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let result = Self.runFFProbe(path: path, environment: environment)
                continuation.resume(returning: result)
            }
        }
    }

    /// Synchronous ffprobe execution with timeout — returns nil on failure.
    /// Isolated to a single return site to prevent double-resume when called
    /// from `withCheckedContinuation`.
    nonisolated private static func runFFProbe(
        path: String,
        environment: [String: String]
    ) -> FileMetadata? {
        let process = Process()
        process.executableURL = URL(filePath: "/usr/bin/env")
        process.arguments = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ]

        if !environment.isEmpty {
            process.environment = environment
        }

        let stdout = Pipe()
        process.standardOutput = stdout
        process.standardError = Pipe()

        do {
            try process.run()
        } catch {
            return nil
        }

        // Run pipe read + waitUntilExit concurrently under a shared timeout.
        // Both must complete before we can inspect results — reading must be
        // on its own thread because readDataToEndOfFile() blocks until EOF.
        var readData: Data?
        let workGroup = DispatchGroup()

        workGroup.enter()
        DispatchQueue.global(qos: .utility).async {
            readData = stdout.fileHandleForReading.readDataToEndOfFile()
            workGroup.leave()
        }

        workGroup.enter()
        DispatchQueue.global(qos: .utility).async {
            process.waitUntilExit()
            workGroup.leave()
        }

        let waitResult = workGroup.wait(timeout: .now() + ffprobeTimeout)
        if waitResult == .timedOut {
            process.terminate()
            // Wait for both tasks to finish before returning — avoids a
            // data race on `readData` from the read thread still running.
            workGroup.wait()
            return nil
        }

        guard process.terminationStatus == 0, let data = readData else {
            return nil
        }

        return parseFFProbeOutput(data, filePath: path)
    }

    /// Parses ffprobe JSON output into FileMetadata.
    nonisolated static func parseFFProbeOutput(_ data: Data, filePath: String) -> FileMetadata? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }

        let format = json["format"] as? [String: Any]
        let durationStr = format?["duration"] as? String
        let duration = durationStr.flatMap(Double.init)

        let sizeStr = format?["size"] as? String
        let fileSizeValue = sizeStr.flatMap(Int.init) ?? fileSize(at: filePath)

        let streams = json["streams"] as? [[String: Any]] ?? []
        let videoStream = streams.first { ($0["codec_type"] as? String) == "video" }

        let width = videoStream?["width"] as? Int
        let height = videoStream?["height"] as? Int
        let codec = videoStream?["codec_name"] as? String

        return FileMetadata(
            duration: duration,
            width: width,
            height: height,
            fileSize: fileSizeValue,
            codec: codec
        )
    }
}
