import SwiftUI

/// Sheet that displays action log entries in reverse-chronological order.
struct ActionLogView: View {
    let logPath: String
    @Environment(\.dismiss) private var dismiss
    @State private var entries: [ActionLogEntry] = []
    @State private var showClearConfirmation = false
    @State private var clearError: String?

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()

            if entries.isEmpty {
                ContentUnavailableView(
                    "No Actions Logged",
                    systemImage: "doc.text",
                    description: Text("File operations will appear here when actions are performed")
                )
            } else {
                List(entries.reversed()) { entry in
                    ActionLogRow(entry: entry)
                }
                .listStyle(.inset)
            }
        }
        .frame(minWidth: 550, idealWidth: 650, minHeight: 400, idealHeight: 500)
        .onAppear { loadEntries() }
        .confirmationDialog("Clear Action Log?", isPresented: $showClearConfirmation, titleVisibility: .visible) {
            Button("Clear Log", role: .destructive) { clearLog() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will remove all entries from the log file. This cannot be undone.")
        }
        .alert("Clear Failed", isPresented: Binding(
            get: { clearError != nil },
            set: { if !$0 { clearError = nil } }
        )) {
            Button("OK") { clearError = nil }
        } message: {
            Text(clearError ?? "")
        }
    }

    private var header: some View {
        SheetHeader(title: "Action Log", count: entries.count) {
            Button {
                loadEntries()
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .controlSize(.small)

            Button(role: .destructive) {
                showClearConfirmation = true
            } label: {
                Label("Clear", systemImage: "trash")
            }
            .controlSize(.small)
            .disabled(entries.isEmpty)
        } onDismiss: {
            dismiss()
        }
    }

    private func loadEntries() {
        entries = ActionLogEntry.parseLogFile(at: logPath)
    }

    private func clearLog() {
        do {
            try "".write(toFile: logPath, atomically: true, encoding: .utf8)
            entries = []
        } catch {
            clearError = "Failed to clear log: \(error.localizedDescription)"
        }
    }
}

/// A single row in the action log viewer.
private struct ActionLogRow: View {
    let entry: ActionLogEntry
    @Environment(\.ddColors) private var ddColors
    @State private var isExpanded = false

    /// Build the accessibility label for a log entry row. Exposed for unit testing.
    nonisolated static func entryAccessibilityText(action: String, filename: String, timestamp: String) -> String {
        "\(action) on \(filename) at \(timestamp)"
    }

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            detailView
        } label: {
            summaryView
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Self.entryAccessibilityText(
            action: entry.action, filename: entry.fileName, timestamp: entry.timestamp
        ))
    }

    private var summaryView: some View {
        HStack(spacing: DDSpacing.sm) {
            Image(systemName: entry.actionIcon)
                .foregroundStyle(actionColor)
                .frame(width: DDSpacing.iconFrame)

            Text(entry.fileName)
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textPrimary)
                .lineLimit(1)
                .truncationMode(.middle)

            Spacer()

            if let bytes = entry.bytesFreed, bytes > 0 {
                Text(DDFormatters.formatFileSize(bytes))
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }

            Text(formatTimestamp(entry.timestamp))
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
    }

    private var detailView: some View {
        Grid(alignment: .leading, horizontalSpacing: DDSpacing.md, verticalSpacing: DDSpacing.xs) {
            detailRow("Action", entry.action)
            detailRow("Path", entry.path)
            if let dest = entry.destination {
                detailRow("Destination", dest)
            }
            if let score = entry.score {
                detailRow("Score", String(format: "%.1f", score))
            }
            if let strategy = entry.strategy {
                detailRow("Strategy", strategy)
            }
            if let kept = entry.kept {
                detailRow("Kept", kept)
            }
            if let source = entry.source {
                detailRow("Source", source)
            }
        }
        .padding(.leading, DDSpacing.lg)
        .padding(.vertical, DDSpacing.xs)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label)
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
                .frame(width: DDSpacing.labelColumnWidth, alignment: .leading)
            Text(value)
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
                .lineLimit(2)
                .truncationMode(.middle)
                .textSelection(.enabled)
        }
    }

    private var actionColor: Color {
        entry.fileAction?.color ?? ddColors.textMuted
    }

    private func formatTimestamp(_ ts: String) -> String {
        // Show just date and time, trimming the ISO 8601 timezone suffix
        let trimmed = ts.replacingOccurrences(of: "Z", with: "")
            .replacingOccurrences(of: "T", with: " ")
        if let dotIndex = trimmed.lastIndex(of: ".") {
            return String(trimmed[trimmed.startIndex..<dotIndex])
        }
        return trimmed
    }
}

#if DEBUG
#Preview("Action Log View") {
    ActionLogView(logPath: "/tmp/test-action-log.jsonl")
}
#endif
