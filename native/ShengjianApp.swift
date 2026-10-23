import SwiftUI
import AppKit
import CoreImage.CIFilterBuiltins
import UniformTypeIdentifiers
import ApplicationServices
import Darwin

// Keyboard events belong to the app the user authorizes, not its Python helper.
// The private socket only accepts permission checks and the two supported keys.
final class NativeInputBroker: @unchecked Sendable {
    let path = "/tmp/shengjian-input-\(UUID().uuidString).sock"
    let token = UUID().uuidString + UUID().uuidString
    private var descriptor: Int32 = -1
    var environment: [String:String] { ["SHENGJIAN_NATIVE_INPUT_SOCKET":path, "SHENGJIAN_NATIVE_INPUT_TOKEN":token] }

    init() throws {
        descriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw POSIXError(.EIO) }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let bytes = Array(path.utf8CString)
        guard bytes.count <= MemoryLayout.size(ofValue:address.sun_path) else { stop(); throw POSIXError(.ENAMETOOLONG) }
        withUnsafeMutableBytes(of:&address.sun_path) { target in bytes.withUnsafeBytes { target.copyBytes(from:$0) } }
        let result = withUnsafePointer(to:&address) { pointer in
            pointer.withMemoryRebound(to:sockaddr.self,capacity:1) { Darwin.bind(descriptor,$0,socklen_t(MemoryLayout<sockaddr_un>.size)) }
        }
        guard result == 0, Darwin.chmod(path,0o600) == 0, Darwin.listen(descriptor,8) == 0 else { stop(); throw POSIXError(.EIO) }
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in self?.serve() }
    }
    func stop() {
        if descriptor >= 0 { Darwin.shutdown(descriptor,SHUT_RDWR); Darwin.close(descriptor); descriptor = -1 }
        Darwin.unlink(path)
    }
    deinit { stop() }

    private func serve() {
        while descriptor >= 0 {
            let client = Darwin.accept(descriptor,nil,nil)
            if client < 0 { return }
            var timeout = timeval(tv_sec:2,tv_usec:0)
            setsockopt(client,SOL_SOCKET,SO_RCVTIMEO,&timeout,socklen_t(MemoryLayout<timeval>.size))
            var noSignal: Int32 = 1
            setsockopt(client,SOL_SOCKET,SO_NOSIGPIPE,&noSignal,socklen_t(MemoryLayout<Int32>.size))
            var input = Data(), buffer = [UInt8](repeating:0,count:1024)
            while input.count < 8192 && !input.contains(10) {
                let size = Darwin.read(client,&buffer,buffer.count)
                if size <= 0 { break }
                input.append(contentsOf:buffer.prefix(size))
            }
            var reply: [String:Any] = ["ok":false,"error":"本机输入请求被拒绝"]
            if let request = try? JSONSerialization.jsonObject(with:input) as? [String:Any],
               request["token"] as? String == token {
                reply = DispatchQueue.main.sync { self.perform(request) }
            }
            if var output = try? JSONSerialization.data(withJSONObject:reply) {
                output.append(10)
                output.withUnsafeBytes { buffer in
                    var sent = 0
                    while sent < buffer.count {
                        let size = Darwin.write(client,buffer.baseAddress!.advanced(by:sent),buffer.count-sent)
                        if size <= 0 { break }
                        sent += size
                    }
                }
            }
            Darwin.close(client)
        }
    }
    private func perform(_ request:[String:Any]) -> [String:Any] {
        let operation = request["operation"] as? String ?? ""
        if operation == "permission" { return ["ok":true,"allowed":AXIsProcessTrusted()] }
        if operation == "request-permission" {
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String:true] as CFDictionary
            AXIsProcessTrustedWithOptions(options)
            return ["ok":true]
        }
        guard operation == "paste" || operation == "enter" else { return ["ok":false,"error":"不支持的输入操作"] }
        guard AXIsProcessTrusted() else { return ["ok":false,"error":"请在系统设置的设备控制和数据访问（辅助功能）中重新开启声笺。"] }
        let key:CGKeyCode = operation == "paste" ? 9 : 36
        guard let down = CGEvent(keyboardEventSource:nil,virtualKey:key,keyDown:true),
              let up = CGEvent(keyboardEventSource:nil,virtualKey:key,keyDown:false) else { return ["ok":false,"error":"无法创建键盘事件"] }
        if operation == "paste" { down.flags = .maskCommand; up.flags = .maskCommand }
        down.post(tap:.cghidEventTap); up.post(tap:.cghidEventTap)
        return ["ok":true]
    }
}

private typealias ViewState<Value> = SwiftUI.State<Value>

private let accent = Color(red: 0.0, green: 0.48, blue: 1.0)
private let canvas = Color(nsColor: NSColor(name:nil) { appearance in
    appearance.bestMatch(from:[.aqua,.darkAqua]) == .darkAqua
    ? NSColor(calibratedWhite:0.065,alpha:1)
    : NSColor(calibratedRed:0.965,green:0.965,blue:0.978,alpha:1)
})
private let surface = Color(nsColor: NSColor(name:nil) { appearance in
    appearance.bestMatch(from:[.aqua,.darkAqua]) == .darkAqua ? NSColor(calibratedWhite:0.12,alpha:1) : .white
})

struct PairedMachine: Identifiable {
    let id: String
    let name: String
    let endpoint: String
}
struct MachineJob: Identifiable {
    let id: String
    let peer: String
    let name: String
    let status: String
    let direction: String
    let sent: Double
    let total: Double
    let error: String
    var progress: Double { total > 0 ? min(1, sent / total) : status == "complete" ? 1 : 0 }
}

struct Transfer: Identifiable {
    let id: String
    let type: String
    let title: String
    let detail: String
    let time: Date
    let filePath: String?
    var icon: String { type == "text" ? "text.alignleft" : type == "image" ? "photo" : type == "video" ? "play.rectangle" : "doc" }
    var tint: Color { type == "text" ? .blue : type == "image" ? .purple : .orange }
}

@MainActor final class BridgeModel: ObservableObject {
    @Published var online = false
    @Published var publicEnabled = true
    @Published var relayConfigured = false
    @Published var connectionMode = "lan"
    @Published var modeDescription = "同一 Wi-Fi 或内网直接连接。"
    @Published var p2pCount = 0
    @Published var tunnelPhase = "off"
    @Published var publicURL = ""
    @Published var lanURL = ""
    @Published var localURL = ""
    @Published var allowed = false
    @Published var transfers: [Transfer] = []
    @Published var total = 0
    @Published var more = false
    @Published var query = ""
    @Published var category = "all"
    @Published var loading = false
    @Published var notice: String?
    @Published var lastError = ""
    @Published var selected: String? = "connect"
    @Published var showPublish = false
    @Published var publishText = ""
    @Published var publishFiles: [URL] = []
    @Published var publishTarget = "phone"
    @Published var publishFileMode = false
    @Published var importingFiles = false
    @Published var copied = false
    @Published var busy = false
    @Published var machines: [PairedMachine] = []
    @Published var machineJobs: [MachineJob] = []
    @Published var invitation = ""
    @Published var showAddMachine = false
    @Published var showInvitation = false
    private var pendingImportCount = 0
    private var retryFiles: [String: (String, [URL])] = [:]
    private var process: Process?
    private var nativeInput: NativeInputBroker?
    private var timer: Timer?
    private var port = 0
    private var key = ""
    private var stateInFlight = false
    private var historyTask: Task<Void, Never>?
    private var wasReady = false
    private var lastTunnelError = ""
    let preview = CommandLine.arguments.contains("--preview")
    let dataDirectory: URL = {
        if let override = ProcessInfo.processInfo.environment["DOUBAO_BRIDGE_DATA_DIR"], !override.isEmpty { return URL(fileURLWithPath: override) }
        let folder = Bundle.main.bundleIdentifier?.hasSuffix(".development") == true ? "DoubaoLanInputBridge-Development" : "DoubaoLanInputBridge"
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/" + folder)
    }()
    static let modes = [("public", "固定公网", "globe"), ("cloudflare", "CF 隧道", "cloud"), ("p2p", "P2P 直连", "point.3.connected.trianglepath.dotted"), ("lan", "局域网", "wifi")]
    var modeTitle: String { Self.modes.first { $0.0 == connectionMode }?.1 ?? "连接" }
    var connectedURL: String { publicEnabled && tunnelPhase == "ready" ? publicURL : "" }
    var publicHost: String { URL(string: publicURL)?.host ?? "正在准备连接" }
    var connectionLabel: String {
        if !online { return "服务启动中" }
        if !publicEnabled { return "连接已关闭" }
        return tunnelPhase == "ready" ? modeTitle + "已就绪" : tunnelPhase == "starting" ? "正在连接" : "连接未就绪"
    }
    var connectionColor: Color { !online || !publicEnabled ? .secondary : tunnelPhase == "ready" ? .green : .orange }

