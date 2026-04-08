import Foundation
import Observation

/// Events emitted during dependency installation.
enum InstallEvent: Sendable {
    /// An install step is about to begin.
    case stepStart(stepIndex: Int, command: String)
    /// A line of output (stdout or stderr) from the current step.
    case output(stepIndex: Int, line: String)
    /// An install step completed.
    case stepEnd(stepIndex: Int, success: Bool, message: String?)
}

/// Tracks the state of dependency installation for the UI.
@Observable @MainActor
final class InstallProgressModel {
    enum StepStatus: Equatable {
        case pending
        case running
        case succeeded
        case failed(String?)
    }

    struct Step: Identifiable, Equatable {
        let id: Int
        let name: String
        let displayName: String
        var status: StepStatus = .pending
    }

    struct LogLine: Identifiable {
        let id = UUID()
        let stepIndex: Int
        let text: String
    }

    enum OverallStatus: Equatable {
        case idle
        case installing
        case completed
        case partialFailure
        case allFailed
        case cancelled
    }

    private(set) var steps: [Step] = []
    private(set) var logLines: [LogLine] = []
    private(set) var overallStatus: OverallStatus = .idle

    /// Whether a Homebrew installation is needed but Homebrew is not found.
    var homebrewMissing = false

    init(steps: [(name: String, displayName: String)]) {
        self.steps = steps.enumerated().map { idx, s in
            Step(id: idx, name: s.name, displayName: s.displayName)
        }
    }

    func handleEvent(_ event: InstallEvent) {
        switch event {
        case .stepStart(let idx, _):
            if idx < steps.count { steps[idx].status = .running }
            overallStatus = .installing

        case .output(let idx, let line):
            logLines.append(LogLine(stepIndex: idx, text: line))

        case .stepEnd(let idx, let success, let message):
            if idx < steps.count {
                steps[idx].status = success ? .succeeded : .failed(message)
            }
            updateOverallStatus()
        }
    }

    func markCancelled() {
        overallStatus = .cancelled
    }

    var activeStep: Step? {
        steps.first { $0.status == .running }
    }

    var failedSteps: [Step] {
        steps.filter { if case .failed = $0.status { return true }; return false }
    }

    // MARK: - Private

    private func updateOverallStatus() {
        let allDone = steps.allSatisfy {
            if case .pending = $0.status { return false }
            if case .running = $0.status { return false }
            return true
        }
        guard allDone else { return }
        let failCount = failedSteps.count
        if failCount == 0 {
            overallStatus = .completed
        } else if failCount == steps.count {
            overallStatus = .allFailed
        } else {
            overallStatus = .partialFailure
        }
    }
}
