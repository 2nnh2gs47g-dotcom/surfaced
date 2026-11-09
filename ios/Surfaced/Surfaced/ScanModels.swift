import Foundation

/// Decodes `GET /api/scan` JSON from `server.result_to_dict`.
/// Extra keys such as `checks` and `crawlers` are ignored.
struct ScanReport: Decodable, Equatable {
    let url: String
    let title: String
    let checkedAt: String
    let wordCount: Int
    let javascriptRendered: Bool
    let summary: String
    let grade: String
    let vertical: ScanVertical
    let scores: ScanScores
    let pillars: [String: Int]
    let recommendations: [ScanRecommendation]

    enum CodingKeys: String, CodingKey {
        case url = "url"
        case title = "title"
        case checkedAt = "checked_at"
        case wordCount = "word_count"
        case javascriptRendered = "javascript_rendered"
        case summary = "summary"
        case grade = "grade"
        case vertical = "vertical"
        case scores = "scores"
        case pillars = "pillars"
        case recommendations = "recommendations"
    }
}

struct ScanVertical: Decodable, Equatable {
    let key: String
    let label: String
    let weighting: String
    let detectedFrom: String

    enum CodingKeys: String, CodingKey {
        case key = "key"
        case label = "label"
        case weighting = "weighting"
        case detectedFrom = "detected_from"
    }
}

struct ScanScores: Decodable, Equatable {
    let overall: Int
    let geo: Int
    let aeo: Int
    let reviews: Int
    let social: Int

    enum CodingKeys: String, CodingKey {
        case overall = "overall"
        case geo = "geo"
        case aeo = "aeo"
        case reviews = "reviews"
        case social = "social"
    }
}

struct ScanRecommendation: Decodable, Equatable {
    let label: String
    let priority: String
    let observed: String
    let fix: String

    enum CodingKeys: String, CodingKey {
        case label = "label"
        case priority = "priority"
        case observed = "observed"
        case fix = "fix"
    }
}

/// Unpaid `GET /api/scan` body from `teaser_payload` when payments are on.
/// Checkout fields are intentionally not decoded. The app does not start a purchase.
struct ScanPreview: Decodable, Equatable {
    let access: String
    let url: String
    let title: String
    let checkedAt: String
    let grade: String
    let vertical: ScanVertical
    let scores: ScanPreviewScores
    let topFix: ScanRecommendation?

    enum CodingKeys: String, CodingKey {
        case access = "access"
        case url = "url"
        case title = "title"
        case checkedAt = "checked_at"
        case grade = "grade"
        case vertical = "vertical"
        case scores = "scores"
        case topFix = "top_fix"
    }
}

struct ScanPreviewScores: Decodable, Equatable {
    let overall: Int

    enum CodingKeys: String, CodingKey {
        case overall = "overall"
    }
}

enum ScanOutcome: Equatable {
    case full(ScanReport)
    case preview(ScanPreview)
}

enum ScanPayload {
    /// Full report when pillar scores and recommendations are present (payments off,
    /// or a paid session). Otherwise the teaser preview.
    static func decode(_ data: Data) throws -> ScanOutcome {
        let probe: Probe
        do {
            probe = try JSONDecoder().decode(Probe.self, from: data)
        } catch {
            throw ScanFailure.undecodable
        }
        if probe.summary != nil,
           probe.recommendations != nil,
           probe.pillars != nil,
           probe.scores?.geo != nil {
            do {
                return .full(try JSONDecoder().decode(ScanReport.self, from: data))
            } catch {
                throw ScanFailure.undecodable
            }
        }
        if probe.access == "teaser" {
            do {
                return .preview(try JSONDecoder().decode(ScanPreview.self, from: data))
            } catch {
                throw ScanFailure.undecodable
            }
        }
        throw ScanFailure.undecodable
    }

    private struct Probe: Decodable {
        let access: String?
        let summary: String?
        let recommendations: [ScanRecommendation]?
        let pillars: [String: Int]?
        let scores: Scores?

        struct Scores: Decodable {
            let geo: Int?
        }
    }
}

