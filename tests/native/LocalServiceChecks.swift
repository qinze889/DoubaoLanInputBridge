import Foundation

@main struct LocalServiceChecks {
    static func reject(_ block: () throws -> Void) {
        do { try block(); fatalError("Invalid local service identity was accepted") } catch {}
    }
    static func main() async throws {
        let instance = "0123456789abcdef0123456789abcdef", challenge = String(repeating:"0",count:32)
        var ready: [String:Any] = ["service":"shengjian.bridge","protocol":1,"port":54321,"pid":12345,"instance_id":instance]
        let identity = try LocalServiceIdentity(ready, childPID:12345)
        reject { _ = try LocalServiceIdentity(ready,childPID:999) }
        ready["port"] = 0; reject { _ = try LocalServiceIdentity(ready,childPID:12345) }; ready["port"] = 54321
        ready["service"] = "foreign"; reject { _ = try LocalServiceIdentity(ready,childPID:12345) }; ready["service"] = "shengjian.bridge"
        var health = ready
        health["ok"] = true
        health["proof"] = "fd69542ff84590e6bbfd89ba78fcf4dc530264a546d76c6a704290f15af62c0b"
        try identity.validate(health,challenge:challenge,key:"fixture-local-service-key")
        reject { try identity.validate(health,challenge:challenge,key:"wrong-key") }
        reject { try identity.validate(health,challenge:String(repeating:"1",count:32),key:"fixture-local-service-key") }
        health["instance_id"] = String(repeating:"f",count:32)
        reject { try identity.validate(health,challenge:challenge,key:"fixture-local-service-key") }
        if CommandLine.arguments.count == 3 {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent("shengjian-native-identity-"+UUID().uuidString)
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            let process = Process(), output = Pipe()
            process.executableURL = URL(fileURLWithPath:CommandLine.arguments[1])
            process.arguments = [CommandLine.arguments[2],folder.path]
            process.standardOutput = output; process.standardError = FileHandle.nullDevice
            try process.run()
            defer { process.terminate(); process.waitUntilExit(); try? FileManager.default.removeItem(at:folder) }
            var data = Data()
            while !data.contains(10),data.count < 4096 {
                let chunk = output.fileHandleForReading.availableData
                guard !chunk.isEmpty else { throw LocalServiceError.unavailable }; data.append(chunk)
            }
            let info = try JSONSerialization.jsonObject(with:data) as! [String:Any]
            let live = try LocalServiceIdentity(info,childPID:Int(process.processIdentifier))
            let session = LocalServiceSession()
            try await live.verify(session:session.session,key:"fixture-local-service-key")
            var rejected = false
            do { try await live.verify(session:session.session,key:"wrong-key") } catch { rejected = true }
            precondition(rejected)
            print("Real Python listener + native challenge verification: passed")
        }
        print("Native local identity: PID, instance, port, proof, nonce and wrong-service rejection passed")
    }
}
