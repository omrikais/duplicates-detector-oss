import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("InstallProgressModel")
@MainActor
struct InstallProgressModelTests {
    // MARK: - Helpers

    /// Create a model with a given number of steps.
    private func makeModel(stepCount: Int = 3) -> InstallProgressModel {
        let steps = (0..<stepCount).map { i in
            (name: "step-\(i)", displayName: "Step \(i)")
        }
        return InstallProgressModel(steps: steps)
    }

    /// Drive a step through start + successful end.
    private func succeedStep(_ model: InstallProgressModel, index: Int) {
        model.handleEvent(.stepStart(stepIndex: index, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: index, success: true, message: nil))
    }

    /// Drive a step through start + failed end.
    private func failStep(_ model: InstallProgressModel, index: Int, message: String? = "error") {
        model.handleEvent(.stepStart(stepIndex: index, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: index, success: false, message: message))
    }

    // MARK: - Initial State

    @Test("Initial overall status is idle")
    func initialOverallStatus() {
        let model = makeModel()
        #expect(model.overallStatus == .idle)
    }

    @Test("Initial steps are all pending")
    func initialStepsAllPending() {
        let model = makeModel(stepCount: 3)
        for step in model.steps {
            #expect(step.status == .pending)
        }
    }

    @Test("Initial logLines is empty")
    func initialLogLinesEmpty() {
        let model = makeModel()
        #expect(model.logLines.isEmpty)
    }

    @Test("Initial activeStep is nil")
    func initialActiveStepNil() {
        let model = makeModel()
        #expect(model.activeStep == nil)
    }

    @Test("Initial failedSteps is empty")
    func initialFailedStepsEmpty() {
        let model = makeModel()
        #expect(model.failedSteps.isEmpty)
    }

    @Test("Steps have correct IDs and names from init")
    func stepsHaveCorrectMetadata() {
        let model = InstallProgressModel(steps: [
            (name: "cli", displayName: "CLI Install"),
            (name: "ffmpeg", displayName: "FFmpeg"),
        ])
        #expect(model.steps.count == 2)
        #expect(model.steps[0].id == 0)
        #expect(model.steps[0].name == "cli")
        #expect(model.steps[0].displayName == "CLI Install")
        #expect(model.steps[1].id == 1)
        #expect(model.steps[1].name == "ffmpeg")
        #expect(model.steps[1].displayName == "FFmpeg")
    }

    // MARK: - stepStart Transitions

    @Test("stepStart transitions step to running and overall to installing")
    func stepStartTransition() {
        let model = makeModel()
        model.handleEvent(.stepStart(stepIndex: 0, command: "pip install test"))

        #expect(model.steps[0].status == .running)
        #expect(model.overallStatus == .installing)
    }

    @Test("stepStart on second step while first still running updates correctly")
    func stepStartSecondStep() {
        let model = makeModel()
        model.handleEvent(.stepStart(stepIndex: 0, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: 0, success: true, message: nil))
        model.handleEvent(.stepStart(stepIndex: 1, command: "test"))

        #expect(model.steps[0].status == .succeeded)
        #expect(model.steps[1].status == .running)
        #expect(model.overallStatus == .installing)
    }

    @Test("stepStart with out-of-bounds index does not crash")
    func stepStartOutOfBounds() {
        let model = makeModel(stepCount: 1)
        // Should not crash — guarded by idx < steps.count
        model.handleEvent(.stepStart(stepIndex: 5, command: "test"))
        #expect(model.overallStatus == .installing)
    }

    // MARK: - stepEnd Success

    @Test("stepEnd with success transitions step to succeeded")
    func stepEndSuccess() {
        let model = makeModel(stepCount: 1)
        model.handleEvent(.stepStart(stepIndex: 0, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: 0, success: true, message: nil))

        #expect(model.steps[0].status == .succeeded)
    }

    // MARK: - stepEnd Failure

    @Test("stepEnd with failure transitions step to failed with message")
    func stepEndFailure() {
        let model = makeModel(stepCount: 1)
        model.handleEvent(.stepStart(stepIndex: 0, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: 0, success: false, message: "Exited with non-zero status"))

        #expect(model.steps[0].status == .failed("Exited with non-zero status"))
    }

