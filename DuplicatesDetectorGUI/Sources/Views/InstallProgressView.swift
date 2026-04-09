import AppKit
import SwiftUI

/// Shows streaming installation progress during dependency setup.
struct InstallProgressView: View {
    let model: InstallProgressModel
    var onCancel: () -> Void
    var onDone: () -> Void
    var onRetryFailed: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(spacing: DDSpacing.lg) {
            header
            stepList
            logArea
            actionButtons
        }
        .padding(DDDensity.regular)
        .frame(maxWidth: 640)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DDColors.surface0)
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: DDSpacing.sm) {
            Image(systemName: headerIcon)
                .font(DDTypography.headerIcon)
                .foregroundStyle(headerColor)
                .symbolEffect(.pulse, isActive: model.overallStatus == .installing && !reduceMotion)

            Text(headerTitle)
                .font(DDTypography.heading)

            statusSummary
        }
    }

    private var headerIcon: String {
        switch model.overallStatus {
        case .idle, .installing: "arrow.down.circle"
        case .completed: "checkmark.circle"
        case .partialFailure: "exclamationmark.triangle"
        case .allFailed: "xmark.circle"
        case .cancelled: "stop.circle"
        }
    }

    private var headerColor: Color {
        switch model.overallStatus {
        case .idle, .installing: DDColors.accent
        case .completed: DDColors.success
        case .partialFailure: DDColors.warning
        case .allFailed: DDColors.destructive
        case .cancelled: ddColors.textSecondary
        }
    }

    private var headerTitle: String {
        switch model.overallStatus {
        case .idle, .installing: "Installing Dependencies"
        case .completed: "Installation Complete"
        case .partialFailure: "Partially Installed"
        case .allFailed: "Installation Failed"
        case .cancelled: "Installation Cancelled"
        }
    }

    @ViewBuilder
    private var statusSummary: some View {
        switch model.overallStatus {
        case .idle, .installing:
            if let active = model.activeStep {
                Text("Installing \(active.displayName)\u{2026}")
                    .font(DDTypography.body)
                    .foregroundStyle(ddColors.textSecondary)
            }
        case .completed:
            Text("All dependencies installed successfully.")
                .font(DDTypography.body)
                .foregroundStyle(DDColors.success)
        case .partialFailure:
            Text("\(model.failedSteps.count) step(s) failed. You can retry or continue.")
                .font(DDTypography.body)
                .foregroundStyle(DDColors.warning)
        case .allFailed:
            Text("Installation failed. Check the log for details.")
                .font(DDTypography.body)
                .foregroundStyle(DDColors.destructive)
        case .cancelled:
            Text("Installation was cancelled.")
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
        }
    }

    // MARK: - Step List

    private var stepList: some View {
        VStack(alignment: .leading, spacing: DDSpacing.xs) {
            ForEach(model.steps) { step in
                stepRow(step)
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private func stepRow(_ step: InstallProgressModel.Step) -> some View {
        HStack(spacing: DDSpacing.sm) {
            stepStatusIcon(step.status)
                .frame(width: DDSpacing.iconFrame, height: DDSpacing.iconFrame)

            Text(step.displayName)
                .font(DDTypography.body)
                .foregroundStyle(stepTextColor(step.status))

            Spacer()

            stepStatusLabel(step.status)
        }
        .padding(.vertical, DDSpacing.xxs)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(step.displayName), \(stepAccessibilityStatus(step.status))")
    }

    private func stepAccessibilityStatus(_ status: InstallProgressModel.StepStatus) -> String {
        switch status {
        case .pending: "pending"
        case .running: "installing"
        case .succeeded: "done"
        case .failed(let message): message ?? "failed"
        }
    }

    @ViewBuilder
    private func stepStatusIcon(_ status: InstallProgressModel.StepStatus) -> some View {
        switch status {
        case .pending:
            Image(systemName: "circle")
                .foregroundStyle(ddColors.textMuted)
        case .running:
            ProgressView()
                .controlSize(.small)
        case .succeeded:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(DDColors.success)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(DDColors.destructive)
        }
    }

    private func stepTextColor(_ status: InstallProgressModel.StepStatus) -> Color {
        switch status {
        case .pending: ddColors.textMuted
        case .running: DDColors.accent
        case .succeeded: ddColors.textSecondary
        case .failed: DDColors.destructive
        }
    }

    @ViewBuilder
    private func stepStatusLabel(_ status: InstallProgressModel.StepStatus) -> some View {
        switch status {
        case .pending:
            Text("Pending")
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
        case .running:
            Text("Installing")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.accent)
        case .succeeded:
            Text("Done")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.success)
        case .failed(let message):
            Text(message ?? "Failed")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.destructive)
                .lineLimit(1)
        }
    }

    // MARK: - Log Area

    private var logArea: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: DDSpacing.hairline) {
                    ForEach(model.logLines) { line in
                        Text(line.text)
                            .font(DDTypography.metadata)
                            .foregroundStyle(ddColors.textMuted)
                            .id(line.id)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(DDDensity.regular)
            }
            .frame(maxHeight: 180)
            .ddGlassCard()
            .onChange(of: model.logLines.count) {
                if let last = model.logLines.last {
                    withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    // MARK: - Action Buttons

    @ViewBuilder
    private var actionButtons: some View {
        HStack(spacing: DDSpacing.md) {
            switch model.overallStatus {
            case .idle:
                EmptyView()
            case .installing:
                Button("Cancel", role: .destructive, action: onCancel)
                    .buttonStyle(.glass)
            case .completed:
                Button("Continue \u{2192}", action: onDone)
                    .buttonStyle(.glassProminent)
            case .partialFailure:
                Button("Retry Failed", action: onRetryFailed)
                    .buttonStyle(.glass)
                Button("Continue Anyway \u{2192}", action: onDone)
                    .buttonStyle(.glassProminent)
            case .allFailed, .cancelled:
                Button("Retry", action: onRetryFailed)
                    .buttonStyle(.glass)
                Button("Back", action: onDone)
                    .buttonStyle(.glass)
            }
        }
    }
}

/// Shown when Homebrew is needed but not installed.
struct HomebrewMissingView: View {
    @Environment(\.ddColors) private var ddColors
    var onCopy: () -> Void
    var onBack: () -> Void

    private static let brewInstallCommand =
        "/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""

    var body: some View {
        VStack(spacing: DDSpacing.lg) {
            Image(systemName: "exclamationmark.triangle")
                .font(DDTypography.headerIcon)
                .foregroundStyle(DDColors.warning)

            Text("Homebrew Required")
                .font(DDTypography.heading)

            Text("System tools (FFmpeg, Chromaprint) require Homebrew.\nInstall it first, then retry.")
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
                .multilineTextAlignment(.center)

            Text(Self.brewInstallCommand)
                .font(DDTypography.metadata)
                .textSelection(.enabled)
                .padding(DDDensity.regular)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(DDColors.surface2, in: .rect(cornerRadius: DDRadius.medium))

            HStack(spacing: DDSpacing.md) {
                Button("Copy Command") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(Self.brewInstallCommand, forType: .string)
                    onCopy()
                }
                .buttonStyle(.glass)

                Button("Back", action: onBack)
                    .buttonStyle(.glass)
            }
        }
        .padding(DDDensity.regular)
        .frame(maxWidth: 640)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DDColors.surface0)
    }
}

