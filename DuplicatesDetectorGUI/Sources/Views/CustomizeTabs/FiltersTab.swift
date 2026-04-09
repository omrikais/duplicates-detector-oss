import SwiftUI

/// Filters configuration tab: file size, duration, resolution, bitrate, codec.
struct FiltersTab: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors

    private var setup: SetupState { store.setupState }

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.lg) {
            VStack(alignment: .leading, spacing: DDSpacing.sm) {
                filterPair(label: "File Size",
                           minBinding: store.setupBinding(\.minSize, action: { .setFilter(.minSize, $0) }),
                           maxBinding: store.setupBinding(\.maxSize, action: { .setFilter(.maxSize, $0) }),
                           minPlaceholder: "e.g. 10MB", maxPlaceholder: "e.g. 1GB")

                if setup.mode != .image && setup.mode != .document {
                    filterPair(label: "Duration",
                               minBinding: store.setupBinding(\.minDuration, action: { .setFilter(.minDuration, $0) }),
                               maxBinding: store.setupBinding(\.maxDuration, action: { .setFilter(.maxDuration, $0) }),
                               minPlaceholder: "seconds", maxPlaceholder: "seconds")
                }

                if setup.mode != .audio && setup.mode != .document {
                    filterPair(label: "Resolution",
                               minBinding: store.setupBinding(\.minResolution, action: { .setFilter(.minResolution, $0) }),
                               maxBinding: store.setupBinding(\.maxResolution, action: { .setFilter(.maxResolution, $0) }),
                               minPlaceholder: "e.g. 1280x720", maxPlaceholder: "e.g. 3840x2160")
                }

                if setup.mode != .document {
                    filterPair(label: "Bitrate",
                               minBinding: store.setupBinding(\.minBitrate, action: { .setFilter(.minBitrate, $0) }),
                               maxBinding: store.setupBinding(\.maxBitrate, action: { .setFilter(.maxBitrate, $0) }),
                               minPlaceholder: "e.g. 1Mbps", maxPlaceholder: "e.g. 50Mbps")

                    LabeledContent("Codec") {
                        TextField("e.g. h264", text: store.setupBinding(\.codec, action: { .setFilter(.codec, $0) }))
                            .styledField()
                    }
                }
            }
        }
        .padding(DDDensity.regular)
    }

    private func filterPair(label: String, minBinding: Binding<String>, maxBinding: Binding<String>,
                            minPlaceholder: String, maxPlaceholder: String) -> some View {
        LabeledContent(label) {
            HStack(spacing: DDSpacing.sm) {
                TextField("Min", text: minBinding, prompt: Text(minPlaceholder))
                    .styledField()
                Text("\u{2013}")
                    .foregroundStyle(ddColors.textMuted)
                TextField("Max", text: maxBinding, prompt: Text(maxPlaceholder))
                    .styledField()
            }
        }
    }
}
