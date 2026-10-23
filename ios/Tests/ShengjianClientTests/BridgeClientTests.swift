import XCTest
@testable import ShengjianClient

final class MockProtocol: URLProtocol, @unchecked Sendable {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do { let (code, data) = try Self.handler!(request); client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed); client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self) }
        catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
final class BridgeClientTests: XCTestCase {
    func connection() throws -> BridgeConnection { try BridgeConnection(pairingURL: URL(string: "https://example.trycloudflare.com/?key=synthetic-key")!) }
    func client() throws -> BridgeClient {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockProtocol.self]
        return BridgeClient(connection: try connection(), session: URLSession(configuration: config))
    }
    func testParsesQRCodeWithoutKeepingCredentialInBaseURL() throws {
        let value = try connection()
        XCTAssertEqual(value.baseURL.absoluteString, "https://example.trycloudflare.com")
        XCTAssertEqual(value.key, "synthetic-key")
    }
    func testRejectsUnsafeAndMalformedPairingURLs() {
        for value in ["javascript:alert(1)", "https://example.com", "https://name:password@example.com/?key=test", "http://example.com/?key=test", "http://10.1.2.3.evil.example/?key=test", "HTTP://example.com/?key=test", "https://example.com/desktop?key=test"] {
            XCTAssertThrowsError(try BridgeConnection(pairingURL: URL(string: value)!))
        }
    }
    func testAllowsPrivateLAN() throws { _ = try BridgeConnection(pairingURL: URL(string: "http://192.168.2.3:8766/?key=example")!) }
    func testSendTextUsesPOSTAndOptionalReturn() async throws {
        MockProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST"); XCTAssertEqual(request.url?.path, "/send")
            var body = request.httpBody ?? Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }
                    body.append(contentsOf: buffer.prefix(count))
                }
            }
            let json = try JSONSerialization.jsonObject(with: body) as! [String: Any]
            XCTAssertEqual(json["text"] as? String, "中文 😀"); XCTAssertEqual(json["press_enter"] as? Bool, false)
            return (200, Data("{\"ok\":true}".utf8))
        }
        try await client().sendText("中文 😀", pressEnter: false)
    }
    func testSharedFeedDecodesTextAndFile() async throws {
        MockProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/files/shared")
            return (200, Data("{\"ok\":true,\"items\":[{\"id\":\"one\",\"type\":\"text\",\"text\":\"hello\"},{\"id\":\"two\",\"type\":\"file\",\"name\":\"a.pdf\",\"bytes\":3}]}".utf8))
        }
        let items = try await client().sharedItems(); XCTAssertEqual(items.count, 2); XCTAssertEqual(items[0].text, "hello")
    }
    func testExpiredPairingFailsClearly() async throws {
        MockProtocol.handler = { _ in (401, Data("{\"ok\":false}".utf8)) }
        do { _ = try await client().sharedItems(); XCTFail("should reject expired key") } catch { XCTAssertTrue(error.localizedDescription.contains("失效")) }
    }
    func testFixedRelayStripsFragmentAndAuthenticatesBeforeForwarding() async throws {
        let code = String(repeating: "a", count: 40)
        let connection = try BridgeConnection(pairingURL: URL(string: "https://test.example/shengjian/d/test-device/#" + code)!)
        XCTAssertTrue(connection.isFixedRelay)
        XCTAssertEqual(connection.baseURL.absoluteString, "https://test.example/shengjian/d/test-device")
        XCTAssertNil(URLComponents(url: connection.baseURL, resolvingAgainstBaseURL: false)?.fragment)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockProtocol.self]
        var paths: [String] = []
        MockProtocol.handler = { request in
            paths.append(request.url!.path)
            XCTAssertNil(request.url?.query)
            return (200, Data("{\"ok\":true,\"items\":[]}".utf8))
        }
        let client = BridgeClient(connection: connection, session: URLSession(configuration: config))
        _ = try await client.sharedItems()
        _ = try await client.sharedItems()
        XCTAssertEqual(paths, ["/shengjian/d/test-device/login", "/shengjian/d/test-device/r/files/shared", "/shengjian/d/test-device/r/files/shared"])
    }
    func testFixedRelayRequiresHTTPSAndWellFormedFragment() {
        for value in ["http://192.168.1.1/shengjian/d/device/#" + String(repeating: "a", count: 40), "https://test.example/shengjian/d/device/#short", "https://test.example/shengjian/d/device/?key=secret#" + String(repeating: "a", count: 40)] {
            XCTAssertThrowsError(try BridgeConnection(pairingURL: URL(string: value)!))
        }
    }

}
