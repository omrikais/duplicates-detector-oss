import Foundation
import os
import Subprocess
import Synchronization

private let log = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "CLIBridge")

/// Output from a CLI scan invocation.
enum CLIOutput: Sendable {
    case progress(ProgressEvent)
    case result(ScanEnvelope, Data)
}

// MARK: - Child Process Lifecycle

/// Tracks the PID of any running CLI subprocess so it can be killed on app exit.
///
/// Uses `Atomic<Int32>` with `.relaxed` ordering because `atexit` handlers and
/// signal handlers must be async-signal-safe. `Atomic` operations are
/// async-signal-safe (unlike `OSAllocatedUnfairLock`), and `kill()` is
/// async-signal-safe per POSIX.
private let _childPID = Atomic<Int32>(0)

/// Kill any tracked child process group. Safe to call from signal handlers and `atexit`.
///
/// Sends SIGTERM first (the CLI handles it gracefully), then SIGKILL after a
/// brief pause to guarantee cleanup even if the child ignores SIGTERM.
/// Uses negative PID to target the entire process group (CLI + ffprobe/ffmpeg/fpcalc
/// children), matching the subprocess launch with `processGroupID: 0`.
public func _killChild() {
    let pid = _childPID.load(ordering: .relaxed)
    guard pid > 0 else { return }
    kill(-pid, SIGTERM)
    // Brief pause so the CLI can flush caches / remove temp files.
    // usleep is async-signal-safe on Darwin.
    usleep(200_000) // 200ms
    // Force-kill if still running.
    kill(-pid, SIGKILL)
}

/// One-time registration of atexit + signal handlers.
private let _installAtexitHandler: Void = {
    atexit { _killChild() }
}()

private let _installSignalHandlers: Void = {
    // SIGTERM (sent by `kill`, Activity Monitor "Quit")
    signal(SIGTERM) { _ in _killChild(); _exit(143) }
    // SIGINT (Ctrl-C in terminal if running via `swift run`)
    signal(SIGINT) { _ in _killChild(); _exit(130) }
    // SIGHUP (terminal closed)
    signal(SIGHUP) { _ in _killChild(); _exit(129) }
}()

/// Read lines from an async byte stream, calling `body` for each decoded line.
///
/// Buffers raw bytes and splits on newlines (0x0A) to avoid corrupting
/// multi-byte UTF-8 sequences split across pipe chunks. Flushes any
/// trailing partial line after the stream ends.
func forEachBufferedLine(
    from stream: AsyncBufferSequence,
    body: (String) -> Void
) async throws {
    var buffer = Data()
    for try await chunk in stream {
        chunk.withUnsafeBytes { ptr in
            buffer.append(contentsOf: UnsafeBufferPointer(
                start: ptr.baseAddress?.assumingMemoryBound(to: UInt8.self),
                count: ptr.count
            ))
        }
        // Process complete lines using index advancement to avoid per-line copies.
        var searchStart = buffer.startIndex
        while let newlineIdx = buffer[searchStart...].firstIndex(of: UInt8(ascii: "\n")) {
            let line = String(decoding: buffer[searchStart..<newlineIdx], as: UTF8.self)
            searchStart = buffer.index(after: newlineIdx)
            body(line)
        }
        // Keep only the unprocessed tail.
        if searchStart > buffer.startIndex {
            buffer = Data(buffer[searchStart...])
        }
    }
    // Flush trailing partial line (no final newline).
    if !buffer.isEmpty {
        body(String(decoding: buffer, as: UTF8.self))
    }
}

// MARK: - Pause File Management

extension CLIBridge {
    private static func writePauseControlContents(_ contents: String, to url: URL) throws {
        let data = Data(contents.utf8)

        if !FileManager.default.fileExists(atPath: url.path) {
            let created = FileManager.default.createFile(atPath: url.path, contents: data)
            if !created {
                throw CocoaError(.fileWriteUnknown)
            }
            return
        }

        let handle = try FileHandle(forWritingTo: url)
        defer {
            try? handle.close()
        }
        try handle.truncate(atOffset: 0)
        try handle.write(contentsOf: data)
        try handle.synchronize()
    }

    /// Create a temporary pause control file for GUI-to-CLI communication.
    ///
    /// The file is initialized with "resume" so the CLI starts in a running state.
    /// The GUI writes "pause" or "resume" to control the scan lifecycle.
    static func createPauseFile() -> URL {
        let path = NSTemporaryDirectory() + "dd-pause-\(ProcessInfo.processInfo.processIdentifier).ctl"
        let url = URL(filePath: path)
        do {
            try writePauseControlContents("resume", to: url)
        } catch {
            log.error("createPauseFile: failed to initialize \(url.path, privacy: .public): \(error.localizedDescription, privacy: .public)")
        }
        return url
    }

