import Foundation
import Subprocess
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Build a `ToolStatus` with sensible defaults.
private func makeTool(
    name: String,
    isAvailable: Bool = true,
    path: String? = nil,
    version: String? = nil,
    isRequired: Bool = true
) -> ToolStatus {
    ToolStatus(
        name: name,
        isAvailable: isAvailable,
        path: path,
        version: version,
        isRequired: isRequired
    )
}

/// Build a `DependencyStatus` where everything is present by default.
private func makeStatus(
    cliAvailable: Bool = true,
    ffmpegAvailable: Bool = true,
    ffprobeAvailable: Bool = true,
    fpcalcAvailable: Bool = true,
    hasMutagen: Bool = true,
    hasSkimage: Bool = true,
    hasPdfminer: Bool = true
) -> DependencyStatus {
    DependencyStatus(
        cli: makeTool(name: "duplicates-detector", isAvailable: cliAvailable),
        ffmpeg: makeTool(name: "ffmpeg", isAvailable: ffmpegAvailable),
        ffprobe: makeTool(name: "ffprobe", isAvailable: ffprobeAvailable),
        fpcalc: makeTool(name: "fpcalc", isAvailable: fpcalcAvailable, isRequired: false),
        hasMutagen: hasMutagen,
        hasSkimage: hasSkimage,
        hasPdfminer: hasPdfminer
    )
}

@Suite("DependencyInstaller.buildPlan")
struct DependencyInstallerTests {
    // The installer is an actor, but buildPlan() is nonisolated — no await needed
    // for the method call itself. We create the installer once for the suite.
    private let installer = DependencyInstaller(shellEnvironment: .inherit)

    // MARK: - Happy Path

    @Test("All dependencies present produces empty plan")
    func allDependenciesPresent() {
        let status = makeStatus()
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: "/opt/homebrew/bin/brew")