struct APIErrorBody: Decodable, Equatable {
    let error: String
    let retryAfterSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case error = "error"
        case retryAfterSeconds = "retry_after_seconds"
    }
}

enum ScanFailure: Error, Equatable {
    case websiteInvalid(String)
    case backendMissing
    case backendInvalid
    case transport(String)
    case http(status: Int, message: String)
    case undecodable

    var message: String {
        switch self {
        case .websiteInvalid(let message):
            return message
        case .backendMissing:
            return "Set the HTTPS address of your Surfaced server before scanning."
        case .backendInvalid:
            return "The server address must be an https origin, such as https://scan.example.com, with no path."
        case .transport(let message):
            return message
        case .http(_, let message):
            return message
        case .undecodable:
            return "The server response was not a Surfaced scan report."
        }
    }
}

enum BackendSettings {
    static let storageKey = "surfaced.backendBaseURL"

    static func load(defaults: UserDefaults = .standard) -> String {
        defaults.string(forKey: storageKey) ?? ""
    }

    static func save(_ value: String, defaults: UserDefaults = .standard) {
        defaults.set(value, forKey: storageKey)
    }
}

enum WebsiteAddress {
    /// Returns the address sent as `?url=`. Accepts `example.com` or an http(s) URL.
    static func normalize(_ raw: String) throws -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            throw ScanFailure.websiteInvalid("Enter a website address to check.")
        }
        if trimmed.contains(where: { $0.isWhitespace }) {
            throw ScanFailure.websiteInvalid("The website address cannot contain spaces.")
        }
        let withScheme = trimmed.contains("://") ? trimmed : "https://\(trimmed)"
        guard var components = URLComponents(string: withScheme),
              let scheme = components.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              components.user == nil,
              components.password == nil,
              let host = components.host?.lowercased(),
              host.contains("."),
              !host.hasPrefix("."),
              !host.hasSuffix("."),
              !host.contains("..")
        else {
            throw ScanFailure.websiteInvalid("Enter a website address like example.com.")
        }
        components.scheme = scheme
        guard let url = components.url else {
            throw ScanFailure.websiteInvalid("Enter a website address like example.com.")
        }
        return url.absoluteString
    }
}

enum BackendEndpoint {
    /// `base` is an https origin with no path, query, or credentials. The request is `{base}/api/scan?url=`.
    static func scanURL(base: String, website: String) -> URL? {
        let trimmed = base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        guard var components = URLComponents(string: trimmed) else { return nil }
        guard components.scheme?.lowercased() == "https" else { return nil }
        guard components.user == nil, components.password == nil else { return nil }
        guard let host = components.host, !host.isEmpty else { return nil }
        components.scheme = "https"
        let path = components.path
        guard path.isEmpty || path == "/" else { return nil }
        guard components.query == nil, components.fragment == nil else { return nil }
        components.host = host
        components.path = "/api/scan"
        components.queryItems = [URLQueryItem(name: "url", value: website)]
        return components.url
    }
}

#if DEBUG
extension ScanReport {
    /// Xcode preview only. The running app never uses this as a scan result.
    static let sample = ScanReport(
        url: "https://sample.example/",
        title: "SAMPLE — not a live scan",
        checkedAt: "2026-01-01T00:00:00Z",
        wordCount: 120,
        javascriptRendered: false,
        summary: "SAMPLE payload for Xcode previews. Not a real website score.",
        grade: "F",
        vertical: ScanVertical(
            key: "local",
            label: "Local / in-person business",
            weighting: "40% website (GEO+AEO) + 40% reviews + 20% social",
            detectedFrom: "SAMPLE"
        ),
        scores: ScanScores(overall: 32, geo: 40, aeo: 50, reviews: 20, social: 30),
        pillars: ["Content": 33],
        recommendations: [
            ScanRecommendation(
                label: "Answer-first summary",
                priority: "High",
                observed: "SAMPLE: no summary found.",
                fix: "SAMPLE: add a short answer at the top."
            )
        ]
    )
}
#endif
