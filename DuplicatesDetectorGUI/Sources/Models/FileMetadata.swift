import Foundation

/// Per-file metadata from the CLI JSON envelope.
///
/// All fields use `convertFromSnakeCase` key decoding strategy.
/// Tag fields (`tagTitle`, `tagArtist`, `tagAlbum`) are only present
/// when non-nil in the CLI output.
struct FileMetadata: Codable, Hashable, Sendable {
    var duration: Double?
    var width: Int?
    var height: Int?
    var fileSize: Int
    var codec: String?
    var bitrate: Int?
    var framerate: Double?
    var audioChannels: Int?
    var mtime: Double?
    var tagTitle: String?
    var tagArtist: String?
    var tagAlbum: String?
    var thumbnail: String?
    var pageCount: Int?
    var docTitle: String?
    var docAuthor: String?
    var docCreated: String?
    var albumNames: [String]?
}
