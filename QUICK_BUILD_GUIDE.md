> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# 🚀 Quick Build Guide - NUA POS Windows Executable

## ⚡ Fast Track (5 Minutes Read)

This guide will help you build a **single Windows .exe installer** with everything bundled:
- ✅ Frontend (React UI)
- ✅ Backend (FastAPI Server)  
- ✅ Database (MongoDB)
- ✅ Node.js Runtime
- ✅ Python Runtime

**Result**: One .exe file that users can install and run completely offline!

---

## 📋 Prerequisites (One-Time Setup)

Before building, install these on your **Windows machine**:

### 1. **Node.js** (Required)
- 🔗 Download: https://nodejs.org/
- ✅ Version: 18.x or 20.x LTS
- ⚠️ Choose: "Automatically install necessary tools" during setup
- 🧪 Test: Open Command Prompt and type:
  ```bash
  node --version
  npm --version
  ```

### 2. **Python** (Required)
- 🔗 Download: https://www.python.org/downloads/
- ✅ Version: 3.9, 3.10, or 3.11
- ⚠️ **CRITICAL**: Check ☑️ "Add Python to PATH" during installation!
- 🧪 Test: Open Command Prompt and type:
  ```bash
  python --version
  pip --version
  ```

### 3. **Git** (To download the code)
- 🔗 Download: https://git-scm.com/
- ✅ Use default settings during installation
- 🧪 Test:
  ```bash
  git --version
  ```

### 4. **MongoDB Portable** (Required for bundling)
- 🔗 Download: https://www.mongodb.com/try/download/community
- ✅ Select: 
  - Platform: **Windows x64**
  - Package: **ZIP** (not MSI)
  - Version: **6.0** or higher
- 📦 Extract and prepare:
  1. Extract the downloaded ZIP file
  2. Find the `bin` folder inside
  3. Copy the entire `bin` folder
  4. Paste it to: `/app/mongodb/bin/`
  
  Your structure should look like:
  ```
  /app/
    └── mongodb/
        └── bin/
            ├── mongod.exe
            ├── mongo.exe
            └── (other .exe and .dll files)
  ```

---

## 🛠️ Build Process (Choose One Method)

### Method 1: Automated Build Script (⚡ Easiest)

1. **Download/Clone the code**
   ```bash
   git clone <your-repo-url>
   cd nua-pos
   ```

2. **Run the build script**
   - Double-click `build_windows_exe.bat`
   - OR open Command Prompt and run:
     ```bash
     build_windows_exe.bat
     ```

3. **Wait for completion**
   - Backend build: ~5-10 minutes
   - Frontend build: ~5-10 minutes
   - Electron packaging: ~10-15 minutes
   - **Total time: 20-35 minutes**

4. **Get your installer!**
   - Location: `/app/frontend/dist/`
   - Files created:
     - `NUA POS-Setup-2.0.1.exe` (Full installer)
     - `NUA POS-Portable-2.0.1.exe` (Portable version)

---

### Method 2: Manual Build (Step-by-Step)

If the automated script fails, follow these manual steps:

#### **Step 1: Build Backend Executable**

```bash
# Navigate to backend folder
cd /app/backend

# Install PyInstaller
pip install pyinstaller

# Install all dependencies
pip install -r requirements.txt

# Build the executable
python build_backend.py
```

✅ **Success Check**: File `/app/backend/dist/server.exe` should exist (~50-100 MB)

---

#### **Step 2: Prepare MongoDB** (Already done in prerequisites)

Ensure `/app/mongodb/bin/` contains `mongod.exe` and other MongoDB files.

---

#### **Step 3: Build Frontend & Create Installer**

```bash
# Navigate to frontend folder
cd /app/frontend

# Install Yarn (if not installed)
npm install -g yarn

# Use Electron package configuration
copy electron-package.json package.json

# Install all dependencies (takes 5-10 minutes)
yarn install

# Install Electron helper
yarn add electron-is-dev

# Build React app (takes 2-5 minutes)
yarn build

# Build Windows installer (takes 10-15 minutes)
yarn electron:build
```

✅ **Success Check**: Files in `/app/frontend/dist/`:
- `NUA POS-Setup-2.0.1.exe` 
- `NUA POS-Portable-2.0.1.exe`

---

## 🎯 What You Get

After successful build:

### 📦 Installer Version (`NUA POS-Setup-2.0.1.exe`)
- Size: ~200-300 MB
- Type: NSIS Windows Installer
- Features:
  - Professional installation wizard
  - Desktop and Start Menu shortcuts
  - Add/Remove Programs entry
  - Auto-start option
  - Clean uninstaller

### 💼 Portable Version (`NUA POS-Portable-2.0.1.exe`)
- Size: ~200-300 MB  
- Type: Standalone executable
- Features:
  - No installation needed
  - Run from USB drive
  - Run from any folder
  - Leave no traces on system
  - Perfect for testing

---

## 🧪 Testing Your Build

### Test Installer:
1. Navigate to `/app/frontend/dist/`
2. Double-click `NUA POS-Setup-2.0.1.exe`
3. Follow installation wizard
4. Launch from Desktop or Start Menu
5. **First launch**: Takes 10-15 seconds (services starting)
6. **Verify**: 
   - Window opens with NUA POS interface
   - Can navigate between pages
   - Can create transactions
   - Works completely offline