        #expect(plan.steps.isEmpty)
        #expect(!plan.requiresHomebrew)
        #expect(!plan.homebrewMissing)
    }

    // MARK: - CLI Missing

    @Test("CLI missing produces pip install step")
    func cliMissing() {
        let status = makeStatus(cliAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: nil, brewPath: "/opt/homebrew/bin/brew")

        let cliSteps = plan.steps.filter { $0.name == "duplicates-detector" }
        #expect(cliSteps.count == 1)

        let step = cliSteps[0]
        #expect(step.arguments.contains("install"))
        #expect(step.arguments.contains("duplicates-detector[audio,ssim,trash,document]"))
    }

    @Test("CLI missing step does not include pip package steps since extras cover them")
    func cliMissingSkipsPipPackages() {
        // When CLI is missing, step 1 installs with all extras, so no separate
        // mutagen/scikit-image steps should appear even if hasMutagen/hasSkimage are false.
        let status = makeStatus(cliAvailable: false, hasMutagen: false, hasSkimage: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: "/opt/homebrew/bin/brew")

        let pipSteps = plan.steps.filter { $0.name == "mutagen" || $0.name == "scikit-image" }
        #expect(pipSteps.isEmpty)
    }

    // MARK: - ffmpeg Missing

    @Test("ffmpeg missing produces brew install step when brew is available")
    func ffmpegMissingWithBrew() {
        let status = makeStatus(ffmpegAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: "/opt/homebrew/bin/brew")

        let ffmpegSteps = plan.steps.filter { $0.name == "ffmpeg" }
        #expect(ffmpegSteps.count == 1)
        #expect(ffmpegSteps[0].executable == "/opt/homebrew/bin/brew")
        #expect(ffmpegSteps[0].arguments == ["install", "ffmpeg"])
        #expect(plan.requiresHomebrew)
        #expect(!plan.homebrewMissing)
    }

    @Test("ffprobe missing also triggers ffmpeg install step")
    func ffprobeMissingTriggersFFmpegStep() {
        let status = makeStatus(ffprobeAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: "/opt/homebrew/bin/brew")

        let ffmpegSteps = plan.steps.filter { $0.name == "ffmpeg" }
        #expect(ffmpegSteps.count == 1)
    }

    @Test("ffmpeg missing without brew produces no step but sets requiresHomebrew")
    func ffmpegMissingWithoutBrew() {
        let status = makeStatus(ffmpegAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: nil)

        // No step because brew is nil, but the flag indicates brew is needed
        let ffmpegSteps = plan.steps.filter { $0.name == "ffmpeg" }
        #expect(ffmpegSteps.isEmpty)
        #expect(plan.requiresHomebrew)
        #expect(plan.homebrewMissing)
    }

    // MARK: - fpcalc Missing

    @Test("fpcalc missing produces brew install chromaprint step")
    func fpcalcMissing() {
        let status = makeStatus(fpcalcAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: "/opt/homebrew/bin/brew")

        let chromaprintSteps = plan.steps.filter { $0.name == "chromaprint" }
        #expect(chromaprintSteps.count == 1)
        #expect(chromaprintSteps[0].executable == "/opt/homebrew/bin/brew")
        #expect(chromaprintSteps[0].arguments == ["install", "chromaprint"])
        #expect(plan.requiresHomebrew)
    }

    @Test("fpcalc missing without brew produces no step but flags homebrewMissing")
    func fpcalcMissingWithoutBrew() {
        let status = makeStatus(fpcalcAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: nil, brewPath: nil)

        let chromaprintSteps = plan.steps.filter { $0.name == "chromaprint" }
        #expect(chromaprintSteps.isEmpty)
        #expect(plan.requiresHomebrew)
        #expect(plan.homebrewMissing)
    }

    // MARK: - Homebrew Missing

    @Test("Homebrew missing when both ffmpeg and fpcalc are missing")
    func homebrewMissingMultipleDeps() {
        let status = makeStatus(ffmpegAvailable: false, fpcalcAvailable: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: nil)

        #expect(plan.requiresHomebrew)
        #expect(plan.homebrewMissing)
        // No brew steps generated since brewPath is nil
        let brewSteps = plan.steps.filter { $0.name == "ffmpeg" || $0.name == "chromaprint" }
        #expect(brewSteps.isEmpty)
    }

    @Test("Homebrew not required when all brew dependencies present")
    func homebrewNotRequired() {
        let status = makeStatus(hasMutagen: false)
        let plan = installer.buildPlan(for: status, cliPython: "/usr/bin/python3", brewPath: nil)

        #expect(!plan.requiresHomebrew)
        #expect(!plan.homebrewMissing)
    }

    // MARK: - pipx Detection

    @Test("pipx detected from .local/share/pipx/ path uses pipx inject")
    func pipxDetectedSharePath() {
        let status = makeStatus(hasMutagen: false)
        let pythonPath = "/Users/test/.local/share/pipx/venvs/duplicates-detector/bin/python3"
        let plan = installer.buildPlan(for: status, cliPython: pythonPath, brewPath: nil)

        let mutagenSteps = plan.steps.filter { $0.name == "mutagen" }
        #expect(mutagenSteps.count == 1)
        #expect(mutagenSteps[0].displayName.contains("pipx inject"))
        #expect(mutagenSteps[0].arguments.contains("inject"))
        #expect(mutagenSteps[0].arguments.contains("duplicates-detector"))
        #expect(mutagenSteps[0].arguments.contains("mutagen"))
    }

    @Test("pipx detected from .local/pipx/ path uses pipx inject")
    func pipxDetectedLocalPath() {
        let status = makeStatus(hasSkimage: false)
        let pythonPath = "/Users/test/.local/pipx/venvs/duplicates-detector/bin/python3"
        let plan = installer.buildPlan(for: status, cliPython: pythonPath, brewPath: nil)

        let skimageSteps = plan.steps.filter { $0.name == "scikit-image" }
        #expect(skimageSteps.count == 1)
        #expect(skimageSteps[0].displayName.contains("pipx inject"))
        #expect(skimageSteps[0].arguments.contains("inject"))
    }

    @Test("Non-pipx Python path uses pip install for missing packages")
    func nonPipxUsesPip() {
        let status = makeStatus(hasMutagen: false, hasSkimage: false)
        let pythonPath = "/usr/local/bin/python3"
        let plan = installer.buildPlan(for: status, cliPython: pythonPath, brewPath: nil)

        let mutagenSteps = plan.steps.filter { $0.name == "mutagen" }
        #expect(mutagenSteps.count == 1)
        #expect(mutagenSteps[0].executable == pythonPath)
        #expect(mutagenSteps[0].arguments == ["-m", "pip", "install", "mutagen"])
        #expect(mutagenSteps[0].displayName.contains("pip"))
        #expect(!mutagenSteps[0].displayName.contains("pipx"))

        let skimageSteps = plan.steps.filter { $0.name == "scikit-image" }
        #expect(skimageSteps.count == 1)
        #expect(skimageSteps[0].executable == pythonPath)
        #expect(skimageSteps[0].arguments == ["-m", "pip", "install", "scikit-image"])
    }

    // MARK: - Step Ordering

    @Test("Step order: CLI first, then ffmpeg, then chromaprint, then Python packages")
    func stepOrdering() {
        // Everything missing except CLI is available (so pip packages are generated)
        let status = makeStatus(
            ffmpegAvailable: false,
            ffprobeAvailable: false,
            fpcalcAvailable: false,
            hasMutagen: false,
            hasSkimage: false
        )
        let plan = installer.buildPlan(
            for: status,
            cliPython: "/usr/bin/python3",
            brewPath: "/opt/homebrew/bin/brew"
        )

        let names = plan.steps.map(\.name)
        // CLI is present so no CLI step. Order should be: ffmpeg, chromaprint, mutagen, scikit-image
        #expect(names == ["ffmpeg", "chromaprint", "mutagen", "scikit-image"])
    }

    @Test("CLI step comes before brew and pip steps when CLI is also missing")
    func cliStepComesFirst() {
        let status = makeStatus(
            cliAvailable: false,
            ffmpegAvailable: false,
            fpcalcAvailable: false
        )
        let plan = installer.buildPlan(
            for: status,
            cliPython: nil,
            brewPath: "/opt/homebrew/bin/brew"
        )

        let names = plan.steps.map(\.name)
        #expect(names.first == "duplicates-detector")
        // When CLI is missing, no pip package steps are generated (extras cover them)
        #expect(!names.contains("mutagen"))
        #expect(!names.contains("scikit-image"))
    }

    // MARK: - Python Packages Without cliPython

    @Test("Missing pip packages are skipped when cliPython is nil")
    func missingPipPackagesSkippedWithoutPython() {
        let status = makeStatus(hasMutagen: false, hasSkimage: false)
        let plan = installer.buildPlan(for: status, cliPython: nil, brewPath: nil)

        // No pip steps because we don't know which Python to use
        let pipSteps = plan.steps.filter { $0.name == "mutagen" || $0.name == "scikit-image" }
        #expect(pipSteps.isEmpty)
    }

    // MARK: - Combined Scenarios

    @Test("Only missing dependencies produce steps, present ones are skipped")
    func onlyMissingDepsProduceSteps() {
        // Only fpcalc and mutagen missing
        let status = makeStatus(fpcalcAvailable: false, hasMutagen: false)
        let plan = installer.buildPlan(
            for: status,
            cliPython: "/usr/bin/python3",
            brewPath: "/opt/homebrew/bin/brew"
        )

        let names = plan.steps.map(\.name)
        #expect(names == ["chromaprint", "mutagen"])
    }

    // MARK: - Bundled CLI

    @Test("Bundled CLI produces empty plan even when system tools are missing")
    func bundledCLIProducesEmptyPlan() {
        let status = makeStatus(
            ffmpegAvailable: false,
            ffprobeAvailable: false,
            fpcalcAvailable: false,
            hasMutagen: false,
            hasSkimage: false
        )
        let plan = installer.buildPlan(for: status, cliPython: nil, brewPath: nil, isBundled: true)

        #expect(plan.steps.isEmpty)
        #expect(!plan.requiresHomebrew)
        #expect(!plan.homebrewMissing)
    }

    @Test("All missing with brew produces full plan")
    func allMissingWithBrew() {
        let status = makeStatus(
            cliAvailable: false,
            ffmpegAvailable: false,
            ffprobeAvailable: false,
            fpcalcAvailable: false,
            hasMutagen: false,
            hasSkimage: false
        )
        let plan = installer.buildPlan(
            for: status,
            cliPython: nil,
            brewPath: "/opt/homebrew/bin/brew"
        )

        let names = plan.steps.map(\.name)
        // CLI missing => pip install step, no separate pip packages
        // ffmpeg missing => brew install ffmpeg
        // fpcalc missing => brew install chromaprint
        #expect(names == ["duplicates-detector", "ffmpeg", "chromaprint"])
        #expect(plan.requiresHomebrew)
        #expect(!plan.homebrewMissing)
    }
}
