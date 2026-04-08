import CoreLocation
import Photos

/// Metadata extracted from a PHAsset for scoring.
struct PhotoAssetMetadata: Sendable, Equatable, Identifiable {
    let id: String  // PHAsset.localIdentifier
    let filename: String
    let duration: Double?  // nil for images
    let width: Int
    let height: Int
    let fileSize: Int64
    let creationDate: Date?
    let modificationDate: Date?  // PHAsset.modificationDate — staleness key for caching
    let latitude: Double?
    let longitude: Double?
    let cameraModel: String?
    let lensModel: String?
    let albumNames: [String]
    let mediaType: PHAssetMediaType

    var isVideo: Bool { mediaType == .video }
    var isImage: Bool { mediaType == .image }
    var totalPixels: Int { width * height }

    /// Synthetic URI for use in PairResult paths.
    /// Embeds the original filename as a fragment so display code can show
    /// `IMG_1234.JPG` instead of an opaque UUID truncation.
    var photosURI: String { "photos://asset/\(id)#\(filename)" }

    /// Convert to `FileMetadata` for use in `PairResult` envelopes.
    func toFileMetadata() -> FileMetadata {
        FileMetadata(
            duration: duration,
            width: width,
            height: height,
            fileSize: Int(clamping: fileSize),
            codec: nil,
            bitrate: nil,
            framerate: nil,
            audioChannels: nil,
            mtime: modificationDate?.timeIntervalSince1970 ?? creationDate?.timeIntervalSince1970,
            tagTitle: nil,
            tagArtist: nil,
            tagAlbum: nil,
            thumbnail: nil,
            pageCount: nil,
            docTitle: nil,
            docAuthor: nil,
            docCreated: nil,
            albumNames: albumNames.isEmpty ? nil : albumNames
        )
    }
}

// MARK: - Codable

extension PhotoAssetMetadata: Codable {
    enum CodingKeys: String, CodingKey {
        case id, filename, duration, width, height, fileSize
        case creationDate, modificationDate
        case latitude, longitude, cameraModel, lensModel
        case albumNames, mediaType
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        filename = try c.decode(String.self, forKey: .filename)
        duration = try c.decodeIfPresent(Double.self, forKey: .duration)
        width = try c.decode(Int.self, forKey: .width)
        height = try c.decode(Int.self, forKey: .height)
        fileSize = try c.decode(Int64.self, forKey: .fileSize)
        creationDate = try c.decodeIfPresent(Date.self, forKey: .creationDate)
        modificationDate = try c.decodeIfPresent(Date.self, forKey: .modificationDate)
        latitude = try c.decodeIfPresent(Double.self, forKey: .latitude)
        longitude = try c.decodeIfPresent(Double.self, forKey: .longitude)
        cameraModel = try c.decodeIfPresent(String.self, forKey: .cameraModel)
        lensModel = try c.decodeIfPresent(String.self, forKey: .lensModel)
        albumNames = try c.decode([String].self, forKey: .albumNames)
        let rawType = try c.decode(Int.self, forKey: .mediaType)
        mediaType = PHAssetMediaType(rawValue: rawType) ?? .unknown
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(filename, forKey: .filename)
        try c.encodeIfPresent(duration, forKey: .duration)
        try c.encode(width, forKey: .width)
        try c.encode(height, forKey: .height)
        try c.encode(fileSize, forKey: .fileSize)
        try c.encodeIfPresent(creationDate, forKey: .creationDate)
        try c.encodeIfPresent(modificationDate, forKey: .modificationDate)
        try c.encodeIfPresent(latitude, forKey: .latitude)
        try c.encodeIfPresent(longitude, forKey: .longitude)
        try c.encodeIfPresent(cameraModel, forKey: .cameraModel)
        try c.encodeIfPresent(lensModel, forKey: .lensModel)
        try c.encode(albumNames, forKey: .albumNames)
        try c.encode(mediaType.rawValue, forKey: .mediaType)
    }
}