    /// Write a pause command ("pause" or "resume") to the control file.
    @discardableResult
    static func writePauseCommand(_ command: String, to url: URL) -> Bool {
        do {
            try writePauseControlContents(command, to: url)
            return true
        } catch {
            log.error("writePauseCommand: failed to write \(command, privacy: .public) to \(url.path, privacy: .public): \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    /// Clean up the pause file when the scan completes or is cancelled.
    static func removePauseFile(at url: URL) {
        try? FileManager.default.removeItem(at: url)
    }
}

/// Actor that manages all subprocess interactions with the `duplicates-detector` CLI.
///
/// Ensures subprocess I/O runs off `@MainActor`. All methods are `async`
/// and can be called from SwiftUI views via `Task`.
actor CLIBridge: CLIBridgeProtocol {
    private static let userConfiguredPathDefaultsKey = "duplicates-detector.cliBinaryPath"
    private static let environmentOverrideKey = "DUPLICATES_DETECTOR_CLI_PATH"
    private static let developmentPathInfoKey = "DDCLIDevelopmentPath"
    private static let injectedEnvironmentKeysToRemove: [Environment.Key] = [
        "DYLD_INSERT_LIBRARIES",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_IMAGE_SUFFIX",
        "__XPC_DYLD_INSERT_LIBRARIES",
        "__XPC_DYLD_FRAMEWORK_PATH",
        "__XPC_DYLD_LIBRARY_PATH",
        "XCInjectBundle",
        "XCInjectBundleInto",
        "XCODE_RUNNING_FOR_PREVIEWS",
        "__XCODE_BUILT_PRODUCTS_DIR_PATHS",
        "OS_ACTIVITY_DT_MODE",
    ]

    /// Path to the CLI binary, set after `locateBinary()`.
    private(set) var binaryPath: String?

    /// Currently running subprocess execution (for cancellation).
    private var currentExecution: Execution?

    /// Resolved shell environment for subprocess calls.
    ///
    /// macOS GUI apps inherit a minimal PATH that lacks Homebrew / pip paths.
    /// We resolve the user's full PATH from a login shell once during
    /// `locateBinary()` and reuse it for all subprocess invocations.
    private var shellEnvironment: Environment = CLIBridge.sanitizedInheritedEnvironment()
    private var resolvedPathString: String?
    private var didResolveShellEnvironment = false

    init() {
        // GUI apps already terminate through AppKit lifecycle notifications.
        // Keep Unix signal handlers for the SwiftPM CLI only, where SIGINT/SIGHUP
        // are part of normal process control and debugger pauses are not a concern.
        _ = _installAtexitHandler
        if !Bundle.main.bundlePath.hasSuffix(".app") {
            _ = _installSignalHandlers
        }
    }

    // MARK: - Cache invalidation

    /// If `clearPersistedBinaryPath()` was called externally, clear the
    /// in-memory cache so the next operation re-resolves the binary.
    private func consumeInvalidationFlag() {
        if Self._cacheInvalidated.withLock({ let v = $0; $0 = false; return v }) {
            binaryPath = nil
        }
    }

    // MARK: - Binary location

    /// Locate the `duplicates-detector` binary.
    ///
    /// Search order: explicit/persisted override, environment override,
    /// bundled resource, debug development path, PATH, common install
    /// locations, then a debug-only source-tree fallback.
    func locateBinary(
        userConfiguredPath: String? = nil,
        refreshShellEnvironment: Bool = false
    ) async -> String? {
        consumeInvalidationFlag()

        if userConfiguredPath == nil,
           !refreshShellEnvironment,
           let cachedPath = binaryPath,
           isExecutable(atPath: cachedPath) {
            log.debug("locateBinary: using cached path \(cachedPath)")
            return cachedPath
        }

        // 1. User-configured path
        if let path = userConfiguredPath,
           let resolvedPath = firstExecutablePath(in: [path]) {
            log.info("locateBinary: user-configured → \(resolvedPath)")
            persistUserConfiguredPath(resolvedPath)
            binaryPath = resolvedPath
            return resolvedPath
        }

        let overrideCandidates: [String?] = [
            persistedUserConfiguredPath(),
            ProcessInfo.processInfo.environment[Self.environmentOverrideKey],
            bundledBinaryPath(),
            developmentBinaryPathFromInfoDictionary(),
        ]
        log.debug("locateBinary: override candidates = \(overrideCandidates.compactMap { $0 })")
        if let resolvedPath = firstExecutablePath(in: overrideCandidates) {
            log.info("locateBinary: override → \(resolvedPath)")
            binaryPath = resolvedPath
            return resolvedPath
        }

        // 2. Common locations
        var commonPaths = commonExecutableCandidates(named: "duplicates-detector")

        #if DEBUG
        let devCandidates = sourceTreeDevelopmentCandidates()
        log.debug("locateBinary: source-tree candidates = \(devCandidates)")
        commonPaths.append(contentsOf: devCandidates)
        #endif

        log.debug("locateBinary: checking \(commonPaths.count) common paths")
        if let resolvedPath = firstExecutablePath(in: commonPaths) {
            log.info("locateBinary: common path → \(resolvedPath)")
            binaryPath = resolvedPath
            return resolvedPath
        }

        // 3. PATH lookup
        if let path = await runWhich("duplicates-detector", refreshShellEnvironment: refreshShellEnvironment) {
            log.info("locateBinary: which → \(path)")
            binaryPath = path
            return path
        }

        log.warning("locateBinary: binary not found")
        return nil
    }

    // MARK: - Dependency validation

    /// Check availability of all required tools.
    ///
    /// For the CLI, honors the already-resolved `binaryPath` (which may have
    /// been found via fallback locations not on `$PATH`).
    func validateDependencies(
        userConfiguredPath: String? = nil,
        refreshShellEnvironment: Bool = false
    ) async -> DependencyStatus {
        _ = await locateBinary(
            userConfiguredPath: userConfiguredPath,
            refreshShellEnvironment: refreshShellEnvironment
        )

        async let cliCheck = checkCLI()
        async let ffmpegCheck = checkTool("ffmpeg", required: false)
        async let ffprobeCheck = checkTool("ffprobe", required: false)
        async let fpcalcCheck = checkTool("fpcalc", required: false)
        async let mutagenCheck = checkPythonImport("mutagen")
        async let skimageCheck = checkPythonImport("skimage")
        async let pdfminerCheck = checkPythonImport("pdfminer")

        return await DependencyStatus(
            cli: cliCheck,
            ffmpeg: ffmpegCheck,
            ffprobe: ffprobeCheck,
            fpcalc: fpcalcCheck,
            hasMutagen: mutagenCheck,
            hasSkimage: skimageCheck,
            hasPdfminer: pdfminerCheck
        )
    }

    /// Get the CLI version string.
    func getVersion() async throws -> String {
        consumeInvalidationFlag()
        guard let bin = binaryPath else {
            throw CLIBridgeError.binaryNotFound
        }

        let result = try await run(
            .name(bin),
            arguments: ["--version"],
            environment: shellEnvironment,
            output: .string(limit: 4096)
        )
        return (result.standardOutput ?? "").trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
    }

    // MARK: - Installer Support

    /// The resolved shell environment for subprocess calls.
    ///
    /// Ensures the login-shell PATH has been resolved before returning,
    /// so the caller (e.g. ``DependencyInstaller``) can launch tools at
    /// the same paths ``CLIBridge`` uses internally.
    func resolvedEnvironment() async -> Environment {
        await resolveShellEnvironment()
        return shellEnvironment
    }

    /// The Python interpreter path used by the CLI entry-point.
    ///
    /// Returns `nil` if the CLI binary hasn't been located yet or if
    /// the shebang / sibling lookup fails.
    func cliPythonPath() -> String? {
        resolveCLIPython()
    }

    // MARK: - Undo Script Generation

    /// Generate an undo script from an action log file by invoking the CLI.
    func generateUndoScript(logPath: String) async throws -> String {
        consumeInvalidationFlag()
        guard let bin = binaryPath else { throw CLIBridgeError.binaryNotFound }
        await resolveShellEnvironment()
        let result = try await run(
            .name(bin),
            arguments: ["--generate-undo", logPath],
            environment: shellEnvironment,
            output: .string(limit: 52_428_800)
        )
        guard result.terminationStatus.isSuccess else {
            throw CLIBridgeError.processExitedWithError(
                code: terminationCode(result.terminationStatus)
            )
        }
        let output = result.standardOutput ?? ""
        guard !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CLIBridgeError.emptyOutput
        }
        return output
    }

    /// Export scan results in a specific format using the CLI's replay pipeline.
    ///
    /// Spawns the CLI with `--replay <envelopePath> --format <format> --output <outputPath>`.
    func exportAsFormat(
        envelopePath: String,
        format: String,
        outputPath: String,
        keep: String? = nil,
        embedThumbnails: Bool = false,
        group: Bool = false,
        ignoreFile: String? = nil
    ) async throws {
        consumeInvalidationFlag()
        guard let bin = binaryPath else { throw CLIBridgeError.binaryNotFound }
        await resolveShellEnvironment()

        var args = [
            "scan", "--no-config", "--no-color",
            "--replay", envelopePath,
            "--format", format,
            "--output", outputPath,
        ]
        if let keep { args += ["--keep", keep] }
        if embedThumbnails { args.append("--embed-thumbnails") }
        if group { args.append("--group") }
        if let ignoreFile { args += ["--ignore-file", ignoreFile] }

        // Write to a temp path so a failure doesn't destroy an existing file.
        let outputURL = URL(fileURLWithPath: outputPath)
        let tempPath = outputURL.deletingLastPathComponent()
            .appendingPathComponent(".\(UUID().uuidString).\(outputURL.pathExtension)").path
        var tempArgs = args
        if let idx = tempArgs.firstIndex(of: outputPath) {
            tempArgs[idx] = tempPath
        }

        let result = try await run(
            .name(bin),
            arguments: Arguments(tempArgs),
            environment: environmentForCLI(),
            output: .string(limit: 52_428_800)
        )
        guard result.terminationStatus.isSuccess else {
            try? FileManager.default.removeItem(atPath: tempPath)
            throw CLIBridgeError.processExitedWithError(
                code: terminationCode(result.terminationStatus)
            )
        }
        // Replay with zero pairs exits 0 but writes no file — surface as an error.
        guard FileManager.default.fileExists(atPath: tempPath) else {
            throw CLIBridgeError.emptyOutput
        }
        // Preserve the CLI-set permissions (e.g. 0755 for shell scripts)
        // before the replace, since replaceItemAt keeps the destination's metadata.
        let tempAttrs = try? FileManager.default.attributesOfItem(atPath: tempPath)
        let tempPerms = tempAttrs?[.posixPermissions] as? Int

        // Atomically replace the destination with the new export.
        if FileManager.default.fileExists(atPath: outputPath) {
            _ = try FileManager.default.replaceItemAt(outputURL, withItemAt: URL(fileURLWithPath: tempPath))
        } else {
            try FileManager.default.moveItem(atPath: tempPath, toPath: outputPath)
        }

        // Reapply the CLI's permissions if replaceItemAt overwrote them.
        if let perms = tempPerms {
            try? FileManager.default.setAttributes([.posixPermissions: perms], ofItemAtPath: outputPath)
        }
    }

    // MARK: - Session Management

    /// Return the cached binary path, falling back to `locateBinary()`.
    private func ensureBinaryPath() async -> String? {
        if let binaryPath { return binaryPath }
        return await locateBinary()
    }

    /// Clear all saved scan sessions via CLI `--clear-sessions`.
    func clearSessions() async {
        guard let path = await ensureBinaryPath() else { return }
        _ = try? await run(
            .name(path),
            arguments: ["scan", "--clear-sessions"],
            environment: shellEnvironment,
            output: .string(limit: 1024)
        )
    }

    /// Delete a specific saved scan session via CLI `--delete-session`.
    func deleteSession(_ sessionId: String) async {
        guard let path = await ensureBinaryPath() else { return }
        _ = try? await run(
            .name(path),
            arguments: ["scan", "--delete-session", sessionId],
            environment: shellEnvironment,
            output: .string(limit: 1024)
        )
    }

    /// List saved scan sessions as structured data via CLI `--list-sessions-json`.
    ///
    /// Returns `nil` when the command could not be executed (binary not found,
    /// subprocess error, decoding failure) — callers must distinguish this from
    /// a successful empty result (`[]`).
    func listSessionsJSON() async -> [SessionInfo]? {
        guard let path = await ensureBinaryPath() else { return nil }
        do {
            let result = try await run(
                .name(path),
                arguments: ["scan", "--list-sessions-json"],
                environment: shellEnvironment,
                output: .string(limit: 1_048_576)
            )
            guard let output = result.standardOutput,
                  let data = output.data(using: .utf8) else { return nil }
            return (try? JSONDecoder().decode([SessionInfo].self, from: data)) ?? nil
        } catch {
            return nil
        }
    }

    // MARK: - Scan

    /// Run a scan and stream progress events, concluding with the result.
    func runScan(config: ScanConfig) -> AsyncThrowingStream<CLIOutput, any Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                #if DEBUG
                log.notice("[bridge] internal task body entered, awaiting executeScan on bridge actor")
                #endif
                do {
                    try await self.executeScan(config: config, continuation: continuation)
                    #if DEBUG
                    log.notice("[bridge] executeScan returned normally")
                    #endif
                } catch is CancellationError {
                    #if DEBUG
                    log.notice("[bridge] executeScan threw CancellationError")
                    #endif
                    continuation.finish(throwing: CancellationError())
                } catch {
                    #if DEBUG
                    log.error("[bridge] executeScan threw: \(error.localizedDescription, privacy: .public)")
                    #endif
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { @Sendable _ in
                let pid = _childPID.load(ordering: .relaxed)
                #if DEBUG
                log.notice("[bridge] onTermination fired, pid=\(pid)")
                #endif
                // Kill the process GROUP (negative PID) so ffprobe/ffmpeg/fpcalc
                // children are terminated too.
                // Synchronous via the atomic PID — no actor hop needed.
                if pid > 0 { kill(-pid, SIGTERM) }
                task.cancel()
            }
        }
    }

    /// Send SIGTERM to the running CLI process group immediately.
    ///
    /// Uses negative PID to target the entire process group (CLI + its
    /// ffprobe/ffmpeg/fpcalc children). Requires the subprocess to have been
    /// launched with `processGroupID: 0` so it has its own group.
    ///
    /// `nonisolated` + `static`: the signal must fire synchronously on the
    /// calling thread without waiting for the actor, matching the
    /// ``sendPauseSignal()`` / ``sendResumeSignal()`` pattern.
    nonisolated static func sendTerminateSignal() {
        let pid = _childPID.load(ordering: .relaxed)
        guard pid > 0 else { return }
        // Kill the process GROUP (negative PID) so ffprobe/ffmpeg/fpcalc
        // children are terminated too, preventing orphaned I/O on slow drives.
        kill(-pid, SIGTERM)
    }

    private func executeScan(
        config: ScanConfig,
        continuation: AsyncThrowingStream<CLIOutput, any Error>.Continuation
    ) async throws {
        #if DEBUG
        log.notice("[bridge] executeScan entered (bridge actor acquired)")
        #endif
        consumeInvalidationFlag()
        guard let bin = binaryPath else {
            throw CLIBridgeError.binaryNotFound
        }

        // Ensure the full login-shell PATH is resolved before launching
        // the CLI.  locateBinary() may have found the binary via an
        // absolute-path branch without ever calling resolveShellEnvironment(),
        // leaving shellEnvironment at the minimal GUI-inherited PATH.
        await resolveShellEnvironment()

        // Redirect CLI JSON output to a temp file so we can keep
        // preferredBufferSize: 1 for responsive stderr progress events
        // without paying the 1-byte-at-a-time DispatchIO overhead on
        // stdout.  swift-subprocess uses preferredBufferSize as the
        // DispatchIO read length for ALL pipes — with value 1, each read
        // returns at most 1 byte.  For a 200 MB JSON envelope, that means
        // 200 million DispatchIO callbacks (~18 µs each ≈ 1 hour).
        // Writing to a file and reading it after exit eliminates this
        // entirely while stderr stays responsive.
        let resultFileURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("dd-result-\(UUID().uuidString).json")
        var scanConfig = config
        scanConfig.resultOutputFile = resultFileURL.path

        let args = FlagAssembler.assembleFlags(from: scanConfig)
        #if DEBUG
        log.notice("[executeScan] bin=\(bin, privacy: .public), args=\(args, privacy: .public)")
        #endif

        // processGroupID: 0 gives the CLI its own process group so that
        // cancellation kills ffprobe/ffmpeg/fpcalc children too — not just
        // the Python parent.  Without this, orphaned children saturate disk
        // I/O on slow external drives and block subsequent scans.
        //
        // preferredBufferSize: 1 makes DispatchIO deliver stderr data as
        // soon as ANY bytes arrive, instead of accumulating 16KB (page size).
        // Without this, progress events sit in the kernel pipe buffer until
        // 16KB accrues — which can take 50+ seconds on a slow external drive
        // with sparse events, causing the GUI to show 0% indefinitely.
        //
        // Stdout is redirected to a temp file (--output) to avoid the
        // 1-byte-at-a-time read penalty on the JSON envelope pipe.
        var stderrText = ""
        var platformOptions = PlatformOptions()
        platformOptions.processGroupID = 0
        let result = try await run(
            .name(bin),
            arguments: Arguments(args),
            environment: environmentForCLI(),
            platformOptions: platformOptions,
            preferredBufferSize: 1
        ) { (execution: Execution, _: StandardInputWriter, stdout: AsyncBufferSequence, stderr: AsyncBufferSequence) in
            self.setCurrentExecution(execution)
            defer {
                #if DEBUG
                log.notice("[bridge] body defer: clearing currentExecution, pid was \(execution.processIdentifier.value)")
                #endif
                self.clearCurrentExecution()
            }
            #if DEBUG
            log.notice("[bridge] subprocess launched pid=\(execution.processIdentifier.value), reading stderr")
            #endif

            // Read stderr for progress events (line-buffered) concurrently.
            // Non-progress lines are collected for error reporting.
            let stderrTask = Task {
                var nonProgressLines: [String] = []
                var yieldCount = 0
                try await forEachBufferedLine(from: stderr) { line in
                    if let event = ProgressEventParser.parseLine(line) {
                        continuation.yield(.progress(event))
                        yieldCount += 1
                        #if DEBUG
                        if yieldCount <= 5 || yieldCount % 50 == 0 {
                            log.notice("[executeScan] yielded event #\(yieldCount, privacy: .public): \(String(describing: event).prefix(120), privacy: .public)")
                        }
                        #endif
                    } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                        nonProgressLines.append(line)
                        #if DEBUG
                        log.notice("[executeScan] non-progress stderr: \(line.prefix(200), privacy: .public)")
                        #endif
                    }
                }
                #if DEBUG
                log.notice("[executeScan] stderr done, total yielded=\(yieldCount, privacy: .public)")
                #endif
                return nonProgressLines.joined(separator: "\n")
            }
            // Ensure stderr reader is cancelled on all exit paths
            // (e.g. stdout throw, cancellation). The explicit `try await stderrTask.value`
            // below handles the normal cleanup path; on cancellation the subprocess pipe
            // will EOF when the process terminates.
            defer { stderrTask.cancel() }

            // Drain stdout without accumulating — JSON output goes to the
            // temp file via --output.  We still need to drain the pipe so
            // the CLI doesn't block if it writes anything unexpected to stdout
            // (e.g., Python warnings before the JSON).
            for try await _ in stdout {}

            do {
                stderrText = try await stderrTask.value
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                stderrText = ""
            }
        }

        // If the task was cancelled (user hit Cancel), treat any non-zero exit
        // as cancellation rather than an error — the CLI was killed by our SIGTERM.
        #if DEBUG
        log.notice("[executeScan] process exited, status=\(result.terminationStatus.debugDescription, privacy: .public)")
        #endif
        try throwIfFailed(result.terminationStatus, stderr: stderrText)

        // Read the JSON envelope from the temp file (instant — no pipe overhead).
        defer { try? FileManager.default.removeItem(at: resultFileURL) }
        if FileManager.default.fileExists(atPath: resultFileURL.path) {
            let stdoutData = try Data(contentsOf: resultFileURL)
            #if DEBUG
            log.notice("[executeScan] read result file, bytes=\(stdoutData.count, privacy: .public)")
            #endif
            if !stdoutData.isEmpty {
                let envelope = try JSONEnvelopeParser.parse(data: stdoutData)
                continuation.yield(.result(envelope, stdoutData))
            }
        }

        continuation.finish()
    }