    init() {
        if CommandLine.arguments.contains("--agent") { selected = "agent" }
        if preview {
            online = true; allowed = true; tunnelPhase = "ready"
            publicURL = "https://preview-example.trycloudflare.com/?key=preview-only"
            lanURL = "http://192.168.1.8:8766/?key=preview-only"
            localURL = lanURL
            transfers = [Transfer(id:"demo1",type:"text",title:"把突然想到的灵感，轻轻送到 Mac。",detail:"手机 → Mac · 文字",time:Date().addingTimeInterval(-180),filePath:nil), Transfer(id:"demo2",type:"image",title:"周末的城市漫步.heic",detail:"手机 → Mac · 图片",time:Date().addingTimeInterval(-960),filePath:nil)]
            total = transfers.count
            return
        }
        if UserDefaults.standard.object(forKey: "cloudEnabled") != nil { publicEnabled = UserDefaults.standard.bool(forKey: "cloudEnabled") }
        launchService()
    }

    func launchService() {
        do { nativeInput = try NativeInputBroker() }
        catch { report("无法启动本机输入服务，请重新打开声笺。"); return }
        let executable = Bundle.main.resourceURL!.appendingPathComponent("bridge-service/bridge-service")
        let child = Process(); let output = Pipe()
        child.executableURL = executable
        child.environment = ProcessInfo.processInfo.environment
        child.environment?["DOUBAO_BRIDGE_DATA_DIR"] = dataDirectory.path
        child.environment?.merge(nativeInput!.environment) { _, new in new }
        child.standardOutput = output
        child.standardError = FileHandle.nullDevice
        child.terminationHandler = { [weak self] _ in Task { @MainActor in self?.online = false; self?.lastError = "本机服务已停止，请重新打开应用。" } }
        do {
            try child.run(); process = child
            let handle = output.fileHandleForReading
            Task.detached { [weak self] in
                var buffer = Data()
                do {
                    while buffer.count < 4096 {
                        let chunk = handle.availableData
                        guard !chunk.isEmpty else { break }
                        buffer.append(chunk)
                        if buffer.contains(10) { break }
                    }
                    if let line = String(data:buffer,encoding:.utf8)?.split(separator:"\n").first,
                       let data = String(line).data(using:.utf8),
                       let info = try JSONSerialization.jsonObject(with:data) as? [String:Any],
                       let port = info["port"] as? Int {
                        await self?.didStart(port:port)
                    } else { await self?.report("服务启动失败，请重新打开应用。") }
                } catch { await self?.report("无法连接本机服务。") }
            }
        } catch { report("无法启动服务：\(error.localizedDescription)") }
    }
    private func didStart(port:Int) async {
        self.port = port
        do { key = try String(contentsOf:dataDirectory.appendingPathComponent("access_key.txt"),encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines) }
        catch { report("无法读取本机配对信息。"); return }
        await refresh()
        await loadHistory()
        timer = Timer.scheduledTimer(withTimeInterval:2,repeats:true) { [weak self] _ in Task { @MainActor in await self?.refresh() } }

    }
    func report(_ text:String) { lastError = text }
    func api(_ path:String, body:[String:Any]? = nil) async throws -> [String:Any] {
        guard port > 0 else { throw URLError(.cannotConnectToHost) }
        var request:URLRequest
        if let body {
            request = URLRequest(url:URL(string:"http://127.0.0.1:\(port)\(path)")!)
            request.httpMethod = "POST"
            request.setValue("application/json",forHTTPHeaderField:"Content-Type")
            var payload = body; payload["key"] = key
            request.httpBody = try JSONSerialization.data(withJSONObject:payload)
        } else {
            let separator = path.contains("?") ? "&" : "?"
            request = URLRequest(url:URL(string:"http://127.0.0.1:\(port)\(path)\(separator)key=\(key)")!)
        }
        request.timeoutInterval = 90
        let (data,response) = try await URLSession.shared.data(for:request)
        let result = (try? JSONSerialization.jsonObject(with:data) as? [String:Any]) ?? [:]
        guard (response as? HTTPURLResponse)?.statusCode == 200, result["ok"] as? Bool == true else {
            throw NSError(domain:"Shengjian",code:1,userInfo:[NSLocalizedDescriptionKey: result["error"] as? String ?? "请求未完成，请重试。"])
        }
        return result
    }
    func refresh() async {
        guard !preview, !stateInFlight else { return }
        stateInFlight = true; defer { stateInFlight = false }
        do {
            let state = try await api("/desktop/state")
            online = true; allowed = state["accessibility"] as? Bool ?? false
            let host = state["host"] as? String ?? "127.0.0.1"
            lanURL = "http://\(host):\(port)/?key=\(key)"
            localURL = state["local_url"] as? String ?? ""
            let relay = state["relay"] as? [String:Any] ?? [:]
            relayConfigured = relay["configured"] as? Bool ?? false
            let connection = state["connections"] as? [String:Any] ?? [:]
            connectionMode = connection["mode"] as? String ?? "lan"
            publicEnabled = connection["enabled"] as? Bool ?? false
            publicURL = connection["url"] as? String ?? ""
            let phase = connection["phase"] as? String ?? "off"
            tunnelPhase = phase == "online" || phase == "ready" ? "ready" : phase == "reconnecting" ? "starting" : phase
            let modes = connection["modes"] as? [[String:Any]] ?? []
            modeDescription = modes.first { $0["id"] as? String == connectionMode }?["description"] as? String ?? ""
            p2pCount = (connection["p2p"] as? [String:Any])?["connections"] as? Int ?? 0
            if let error = connection["error"] as? String, !error.isEmpty, error != lastTunnelError { lastTunnelError = error; lastError = error }
            if selected == "history" && transfers.count <= 30 { await loadHistory() }
            if selected == "machines" { await loadMachines() }
        } catch { online = false }
    }
    func setPublic(_ value:Bool) async { await setMode(connectionMode, enabled:value) }
    func setMode(_ mode:String, enabled:Bool = true) async {
        guard !busy else { return }
        guard !preview else { connectionMode = mode; publicEnabled = enabled; tunnelPhase = enabled ? "ready" : "off"; return }
        busy = true; defer { busy = false }
        do {
            _ = try await api("/desktop/connections",body:["mode":mode,"enabled":enabled])
            lastError = ""; lastTunnelError = ""
            await refresh()
        } catch { report(error.localizedDescription) }
    }
    func importServerConfig() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        panel.message = "选择后台为这台机器生成的 relay.json。每台机器使用独立配置。"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let data = try Data(contentsOf:url)
            guard data.count < 16384, let config = try JSONSerialization.jsonObject(with:data) as? [String:Any] else { report("配置格式不正确"); return }
            Task {
                do { _ = try await api("/desktop/connections/config",body:["config":config]); await refresh(); toast("服务器配置已导入") }
                catch { report(error.localizedDescription) }
            }
        } catch { report("无法读取配置文件") }
    }
    func regenerate() async {
        guard !preview else { return }
        do {
            let data = try await api("/desktop/key/regenerate",body:[:])
            if let value = data["key"] as? String { key = value }
            await refresh(); toast("二维码已刷新，旧的配对链接已失效")
        } catch { report(error.localizedDescription) }
    }
    func requestPermission() async {
        do { _ = try await api("/desktop/accessibility",body:[:]) } catch { report(error.localizedDescription) }
    }
    func loadHistory(more loadMore:Bool = false) async {
        guard !preview else { return }
        do {
            let encoded = query.addingPercentEncoding(withAllowedCharacters:.urlQueryAllowed.subtracting(CharacterSet(charactersIn:"&+#?"))) ?? ""
            let offset = loadMore ? transfers.count : 0
            let result = try await api("/desktop/history?q=\(encoded)&category=\(category)&offset=\(offset)&limit=30")
            let items = (result["items"] as? [[String:Any]] ?? []).map { row -> Transfer in
                let summary = row["summary"] as? [String:Any] ?? [:]
                let file = (row["files"] as? [[String:Any]])?.first
                let kind = row["category"] as? String ?? "text"
                return Transfer(id:row["id"] as? String ?? UUID().uuidString,type:kind,
                    title: row["type"] as? String == "text" ? row["text"] as? String ?? "文字" : summary["preview"] as? String ?? "文件",
                    detail: (summary["kind"] as? String ?? "文字") + " · " + (summary["info"] as? String ?? ""),
                    time:Date(timeIntervalSince1970:row["ts"] as? Double ?? 0),filePath:file?["path"] as? String)
            }
            transfers = loadMore ? transfers + items : items
            total = result["total"] as? Int ?? 0; more = result["has_more"] as? Bool ?? false
        } catch { report(error.localizedDescription) }
    }
    func search() {
        historyTask?.cancel()
        historyTask = Task { try? await Task.sleep(for:.milliseconds(250)); if !Task.isCancelled { await loadHistory() } }
    }
    func copyConnection() {
        guard !connectedURL.isEmpty else { return }
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(connectedURL,forType:.string)
        copied = true
        Task { try? await Task.sleep(for:.seconds(2)); copied = false }
    }
    func act(_ item:Transfer) {
        if let path = item.filePath { NSWorkspace.shared.open(URL(fileURLWithPath:path)) }
        else { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.title,forType:.string); toast("已复制到剪贴板") }
    }
    func publish(_ text:String, paths:[URL]) async -> Bool {
        do { _ = try await api("/desktop/publish",body:["text":text,"paths":paths.map(\.path)]); await loadHistory(); toast("已分享，在手机的“来自电脑”中查看"); return true }
        catch { report(error.localizedDescription); return false }
    }
    func openPublish(files: Bool = false) {
        publishFileMode = files
        showPublish = true
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first(where: { $0.canBecomeMain })?.makeKeyAndOrderFront(nil)
    }
    func importSharedFiles(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        guard urls.count + publishFiles.count + pendingImportCount <= ShareImport.maximumFiles else { report(ShareImport.Failure.tooManyFiles.localizedDescription); return }
        pendingImportCount += urls.count
        importingFiles = true
        openPublish(files: true)
        let parent = dataDirectory.appendingPathComponent("share-imports", isDirectory: true)
        Task {
            defer { pendingImportCount -= urls.count; importingFiles = pendingImportCount > 0 }
            do {
                let copied = try await Task.detached(priority: .userInitiated) {
                    let batch = try ShareImport.makeBatch(in: parent)
                    do { return try urls.map { try ShareImport.copy($0, into: batch) } }
                    catch { try? FileManager.default.removeItem(at: batch); throw error }
                }.value
                publishFiles.append(contentsOf: copied)
            } catch { report("添加文件失败：\(error.localizedDescription)") }
        }
    }
    func sendDraft() async -> Bool {
        guard online else { report("请等待本机服务启动。"); return false }
        let text = publishText.trimmingCharacters(in: .whitespacesAndNewlines)
        if publishTarget == "phone" {
            guard await publish(publishText, paths: publishFiles) else { return false }
        } else {
            var files = publishFiles
            if !text.isEmpty {
                do {
                    let batch = try ShareImport.makeBatch(in: dataDirectory.appendingPathComponent("share-imports"))
                    let file = batch.appendingPathComponent("分享文字.txt")
                    try publishText.write(to: file, atomically: true, encoding: .utf8)
                    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
                    files.append(file)
                } catch { report("无法准备文字文件，请重试。"); return false }
            }
            guard await sendToMachine(publishTarget, files: files) else { return false }
        }
        publishText = ""; publishFiles = []; publishTarget = "phone"
        return true
    }
    func saveAIKey(_ value:String) async {
        guard !value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        do { _ = try await api("/desktop/config",body:["minimax_api_key":value]); toast("润色服务已配置") }
        catch { report(error.localizedDescription) }
    }
    func toast(_ text:String) { notice = text; Task { try? await Task.sleep(for:.seconds(3)); if notice == text { notice = nil } } }
    func loadMachines() async {
        guard !preview else { return }
        do {
            let data = try await api("/desktop/peers")
            machines = (data["peers"] as? [[String: Any]] ?? []).map { PairedMachine(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "Mac", endpoint: $0["endpoint"] as? String ?? "") }
            machineJobs = (data["jobs"] as? [[String: Any]] ?? []).map {
                MachineJob(id: $0["id"] as? String ?? "", peer: $0["peer_name"] as? String ?? "Mac", name: $0["name"] as? String ?? "文件", status: $0["status"] as? String ?? "", direction: $0["direction"] as? String ?? "send", sent: $0["sent"] as? Double ?? 0, total: $0["total"] as? Double ?? 0, error: $0["error"] as? String ?? "")
            }
        } catch { report(error.localizedDescription) }
    }
    func createInvitation() async {
        guard online else { report("请等待本机服务启动。"); return }
        guard tunnelPhase == "ready" else { report("请先在连接页选择一种方式并等待就绪。"); return }
        do {
            let data = try await api("/desktop/peers/invite", body: [:])
            invitation = data["invitation"] as? String ?? ""
            showInvitation = true
        } catch { report(error.localizedDescription) }
    }
    func joinMachine(_ link: String) async -> Bool {
        do { _ = try await api("/desktop/peers/join", body: ["invitation": link]); await loadMachines(); toast("机器已配对，可以互传文件"); return true }
        catch { report(error.localizedDescription); return false }
    }
    func removeMachine(_ id: String) async {
        do { _ = try await api("/desktop/peers/remove", body: ["id": id]); await loadMachines() }
        catch { report(error.localizedDescription) }
    }
    @discardableResult func sendToMachine(_ id: String, files: [URL]) async -> Bool {
        guard !files.isEmpty else { return false }
        do {
            let data = try await api("/desktop/peers/send", body: ["id": id, "paths": files.map(\.path)])
            if let job = data["job_id"] as? String { retryFiles[job] = (id, files) }
            await loadMachines(); toast("传输已开始"); selected = "machines"
            return true
        } catch { report(error.localizedDescription); return false }
    }
    func retryMachineJob(_ id: String) async {
        if let (peer, files) = retryFiles[id] { await sendToMachine(peer, files: files) }
        else { report("请重新选择要发送的文件。"); return }
    }
    func openReceived() {
        let folder = dataDirectory.appendingPathComponent("received")
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        NSWorkspace.shared.open(folder)
    }
    func shutdown() { timer?.invalidate(); nativeInput?.stop(); if let process, process.isRunning { process.terminate(); process.waitUntilExit() } }
}

