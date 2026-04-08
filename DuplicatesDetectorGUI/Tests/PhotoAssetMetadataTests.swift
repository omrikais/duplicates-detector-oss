import Foundation
import Photos
import Testing

@testable import DuplicatesDetector

// MARK: - Test Helpers

/// Shared factory for `PhotoAssetMetadata` with sensible defaults.
private func makeAsset(
    id: String = "test-id",
    filename: String = "IMG_0001.jpg",
    duration: Double? = nil,
    width: Int = 4032,
    height: Int = 3024,
    fileSize: Int64 = 3_200_000,
    creationDate: Date? = nil,
    modificationDate: Date? = nil,
    latitude: Double? = nil,
    longitude: Double? = nil,
    cameraModel: String? = nil,
    lensModel: String? = nil,
    albumNames: [String] = [],
    mediaType: PHAssetMediaType = .image
) -> PhotoAssetMetadata {
    PhotoAssetMetadata(
        id: id, filename: filename, duration: duration,
        width: width, height: height, fileSize: fileSize,
        creationDate: creationDate, modificationDate: modificationDate,
        latitude: latitude, longitude: longitude,
        cameraModel: cameraModel, lensModel: lensModel,
        albumNames: albumNames, mediaType: mediaType
    )
}

// MARK: - PhotoAssetMetadata: photosURI

@Suite("PhotoAssetMetadata.photosURI")
struct PhotosURIPropertyTests {

    @Test("photosURI embeds id and filename in correct format")
    func photosURIFormat() {
        let asset = makeAsset(id: "ABC-123/L0/001", filename: "IMG_1234.JPG")
        #expect(asset.photosURI == "photos://asset/ABC-123/L0/001#IMG_1234.JPG")
    }

    @Test("photosURI with special characters in filename")
    func photosURISpecialCharacters() {
        let asset = makeAsset(id: "DEF-456", filename: "Photo (1).HEIC")
        #expect(asset.photosURI == "photos://asset/DEF-456#Photo (1).HEIC")
    }

    @Test("photosURI with empty filename still has fragment separator")
    func photosURIEmptyFilename() {
        let asset = makeAsset(id: "GHI-789", filename: "")
        #expect(asset.photosURI == "photos://asset/GHI-789#")
    }
}

// MARK: - PhotoAssetMetadata: isVideo / isImage

@Suite("PhotoAssetMetadata.isVideo and isImage")
struct MediaTypePredicateTests {

    @Test("isImage returns true for .image type")
    func isImageForImage() {
        let asset = makeAsset(mediaType: .image)
        #expect(asset.isImage)
        #expect(!asset.isVideo)
    }

    @Test("isVideo returns true for .video type")
    func isVideoForVideo() {
        let asset = makeAsset(mediaType: .video)
        #expect(asset.isVideo)
        #expect(!asset.isImage)
    }

    @Test("isImage and isVideo both false for .audio type")
    func neitherForAudio() {
        let asset = makeAsset(mediaType: .audio)
        #expect(!asset.isImage)
        #expect(!asset.isVideo)
    }

    @Test("isImage and isVideo both false for .unknown type")
    func neitherForUnknown() {
        let asset = makeAsset(mediaType: .unknown)
        #expect(!asset.isImage)
        #expect(!asset.isVideo)
    }
}

// MARK: - PhotoAssetMetadata: totalPixels

@Suite("PhotoAssetMetadata.totalPixels")
struct TotalPixelsTests {

    @Test("totalPixels returns width * height for typical dimensions")
    func normalDimensions() {
        let asset = makeAsset(width: 4032, height: 3024)
        #expect(asset.totalPixels == 4032 * 3024)
    }

    @Test("totalPixels returns 0 when width is zero")
    func zeroWidth() {
        let asset = makeAsset(width: 0, height: 3024)
        #expect(asset.totalPixels == 0)
    }

    @Test("totalPixels returns 0 when height is zero")
    func zeroHeight() {
        let asset = makeAsset(width: 4032, height: 0)
        #expect(asset.totalPixels == 0)
    }

    @Test("totalPixels returns 0 when both dimensions are zero")
    func bothZero() {
        let asset = makeAsset(width: 0, height: 0)
        #expect(asset.totalPixels == 0)
    }

    @Test("totalPixels for 1x1 image")
    func singlePixel() {
        let asset = makeAsset(width: 1, height: 1)
        #expect(asset.totalPixels == 1)
    }
}

// MARK: - PhotoAssetMetadata: Codable round-trip

@Suite("PhotoAssetMetadata Codable")
struct PhotoAssetMetadataCodableTests {