    // MARK: - Cancellation

    /// Send SIGTERM to the running process group.
    func cancelCurrentTask() {
        let hasExec = currentExecution != nil
        #if DEBUG
        log.notice("[bridge] cancelCurrentTask called, hasExecution=\(hasExec)")
        #endif
        guard let execution = currentExecution else { return }
        try? execution.send(signal: .terminate, toProcessGroup: true)
    }

    // MARK: - Pause / Resume via Signal

    /// Send SIGUSR1 to the running CLI process to request a pause.
    ///
    /// The CLI's signal handler calls ``PipelineController.pause()`` which
    /// emits a ``pause`` progress event back to the GUI.  This is instant
    /// and does not depend on the 500ms file-polling interval.
    ///
    /// `nonisolated` + `static`: the signal must fire immediately on the
    /// calling thread.  Actor isolation would enqueue behind the stderr
    /// reader, delaying the signal indefinitely.
    nonisolated static func sendPauseSignal() {
        let pid = _childPID.load(ordering: .relaxed)
        guard pid > 0 else { return }
        kill(pid, SIGUSR1)
    }

    /// Send SIGUSR2 to the running CLI process to request a resume.
    nonisolated static func sendResumeSignal() {
        let pid = _childPID.load(ordering: .relaxed)
        guard pid > 0 else {
            log.warning("sendResumeSignal: _childPID is 0, signal not sent")
            return
        }
        log.info("sendResumeSignal: sending SIGUSR2 to pid \(pid)")
        kill(pid, SIGUSR2)
    }

