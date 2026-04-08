import SwiftUI

/// An ignored pair with a stable identity for SwiftUI List rendering.
private struct IdentifiedPair: Identifiable {
    let id: String
    let paths: [String]

    init(_ paths: [String]) {
        self.paths = paths
        self.id = paths.joined(separator: "\t")
    }
}

/// Sheet that displays and manages ignored pairs from the CLI ignore list.
struct IgnoreListView: View {
    let ignoreFilePath: URL?
    /// Called when a pair is removed or all pairs are cleared, passing the removed paths.
    var onPairRemoved: ((_ fileA: String, _ fileB: String) -> Void)?
    /// Called when all pairs are cleared.
    var onAllCleared: (() -> Void)?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.ddColors) private var ddColors
    @State private var pairs: [[String]] = []
    @State private var searchText = ""
    @State private var showClearConfirmation = false
    @State private var errorMessage: String?
    @State private var identifiedFilteredPairs: [IdentifiedPair] = []

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()

            if pairs.isEmpty {
                ContentUnavailableView(
                    "No Ignored Pairs",
                    systemImage: "eye.slash",
                    description: Text("Pairs you choose to ignore will appear here")
                )
            } else {
                VStack(spacing: 0) {
                    HStack {
                        Image(systemName: "magnifyingglass")
                            .foregroundStyle(ddColors.textMuted)
                        TextField("Filter by path\u{2026}", text: $searchText)
                            .textFieldStyle(.plain)
                    }
                    .padding(.horizontal, DDSpacing.md)
                    .padding(.vertical, DDSpacing.sm)

                    Divider()

                    List {
                        ForEach(identifiedFilteredPairs) { item in
                            IgnoredPairRow(pair: item.paths)
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    Button("Remove", role: .destructive) {
                                        removePair(item.paths)
                                    }
                                    .accessibilityHint("Removes this pair from the ignore list")
                                }
                        }
                    }
                    .listStyle(.inset)
                }
            }
        }
        .frame(minWidth: 550, idealWidth: 700, minHeight: 400, idealHeight: 500)
        .onAppear { loadPairs() }
        .onChange(of: searchText) { _, _ in recomputeFilteredPairs() }
        .onChange(of: pairs) { _, _ in recomputeFilteredPairs() }
        .confirmationDialog("Clear All Ignored Pairs?", isPresented: $showClearConfirmation, titleVisibility: .visible) {
            Button("Clear All", role: .destructive) { clearAll() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will remove all \(pairs.count) ignored pairs. Future scans will include these pairs again.")
        }
        .alert("Error", isPresented: Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private var header: some View {
        SheetHeader(title: "Ignored Pairs", count: pairs.count) {
            Text((ignoreFilePath ?? IgnoreListManager.defaultPath).path)
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: 200)
                .help((ignoreFilePath ?? IgnoreListManager.defaultPath).path)

            Button {
                loadPairs()
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .controlSize(.small)

            Button(role: .destructive) {
                showClearConfirmation = true
            } label: {
                Label("Clear All", systemImage: "trash")
            }
            .controlSize(.small)
            .disabled(pairs.isEmpty)
        } onDismiss: {
            dismiss()
        }
    }

    private func recomputeFilteredPairs() {
        let source: [[String]]
        if searchText.isEmpty {
            source = pairs
        } else {
            let query = searchText.lowercased()
            source = pairs.filter { pair in
                pair.contains { $0.lowercased().contains(query) }
            }
        }
        identifiedFilteredPairs = source.map { IdentifiedPair($0) }
    }

    private func loadPairs() {
        Task {
            pairs = await IgnoreListManager.shared.load(from: ignoreFilePath)
        }
    }

    private func removePair(_ pair: [String]) {
        guard pair.count == 2 else { return }
        Task {
            do {
                try await IgnoreListManager.shared.removePair(pair[0], pair[1], from: ignoreFilePath)
                onPairRemoved?(pair[0], pair[1])
                pairs = await IgnoreListManager.shared.load(from: ignoreFilePath)
            } catch {
                errorMessage = "Failed to remove pair: \(error.localizedDescription)"
            }
        }
    }

    private func clearAll() {
        Task {
            do {
                try await IgnoreListManager.shared.clearAll(at: ignoreFilePath)
                onAllCleared?()
                pairs = []
            } catch {
                errorMessage = "Failed to clear ignore list: \(error.localizedDescription)"
            }
        }
    }
}

/// A single row showing an ignored pair.
private struct IgnoredPairRow: View {
    let pair: [String]
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.xxs) {
            pathLabel(pair.first ?? "")
            pathLabel(pair.count > 1 ? pair[1] : "")
        }
        .padding(.vertical, DDSpacing.xxs)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Ignored pair: \(pair.first ?? "") and \(pair.count > 1 ? pair[1] : "")")
    }

    private func pathLabel(_ path: String) -> some View {
        Text(path)
            .font(DDTypography.monospaced)
            .foregroundStyle(ddColors.textSecondary)
            .lineLimit(1)
            .truncationMode(.middle)
            .help(path)
            .textSelection(.enabled)
    }
}

#if DEBUG
#Preview("Ignore List View — Empty") {
    IgnoreListView(ignoreFilePath: URL(fileURLWithPath: "/tmp/nonexistent-ignore-list.json"))
}
#endif
