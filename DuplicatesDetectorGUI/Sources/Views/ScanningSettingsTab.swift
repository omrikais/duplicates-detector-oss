import SwiftUI

/// Scanning preferences: threshold, content hashing, audio, weight presets, filters, output options.
struct ScanningSettingsTab: View {
    @Environment(ObservableDefaults.self) private var defaults
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        @Bindable var defaults = defaults
        Form {
            detectionSection(defaults: defaults)
            contentHashingSection(defaults: defaults)
            audioSection(defaults: defaults)
            weightPresetsSection
            outputSection(defaults: defaults)
            filtersSection(defaults: defaults)
        }
        .formStyle(.grouped)
        .onChange(of: defaults.mode) { _, _ in
            AppDefaults.normalizeStoredDefaults()
            // Re-notify so bound fields reflect the normalization.
            defaults.reload()
        }
    }

    // MARK: - Sections

    @ViewBuilder
    private func detectionSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Detection") {
            LabeledContent("Threshold") {
                HStack {
                    Slider(value: Binding(
                        get: { Double(defaults.threshold) },
                        set: { defaults.threshold = Int($0.rounded()) }
                    ), in: 0...100)
                    Text("\(defaults.threshold)")
                        .font(DDTypography.sliderReadout)
                        .frame(width: 30, alignment: .trailing)
                }
            }

            Stepper("Workers: \(defaults.workers == 0 ? "Auto" : "\(defaults.workers)")", value: $defaults.workers, in: 0...16)
                .accessibilityValue(defaults.workers == 0 ? "Auto" : "\(defaults.workers) workers")
        }
    }

    @ViewBuilder
    private func contentHashingSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Content Hashing") {
            Toggle("Enable content hashing", isOn: $defaults.content)

            if defaults.content {
                Picker("Method", selection: $defaults.contentMethod) {
                    if defaults.mode == .document {
                        Text("SimHash").tag(ContentMethod.simhash)
                        Text("TF-IDF").tag(ContentMethod.tfidf)
                    } else {
                        Text("pHash").tag(ContentMethod.phash)
                        Text("SSIM").tag(ContentMethod.ssim)
                        Text("CLIP").tag(ContentMethod.clip)
                    }
                }

                Toggle("Rotation invariant", isOn: $defaults.rotationInvariant)
            }
        }
    }

    @ViewBuilder
    private func audioSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Audio Fingerprinting") {
            Toggle("Enable audio fingerprinting", isOn: $defaults.audio)
        }
    }

    @ViewBuilder
    private var weightPresetsSection: some View {
        Section {
            let weights = WeightDefaults.defaults(mode: defaults.mode, content: defaults.content, audio: defaults.audio)
            if let weights {
                ForEach(weights.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                    LabeledContent(key) {
                        Text("\(Int(value))")
                            .font(DDTypography.sliderReadout)
                    }
                }
            } else {
                Text("Weight presets are not available for Auto mode.")
                    .foregroundStyle(ddColors.textSecondary)
            }
        } header: {
            Text("Weight Presets")
        } footer: {
            Text("Weights are configured per-scan in the scan setup screen. These are the defaults for the selected mode.")
        }
    }

    @ViewBuilder
    private func outputSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Output") {
            Toggle("Embed thumbnails", isOn: $defaults.embedThumbnails)

            Picker("Sort by", selection: $defaults.sort) {
                ForEach(SortField.allCases, id: \.self) { field in
                    Text(field.rawValue.capitalized).tag(field)
                }
            }

            Toggle("Group duplicates", isOn: $defaults.group)
        }
    }

    @ViewBuilder
    private func filtersSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section {
            HStack {
                TextField("Min size (e.g. 100MB)", text: $defaults.minSize)
                    .textFieldStyle(.roundedBorder)
                TextField("Max size (e.g. 2GB)", text: $defaults.maxSize)
                    .textFieldStyle(.roundedBorder)
            }
            HStack {
                TextField("Min duration (seconds)", text: $defaults.minDuration)
                    .textFieldStyle(.roundedBorder)
                TextField("Max duration (seconds)", text: $defaults.maxDuration)
                    .textFieldStyle(.roundedBorder)
            }
            HStack {
                TextField("Min resolution (e.g. 1280x720)", text: $defaults.minResolution)
                    .textFieldStyle(.roundedBorder)
                TextField("Max resolution (e.g. 1920x1080)", text: $defaults.maxResolution)
                    .textFieldStyle(.roundedBorder)
            }
            HStack {
                TextField("Min bitrate (e.g. 1Mbps)", text: $defaults.minBitrate)
                    .textFieldStyle(.roundedBorder)
                TextField("Max bitrate (e.g. 10Mbps)", text: $defaults.maxBitrate)
                    .textFieldStyle(.roundedBorder)
            }
            TextField("Codec (e.g. h264)", text: $defaults.codec)
                .textFieldStyle(.roundedBorder)
        } header: {
            Text("Default Filters")
        } footer: {
            Text("Filters applied by default to each new scan. Leave empty to skip. Formats: size (100MB, 2GB), duration (seconds), resolution (1280x720, 1920x1080), bitrate (1Mbps, 10Mbps).")
        }
    }
}