struct Card<Content:View>:View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ViewState private var hovering = false
    var padding:CGFloat = 24
    @ViewBuilder var content:Content
    var body:some View { content.padding(padding).frame(maxWidth:.infinity,alignment:.leading).background(surface,in:RoundedRectangle(cornerRadius:24,style:.continuous)).overlay(RoundedRectangle(cornerRadius:24).strokeBorder(.primary.opacity(0.035),lineWidth:1)).shadow(color:.black.opacity(hovering ? 0.045 : 0.025),radius:14,x:0,y:5).offset(y: reduceMotion ? 0 : hovering ? -2 : 0).animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: hovering).onHover { hovering = $0 } }
}
struct SymbolTile:View {
    let name:String; var color:Color = accent; var size:CGFloat = 38
    var body:some View { Image(systemName:name).font(.system(size:size*0.44,weight:.semibold)).foregroundStyle(color).frame(width:size,height:size).background(color.opacity(0.10),in:RoundedRectangle(cornerRadius:size*0.28)) }
}
struct StatusPill:View {
    let text:String; var color:Color = .green
    var body:some View { HStack(spacing:6) { Circle().fill(color).frame(width:6,height:6); Text(text).font(.system(size:11,weight:.semibold)) }.foregroundStyle(color).padding(.horizontal,10).padding(.vertical,6).background(color.opacity(0.09),in:Capsule()) }
}
struct QRCode:View {
    let value:String
    var image:NSImage? {
        let filter = CIFilter.qrCodeGenerator(); filter.message = Data(value.utf8); filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by:CGAffineTransform(scaleX:9,y:9)), let cg = CIContext().createCGImage(output,from:output.extent) else { return nil }
        return NSImage(cgImage:cg,size:NSSize(width:cg.width,height:cg.height))
    }
    var body:some View { Group { if let image { Image(nsImage:image).interpolation(.none).resizable().scaledToFit() } }.accessibilityLabel("手机连接二维码").accessibilityHidden(true) }
}

