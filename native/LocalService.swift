import Foundation
import CryptoKit

enum LocalServiceError: LocalizedError {
    case unavailable, identity
    var errorDescription: String? {
        switch self {
        case .unavailable: return "本机服务暂时无法连接，正在重试。"
        case .identity: return "本机连接身份不匹配，已停止向该端口发送数据。请重新打开声笺。"
        }
    }
}

struct LocalServiceIdentity: Equatable {
    let port: Int
    let pid: Int
    let instance: String
    init(_ value: [String:Any], childPID: Int) throws {
        guard value["service"] as? String == "shengjian.bridge",
              value["protocol"] as? Int == 1,
              let port = value["port"] as? Int, (1...65535).contains(port),
              let pid = value["pid"] as? Int, pid == childPID,
              let instance = value["instance_id"] as? String,
              instance.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { throw LocalServiceError.identity }
        self.port = port; self.pid = pid; self.instance = instance
    }
    func validate(_ value: [String:Any], challenge: String, key: String) throws {
        guard value["ok"] as? Bool == true,
              value["service"] as? String == "shengjian.bridge",
              value["protocol"] as? Int == 1,
              value["port"] as? Int == port, value["pid"] as? Int == pid,
              value["instance_id"] as? String == instance,
              let proof = value["proof"] as? String,
              proof.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { throw LocalServiceError.identity }
        let bytes = stride(from: 0, to: 64, by: 2).map { i -> UInt8 in
            let start = proof.index(proof.startIndex, offsetBy: i)
            return UInt8(proof[start..<proof.index(start, offsetBy: 2)], radix: 16)!
        }
        let message = "shengjian-local-v1\n\(challenge)\n\(instance)\n\(pid)\n\(port)"
        guard HMAC<SHA256>.isValidAuthenticationCode(bytes, authenticating: Data(message.utf8), using: SymmetricKey(data: Data(key.utf8))) else { throw LocalServiceError.identity }
    }
    func verify(session: URLSession, key: String) async throws {
        let challenge = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/health")!)
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue(challenge, forHTTPHeaderField: "X-Shengjian-Challenge")
        let (data,response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              http.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("application/json") == true,
              data.count <= 16384,
              let value = try? JSONSerialization.jsonObject(with: data) as? [String:Any] else { throw LocalServiceError.identity }
        try validate(value, challenge: challenge, key: key)
    }
}

// A foreign local listener must not redirect account requests to another host.
final class LocalServiceSession: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.connectionProxyDictionary = [:]
        configuration.urlCache = nil
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