    // MARK: - Helpers

    /// Check non-zero exit, strip ANSI codes from stderr, and throw the appropriate error.
    private func throwIfFailed(_ status: TerminationStatus, stderr: String) throws {
        guard !status.isSuccess else { return }
        if Task.isCancelled { throw CancellationError() }
        let cleaned = stderr
            .replacingOccurrences(of: "\\x1b\\[[0-9;]*m", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            throw CLIBridgeError.processExitedWithError(code: terminationCode(status))
        } else {
            throw CLIBridgeError.processExitedWithErrorMessage(code: terminationCode(status), stderr: cleaned)
        }
    }

    private func setCurrentExecution(_ e: Execution) {
        currentExecution = e
        let pid = e.processIdentifier.value
        _childPID.store(pid, ordering: .relaxed)
        Self.writePIDFile(pid)
    }

    private func clearCurrentExecution() {
        currentExecution = nil
        _childPID.store(0, ordering: .relaxed)
        Self.removePIDFile()
    }

    /// Resolve the user's full login-shell PATH and store it for all subprocess calls.
    ///
    /// Uses `/usr/bin/env PATH` inside a login shell to get the raw colon-separated
    /// PATH string, which avoids shell-specific expansion (e.g. fish outputs
    /// space-separated lists from `echo $PATH`). Falls back to `printenv PATH`
    /// for shells that don't support `-l -c`.
    private func resolveShellEnvironment(forceRefresh: Bool = false) async {
        guard forceRefresh || !didResolveShellEnvironment else { return }

        let shell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        // Use printenv to get the raw PATH — immune to shell-specific variable rendering.
        guard let result = try? await run(
            .name(shell),
            arguments: ["-l", "-c", "/usr/bin/printenv PATH"],
            environment: Self.sanitizedInheritedEnvironment(),
            output: .string(limit: 8192)
        ), result.terminationStatus.isSuccess else { return }

        // Take only the last non-empty line — shell startup scripts
        // (motd, banners, warnings) may print to stdout before the PATH value.
        let output = (result.standardOutput ?? "")
            .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
        let resolvedPath = output.components(separatedBy: CharacterSet.newlines)
            .last { !$0.trimmingCharacters(in: CharacterSet.whitespaces).isEmpty }
            ?? ""
        guard !resolvedPath.isEmpty else { return }
        resolvedPathString = resolvedPath
        shellEnvironment = Self.sanitizedInheritedEnvironment(path: resolvedPath)
        didResolveShellEnvironment = true
    }

