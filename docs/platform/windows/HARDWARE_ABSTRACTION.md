# Hardware boundary

`contracts.d.ts` defines capability availability and receipt/native storage shapes. Native bridge supports printer enumeration and structured receipt dialog submission only. Receipt text is bounded and escaped. Submission means accepted by the spooler, not paper delivery; unknown outcomes need operator reconciliation, never automatic duplicate printing.

Keyboard-wedge scanners may type into normal fields, but barcode focus/suffix/duplicate scans need physical tests. Serial/USB/Bluetooth/LAN commands and cash-drawer pulses are unsupported, not simulated success. Do not POST HTTP to TCP 9100. Future adapters need device allowlists, bounded payloads, user authorization and vendor tests. Camera/microphone/notifications/biometrics are denied in this phase until explicit permission UX exists. Network online status is only a hint; request outcomes decide retry.
