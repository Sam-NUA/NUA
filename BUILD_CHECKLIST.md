> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# ⚡ NUA POS - Windows .EXE Build Checklist

## 📥 DOWNLOAD & INSTALL (One Time)

```
□ Node.js 18+ from nodejs.org
□ Python 3.9+ from python.org (✓ Add to PATH!)
□ Git from git-scm.com
□ MongoDB ZIP from mongodb.com (Windows x64)
```

## 📦 PREPARE MONGODB

```
1. Extract MongoDB ZIP
2. Copy bin folder to: /app/mongodb/bin/
   (Should contain mongod.exe, mongo.exe, etc.)
```

## 🛠️ BUILD COMMANDS

### Option A: One-Click Build (EASIEST)
```bash
# Just double-click this file:
build_windows_exe.bat

# OR run in Command Prompt:
cd /app
build_windows_exe.bat
```

### Option B: Manual Build
```bash
# 1. Build Backend
cd /app/backend
pip install pyinstaller
pip install -r requirements.txt
python build_backend.py

# 2. Build Frontend
cd /app/frontend
npm install -g yarn
copy electron-package.json package.json
yarn install
yarn add electron-is-dev
yarn build
yarn electron:build
```

## 📍 OUTPUT LOCATION

```
/app/frontend/dist/
├── NUA POS-Setup-2.0.1.exe      (Installer - 200-300 MB)
└── NUA POS-Portable-2.0.1.exe   (Portable - 200-300 MB)
```

## ⏱️ BUILD TIME

```
Backend:  ~5-10 min
Frontend: ~5-10 min  
Electron: ~10-15 min
━━━━━━━━━━━━━━━━━━━
TOTAL:    ~20-35 min
```

## ✅ TEST

```
1. Navigate to /app/frontend/dist/
2. Double-click NUA POS-Setup-2.0.1.exe
3. Install and launch
4. First start takes 10-15 seconds
5. Verify app opens and works offline
```

## 🚨 COMMON FIXES

```
❌ "Python not found"
   → Reinstall Python with "Add to PATH" checked

❌ "Node not found"  
   → Reinstall Node.js, restart Command Prompt

❌ Backend build fails
   → cd /app/backend
   → pip install -r requirements.txt --force-reinstall

❌ Frontend build fails
   → cd /app/frontend
   → rmdir /s /q node_modules
   → yarn install

❌ "Access Denied"
   → Run Command Prompt as Administrator
   → Disable antivirus temporarily

❌ App doesn't start
   → Run portable version first
   → Check Windows Firewall
   → Run as Administrator
```

## 📋 QUICK REFERENCE

```
Minimum Requirements:
• Windows 7/8/10/11 (x64)
• 5 GB free disk space
• Internet (for first build only)

What's Bundled:
✓ React Frontend
✓ FastAPI Backend
✓ MongoDB Database
✓ Node.js Runtime
✓ Python Runtime

Features:
✓ Works 100% offline
✓ No dependencies needed
✓ Professional installer
✓ Desktop shortcuts
✓ Complete POS system
```

## 📄 FULL GUIDES

```
Quick Start:        QUICK_BUILD_GUIDE.md
Detailed Steps:     BUILD_INSTRUCTIONS.md
Current Windows:    WINDOWS_EXE_GUIDE.md
```

## 🎯 DISTRIBUTION

```
Share this file with users:
→ NUA POS-Setup-2.0.1.exe

Size: ~200-300 MB
Includes: Everything (frontend + backend + database)
Internet: Not required after installation
```

---

**Need Help?** Read QUICK_BUILD_GUIDE.md for detailed troubleshooting.

**Ready to Build?** Run: `build_windows_exe.bat`

---
