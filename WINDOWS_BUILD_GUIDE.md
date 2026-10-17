> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# 🔨 Windows Build Guide - NUA POS .exe

## Overview

This guide will walk you through building the NUA POS Windows executable file.

**Time Required:** 20-35 minutes (mostly automated)

**Prerequisites:**
- ✅ Code downloaded to Windows PC
- ✅ Node.js, Python, Git installed
- ✅ MongoDB prepared
- ✅ All checks pass in `check_prerequisites.py`

---

## 🎯 Two Build Methods

Choose the method that works best for you:

### Method 1: Automated Build (Recommended ⭐)
- One command does everything
- Easiest and fastest
- **Perfect for:** First-time builders

### Method 2: Manual Step-by-Step
- Full control over each step
- Better for troubleshooting
- **Perfect for:** Experienced developers

---

## ⚡ METHOD 1: Automated Build (Recommended)

### Step 1: Open Command Prompt in Project Folder

**Option A: From File Explorer**
1. Open File Explorer
2. Navigate to your project folder (e.g., `C:\Users\...\NUAPOS\`)
3. Click in the address bar
4. Type: `cmd`
5. Press Enter

**Option B: Manual**
1. Press `Windows Key + R`
2. Type: `cmd`
3. Press Enter
4. Navigate:
   ```bash
   cd C:\Users\YourName\Documents\NUAPOS
   ```

---

### Step 2: Run the Build Script

**In Command Prompt, type:**

```bash
build_windows_exe.bat
```

**Press Enter**

---

### Step 3: Watch the Build Process

The script will automatically:

**Phase 1: Check Prerequisites** (1 minute)
```
========================================
NUA POS - Windows Build Script
========================================

[1/6] Checking Node.js installation...
✓ OK: Node.js found

[2/6] Checking Python installation...
✓ OK: Python found
```

**Phase 2: Build Backend** (5-10 minutes)
```
[3/6] Building backend executable...
This may take 5-10 minutes...
Installing PyInstaller...
Building with PyInstaller...
✓ OK: Backend built successfully
```

You'll see lots of output - this is normal!

**Phase 3: Setup Frontend** (5-10 minutes)
```
[4/6] Setting up frontend...
Installing Yarn...
Installing dependencies (this may take 5-10 minutes)...
✓ OK: Frontend setup complete
```

**Phase 4: Build React App** (2-5 minutes)
```
[5/6] Building React application...
Creating optimized production build...
✓ OK: React app built successfully
```

**Phase 5: Build Electron Installer** (10-15 minutes)
```
[6/6] Building Electron installer...
This may take 10-15 minutes...
Please be patient, electron-builder downloads additional tools...

• electron-builder version=24.x.x
• loaded configuration file=package.json
• writing effective config file=dist\builder-effective-config.yaml
• packaging platform=win32 arch=x64
• building target=nsis
• building target=portable
```

**This is the longest step - be patient!**

---

### Step 4: Build Complete! 🎉

**You'll see:**
```
========================================
BUILD COMPLETE!
========================================

Your installer files are located at:
  C:\...\NUAPOS\frontend\dist\NUA POS-Setup-2.0.1.exe
  C:\...\NUAPOS\frontend\dist\NUA POS-Portable-2.0.1.exe

You can now distribute these files!

Press any key to continue...
```

**Congratulations! Your .exe file is ready!**

---

## 🛠️ METHOD 2: Manual Step-by-Step Build

Use this method if automated script fails or you want more control.

### Part 1: Build Backend Executable

#### Step 1: Navigate to Backend

```bash
cd backend
```

#### Step 2: Install PyInstaller

```bash
pip install pyinstaller
```

**Output:**
```
Collecting pyinstaller
  Downloading pyinstaller-x.x.x.tar.gz
Installing collected packages: pyinstaller
Successfully installed pyinstaller-x.x.x
```

**Time:** 1-2 minutes

---

#### Step 3: Install Backend Dependencies

```bash
pip install -r requirements.txt
```

**Output:**
```
Collecting fastapi
Collecting uvicorn
Collecting motor
Collecting pydantic
... (many more packages)
Successfully installed fastapi-x.x uvicorn-x.x ...
```

**Time:** 2-3 minutes

---

#### Step 4: Build Backend Executable

```bash
python build_backend.py
```

**What happens:**
- PyInstaller analyzes server.py
- Collects all dependencies
- Creates standalone executable
- Takes 5-10 minutes

**Expected output:**
```
Building NUA POS Backend Executable...
Running: pyinstaller --name=server --onefile ...
INFO: PyInstaller: 5.x.x
INFO: Python: 3.x.x
INFO: Building EXE from ...
INFO: Appending PKG archive to EXE
✅ Backend executable built successfully!
Location: dist\server.exe
Size: 78.45 MB
✅ .env file copied to dist folder
```

**Verify:**
```bash
dir dist
```

You should see `server.exe` (50-100 MB)

---

### Part 2: Build Frontend and Package

#### Step 5: Navigate to Frontend

```bash
cd ..\frontend
```

#### Step 6: Install Yarn (if needed)

```bash
npm install -g yarn
```

**Time:** 1-2 minutes

---

#### Step 7: Use Electron Package Configuration

```bash
copy electron-package.json package.json
```

**Output:**
```
        1 file(s) copied.
```

This replaces the development package.json with the Electron build configuration.

---

#### Step 8: Install Frontend Dependencies

```bash
yarn install
```

**What happens:**
- Downloads all npm packages
- Installs React, Electron, and dependencies
- Creates node_modules folder
- Takes 5-10 minutes

**Output:**
```
yarn install v1.x.x
[1/4] Resolving packages...
[2/4] Fetching packages...
[3/4] Linking dependencies...
[4/4] Building fresh packages...
✨ Done in 300.00s
```

**⚠️ Warnings are normal - don't worry about them!**

---

#### Step 9: Install Electron Helper

```bash
yarn add electron-is-dev
```

**Output:**
```
✨ Done in 5.00s
```

---

#### Step 10: Build React Application

```bash
yarn build
```

**What happens:**
- Compiles React code
- Optimizes for production
- Creates `build` folder
- Takes 2-5 minutes

**Output:**
```
Creating an optimized production build...
Compiled successfully.

File sizes after gzip:

  150.23 KB  build\static\js\main.abc123.js
  12.45 KB   build\static\css\main.def456.css

The build folder is ready to be deployed.
```

---

#### Step 11: Build Electron Installer

**This is the final step!**

```bash
yarn electron:build
```

**What happens:**
- electron-builder packages everything
- Creates Windows installer
- Downloads additional tools (first time)
- Takes 10-15 minutes

**Output:**
```
• electron-builder  version=24.x.x
• loaded configuration  file=package.json
• writing effective config  file=dist\builder-effective-config.yaml
• packaging  platform=win32 arch=x64 electron=28.x.x
• downloading  url=https://github.com/electron/electron/releases/download/...
• downloaded  url=... duration=30s
• building  target=nsis file=dist\NUA POS-Setup-2.0.1.exe
• building  target=portable file=dist\NUA POS-Portable-2.0.1.exe
• building block map  blockMapFile=dist\NUA POS-Setup-2.0.1.exe.blockmap
```

**⚠️ This step takes the longest - be patient!**

**Common progress indicators:**
- Downloading Electron
- Downloading NSIS (installer builder)
- Compiling application
- Creating installer
- Creating portable version

---

## 📦 Build Output

### Location

After successful build:

```
frontend\dist\
├── NUA POS-Setup-2.0.1.exe          (~200-300 MB)
├── NUA POS-Portable-2.0.1.exe       (~200-300 MB)
├── NUA POS-Setup-2.0.1.exe.blockmap
├── builder-effective-config.yaml
└── win-unpacked\                        (folder)
```

---

### What's What?

**`NUA POS-Setup-2.0.1.exe`** - Full Installer
- Professional NSIS installer
- Installation wizard
- Creates Desktop shortcut
- Creates Start Menu entry
- Add/Remove Programs entry
- **Use this** for distributing to end users

**`NUA POS-Portable-2.0.1.exe`** - Portable Version
- Standalone executable
- No installation needed
- Run from anywhere
- Run from USB drive
- **Use this** for testing or demos

**`win-unpacked\`** - Unpacked Files
- Raw application files
- For debugging only
- Don't distribute this

---

## ✅ Test Your Build

### Test the Installer

1. **Navigate to:**
   ```
   C:\...\NUAPOS\frontend\dist\
   ```

2. **Double-click:** `NUA POS-Setup-2.0.1.exe`

3. **Installation Wizard:**
   - Click "Next"
   - Choose installation folder (or keep default)
   - Select "Create Desktop shortcut"
   - Click "Install"
   - Wait 30-60 seconds
   - Click "Finish"

4. **Launch the app:**
   - Double-click Desktop shortcut, OR
   - Windows Key → Search "NUA POS" → Click

5. **First Launch:**
   - Takes 10-15 seconds (services starting)
   - MongoDB starts
   - Backend starts
   - Frontend loads

6. **Verify it works:**
   - Dashboard loads
   - You can click around
   - Pages navigate
   - No error messages

**✅ If app opens and works → Build successful!**

---

### Test the Portable Version

1. **Navigate to:**
   ```
   C:\...\NUAPOS\frontend\dist\
   ```

2. **Double-click:** `NUA POS-Portable-2.0.1.exe`

3. **Direct Launch:**
   - No installation needed
   - App starts directly
   - Same 10-15 second startup time

4. **Test functionality:**
   - Create a test transaction
   - Add a product
   - Check settings
   - Verify offline capability (disconnect internet)

**✅ If everything works → Ready to distribute!**

---

## 🎉 Success! What Now?

### You Have:

- ✅ `NUA POS-Setup-2.0.1.exe` - For distribution
- ✅ `NUA POS-Portable-2.0.1.exe` - For testing/demos
- ✅ Fully tested application
- ✅ Ready to share with users!

---

### Distribution Options:

**1. Upload to Cloud Storage**
- Google Drive
- Dropbox
- OneDrive
- Share link with users

**2. Company Website**
- Upload to downloads section
- Create download page

**3. Email**
- If file size permits (< 25 MB with compression)
- Consider using file transfer services

**4. USB Drives**
- Copy .exe to USB
- Hand deliver to users

**5. Network Share**
- Place on company file server
- Users download internally

---

### User Installation:

**What users need to do:**

1. Download `NUA POS-Setup-2.0.1.exe`
2. Double-click to run
3. Follow installation wizard
4. Launch from Desktop or Start Menu
5. Start using immediately!

**Requirements for users:**
- Windows 7/8/10/11 (64-bit)
- 500 MB disk space
- 2 GB RAM (minimum)
- **No other software needed!**

---

## 🚨 Troubleshooting

### Build Script Fails

**"Python not found"**
```bash
# Verify Python installation
python --version

# If fails, reinstall Python with "Add to PATH"
```

**"Node not found"**
```bash
# Verify Node installation
node --version

# If fails, reinstall Node.js
```

**"MongoDB not found in package"**
```bash
# Verify MongoDB exists
dir mongodb\bin\mongod.exe

# If missing, re-download and extract MongoDB
```

---

### Backend Build Fails

**"No module named X"**
```bash
# Reinstall dependencies
cd backend
pip install -r requirements.txt --force-reinstall
python build_backend.py
```

**"PyInstaller failed"**
```bash
# Reinstall PyInstaller
pip uninstall pyinstaller
pip install pyinstaller
python build_backend.py
```

**"Permission denied"**
```bash
# Run Command Prompt as Administrator
# Right-click Command Prompt → "Run as administrator"
```

---

### Frontend Build Fails

**"Cannot find module"**
```bash
# Delete node_modules and reinstall
cd frontend
rmdir /s /q node_modules
yarn install
yarn build
```

**"Out of memory"**
```bash
# Increase Node memory limit
set NODE_OPTIONS=--max_old_space_size=4096
yarn build
```

**"EPERM or EACCES errors"**
```bash
# Close all programs (especially VS Code, editors)
# Run as Administrator
# Disable antivirus temporarily
```

---

### Electron Build Fails

**"electron-builder command not found"**
```bash
# Install electron-builder
cd frontend
yarn add electron-builder --dev
yarn electron:build
```

**"Download failed"**
```bash
# Check internet connection
# Check firewall/antivirus
# Try again - sometimes servers are busy
```

**"Build takes forever"**
```bash
# First build is slow (downloads tools)
# Wait patiently - can take 15-20 minutes
# Future builds will be faster
```

**"Windows Defender blocking"**
- Windows Defender may flag build
- Click "More info" → "Run anyway"
- Or temporarily disable Defender during build

---

### App Won't Start After Building

**"App opens then closes immediately"**

Check logs:
```
C:\Users\YourName\AppData\Roaming\NUA POS\logs\
```

Common causes:
1. MongoDB port 27017 blocked by firewall
2. Backend executable missing
3. MongoDB files corrupted

**Fix:**
1. Run portable version (easier to debug)
2. Check Windows Firewall
3. Try running as Administrator
4. Rebuild backend: `python backend\build_backend.py`

---

## 💡 Pro Tips

### Reduce Build Time

**After first build, subsequent builds are faster:**
- node_modules already installed
- Electron already downloaded
- PyInstaller cached

**Typical times:**
- First build: 30-35 minutes
- Second build: 15-20 minutes
- Third+ build: 10-15 minutes

---

### Build Size Optimization

**Current size: ~250-300 MB**

To reduce (optional):
1. Remove unused dependencies
2. Optimize images
3. Enable compression in electron-builder
4. Remove dev dependencies

**But honestly, 250-300 MB is reasonable for a complete POS system!**

---

### Version Control

**For future versions:**

1. Edit version in `frontend\electron-package.json`:
   ```json
   "version": "2.0.2"  // Change this
   ```

2. Rebuild:
   ```bash
   yarn electron:build
   ```

3. New filename:
   ```
   NUA POS-Setup-2.0.2.exe
   ```

---

### Backup Your Build

**After successful build, backup:**

1. Copy entire `dist` folder
2. Save to external drive or cloud
3. You can redistribute this anytime
4. No need to rebuild unless code changes

---

### Auto-Updates (Future)

**Currently:**
- Users download new .exe for updates
- Reinstall to upgrade

**Future enhancement:**
- Add electron-updater
- Auto-check for updates
- One-click updates from within app

---

## 📊 Build Timeline

**Complete build from scratch:**

```
Prerequisites Check        1 min
Backend Build           5-10 min
Frontend Dependencies   5-10 min
React Build            2-5 min
Electron Package      10-15 min
Testing               5-10 min
━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL                 28-51 min
```

**Most time is spent waiting - the build is automated!**

---

## 🎓 Understanding the Build

### What Gets Bundled?

**Frontend:**
- React application
- All JavaScript libraries
- CSS and assets
- UI components

**Backend:**
- Python interpreter
- FastAPI server
- All Python packages
- Business logic

**Database:**
- MongoDB binaries
- Database engine
- No data (fresh install)

**Runtimes:**
- Node.js (via Electron)
- Python (via PyInstaller)
- All dependencies

**Result:**
One .exe file with everything needed!

---

## ✨ Summary

**What you accomplished:**

1. ✅ Built backend executable (Python → .exe)
2. ✅ Built React frontend (production build)
3. ✅ Packaged everything with Electron
4. ✅ Created Windows installer
5. ✅ Created portable version
6. ✅ Tested the build
7. ✅ Ready to distribute!

**You now have:**
- Professional Windows installer
- Portable standalone version
- Complete offline POS system
- Ready for distribution!

---

## 🎯 Next Steps

### Immediate:
1. ✅ Test thoroughly on clean Windows PC
2. ✅ Share with test users
3. ✅ Gather feedback

### Short-term:
1. Create user documentation
2. Set up distribution method
3. Plan support process

### Long-term:
1. Plan updates and maintenance
2. Consider auto-update feature
3. Expand to other platforms (macOS, Linux)

---

**🎉 Congratulations! You've successfully built NUA POS Windows executable!**

**Your .exe file is ready to change the way businesses operate! 🚀**

---

## 📞 Need Help?

**If you encounter issues:**

1. ✅ Re-read relevant troubleshooting section
2. ✅ Check `check_prerequisites.py` output
3. ✅ Verify all installations are current
4. ✅ Try manual build method if automated fails
5. ✅ Check logs in build directories
6. ✅ Ensure antivirus isn't blocking build

**Most issues are resolved by:**
- Reinstalling prerequisites
- Running as Administrator
- Checking internet connection
- Being patient (builds take time!)

---

**You did it! 🎊**
