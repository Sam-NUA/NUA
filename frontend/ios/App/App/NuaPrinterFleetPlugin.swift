import Foundation
import Capacitor
import Network
import CoreBluetooth

// iPadOS: raw Wi-Fi ESC/POS and vendor-configured BLE GATT write characteristic.
// Generic Bluetooth Classic SPP and direct USB bulk are not available through
// public iOS APIs; those printers require an MFi/vendor SDK or AirPrint.
@objc(NuaPrinterFleetPlugin)
public class NuaPrinterFleetPlugin: CAPPlugin, CAPBridgedPlugin, CBCentralManagerDelegate, CBPeripheralDelegate {
    public let identifier = "NuaPrinterFleetPlugin"
    public let jsName = "NuaPrinterFleet"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "listDevices", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "scanBle", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "send", returnType: CAPPluginReturnPromise)
    ]

    private var central: CBCentralManager?
    private var scanning: CAPPluginCall?
    private var discoveries: [[String: String]] = []
    private var writes: [UUID: BleJob] = [:]

    private class BleJob {
        let call: CAPPluginCall
        let peripheral: CBPeripheral
        let service: CBUUID
        let characteristic: CBUUID
        let bytes: Data
        var offset = 0
        var characteristicHandle: CBCharacteristic?
        init(_ call: CAPPluginCall, _ peripheral: CBPeripheral, _ service: CBUUID,
             _ characteristic: CBUUID, _ bytes: Data) {
            self.call = call
            self.peripheral = peripheral
            self.service = service
            self.characteristic = characteristic
            self.bytes = bytes
        }
    }

    private func validPrivateIP(_ ip: String) -> Bool {
        let pieces = ip.split(separator: ".", omittingEmptySubsequences: false)
        guard pieces.count == 4 else { return false }
        let bytes = pieces.compactMap { UInt8($0) }
        guard bytes.count == 4 else { return false }
        return bytes[0] == 10 ||
            (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
            (bytes[0] == 192 && bytes[1] == 168) ||
            (bytes[0] == 169 && bytes[1] == 254)
    }

    @objc public func listDevices(_ call: CAPPluginCall) {
        // iOS cannot list paired Classic SPP or attached generic USB devices.
        // BLE devices are discovered with an explicit vendor service UUID.
        call.resolve(["devices": []])
    }

    private func getCentral() -> CBCentralManager {
        if let c = central { return c }
        let c = CBCentralManager(delegate: self, queue: DispatchQueue.main)
        central = c
        return c
    }

    @objc public func scanBle(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            let service = call.getString("serviceUUID") ?? ""
            guard !service.isEmpty else { call.reject("Enter the printer's BLE GATT service UUID"); return }
            guard let uuid = UUID(uuidString: service) ?? self.shortUUID(service) else {
                call.reject("Invalid BLE service UUID"); return
            }
            let cb = self.getCentral()
            guard cb.state == .poweredOn else {
                call.reject("Bluetooth not ready; enable it and retry"); return
            }
            guard self.scanning == nil else { call.reject("Scan already in progress"); return }
            self.discoveries = []
            self.scanning = call
            cb.scanForPeripherals(withServices: [CBUUID(nsuuid: uuid)], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
            DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
                guard self.scanning === call else { return }
                cb.stopScan()
                self.scanning = nil
                call.resolve(["devices": self.discoveries])
            }
        }
    }

    private func shortUUID(_ text: String) -> UUID? {
        // Standard Bluetooth short service UUID -> base UUID
        guard text.range(of: "^[0-9A-Fa-f]{4,8}$", options: .regularExpression) != nil else { return nil }
        let prefix = String(repeating: "0", count: 8 - text.count) + text
        return UUID(uuidString: "\(prefix)-0000-1000-8000-00805F9B34FB")
    }

    @objc public func send(_ call: CAPPluginCall) {
        guard let base64 = call.getString("payload"), let bytes = Data(base64Encoded: base64),
              !bytes.isEmpty && bytes.count <= 262144 else {
            call.reject("Invalid ESC/POS payload"); return
        }
        switch call.getString("transport") ?? "" {
        case "wifi":
            guard let host = call.getString("host"), validPrivateIP(host),
                  let port = call.getInt("port"), port >= 1 && port <= 65535,
                  let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
                call.reject("Enter a valid private-LAN printer IP and TCP port"); return
            }
            let conn = NWConnection(host: NWEndpoint.Host(host), port: endpointPort, using: .tcp)
            let queue = DispatchQueue(label: "com.nua.pos.printer.tcp.\(UUID().uuidString)")
            var completed = false
            func finish(_ error: String?) {
                if completed { return }
                completed = true
                conn.cancel()
                if let error = error { call.reject("Printer submission uncertain: " + error) }
                else { call.resolve(["status": "submitted", "bytes": bytes.count]) }
            }
            conn.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    conn.send(content: bytes, completion: .contentProcessed { error in
                        finish(error?.localizedDescription)
                    })
                case .failed(let error): finish(error.localizedDescription)
                case .cancelled: break
                default: break
                }
            }
            conn.start(queue: queue)
            queue.asyncAfter(deadline: .now() + 8) { finish("TCP timeout") }
        case "ble":
            DispatchQueue.main.async {
                guard let identifier = UUID(uuidString: call.getString("address") ?? ""),
                      let service = self.cbUUID(call.getString("serviceUUID")),
                      let characteristic = self.cbUUID(call.getString("characteristicUUID")) else {
                    call.reject("BLE printer ID, GATT service and writable characteristic UUID are required"); return
                }
                let cb = self.getCentral()
                guard cb.state == .poweredOn else { call.reject("Bluetooth unavailable"); return }
                guard self.writes[identifier] == nil else { call.reject("Printer already has a pending job"); return }
                guard let device = cb.retrievePeripherals(withIdentifiers: [identifier]).first else {
                    call.reject("Discover this BLE printer first using the vendor service UUID"); return
                }
                let job = BleJob(call, device, service, characteristic, bytes)
                self.writes[identifier] = job
                device.delegate = self
                cb.connect(device, options: nil)
                DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
                    if self.writes[identifier] === job { self.finishBle(identifier, "BLE acknowledgement timeout") }
                }
            }
        default: call.reject("iOS supports private Wi-Fi TCP and compatible BLE GATT. Generic USB/Classic SPP requires vendor drivers.")
        }
    }

    private func cbUUID(_ text: String?) -> CBUUID? {
        guard let text = text, !text.isEmpty,
              let uuid = UUID(uuidString: text) ?? shortUUID(text) else { return nil }
        return CBUUID(nsuuid: uuid)
    }

    private func finishBle(_ id: UUID, _ error: String?) {
        guard let job = writes.removeValue(forKey: id) else { return }
        central?.cancelPeripheralConnection(job.peripheral)
        if let error = error { job.call.reject("BLE submission uncertain: " + error) }
        else { job.call.resolve(["status": "submitted", "bytes": job.bytes.count]) }
    }

    private func sendNext(_ job: BleJob) {
        guard let characteristic = job.characteristicHandle else { finishBle(job.peripheral.identifier, "Characteristic not found"); return }
        if job.offset >= job.bytes.count { finishBle(job.peripheral.identifier, nil); return }
        let mtu = max(1, job.peripheral.maximumWriteValueLength(for: .withResponse))
        let end = min(job.bytes.count, job.offset + mtu)
        let segment = job.bytes.subdata(in: job.offset..<end)
        job.offset = end
        job.peripheral.writeValue(segment, for: characteristic, type: .withResponse)
    }

    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state != .poweredOn, let scan = scanning {
            scanning = nil
            scan.reject("Bluetooth switched off during scan")
        }
    }
    public func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                               advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard scanning != nil else { return }
        if discoveries.contains(where: { $0["address"] == peripheral.identifier.uuidString }) { return }
        discoveries.append(["transport": "ble", "address": peripheral.identifier.uuidString,
                            "name": peripheral.name ?? "BLE thermal printer"])
    }
    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard let job = writes[peripheral.identifier] else { return }
        peripheral.discoverServices([job.service])
    }
    public func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        finishBle(peripheral.identifier, error?.localizedDescription ?? "Could not connect")
    }
    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let job = writes[peripheral.identifier], error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == job.service }) else {
            finishBle(peripheral.identifier, error?.localizedDescription ?? "BLE printer service not found")
            return
        }
        peripheral.discoverCharacteristics([job.characteristic], for: service)
    }
    public func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let job = writes[peripheral.identifier], error == nil,
              let characteristic = service.characteristics?.first(where: { $0.uuid == job.characteristic }),
              characteristic.properties.contains(.write) else {
            finishBle(peripheral.identifier, error?.localizedDescription ?? "BLE characteristic does not support write-with-response")
            return
        }
        job.characteristicHandle = characteristic
        sendNext(job)
    }
    public func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let job = writes[peripheral.identifier] else { return }
        if let error = error { finishBle(peripheral.identifier, error.localizedDescription) }
        else { sendNext(job) }
    }
}
