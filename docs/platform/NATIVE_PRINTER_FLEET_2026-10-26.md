# NUA POS — Native Printer Fleet Pilot, 26 October 2026

## Architecture & supported transports

The terminal designated as the **printer gateway** is an installed native app, signed in as an owner/manager, with Settings → Hardware → Native printer fleet explicitly enabled. It can manage 32 devices per terminal. Other tills still take orders, but do **not** print the same docket again.

- **Android:** Wi-Fi/Ethernet printer on a private IPv4 LAN using raw TCP ESC/POS (normally 9100), paired *Classic* Bluetooth thermal printer with Serial Port Profile (SPP / RFCOMM), and directly attached USB printer exposing an ESC/POS writable bulk endpoint. USB permission must be explicitly approved on device. Connecting two USB printers with identical IDs requires selecting the OS device path discovered each time.
- **Windows:** private-LAN ESC/POS TCP (normally 9100) or Windows-installed USB/Bluetooth printer drivers through the Windows spooler; silent OS spooler submission uses the exact user-selected installed printer. Install the manufacturer's Windows driver and pair/connect in Windows Settings first; generic Bluetooth Classic raw RFCOMM is **not** exposed in Electron.
- **iPad/iPhone:** private IPv4 LAN TCP and *compatible BLE GATT* thermal printers with user-supplied service and writable characteristic UUIDs. Apple does **not** expose arbitrary Classic Bluetooth SPP or USB bulk output; those require approved manufacturer/MFi integrations. Pairing a generic Bluetooth-only printer is not sufficient on iPad.

**No printer connection opens to public IPs.** Client drivers accept only private IPv4 LAN targets. USB/Bluetooth device access is explicitly permissioned. None of these transports can guarantee a ticket actually emerged from a paper printer: "submitted" means successful write/spooler callback, not paper/ink status.

## Per-device automatic delivery

When a kitchen order is queued, server prints to **each explicitly registered enabled local target** for its station, with one unique `printer_fleet_deliveries` record per (job, target). The legacy backend printer path is *not* simultaneously used for that station: it would duplicate dockets. All queued jobs are tenant-scoped.

The gateway polls for at most 12 jobs, using an atomic claim per delivery. It sends jobs serially to the **same** physical device, and concurrently to **different** devices. An uncertain write, crash, unknown transport response or missing acknowledgement **never triggers a blind automatic retry**; the record becomes `uncertain` and a manager must check the paper and explicitly choose **Review & retry**.

A gateway is **not a headless Windows service**: NUA POS must stay open, network-connected, authenticated and running for automatic local printing. For highly available 24/7 multi-location installations, a provisioned always-on signed local print agent with standby leader election remains future work.

## Setup and on-site acceptance

1. Use a dedicated test venue, latest signed/verified pilot build, staff owner/manager account. Do not use live card payments during hardware testing.
2. Attach USB printer to Android via supported USB host/OTG and approve the permission dialog; or pair Bluetooth Classic device in Android Settings before pressing Scan; or install Windows USB/Bluetooth printer drivers in Windows Settings; or put Wi-Fi printer on the same secured LAN and record its fixed IP/port.
3. Go to **Settings → Hardware → Native printer fleet**, enter each printer's separate name and station (Kitchen Printer, Bar Printer, Pizza Station, Receipt Printer or matching custom routing name), transport/endpoint, paper width and cutter. More than one printer may share a station if duplicate paper copies are intentional.
4. Save each printer, then **Test all connected printers simultaneously**. Confirm the test paper arrived *at each physical printer* and there are no cut, column width or diacritic errors. The OS saying 'submitted' is not enough.
5. Enable **Automatic station printing** on the designated gateway only. Make a fake non-financial order containing kitchen/bar items; verify each relevant printer prints exactly one docket. The backend remains the source of truth for print job routing.
6. Kill one printer and send a new test order: healthy devices should still submit; bad printer should show an uncertain delivery. Restore its connection, check for printed paper **first**, then review/retry manually.
7. Close the gateway during a print attempt. After 90 seconds, stale claims become uncertain; do **not** auto-send duplicates when the device restarts.
8. Test login/logout, tenant switch, device revocation, Windows reinstall and Android USB unplug/replug; verify no cross-business jobs are dispatched.
9. Verify no printer is accidentally targeted via both old network station settings and the new local fleet.
10. Final proof: manufacturer/model, printer firmware, connection type, host or OS device, app SHA, source sale/order ID (test only), actual paper photo, pass/fail log.

## Menu Matrix PDF and Excel verification

PR #41 (`feat/menu-import-without-api-key`) was verified green in CI (backend, frontend, Android, Windows and iOS) and merged into main on 26 October 2026 as commit `600e2aeed743cafe938f11c641777678f8b82167`.

- `.xlsx` and `.xls` with identifiable menu name headers are parsed with `openpyxl` / `xlrd` without any AI key.
- PDFs that include actual selectable embedded text can be parsed without an AI key. Formats whose price appears at the **end of each line** are best supported. A complicated multi-column layout may require manual review.
- Scanned/photographed PDFs and photo imports still need a configured AI vision provider. They cannot be represented as deterministic text extraction.
- **Review before committing** each import: headers/categories, variant modifiers, GST/tax and prices, zero-price products, duplicate names, missing item rows. Test with a real anonymised venue menu; tests alone cannot certify all menu layouts.

## Remaining blocks before general release

- Required: Android native compiler CI, Xcode Simulator/Swift compile, Windows Electron CI, backend in-process and real-Mongo transaction checks; review PR #43.
- Physical proof on at least one printer model for each desired transport; USB and Bluetooth protocols vary by vendor.
- Signed platform distribution, driver permissions, backup/recovery and operator acceptance.
- Existing credit-card/EFTPOS certification remains separate and is **not** changed here.
- Any newly discovered dependency advisory (including a new Zod alert) must be triaged without disabling CI security checks.

PR: https://github.com/Sam-NUA/NUA/pull/43