struct ConnectionView:View {
    @EnvironmentObject var model:BridgeModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:24) {
                HStack(alignment:.top) {
                    VStack(alignment:.leading,spacing:8) {
                        Text("连接你的手机").font(.system(size:30,weight:.bold,design:.rounded)).tracking(-0.7)
                        Text("想法在手机，落笔在 Mac。").font(.system(size:14)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusPill(text:model.connectionLabel,color:model.connectionColor).padding(.top,7)
                }
                CloudAccountCard()
                Card(padding:0) {
                    HStack(spacing:0) {
                        VStack(spacing:18) {
                            ZStack {
                                RoundedRectangle(cornerRadius:24).fill(Color.white).frame(width:244,height:244)
                                if !model.connectedURL.isEmpty { QRCode(value:model.connectedURL).padding(18).frame(width:244,height:244).transition(.opacity.combined(with: .scale(scale: 0.96))) }
                                else {
                                    VStack(spacing:14) {
                                        if model.tunnelPhase == "starting" || !model.online { ProgressView().controlSize(.large) }
                                        else { Image(systemName:"qrcode").font(.system(size:56,weight:.ultraLight)).foregroundStyle(Color.gray.opacity(0.35)) }
                                        Text(model.tunnelPhase == "starting" ? "正在准备连接二维码…" : "开启连接后显示二维码").font(.system(size:12)).foregroundStyle(Color.gray)
                                    }
                                }
                            }.animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.86), value: model.connectedURL).overlay(RoundedRectangle(cornerRadius:24).stroke(Color.black.opacity(0.045),lineWidth:1))
                            HStack(spacing:6) { Image(systemName:model.connectionMode == "lan" ? "wifi" : "globe"); Text(model.connectionMode == "lan" ? "同一 Wi-Fi，扫一扫" : "用手机相机扫一扫") }.font(.system(size:13,weight:.medium)).foregroundStyle(.secondary)
                            if !model.connectedURL.isEmpty {
                                HStack(spacing:18) {
                                    Button { model.copyConnection() } label: { Label(model.copied ? "已复制" : "复制连接",systemImage:model.copied ? "checkmark" : "link") }
                                    Button { Task { await model.regenerate() } } label: { Label("刷新",systemImage:"arrow.clockwise") }
                                }.buttonStyle(.borderless).font(.system(size:12,weight:.medium)).tint(accent)
                            }
                        }.padding(32).frame(maxWidth:.infinity)
                        Rectangle().fill(.primary.opacity(0.055)).frame(width:1).padding(.vertical,32)
                        VStack(alignment:.leading,spacing:18) {
                            HStack { Text("连接方式").font(.system(size:18,weight:.semibold)); Spacer(); Toggle("启用连接",isOn:Binding(get:{model.publicEnabled},set:{v in Task { await model.setPublic(v) }})).labelsHidden().toggleStyle(.switch).tint(accent).disabled(model.busy || !model.online) }
                            LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],spacing:10) {
                                ForEach(BridgeModel.modes, id: \.0) { mode in
                                    Button { Task { await model.setMode(mode.0) } } label: {
                                        VStack(alignment:.leading,spacing:10) {
                                            HStack { Image(systemName:mode.2).font(.system(size:19)); Spacer(); if model.connectionMode == mode.0 { Image(systemName:"checkmark.circle.fill").foregroundStyle(accent) } }
                                            Text(mode.1).font(.system(size:12,weight:.semibold))
                                        }.foregroundStyle(model.connectionMode == mode.0 ? accent : Color.primary).padding(13).frame(maxWidth:.infinity,alignment:.leading)
                                            .background(model.connectionMode == mode.0 ? accent.opacity(0.09) : Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:14))
                                            .overlay(RoundedRectangle(cornerRadius:14).stroke(model.connectionMode == mode.0 ? accent.opacity(0.35) : .clear,lineWidth:1))
                                    }.buttonStyle(.plain).disabled(model.busy || !model.online)
                                }
                            }.animation(reduceMotion ? nil : .easeInOut(duration:0.2),value:model.connectionMode)
                            Text(model.modeDescription).font(.system(size:12)).foregroundStyle(.secondary).lineSpacing(4).frame(minHeight:40,alignment:.topLeading)
                            if model.connectionMode == "p2p" { Text(model.p2pCount > 0 ? "直连中 · 内容不经过服务器" : "扫码后建立直连 · 失败可手动切换其他方式").font(.system(size:11)).foregroundStyle(.secondary) }
                            HStack {
                                Button("导入服务器配置") { model.importServerConfig() }.buttonStyle(.borderless).font(.system(size:11)).tint(accent)
                                Spacer()
                                if model.publicEnabled && model.tunnelPhase != "ready" && model.tunnelPhase != "starting" { Button("重连") { Task { await model.setPublic(true) } }.buttonStyle(.bordered) }
                            }
                        }.padding(30).frame(maxWidth:.infinity,alignment:.leading)
                    }
                }
                if !model.allowed {
                    HStack(spacing:14) {
                        SymbolTile(name:"hand.tap",color:.orange)
                        VStack(alignment:.leading,spacing:4) { Text("开启自动粘贴").font(.system(size:13,weight:.semibold)); Text("允许辅助功能后，手机发送的内容会粘贴到当前输入框。").font(.system(size:12)).foregroundStyle(.secondary) }
                        Spacer()
                        Button("去设置") { Task { await model.requestPermission() } }.buttonStyle(.bordered).controlSize(.regular)
                    }.padding(18).background(Color.orange.opacity(0.055),in:RoundedRectangle(cornerRadius:20))
                }
                HStack(spacing:16) {
                    miniFeature("text.bubble","发送文字","写下内容，发送到手机或电脑",color:.blue) { model.openPublish() }
                    miniFeature("photo.on.rectangle","照片、文件，随手传","选择文件，或从系统分享菜单添加",color:.purple) { model.openPublish(files: true) }
                }
                HStack(spacing:6) { Image(systemName:"info.circle"); Text("每台机器拥有独立连接码。同一域名按设备编号连接，不会混发到其他电脑。") }.font(.system(size:11)).foregroundStyle(.tertiary).frame(maxWidth:.infinity)
            }.padding(32).frame(maxWidth:1000).frame(maxWidth:.infinity)
        }
    }
    func miniFeature(_ icon:String,_ title:String,_ subtitle:String,color:Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Card(padding:20) { HStack(spacing:12) { SymbolTile(name:icon,color:color); VStack(alignment:.leading,spacing:4) { Text(title).font(.system(size:13,weight:.semibold)); Text(subtitle).font(.system(size:11)).foregroundStyle(.secondary) }; Spacer(minLength:0); Image(systemName:"arrow.up.right").font(.system(size:12,weight:.semibold)).foregroundStyle(.tertiary) }.contentShape(Rectangle()) }
        }.buttonStyle(.plain).accessibilityLabel(title).help(subtitle)
    }
}

