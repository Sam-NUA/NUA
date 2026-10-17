> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# 📦 NUA POS - Windows Executable Package

## 🎯 What You Have

This package contains everything needed to build a **standalone Windows .exe installer** for NUA POS - a complete Point of Sale system with:

- ✅ Modern React Frontend
- ✅ FastAPI Backend Server
- ✅ MongoDB Database
- ✅ Complete offline capability
- ✅ Professional Windows installer

---

## 🚀 Getting Started (3 Steps)

### Step 1: Check Prerequisites ✓
Run the checker script:
```bash
python check_prerequisites.py
```

This will verify you have:
- Node.js installed
- Python installed  
- MongoDB downloaded and ready
- Required disk space
- All necessary files

### Step 2: Build ⚡
Run the build script:
```bash
build_windows_exe.bat
```

This will:
- Build backend executable (~5-10 min)
- Build React frontend (~5-10 min)
- Package everything with Electron (~10-15 min)

### Step 3: Test & Distribute 🎉
Your installer will be at:
```
/app/frontend/dist/NUA POS-Setup-2.0.1.exe
```

Double-click to install and test!

---

## 📚 Documentation Files

This package includes multiple guides for different needs:

### 🏁 Quick Start
- **`BUILD_CHECKLIST.md`** - One-page checklist (60 seconds)
- **`check_prerequisites.py`** - Automated prerequisite checker

### 📖 Detailed Guides  
- **`QUICK_BUILD_GUIDE.md`** - Complete guide with troubleshooting
- **`BUILD_INSTRUCTIONS.md`** - Step-by-step detailed instructions
- **`WINDOWS_EXE_GUIDE.md`** - Technical details and architecture

### 🛠️ Build Scripts
- **`build_windows_exe.bat`** - Automated Windows build script
- **`backend/build_backend.py`** - Backend executable builder

### ⚙️ Configuration Files
- **`frontend/electron-package.json`** - Electron packaging config
- **`frontend/electron/main.js`** - Electron main process
- **`frontend/electron/preload.js`** - Electron preload script
- **`frontend/assets/`** - Icons and installer graphics
- **`frontend/LICENSE.txt`** - Software license

---

## 🎓 Build Methods

### Method 1: Fully Automated (Recommended)
Perfect for quick builds and non-technical users.

```bash
# One command does everything:
build_windows_exe.bat
```

**Pros:**
- Simplest method
- Automatic error handling
- Progress indicators
- One-click solution

**Time:** 20-35 minutes total

---

### Method 2: Manual Step-by-Step
For developers who want control over each step.

```bash
# Backend
cd backend
pip install pyinstaller
pip install -r requirements.txt
python build_backend.py

# Frontend
cd ../frontend
npm install -g yarn
copy electron-package.json package.json
yarn install
yarn add electron-is-dev
yarn build
yarn electron:build
```

**Pros:**
- Full control
- Better for debugging
- Understand each step
- Customize easily

**Time:** 20-35 minutes total

---

## 📦 What Gets Built

### Build Outputs:

```
/app/frontend/dist/
├── NUA POS-Setup-2.0.1.exe          [~200-300 MB]
│   • Full Windows installer
│   • NSIS-based installation wizard
│   • Creates Start Menu & Desktop shortcuts
│   • Professional install/uninstall
│   • Recommended for distribution
│
├── NUA POS-Portable-2.0.1.exe       [~200-300 MB]
│   • Standalone executable
│   • No installation required
│   • Run from any location
│   • Perfect for testing/demos
│   • Can run from USB drive
│
└── win-unpacked/
    • Unpacked application files
    • Used for debugging
    • Not for distribution
```

### What's Inside the Executable:

```
📦 NUA POS Setup.exe
 ├─ 🎨 React Frontend
 │   ├─ Dashboard
 │   ├─ POS Terminal
 │   ├─ Products Management
 │   ├─ Customer Management
 │   ├─ Inventory Tracking
 │   ├─ Accounting
 │   ├─ BAS/GST Filing
 │   └─ Settings
 │
 ├─ ⚙️ FastAPI Backend
 │   ├─ REST API Server
 │   ├─ Business Logic
 │   ├─ Data Validation
 │   └─ EFTPOS Integration
 │
 ├─ 🗄️ MongoDB Database
 │   ├─ Local data storage
 │   ├─ Transaction records
 │   ├─ Product catalog
 │   └─ Customer data
 │
 ├─ 🟢 Node.js Runtime
 │   └─ Bundled by Electron
 │
 └─ 🐍 Python Runtime
     └─ Bundled by PyInstaller
```

---

## ✅ System Requirements

### For Building (Your Machine):
- **OS:** Windows 7/8/10/11 (64-bit)
- **RAM:** 4 GB minimum, 8 GB recommended
- **Disk:** 5 GB free space
- **Internet:** Required for downloading dependencies

### For Running (User's Machine):
- **OS:** Windows 7/8/10/11 (64-bit)
- **RAM:** 2 GB minimum, 4 GB recommended
- **Disk:** 500 MB for installation
- **Internet:** NOT required (fully offline)

---

## 🎯 Build Features

### What Makes This Special:

✅ **Truly Standalone**
- No Node.js installation needed
- No Python installation needed
- No MongoDB installation needed
- Works on fresh Windows install

✅ **Professional Installer**
- NSIS-based wizard
- Custom branding
- Desktop shortcuts
- Start Menu integration
- Clean uninstaller

✅ **Portable Option**
- Run without installation
- Perfect for testing
- USB drive compatible
- Zero registry changes

✅ **Offline First**
- Embedded database
- Local backend server
- No internet dependency
- Sync when online

✅ **Production Ready**
- Error handling
- Logging system
- Auto-recovery
- Service management

---

## 🔧 Customization Options