    @Test("full round-trip preserves all fields")
    func fullRoundTrip() throws {
        let creation = Date(timeIntervalSince1970: 1_700_000_000)
        let modification = Date(timeIntervalSince1970: 1_700_001_000)
        let original = makeAsset(
            id: "ABC-123/L0/001",
            filename: "vacation.HEIC",
            duration: 15.5,
            width: 1920,
            height: 1080,
            fileSize: 5_000_000,
            creationDate: creation,
            modificationDate: modification,
            latitude: 40.7128,
            longitude: -74.0060,
            cameraModel: "iPhone 15 Pro",
            lensModel: "iPhone 15 Pro back triple camera 6.765mm f/1.78",
            albumNames: ["Vacation", "Favorites"],
            mediaType: .video
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(original)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(PhotoAssetMetadata.self, from: data)

        #expect(decoded.id == original.id)
        #expect(decoded.filename == original.filename)
        #expect(decoded.duration == original.duration)
        #expect(decoded.width == original.width)
        #expect(decoded.height == original.height)
        #expect(decoded.fileSize == original.fileSize)
        #expect(decoded.creationDate == original.creationDate)
        #expect(decoded.modificationDate == original.modificationDate)
        #expect(decoded.latitude == original.latitude)
        #expect(decoded.longitude == original.longitude)
        #expect(decoded.cameraModel == original.cameraModel)
        #expect(decoded.lensModel == original.lensModel)
        #expect(decoded.albumNames == original.albumNames)
        #expect(decoded.mediaType == original.mediaType)
    }

    @Test("mediaType encodes as raw Int value")
    func mediaTypeEncodesAsInt() throws {
        let asset = makeAsset(mediaType: .video)
        let encoder = JSONEncoder()
        let data = try encoder.encode(asset)
        let jsonObject = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        // PHAssetMediaType.video rawValue is 2
        #expect(jsonObject["mediaType"] as? Int == 2)
    }

    @Test("mediaType .image encodes as raw Int 1")
    func imageMediaTypeEncodesAs1() throws {
        let asset = makeAsset(mediaType: .image)
        let encoder = JSONEncoder()
        let data = try encoder.encode(asset)
        let jsonObject = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        #expect(jsonObject["mediaType"] as? Int == 1)
    }

    // BUG: PHAssetMediaType is an Objective-C enum bridged to Swift. Its init(rawValue:)
    // never returns nil — it creates a value with the given rawValue even if undefined.
    // The `?? .unknown` fallback in the decoder therefore never triggers.
    // To fix, the decoder should check if the rawValue is in the known set (0..3)
    // and explicitly map to .unknown otherwise.
    @Test("unknown mediaType raw value preserves raw value (ObjC enum bridging)")
    func unknownMediaTypePreservesRawValue() throws {
        let json = """
        {
            "id": "test-id",
            "filename": "file.dat",
            "width": 100,
            "height": 100,
            "fileSize": 1024,
            "albumNames": [],
            "mediaType": 999
        }
        """
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(PhotoAssetMetadata.self, from: Data(json.utf8))
        // ObjC enum bridging: rawValue 999 is accepted, not mapped to .unknown
        #expect(decoded.mediaType.rawValue == 999)
        #expect(decoded.mediaType != .unknown)
        #expect(decoded.mediaType != .image)
        #expect(decoded.mediaType != .video)
        #expect(decoded.mediaType != .audio)
    }

    @Test("nil optional fields round-trip correctly")
    func nilFieldsRoundTrip() throws {
        let asset = makeAsset(
            duration: nil,
            creationDate: nil,
            modificationDate: nil,
            latitude: nil,
            longitude: nil,
            cameraModel: nil,
            lensModel: nil
        )
        let encoder = JSONEncoder()
        let data = try encoder.encode(asset)
        let decoded = try JSONDecoder().decode(PhotoAssetMetadata.self, from: data)
        #expect(decoded.duration == nil)
        #expect(decoded.creationDate == nil)
        #expect(decoded.modificationDate == nil)
        #expect(decoded.latitude == nil)
        #expect(decoded.longitude == nil)
        #expect(decoded.cameraModel == nil)
        #expect(decoded.lensModel == nil)
    }
}

// MARK: - PhotoAssetMetadata: toFileMetadata mtime fallback

@Suite("PhotoAssetMetadata.toFileMetadata mtime fallback")
struct ToFileMetadataMtimeTests {

    @Test("mtime uses modificationDate when present")
    func mtimeUsesModificationDate() {
        let modDate = Date(timeIntervalSince1970: 1_700_001_000)
        let createDate = Date(timeIntervalSince1970: 1_700_000_000)
        let asset = makeAsset(creationDate: createDate, modificationDate: modDate)
        let meta = asset.toFileMetadata()
        #expect(meta.mtime == 1_700_001_000)
    }

