import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Mock Environment Provider

/// A test double that records shell call count and returns configured values.
private final class MockEnvironmentProvider: EnvironmentProvider, @unchecked Sendable {
    let env: [String: String]
    let shellOutput: Result<String, Error>
    private(set) var shellCallCount = 0

    init(env: [String: String] = [:], shellOutput: Result<String, Error> = .success("")) {
        self.env = env
        self.shellOutput = shellOutput
    }

    var processEnvironment: [String: String] { env }

    func runLoginShell(command: String) async throws -> String {
        shellCallCount += 1
        return try shellOutput.get()
    }
}

private enum MockError: Error {
    case shellFailure
}

// MARK: - Process env resolution

@Suite("ShellEnvironmentResolver process env resolution")
struct SERProcessEnvTests {
    @Test("All three XDG vars resolved from process environment when present")
    func allThreeFromProcessEnv() async {
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/custom/config",
                "XDG_CACHE_HOME": "/custom/cache",
                "XDG_DATA_HOME": "/custom/data",
            ]
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == "/custom/config")
        #expect(result.xdgCacheHome == "/custom/cache")
        #expect(result.xdgDataHome == "/custom/data")
        // Shell should NOT be called when all three are present in process env
        #expect(provider.shellCallCount == 0)
    }

    @Test("Empty XDG values in process env treated as nil")
    func emptyValuesAreTreatedAsNil() async {
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "",
                "XDG_CACHE_HOME": "",
                "XDG_DATA_HOME": "",
            ]
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == nil)
        #expect(result.xdgCacheHome == nil)
        #expect(result.xdgDataHome == nil)
    }
}

// MARK: - Shell probe resolution

@Suite("ShellEnvironmentResolver shell probe resolution")
struct SERShellProbeTests {
    @Test("Shell probe fills all three vars when process env is empty")
    func shellFillsMissingVars() async {
        let shellOutput = """
            Some login banner noise
            __XDG_RESOLVE__XDG_CONFIG_HOME=/shell/config
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=/shell/data
            More noise
            """
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == "/shell/config")
        #expect(result.xdgCacheHome == "/shell/cache")
        #expect(result.xdgDataHome == "/shell/data")
    }

    @Test("Process env takes priority over shell output")
    func processEnvWinsOverShell() async {
        let shellOutput = """
            __XDG_RESOLVE__XDG_CONFIG_HOME=/shell/config
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=/shell/data
            """
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/process/config",
                "XDG_CACHE_HOME": "/process/cache",
                "XDG_DATA_HOME": "/process/data",
            ],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        // Process env should win for all three
        #expect(result.xdgConfigHome == "/process/config")
        #expect(result.xdgCacheHome == "/process/cache")
        #expect(result.xdgDataHome == "/process/data")
    }

    @Test("Partial process env supplemented by shell probe")
    func partialProcessEnvPlusShell() async {
        let shellOutput = """
            __XDG_RESOLVE__XDG_CONFIG_HOME=/shell/config
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=/shell/data
            """
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/process/config"
                // cache and data NOT in process env
            ],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        // Config from process env, cache and data from shell
        #expect(result.xdgConfigHome == "/process/config")
        #expect(result.xdgCacheHome == "/shell/cache")
        #expect(result.xdgDataHome == "/shell/data")
    }

    @Test("Shell probe lines with empty values are ignored")
    func shellEmptyValuesIgnored() async {
        let shellOutput = """
            __XDG_RESOLVE__XDG_CONFIG_HOME=
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=
            """
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == nil)
        #expect(result.xdgCacheHome == "/shell/cache")
        #expect(result.xdgDataHome == nil)
    }

    @Test("Shell probe lines without prefix are ignored")
    func nonPrefixedLinesIgnored() async {
        let shellOutput = """
            XDG_CONFIG_HOME=/not/this/one
            random noise line
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            """
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == nil)
        #expect(result.xdgCacheHome == "/shell/cache")
        #expect(result.xdgDataHome == nil)
    }
}

// MARK: - Error handling

@Suite("ShellEnvironmentResolver error handling")
struct SERErrorHandlingTests {
    @Test("Shell probe failure falls back to process env values only")
    func shellFailureFallsBackSafely() async {
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .failure(MockError.shellFailure)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        // All nil because process env is empty and shell failed
        #expect(result.xdgConfigHome == nil)
        #expect(result.xdgCacheHome == nil)
        #expect(result.xdgDataHome == nil)
    }

    @Test("Shell failure preserves partial process env values")
    func shellFailurePreservesProcessEnv() async {
        let provider = MockEnvironmentProvider(
            env: ["XDG_CONFIG_HOME": "/process/config"],
            shellOutput: .failure(MockError.shellFailure)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let result = await resolver.resolve()

        #expect(result.xdgConfigHome == "/process/config")
        #expect(result.xdgCacheHome == nil)
        #expect(result.xdgDataHome == nil)
    }
}

// MARK: - Caching behavior

@Suite("ShellEnvironmentResolver caching")
struct SERCachingTests {
    @Test("Second resolve returns cached result without re-probing shell")
    func resolveIsCached() async {
        let shellOutput = """
            __XDG_RESOLVE__XDG_CONFIG_HOME=/shell/config
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=/shell/data
            """
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)

