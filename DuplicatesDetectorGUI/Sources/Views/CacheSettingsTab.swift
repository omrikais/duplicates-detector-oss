import SwiftUI

/// Cache preferences: location, sizes, clear buttons, disable toggles.
struct CacheSettingsTab: View {
    @Environment(ObservableDefaults.self) private var defaults
    @Environment(\.ddColors) private var ddColors
    @State private var metadataSize: Int64?
    @State private var contentSize: Int64?
    @State private var audioSize: Int64?
    @State private var showClearAllConfirmation = false
    @State private var resolvedDefaultDir: URL?
    @State private var isRefreshing = false
    @State private var isClearing = false
    @State private var photosCacheSize: Int64 = 0
    @State private var thumbnailCacheSize: Int64 = 0
    @State private var showClearPhotosConfirmation = false
    @State private var showClearThumbnailsConfirmation = false

    private var effectiveDirectory: URL? {
        let trimmed = defaults.cacheDir.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty {
            return URL(fileURLWithPath: (trimmed as NSString).expandingTildeInPath)
        }
        return resolvedDefaultDir
    }

    private var totalSize: Int64 {
        (metadataSize ?? 0) + (contentSize ?? 0) + (audioSize ?? 0)
    }

    var body: some View {
        @Bindable var defaults = defaults
        Form {
            locationSection(defaults: defaults)
            sizesSection
            clearSection
            photosCacheSection
            togglesSection(defaults: defaults)
        }
        .formStyle(.grouped)
        .task {
            resolvedDefaultDir = await CacheManager.resolvedDefaultCacheDirectory()
            refreshSizes()
            await refreshPhotosSizes()
        }
        .onChange(of: defaults.cacheDir) { _, _ in
            refreshSizes()
        }
    }

    // MARK: - Sections

