import SwiftUI

/// Editor for per-comparator weight values using sliders with colored tints.
///
/// Renders as Form sections (placed inside a parent Form).
/// Each weight has a colored slider and numeric display.
struct WeightsEditorView: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors

    private var setup: SetupState { store.setupState }

    var body: some View {
        if setup.mode == .auto {
            Section {
                ContentUnavailableView {
                    Label("Not Available", systemImage: "dial.low")
                } description: {
                    Text("Weights are not configurable in auto mode.")
                }
            }
        } else {
            Section("Comparator Weights") {
                ForEach(setup.visibleWeightKeys, id: \.self) { key in
                    weightRow(key)
                }
            }

            Section {
                LabeledContent("Total") {
                    HStack(spacing: DDSpacing.sm) {
                        Text(formattedSum)
                            .font(DDTypography.sliderReadout)
                            .fontWeight(.semibold)
                            .foregroundStyle(setup.isWeightSumValid ? ddColors.textPrimary : DDColors.destructive)
                        if !setup.isWeightSumValid {
                            Text("must equal 100")
                                .font(DDTypography.label)
                                .foregroundStyle(DDColors.destructive)
                        }
                    }
                }

                Button("Reset to Defaults") {
                    store.sendSetup(.reloadDefaults)
                }
            }
        }
    }

    // MARK: - Weight Row

    private func weightRow(_ key: String) -> some View {
        let isLocked = setup.lockedWeights.contains(key)
        let displayName = DDComparators.displayName(for: key)
        return LabeledContent {
            HStack(spacing: DDSpacing.sm) {
                ColoredSlider(
                    value: rebalancingBinding(for: key),
                    color: comparatorColor(key)
                )
                Text("\(Int(Double(setup.weightStrings[key] ?? "") ?? 0))")
                    .font(DDTypography.sliderReadout)
                    .frame(width: DDSpacing.numericReadoutWidth, alignment: .trailing)
            }
        } label: {
            HStack(spacing: DDSpacing.sm) {
                Button {
                    store.sendSetup(.toggleLockedWeight(key))
                } label: {
                    Image(systemName: isLocked ? "lock.fill" : "lock.open")
                        .font(DDIcon.smallFont)
                        .foregroundStyle(isLocked ? DDColors.accent : ddColors.textMuted)
                }
                .buttonStyle(.plain)
                .help(isLocked ? "Unlock weight" : "Lock weight")

                Circle()
                    .fill(comparatorColor(key))
                    .frame(width: DDSpacing.sm, height: DDSpacing.sm)
                Text(displayName)
            }
        }
        .accessibilityHint("Adjusts the weight of \(displayName) in similarity scoring")
    }

    // MARK: - Bindings

    private func rebalancingBinding(for key: String) -> Binding<Double> {
        Binding(
            get: { Double(setup.weightStrings[key] ?? "") ?? 0 },
            set: { newValue in
                let oldValue = Double(setup.weightStrings[key] ?? "") ?? 0
                let rounded = newValue.rounded()

                let unlockedPeers = setup.visibleWeightKeys.filter { k in
                    k != key && !setup.lockedWeights.contains(k)
                }

                // Parse weight strings via Double to handle fractional values from profiles (e.g. "33.3").
                // Int("33.3") returns nil; Double("33.3") returns 33.3.
                let intWeight: (String) -> Int = { k in
                    Int((Double(setup.weightStrings[k] ?? "") ?? 0).rounded())
                }

                // Compute locked total once — used for clamping in both paths.
                let lockedTotal = setup.visibleWeightKeys
                    .filter { $0 != key && setup.lockedWeights.contains($0) }
                    .reduce(0) { $0 + intWeight($1) }

                guard !unlockedPeers.isEmpty else {
                    // All peers locked: dragged slider gets whatever is left.
                    let onlyOption = max(0, 100 - lockedTotal)
                    store.sendSetup(.setWeightString(key: key, value: String(onlyOption)))
                    return
                }

                // Clamp the dragged value so it can't exceed what locked + peers can accommodate.
                let maxAllowed = Double(100 - lockedTotal)
                let clamped = min(maxAllowed, max(0, rounded))

                store.sendSetup(.setWeightString(key: key, value: String(Int(clamped))))

                let peerValues = unlockedPeers.map { Double(setup.weightStrings[$0] ?? "") ?? 0 }
                let peerTotal = peerValues.reduce(0, +)
                let actualDelta = clamped - oldValue

                for peer in unlockedPeers {
                    let peerVal = Double(setup.weightStrings[peer] ?? "") ?? 0
                    let proportion = peerTotal > 0 ? peerVal / peerTotal : 1.0 / Double(unlockedPeers.count)
                    let adjustment = -actualDelta * proportion
                    let adjusted = min(100, max(0, peerVal + adjustment))
                    store.sendSetup(.setWeightString(key: peer, value: String(Int(adjusted.rounded()))))
                }

                // Fix rounding remainder: adjust the largest unlocked peer so total == 100
                // Re-read the state after the individual setWeightString dispatches above.
                let updatedState = store.setupState
                let intWeightUpdated: (String) -> Int = { k in
                    Int((Double(updatedState.weightStrings[k] ?? "") ?? 0).rounded())
                }
                let currentSum = updatedState.visibleWeightKeys.reduce(0) { $0 + intWeightUpdated($1) }
                let remainder = 100 - currentSum
                if remainder != 0, let largest = unlockedPeers.max(by: {
                    intWeightUpdated($0) < intWeightUpdated($1)
                }) {
                    let val = intWeightUpdated(largest)
                    let corrected = max(0, min(100, val + remainder))
                    store.sendSetup(.setWeightString(key: largest, value: String(corrected)))
                }
            }
        )
    }

    // MARK: - Formatting

    private var formattedSum: String {
        guard setup.weightSum.isFinite else { return "0" }
        let rounded = setup.weightSum.rounded()
        if let intVal = Int(exactly: rounded) {
            return "\(intVal)"
        }
        return String(format: "%.1f", setup.weightSum)
    }

    private func comparatorColor(_ key: String) -> Color {
        DDColors.comparatorColor(for: key)
    }
}

