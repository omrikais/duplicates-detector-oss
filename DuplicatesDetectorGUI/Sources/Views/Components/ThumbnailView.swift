import AppKit
import SwiftUI

/// Renders a thumbnail with progressive loading: system icon placeholder,
/// then async-resolved real thumbnail with crossfade.
///
/// When `path` is provided, uses `ThumbnailProvider` for on-demand generation
/// with memory + disk caching. Falls back to synchronous base64 decode when
/// only `base64` is provided (backward-compatible with all existing call sites).
struct ThumbnailView: View {
    /// File path for async thumbnail resolution (new — on-demand generation).
    var path: String? = nil
    /// Embedded base64 data from the CLI envelope (existing).
    let base64: String?
    var fixedWidth: CGFloat? = nil
    var fixedHeight: CGFloat? = nil
    var maxWidth: CGFloat? = nil
    var maxHeight: CGFloat? = nil
    var contentMode: ContentMode = .fill
    /// Modification date for Photos Library assets (disk cache validation).
    var modificationDate: Date? = nil

    /// Cache for synchronous base64 decode (backward-compatible path).
    private static let base64Cache: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 200
        return cache
    }()

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.ddColors) private var ddColors
    @State private var resolvedImage: NSImage?
    @State private var resolvedPath: String?

    var body: some View {
        if let path {
            asyncBody(path: path)
        } else {
            syncBody
        }
    }

    // MARK: - Async Path (file path available)

    @ViewBuilder
    private func asyncBody(path: String) -> some View {
        let targetSize = CGSize(
            width: fixedWidth ?? maxWidth ?? 200,
            height: fixedHeight ?? maxHeight ?? 200
        )

        Group {
            if let image = resolvedImage, resolvedPath == path {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
                    .transition(.opacity)
            } else {
                // Phase 1: system file icon as placeholder
                Image(nsImage: NSWorkspace.shared.icon(forFile: path))
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .opacity(0.6)
                    .transition(.opacity)
            }
        }
        .frame(width: fixedWidth, height: fixedHeight)
        .frame(maxWidth: maxWidth, maxHeight: maxHeight)
        .clipShape(RoundedRectangle(cornerRadius: DDRadius.small))
        .overlay(alignment: .bottomTrailing) {
            if path.isPhotosAssetURI {
                Image(systemName: "photo.on.rectangle")
                    .font(DDTypography.label.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(3)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 4))
                    .padding(4)
            }
        }
        .accessibilityLabel("Thumbnail for \((path ?? "unknown file").fileName)")
        .accessibilityAddTraits(.isImage)
        .animation(reduceMotion ? .none : DDMotion.smooth, value: resolvedImage != nil)
        .task(id: path) {
            resolvedImage = nil
            resolvedPath = nil
            let image = await ThumbnailProvider.shared.resolve(
                path: path, embeddedBase64: base64, size: targetSize,
                modificationDate: modificationDate
            )
            guard !Task.isCancelled else { return }
            resolvedImage = image
            resolvedPath = path
        }
    }

    // MARK: - Sync Path (base64 only, backward-compatible)

    private var syncBody: some View {
        Group {
            if let nsImage = decodedBase64Image {
                Image(nsImage: nsImage)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
                    .frame(width: fixedWidth, height: fixedHeight)
                    .frame(maxWidth: maxWidth, maxHeight: maxHeight)
                    .clipShape(RoundedRectangle(cornerRadius: DDRadius.small))
                    .accessibilityLabel("Thumbnail for \((base64 != nil ? "file" : "unknown").description)")
                    .accessibilityAddTraits(.isImage)
            } else {
                placeholderView
            }
        }
    }

    private var decodedBase64Image: NSImage? {
        guard let b64 = base64 else { return nil }
        let key = NSString(string: b64)
        if let cached = Self.base64Cache.object(forKey: key) {
            return cached
        }
        guard let data = Data(base64Encoded: b64),
              let image = NSImage(data: data) else { return nil }
        Self.base64Cache.setObject(image, forKey: key)
        return image
    }

    private var placeholderView: some View {
        RoundedRectangle(cornerRadius: DDRadius.small)
            .fill(DDColors.surface2)
            .frame(
                width: fixedWidth ?? maxWidth ?? DDSpacing.thumbnailCompactWidth,
                height: fixedHeight ?? maxHeight ?? DDSpacing.thumbnailCompactHeight
            )
            .overlay {
                Image(systemName: "doc")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
            }
            .accessibilityLabel("Thumbnail placeholder")
            .accessibilityAddTraits(.isImage)
    }
}