struct CloudAccountCard: View {
    @EnvironmentObject var model: BridgeModel
    @ViewState private var username = ""
    @ViewState private var password = ""
    @ViewState private var invitation = ""
    @ViewState private var registering = false
    @ViewState private var authenticated = false
    @ViewState private var qr = ""
    @ViewState private var expires = Date.distantPast
    @ViewState private var working = false
    @ViewState private var failure = ""
    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                Label("账号 · 实时语音与任务", systemImage: "person.crop.circle").font(.headline)
                if authenticated {
                    HStack(spacing: 24) {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            if context.date < expires && !qr.isEmpty {
                                QRCode(value: qr).padding(12).frame(width: 168, height: 168).background(.white, in: RoundedRectangle(cornerRadius: 16))
                            } else { Text("二维码已过期，请刷新").frame(width: 168, height: 168) }
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            Text("已登录，手机扫码即可对话").font(.subheadline.weight(.medium))
                            Text("登录保留 30 天。二维码两分钟有效、仅可使用一次，请只让自己的手机扫描。").font(.caption).foregroundStyle(.secondary)
                            Button("刷新语音二维码") { Task { await run("qr") } }.disabled(working)
                            Button("退出账号") { Task { await run("logout") } }.disabled(working)
                        }
                    }
                } else {
                    HStack(spacing: 24) {
                        QRCode(value: "https://test.xjiaoai.com/shengjian/api/v2/console").padding(12).frame(width: 168, height: 168).background(.white, in: RoundedRectangle(cornerRadius: 16))
                        VStack(alignment: .leading, spacing: 10) {
                            Text("手机扫码，直接测试实时对话").font(.subheadline.weight(.medium))
                            Text("手机已登录即可直接使用。也可在下方登录电脑，生成免登录二维码。下次打开自动复用登录态。").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    TextField("用户名", text: $username).textContentType(.username)
                    SecureField("密码（至少 12 位）", text: $password).textContentType(.password)
                    if registering { TextField("注册码 / 邀请码", text: $invitation) }
                    HStack {
                        Button(registering ? "注册并登录" : "登录") { Task { await run(registering ? "register" : "login") } }.buttonStyle(.borderedProminent).disabled(working || username.isEmpty || password.isEmpty)
                        Button(registering ? "已有账号" : "使用注册码注册") { registering.toggle() }.disabled(working)
                    }
                }
                if working { ProgressView().controlSize(.small) }
                if !failure.isEmpty { Text(failure).font(.caption).foregroundStyle(.red) }
            }.textFieldStyle(.roundedBorder)
        }.task { if model.online && !model.preview { await run("status") } }
         .onChange(of: model.online) { _, online in if online { Task { await run("status") } } }
    }
    private func run(_ action: String) async {
        guard !working else { return }
        working = true; failure = ""; defer { working = false }
        do {
            let result: [String: Any]
            if action == "status" { result = try await model.api("/desktop/account") }
            else { result = try await model.api("/desktop/account/"+action, body: action == "login" || action == "register" ? ["username": username, "password": password, "invite": invitation] : [:]) }
            if action == "login" || action == "register" { password = ""; invitation = "" }
            authenticated = result["authenticated"] as? Bool ?? false
            if authenticated {
                let ticket = action == "qr" ? result : try await model.api("/desktop/account/qr", body: [:])
                qr = ticket["url"] as? String ?? ""
                expires = Date(timeIntervalSince1970: ticket["expires_at"] as? Double ?? 0)
            } else { qr = "" }
        } catch { failure = error.localizedDescription }
    }
}

struct HistoryView:View {
    @EnvironmentObject var model:BridgeModel
    var body:some View {
        VStack(alignment:.leading,spacing:22) {
            HStack { VStack(alignment:.leading,spacing:7) { Text("传输记录").font(.system(size:30,weight:.bold,design:.rounded)); Text("每一次传递，都好好收着。").font(.system(size:14)).foregroundStyle(.secondary) }; Spacer(); Button { model.openPublish() } label:{ Label("分享内容",systemImage:"square.and.arrow.up") }.buttonStyle(.borderedProminent).tint(accent).controlSize(.large) }
            HStack(spacing:14) {
                HStack { Image(systemName:"magnifyingglass").foregroundStyle(.tertiary); TextField("搜索文字、文件名…",text:$model.query).textFieldStyle(.plain).onChange(of:model.query) { _,_ in model.search() }; if !model.query.isEmpty { Button { model.query = "" } label:{ Image(systemName:"xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.tertiary) } }.padding(11).background(surface,in:RoundedRectangle(cornerRadius:12))
                Picker("类型",selection:$model.category) { Text("全部").tag("all"); Text("文字").tag("text"); Text("图片").tag("image"); Text("文件").tag("file") }.pickerStyle(.segmented).frame(width:260).onChange(of:model.category) { _,_ in Task { await model.loadHistory() } }
            }
            if model.transfers.isEmpty {
                Spacer(); VStack(spacing:14) { Image(systemName:"tray").font(.system(size:48,weight:.ultraLight)).foregroundStyle(.tertiary); Text(model.query.isEmpty ? "等一条来自手机的消息" : "没有找到相关记录").font(.system(size:17,weight:.semibold)); Text("发送过的文字和文件，会出现在这里。").font(.system(size:13)).foregroundStyle(.secondary) }.frame(maxWidth:.infinity); Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing:10) {
                        ForEach(model.transfers) { item in
                            Button { model.act(item) } label: {
                                HStack(spacing:16) {
                                    SymbolTile(name:item.icon,color:item.tint,size:44)
                                    VStack(alignment:.leading,spacing:7) { Text(item.title).font(.system(size:14,weight:.medium)).lineLimit(2).multilineTextAlignment(.leading).foregroundStyle(.primary); Text(item.detail).font(.system(size:11)).foregroundStyle(.secondary) }
                                    Spacer()
                                    VStack(alignment:.trailing,spacing:8) { Text(item.time,style:.relative).font(.system(size:11)).foregroundStyle(.tertiary); Image(systemName:item.filePath == nil ? "doc.on.doc" : "arrow.up.right").font(.system(size:12)).foregroundStyle(accent) }
                                }.padding(18).background(surface,in:RoundedRectangle(cornerRadius:18))
                            }.buttonStyle(.plain)
                        }
                        if model.more { Button("加载更多") { Task { await model.loadHistory(more:true) } }.buttonStyle(.borderless).padding() }
                    }
                }
            }
            Text("\(model.total) 条记录 · 保存在这台 Mac").font(.system(size:11)).foregroundStyle(.tertiary)
        }.padding(32).task { await model.loadHistory() }
    }
}

struct SettingsView:View {
    @EnvironmentObject var model:BridgeModel
    @ViewState private var aiKey = ""
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:24) {
                Text("设置").font(.system(size:30,weight:.bold,design:.rounded))
                Card {
                    VStack(spacing:18) {
                        HStack { SymbolTile(name:"globe",size:36); VStack(alignment:.leading,spacing:4) { Text(model.modeTitle).font(.system(size:14,weight:.semibold)); Text("在连接页切换四种方式").font(.system(size:12)).foregroundStyle(.secondary) }; Spacer(); Toggle("公网",isOn:Binding(get:{model.publicEnabled},set:{ value in Task { await model.setPublic(value) } })).labelsHidden().toggleStyle(.switch).tint(accent).disabled(model.busy) }
                        Divider()
                        settingsRow("lock.shield","辅助功能",model.allowed ? "已授权" : "自动粘贴需要授权",color:.green) { Task { await model.requestPermission() } }
                        Divider()
                        settingsRow("wifi","本地网络权限","连接同一 Wi-Fi 时使用",color:.purple) { NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork")!) }
                    }
                }
                Text("智能润色").font(.system(size:12,weight:.medium)).foregroundStyle(.secondary).padding(.leading,8)
                Card {
                    VStack(alignment:.leading,spacing:15) {
                        HStack { SymbolTile(name:"sparkles",color:.purple); VStack(alignment:.leading,spacing:4) { Text("MiniMax").font(.system(size:14,weight:.semibold)); Text("在手机上润色和整理表达").font(.system(size:12)).foregroundStyle(.secondary) }; Spacer() }
                        HStack { SecureField("输入你的 API Key",text:$aiKey).textFieldStyle(.roundedBorder); Button("保存") { Task { await model.saveAIKey(aiKey); aiKey = "" } }.buttonStyle(.bordered).disabled(aiKey.isEmpty) }
                        Text("仅在使用润色时发送文本到 MiniMax。密钥保存在这台 Mac。").font(.system(size:11)).foregroundStyle(.tertiary)
                    }
                }
                Text("本机存储").font(.system(size:12,weight:.medium)).foregroundStyle(.secondary).padding(.leading,8)
                Card { VStack(spacing:18) {
                    settingsRow("folder","打开数据目录","历史、文件和本机配置",color:.orange) { NSWorkspace.shared.open(model.dataDirectory) }
                    Divider()
                    settingsRow("arrow.clockwise","重新配对","刷新二维码，让旧连接失效",color:.blue) { Task { await model.regenerate() } }
                } }
                HStack { Spacer(); VStack(spacing:6) { Image(systemName:"waveform.bubble.fill").font(.system(size:24)).foregroundStyle(accent.opacity(0.7)); Text("声笺 1.4.0").font(.system(size:12,weight:.medium)); Text("想法，自在流动。").font(.system(size:11)).foregroundStyle(.tertiary) }; Spacer() }.padding(.top,8)
            }.padding(32).frame(maxWidth:780).frame(maxWidth:.infinity)
        }
    }
    func settingsRow(_ icon:String,_ title:String,_ subtitle:String,color:Color, action:@escaping()->Void) -> some View {
        Button(action:action) { HStack(spacing:12) { SymbolTile(name:icon,color:color,size:36); VStack(alignment:.leading,spacing:4) { Text(title).font(.system(size:14,weight:.medium)).foregroundStyle(.primary); Text(subtitle).font(.system(size:12)).foregroundStyle(.secondary) }; Spacer(); Image(systemName:"chevron.right").font(.system(size:11,weight:.semibold)).foregroundStyle(.tertiary) } }.buttonStyle(.plain)
    }
}

