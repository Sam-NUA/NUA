package com.nua.pos;

import android.Manifest;
import android.app.PendingIntent;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothSocket;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;
import android.hardware.usb.UsbConstants;
import android.os.Build;
import android.util.Base64;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Direct ESC/POS transports. Raw bytes, not HTTP to printers.
 *
 * Each send executes on a separate I/O worker. JS serializes a printer's
 * jobs; independent Wi-Fi/USB/paired Classic Bluetooth printers can send
 * concurrently. Resolving means bytes submitted to the interface ONLY.
 */
@CapacitorPlugin(name = "NuaPrinterFleet", permissions = {
    @Permission(alias = "bluetooth", strings = {Manifest.permission.BLUETOOTH_CONNECT})
})
public class NuaPrinterFleetPlugin extends Plugin {
    private static final String USB_ACTION = "com.nua.pos.USB_PRINTER_PERMISSION";
    private static final UUID SPP = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB");
    private final ExecutorService workers = Executors.newFixedThreadPool(6);
    private final Map<String, PluginCall> pendingUsb = new ConcurrentHashMap<>();
    private BroadcastReceiver receiver;

    @Override public void load() {
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if (!USB_ACTION.equals(intent.getAction())) return;
                UsbDevice usb = (UsbDevice) intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
                String key = usb == null ? "" : usb.getDeviceName();
                PluginCall pending = pendingUsb.remove(key);
                if (pending == null) return;
                if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) {
                    JSObject result = new JSObject();
                    result.put("granted", true);
                    pending.resolve(result);
                } else pending.reject("USB permission declined; choose an attached printer and approve access");
            }
        };
        IntentFilter filter = new IntentFilter(USB_ACTION);
        if (Build.VERSION.SDK_INT >= 33) {
            getContext().registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            getContext().registerReceiver(receiver, filter);
        }
    }

    @Override protected void handleOnDestroy() {
        if (receiver != null) getContext().unregisterReceiver(receiver);
        workers.shutdownNow();
        super.handleOnDestroy();
    }

    private UsbManager usbManager() {
        return (UsbManager) getContext().getSystemService(Context.USB_SERVICE);
    }

    private boolean btPermission() {
        return Build.VERSION.SDK_INT < 31 ||
            ContextCompat.checkSelfPermission(getContext(), Manifest.permission.BLUETOOTH_CONNECT)
                == PackageManager.PERMISSION_GRANTED;
    }

    @PluginMethod public void requestBluetooth(PluginCall call) {
        if (btPermission()) {
            JSObject r = new JSObject(); r.put("granted", true); call.resolve(r); return;
        }
        requestPermissionForAlias("bluetooth", call, "bluetoothPermissionDone");
    }

    @PermissionCallback private void bluetoothPermissionDone(PluginCall call) {
        if (!btPermission()) { call.reject("Bluetooth permission was not granted"); return; }
        JSObject r = new JSObject(); r.put("granted", true); call.resolve(r);
    }

    @PluginMethod public void listDevices(PluginCall call) {
        JSArray devices = new JSArray();
        for (UsbDevice usb : usbManager().getDeviceList().values()) {
            JSObject d = new JSObject();
            d.put("transport", "usb");
            d.put("address", usb.getDeviceName());
            d.put("name", usb.getProductName() == null ? "USB printer" : usb.getProductName());
            d.put("vendorId", usb.getVendorId());
            d.put("productId", usb.getProductId());
            d.put("permitted", usbManager().hasPermission(usb));
            devices.put(d);
        }
        if (btPermission()) {
            BluetoothManager manager = (BluetoothManager) getContext().getSystemService(Context.BLUETOOTH_SERVICE);
            BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
            if (adapter != null && adapter.isEnabled()) {
                try {
                    for (BluetoothDevice bt : adapter.getBondedDevices()) {
                        JSObject d = new JSObject();
                        d.put("transport", "bluetooth");
                        d.put("address", bt.getAddress());
                        d.put("name", bt.getName() == null ? "Paired Bluetooth printer" : bt.getName());
                        d.put("permitted", true);
                        devices.put(d);
                    }
                } catch (SecurityException ignored) { }
            }
        }
        JSObject result = new JSObject(); result.put("devices", devices);
        call.resolve(result);
    }

    @PluginMethod public void requestUsb(PluginCall call) {
        String name = call.getString("address", "");
        UsbDevice usb = usbManager().getDeviceList().get(name);
        if (usb == null) { call.reject("USB printer not attached; rediscover after reconnect"); return; }
        if (usbManager().hasPermission(usb)) {
            JSObject result = new JSObject(); result.put("granted", true); call.resolve(result); return;
        }
        if (pendingUsb.putIfAbsent(name, call) != null) {
            call.reject("USB permission request is already in progress"); return;
        }
        Intent intent = new Intent(USB_ACTION).setPackage(getContext().getPackageName());
        PendingIntent pending = PendingIntent.getBroadcast(getContext(), name.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
        usbManager().requestPermission(usb, pending);
    }

    private static String privateIpv4(String host) throws Exception {
        if (host == null || !host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}"))
            throw new Exception("Use a private numeric IPv4 address for a local printer");
        String[] parts = host.split("\\.");
        int[] ip = new int[4];
        for (int i = 0; i < 4; i++) {
            ip[i] = Integer.parseInt(parts[i]);
            if (ip[i] > 255) throw new Exception("Invalid IP address");
        }
        boolean lan = ip[0] == 10 || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31) ||
            (ip[0] == 192 && ip[1] == 168) || (ip[0] == 169 && ip[1] == 254);
        if (!lan) throw new Exception("Only private/LAN printer addresses are permitted");
        return host;
    }

    @PluginMethod public void send(PluginCall call) {
        String transport = call.getString("transport", "");
        String encoded = call.getString("payload", "");
        String address = call.getString("address", "");
        String host = call.getString("host", "");
        int port = call.getInt("port", 9100);
        final byte[] bytes;
        try {
            bytes = Base64.decode(encoded, Base64.NO_WRAP);
            if (bytes.length == 0 || bytes.length > 262144) throw new Exception("Invalid print payload size");
            if (port < 1 || port > 65535) throw new Exception("Invalid printer port");
            if ("wifi".equals(transport)) privateIpv4(host);
            else if ("bluetooth".equals(transport)) {
                if (!btPermission()) throw new Exception("Approve Bluetooth permission first");
                if (address == null || !address.matches("(?i)([0-9a-f]{2}:){5}[0-9a-f]{2}"))
                    throw new Exception("Select a paired Bluetooth device");
            } else if ("usb".equals(transport)) {
                if (!usbManager().getDeviceList().containsKey(address)) throw new Exception("USB device disconnected");
            } else throw new Exception("Unsupported native printer connection");
        } catch (Exception error) { call.reject(error.getMessage()); return; }

        workers.execute(() -> {
            try {
                if ("wifi".equals(transport)) sendWifi(host, port, bytes);
                else if ("bluetooth".equals(transport)) sendBluetooth(address, bytes);
                else sendUsb(address, bytes);
                JSObject result = new JSObject();
                result.put("status", "submitted");
                result.put("bytes", bytes.length);
                call.resolve(result);
            } catch (Exception error) {
                call.reject("Printer submission uncertain: " + error.getMessage());
            }
        });
    }

    private static void sendWifi(String host, int port, byte[] bytes) throws Exception {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), 3500);
            socket.setSoTimeout(5000);
            OutputStream out = socket.getOutputStream();
            out.write(bytes);
            out.flush();
        }
    }

    private void sendBluetooth(String address, byte[] bytes) throws Exception {
        BluetoothManager manager = (BluetoothManager) getContext().getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new Exception("Bluetooth radio is disabled");
        BluetoothDevice device = adapter.getRemoteDevice(address);
        if (device.getBondState() != BluetoothDevice.BOND_BONDED)
            throw new Exception("Pair the printer in Android Settings first");
        try (BluetoothSocket socket = device.createRfcommSocketToServiceRecord(SPP)) {
            socket.connect(); // RFCOMM SPP: not BLE GATT, not every thermal printer supports it.
            socket.getOutputStream().write(bytes);
            socket.getOutputStream().flush();
        }
    }

    private void sendUsb(String address, byte[] bytes) throws Exception {
        UsbDevice device = usbManager().getDeviceList().get(address);
        if (device == null || !usbManager().hasPermission(device))
            throw new Exception("USB printer permission required");
        UsbDeviceConnection conn = usbManager().openDevice(device);
        if (conn == null) throw new Exception("Cannot open USB printer");
        try {
            for (int i = 0; i < device.getInterfaceCount(); i++) {
                UsbInterface iface = device.getInterface(i);
                UsbEndpoint out = null;
                for (int n = 0; n < iface.getEndpointCount(); n++) {
                    UsbEndpoint endpoint = iface.getEndpoint(n);
                    if (endpoint.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                        endpoint.getDirection() == UsbConstants.USB_DIR_OUT) { out = endpoint; break; }
                }
                if (out == null || !conn.claimInterface(iface, true)) continue;
                try {
                    for (int offset = 0; offset < bytes.length;) {
                        int len = Math.min(4096, bytes.length - offset);
                        // Bulk transfers must send only the intended slice.
                        int n = conn.bulkTransfer(out, bytes, offset, len, 5000);
                        if (n <= 0) throw new Exception("USB bulk transfer failed; outcome uncertain");
                        offset += n;
                    }
                    return;
                } finally { conn.releaseInterface(iface); }
            }
            throw new Exception("No writable USB bulk endpoint; vendor driver required");
        } finally { conn.close(); }
    }
}