    private func runWhich(_ tool: String, refreshShellEnvironment: Bool = false) async -> String? {
        if let path = await runWhichInCurrentEnvironment(tool) {
            return path
        }

        let shouldRefresh = refreshShellEnvironment || !didResolveShellEnvironment
        guard shouldRefresh else { return nil }

        await resolveShellEnvironment(forceRefresh: refreshShellEnvironment)
        return await runWhichInCurrentEnvironment(tool)
    }

    private func runWhichInCurrentEnvironment(_ tool: String) async -> String? {
        guard let result = try? await run(
            .name("/usr/bin/which"),
            arguments: [tool],
            environment: shellEnvironment,
            output: .string(limit: 4096)
        ) else { return nil }

        guard result.terminationStatus.isSuccess else { return nil }
        let path = (result.standardOutput ?? "")
            .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
        guard !path.isEmpty else { return nil }
        return path
    }

    /// Check CLI availability, honoring the already-resolved `binaryPath`.
    ///
    /// Stricter than `checkTool`: requires `--version` to exit 0, since
    /// `duplicates-detector` is our own tool and a non-zero exit indicates a
    /// broken install (missing Python deps, corrupt entry point, etc.).
    private func checkCLI() async -> ToolStatus {
        let path = if let binaryPath {
            binaryPath
        } else {
            await locateBinary()
        }

        guard let path else {
            log.warning("checkCLI: no binary path available")
            return ToolStatus(name: "duplicates-detector", isAvailable: false, path: nil, version: nil, isRequired: true)
        }

        log.debug("checkCLI: running --version at \(path)")
        guard let result = try? await run(
            .name(path),
            arguments: ["--version"],
            environment: environmentForCLI(),
            output: .string(limit: 4096)
        ) else {
            log.error("checkCLI: run threw for \(path)")
            return ToolStatus(name: "duplicates-detector", isAvailable: false, path: path, version: nil, isRequired: true)
        }
        guard result.terminationStatus.isSuccess else {
            log.warning("checkCLI: --version exited \(self.terminationCode(result.terminationStatus))")
            return ToolStatus(name: "duplicates-detector", isAvailable: false, path: path, version: nil, isRequired: true)
        }

        var version: String?
        let output = (result.standardOutput ?? "")
            .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
        if !output.isEmpty {
            version = output.components(separatedBy: CharacterSet.newlines).first
        }

        return ToolStatus(name: "duplicates-detector", isAvailable: true, path: path, version: version, isRequired: true)
    }