struct PublishView:View {
    @EnvironmentObject var model:BridgeModel
    @Environment(\.dismiss) var dismiss
    @ViewState private var sending = false
    @ViewState private var picker = false
    @FocusState private var textFocused: Bool
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            HStack {
                VStack(alignment:.leading,spacing:7) {
                    Text("分享内容").font(.system(size:25,weight:.bold,design:.rounded))
                    Text(model.publishFileMode ? "截屏、照片和文件，一起送过去。" : "写一句话，或放几个文件。").font(.system(size:13)).foregroundStyle(.secondary)
                }
                Spacer()
                Button { dismiss() } label:{Image(systemName:"xmark.circle.fill").font(.system(size:22)).foregroundStyle(.tertiary)}.buttonStyle(.plain).accessibilityLabel("关闭分享")
            }
            Picker("发送到", selection: $model.publishTarget) {
                Text("手机 · 来自电脑").tag("phone")
                ForEach(model.machines) { machine in Text(machine.name).tag(machine.id) }
            }.pickerStyle(.menu)
            TextEditor(text:$model.publishText).font(.system(size:15)).scrollContentBackground(.hidden).padding(12).frame(height:model.publishFileMode ? 70 : 120).background(canvas,in:RoundedRectangle(cornerRadius:16)).focused($textFocused).accessibilityLabel("分享文字")
            Button { picker = true } label:{ Label("添加文件或拖到这里",systemImage:"plus.circle").font(.system(size:13,weight:.medium)).frame(maxWidth:.infinity).padding(18).background(accent.opacity(0.04),in:RoundedRectangle(cornerRadius:16)).overlay(RoundedRectangle(cornerRadius:16).strokeBorder(accent.opacity(0.17),style:StrokeStyle(lineWidth:1,dash:[5])).allowsHitTesting(false)) }.buttonStyle(.plain).foregroundStyle(accent)
                .onDrop(of:[UTType.fileURL],isTargeted:nil) { providers in
                    for provider in providers { _ = provider.loadObject(ofClass:URL.self) { url,_ in if let url { Task { @MainActor in model.importSharedFiles([url]) } } } }; return true
                }
            if model.importingFiles { ProgressView("正在添加文件…").controlSize(.small) }
            if !model.publishFiles.isEmpty {
                ScrollView {
                    VStack(spacing:10) {
                        ForEach(model.publishFiles,id:\.self) { file in
                            HStack(spacing:12) {
                                if let image = NSImage(contentsOf:file) {
                                    Image(nsImage:image).resizable().scaledToFit().frame(width:64,height:48).background(canvas,in:RoundedRectangle(cornerRadius:8))
                                } else { Image(systemName:"doc").foregroundStyle(accent).frame(width:64,height:48) }
                                Text(file.lastPathComponent).font(.system(size:12)).lineLimit(2)
                                Spacer()
                                Button { model.publishFiles.removeAll { $0 == file } } label: { Image(systemName:"xmark.circle.fill").foregroundStyle(.tertiary) }.buttonStyle(.plain).accessibilityLabel("移除 \(file.lastPathComponent)")
                            }
                        }
                    }
                }.frame(maxHeight:180)
            }
            HStack {
                Text(model.publishTarget == "phone" ? "手机 → 文件与下载 → 来自电脑" : "发往已配对电脑；文字将作为 txt 文件发送").font(.system(size:11)).foregroundStyle(.secondary)
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button {
                    sending = true
                    Task { if await model.sendDraft() { dismiss() }; sending = false }
                } label:{ if sending { ProgressView().controlSize(.small).frame(width:58) } else { Text("发送").frame(width:58) } }
                .buttonStyle(.borderedProminent).tint(accent).disabled(sending || model.importingFiles || !model.online || (model.publishText.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && model.publishFiles.isEmpty)).keyboardShortcut(.defaultAction)
            }
        }.padding(28).frame(width:560)
         .task(id: model.online) { if model.online { await model.loadMachines() }; textFocused = !model.publishFileMode }
         .fileImporter(isPresented:$picker,allowedContentTypes:[.item],allowsMultipleSelection:true) { result in if case .success(let urls) = result { model.importSharedFiles(urls) } }
         .alert("分享提示",isPresented:Binding(get:{!model.lastError.isEmpty},set:{if !$0 {model.lastError = ""}})) { Button("知道了") { model.lastError = "" } } message:{ Text(model.lastError) }
    }
}

