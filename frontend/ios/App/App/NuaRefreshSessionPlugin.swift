import Capacitor
import Foundation
import Security
import WebKit

// One authoritative refresh session per API origin. No JS cookie getter and
// no fallback to either of Capacitor's asynchronously synchronized cookie jars.
@objc(NuaRefreshSessionPlugin)
public class NuaRefreshSessionPlugin: CAPPlugin, CAPBridgedPlugin, URLSessionTaskDelegate {
    public let identifier = "NuaRefreshSessionPlugin"
    public let jsName = "NuaRefreshSession"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "commit", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "refresh", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clear", returnType: CAPPluginReturnPromise)
    ]
    private let serial = DispatchQueue(label: "com.nua.pos.refresh-session")
    private var generation = 0
    private let service = "com.nua.pos.refresh-session.v1"
    private struct State: Codable {
        let value: String
        let expiresAt: Date
        let sessionId: String
    }
    private struct SessionError: Error { let message: String }

    private func origin(_ call: CAPPluginCall) throws -> URL {
        guard let raw = call.getString("url"), let parts = URLComponents(string: raw),
              let host = parts.host?.lowercased(), parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil, ["", "/"].contains(parts.path) else {
            throw SessionError(message: "A valid API origin is required")
        }
        var allowed = parts.scheme?.lowercased() == "https"
        #if DEBUG
        allowed = allowed || (parts.scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host))
        #endif
        guard allowed else { throw SessionError(message: "HTTPS API origin required") }
        var normalized = URLComponents()
        normalized.scheme = parts.scheme?.lowercased()
        normalized.host = host
        normalized.port = parts.port
        guard let url = normalized.url else { throw SessionError(message: "Invalid API origin") }
        return url
    }

    private func query(_ url: URL) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: url.absoluteString]
    }
    private func write(_ state: State, _ url: URL) throws {
        let data = try JSONEncoder().encode(state)
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query(url) as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query(url).merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw SessionError(message: "Native refresh storage unavailable (\(status))") }
    }
    private func read(_ url: URL) throws -> State? {
        var lookup = query(url)
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else {
            throw SessionError(message: "Native refresh storage unavailable (\(status))")
        }
        return try JSONDecoder().decode(State.self, from: data)
    }
    private func sessionId(_ token: String) -> String? {
        let parts = token.split(separator: ".")
        guard parts.count == 3 else { return nil }
        var payload = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        payload += String(repeating: "=", count: (4 - payload.count % 4) % 4)
        guard let data = Data(base64Encoded: payload),
              let claims = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return claims["sessionId"] as? String
    }
    private func reject(_ call: CAPPluginCall, _ error: Error) {
        call.reject((error as? SessionError)?.message ?? "Native refresh operation failed")
    }

    @objc public func commit(_ call: CAPPluginCall) {
        serial.async {
            do {
                let url = try self.origin(call)
                guard let expected = call.getString("sessionId"), !expected.isEmpty else {
                    throw SessionError(message: "Verified terminal session required")
                }
                let cookies = (HTTPCookieStorage.shared.cookies(for: url) ?? []).filter {
                    $0.name == "refresh_token" && $0.isHTTPOnly && $0.path == "/" &&
                    $0.domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased() == url.host &&
                    ($0.expiresDate ?? .distantPast) > Date() && self.sessionId($0.value) == expected &&
                    (!$0.isSecure || url.scheme == "https")
                }
                guard let cookie = cookies.first, Set(cookies.map { $0.value }).count == 1,
                      let expiry = cookie.expiresDate else {
                    throw SessionError(message: "Matching HttpOnly refresh cookie was not issued")
                }
                // The cookie came from native HTTPS login/binding. The server
                // still verifies its signature, membership and device on use.
                try self.write(State(value: cookie.value, expiresAt: expiry, sessionId: expected), url)
                self.generation += 1
                call.resolve(["committed": true])
            } catch { self.reject(call, error) }
        }
    }

    @objc public func refresh(_ call: CAPPluginCall) {
        serial.async {
            do {
                let url = try self.origin(call)
                guard let state = try self.read(url), state.expiresAt > Date() else {
                    call.resolve(["status": 401, "data": ["detail": "No durable native refresh session"]])
                    return
                }
                let epoch = self.generation
                var request = URLRequest(url: url.appendingPathComponent("api/auth/refresh"))
                request.httpMethod = "POST"
                request.timeoutInterval = 30
                request.httpShouldHandleCookies = false
                request.setValue("refresh_token=\(state.value)", forHTTPHeaderField: "Cookie")
                let config = URLSessionConfiguration.ephemeral
                config.httpCookieStorage = nil
                config.httpShouldSetCookies = false
                config.urlCache = nil
                let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
                session.dataTask(with: request) { data, response, error in
                    session.finishTasksAndInvalidate()
                    self.serial.async {
                        guard epoch == self.generation else {
                            self.reject(call, SessionError(message: "Native session changed during refresh")); return
                        }
                        if let error = error { self.reject(call, error); return }
                        guard let response = response as? HTTPURLResponse, let data = data,
                              let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                            self.reject(call, SessionError(message: "Invalid refresh response")); return
                        }
                        // This server refreshes only access, leaving its
                        // seven-day refresh grant unchanged. Never export
                        // response headers or refresh-cookie values to JS.
                        call.resolve(["status": response.statusCode, "data": body])
                    }
                }.resume()
            } catch { self.reject(call, error) }
        }
    }

    @objc public func clear(_ call: CAPPluginCall) {
        serial.async {
            do {
                let url = try self.origin(call)
                self.generation += 1
                let status = SecItemDelete(self.query(url) as CFDictionary)
                guard status == errSecSuccess || status == errSecItemNotFound else {
                    throw SessionError(message: "Native refresh deletion unavailable (\(status))")
                }
                for cookie in HTTPCookieStorage.shared.cookies(for: url) ?? [] {
                    HTTPCookieStorage.shared.deleteCookie(cookie)
                }
                DispatchQueue.main.async {
                    let store = WKWebsiteDataStore.default().httpCookieStore
                    store.getAllCookies { cookies in
                        let group = DispatchGroup()
                        for cookie in cookies where cookie.domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased() == url.host {
                            group.enter()
                            store.delete(cookie) { group.leave() }
                        }
                        group.notify(queue: .main) { call.resolve(["cleared": true]) }
                    }
                }
            } catch { self.reject(call, error) }
        }
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           willPerformHTTPRedirection response: HTTPURLResponse,
                           newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // A fixed refresh endpoint must never forward its credential elsewhere.
        completionHandler(nil)
    }
}

class NuaBridgeViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(NuaRefreshSessionPlugin())
    }
}
