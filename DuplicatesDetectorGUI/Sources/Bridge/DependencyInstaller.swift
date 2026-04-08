import Foundation
import os
import Subprocess

private let log = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "DependencyInstaller")

/// What needs to be installed and how.
struct InstallPlan: Sendable {
    struct Step: Sendable {
        let name: String
        let displayName: String
        let executable: String
        let arguments: [String]
    }

    let steps: [Step]
    /// Whether any step requires Homebrew.
    let requiresHomebrew: Bool
    /// Whether Homebrew is needed but not found on this system.
    let homebrewMissing: Bool
}

/// Actor that runs dependency installation commands.
///
/// Separate from ``CLIBridge`` to keep scan lifecycle isolated from
/// installation lifecycle. Accepts the resolved shell environment from
/// ``CLIBridge`` so subprocess PATH resolution is consistent.
actor DependencyInstaller {
    private let shellEnvironment: Environment
    private var currentExecution: Execution?

    init(shellEnvironment: Environment) {
        self.shellEnvironment = shellEnvironment
    }

    // MARK: - Plan Building

    /// Build an installation plan based on current dependency status.
    ///
    /// Steps are ordered: CLI first (if missing), then Homebrew formulas,
    /// then pip packages that depend on the CLI's Python.
    nonisolated func buildPlan(
        for status: DependencyStatus,
        cliPython: String?,
        brewPath: String?,
        isBundled: Bool = false
    ) -> InstallPlan {
        // Bundled app has all deps pre-installed — nothing to install.
        if isBundled {
            return InstallPlan(steps: [], requiresHomebrew: false, homebrewMissing: false)
        }

        var steps: [InstallPlan.Step] = []
        var needsBrew = false

        // 1. CLI itself (installs with all extras so mutagen/scikit-image come along)
        if !status.cli.isAvailable {
            let pip = resolvePip3()
            steps.append(InstallPlan.Step(
                name: "duplicates-detector",
                displayName: "Duplicates Detector CLI (pip)",
                executable: pip,
                arguments: ["install", "duplicates-detector[audio,ssim,trash,document]"]
            ))
        }

        // 2. ffmpeg (includes ffprobe)
        if !status.ffmpeg.isAvailable || !status.ffprobe.isAvailable {
            needsBrew = true
            if let brew = brewPath {
                steps.append(InstallPlan.Step(
                    name: "ffmpeg",
                    displayName: "FFmpeg (Homebrew)",
                    executable: brew,
                    arguments: ["install", "ffmpeg"]
                ))
            }
        }

        // 3. fpcalc (chromaprint)
        if !status.fpcalc.isAvailable {
            needsBrew = true
            if let brew = brewPath {
                steps.append(InstallPlan.Step(
                    name: "chromaprint",
                    displayName: "Chromaprint / fpcalc (Homebrew)",
                    executable: brew,
                    arguments: ["install", "chromaprint"]
                ))
            }
        }

        // 4. Python packages (only if CLI already exists — otherwise step 1 installed extras)
        if status.cli.isAvailable {
            if let python = cliPython {
                let isPipx = python.contains(".local/share/pipx/")
                    || python.contains(".local/pipx/")

                if !status.hasMutagen {
                    if isPipx {
                        let pipx = resolvePipx()
                        steps.append(InstallPlan.Step(
                            name: "mutagen",
                            displayName: "mutagen (pipx inject)",
                            executable: pipx,
                            arguments: ["inject", "duplicates-detector", "mutagen"]
                        ))
                    } else {
                        steps.append(InstallPlan.Step(
                            name: "mutagen",
                            displayName: "mutagen (pip)",
                            executable: python,
                            arguments: ["-m", "pip", "install", "mutagen"]
                        ))
                    }
                }

                if !status.hasSkimage {
                    if isPipx {
                        let pipx = resolvePipx()
                        steps.append(InstallPlan.Step(
                            name: "scikit-image",
                            displayName: "scikit-image (pipx inject)",
                            executable: pipx,
                            arguments: ["inject", "duplicates-detector", "scikit-image"]
                        ))
                    } else {
                        steps.append(InstallPlan.Step(
                            name: "scikit-image",
                            displayName: "scikit-image (pip)",
                            executable: python,
                            arguments: ["-m", "pip", "install", "scikit-image"]
                        ))
                    }
                }
            }
        }

        let homebrewMissing = needsBrew && brewPath == nil
        return InstallPlan(
            steps: steps,
            requiresHomebrew: needsBrew,
            homebrewMissing: homebrewMissing
        )
    }

    // MARK: - Execution

    /// Execute the installation plan, streaming events via ``AsyncStream``.
    func install(plan: InstallPlan) -> AsyncStream<InstallEvent> {
        AsyncStream { continuation in
            let task = Task { [shellEnvironment] in
                for (index, step) in plan.steps.enumerated() {
                    guard !Task.isCancelled else { break }

                    continuation.yield(.stepStart(stepIndex: index, command: step.displayName))
                    log.info("Installing step \(index): \(step.displayName)")

                    do {
                        let result = try await run(
                            .name(step.executable),
                            arguments: Arguments(step.arguments),
                            environment: shellEnvironment
                        ) { (
                            execution: Execution,
                            _: StandardInputWriter,
                            stdout: AsyncBufferSequence,
                            stderr: AsyncBufferSequence
                        ) in
                            self.currentExecution = execution
                            defer { self.currentExecution = nil }

                            // Stream both stdout and stderr line-buffered.
                            let stderrTask = Task {
                                await Self.streamLines(from: stderr, stepIndex: index, continuation: continuation)
                            }
                            await Self.streamLines(from: stdout, stepIndex: index, continuation: continuation)
                            await stderrTask.value
                        }

                        let success = result.terminationStatus.isSuccess
                        if !success {
                            log.warning("Step \(index) (\(step.name)) exited with non-zero status")
                        }
                        continuation.yield(.stepEnd(
                            stepIndex: index,
                            success: success,
                            message: success ? nil : "Exited with non-zero status"
                        ))
                    } catch {
                        log.error("Step \(index) (\(step.name)) failed: \(error)")
                        continuation.yield(.stepEnd(
                            stepIndex: index,
                            success: false,
                            message: error.localizedDescription
                        ))
                    }
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    /// Cancel the currently running subprocess.
    func cancelCurrent() {
        if let exec = currentExecution {
            try? exec.send(signal: .terminate)
            currentExecution = nil
        }
    }

    // MARK: - Tool Resolution

    /// Check if Homebrew is available at well-known paths.
    nonisolated func locateBrew() -> String? {
        resolveExecutable(in: [
            "/opt/homebrew/bin/brew",
            "/usr/local/bin/brew",
        ])
    }

    // MARK: - Private

    /// Return the first executable path from `candidates`, or `fallback`.
    private nonisolated func resolveExecutable(
        in candidates: [String],
        fallback: String? = nil
    ) -> String? {
        for path in candidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }
        return fallback
    }

    private nonisolated func resolvePip3() -> String {
        resolveExecutable(in: [
            "\(NSHomeDirectory())/.local/bin/pip3",
            "/opt/homebrew/bin/pip3",
            "/usr/local/bin/pip3",
            "/usr/bin/pip3",
        ], fallback: "pip3")!
    }

    private nonisolated func resolvePipx() -> String {
        resolveExecutable(in: [
            "\(NSHomeDirectory())/.local/bin/pipx",
            "/opt/homebrew/bin/pipx",
            "/usr/local/bin/pipx",
        ], fallback: "pipx")!
    }

    /// Read lines from an async byte stream and yield them as install events.
    private static func streamLines(
        from stream: AsyncBufferSequence,
        stepIndex: Int,
        continuation: AsyncStream<InstallEvent>.Continuation
    ) async {
        do {
            try await forEachBufferedLine(from: stream) { line in
                if !line.isEmpty {
                    continuation.yield(.output(stepIndex: stepIndex, line: line))
                }
            }
        } catch {
            // Stream ended (cancellation or EOF).
        }
    }
}