#if DEBUG
#Preview("Installing") {
    InstallProgressView(
        model: {
            let model = InstallProgressModel(steps: [
                (name: "ffmpeg", displayName: "FFmpeg (Homebrew)"),
                (name: "chromaprint", displayName: "Chromaprint / fpcalc (Homebrew)"),
                (name: "mutagen", displayName: "mutagen (pip)"),
            ])
            model.handleEvent(.stepStart(stepIndex: 0, command: "FFmpeg"))
            model.handleEvent(.stepEnd(stepIndex: 0, success: true, message: nil))
            model.handleEvent(.stepStart(stepIndex: 1, command: "Chromaprint"))
            model.handleEvent(.output(stepIndex: 1, line: "==> Fetching chromaprint"))
            return model
        }(),
        onCancel: {},
        onDone: {},
        onRetryFailed: {}
    )
    .frame(width: 700, height: 600)
}

#Preview("Completed") {
    InstallProgressView(
        model: {
            let model = InstallProgressModel(steps: [
                (name: "ffmpeg", displayName: "FFmpeg (Homebrew)"),
                (name: "chromaprint", displayName: "Chromaprint / fpcalc (Homebrew)"),
            ])
            model.handleEvent(.stepStart(stepIndex: 0, command: "FFmpeg"))
            model.handleEvent(.stepEnd(stepIndex: 0, success: true, message: nil))
            model.handleEvent(.stepStart(stepIndex: 1, command: "Chromaprint"))
            model.handleEvent(.stepEnd(stepIndex: 1, success: true, message: nil))
            return model
        }(),
        onCancel: {},
        onDone: {},
        onRetryFailed: {}
    )
    .frame(width: 700, height: 600)
}

#Preview("Homebrew Missing") {
    HomebrewMissingView(onCopy: {}, onBack: {})
        .frame(width: 700, height: 600)
}
#endif