    @Test("mtime falls back to creationDate when modificationDate is nil")
    func mtimeFallsBackToCreationDate() {
        let createDate = Date(timeIntervalSince1970: 1_700_000_000)
        let asset = makeAsset(creationDate: createDate, modificationDate: nil)
        let meta = asset.toFileMetadata()
        #expect(meta.mtime == 1_700_000_000)
    }

    @Test("mtime is nil when both dates are nil")
    func mtimeNilWhenBothDatesNil() {
        let asset = makeAsset(creationDate: nil, modificationDate: nil)
        let meta = asset.toFileMetadata()
        #expect(meta.mtime == nil)
    }

    @Test("toFileMetadata maps fileSize via Int(clamping:)")
    func fileSizeClamped() {
        let asset = makeAsset(fileSize: 5_000_000)
        let meta = asset.toFileMetadata()
        #expect(meta.fileSize == 5_000_000)
    }

    @Test("toFileMetadata sets codec, bitrate, framerate, audioChannels to nil")
    func videoOnlyFieldsNil() {
        let asset = makeAsset()
        let meta = asset.toFileMetadata()
        #expect(meta.codec == nil)
        #expect(meta.bitrate == nil)
        #expect(meta.framerate == nil)
        #expect(meta.audioChannels == nil)
    }
}

// MARK: - ScanSource URI helpers: photosAssetID with fragment

@Suite("String.photosAssetID with fragment")
struct PhotosAssetIDFragmentTests {

    @Test("photosAssetID strips #fragment and returns asset ID")
    func stripsFragment() {
        let uri = "photos://asset/ABC-123/L0/001#IMG_1234.JPG"
        #expect(uri.photosAssetID == "ABC-123/L0/001")
    }

    @Test("photosAssetID with empty fragment returns asset ID")
    func emptyFragment() {
        let uri = "photos://asset/ABC-123#"
        #expect(uri.photosAssetID == "ABC-123")
    }

    @Test("photosAssetID without fragment returns full identifier")
    func noFragment() {
        let uri = "photos://asset/ABC-123/L0/001"
        #expect(uri.photosAssetID == "ABC-123/L0/001")
    }

    @Test("photosAssetID returns nil for non-photos URI")
    func nonPhotosURI() {
        #expect("/videos/a.mp4".photosAssetID == nil)
    }
}

// MARK: - ScanSource URI helpers: displayFileName with fragment

@Suite("String.displayFileName with fragment")
struct DisplayFileNameFragmentTests {

    @Test("displayFileName returns filename from #fragment")
    func returnsFragmentFilename() {
        let uri = "photos://asset/ABC-123#IMG_1234.JPG"
        #expect(uri.displayFileName == "IMG_1234.JPG")
    }

    @Test("displayFileName returns filename with spaces from #fragment")
    func fragmentWithSpaces() {
        let uri = "photos://asset/DEF-456#My Photo (1).HEIC"
        #expect(uri.displayFileName == "My Photo (1).HEIC")
    }

    @Test("displayFileName falls back to truncated UUID when fragment is empty")
    func emptyFragmentFallback() {
        let uri = "photos://asset/ABCDEFGH-1234-5678-9012-345678901234#"
        let display = uri.displayFileName
        // UUID is > 8 chars, so truncated with ellipsis
        #expect(display == "Photo ABCDEFGH\u{2026}")
    }

    @Test("displayFileName short UUID without truncation")
    func shortUUIDNoTruncation() {
        let uri = "photos://asset/SHORT123#"
        #expect(uri.displayFileName == "Photo SHORT123")
    }

    @Test("displayFileName for filesystem path returns last component")
    func filesystemPath() {
        #expect("/Users/test/Videos/vacation.mp4".displayFileName == "vacation.mp4")
    }
}

// MARK: - ScanSource Codable

@Suite("ScanSource Codable")
struct ScanSourceCodableTests {

    @Test("ScanSource.directory round-trips through JSON")
    func directoryRoundTrip() throws {
        let original = ScanSource.directory
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(ScanSource.self, from: data)
        #expect(decoded == original)
    }

    @Test("ScanSource.photosLibrary round-trips through JSON")
    func photosLibraryRoundTrip() throws {
        let original = ScanSource.photosLibrary(scope: .fullLibrary)
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(ScanSource.self, from: data)
        #expect(decoded == original)
    }

    @Test("ScanSource.directory and .photosLibrary decode to different values")
    func directoryNotEqualToPhotosLibrary() throws {
        let dir = ScanSource.directory
        let photos = ScanSource.photosLibrary(scope: .fullLibrary)
        #expect(dir != photos)
    }
}

// MARK: - PhotosScope Codable

@Suite("PhotosScope Codable")
struct PhotosScopeCodableTests {

    @Test("PhotosScope.fullLibrary round-trips through JSON")
    func fullLibraryRoundTrip() throws {
        let original = PhotosScope.fullLibrary
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(PhotosScope.self, from: data)
        #expect(decoded == original)
    }
}
