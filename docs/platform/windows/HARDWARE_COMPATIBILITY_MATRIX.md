# Hardware compatibility matrix

| Capability | Implementation | Evidence | Release status |
|---|---|---|---|
| Windows mouse/keyboard | Shared React + desktop host | Shell tests; no physical QA | NOT TESTED physically |
| Windows touchscreen | 44px targets, touch mode, fullscreen | Mode smoke planned in Windows CI | NOT TESTED physically |
| Windows spooler receipt | Enumeration + user print dialog | Escaping/validation tests | NOT TESTED with printer |
| OS encrypted storage | Windows safeStorage adapter | Failure-closed tests; Windows crypto CI | Integration BLOCKED |
| USB/serial/LAN raw printer | None | None | UNSUPPORTED |
| Cash drawer/cutter | None | None | UNSUPPORTED |
| Keyboard-wedge scanner | Browser input only | No focus/duplicate-scan QA | UNVERIFIED |
| Payment terminal | None | No certified SDK/hardware | UNSUPPORTED |
| Camera/mic/biometric | Permissions denied | Host policy | UNSUPPORTED |
| Android/Apple hardware | Claude/future platform scope | No evidence on this branch | NOT TESTED |