    /// Probe whether the CLI's Python environment has mutagen installed.
    ///
    /// Runs `scan --mode audio <empty-dir>` which hits the mutagen import
    /// check immediately and exits 0 ("Found 0 audio file(s)") if present,
    /// or exits 1 with "requires mutagen" if missing. Uses a freshly created
    /// empty directory to avoid scanning unrelated files.
    /// Check whether a Python module is importable by the CLI's Python.
    ///
    /// Finds the Python interpreter by reading the shebang line from the CLI
    /// entry-point script (all pip-installed scripts have `#!/path/to/python3`).
    /// Falls back to a sibling python3 next to the resolved binary path.
    private func checkPythonImport(_ module: String) async -> Bool {
        guard let python = resolveCLIPython() else { return false }
        guard let result = try? await run(
            .name(python),
            arguments: ["-c", "import \(module)"],
            environment: environmentForCLI(),
            output: .string(limit: 1024)
        ) else { return false }
        return result.terminationStatus.isSuccess
    }

    /// Resolve the Python interpreter that the CLI entry-point uses.
    ///
    /// Strategy:
    /// 1. Read the shebang from the CLI script — pip/pipx/venv entry points
    ///    always embed the full interpreter path (e.g. `#!/home/user/.venv/bin/python3`).
    /// 2. Fall back to sibling python3 next to the symlink-resolved binary path.
    private func resolveCLIPython() -> String? {
        guard let bin = binaryPath else { return nil }

        // 1. Parse shebang from the CLI entry-point script.
        if let data = FileManager.default.contents(atPath: bin),
           let firstLine = String(data: data.prefix(256), encoding: .utf8)?
            .components(separatedBy: CharacterSet.newlines).first,
           firstLine.hasPrefix("#!") {
            let shebang = String(firstLine.dropFirst(2))
                .trimmingCharacters(in: CharacterSet.whitespaces)
            if shebang.hasPrefix("/usr/bin/env ") {
                // "#!/usr/bin/env python3" — extract bare name; caller uses .name()
                // which resolves via PATH, matching env shebang behavior.
                let command = String(shebang.dropFirst("/usr/bin/env ".count))
                    .trimmingCharacters(in: CharacterSet.whitespaces)
                if !command.isEmpty { return command }
            } else if FileManager.default.isExecutableFile(atPath: shebang) {
                return shebang
            }
        }

        // 2. Fallback: sibling python3 next to the resolved binary.
        let resolved = (bin as NSString).resolvingSymlinksInPath
        let binDir = (resolved as NSString).deletingLastPathComponent
        let python = (binDir as NSString).appendingPathComponent("python3")
        if FileManager.default.isExecutableFile(atPath: python) {
            return python
        }

        return nil
    }

    private func checkTool(_ name: String, required: Bool) async -> ToolStatus {
        // Check bundled tools first (highest priority)
        if let toolsDir = bundledToolsPath() {
            let bundledPath = (toolsDir as NSString).appendingPathComponent(name)
            if isExecutable(atPath: bundledPath) {
                return await checkToolAtPath(name, path: bundledPath, required: required)
            }
        }

        // Check user-configured path (Settings > External Tools)
        let userPath: String? = switch name {
        case "ffmpeg": AppDefaults.ffmpegPath
        case "ffprobe": AppDefaults.ffprobePath
        default: nil
        }
        if let resolved = normalizeExecutablePath(userPath), isExecutable(atPath: resolved) {
            return await checkToolAtPath(name, path: resolved, required: required)
        }

        if let path = firstExecutablePath(in: commonExecutableCandidates(named: name)) {
            return await checkToolAtPath(name, path: path, required: required)
        }

        guard let path = await runWhich(name) else {
            return ToolStatus(name: name, isAvailable: false, path: nil, version: nil, isRequired: required)
        }
        return await checkToolAtPath(name, path: path, required: required)
    }