        let first = await resolver.resolve()
        let second = await resolver.resolve()

        #expect(first == second)
        #expect(provider.shellCallCount == 1)
    }

    @Test("reset() clears cache so next resolve re-probes shell")
    func resetClearsCache() async {
        let shellOutput = """
            __XDG_RESOLVE__XDG_CONFIG_HOME=/shell/config
            __XDG_RESOLVE__XDG_CACHE_HOME=/shell/cache
            __XDG_RESOLVE__XDG_DATA_HOME=/shell/data
            """
        let provider = MockEnvironmentProvider(
            env: [:],
            shellOutput: .success(shellOutput)
        )
        let resolver = ShellEnvironmentResolver(provider: provider)

        _ = await resolver.resolve()
        #expect(provider.shellCallCount == 1)

        await resolver.reset()
        _ = await resolver.resolve()
        #expect(provider.shellCallCount == 2)
    }
}

// MARK: - Convenience directory helpers

@Suite("ShellEnvironmentResolver directory helpers")
struct SERDirectoryHelperTests {
    @Test("configBaseDirectory uses resolved xdgConfigHome")
    func configBaseFromXDG() async {
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/custom/config",
                "XDG_CACHE_HOME": "/custom/cache",
                "XDG_DATA_HOME": "/custom/data",
            ]
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.configBaseDirectory()

        #expect(url == URL(fileURLWithPath: "/custom/config/duplicates-detector"))
    }

    @Test("cacheBaseDirectory uses resolved xdgCacheHome")
    func cacheBaseFromXDG() async {
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/custom/config",
                "XDG_CACHE_HOME": "/custom/cache",
                "XDG_DATA_HOME": "/custom/data",
            ]
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.cacheBaseDirectory()

        #expect(url == URL(fileURLWithPath: "/custom/cache/duplicates-detector"))
    }

    @Test("dataBaseDirectory uses resolved xdgDataHome")
    func dataBaseFromXDG() async {
        let provider = MockEnvironmentProvider(
            env: [
                "XDG_CONFIG_HOME": "/custom/config",
                "XDG_CACHE_HOME": "/custom/cache",
                "XDG_DATA_HOME": "/custom/data",
            ]
        )
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.dataBaseDirectory()

        #expect(url == URL(fileURLWithPath: "/custom/data/duplicates-detector"))
    }

    @Test("configBaseDirectory falls back to ~/.config when xdgConfigHome is nil")
    func configBaseFallsBackToDefault() async {
        let provider = MockEnvironmentProvider(env: [:])
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.configBaseDirectory()

        let expected = URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent(".config")
            .appendingPathComponent("duplicates-detector")
        #expect(url == expected)
    }

    @Test("cacheBaseDirectory falls back to ~/.cache when xdgCacheHome is nil")
    func cacheBaseFallsBackToDefault() async {
        let provider = MockEnvironmentProvider(env: [:])
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.cacheBaseDirectory()

        let expected = URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent(".cache")
            .appendingPathComponent("duplicates-detector")
        #expect(url == expected)
    }

    @Test("dataBaseDirectory falls back to ~/.local/share when xdgDataHome is nil")
    func dataBaseFallsBackToDefault() async {
        let provider = MockEnvironmentProvider(env: [:])
        let resolver = ShellEnvironmentResolver(provider: provider)
        let url = await resolver.dataBaseDirectory()

        let expected = URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent(".local/share")
            .appendingPathComponent("duplicates-detector")
        #expect(url == expected)
    }
}

// MARK: - ResolvedShellEnvironment Equatable

@Suite("ResolvedShellEnvironment value semantics")
struct ResolvedShellEnvironmentTests {
    @Test("Equatable compares all three fields")
    func equatableComparesAllFields() {
        let a = ResolvedShellEnvironment(xdgConfigHome: "/a", xdgCacheHome: "/b", xdgDataHome: "/c")
        let b = ResolvedShellEnvironment(xdgConfigHome: "/a", xdgCacheHome: "/b", xdgDataHome: "/c")
        let c = ResolvedShellEnvironment(xdgConfigHome: "/a", xdgCacheHome: "/b", xdgDataHome: "/different")

        #expect(a == b)
        #expect(a != c)
    }

    @Test("All-nil environment is a valid state")
    func allNilIsValid() {
        let env = ResolvedShellEnvironment(xdgConfigHome: nil, xdgCacheHome: nil, xdgDataHome: nil)
        #expect(env.xdgConfigHome == nil)
        #expect(env.xdgCacheHome == nil)
        #expect(env.xdgDataHome == nil)
    }
}