    @Test("stepEnd with failure and nil message stores nil in failed")
    func stepEndFailureNilMessage() {
        let model = makeModel(stepCount: 1)
        model.handleEvent(.stepStart(stepIndex: 0, command: "test"))
        model.handleEvent(.stepEnd(stepIndex: 0, success: false, message: nil))

        #expect(model.steps[0].status == .failed(nil))
    }

    // MARK: - Overall Status: completed

    @Test("All steps succeeded transitions to completed")
    func allSucceededCompleted() {
        let model = makeModel(stepCount: 3)
        for i in 0..<3 {
            succeedStep(model, index: i)
        }

        #expect(model.overallStatus == .completed)
    }

    @Test("Single step succeeded transitions to completed")
    func singleStepSucceeded() {
        let model = makeModel(stepCount: 1)
        succeedStep(model, index: 0)

        #expect(model.overallStatus == .completed)
    }

    // MARK: - Overall Status: partialFailure

    @Test("Mix of success and failure transitions to partialFailure")
    func mixedPartialFailure() {
        let model = makeModel(stepCount: 3)
        succeedStep(model, index: 0)
        failStep(model, index: 1)
        succeedStep(model, index: 2)

        #expect(model.overallStatus == .partialFailure)
    }

    @Test("One failure among many successes is partialFailure")
    func oneFailurePartialFailure() {
        let model = makeModel(stepCount: 3)
        succeedStep(model, index: 0)
        succeedStep(model, index: 1)
        failStep(model, index: 2)

        #expect(model.overallStatus == .partialFailure)
    }

    // MARK: - Overall Status: allFailed

    @Test("All steps failed transitions to allFailed")
    func allStepsFailed() {
        let model = makeModel(stepCount: 3)
        for i in 0..<3 {
            failStep(model, index: i)
        }

        #expect(model.overallStatus == .allFailed)
    }

    @Test("Single step failed transitions to allFailed")
    func singleStepFailed() {
        let model = makeModel(stepCount: 1)
        failStep(model, index: 0)

        #expect(model.overallStatus == .allFailed)
    }

    // MARK: - Overall Status: stays installing while steps pending

    @Test("Overall status stays installing while steps are still pending")
    func staysInstallingWhilePending() {
        let model = makeModel(stepCount: 3)
        succeedStep(model, index: 0)
        // Steps 1 and 2 are still pending
        #expect(model.overallStatus == .installing)
    }

    @Test("Overall status stays installing while a step is running")
    func staysInstallingWhileRunning() {
        let model = makeModel(stepCount: 2)
        succeedStep(model, index: 0)
        model.handleEvent(.stepStart(stepIndex: 1, command: "test"))
        // Step 1 is running
        #expect(model.overallStatus == .installing)
    }

    // MARK: - markCancelled

    @Test("markCancelled transitions to cancelled")
    func markCancelled() {
        let model = makeModel()
        model.handleEvent(.stepStart(stepIndex: 0, command: "test"))
        model.markCancelled()

        #expect(model.overallStatus == .cancelled)
    }

    @Test("markCancelled from idle transitions to cancelled")
    func markCancelledFromIdle() {
        let model = makeModel()
        model.markCancelled()

        #expect(model.overallStatus == .cancelled)
    }

    // MARK: - activeStep

    @Test("activeStep returns the currently running step")
    func activeStepRunning() {
        let model = makeModel(stepCount: 3)
        succeedStep(model, index: 0)
        model.handleEvent(.stepStart(stepIndex: 1, command: "test"))

        #expect(model.activeStep?.id == 1)
        #expect(model.activeStep?.name == "step-1")
    }

    @Test("activeStep returns nil after all steps complete")
    func activeStepNilAfterCompletion() {
        let model = makeModel(stepCount: 1)
        succeedStep(model, index: 0)

        #expect(model.activeStep == nil)
    }

    // MARK: - failedSteps

