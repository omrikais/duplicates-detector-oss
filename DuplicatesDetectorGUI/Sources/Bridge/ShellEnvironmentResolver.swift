import Foundation

/// XDG variables resolved from the user's login shell.
struct ResolvedShellEnvironment: Sendable, Equatable {
    var xdgConfigHome: String?
    var xdgCacheHome: String?
    var xdgDataHome: String?
}

/// Abstracts how environment variables are read — enables test injection.
protocol EnvironmentProvider: Sendable {
    /// The current process environment dictionary.
    var processEnvironment: [String: String] { get }
    /// Run the user's login shell and return stdout.
    func runLoginShell(command: String) async throws -> String
}

/// Production provider that reads `ProcessInfo` and spawns a real shell.
struct ProcessEnvironmentProvider: EnvironmentProvider {
    var processEnvironment: [String: String] {
        ProcessInfo.processInfo.environment
    }

    func runLoginShell(command: String) async throws -> String {
        // Prefer the passwd database (works when launched from Finder where
        // SHELL is absent), then fall back to the SHELL env var.
        let shell: String = {
            if let pw = getpwuid(getuid()), let cStr = pw.pointee.pw_shell {
                let path = String(cString: cStr)
                if !path.isEmpty { return path }
            }
            return ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        }()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: shell)
        process.arguments = ["-l", "-c", command]

        // Strip Xcode-injected DYLD/XPC keys that can confuse login shells.
        var env = ProcessInfo.processInfo.environment
        for key in env.keys where key.hasPrefix("DYLD_") || key.hasPrefix("XPC_") || key.hasPrefix("__XPC_") {
            env.removeValue(forKey: key)
        }
        process.environment = env

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice

        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            throw ShellProbeError.nonZeroExit(process.terminationStatus)
        }
        return String(decoding: data, as: UTF8.self)
    }
}

enum ShellProbeError: Error {
    case nonZeroExit(Int32)
}

/// Resolves XDG environment variables from the user's login shell.
///
/// macOS apps launched from Finder/Spotlight do not inherit shell-defined
/// environment variables.  This actor spawns the login shell once, reads
/// `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, and `XDG_DATA_HOME`, and caches
/// the result for the session.
actor ShellEnvironmentResolver {
    static let shared = ShellEnvironmentResolver()

    private let provider: EnvironmentProvider
    private var cached: ResolvedShellEnvironment?

    init(provider: EnvironmentProvider = ProcessEnvironmentProvider()) {
        self.provider = provider
    }

    /// Resolve XDG variables, caching the result after the first call.
    func resolve() async -> ResolvedShellEnvironment {
        if let cached { return cached }

        let result = await probeShellEnvironment()
        cached = result
        return result
    }

    /// Clear the cache (useful for tests).
    func reset() {
        cached = nil
    }

    // MARK: - Private

    private static let xdgKeys = ["XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"]

    private func probeShellEnvironment() async -> ResolvedShellEnvironment {
        // First check process environment — covers the terminal-launch case.
        let procEnv = provider.processEnvironment
        let fromProcess = ResolvedShellEnvironment(
            xdgConfigHome: procEnv["XDG_CONFIG_HOME"]?.nonEmpty,
            xdgCacheHome: procEnv["XDG_CACHE_HOME"]?.nonEmpty,
            xdgDataHome: procEnv["XDG_DATA_HOME"]?.nonEmpty
        )

        // If all three are already set, no need to spawn a shell.
        if fromProcess.xdgConfigHome != nil,
           fromProcess.xdgCacheHome != nil,
           fromProcess.xdgDataHome != nil {
            return fromProcess
        }

        // Spawn login shell to resolve missing variables.
        // Each variable is echoed with a known prefix so we can parse
        // reliably even in the presence of motd/banner noise.
        let echoStatements = Self.xdgKeys
            .map { "echo \"__XDG_RESOLVE__\($0)=$\($0)\"" }
            .joined(separator: "; ")

        guard let output = try? await provider.runLoginShell(command: echoStatements) else {
            return fromProcess
        }

        var shellVars: [String: String] = [:]
        for line in output.components(separatedBy: .newlines) {
            guard line.hasPrefix("__XDG_RESOLVE__") else { continue }
            let payload = String(line.dropFirst("__XDG_RESOLVE__".count))
            guard let eqIndex = payload.firstIndex(of: "=") else { continue }
            let key = String(payload[payload.startIndex..<eqIndex])
            let value = String(payload[payload.index(after: eqIndex)...])
            if !value.isEmpty {
                shellVars[key] = value
            }
        }

        return ResolvedShellEnvironment(
            xdgConfigHome: fromProcess.xdgConfigHome ?? shellVars["XDG_CONFIG_HOME"],
            xdgCacheHome: fromProcess.xdgCacheHome ?? shellVars["XDG_CACHE_HOME"],
            xdgDataHome: fromProcess.xdgDataHome ?? shellVars["XDG_DATA_HOME"]
        )
    }
}

// MARK: - Resolved XDG directory helpers

extension ShellEnvironmentResolver {
    /// Resolved config base: `$XDG_CONFIG_HOME/duplicates-detector/`.
    func configBaseDirectory() async -> URL {
        await xdgDirectory(\.xdgConfigHome, fallback: ".config")
    }

    /// Resolved cache base: `$XDG_CACHE_HOME/duplicates-detector/`.
    func cacheBaseDirectory() async -> URL {
        await xdgDirectory(\.xdgCacheHome, fallback: ".cache")
    }

    /// Resolved data base: `$XDG_DATA_HOME/duplicates-detector/`.
    func dataBaseDirectory() async -> URL {
        await xdgDirectory(\.xdgDataHome, fallback: ".local/share")
    }

    private func xdgDirectory(
        _ keyPath: KeyPath<ResolvedShellEnvironment, String?>,
        fallback: String
    ) async -> URL {
        let env = await resolve()
        let base = env[keyPath: keyPath]
            ?? (NSHomeDirectory() as NSString).appendingPathComponent(fallback)
        return URL(fileURLWithPath: base).appendingPathComponent("duplicates-detector")
    }
}

// MARK: - String helper

private extension String {
    var nonEmpty: String? {
        isEmpty ? nil : self
    }
}