    /// Check a third-party tool's availability by attempting to launch it.
    ///
    /// **Intentional design: a non-zero `--version` exit code does NOT mark
    /// the tool as unavailable.** Many working third-party tools exit non-zero
    /// from `--version` (e.g., `ffmpeg --version` exits 8, `ffprobe --version`
    /// exits 1 on standard Homebrew installs). Only a launch failure (wrong
    /// arch, corrupt binary, stale symlink) marks the tool unavailable.
    ///
    /// This differs from ``checkCLI()`` which requires exit 0, because
    /// `duplicates-detector` is our own tool with reliable `--version` behavior.
    private func checkToolAtPath(_ name: String, path: String, required: Bool) async -> ToolStatus {
        var version: String?
        // If the binary cannot be launched at all (wrong arch, corrupt, stale
        // symlink), mark it unavailable rather than letting the user start a
        // scan that will immediately fail.
        guard let result = try? await run(
            .name(path),
            arguments: ["--version"],
            environment: shellEnvironment,
            output: .string(limit: 4096)
        ) else {
            log.error("checkToolAtPath(\(name)): run threw for path=\(path)")
            return ToolStatus(name: name, isAvailable: false, path: path, version: nil, isRequired: required)
        }

        // Version string is best-effort; non-zero exit is expected for some
        // tools (see doc comment above) so we only parse on success.
        if result.terminationStatus.isSuccess {
            let output = (result.standardOutput ?? "")
                .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
            if !output.isEmpty {
                version = output.components(separatedBy: CharacterSet.newlines).first
            }
        }

        return ToolStatus(name: name, isAvailable: true, path: path, version: version, isRequired: required)
    }

    private nonisolated func terminationCode(_ status: TerminationStatus) -> Int32 {
        switch status {
        case .exited(let code): return code
        case .unhandledException(let code): return code
        @unknown default: return -1
        }
    }

    private func firstExecutablePath(in paths: [String?]) -> String? {
        for path in paths {
            guard let normalizedPath = normalizeExecutablePath(path) else { continue }
            if isExecutable(atPath: normalizedPath) {
                return normalizedPath
            }
        }
        return nil
    }

    private func firstExecutablePath(in paths: [String]) -> String? {
        firstExecutablePath(in: paths.map(Optional.some))
    }

    private func normalizeExecutablePath(_ path: String?) -> String? {
        guard let path, !path.isEmpty else { return nil }

        let expandedPath = (path as NSString).expandingTildeInPath
        guard !expandedPath.isEmpty else { return nil }
        return URL(fileURLWithPath: expandedPath).standardizedFileURL.path
    }

    private func isExecutable(atPath path: String) -> Bool {
        FileManager.default.isExecutableFile(atPath: path)
    }

    private func persistUserConfiguredPath(_ path: String) {
        UserDefaults.standard.set(path, forKey: Self.userConfiguredPathDefaultsKey)
    }

    /// Tracks whether the persisted binary path was externally cleared
    /// (e.g., by "Reset All Defaults") so the next `locateBinary()` call
    /// on any live instance discards its in-memory cache.
    private static let _cacheInvalidated = OSAllocatedUnfairLock(initialState: false)

    /// Clear the persisted CLI binary override from UserDefaults and
    /// signal all live instances to discard their in-memory cache.
    ///
    /// Static variant for use by "Reset All Defaults" where no `CLIBridge`
    /// instance is available.
    static func clearPersistedBinaryPath() {
        UserDefaults.standard.removeObject(forKey: userConfiguredPathDefaultsKey)
        _cacheInvalidated.withLock { $0 = true }
    }

    /// Remove the persisted manual CLI override so the next
    /// ``locateBinary()`` call falls through to auto-detection.
    func clearPersistedUserConfiguredPath() {
        UserDefaults.standard.removeObject(forKey: Self.userConfiguredPathDefaultsKey)
        binaryPath = nil
    }

    private func persistedUserConfiguredPath() -> String? {
        guard let storedPath = normalizeExecutablePath(
            UserDefaults.standard.string(forKey: Self.userConfiguredPathDefaultsKey)
        ) else {
            return nil
        }

        guard isExecutable(atPath: storedPath) else {
            UserDefaults.standard.removeObject(forKey: Self.userConfiguredPathDefaultsKey)
            return nil
        }

        return storedPath
    }

    /// Whether the app bundle contains an embedded CLI.
    nonisolated func hasBundledCLI() -> Bool {
        bundledBinaryPathSync() != nil
    }

    private func bundledBinaryPath() -> String? {
        bundledBinaryPathSync()
    }

    /// Shared implementation for ``hasBundledCLI()`` and ``bundledBinaryPath()``.
    ///
    /// Uses `FileManager.fileExists` (matching ``bundledToolsPath()``) instead of
    /// `Bundle.path(forResource:ofType:inDirectory:)` which fails for scripts
    /// injected into deeply nested bundle directories after the Xcode build.
    private nonisolated func bundledBinaryPathSync() -> String? {
        for bundle in [Bundle.main, Bundle(for: CLIBridgeBundleToken.self)] {
            if let resourcePath = bundle.resourcePath {
                let cliPath = (resourcePath as NSString).appendingPathComponent("cli/venv/bin/duplicates-detector")
                if FileManager.default.fileExists(atPath: cliPath) {
                    return cliPath
                }
            }
        }
        return nil
    }

    /// Path to the bundled native tools directory (ffmpeg, ffprobe, fpcalc).
    /// Returns `nil` when running from source (no bundled tools).
    private func bundledToolsPath() -> String? {
        for bundle in [Bundle.main, Bundle(for: CLIBridgeBundleToken.self)] {
            if let resourcePath = bundle.resourcePath {
                let toolsDir = (resourcePath as NSString).appendingPathComponent("cli/bin")
                if FileManager.default.fileExists(atPath: (toolsDir as NSString).appendingPathComponent("ffmpeg")) {
                    return toolsDir
                }
            }
        }
        return nil
    }

    /// Path to the bundled venv bin directory.
    /// Returns `nil` when running from source (no bundled venv).
    private func bundledVenvBinPath() -> String? {
        for bundle in [Bundle.main, Bundle(for: CLIBridgeBundleToken.self)] {
            if let resourcePath = bundle.resourcePath {
                let venvBin = (resourcePath as NSString).appendingPathComponent("cli/venv/bin")
                if FileManager.default.fileExists(atPath: (venvBin as NSString).appendingPathComponent("python3")) {
                    return venvBin
                }
            }
        }
        return nil
    }

    private func developmentBinaryPathFromInfoDictionary() -> String? {
        guard let rawValue = Bundle.main.object(forInfoDictionaryKey: Self.developmentPathInfoKey) as? String else {
            return nil
        }

        let trimmedValue = rawValue.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
        guard !trimmedValue.isEmpty else { return nil }
        return trimmedValue
    }

