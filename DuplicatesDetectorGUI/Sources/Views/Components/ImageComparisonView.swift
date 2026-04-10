import AppKit
import SwiftUI

/// Full-resolution image comparison with synchronized zoom/pan and wipe-slider overlay.
struct ImageComparisonView: View {
    let pathA: String
    let pathB: String
    var labelA: String = "File A"
    var labelB: String = "File B"
    @ScaledMetric(relativeTo: .caption2) private var wipeHandleSize: CGFloat = 10
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum ComparisonMode: String, CaseIterable {
        case sideBySide = "Side by Side"
        case wipeSlider = "Wipe"
    }

    @State private var mode: ComparisonMode = .sideBySide
    @State private var scale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var imageA: NSImage?
    @State private var imageB: NSImage?
    @State private var isLoadingA = true
    @State private var isLoadingB = true
    @State private var wipePosition: CGFloat = 0.5
    @State private var surfaceSize: CGSize = .zero

    // Gesture transient state
    @GestureState private var magnifyBy: CGFloat = 1.0
    @GestureState private var dragOffset: CGSize = .zero

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider()
            comparisonSurface
        }
        .task(id: "\(pathA)|\(pathB)") {
            // Reset comparison state for new pair
            imageA = nil
            imageB = nil
            isLoadingA = true
            isLoadingB = true
            scale = 1.0
            offset = .zero
            mode = .sideBySide
            wipePosition = 0.5

            async let a = Self.loadImage(from: pathA)
            async let b = Self.loadImage(from: pathB)
            let (loadedA, loadedB) = await (a, b)
            guard !Task.isCancelled else { return }
            imageA = loadedA
            imageB = loadedB
            isLoadingA = false
            isLoadingB = false
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        HStack(spacing: DDSpacing.sm) {
            Picker("Mode", selection: $mode) {
                ForEach(ComparisonMode.allCases, id: \.self) { m in
                    Text(m.rawValue).tag(m)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 180)

            Spacer()

            zoomControls
        }
        .padding(.horizontal, DDSpacing.md)
        .padding(.vertical, DDSpacing.sm)
        .background(DDColors.surface2)
    }

    private var zoomControls: some View {
        HStack(spacing: DDSpacing.sm) {
            Button("Fit") {
                withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                    scale = 1.0
                    offset = .zero
                }
            }
            .controlSize(.small)

            Button("1:1") {
                withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                    scale = actualSizeScale
                    offset = .zero
                }
            }
            .controlSize(.small)
            .disabled(imageA == nil)

            Button {
                withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                    scale = max(0.1, scale - 0.25)
                }
            } label: {
                Image(systemName: "minus.magnifyingglass")
            }
            .controlSize(.small)

            Button {
                withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                    scale = min(10.0, scale + 0.25)
                }
            } label: {
                Image(systemName: "plus.magnifyingglass")
            }
            .controlSize(.small)

            Text("\(Int(scale * 100))%")
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
                .frame(width: DDSpacing.zoomReadoutWidth, alignment: .trailing)
        }
    }

    // MARK: - Comparison Surface

    @ViewBuilder
    private var comparisonSurface: some View {
        Group {
            switch mode {
            case .sideBySide:
                sideBySideView
            case .wipeSlider:
                wipeSliderView
            }
        }
        .onGeometryChange(for: CGSize.self) { proxy in proxy.size } action: { surfaceSize = $0 }
    }

    // MARK: - Side by Side

    private var sideBySideView: some View {
        HStack(spacing: DDSpacing.hairline) {
            imagePane(imageA, isLoading: isLoadingA, label: labelA, path: pathA)
            Divider()
            imagePane(imageB, isLoading: isLoadingB, label: labelB, path: pathB)
        }
        .contentShape(Rectangle())
        .gesture(magnifyGesture)
        .gesture(panGesture)
    }

    private func imagePane(_ image: NSImage?, isLoading: Bool, label: String, path: String) -> some View {
        imageSurface(image, isLoading: isLoading, label: label, path: path)
            .clipped()
    }

    // MARK: - Wipe Slider

    private var wipeSliderView: some View {
        ZStack {
            imageSurface(imageB, isLoading: isLoadingB, label: labelB, path: pathB,
                         labelAlignment: .trailing)

            imageSurface(imageA, isLoading: isLoadingA, label: labelA, path: pathA)
                .clipShape(
                    HorizontalClip(width: surfaceSize.width * wipePosition)
                )

            wipeHandle(at: surfaceSize.width * wipePosition,
                       height: surfaceSize.height,
                       containerWidth: surfaceSize.width)
        }
        .clipped()
        .contentShape(Rectangle())
        .gesture(magnifyGesture)
    }

    /// Shared image rendering surface used by both side-by-side panes and wipe layers.
    private func imageSurface(
        _ image: NSImage?, isLoading: Bool, label: String, path: String,
        labelAlignment: HorizontalAlignment = .leading
    ) -> some View {
        ZStack {
            DDColors.surface0

            if let image {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .scaleEffect(scale * magnifyBy)
                    .offset(
                        x: offset.width + dragOffset.width,
                        y: offset.height + dragOffset.height
                    )
                    .accessibilityLabel("Image preview for \(label)")
                    .accessibilityAddTraits(.isImage)
            } else if isLoading {
                ProgressView()
                    .controlSize(.small)
            } else {
                ContentUnavailableView(
                    "Image Unavailable",
                    systemImage: "photo",
                    description: Text(path.fileName)
                )
            }

            VStack {
                HStack {
                    if labelAlignment == .leading {
                        DDMediaLabel(text: label)
                        Spacer()
                    } else {
                        Spacer()
                        DDMediaLabel(text: label)
                    }
                }
                Spacer()
            }
            .padding(DDSpacing.sm)
        }
    }

    private func wipeHandle(at x: CGFloat, height: CGFloat, containerWidth: CGFloat) -> some View {
        ZStack {
            // Vertical line
            Rectangle()
                .fill(DDColors.accent)
                .frame(width: 2, height: height)

            // Circular handle
            Circle()
                .fill(DDColors.accent)
                .frame(width: 24, height: 24)
                .shadow(color: .black.opacity(0.3), radius: 2, y: 1)
                .overlay {
                    Image(systemName: "arrow.left.and.right")
                        .font(.system(size: wipeHandleSize, weight: .bold))
                        .foregroundStyle(ddColors.textPrimary)
                }
        }
        .position(x: x, y: height / 2)
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in
                    wipePosition = max(0.02, min(0.98, value.location.x / containerWidth))
                }
        )
        .accessibilityLabel("Comparison slider")
        .accessibilityValue("\(Int(wipePosition * 100)) percent")
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: wipePosition = min(1.0, wipePosition + 0.1)
            case .decrement: wipePosition = max(0.0, wipePosition - 0.1)
            @unknown default: break
            }
        }
    }


    // MARK: - Gestures

    private var magnifyGesture: some Gesture {
        MagnifyGesture()
            .updating($magnifyBy) { value, state, _ in
                state = value.magnification
            }
            .onEnded { value in
                scale = max(0.1, min(10.0, scale * value.magnification))
            }
    }

    private var panGesture: some Gesture {
        DragGesture()
            .updating($dragOffset) { value, state, _ in
                state = value.translation
            }
            .onEnded { value in
                offset = CGSize(
                    width: offset.width + value.translation.width,
                    height: offset.height + value.translation.height
                )
            }
    }

    // MARK: - Helpers

    /// Scale factor that displays imageA at native pixel resolution (1 image pixel = 1 screen point).
    /// At `scale = 1.0` the image is aspect-fitted to the pane; this computes
    /// how much to inflate that so one image pixel = one screen point.
    private var actualSizeScale: CGFloat {
        guard let image = imageA, surfaceSize.width > 0, surfaceSize.height > 0 else { return 1.0 }
        // Use pixel dimensions, not NSImage.size (which is in points and affected by DPI metadata).
        let pixelSize = Self.pixelSize(of: image)
        // In side-by-side each pane is ~half the surface width; in wipe mode it's full width.
        let paneWidth = mode == .sideBySide ? surfaceSize.width / 2 : surfaceSize.width
        let paneHeight = surfaceSize.height
        // SwiftUI's Image(nsImage:) renders using NSImage.size (points), so the fit
        // scale is relative to the point size, but we want 1 pixel = 1 screen point.
        let pointSize = image.size
        let fitScale = min(paneWidth / pointSize.width, paneHeight / pointSize.height)
        guard fitScale > 0 else { return 1.0 }
        // At fitScale the image is (pointSize * fitScale) screen points.
        // We want (pixelSize) screen points, so scale = pixelSize / (pointSize * fitScale).
        return pixelSize.width / (pointSize.width * fitScale)
    }

    private static func pixelSize(of image: NSImage) -> CGSize {
        guard let rep = image.representations.first else { return image.size }
        return CGSize(width: rep.pixelsWide, height: rep.pixelsHigh)
    }

    /// Maximum pixel dimension for comparison images. Larger images are downsampled
    /// via `CGImageSource` to avoid multi-hundred-megabyte decoded bitmaps.
    private static nonisolated let maxImageDimension = 4096

    @Sendable
    nonisolated private static func loadImage(from path: String) async -> NSImage? {
        // Photos Library assets — load via PhotoKit at full comparison resolution
        if path.isPhotosAssetURI, let assetID = path.photosAssetID {
            let size = CGSize(width: maxImageDimension, height: maxImageDimension)
            return await PhotoKitBridge.shared.fetchThumbnail(assetID: assetID, size: size)
        }

        return await Task.detached {
            let url = URL(fileURLWithPath: path) as CFURL
            guard let source = CGImageSourceCreateWithURL(url, nil) else {
                return NSImage(contentsOfFile: path)
            }
            let options: [CFString: Any] = [
                kCGImageSourceThumbnailMaxPixelSize: maxImageDimension,
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceShouldCacheImmediately: true,
            ]
            guard let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
                return NSImage(contentsOfFile: path)
            }
            return NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
        }.value
    }
}

/// Clips content to the left portion of the view, up to a given width.
private struct HorizontalClip: Shape {
    let width: CGFloat

    func path(in rect: CGRect) -> Path {
        Path(CGRect(x: 0, y: 0, width: width, height: rect.height))
    }
}

#if DEBUG
#Preview("Image Comparison — Side by Side") {
    ImageComparisonView(
        pathA: "/System/Library/Desktop Pictures/Sonoma.heic",
        pathB: "/System/Library/Desktop Pictures/Sequoia.heic"
    )
    .frame(width: 800, height: 500)
}

#Preview("Image Comparison — Missing Files") {
    ImageComparisonView(
        pathA: "/nonexistent/file_a.jpg",
        pathB: "/nonexistent/file_b.jpg"
    )
    .frame(width: 800, height: 500)
}
#endif
