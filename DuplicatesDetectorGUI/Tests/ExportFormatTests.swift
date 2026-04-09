import Testing
import UniformTypeIdentifiers
@testable import DuplicatesDetector

@Suite("ExportFormat")
struct ExportFormatTests {
    @Test("html contentType is .html")
    func htmlContentType() {
        #expect(ExportFormat.html.contentType == .html)
    }

    @Test("shell contentType is .shellScript")
    func shellContentType() {
        #expect(ExportFormat.shell.contentType == .shellScript)
    }

    @Test("json contentType is .json")
    func jsonContentType() {
        #expect(ExportFormat.json.contentType == .json)
    }

    @Test("csv contentType is .commaSeparatedText")
    func csvContentType() {
        #expect(ExportFormat.csv.contentType == .commaSeparatedText)
    }

    @Test("displayName values", arguments: [
        (ExportFormat.html, "HTML"),
        (ExportFormat.shell, "shell script"),
        (ExportFormat.json, "JSON"),
        (ExportFormat.csv, "CSV"),
    ])
    func displayNames(format: ExportFormat, expected: String) {
        #expect(format.displayName == expected)
    }

    @Test("defaultFileName values", arguments: [
        (ExportFormat.html, "scan-results.html"),
        (ExportFormat.shell, "scan-results.sh"),
        (ExportFormat.json, "scan-results.ddscan"),
        (ExportFormat.csv, "scan-results.csv"),
    ])
    func defaultFileNames(format: ExportFormat, expected: String) {
        #expect(format.defaultFileName == expected)
    }

    @Test("cliFormatString for replay-based formats")
    func cliFormatStrings() {
        #expect(ExportFormat.html.cliFormatString == "html")
        #expect(ExportFormat.shell.cliFormatString == "shell")
    }

    @Test("cliFormatString is nil for non-replay formats")
    func cliFormatStringNil() {
        #expect(ExportFormat.json.cliFormatString == nil)
        #expect(ExportFormat.csv.cliFormatString == nil)
    }
}
