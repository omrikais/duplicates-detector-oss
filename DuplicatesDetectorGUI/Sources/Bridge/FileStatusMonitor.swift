// Sources/Bridge/FileStatusMonitor.swift
import Foundation
import CoreServices

/// Monitors specific file paths for filesystem changes (deletion, rename, restoration).
///
/// Uses CoreServices FSEventStream to watch parent directories of tracked files.
/// Detects moves via inode matching: when a tracked file disappears and a new file
/// appears with the same inode, emits `.moved` instead of separate disappeared/appeared.
actor FileStatusMonitor {

    /// A change detected by the monitor.
    enum Change: Sendable, Equatable {
        /// A tracked file was removed from disk.
        case disappeared(String)
        /// A previously-missing tracked file reappeared at its original path.
        case appeared(String)
        /// A tracked file was moved (detected via inode match).
        case moved(from: String, to: String)
    }

    // MARK: - State

    private var knownPaths: Set<String> = []
    private var inodeIndex: [UInt64: String] = [:]  // inode → path for move detection
    private var pathToInode: [String: UInt64] = [:]  // path → inode (reverse index for O(1) lookup)
    private var missingPaths: Set<String> = []       // paths known to be missing (for restoration detection)
    private var streamRef: FSEventStreamRef?
    private var continuation: AsyncStream<[RawFSEvent]>.Continuation?
    private var callbackContext: Unmanaged<CallbackContext>?
    private var monitorTask: Task<Void, Never>?
    private let onChange: @Sendable ([Change]) async -> Void
    private let queue = DispatchQueue(label: "com.dd.file-status-monitor", qos: .utility)

    // MARK: - Init

    init(onChange: @Sendable @escaping ([Change]) async -> Void) {
        self.onChange = onChange
    }

    // NOTE: No deinit — FSEventStreamRef is non-Sendable, so Swift 6 strict
    // concurrency forbids accessing it from nonisolated deinit. Callers MUST
    // call stop() before releasing the actor. SessionStore.deinit ensures this
    // via a fire-and-forget Task that awaits stop().

    // MARK: - Public API

    /// Start monitoring the given file paths. Derives parent directories for FSEventStream.
    func start(paths: [String]) {
        // Stop any existing stream
        stopStream()

        knownPaths = Set(paths)
        buildInodeIndex(for: paths)

        // Record initially missing paths so we can detect restoration
        missingPaths = Set(paths.filter { !FileManager.default.fileExists(atPath: $0) })

        let directories = deriveDirectories(from: paths)
        guard !directories.isEmpty else { return }

        startStream(directories: directories)
    }

    /// One-time batch existence check (for history restore or window focus).
    func checkStatuses() -> [String: FileStatus] {
        var result: [String: FileStatus] = [:]
        for path in knownPaths {
            result[path] = FileManager.default.fileExists(atPath: path) ? .present : .missing
        }
        return result
    }

    /// Add new paths to monitoring (e.g., from newly appended watch pairs).
    func addPaths(_ newPaths: [String]) {
        let oldDirs = deriveDirectories(from: Array(knownPaths))
        var alreadyMissing: [Change] = []
        for path in newPaths {
            knownPaths.insert(path)
            if let inode = fileInode(at: path) {
                inodeIndex[inode] = path
                pathToInode[path] = inode
            }
            if !FileManager.default.fileExists(atPath: path) {
                missingPaths.insert(path)
                alreadyMissing.append(.disappeared(path))
            }
        }
        // Restart stream if new parent directories need monitoring
        let newDirs = deriveDirectories(from: Array(knownPaths))
        if newDirs != oldDirs, streamRef != nil {
            startStream(directories: newDirs)
        }
        // Report files that were already missing when added — the FSEventStream
        // won't fire for deletions that happened before we started tracking.
        if !alreadyMissing.isEmpty {
            Task { await onChange(alreadyMissing) }
        }
    }

    /// Stop monitoring and clean up all resources.
    func stop() {
        monitorTask?.cancel()
        monitorTask = nil
        stopStream()
        knownPaths.removeAll()
        inodeIndex.removeAll()
        pathToInode.removeAll()
        missingPaths.removeAll()
    }

    // MARK: - Internal (testable)

    /// Process raw FSEvents and return changes for tracked files.
    ///
    /// Exposed for testing: given arrays of event paths and flags from the FSEvents
    /// callback, determines which tracked paths changed and how.
    func processRawEvents(_ rawEvents: [RawFSEvent]) -> [Change] {
        var changes: [Change] = []
        // Pending disappearances keyed by inode, for move detection within a batch
        var pendingDisappearances: [UInt64: String] = [:]

        for event in rawEvents {
            let path = event.path
            let flags = event.flags
            let isFile = flags & UInt32(kFSEventStreamEventFlagItemIsFile) != 0

            guard isFile else { continue }

            let isTracked = knownPaths.contains(path)
            let exists = FileManager.default.fileExists(atPath: path)

            // Case 1: A tracked file was removed
            if isTracked && !exists &&
               (flags & UInt32(kFSEventStreamEventFlagItemRemoved) != 0 ||
                flags & UInt32(kFSEventStreamEventFlagItemRenamed) != 0) {
                // Record inode for potential move detection
                if let inode = pathToInode[path] {
                    pendingDisappearances[inode] = path
                } else {
                    changes.append(.disappeared(path))
                    missingPaths.insert(path)
                }
            }
            // Case 2: A file appeared where a tracked file was expected (restoration)
            else if isTracked && exists && missingPaths.contains(path) {
                changes.append(.appeared(path))
                missingPaths.remove(path)
                // Update inode index in case inode changed
                if let inode = fileInode(at: path) {
                    // Remove old inode→path mapping before re-indexing
                    if let oldInode = pathToInode[path] {
                        inodeIndex.removeValue(forKey: oldInode)
                    }
                    inodeIndex[inode] = path
                    pathToInode[path] = inode
                }
            }
            // Case 3: A new file appeared in a tracked directory — check inode for move
            else if !isTracked && exists &&
                    (flags & UInt32(kFSEventStreamEventFlagItemCreated) != 0 ||
                     flags & UInt32(kFSEventStreamEventFlagItemRenamed) != 0) {
                if let inode = fileInode(at: path) {
                    if let fromPath = pendingDisappearances[inode] {
                        // Move detected within this batch
                        changes.append(.moved(from: fromPath, to: path))
                        pendingDisappearances.removeValue(forKey: inode)
                        // Update tracking
                        knownPaths.remove(fromPath)
                        knownPaths.insert(path)
                        inodeIndex[inode] = path
                        pathToInode.removeValue(forKey: fromPath)
                        pathToInode[path] = inode
                        missingPaths.remove(fromPath)
                    } else if let fromPath = inodeIndex[inode], !FileManager.default.fileExists(atPath: fromPath) {
                        // Move detected via stored inode (cross-batch)
                        changes.append(.moved(from: fromPath, to: path))
                        knownPaths.remove(fromPath)
                        knownPaths.insert(path)
                        inodeIndex[inode] = path
                        pathToInode.removeValue(forKey: fromPath)
                        pathToInode[path] = inode
                        missingPaths.remove(fromPath)
                    }
                }
            }
        }

        // Any remaining pending disappearances are actual deletions
        for (_, path) in pendingDisappearances {
            changes.append(.disappeared(path))
            missingPaths.insert(path)
        }

        return changes
    }

    // MARK: - Private

    /// Create (or recreate) the FSEventStream for the given directories.
    /// Stops any existing stream first, then starts a new one and wires up the monitor task.
    private func startStream(directories: Set<String>) {
        stopStream()

        let (stream, cont) = AsyncStream<[RawFSEvent]>.makeStream()
        self.continuation = cont

        let cfPaths = Array(directories) as CFArray
        let context = Unmanaged.passRetained(CallbackContext(continuation: cont))
        self.callbackContext = context

        var fsContext = FSEventStreamContext(
            version: 0,
            info: context.toOpaque(),
            retain: nil,
            release: nil,
            copyDescription: nil
        )

        let flags: FSEventStreamCreateFlags =
            UInt32(kFSEventStreamCreateFlagFileEvents) |
            UInt32(kFSEventStreamCreateFlagUseCFTypes) |
            UInt32(kFSEventStreamCreateFlagNoDefer)

        guard let ref = FSEventStreamCreate(
            nil,
            FileStatusMonitor.fsEventCallback,
            &fsContext,
            cfPaths,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            0.3,  // latency — slightly longer than DirectoryWatcher for batching
            flags
        ) else {
            cont.finish()
            context.release()
            self.callbackContext = nil
            return
        }

        streamRef = ref
        FSEventStreamSetDispatchQueue(ref, queue)
        FSEventStreamStart(ref)

        // Start the monitor task that reads events and processes them
        let onChange = self.onChange
        monitorTask = Task { [weak self] in
            for await rawEvents in stream {
                guard let self, !Task.isCancelled else { break }
                let changes = await self.processRawEvents(rawEvents)
                if !changes.isEmpty {
                    await onChange(changes)
                }
            }
        }
    }

    private func stopStream() {
        if let ref = streamRef {
            FSEventStreamStop(ref)
            FSEventStreamInvalidate(ref)
            FSEventStreamRelease(ref)
            streamRef = nil
        }
        continuation?.finish()
        continuation = nil
        if let ctx = callbackContext {
            ctx.release()
            callbackContext = nil
        }
    }

    /// Get the inode number for a file path.
    nonisolated func fileInode(at path: String) -> UInt64? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let inode = attrs[.systemFileNumber] as? UInt64 else { return nil }
        return inode
    }

    private func buildInodeIndex(for paths: [String]) {
        inodeIndex.removeAll()
        pathToInode.removeAll()
        for path in paths {
            if let inode = fileInode(at: path) {
                inodeIndex[inode] = path
                pathToInode[path] = inode
            }
        }
    }

    private func deriveDirectories(from paths: [String]) -> Set<String> {
        Set(paths.map { ($0 as NSString).deletingLastPathComponent })
    }

    // MARK: - FSEvents Callback Bridge

    /// Raw FSEvent data passed from the C callback to the actor for processing.
    struct RawFSEvent: Sendable {
        let path: String
        let flags: UInt32
    }

    /// Context object passed through the FSEventStream C callback.
    private final class CallbackContext: @unchecked Sendable {
        let continuation: AsyncStream<[RawFSEvent]>.Continuation

        init(continuation: AsyncStream<[RawFSEvent]>.Continuation) {
            self.continuation = continuation
        }
    }

    private static let fsEventCallback: FSEventStreamCallback = {
        _, info, numEvents, eventPaths, eventFlags, _ in

        guard let info else { return }
        let context = Unmanaged<CallbackContext>.fromOpaque(info).takeUnretainedValue()
        let paths = unsafeBitCast(eventPaths, to: NSArray.self)

        var events: [RawFSEvent] = []
        events.reserveCapacity(numEvents)

        for i in 0..<numEvents {
            guard let pathStr = paths[i] as? String else { continue }
            events.append(RawFSEvent(path: pathStr, flags: eventFlags[i]))
        }

        if !events.isEmpty {
            context.continuation.yield(events)
        }
    }
}
