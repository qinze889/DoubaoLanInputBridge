import SwiftUI
import Security
import ShengjianClient

@MainActor final class ConnectionStore: ObservableObject {
    @Published var connections: [BridgeConnection] = []
    @Published var selectedID: UUID?
    @Published var error = ""
    @Published var notice = ""
    @Published var busy = false
    @Published var shared: [SharedItem] = []
    @Published var success = 0
    @Published var cloudURL: URL?
    @Published var cloudScanID = UUID()
    let service = "com.doubaolaninputbridge.ios.connections"
    var selected: BridgeConnection? { connections.first { $0.id == selectedID } }
    init() {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccount as String: "devices", kSecReturnData as String: true]
        var result: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data,
           let saved = try? JSONDecoder().decode([BridgeConnection].self, from: data) {
            connections = saved; selectedID = saved.first?.id
        }
    }
    private func save(_ values: [BridgeConnection]) throws {
        let data = try JSONEncoder().encode(values)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "devices"]
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var create = query; create[kSecValueData as String] = data
            create[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            status = SecItemAdd(create as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw ClientError.server("无法安全保存配对信息。") }
        connections = values
    }
    func add(link: String, name: String) async -> Bool {
        if let url = URL(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
           url.scheme == "https", url.host == "test.xjiaoai.com", url.port == nil,
           url.user == nil, url.password == nil, url.path == "/shengjian/api/v2/console", url.query == nil {
            cloudURL = url
            cloudScanID = UUID()
            return true
        }
        busy = true; defer { busy = false }
        do {
            guard let url = URL(string: link.trimmingCharacters(in: .whitespacesAndNewlines)) else { throw ClientError.invalidConnection }
            let connection = try BridgeConnection(pairingURL: url, name: name.isEmpty ? "我的 Mac" : name)
            try await BridgeClient(connection: connection).checkConnection()
            var values = connections.filter { $0.baseURL != connection.baseURL }; values.append(connection)
            try save(values); selectedID = connection.id; success += 1
            return true
        } catch { self.error = error.localizedDescription; return false }
    }
    func remove(_ id: UUID) {
        do { try save(connections.filter { $0.id != id }); if selectedID == id { selectedID = connections.first?.id } }
        catch { self.error = error.localizedDescription }
    }
    func send(_ text: String, enter: Bool) async -> Bool {
        guard let selected else { return false }
        busy = true; defer { busy = false }
        do { try await BridgeClient(connection: selected).sendText(text, pressEnter: enter); completed("已发送到 \(selected.name)"); return true }
        catch { self.error = error.localizedDescription; return false }
    }
    func upload(_ files: [URL], paste: Bool) async {
        guard let selected else { return }
        busy = true; defer { busy = false }
        let scoped = files.filter { $0.startAccessingSecurityScopedResource() }
        defer { for file in scoped { file.stopAccessingSecurityScopedResource() } }
        do { try await BridgeClient(connection: selected).uploadFiles(files, paste: paste); completed(paste ? "文件已发送并粘贴到 Mac" : "文件已上传到 Mac 剪贴板") }
        catch { self.error = error.localizedDescription }
    }
    func refresh() async {
        guard let selected else { shared = []; return }
        do { shared = try await BridgeClient(connection: selected).sharedItems() }
        catch { self.error = error.localizedDescription }
    }
    func download(_ item: SharedItem) async -> URL? {
        guard let selected else { return nil }
        busy = true; defer { busy = false }
        do { return try await BridgeClient(connection: selected).download(item) }
        catch { self.error = error.localizedDescription; return nil }
    }
    func completed(_ value: String) {
        notice = value; success += 1
        Task { try? await Task.sleep(for: .seconds(3)); if notice == value { notice = "" } }
    }
}