#if DEBUG
#Preview("Video Weights") {
    Form {
        WeightsEditorView(store: PreviewFixtures.sessionStore())
    }
    .frame(width: 400, height: 400)
}

#Preview("Image Weights") {
    Form {
        WeightsEditorView(store: PreviewFixtures.imageWeightsSessionStore())
    }
    .frame(width: 400, height: 400)
}
#endif

// MARK: - Custom Colored Slider

/// A slider with a colored fill track that looks clean on macOS.
private struct ColoredSlider: View {
    @Binding var value: Double
    let color: Color
    @Environment(\.ddColors) private var ddColors
    @FocusState private var isFocused: Bool

    private let range: ClosedRange<Double> = 0...100
    private let trackHeight: CGFloat = DDSpacing.xs

    var body: some View {
        GeometryReader { geo in
            let fraction = (value - range.lowerBound) / (range.upperBound - range.lowerBound)
            let fillWidth = fraction * geo.size.width

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(DDColors.surface2)
                    .frame(height: trackHeight)

                Capsule()
                    .fill(color)
                    .frame(width: max(fillWidth, 0), height: trackHeight)

                Circle()
                    .fill(ddColors.textPrimary)
                    .shadow(color: DDShadow.control.color, radius: DDShadow.control.radius, y: DDShadow.control.y)
                    .frame(width: DDSpacing.sliderThumb, height: DDSpacing.sliderThumb)
                    .offset(x: max(fillWidth - DDSpacing.sliderThumb / 2, 0))
            }
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { drag in
                        let fraction = max(0, min(1, drag.location.x / geo.size.width))
                        let raw = range.lowerBound + fraction * (range.upperBound - range.lowerBound)
                        value = (raw).rounded()
                    }
            )
        }
        .frame(height: DDSpacing.sliderThumb + DDSpacing.xs)
        .focusable()
        .focused($isFocused)
        .ddFocusRing(isFocused)
        .onKeyPress(.rightArrow) { value = min(100, value + 5); return .handled }
        .onKeyPress(.leftArrow) { value = max(0, value - 5); return .handled }
        .onKeyPress(.upArrow) { value = min(100, value + 5); return .handled }
        .onKeyPress(.downArrow) { value = max(0, value - 5); return .handled }
        .accessibilityElement()
        .accessibilityLabel("Weight slider")
        .accessibilityValue("\(Int(value)) percent")
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: value = min(100, value + 5)
            case .decrement: value = max(0, value - 5)
            @unknown default: break
            }
        }
    }
}
