import SwiftUI

/// Sheet that displays past scan results for replay.
struct ScanHistoryView: View {
    let store: SessionStore
    @Environment(\.dismiss) private var dismiss
    @State private var entries: [SessionRegistry.Entry] = []
    @State private var showClearConfirmation = false
    @State private var isLoading = true

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()

            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if entries.isEmpty {
                ContentUnavailableView(
                    "No Scan History",
                    systemImage: "clock",
                    description: Text("Completed scans will be saved here automatically")
                )
            } else {
                List {
                    ForEach(entries) { entry in
                        Button {
                            dismiss()
                            store.send(.restoreSession(entry.id))
                        } label: {
                            HistoryRow(entry: entry)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(entry.createdAt.formatted(date: .abbreviated, time: .shortened)), \(entry.directories.joined(separator: ", ")), \(entry.pairCount) pairs, \(entry.mode.rawValue) mode")
                        .accessibilityHint("Double tap to replay this scan")
                    }
                    .onDelete { offsets in
                        deleteEntries(at: offsets)
                    }
                }
                .listStyle(.inset)
            }
        }
        .frame(minWidth: 500, idealWidth: 600, minHeight: 350, idealHeight: 450)
        .task {
            do {
                try await store.registry.pruneOldSessions(keep: 50)
                entries = try await store.registry.listEntries()
            } catch {
                entries = []
            }
            isLoading = false
        }
        .confirmationDialog("Clear All Scan History?", isPresented: $showClearConfirmation, titleVisibility: .visible) {
            Button("Clear All", role: .destructive) {
                Task { await clearAll() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will delete all \(entries.count) saved scan sessions. This cannot be undone.")
        }
    }

    private var header: some View {
        SheetHeader(title: "Scan History", count: entries.count) {
            Button(role: .destructive) {
                showClearConfirmation = true
            } label: {
                Label("Clear All", systemImage: "trash")
            }
            .controlSize(.small)
            .disabled(entries.isEmpty)
        } onDismiss: {
            dismiss()
        }
    }

    private func deleteEntries(at offsets: IndexSet) {
        let toDelete = offsets.map { entries[$0] }
        let registry = store.registry
        Task {
            for entry in toDelete {
                try? await registry.deleteSession(entry.id)
            }
            do {
                entries = try await registry.listEntries()
            } catch {
                entries = []
            }
        }
    }

    private func clearAll() async {
        let registry = store.registry
        for entry in entries {
            try? await registry.deleteSession(entry.id)
        }
        entries = []
    }
}

/// A single row in the scan history list.
private struct HistoryRow: View {
    let entry: SessionRegistry.Entry
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        HStack(spacing: DDSpacing.md) {
            Image(systemName: entry.mode.systemImageName)
                .foregroundStyle(DDColors.accent)
                .frame(width: DDSpacing.iconFrame)

            VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                Text(entry.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(DDTypography.body)
                    .foregroundStyle(ddColors.textPrimary)

                Text(directorySummary)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(entry.directories.joined(separator: "\n"))
            }

            Spacer()

            VStack(alignment: .trailing, spacing: DDSpacing.xxs) {
                Text("\(entry.pairCount) pairs")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textPrimary)

                if !entry.sourceLabel.isEmpty {
                    Text(entry.sourceLabel)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
        }
        .padding(.vertical, DDSpacing.xxs)
    }

    private var directorySummary: String {
        if entry.directories.isEmpty { return "No directories" }
        if entry.directories.count == 1 { return entry.directories[0] }
        return "\(entry.directories[0]) +\(entry.directories.count - 1) more"
    }
}

#if DEBUG
#Preview("Scan History View") {
    ScanHistoryView(store: PreviewFixtures.sessionStore())
}
#endif