struct ComputerAgentView: View {
    @EnvironmentObject var model: BridgeModel
    @ViewState private var state: [String: Any] = [:]
    @ViewState private var working = false
    @ViewState private var failure = ""
    private var phase: String { state["phase"] as? String ?? "off" }
    @ViewState private var prompt = ""
    @ViewState private var reply = ""
    private var connected: Bool { state["connected"] as? Bool ?? false }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("电脑 Agent").font(.system(size: 30, weight: .bold, design: .rounded))
                Text("在手机开口，把任务交给这台 Mac。").foregroundStyle(.secondary)
                Card {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack { Label("DeepSeek Harness", systemImage: "brain.head.profile").font(.title2.bold()); Spacer(); StatusPill(text: connected ? "已连接" : ["starting": "正在启动", "installing": "正在安装", "running": "正在连接", "stopping": "正在停止", "error": "需要处理"][phase] ?? "未启用", color: connected ? .green : .secondary) }
                        Text("执行器 0.2.1-rc.2 · 模型来自 sub-buddy").font(.subheadline).foregroundStyle(.secondary)
                        if let name = state["model"] as? String, !name.isEmpty { Text(name).font(.caption).foregroundStyle(.secondary) }
                        Text("任务目录").font(.headline)
                        Text(state["workspace"] as? String ?? "~/Documents/声笺任务").font(.system(.body, design: .monospaced)).textSelection(.enabled)
                        Text("运行代码、整理和编辑文件。任务在此目录执行；需要额外权限的操作会发到手机确认。").font(.subheadline).foregroundStyle(.secondary)
                        HStack {
                            Button(phase == "off" || phase == "error" ? "启用 DeepSeek Harness" : "重新连接") { Task { await action("start") } }.buttonStyle(.borderedProminent).disabled(working || ["starting", "installing", "stopping", "running"].contains(phase))
                            Button("停止 Agent") { Task { await action("stop") } }.disabled(working || phase == "off")
                            Button("账号登录") { model.selected = "connect" }
                        }
                        Text("运行中任务：\(state["active_tasks"] as? Int ?? 0)").font(.caption).foregroundStyle(.secondary)
                        TextField("也可以在这里输入电脑任务…", text: $prompt).textFieldStyle(.roundedBorder)
                        Button("交给 Harness 执行") { Task {
                            working = true; defer { working = false }
                            do { let result = try await model.api("/desktop/agent/task", body: ["prompt": prompt]); reply = result["reply"] as? String ?? "已提交"; prompt = "" }
                            catch { failure = error.localizedDescription }
                        } }.disabled(working || !connected || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if !reply.isEmpty { Text(reply).font(.caption).foregroundStyle(.secondary) }
                        if let task = state["last_task"] as? [String: Any] {
                            Text("最近任务：" + (["running": "执行中", "succeeded": "已完成", "failed": "失败", "cancelled": "已取消", "unknown": "结果未知", "awaiting_user": "等待确认"][task["state"] as? String ?? ""] ?? "正在处理")).font(.headline)
                            if let text = task["text"] as? String { Text(String(text.prefix(1200))).font(.caption).textSelection(.enabled) }
                        }
                        if let problem = state["error"] as? String, !problem.isEmpty { Text(problem).foregroundStyle(.red) }
                        if !failure.isEmpty { Text(failure).foregroundStyle(.red) }
                    }
                }
                Card {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("手机语音这样用").font(.headline)
                        Text("点击手机上的“电脑 Agent”，再开启实时对话。也可直接说“让电脑帮我在任务目录写一份说明”。")
                        Text("“汇报进度” · “取消当前任务” · “查看电脑状态” · “继续完善刚才的文件”").foregroundStyle(.secondary)
                        Text("“停止播报”只停止声音；停止 Agent 会中断执行，未确认的操作会显示结果未知。").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }.padding(32)
        }.task {
            while !Task.isCancelled {
                if model.online && !model.preview { do { state = try await model.api("/desktop/agent") } catch { failure = error.localizedDescription } }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }
    private func action(_ command: String) async {
        working = true; failure = ""; defer { working = false }
        do { state = try await model.api("/desktop/agent/"+command, body: [:]) }
        catch { failure = error.localizedDescription }
    }
}

struct RootView:View {
    @EnvironmentObject var model:BridgeModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body:some View {
        NavigationSplitView {
            VStack(spacing:0) {
                HStack(spacing:10) { Image(systemName:"waveform.bubble.fill").font(.system(size:25,weight:.medium)).foregroundStyle(accent); VStack(alignment:.leading,spacing:3) { Text("声笺").font(.system(size:20,weight:.bold,design:.rounded)); Text("让想法自在流动").font(.system(size:10)).foregroundStyle(.secondary) }; Spacer() }.padding(.horizontal,22).padding(.top,24).padding(.bottom,24)
                List(selection:$model.selected) {
                    Label("连接设备",systemImage:"iphone.radiowaves.left.and.right").tag("connect")
                    Label("传输记录",systemImage:"clock.arrow.circlepath").tag("history")
                    Label("机器共享",systemImage:"desktopcomputer.and.arrow.down").tag("machines")
                    Label("电脑 Agent",systemImage:"brain.head.profile").tag("agent")
                    Label("设置",systemImage:"gearshape").tag("settings")
                }.listStyle(.sidebar).scrollContentBackground(.hidden)
                VStack(alignment:.leading,spacing:10) {
                    HStack(spacing:7) { Circle().fill(model.online ? .green : .orange).frame(width:6,height:6); Text(model.online ? "Mac 已就绪" : "正在启动…").font(.system(size:11,weight:.medium)) }
                    HStack(spacing:5) { Image(systemName:"lock"); Text("你的内容，只在你的设备") }.font(.system(size:10)).foregroundStyle(.tertiary)
                }.frame(maxWidth:.infinity,alignment:.leading).padding(22)
            }.navigationSplitViewColumnWidth(min:190,ideal:210,max:230)
        } detail: {
            Group {
                switch model.selected {
                case "history": HistoryView()
                case "settings": SettingsView()
                case "machines": MachinesView()
                case "agent": ComputerAgentView()
                default: ConnectionView()
                }
            }.frame(maxWidth:.infinity,maxHeight:.infinity).background(canvas)
              .toolbar { ToolbarItem(placement:.primaryAction) { Button { model.openPublish() } label:{ Label("分享",systemImage:"square.and.arrow.up") }.help("分享给手机或电脑") } }
        }.navigationTitle("").tint(accent).frame(minWidth:980,minHeight:700)
          .sheet(isPresented:$model.showPublish) { PublishView().environmentObject(model) }
          .sheet(isPresented:$model.showAddMachine) { AddMachineView().environmentObject(model) }
          .sheet(isPresented:$model.showInvitation) { MachineInvitationView().environmentObject(model) }
          .overlay(alignment:.bottom) { if let notice = model.notice { Label(notice,systemImage:"checkmark.circle.fill").font(.system(size:13,weight:.medium)).padding(.horizontal,20).padding(.vertical,13).background(.regularMaterial,in:Capsule()).padding(.bottom,22).transition(.move(edge:.bottom).combined(with:.opacity)) } }
          .animation(reduceMotion ? nil : .spring(response: 0.32, dampingFraction: 0.84), value: model.notice)
          .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: model.selected)
          .alert("连接提示",isPresented:Binding(get:{!model.lastError.isEmpty},set:{if !$0 {model.lastError = ""}})) { Button("知道了") { model.lastError = "" } } message:{ Text(model.lastError) }
    }
}

@MainActor final class AppDelegate:NSObject,NSApplicationDelegate {
    weak var model:BridgeModel?
    private var pendingFiles: [URL] = []
    func attach(_ model: BridgeModel) {
        self.model = model
        if !pendingFiles.isEmpty { let files = pendingFiles; pendingFiles = []; model.importSharedFiles(files) }
    }
    func application(_ sender: NSApplication, open urls: [URL]) {
        if let model { model.importSharedFiles(urls) }
        else { pendingFiles.append(contentsOf: urls) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows:Bool) -> Bool {
        NSApp.windows.first(where:{$0.canBecomeMain})?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true); return true
    }
    func applicationWillTerminate(_ notification:Notification) { model?.shutdown() }
    func applicationDidFinishLaunching(_ notification:Notification) {
        NSApp.activate(ignoringOtherApps:true)
        if let index = CommandLine.arguments.firstIndex(of:"--snapshot"), CommandLine.arguments.count > index+1 {
            let path = CommandLine.arguments[index+1]
            DispatchQueue.main.asyncAfter(deadline:.now()+2) {
                if let view = NSApp.windows.first(where:{$0.contentView != nil && $0.frame.width > 600})?.contentView {
                    view.layoutSubtreeIfNeeded()
                    if let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds) {
                        view.cacheDisplay(in:view.bounds,to:bitmap)
                        try? bitmap.representation(using:.png,properties:[:])?.write(to:URL(fileURLWithPath:path))
                    }
                }
                NSApp.terminate(nil)
            }
        }
    }
}

