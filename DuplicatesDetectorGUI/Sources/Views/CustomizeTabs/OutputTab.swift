import AppKit
import SwiftUI

/// Output configuration tab: results display options and review actions.
struct OutputTab: View {
    let store: SessionStore

    private var setup: SetupState { store.setupState }
    private var isPhotosSource: Bool { setup.scanSource != .directory }

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.lg) {
            settingsSection("Results Display") {
                Picker("Sort By", selection: store.setupBinding(\.sort, action: { .setSort($0) })) {
                    ForEach(SortField.allCases, id: \.self) { f in
                        Text(f.rawValue.capitalized).tag(f)
                    }
                }

                LabeledContent("Limit") {
                    TextField("no limit", text: store.setupBinding(\.limit, action: { .setLimit($0) }))
                        .styledField()
                }

                LabeledContent("Min Score") {
                    TextField("0\u{2013}100", text: store.setupBinding(\.minScore, action: { .setMinScore($0) }))
                        .styledField()
                }

                Toggle("Group results", isOn: store.setupBinding(\.group, action: { .setGroup($0) }))
                    .toggleStyle(.switch)

                Toggle("Embed thumbnails", isOn: store.setupBinding(\.embedThumbnails, action: { .setBool(.embedThumbnails, $0) }))
                    .toggleStyle(.switch)

                if setup.embedThumbnails {
                    LabeledContent("Thumbnail Size") {
                        TextField("e.g. 160x120", text: store.setupBinding(\.thumbnailSize, action: { .setThumbnailSize($0) }))
                            .styledField()
                    }
                }
            }

            settingsSection("Review Actions") {
                Picker("Keep Strategy", selection: store.setupBinding(\.keep, action: { .setKeep($0) })) {
                    Text("None").tag(Optional<KeepStrategy>.none)
                    ForEach(KeepStrategy.allCases, id: \.self) { strategy in
                        Text(strategy.displayName).tag(Optional(strategy))
                    }
                }

                Picker("Action", selection: store.setupBinding(\.action, action: { .setAction($0) })) {
                    let excluded: Set<ActionType> = isPhotosSource
                        ? [.delete, .hardlink, .symlink, .reflink, .moveTo]
                        : [.delete, .hardlink, .symlink, .reflink]
                    ForEach(ActionType.allCases.filter { !excluded.contains($0) },
                            id: \.self) { action in
                        Text(action.displayName).tag(action)
                    }
                }

                if setup.action == .moveTo {
                    LabeledContent("Move To") {
                        HStack {
                            TextField("Select destination\u{2026}", text: store.setupBinding(\.moveToDir, action: { .setMoveToDir($0) }))
                                .styledField()
                            Button("Browse\u{2026}") {
                                let panel = NSOpenPanel()
                                panel.canChooseDirectories = true
                                panel.canChooseFiles = false
                                panel.allowsMultipleSelection = false
                                if panel.runModal() == .OK, let url = panel.url {
                                    store.sendSetup(.setMoveToDir(url.path))
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(DDDensity.regular)
    }
}