### Test Portable:
1. Navigate to `/app/frontend/dist/`
2. Double-click `NUA POS-Portable-2.0.1.exe`
3. App starts directly (no installation)
4. Verify same functionality as installer

---

## 🚨 Troubleshooting

### ❌ "Python not found" or "pip not found"
**Cause**: Python not in system PATH  
**Fix**:
1. Reinstall Python
2. ☑️ Check "Add Python to PATH"
3. Restart Command Prompt
4. OR manually add to PATH:
   - Right-click "This PC" → Properties
   - Advanced System Settings → Environment Variables
   - Add Python installation path to PATH

### ❌ "Node not found" or "npm not found"
**Cause**: Node.js not installed or not in PATH  
**Fix**:
1. Reinstall Node.js
2. Restart Command Prompt
3. Verify: `node --version`

### ❌ Backend build fails: "No module named 'X'"
**Cause**: Missing Python dependencies  
**Fix**:
```bash
cd /app/backend
pip install -r requirements.txt --force-reinstall
python build_backend.py
```

### ❌ Electron build fails: "Cannot find module"
**Cause**: Missing or corrupted node_modules  
**Fix**:
```bash
cd /app/frontend
rmdir /s /q node_modules
yarn install
yarn build
yarn electron:build
```

### ❌ "EPERM" or "Access Denied" errors
**Cause**: Insufficient permissions or files in use  
**Fix**:
1. Close all applications (especially IDEs)
2. Run Command Prompt as Administrator:
   - Search "cmd" → Right-click → "Run as administrator"
3. Temporarily disable antivirus
4. Try build again

### ❌ Electron build is very slow or hangs
**Cause**: electron-builder downloading tools  
**Fix**:
- Ensure stable internet connection
- Be patient (can take 15-20 minutes first time)
- Check firewall isn't blocking downloads
- Try portable build: `yarn build:portable`

### ❌ Built app doesn't start
**Cause**: Various (MongoDB, backend, permissions)  
**Fix**:
1. Run portable version first (easier to debug)
2. Check Windows Firewall settings
3. Ensure MongoDB port 27017 isn't blocked
4. Check logs in: `%APPDATA%/NUA POS/logs/`
5. Try running as Administrator

### ❌ MongoDB not found in package
**Cause**: MongoDB files not copied to correct location  
**Fix**:
1. Verify `/app/mongodb/bin/mongod.exe` exists
2. Re-extract MongoDB ZIP and copy again
3. Rebuild: `yarn electron:build`

---

## 📊 Build Size Reference

Expected file sizes:
- Backend executable: **50-100 MB**
- MongoDB portable: **150-200 MB**
- Frontend build: **10-20 MB**
- **Final installer: 200-300 MB**
- **Installed size: 400-500 MB**

These sizes are normal for a complete, self-contained desktop application.

---

## 🎨 Customization (Optional)

### Change App Version
Edit `/app/frontend/electron-package.json`:
```json
"version": "2.0.1"  ← Change this
```

### Custom App Icon
1. Create a 256x256 PNG image
2. Convert to .ico using: https://convertio.co/png-ico/
3. Replace `/app/frontend/assets/icon.ico`

### Custom Installer Graphics
See `/app/frontend/assets/README.md` for details on:
- Installer header image
- Installer sidebar image
- Custom icons

---

## 💾 Distribution

You can now distribute your installer to users:

### ✅ Recommended: Installer Version
- Professional installation experience
- Adds to Windows programs
- Creates shortcuts automatically
- Users can easily uninstall

### ✅ Alternative: Portable Version  
- No installation needed
- Great for testing
- Can run from USB
- Useful for demo purposes

### 📤 Upload Options
- Google Drive / Dropbox
- Company website
- USB drives
- Network share

**File to share**: 
- `NUA POS-Setup-2.0.1.exe` (for end users)
- `NUA POS-Portable-2.0.1.exe` (for testing/demo)

---

## ✨ What's Included

Your Windows executable includes:

✅ **Complete POS System**
- Fast, touch-optimized checkout
- Product management with variants
- Customer profiles and loyalty
- Inventory tracking
- Staff management with roles
- Multi-location support

✅ **Advanced Features**
- Offline capability (works without internet)
- Receipt printing (network/USB printers)
- EFTPOS integration
- Promotions and discounts
- Gift cards
- Split payments
- Detailed reporting

✅ **Self-Contained**
- Built-in database (MongoDB)
- Built-in backend server (FastAPI)
- No external dependencies
- No internet required
- Works on any Windows PC

---

## 📞 Need Help?

If you encounter issues not covered here:

1. ✅ Re-read Prerequisites section (most issues are here)
2. ✅ Check Troubleshooting section
3. ✅ Ensure you have stable internet during build
4. ✅ Try running Command Prompt as Administrator
5. ✅ Make sure antivirus isn't blocking the build
6. ✅ Verify you have 5+ GB free disk space

---

## 🎉 Success!

Once you have your `.exe` files, you're done! 

Your NUA POS is now a professional Windows application that can be:
- ✅ Installed on any Windows PC (7, 8, 10, 11)
- ✅ Distributed to customers
- ✅ Run completely offline
- ✅ Used immediately after installation

**Total build time**: 20-35 minutes  
**Result**: Professional Windows installer for your POS system!

---

**Built with ❤️ by NUA POS Team**