@main struct ShengjianApp:App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = BridgeModel()
    var body:some Scene {
        WindowGroup {
            RootView().environmentObject(model).onAppear { delegate.attach(model) }
        }.defaultSize(width:1120,height:780).windowStyle(.hiddenTitleBar)
         .commands { CommandGroup(replacing:.newItem) { Button("分享内容…") { model.openPublish() }.keyboardShortcut("n"); Button("显示连接") { model.selected = "connect" }.keyboardShortcut("1") }; CommandGroup(replacing:.appSettings) { Button("设置…") { model.selected = "settings" }.keyboardShortcut(",") } }
        MenuBarExtra("声笺",systemImage:"waveform.bubble.fill") {
            Button("打开声笺") { NSApp.activate(ignoringOtherApps:true); NSApp.windows.first(where:{$0.canBecomeMain})?.makeKeyAndOrderFront(nil) }
            Button("分享内容…") { model.openPublish() }
            Divider()
            Link("设备、任务与语音对话", destination: URL(string:"https://test.xjiaoai.com/shengjian/api/v2/console")!)
            Text(model.connectionLabel)
            Button(model.publicEnabled ? "关闭连接" : "开启连接") { Task { await model.setPublic(!model.publicEnabled) } }
            Divider()
            Button("退出声笺") { NSApp.terminate(nil) }.keyboardShortcut("q")
        }
    }
}

struct MachinesView: View {
    @EnvironmentObject var model: BridgeModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ViewState private var target: String?
    @ViewState private var picker = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    VStack(alignment: .leading, spacing: 8) { Text("机器共享").font(.system(size: 30, weight: .bold, design: .rounded)); Text("各自在线，彼此相连。通过隧道，把文件送到另一台机器。").font(.system(size: 13)).foregroundStyle(.secondary) }
                    Spacer()
                    Button { Task { await model.createInvitation() } } label: { Label("邀请机器", systemImage: "qrcode") }.buttonStyle(.bordered)
                    Button { model.showAddMachine = true } label: { Label("添加机器", systemImage: "plus") }.buttonStyle(.borderedProminent).tint(accent)
                }
                if model.machines.isEmpty {
                    Card { VStack(spacing: 18) { Image(systemName: "laptopcomputer.and.arrow.down").font(.system(size: 44, weight: .light)).foregroundStyle(accent); Text("让 Mac 或 Windows 加入").font(.system(size: 19, weight: .semibold)); Text("选择可达的连接方式，\n复制配对邀请到另一台机器即可。").font(.system(size: 13)).foregroundStyle(.secondary).multilineTextAlignment(.center); Button("生成一次性邀请") { Task { await model.createInvitation() } }.buttonStyle(.borderedProminent) }.frame(maxWidth: .infinity).padding(.vertical, 28) }
                }
                ForEach(model.machines) { machine in
                    Card(padding: 22) {
                        HStack(spacing: 16) {
                            SymbolTile(name: "desktopcomputer", size: 48)
                            VStack(alignment: .leading, spacing: 6) { Text(machine.name).font(.system(size: 17, weight: .semibold)); Text(URL(string: machine.endpoint)?.host ?? "已配对设备").font(.system(size: 11)).foregroundStyle(.secondary); Label("已配对 · 独立机器凭据", systemImage: "lock.shield").font(.system(size: 11)).foregroundStyle(.green) }
                            Spacer()
                            Button { target = machine.id; picker = true } label: { Label("发送文件", systemImage: "arrow.up.doc") }.buttonStyle(.borderedProminent).tint(accent)
                            Menu { Button("移除配对", role: .destructive) { Task { await model.removeMachine(machine.id) } } } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).frame(width: 24)
                        }
                    }
                }
                HStack { Text("传输任务").font(.system(size: 16, weight: .semibold)); Spacer(); Button("打开接收目录") { model.openReceived() }.buttonStyle(.borderless).font(.system(size: 12)) }
                if model.machineJobs.isEmpty { Text("收到和发出的文件会显示在这里。").font(.system(size: 12)).foregroundStyle(.secondary).padding(.vertical, 10) }
                ForEach(model.machineJobs) { job in
                    Card(padding: 20) {
                        VStack(spacing: 12) {
                            HStack {
                                SymbolTile(name: job.status == "complete" ? "checkmark" : job.status == "error" ? "exclamationmark" : job.direction == "receive" ? "arrow.down" : "arrow.up", color: job.status == "complete" ? .green : job.status == "error" ? .orange : accent)
                                VStack(alignment: .leading, spacing: 5) { Text(job.name).font(.system(size: 13, weight: .medium)); Text((job.direction == "receive" ? "来自 " : "发送至 ") + job.peer).font(.system(size: 11)).foregroundStyle(.secondary) }
                                Spacer()
                                if job.status == "complete" { Text("校验完成").font(.system(size: 11, weight: .medium)).foregroundStyle(.green) }
                                else if job.status == "error" { Button("重新发送") { Task { await model.retryMachineJob(job.id) } }.buttonStyle(.bordered) }
                                else { Text("\(Int(job.progress * 100))%").font(.system(size: 12, design: .monospaced)).contentTransition(.numericText()) }
                            }
                            if job.status != "complete" { ProgressView(value: job.progress).tint(job.status == "error" ? .orange : accent).animation(reduceMotion ? nil : .linear(duration: 0.4), value: job.sent) }
                            if !job.error.isEmpty { Text(job.error).font(.system(size: 11)).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading) }
                        }
                    }.transition(.opacity.combined(with: .move(edge: .bottom)))
                }
                Text("配对邀请 5 分钟内有效，仅可使用一次。CF 临时域名变化时会向在线的已配对机器更新地址；双方都更换地址后需重新配对。").font(.system(size: 11)).foregroundStyle(.tertiary)
            }.padding(32)
        }.task { await model.loadMachines() }
         .fileImporter(isPresented: $picker, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in if case .success(let files) = result, let target { Task { await model.sendToMachine(target, files: files) } } }
    }
}
struct AddMachineView: View {
    @EnvironmentObject var model: BridgeModel
    @Environment(\.dismiss) private var dismiss
    @ViewState private var link = ""
    @ViewState private var joining = false
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("添加另一台机器").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("在另一台机器打开声笺 → 机器共享 → 邀请机器，然后粘贴邀请。").font(.system(size: 13)).foregroundStyle(.secondary)
            TextField("shengjian://pair?…", text: $link).textFieldStyle(.roundedBorder).privacySensitive()
            HStack { Button("取消") { dismiss() }; Spacer(); if joining { ProgressView().controlSize(.small) }; Button("配对") { joining = true; Task { if await model.joinMachine(link) { dismiss() }; joining = false } }.buttonStyle(.borderedProminent).disabled(joining || link.isEmpty) }
        }.padding(28).frame(width: 510)
         .alert("连接提示", isPresented: Binding(get: { !model.lastError.isEmpty }, set: { if !$0 { model.lastError = "" } })) { Button("知道了") { model.lastError = "" } } message: { Text(model.lastError) }
    }
}
struct MachineInvitationView: View {
    @EnvironmentObject var model: BridgeModel
    @Environment(\.dismiss) private var dismiss
    @ViewState private var copied = false
    var body: some View {
        VStack(spacing: 20) {
            Text("邀请另一台机器").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("在另一台机器中选择“添加机器”，粘贴这个邀请。\n一次性邀请，5 分钟内有效。").font(.system(size: 13)).foregroundStyle(.secondary).multilineTextAlignment(.center)
            QRCode(value: model.invitation).padding(16).frame(width: 240, height: 240).background(.white, in: RoundedRectangle(cornerRadius: 20))
            Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(model.invitation, forType: .string); copied = true } label: { Label(copied ? "邀请已复制" : "复制配对邀请", systemImage: copied ? "checkmark" : "doc.on.doc") }.buttonStyle(.borderedProminent)
            Button("完成") { dismiss() }.buttonStyle(.borderless)
        }.padding(32).frame(width: 460)
    }
}
