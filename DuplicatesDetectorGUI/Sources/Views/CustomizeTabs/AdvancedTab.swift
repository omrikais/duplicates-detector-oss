import AppKit
import SwiftUI

/// Advanced configuration tab: processing, exclude patterns, cache, logging, debug.
struct AdvancedTab: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors

    private var setup: SetupState { store.setupState }

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.lg) {
            settingsSection("Processing") {
                LabeledContent("Workers") {
                    HStack(spacing: DDSpacing.sm) {
                        Slider(
                            value: Binding(
                                get: { Double(setup.workers) },
                                set: { store.sendSetup(.setWorkers(Int($0.rounded()))) }
                            ),
                            in: 0...16
                        )
                        Text(setup.workers == 0 ? "auto" : "\(setup.workers)")
                            .font(DDTypography.monospaced)
                            .foregroundStyle(ddColors.textPrimary)
                            .frame(width: DDSpacing.numericReadoutWidth, alignment: .trailing)
                    }
                }

                LabeledContent("File Extensions") {
                    TextField("e.g. mp4,mkv,avi", text: store.setupBinding(\.extensions, action: { .setExtensions($0) }))
                        .styledField()
                }

                Toggle("Non-recursive scan", isOn: store.setupBinding(\.noRecursive, action: { .setBool(.noRecursive, $0) }))
                    .toggleStyle(.switch)
            }

            settingsSection("Exclude Patterns") {
                ForEach(Array(setup.exclude.enumerated()), id: \.offset) { idx, pattern in
                    HStack {
                        Text(pattern)
                            .font(DDTypography.metadata)
                            .foregroundStyle(ddColors.textSecondary)
                        Spacer()
                        Button(role: .destructive) {
                            store.sendSetup(.removeExclude(idx))
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(ddColors.textMuted)
                        }
                        .buttonStyle(.plain)
                    }
                }

                HStack(spacing: DDSpacing.sm) {
                    TextField("e.g. *.tmp", text: store.setupBinding(\.excludeInput, action: { .setExcludeInput($0) }))
                        .styledField()
                        .onSubmit { addExclude() }
                    Button("Add") { addExclude() }
                        .disabled(setup.excludeInput.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            settingsSection("Cache") {
                Toggle("Use metadata cache", isOn: Binding(
                    get: { !setup.noMetadataCache },
                    set: { store.sendSetup(.setBool(.noMetadataCache, !$0)) }
                ))
                .toggleStyle(.switch)
                Toggle("Use content cache", isOn: Binding(
                    get: { !setup.noContentCache },
                    set: { store.sendSetup(.setBool(.noContentCache, !$0)) }
                ))
                .toggleStyle(.switch)
                Toggle("Use audio cache", isOn: Binding(
                    get: { !setup.noAudioCache },
                    set: { store.sendSetup(.setBool(.noAudioCache, !$0)) }
                ))
                .toggleStyle(.switch)

                LabeledContent("Cache Directory") {
                    HStack {
                        TextField("default", text: store.setupBinding(\.cacheDir, action: { .setCacheDir($0) }))
                            .styledField()
                        Button("Browse\u{2026}") {
                            let panel = NSOpenPanel()
                            panel.canChooseDirectories = true
                            panel.canChooseFiles = false
                            panel.allowsMultipleSelection = false
                            if panel.runModal() == .OK, let url = panel.url {
                                store.sendSetup(.setCacheDir(url.path))
                            }
                        }
                    }
                }
            }

            settingsSection("Logging") {
                LabeledContent("Ignore File") {
                    HStack {
                        TextField("path to ignore list", text: store.setupBinding(\.ignoreFile, action: { .setIgnoreFile($0) }))
                            .styledField()
                        Button("Browse\u{2026}") {
                            let panel = NSOpenPanel()
                            panel.canChooseFiles = true
                            panel.canChooseDirectories = false
                            panel.allowsMultipleSelection = false
                            if panel.runModal() == .OK, let url = panel.url {
                                store.sendSetup(.setIgnoreFile(url.path))
                            }
                        }
                    }
                }

                LabeledContent("Action Log") {
                    HStack {
                        TextField("path to log file", text: store.setupBinding(\.log, action: { .setLog($0) }))
                            .styledField()
                        Button("Browse\u{2026}") {
                            let panel = NSOpenPanel()
                            panel.canChooseFiles = true
                            panel.canChooseDirectories = false
                            panel.allowsMultipleSelection = false
                            if panel.runModal() == .OK, let url = panel.url {
                                store.sendSetup(.setLog(url.path))
                            }
                        }
                    }
                }
            }

            settingsSection("Debug") {
                Toggle("Verbose output", isOn: store.setupBinding(\.verbose, action: { .setBool(.verbose, $0) }))
                    .toggleStyle(.switch)
                Toggle("Dry run", isOn: store.setupBinding(\.dryRun, action: { .setBool(.dryRun, $0) }))
                    .toggleStyle(.switch)
                HelpText(text: "Preview results without taking any action")
            }
        }
        .padding(DDDensity.regular)
    }

    private func addExclude() {
        let p = setup.excludeInput.trimmingCharacters(in: .whitespaces)
        guard !p.isEmpty, !setup.exclude.contains(p) else { return }
        store.sendSetup(.addExclude(p))
        store.sendSetup(.setExcludeInput(""))
    }
}
