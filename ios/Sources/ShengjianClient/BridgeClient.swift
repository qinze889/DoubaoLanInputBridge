import Foundation

public struct BridgeConnection: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public let baseURL: URL
    public let key: String
    public init(pairingURL: URL, name: String = "我的 Mac") throws {
        guard let components = URLComponents(url: pairingURL, resolvingAgainstBaseURL: false),
              let scheme = components.scheme?.lowercased(), ["https", "http"].contains(scheme),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.path.isEmpty || components.path == "/",
              let key = components.queryItems?.first(where: { $0.name == "key" })?.value,
              !key.isEmpty, key.count <= 256 else { throw ClientError.invalidConnection }
        if scheme == "http" {
            let parts = host.split(separator: ".").compactMap { Int($0) }
            let local = host == "localhost" || host == "127.0.0.1" || (host.split(separator: ".", omittingEmptySubsequences: false).count == 4 && parts.count == 4 && parts.allSatisfy { (0...255).contains($0) } &&
                (parts[0] == 10 || (parts[0] == 172 && (16...31).contains(parts[1])) || (parts[0] == 192 && parts[1] == 168)))
            guard local else { throw ClientError.invalidConnection }
        }
        var base = components; base.scheme = scheme; base.query = nil; base.fragment = nil; base.path = ""
        guard let url = base.url else { throw ClientError.invalidConnection }
        self.id = UUID(); self.name = name; self.baseURL = url; self.key = key
    }
}

public enum ClientError: LocalizedError {
    case invalidConnection, invalidResponse, server(String)
    public var errorDescription: String? {
        switch self {
        case .invalidConnection: return "请扫描声笺应用的连接二维码，或粘贴完整配对链接。"
        case .invalidResponse: return "Mac 未返回有效响应，请确认它在线且公网连接已开启。"
        case .server(let message): return message
        }
    }
}

public struct SharedItem: Codable, Identifiable, Sendable {
    public let id: String
    public let type: String
    public let text: String?
    public let name: String?
    public let bytes: Int?
    public let mtime: Double?
}

private final class SameHostRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        let original = task.originalRequest?.url
        let target = request.url
        completionHandler(target?.host == original?.host && target?.scheme == original?.scheme && target?.port == original?.port ? request : nil)
    }
}

public actor BridgeClient {
    public let connection: BridgeConnection
    private let session: URLSession
    public init(connection: BridgeConnection, session: URLSession? = nil) {
        self.connection = connection
        self.session = session ?? URLSession(configuration: .ephemeral, delegate: SameHostRedirects(), delegateQueue: nil)
    }
    private func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var components = URLComponents(url: connection.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        components.queryItems = query + [URLQueryItem(name: "key", value: connection.key)]
        return components.url!
    }
    private func validate(_ data: Data, _ response: URLResponse) throws -> [String: Any] {
        guard let http = response as? HTTPURLResponse else { throw ClientError.invalidResponse }
        let value = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        guard http.statusCode == 200, value["ok"] as? Bool == true else {
            throw ClientError.server(value["error"] as? String ?? (http.statusCode == 401 ? "配对链接已失效，请重新扫码。" : "请求未完成，请重试。"))
        }
        return value
    }
    public func checkConnection() async throws {
        _ = try await sharedItems()
    }
    public func sendText(_ text: String, pressEnter: Bool = true) async throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw ClientError.server("请先输入文字。") }
        var request = URLRequest(url: url("send")); request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["key": connection.key, "text": text, "press_enter": pressEnter, "enter_delay_sec": 0.5])
        request.timeoutInterval = 30
        let (data, response) = try await session.data(for: request); _ = try validate(data, response)
    }
    public func sharedItems() async throws -> [SharedItem] {
        let (data, response) = try await session.data(from: url("files/shared"))
        let value = try validate(data, response)
        let items = try JSONSerialization.data(withJSONObject: value["items"] ?? [])
        return try JSONDecoder().decode([SharedItem].self, from: items)
    }
    public func uploadFiles(_ files: [URL], paste: Bool = false) async throws {
        guard !files.isEmpty, files.count <= 8 else { throw ClientError.server("一次请选择 1–8 个文件。") }
        let boundary = "Shengjian-" + UUID().uuidString
        let bodyURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        FileManager.default.createFile(atPath: bodyURL.path, contents: nil)
        defer { try? FileManager.default.removeItem(at: bodyURL) }
        let output = try FileHandle(forWritingTo: bodyURL)
        do {
            try output.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"key\"\r\n\r\n\(connection.key)\r\n".utf8))
            for file in files {
                let name = file.lastPathComponent.replacingOccurrences(of: "\"", with: "_").replacingOccurrences(of: "\r", with: "_").replacingOccurrences(of: "\n", with: "_")
                try output.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"files\"; filename=\"\(name)\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8))
                let input = try FileHandle(forReadingFrom: file)
                do { while let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty { try output.write(contentsOf: chunk) }; try input.close() }
                catch { try? input.close(); throw error }
                try output.write(contentsOf: Data("\r\n".utf8))
            }
            try output.write(contentsOf: Data("--\(boundary)--\r\n".utf8)); try output.close()
        } catch { try? output.close(); throw error }
        var request = URLRequest(url: url(paste ? "files/paste" : "files/clipboard")); request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 180
        let (data, response) = try await session.upload(for: request, fromFile: bodyURL); _ = try validate(data, response)
    }
    public func download(_ item: SharedItem) async throws -> URL {
        guard let name = item.name else { throw ClientError.invalidResponse }
        let (location, response) = try await session.download(from: url("files/download", query: [URLQueryItem(name: "file", value: name)]))
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw ClientError.server("文件下载失败。") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let target = folder.appendingPathComponent(URL(fileURLWithPath: name).lastPathComponent)
        try FileManager.default.moveItem(at: location, to: target)
        return target
    }
}
