import Foundation

struct ScanClient {
    var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 90
        configuration.timeoutIntervalForResource = 90
        configuration.waitsForConnectivity = false
        return URLSession(configuration: configuration)
    }()

    func scan(websiteRaw: String, backendBase: String) async throws -> ScanOutcome {
        let website = try WebsiteAddress.normalize(websiteRaw)
        let trimmedBase = backendBase.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedBase.isEmpty {
            throw ScanFailure.backendMissing
        }
        guard let endpoint = BackendEndpoint.scanURL(base: trimmedBase, website: website) else {
            throw ScanFailure.backendInvalid
        }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.timeoutInterval = 90
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            if error.code == .cancelled { throw CancellationError() }
            throw ScanFailure.transport(Self.message(for: error))
        } catch let error as ScanFailure {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ScanFailure.transport("The scan could not reach the server.")
        }

        guard let http = response as? HTTPURLResponse else {
            throw ScanFailure.transport("The server returned an unexpected response.")
        }

        if !(200 ... 299).contains(http.statusCode) {
            let apiError = try? JSONDecoder().decode(APIErrorBody.self, from: data)
            let message = apiError?.error
                ?? "The server could not complete the scan (HTTP \(http.statusCode))."
            throw ScanFailure.http(status: http.statusCode, message: message)
        }

        return try ScanPayload.decode(data)
    }

    private static func message(for error: URLError) -> String {
        switch error.code {
        case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed:
            return "No network connection. Check the connection and try again."
        case .timedOut:
            return "The scan timed out before the server responded."
        case .cannotFindHost, .dnsLookupFailed:
            return "The server address could not be found."
        case .cannotConnectToHost:
            return "Could not connect to the Surfaced server."
        case .secureConnectionFailed, .serverCertificateUntrusted,
             .serverCertificateHasBadDate, .serverCertificateNotYetValid,
             .clientCertificateRejected, .clientCertificateRequired:
            return "The secure connection to the server failed."
        case .cancelled:
            return "The scan was cancelled."
        default:
            return "The scan could not reach the server."
        }
    }
}
