# Release and updates

Foundation version 0.1.0, native bridge schema 1. Unsigned NSIS x64 review installer only; isolated app ID prevents overwriting a production install. CI downloads the pinned Electron/runtime dependencies, tests the shell on Windows, builds and uploads a seven-day artifact. It never publishes, signs, deploys or installs onto a venue.

No automatic update feed exists. Manual review-only status is reported by getInfo. Before distribution add signed manifests/installers, certificate ownership, API compatibility handshake/minimum supported version, rollback plan and verified update prompts. Defer restart while any payment outcome is unknown or queue entry unresolved. Never force reload a till mid-sale. Test Windows 10/11 and 125/150/200% scale, reconnect/restart, installer upgrade and rollback with tenant-partitioned data.

Old `frontend/electron-package.json` and old electron-build script are legacy packaging paths, excluded from this foundation. Migrate or remove them in the coordinated release PR rather than shipping two authorities.
