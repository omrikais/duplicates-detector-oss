import SwiftUI

/// Detection settings tab: threshold, content hashing, audio fingerprinting,
/// and content hashing sub-options.
struct DetectionTab: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var setup: SetupState { store.setupState }
    private var isPhotosSource: Bool { setup.scanSource != .directory }

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.lg) {
            VStack(alignment: .leading, spacing: DDSpacing.sm) {
                LabeledContent("Threshold") {
                    HStack(spacing: DDSpacing.sm) {
                        Slider(
                            value: Binding(
                                get: { Double(setup.threshold) },
                                set: { store.sendSetup(.setThreshold(Int($0.rounded()))) }
                            ),
                            in: 0...100
                        )
                        Text("\(setup.threshold)")
                            .font(DDTypography.monospaced)
                            .foregroundStyle(ddColors.textPrimary)
                            .frame(width: DDSpacing.numericReadoutWidth, alignment: .trailing)
                    }
                }
                HelpText(text: "Minimum similarity score to flag as duplicate")

                Divider()

                Toggle("Content hashing", isOn: store.setupBinding(\.content, action: { .setContent($0) }))
                    .toggleStyle(.switch)
                    .disabled(setup.mode == .audio || isPhotosSource)
                HelpText(text: isPhotosSource
                    ? "Not available for Photos Library scans"
                    : setup.mode == .document
                        ? "Compare document text using SimHash or TF-IDF fingerprints"
                        : "Extract visual fingerprints to catch re-encoded duplicates")

                Divider()

                Toggle("Audio fingerprinting", isOn: store.setupBinding(\.audio, action: { .setAudio($0) }))
                    .toggleStyle(.switch)
                    .disabled(setup.mode == .image || setup.mode == .document || isPhotosSource)
                HelpText(text: isPhotosSource
                    ? "Not available for Photos Library scans"
                    : "Compare audio tracks using acoustic signatures")
            }

            if setup.content {
                settingsSection("Content Hashing Options") {
                    if setup.mode == .document {
                        Picker("Method", selection: store.setupBinding(\.contentMethod, action: { .setContentMethod($0) })) {
                            Text("SimHash").tag(ContentMethod.simhash)
                            Text("TF-IDF").tag(ContentMethod.tfidf)
                        }
                    } else {
                        Picker("Method", selection: store.setupBinding(\.contentMethod, action: { .setContentMethod($0) })) {
                            Text("pHash").tag(ContentMethod.phash)
                            Text("SSIM").tag(ContentMethod.ssim)
                            Text("CLIP").tag(ContentMethod.clip)
                        }

                        Toggle("Rotation invariant", isOn: store.setupBinding(\.rotationInvariant, action: { .setBool(.rotationInvariant, $0) }))
                            .toggleStyle(.switch)
                        HelpText(text: "Check all 8 orientations for rotation-invariant matching")
                    }
                }
                .transition(reduceMotion ? .opacity : .opacity.combined(with: .move(edge: .top)))
                .animation(reduceMotion ? .none : DDMotion.snappy, value: setup.content)
            }
        }
        .padding(DDDensity.regular)
    }
}
