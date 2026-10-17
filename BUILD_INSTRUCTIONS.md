> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# NUA POS - Windows Executable Build Instructions

## Complete Guide to Build Standalone Windows .exe

This guide will help you build a complete Windows installer that includes:
- ✅ NUA POS Frontend (React)
- ✅ NUA POS Backend (FastAPI)
- ✅ MongoDB Database
- ✅ Node.js Runtime (bundled by Electron)
- ✅ Python Runtime (bundled by PyInstaller)

---

## Prerequisites

You need to install the following on your Windows machine:

### 1. Node.js (includes npm)
- Download from: https://nodejs.org/
- Version: 18.x or higher (LTS recommended)
- Verify installation: `node --version` and `npm --version`

### 2. Python
- Download from: https://www.python.org/downloads/
- Version: 3.9 or higher
- ⚠️ **IMPORTANT**: Check "Add Python to PATH" during installation
- Verify installation: `python --version`

### 3. Git (to download the code)
- Download from: https://git-scm.com/
- Verify installation: `git --version`

### 4. Windows Build Tools
- Open PowerShell as Administrator and run:
```powershell
npm install --global windows-build-tools
```

---

## Step-by-Step Build Process

### Step 1: Download MongoDB Portable

1. Download MongoDB Community Server (Windows, ZIP format):
   - URL: https://www.mongodb.com/try/download/community
   - Select: Windows x64, ZIP
   - Version: 6.0 or higher

2. Extract the ZIP file

3. Create a folder structure:
   ```
   /app/mongodb/
   └── bin/
       ├── mongod.exe
       ├── mongo.exe
       └── (other MongoDB files)
   ```

4. Copy all files from the extracted `bin` folder to `/app/mongodb/bin/`

---

### Step 2: Build the Backend Executable

1. Open Command Prompt or PowerShell

2. Navigate to the backend directory:
```bash
cd /app/backend
```

3. Install PyInstaller:
```bash
pip install pyinstaller
```

4. Install all backend dependencies:
```bash
pip install -r requirements.txt
```

5. Run the build script:
```bash
python build_backend.py
```

6. Verify the build:
   - Check that `/app/backend/dist/server.exe` exists
   - The file should be around 50-100 MB

**Troubleshooting Backend Build:**
- If you get "pyinstaller not found": Run `pip install pyinstaller` again
- If you get module import errors: Make sure all dependencies are installed with `pip install -r requirements.txt`
- If build fails: Check the error messages and ensure Python is in your PATH

---

### Step 3: Build the Frontend and Create Installer

1. Navigate to the frontend directory:
```bash
cd /app/frontend
```

2. Install Yarn (if not already installed):
```bash
npm install -g yarn
```

3. Copy the Electron package configuration:
```bash
copy electron-package.json package.json
```

4. Install all dependencies:
```bash
yarn install
```

5. Install additional Electron dependencies:
```bash
yarn add electron-is-dev
```

6. Build the React app:
```bash
yarn build
```

7. Build the Electron installer:
```bash
yarn electron:build
```
   OR for portable version:
```bash
yarn build:portable
```

8. The installer will be created in `/app/frontend/dist/`:
   - **Installer**: `NUA POS-Setup-2.0.1.exe` (NSIS installer)
   - **Portable**: `NUA POS-Portable-2.0.1.exe` (No installation needed)

**Troubleshooting Frontend Build:**
- If `yarn install` fails: Delete `node_modules` folder and try again
- If build takes too long: Be patient, Electron builds can take 5-10 minutes
- If you get "EPERM" or permission errors: Run Command Prompt as Administrator
- If you get "electron-builder" errors: Make sure you have internet connection (downloads additional tools)

---

## Step 4: Test the Executable

### Testing the Installer:
1. Navigate to `/app/frontend/dist/`
2. Double-click `NUA POS-Setup-2.0.1.exe`
3. Follow the installation wizard
4. Launch NUA POS from the Start Menu or Desktop shortcut

### Testing the Portable Version:
1. Navigate to `/app/frontend/dist/`
2. Double-click `NUA POS-Portable-2.0.1.exe`
3. The app should start directly (no installation)

### What to Expect:
- First launch may take 10-15 seconds (MongoDB and backend starting)
- A window should open showing the NUA POS interface
- The app should work completely offline
- All features should be functional

---

## Build Output

After successful build, you will have:

```
/app/frontend/dist/
├── NUA POS-Setup-2.0.1.exe          (Full installer, ~200-300 MB)
├── NUA POS-Portable-2.0.1.exe       (Portable version, ~200-300 MB)
└── win-unpacked/                        (Unpacked app files)
```

---

## Distribution

You can distribute either:
- **Installer (.exe with Setup)**: Users run it and install like any Windows app
- **Portable (.exe Portable)**: Users can run directly from USB or any folder

Both versions include:
- ✅ Complete POS system
- ✅ No additional software needed
- ✅ Works completely offline
- ✅ Self-contained database

---

## Common Issues and Solutions

### Issue: "Python not found"
**Solution**: 
- Reinstall Python and check "Add to PATH"
- Or manually add Python to PATH in Environment Variables

### Issue: "Node not found"
**Solution**:
- Reinstall Node.js
- Restart Command Prompt/PowerShell after installation

### Issue: Backend build fails with "No module named X"
**Solution**:
```bash
cd /app/backend
pip install -r requirements.txt
```

### Issue: Electron build fails with "Cannot find module"
**Solution**:
```bash
cd /app/frontend
rm -rf node_modules
yarn install
```

### Issue: "Access denied" or "EPERM" errors
**Solution**:
- Run Command Prompt as Administrator
- Disable antivirus temporarily during build
- Check if files are open in another program

### Issue: Built app doesn't start
**Solution**:
- Check Windows Firewall (may block MongoDB port)
- Run the portable version first to test
- Check logs in `%APPDATA%/NUA POS/logs/`

---

## Advanced Configuration

### Changing App Version
Edit `/app/frontend/electron-package.json`:
```json
"version": "2.0.1"  // Change this
```

### Customizing Installer
Edit the `nsis` section in `/app/frontend/electron-package.json`:
- Change installer text
- Add custom license
- Modify installation directory

### App Icon
Replace `/app/frontend/assets/icon.ico` with your custom 256x256 icon.

---

## Quick Build Commands Summary

```bash
# Backend
cd /app/backend
pip install pyinstaller
pip install -r requirements.txt
python build_backend.py

# Frontend
cd /app/frontend
yarn install
yarn add electron-is-dev
yarn build
yarn electron:build
```

---

## Support

If you encounter any issues:
1. Check the troubleshooting section above
2. Verify all prerequisites are installed correctly
3. Make sure you're running commands in the correct directory
4. Check that you have stable internet connection during build
5. Ensure you have at least 5GB free disk space

---

## File Size Information

- Backend executable: ~50-100 MB
- MongoDB portable: ~150-200 MB
- Frontend build: ~10-20 MB
- Total installer: ~200-300 MB
- Installed size: ~400-500 MB

These sizes are normal for a complete, self-contained POS system.

---

**🎉 Congratulations! You now have a complete Windows installer for NUA POS!**
