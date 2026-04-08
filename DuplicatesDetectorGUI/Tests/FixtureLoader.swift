import Foundation

enum FixtureLoader {
    static func data(named name: String) throws -> Data {
        try Data(contentsOf: url(named: name))
    }

    static func string(named name: String) throws -> String {
        try String(contentsOf: url(named: name), encoding: .utf8)
    }

    private static func url(named name: String) throws -> URL {
        let bundle = Bundle(for: FixtureLoaderBundleToken.self)

        if let url = bundle.url(forResource: name, withExtension: nil, subdirectory: "Fixtures") {
            return url
        }

        guard let url = bundle.url(forResource: name, withExtension: nil) else {
            throw FixtureLoaderError.missingFixture(name)
        }

        return url
    }
}

private final class FixtureLoaderBundleToken {}

enum FixtureLoaderError: Error, LocalizedError {
    case missingFixture(String)

    var errorDescription: String? {
        switch self {
        case .missingFixture(let name):
            "Missing test fixture: \(name)"
        }
    }
}
