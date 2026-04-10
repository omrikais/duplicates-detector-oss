import Foundation

/// Per-file metadata from the CLI JSON envelope.
///
/// All fields use `convertFromSnakeCase` key decoding strategy.
/// Tag fields (`tagTitle`, `tagArtist`, `tagAlbum`) are only present
/// when non-nil in the CLI output.
struct FileMetadata: Codable, Hashable, Sendable {
    let duration: Double?
    let width: Int?
    let height: Int?
    let fileSize: Int
    let codec: String?
    let bitrate: Int?
    let framerate: Double?
    let audioChannels: Int?
    let mtime: Double?
    let tagTitle: String?
    let tagArtist: String?
    let tagAlbum: String?
    let thumbnail: String?
    let pageCount: Int?
    let docTitle: String?
    let docAuthor: String?
    let docCreated: String?
    let albumNames: [String]?

    init(
        duration: Double? = nil, width: Int? = nil, height: Int? = nil,
        fileSize: Int, codec: String? = nil, bitrate: Int? = nil,
        framerate: Double? = nil, audioChannels: Int? = nil, mtime: Double? = nil,
        tagTitle: String? = nil, tagArtist: String? = nil, tagAlbum: String? = nil,
        thumbnail: String? = nil, pageCount: Int? = nil, docTitle: String? = nil,
        docAuthor: String? = nil, docCreated: String? = nil, albumNames: [String]? = nil
    ) {
        self.duration = duration; self.width = width; self.height = height
        self.fileSize = fileSize; self.codec = codec; self.bitrate = bitrate
        self.framerate = framerate; self.audioChannels = audioChannels; self.mtime = mtime
        self.tagTitle = tagTitle; self.tagArtist = tagArtist; self.tagAlbum = tagAlbum
        self.thumbnail = thumbnail; self.pageCount = pageCount; self.docTitle = docTitle
        self.docAuthor = docAuthor; self.docCreated = docCreated; self.albumNames = albumNames
    }
}
