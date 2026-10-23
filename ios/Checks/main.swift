import Foundation
import ShengjianClient

final class CheckProtocol: URLProtocol, @unchecked Sendable {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do { let (code, data) = try Self.handler!(request); client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed); client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self) }
        catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
func runChecks() async throws {
    let connection = try BridgeConnection(pairingURL: URL(string: "https://example.trycloudflare.com/?key=synthetic-key")!)
    precondition(connection.baseURL.absoluteString == "https://example.trycloudflare.com")
    precondition(connection.key == "synthetic-key")
    for input in ["javascript:alert(1)", "https://example.com", "https://name:password@example.com/?key=test", "http://example.com/?key=test", "http://10.1.2.3.evil.example/?key=test", "HTTP://example.com/?key=test", "https://example.com/desktop?key=test"] {
        var rejected = false
        do { _ = try BridgeConnection(pairingURL: URL(string: input)!) } catch { rejected = true }
        precondition(rejected)
    }
    _ = try BridgeConnection(pairingURL: URL(string: "http://10.0.0.2:8766/?key=example")!)
    let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [CheckProtocol.self]
    let client = BridgeClient(connection: connection, session: URLSession(configuration: config))
    CheckProtocol.handler = { request in
        precondition(request.httpMethod == "POST" && request.url?.path == "/send")
        var data = request.httpBody
        if data == nil, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var bytes = [UInt8](repeating: 0, count: 4096); var result = Data()
            while stream.hasBytesAvailable { let count = stream.read(&bytes, maxLength: bytes.count); if count <= 0 { break }; result.append(contentsOf: bytes.prefix(count)) }; data = result
        }
        let json = try JSONSerialization.jsonObject(with: data!) as! [String: Any]
        precondition(json["text"] as? String == "中文 😀" && json["press_enter"] as? Bool == false)
        return (200, Data("{\"ok\":true}".utf8))
    }
    try await client.sendText("中文 😀", pressEnter: false)
    CheckProtocol.handler = { request in
        precondition(request.url?.path == "/files/shared")
        return (200, Data("{\"ok\":true,\"items\":[{\"id\":\"one\",\"type\":\"text\",\"text\":\"hello\"},{\"id\":\"two\",\"type\":\"file\",\"name\":\"a.pdf\",\"bytes\":3}]}".utf8))
    }
    let items = try await client.sharedItems(); precondition(items.count == 2 && items[0].text == "hello")
    CheckProtocol.handler = { _ in (401, Data("{\"ok\":false}".utf8)) }
    var expired = false
    do { _ = try await client.sharedItems() } catch { expired = error.localizedDescription.contains("失效") }
    precondition(expired)
    let relay = try BridgeConnection(pairingURL: URL(string: "https://test.example/shengjian/d/device/#" + String(repeating: "a", count: 40))!)
    precondition(relay.isFixedRelay && relay.baseURL.absoluteString == "https://test.example/shengjian/d/device")
    let relayClient = BridgeClient(connection: relay, session: URLSession(configuration: config))
    var paths: [String] = []
    CheckProtocol.handler = { request in
        precondition(request.url?.query == nil && request.url?.fragment == nil)
        paths.append(request.url!.path)
        return (200, Data("{\"ok\":true,\"items\":[]}".utf8))
    }
    _ = try await relayClient.sharedItems()
    _ = try await relayClient.sharedItems()
    precondition(paths == ["/shengjian/d/device/login", "/shengjian/d/device/r/files/shared", "/shengjian/d/device/r/files/shared"])
    print("Client checks passed: legacy QR/LAN/text/files, invalid endpoints, expired key, fixed relay login and credential-free forwarding URL.")
}
try await runChecks()