### Change Version Number
Edit `frontend/electron-package.json`:
```json
"version": "2.0.1"  // Change here
```

### Change App Name
Edit `frontend/electron-package.json`:
```json
"productName": "NUA POS"  // Change here
```

### Custom Icon
Replace file:
```
frontend/assets/icon.ico
```
Requirements:
- Format: .ico
- Size: 256x256 pixels
- Use online converter: https://convertio.co/png-ico/

### Custom Installer Graphics
See `frontend/assets/README.md` for:
- Installer header (150x57 px)
- Installer sidebar (164x314 px)
- Custom installer/uninstaller icons

### Custom License
Edit file:
```
frontend/LICENSE.txt
```

---

## 📊 Build Timeline

Typical build process:

```
[██████░░░░░░░░] Backend compilation     (5-10 min)
[██████░░░░░░░░] Frontend build          (5-10 min)
[████████████░░] Electron packaging      (10-15 min)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total time: 20-35 minutes

Output: 2 files (~200-300 MB each)
```

---

## 🚨 Troubleshooting Quick Reference

### Top 5 Issues:

1. **"Python not found"**
   - Reinstall Python with "Add to PATH" ✓

2. **"Node not found"**
   - Reinstall Node.js, restart terminal

3. **Backend build fails**
   - Run: `pip install -r requirements.txt --force-reinstall`

4. **Electron build fails**
   - Delete `node_modules`, run `yarn install` again

5. **"Access Denied"**
   - Run Command Prompt as Administrator

**See QUICK_BUILD_GUIDE.md for detailed troubleshooting**

---

## 📦 Distribution Guide

### For End Users:
1. Upload `NUA POS-Setup-2.0.1.exe` to:
   - Google Drive / Dropbox
   - Company website
   - USB drives
   - Email (if size permits)

2. Users simply:
   - Download the .exe
   - Double-click to install
   - Launch from Desktop or Start Menu
   - Start using immediately

### For Testing/Demo:
Use `NUA POS-Portable-2.0.1.exe`:
- No installation needed
- Run from anywhere
- Perfect for demos
- Easy to share

---

## 🎨 Branding

All branding uses "NUA" theme:
- Application name: **NUA POS**
- Window title: **NUA POS**
- Installer name: **NUA POS Setup**
- Desktop shortcut: **NUA POS**

To rebrand:
1. Edit `electron-package.json` (productName, description)
2. Replace icons in `frontend/assets/`
3. Update `LICENSE.txt`
4. Rebuild with new name

---

## 🔐 Security & Privacy

### What's Stored:
- Local database (on user's machine)
- Application settings (in AppData folder)
- Transaction logs (local only)

### What's NOT Sent:
- No telemetry
- No analytics
- No cloud sync (unless configured)
- No external API calls

### Data Location:
```
C:\Users\[Username]\AppData\Roaming\NUA POS\
├── mongodb-data\      (Database files)
├── logs\              (Application logs)
└── config\            (Settings)
```

---

## 📞 Support & Help

### Documentation:
- ⚡ Quick Start: `BUILD_CHECKLIST.md`
- 📖 Full Guide: `QUICK_BUILD_GUIDE.md`
- 🛠️ Technical: `BUILD_INSTRUCTIONS.md`

### Check System:
```bash
python check_prerequisites.py
```

### Build Help:
If build fails, check:
1. Prerequisite checker output
2. Error messages in terminal
3. Troubleshooting sections in guides
4. Log files in build directories

---

## 🎉 Success Checklist

After building, verify:

- [x] Backend `/app/backend/dist/server.exe` exists
- [x] MongoDB `/app/mongodb/bin/mongod.exe` exists
- [x] Frontend `/app/frontend/dist/NUA POS-Setup-2.0.1.exe` exists
- [x] Portable `/app/frontend/dist/NUA POS-Portable-2.0.1.exe` exists

Test the build:
- [x] Installer runs and installs successfully
- [x] App launches from Desktop shortcut
- [x] Dashboard loads and displays data
- [x] Can create test transaction
- [x] All pages are accessible
- [x] Works without internet connection

---

## 🚀 Next Steps

After successful build:

1. **Test thoroughly**
   - Install on clean Windows VM
   - Test all features
   - Verify offline functionality

2. **Create user documentation**
   - Installation guide
   - User manual
   - Feature tutorials

3. **Distribute**
   - Upload to distribution platform
   - Share download link
   - Provide support channels

4. **Maintain**
   - Track user feedback
   - Plan updates
   - Version control

---

## 📈 Roadmap

Future enhancements:
- [ ] Auto-update functionality
- [ ] macOS version
- [ ] Linux version
- [ ] Cloud sync option
- [ ] Mobile companion app
- [ ] Advanced analytics

---

## 💻 Technical Details

### Technologies Used:
- **Frontend:** React 19, Tailwind CSS, Shadcn UI
- **Backend:** FastAPI, Python 3.9+
- **Database:** MongoDB 6.0+
- **Desktop:** Electron 28
- **Packaging:** PyInstaller, electron-builder

### Architecture:
```
Electron Main Process
├─ Spawns MongoDB (27017)
├─ Spawns Backend (8001)
└─ Renders Frontend (embedded)
```

### Communication:
```
User → Frontend → Backend → MongoDB
         (IPC)     (REST)    (Driver)
```

---

## 📄 License

See `LICENSE.txt` for software license details.

---

## ✨ Credits

Built with:
- React.js
- FastAPI
- MongoDB
- Electron
- PyInstaller

---

**Ready to build?** → Run `check_prerequisites.py` first!

**Need help?** → See `QUICK_BUILD_GUIDE.md`

**Quick start?** → Run `build_windows_exe.bat`

---

**🎉 Thank you for using NUA POS!**
