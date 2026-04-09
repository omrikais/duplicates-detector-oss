import SwiftUI
import UniformTypeIdentifiers

/// Section that manages scan directories with add/remove, reference toggles, and drag-and-drop.
/// Also provides a segmented control to switch between directory and Photos Library sources.
struct DirectoryPickerSection: View {
    let store: SessionStore
    @Environment(AppState.self) private var appState
    @Environment(\.ddColors) private var ddColors
    @State private var showFileImporter = false
    @State private var isDropTargeted = false

    private var setup: SetupState { store.setupState }

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            sourceSegmentedControl

            if setup.scanSource == .directory {
                directoryContent
            } else {
                photosLibraryContent
            }
        }
    }

    // MARK: - Source Selection

    private var sourceSegmentedControl: some View {
        Picker("Source", selection: Binding(
            get: { setup.scanSource == .directory ? "directory" : "photos" },
            set: { store.sendSetup(.setScanSource($0 == "directory" ? .directory : .photosLibrary(scope: .fullLibrary))) }
        )) {
            Text("Directories").tag("directory")
            Text("Photos Library").tag("photos")
        }
        .pickerStyle(.segmented)
        .accessibilityLabel("Scan source")
    }

    // MARK: - Directory Mode

    private var directoryContent: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            VStack(spacing: 0) {
                if setup.entries.isEmpty {
                    emptyState
                } else {
                    ForEach(setup.entries) { entry in
                        directoryRow(entry)
                        if entry.id != setup.entries.last?.id {
                            Divider()
                        }
                    }

                    Button {
                        showFileImporter = true
                    } label: {
                        Label("Add Directories\u{2026}", systemImage: "plus.circle")
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DDColors.accent)
                    .font(DDTypography.label)
                    .padding(.vertical, DDSpacing.xs)
                }
            }
            .overlay {
                if isDropTargeted {
                    RoundedRectangle(cornerRadius: DDRadius.small)
                        .strokeBorder(DDColors.accent, style: StrokeStyle(lineWidth: DDSpacing.dropTargetStroke, dash: [6, 3]))
                        .background(DDColors.accent.opacity(0.05), in: RoundedRectangle(cornerRadius: DDRadius.small))
                }
            }
            .dropDestination(for: URL.self) { urls, _ in
                let folders = urls.filter(\.isExistingDirectory)
                guard !folders.isEmpty else { return false }
                for url in folders {
                    store.sendSetup(.addDirectory(url))
                }
                return true
            } isTargeted: { targeted in
                isDropTargeted = targeted
            }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: true
        ) { result in
            if case .success(let urls) = result {
                for url in urls {
                    store.sendSetup(.addDirectory(url))
                    appState.bookmarkManager.saveBookmark(for: url)
                }
            }
        }
    }

    // MARK: - Photos Library Mode

    private var photosLibraryContent: some View {
        ContentUnavailableView {
            Label("Photos Library", systemImage: "photo.on.rectangle.angled")
        } description: {
            Text("Scan for duplicates using Photos metadata")
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Photos Library selected. Scan entire Photos Library for duplicates using Photos metadata.")
    }

    // MARK: - Directory Subviews

    private var emptyState: some View {
        ContentUnavailableView {
            Label("No Directories", systemImage: "folder.badge.questionmark")
        } description: {
            Text("Add or drop directories to scan for duplicates.")
        } actions: {
            Button {
                showFileImporter = true
            } label: {
                Label("Add Directories\u{2026}", systemImage: "plus.circle")
            }
            .buttonStyle(.glass)
        }
        .frame(minHeight: 80)
    }

    private func directoryRow(_ entry: DirectoryEntry) -> some View {
        let url = URL(filePath: entry.path)
        return HStack(spacing: DDSpacing.sm) {
            Image(systemName: entry.isReference ? "folder.fill.badge.gearshape" : "folder.fill")
                .foregroundStyle(entry.isReference ? DDColors.warning : DDColors.accent)
                .frame(width: DDSpacing.iconFrame)

            VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                Text(entry.path)
                    .lineLimit(1)
                    .truncationMode(.middle)

                if entry.isReference {
                    Text("Reference")
                        .font(DDTypography.label)
                        .foregroundStyle(DDColors.warning)
                }
            }

            Spacer()

            Toggle("Reference", isOn: Binding(
                get: { entry.isReference },
                set: { _ in store.sendSetup(.toggleReference(url)) }
            ))
            .toggleStyle(.switch)
            .controlSize(.mini)
            .labelsHidden()
            .help("Mark as reference directory (files here are never deleted)")

            Button(role: .destructive) {
                appState.bookmarkManager.removeBookmark(for: entry.path)
                store.sendSetup(.removeDirectory(url))
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(ddColors.textMuted)
            }
            .buttonStyle(.plain)
            .help("Remove directory")
            .accessibilityLabel("Remove \(url.lastPathComponent)")
            .accessibilityHint("Removes this directory from the scan list")
        }
        .padding(.vertical, DDSpacing.xs)
    }

}

#if DEBUG
#Preview("With Directories") {
    DirectoryPickerSection(store: PreviewFixtures.sessionStore())
        .frame(width: 500)
        .padding()
        .environment(PreviewFixtures.appState())
}

#Preview("Empty") {
    DirectoryPickerSection(store: PreviewFixtures.emptySessionStore())
        .frame(width: 500)
        .padding()
        .environment(PreviewFixtures.appState())
}
#endif