    @ViewBuilder
    private func locationSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Cache Location") {
            LabeledContent("Directory") {
                Text(effectiveDirectory?.path ?? "...")
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            TextField("Custom directory (leave empty for default)", text: $defaults.cacheDir)
                .textFieldStyle(.roundedBorder)

            Button("Open in Finder") {
                CacheManager.revealInFinder(directory: effectiveDirectory)
            }
        }
    }

    @ViewBuilder
    private var sizesSection: some View {
        Section("Cache Sizes") {
            cacheRow(name: "Metadata", filename: CacheManager.metadataFilename, size: metadataSize)
            cacheRow(name: "Content Hashes", filename: CacheManager.contentHashFilename, size: contentSize)
            cacheRow(name: "Audio Fingerprints", filename: CacheManager.audioFingerprintFilename, size: audioSize)

            LabeledContent("Total") {
                Text(formatSize(totalSize))
                    .bold()
            }

            Button("Refresh") { refreshSizes() }
                .disabled(isRefreshing || isClearing)
        }
    }

    @ViewBuilder
    private var clearSection: some View {
        Section("Clear Cache") {
            HStack {
                Button("Metadata") {
                    clearSingle(CacheManager.metadataFilename)
                }
                .disabled(metadataSize == nil || isRefreshing || isClearing)

                Button("Content Hashes") {
                    clearSingle(CacheManager.contentHashFilename)
                }
                .disabled(contentSize == nil || isRefreshing || isClearing)

                Button("Audio Fingerprints") {
                    clearSingle(CacheManager.audioFingerprintFilename)
                }
                .disabled(audioSize == nil || isRefreshing || isClearing)
            }

            Button("Clear All Caches", role: .destructive) {
                showClearAllConfirmation = true
            }
            .disabled(totalSize == 0 || isRefreshing || isClearing)
            .accessibilityHint("Removes all cached metadata and hashes")
            .confirmationDialog(
                "Clear all cache files?",
                isPresented: $showClearAllConfirmation,
                titleVisibility: .visible
            ) {
                Button("Clear All", role: .destructive) { clearAll() }
            } message: {
                Text("This will delete \(formatSize(totalSize)) of cached data. The caches will be rebuilt on the next scan.")
            }
        }
    }

    @ViewBuilder
    private func togglesSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Default Cache Settings") {
            Toggle("Disable metadata cache", isOn: $defaults.noMetadataCache)
            Toggle("Disable content hash cache", isOn: $defaults.noContentCache)
            Toggle("Disable audio fingerprint cache", isOn: $defaults.noAudioCache)

            Text("These settings apply as defaults for new scans.")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
    }

    // MARK: - Photos Cache

    @ViewBuilder
    private var photosCacheSection: some View {
        Section("Photos Library Cache") {
            LabeledContent("Photos Metadata & Scores") {
                Text(formatSize(photosCacheSize))
                    .foregroundStyle(photosCacheSize > 0 ? ddColors.textPrimary : ddColors.textSecondary)
            }

            LabeledContent("Thumbnails") {
                Text(formatSize(thumbnailCacheSize))
                    .foregroundStyle(thumbnailCacheSize > 0 ? ddColors.textPrimary : ddColors.textSecondary)
            }

            LabeledContent("Total") {
                Text(formatSize(photosCacheSize + thumbnailCacheSize))
                    .bold()
            }

            HStack(spacing: DDSpacing.sm) {
                Button("Clear Photos DB") {
                    showClearPhotosConfirmation = true
                }
                .disabled(photosCacheSize == 0 || isRefreshing || isClearing)
                .confirmationDialog(
                    "Clear Photos metadata and scores cache?",
                    isPresented: $showClearPhotosConfirmation,
                    titleVisibility: .visible
                ) {
                    Button("Clear Photos DB", role: .destructive) { clearPhotosCache() }
                } message: {
                    Text("This will delete \(formatSize(photosCacheSize)) of cached Photos Library metadata and scored pairs. They will be rebuilt on the next Photos scan.")
                }

                Button("Clear Thumbnails") {
                    showClearThumbnailsConfirmation = true
                }
                .disabled(thumbnailCacheSize == 0 || isRefreshing || isClearing)
                .confirmationDialog(
                    "Clear thumbnail cache?",
                    isPresented: $showClearThumbnailsConfirmation,
                    titleVisibility: .visible
                ) {
                    Button("Clear Thumbnails", role: .destructive) { clearThumbnailCache() }
                } message: {
                    Text("This will delete \(formatSize(thumbnailCacheSize)) of cached thumbnails. They will be regenerated on demand.")
                }
            }

            Text("Photos Library metadata, scored pairs, and generated thumbnails are cached locally.")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
    }

    // MARK: - Helpers

    @ViewBuilder
    private func cacheRow(name: String, filename: String, size: Int64?) -> some View {
        LabeledContent(name) {
            Text(size.map(formatSize) ?? "Not found")
                .foregroundStyle(size == nil ? ddColors.textSecondary : ddColors.textPrimary)
        }
    }

    private func refreshSizes() {
        let dir = effectiveDirectory
        isRefreshing = true
        Task.detached {
            let sizes = CacheManager.cacheSizes(directory: dir)
            await MainActor.run {
                metadataSize = sizes.metadata
                contentSize = sizes.content
                audioSize = sizes.audio
                isRefreshing = false
            }
        }
    }

    private func clearSingle(_ filename: String) {
        let dir = effectiveDirectory
        isClearing = true
        Task.detached {
            try? CacheManager.clearCache(filename: filename, directory: dir)
            let sizes = CacheManager.cacheSizes(directory: dir)
            await MainActor.run {
                metadataSize = sizes.metadata
                contentSize = sizes.content
                audioSize = sizes.audio
                isClearing = false
            }
        }
    }

    private func clearAll() {
        let dir = effectiveDirectory
        isClearing = true
        Task.detached {
            try? CacheManager.clearAllCaches(directory: dir)
            let sizes = CacheManager.cacheSizes(directory: dir)
            await MainActor.run {
                metadataSize = sizes.metadata
                contentSize = sizes.content
                audioSize = sizes.audio
                isClearing = false
            }
        }
    }

    private func refreshPhotosSizes() async {
        let photosSize = await CacheManager.photosCacheSize()
        let thumbSize = CacheManager.thumbnailCacheSize()
        photosCacheSize = photosSize
        thumbnailCacheSize = thumbSize
    }

    private func clearPhotosCache() {
        isClearing = true
        Task {
            try? await CacheManager.clearPhotosCache()
            await refreshPhotosSizes()
            isClearing = false
        }
    }

    private func clearThumbnailCache() {
        isClearing = true
        Task.detached {
            try? CacheManager.clearThumbnailCache()
            let thumbSize = CacheManager.thumbnailCacheSize()
            let photosSize = await CacheManager.photosCacheSize()
            await MainActor.run {
                thumbnailCacheSize = thumbSize
                photosCacheSize = photosSize
                isClearing = false
            }
        }
    }

    private func formatSize(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