    @Test("failedSteps returns only steps with failed status")
    func failedStepsReturnsOnlyFailed() {
        let model = makeModel(stepCount: 3)
        succeedStep(model, index: 0)
        failStep(model, index: 1, message: "error 1")
        failStep(model, index: 2, message: "error 2")

        #expect(model.failedSteps.count == 2)
        #expect(model.failedSteps[0].id == 1)
        #expect(model.failedSteps[1].id == 2)
    }

    @Test("failedSteps returns empty when all steps succeed")
    func failedStepsEmptyOnSuccess() {
        let model = makeModel(stepCount: 2)
        succeedStep(model, index: 0)
        succeedStep(model, index: 1)

        #expect(model.failedSteps.isEmpty)
    }

    // MARK: - Output Events / logLines

    @Test("output event appends to logLines")
    func outputAppendsToLogLines() {
        let model = makeModel()
        model.handleEvent(.output(stepIndex: 0, line: "Downloading package..."))

        #expect(model.logLines.count == 1)
        #expect(model.logLines[0].stepIndex == 0)
        #expect(model.logLines[0].text == "Downloading package...")
    }

    @Test("Multiple output events accumulate in logLines")
    func multipleOutputsAccumulate() {
        let model = makeModel()
        model.handleEvent(.output(stepIndex: 0, line: "Line 1"))
        model.handleEvent(.output(stepIndex: 0, line: "Line 2"))
        model.handleEvent(.output(stepIndex: 1, line: "Line 3"))

        #expect(model.logLines.count == 3)
        #expect(model.logLines[0].text == "Line 1")
        #expect(model.logLines[1].text == "Line 2")
        #expect(model.logLines[2].text == "Line 3")
        #expect(model.logLines[2].stepIndex == 1)
    }

    @Test("Each logLine has a unique ID")
    func logLinesHaveUniqueIDs() {
        let model = makeModel()
        model.handleEvent(.output(stepIndex: 0, line: "A"))
        model.handleEvent(.output(stepIndex: 0, line: "B"))

        #expect(model.logLines[0].id != model.logLines[1].id)
    }

    // MARK: - homebrewMissing Property

    @Test("homebrewMissing defaults to false")
    func homebrewMissingDefault() {
        let model = makeModel()
        #expect(!model.homebrewMissing)
    }

    @Test("homebrewMissing can be set to true")
    func homebrewMissingSettable() {
        let model = makeModel()
        model.homebrewMissing = true
        #expect(model.homebrewMissing)
    }

    // MARK: - Full Workflow Scenario

    @Test("Full three-step workflow with mixed results reaches partialFailure")
    func fullWorkflowScenario() {
        let model = InstallProgressModel(steps: [
            (name: "cli", displayName: "CLI Install"),
            (name: "ffmpeg", displayName: "FFmpeg"),
            (name: "mutagen", displayName: "mutagen (pip)"),
        ])

        // Verify initial state
        #expect(model.overallStatus == .idle)

        // Step 0: start + output + succeed
        model.handleEvent(.stepStart(stepIndex: 0, command: "pip3 install duplicates-detector"))
        #expect(model.overallStatus == .installing)
        #expect(model.activeStep?.name == "cli")
        model.handleEvent(.output(stepIndex: 0, line: "Collecting duplicates-detector"))
        model.handleEvent(.output(stepIndex: 0, line: "Installing collected packages"))
        model.handleEvent(.stepEnd(stepIndex: 0, success: true, message: nil))

        // Step 1: start + fail
        model.handleEvent(.stepStart(stepIndex: 1, command: "brew install ffmpeg"))
        #expect(model.activeStep?.name == "ffmpeg")
        model.handleEvent(.output(stepIndex: 1, line: "Error: ffmpeg: no bottle available"))
        model.handleEvent(.stepEnd(stepIndex: 1, success: false, message: "Exited with non-zero status"))

        // Step 2: start + succeed
        model.handleEvent(.stepStart(stepIndex: 2, command: "python3 -m pip install mutagen"))
        model.handleEvent(.stepEnd(stepIndex: 2, success: true, message: nil))

        // Final state
        #expect(model.overallStatus == .partialFailure)
        #expect(model.failedSteps.count == 1)
        #expect(model.failedSteps[0].name == "ffmpeg")
        #expect(model.logLines.count == 3)
        #expect(model.activeStep == nil)
    }
}
