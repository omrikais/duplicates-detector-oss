// Sources/Bridge/DirectoryWatcher.swift
import Foundation
import CoreServices

/// Monitors directories for new/renamed files using CoreServices FSEventStream.
///
/// Uses `kFSEventStreamCreateFlagFileEvents` for file-level granularity.
/// On some volume types (exFAT, HFS+, FUSE-based), macOS may coalesce
/// file-level events into directory-level events. The callback handles
/// both: file events are yielded directly; directory events (including
/// `kFSEventStreamEventFlagMustScanSubDirs`) are yielded as
/// `.directoryChanged` so the consumer can rescan for new files.
actor DirectoryWatcher {

    enum FileEvent: Sendable {
        case created(URL)
        case renamed(URL)
        /// A directory changed — consumer should rescan it for new files.
        /// Emitted when FSEvents delivers a directory-level event instead
        /// of individual file events (common on external/non-APFS volumes).
        case directoryChanged(URL)
    }

    private var streamRef: FSEventStreamRef?
    private var continuation: AsyncStream<FileEvent>.Continuation?
    private var callbackContext: Unmanaged<CallbackContext>?
    private let queue = DispatchQueue(label: "com.dd.directory-watcher", qos: .utility)
    private var allowedExtensions: Set<String> = []

    var isRunning: Bool { streamRef != nil }

    /// Known extensions per scan mode — mirrors the CLI's scanner.py.
    nonisolated static func extensionsForMode(_ mode: ScanMode) -> Set<String> {
        switch mode {
        case .video:
            return MediaExtensions.video
        case .image:
            return MediaExtensions.image
        case .audio:
            return MediaExtensions.audio
        case .document:
            return MediaExtensions.document
        case .auto:
            return MediaExtensions.video.union(MediaExtensions.image)
        }
    }

    /// Checks if a URL should be included based on extension and dotfile rules.
    nonisolated static func shouldInclude(_ url: URL, extensions: Set<String>) -> Bool {
        let name = url.lastPathComponent
        if name.hasPrefix(".") { return false }
        let ext = url.pathExtension.lowercased()
        return extensions.contains(ext)
    }

    func start(directories: [URL], latency: TimeInterval,
               extensions: Set<String>) -> AsyncStream<FileEvent> {
        allowedExtensions = extensions

        let (stream, cont) = AsyncStream<FileEvent>.makeStream()
        self.continuation = cont

        let paths = directories.map(\.path) as CFArray
        let context = Unmanaged.passRetained(CallbackContext(
            continuation: cont, extensions: extensions
        ))
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
            DirectoryWatcher.fsEventCallback,
            &fsContext,
            paths,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            latency,
            flags
        ) else {
            cont.finish()
            context.release()
            self.callbackContext = nil
            return stream
        }

        streamRef = ref
        FSEventStreamSetDispatchQueue(ref, queue)
        FSEventStreamStart(ref)

        return stream
    }

    func stop() {
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

    // MARK: - C Callback Bridge

    /// Context object passed through the FSEventStream C callback.
    private final class CallbackContext: @unchecked Sendable {
        let continuation: AsyncStream<FileEvent>.Continuation
        let extensions: Set<String>

        init(continuation: AsyncStream<FileEvent>.Continuation, extensions: Set<String>) {
            self.continuation = continuation
            self.extensions = extensions
        }
    }

    private static let fsEventCallback: FSEventStreamCallback = {
        _, info, numEvents, eventPaths, eventFlags, _ in

        guard let info else { return }
        let context = Unmanaged<CallbackContext>.fromOpaque(info).takeUnretainedValue()
        // Safe: kFSEventStreamCreateFlagUseCFTypes guarantees eventPaths is a CFArray of CFString.
        let paths = unsafeBitCast(eventPaths, to: NSArray.self)

        for i in 0..<numEvents {
            let flags = eventFlags[i]
            guard let pathStr = paths[i] as? String else { continue }

            let isFile = flags & UInt32(kFSEventStreamEventFlagItemIsFile) != 0
            let isDir = flags & UInt32(kFSEventStreamEventFlagItemIsDir) != 0
            let mustScan = flags & UInt32(kFSEventStreamEventFlagMustScanSubDirs) != 0
                || flags & UInt32(kFSEventStreamEventFlagKernelDropped) != 0
                || flags & UInt32(kFSEventStreamEventFlagUserDropped) != 0

            // Kernel/user queue overflow — always rescan, regardless of type flags.
            if mustScan {
                let url = URL(filePath: pathStr, directoryHint: .isDirectory)
                context.continuation.yield(.directoryChanged(url))
                continue
            }

            // File-level events — the fast path on APFS and most native volumes.
            if isFile {
                let url = URL(filePath: pathStr)
                guard shouldInclude(url, extensions: context.extensions) else { continue }

                if flags & UInt32(kFSEventStreamEventFlagItemRenamed) != 0 {
                    // Rename: yield only for the destination (file exists at new path).
                    if FileManager.default.fileExists(atPath: pathStr) {
                        context.continuation.yield(.renamed(url))
                    }
                } else if FileManager.default.fileExists(atPath: pathStr) {
                    // Any other file event (Created, Modified, XattrMod, etc.).
                    // On non-APFS volumes macOS may report new files with Modified
                    // instead of Created. The engine filters already-known files
                    // via knownPaths so modifications of tracked files are no-ops.
                    context.continuation.yield(.created(url))
                }
            }
            // Directory-level events — fired on external/non-APFS volumes when
            // macOS coalesces file events into a parent-directory notification.
            else if isDir {
                let url = URL(filePath: pathStr, directoryHint: .isDirectory)
                context.continuation.yield(.directoryChanged(url))
            }
            // Neither isFile nor isDir — can occur on FUSE-based or degraded
            // volumes. Stat the path to determine the correct event type.
            else {
                var isDirectory: ObjCBool = false
                if FileManager.default.fileExists(atPath: pathStr, isDirectory: &isDirectory) {
                    if isDirectory.boolValue {
                        context.continuation.yield(.directoryChanged(
                            URL(filePath: pathStr, directoryHint: .isDirectory)))
                    } else {
                        let url = URL(filePath: pathStr)
                        if shouldInclude(url, extensions: context.extensions) {
                            context.continuation.yield(.created(url))
                        }
                    }
                }
            }
        }
    }
}