    #if DEBUG
    private func sourceTreeDevelopmentCandidates() -> [String] {
        var candidates: [String] = []
        var currentURL = URL(fileURLWithPath: #filePath).deletingLastPathComponent()

        for _ in 0..<10 {
            let pyprojectPath = currentURL.appendingPathComponent("pyproject.toml").path
            let gitPath = currentURL.appendingPathComponent(".git").path
            if FileManager.default.fileExists(atPath: pyprojectPath) ||
                FileManager.default.fileExists(atPath: gitPath) {
                candidates.append(currentURL.appendingPathComponent(".venv/bin/duplicates-detector").path)
            }
            currentURL.deleteLastPathComponent()
        }

        return candidates
    }
    #endif

    private func commonExecutableCandidates(named name: String) -> [String] {
        [
            "\(NSHomeDirectory())/.local/bin/\(name)",
            "\(NSHomeDirectory())/.pyenv/shims/\(name)",
            "/opt/homebrew/bin/\(name)",
            "/usr/local/bin/\(name)",
            "/usr/bin/\(name)",
            "/bin/\(name)",
        ]
    }

    // MARK: - PID File (Orphan Cleanup)

    private static var pidFileURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("DuplicatesDetector", isDirectory: true)
            .appendingPathComponent("cli.pid")
    }

    private static func writePIDFile(_ pid: pid_t) {
        let url = pidFileURL
        let dir = url.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? Data("\(pid)\n".utf8).write(to: url, options: .atomic)
    }

    private static func removePIDFile() {
        try? FileManager.default.removeItem(at: pidFileURL)
    }

    /// Kill any orphaned CLI subprocess left behind by a previous crash or
    /// force-quit.  Safe to call on every launch — validates the stored PID
    /// belongs to a ``duplicates-detector`` process before sending signals.
    func cleanupOrphanedProcess() {
        let url = Self.pidFileURL
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8)?
                  .trimmingCharacters(in: .whitespacesAndNewlines),
              let pid = pid_t(text),
              pid > 0
        else { return }

        // Remove the file first to avoid repeated attempts.
        try? FileManager.default.removeItem(at: url)

        // Is the process still alive?
        guard kill(pid, 0) == 0 else { return }

        // Verify it really is a duplicates-detector process (PID may have
        // been recycled since the crash).
        guard Self.isProcessDuplicatesDetector(pid: pid) else { return }

        kill(pid, SIGTERM)
        usleep(200_000)
        if kill(pid, 0) == 0 {
            kill(pid, SIGKILL)
        }
    }

    /// Check whether *pid* belongs to a ``duplicates-detector`` (or
    /// ``duplicates_detector``) process via ``sysctl(KERN_PROCARGS2)``.
    private static func isProcessDuplicatesDetector(pid: pid_t) -> Bool {
        var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, pid]
        var size = 0
        guard sysctl(&mib, UInt32(mib.count), nil, &size, nil, 0) == 0, size > 0 else {
            return false
        }
        var buffer = [UInt8](repeating: 0, count: size)
        guard sysctl(&mib, UInt32(mib.count), &buffer, &size, nil, 0) == 0 else {
            return false
        }
        // KERN_PROCARGS2: first 4 bytes = argc, then the executable path
        // (null-terminated).
        guard size > MemoryLayout<Int32>.size else { return false }
        let execBytes = buffer.dropFirst(MemoryLayout<Int32>.size)
        guard let nullIndex = execBytes.firstIndex(of: 0) else { return false }
        let path = String(decoding: execBytes[execBytes.startIndex..<nullIndex], as: UTF8.self)
        return path.contains("duplicates-detector") || path.contains("duplicates_detector")
    }

    /// Returns the shell environment with user-configured tool directories
    /// prepended to PATH, so the CLI subprocess finds custom ffmpeg/ffprobe.
    private func environmentForCLI() -> Environment {
        var extraDirs: [String] = []

        // Bundled tools take highest priority
        if let toolsDir = bundledToolsPath() {
            extraDirs.append(toolsDir)
        }
        if let venvBin = bundledVenvBinPath() {
            extraDirs.append(venvBin)
        }

        // User-configured paths next
        let ffmpegDir = normalizeExecutablePath(AppDefaults.ffmpegPath)
            .map { ($0 as NSString).deletingLastPathComponent } ?? ""
        let ffprobeDir = normalizeExecutablePath(AppDefaults.ffprobePath)
            .map { ($0 as NSString).deletingLastPathComponent } ?? ""
        if !ffmpegDir.isEmpty, ffmpegDir != "." { extraDirs.append(ffmpegDir) }
        if !ffprobeDir.isEmpty, ffprobeDir != ".", !extraDirs.contains(ffprobeDir) {
            extraDirs.append(ffprobeDir)
        }

        guard !extraDirs.isEmpty else { return shellEnvironment }
        let basePath = resolvedPathString
            ?? ProcessInfo.processInfo.environment["PATH"]
            ?? "/usr/bin:/bin"
        let newPath = (extraDirs + [basePath]).joined(separator: ":")
        return Self.sanitizedInheritedEnvironment(path: newPath)
    }

    private static func sanitizedInheritedEnvironment(path: String? = nil) -> Environment {
        var overrides: [Environment.Key: String?] = [:]
        for key in injectedEnvironmentKeysToRemove {
            overrides[key] = nil
        }
        if let path {
            overrides["PATH"] = path
        }
        // Disable Python's output buffering so progress events written to
        // stderr are immediately available on the pipe (not block-buffered).
        overrides["PYTHONUNBUFFERED"] = "1"
        return .inherit.updating(overrides)
    }
}

private final class CLIBridgeBundleToken {}

/// Errors from the CLI bridge.
enum CLIBridgeError: Error, LocalizedError {
    case binaryNotFound
    case processExitedWithError(code: Int32)
    case processExitedWithErrorMessage(code: Int32, stderr: String)
    case emptyOutput

    var errorDescription: String? {
        switch self {
        case .binaryNotFound:
            "duplicates-detector binary not found"
        case .processExitedWithError(let code):
            "CLI process exited with code \(code)"
        case .processExitedWithErrorMessage(_, let stderr):
            stderr
        case .emptyOutput:
            "No undo script generated — the action log may be empty or contain only dry-run entries"
        }
    }
}
