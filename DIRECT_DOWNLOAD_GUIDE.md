> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# 💾 Direct Download Guide - NUA POS

## Overview

This guide shows you how to download the NUA POS code directly from the development platform to your Windows PC (without using GitHub).

**Time Required:** 5-10 minutes

**Best For:**
- Quick one-time build
- No GitHub account needed
- Simple and fast

---

## 📋 Prerequisites

- [ ] Access to this development platform
- [ ] Windows PC with internet connection
- [ ] File extraction tool (Windows has built-in ZIP support)

---

## 🎯 Step-by-Step Instructions

### PART 1: Download from Platform

#### Step 1: Locate Download Feature

**In your current development platform interface:**

1. Look for a button/option labeled:
   - **"Download Workspace"**
   - **"Export Project"**
   - **"Download All Files"**
   - **"Download Code"**
   - **"Export as ZIP"**
   - Or similar wording

2. **Common locations:**
   - Top menu bar
   - Right-click on project name
   - In settings/options menu (⚙️)
   - Dropdown menu (⋮ or ☰)
   - File menu

**Visual Clues:**
- Look for download icon (⬇️)
- Look for export icon (📤)
- Look for folder/archive icon (📁)

---

#### Step 2: Initiate Download

**Method A: Direct Download Button**

1. Click "Download Workspace" or similar
2. Platform prepares files (may take 30-60 seconds)
3. Download starts automatically
4. Save file (usually named `workspace.zip` or `project.zip`)

**Method B: Export Menu**

1. Click "File" or menu icon (☰)
2. Select "Export" or "Download"
3. Choose "Download as ZIP"
4. Select "All files" or "Entire workspace"
5. Click "Export" or "Download"
6. Wait for preparation
7. Save the ZIP file

**Method C: Context Menu**

1. Right-click on project/workspace name
2. Select "Download" or "Export"
3. Choose format: ZIP
4. Save file

---

#### Step 3: Wait for Download

**What to expect:**
- File size: ~50-100 MB (depends on node_modules)
- Download time: 1-5 minutes (depends on connection)
- File name: Usually `workspace.zip`, `nua-pos.zip`, or similar

**Progress indicators:**
- Browser shows download progress
- File appears in Downloads folder

**💡 Pro Tip:** Don't close the platform tab until download completes!

---

### PART 2: Extract on Windows PC

#### Step 4: Locate Downloaded File

1. Open **File Explorer** (Windows Key + E)
2. Go to **Downloads** folder
3. Look for the ZIP file:
   - `workspace.zip`
   - `nua-pos.zip`
   - Or similar name with today's date

**Default location:**
```
C:\Users\YourUsername\Downloads\
```

---

#### Step 5: Choose Extraction Location

**Recommended locations:**

**Option A: Documents Folder (Recommended)**
```
C:\Users\YourUsername\Documents\NUAPOS\
```
- Easy to find
- Good organization
- No permission issues

**Option B: Desktop**
```
C:\Users\YourUsername\Desktop\NUAPOS\
```
- Very accessible
- Quick access
- Good for temporary use

**Option C: Custom Project Folder**
```
C:\Projects\NUAPOS\
```
- Professional setup
- Keep all projects organized
- Better for multiple projects

**💡 Tip:** Create the folder first before extracting!

---

#### Step 6: Extract ZIP File

**Method A: Windows Built-in (Recommended)**

1. **Right-click** on the ZIP file
2. Select **"Extract All..."**
3. Click **"Browse..."** to choose location
4. Navigate to your chosen folder (e.g., Documents)
5. Click **"Select Folder"**
6. Click **"Extract"**
7. Wait for extraction (30-60 seconds)

**Method B: Drag and Drop**

1. **Double-click** ZIP file to open it
2. Select all files inside (Ctrl+A)
3. **Drag** them to your chosen folder
4. Wait for copy to complete

**Method C: Using WinRAR/7-Zip (If Installed)**

1. **Right-click** ZIP file
2. Select **"Extract to..."** or **"7-Zip > Extract to..."**
3. Choose destination
4. Click **"OK"**

---

#### Step 7: Verify Extraction

**Open the extracted folder and check for:**

```
NUAPOS/
├── backend/
│   ├── models/
│   ├── services/
│   ├── server.py
│   ├── requirements.txt
│   ├── build_backend.py
│   └── .env
├── frontend/
│   ├── public/
│   ├── src/
│   ├── electron/
│   ├── package.json
│   └── electron-package.json
├── BUILD_GUIDE.html
├── BUILD_CHECKLIST.md
├── QUICK_BUILD_GUIDE.md
├── build_windows_exe.bat
├── check_prerequisites.py
├── START_HERE.md
└── (more files...)
```

**✅ Success Indicators:**
- You see `backend` and `frontend` folders
- You see `build_windows_exe.bat` file
- You see multiple `.md` guide files
- Folder size: 50-100 MB+

---

#### Step 8: Open Command Prompt in Project Folder

**Method A: Address Bar Trick (Easiest)**

1. Open the extracted folder in File Explorer
2. Click in the **address bar** (where the path shows)
3. Type: `cmd`
4. Press **Enter**
5. Command Prompt opens in that folder! ✨

**Method B: Shift + Right Click**

1. Open File Explorer to the project folder
2. Hold **Shift** key
3. **Right-click** on empty space in folder
4. Select **"Open PowerShell window here"** or **"Open command window here"**

**Method C: Manual Navigation**

1. Press **Windows Key + R**
2. Type: `cmd`
3. Press Enter
4. Navigate to folder:
   ```bash
   cd C:\Users\YourUsername\Documents\NUAPOS
   ```

---

### PART 3: Verify Download

#### Step 9: Run Verification Script

**In Command Prompt (opened in project folder):**

```bash
python check_prerequisites.py
```

**Expected output:**
```
=============================================================
🔍 NUA POS - Build Prerequisites Checker
=============================================================

1️⃣  System Requirements
------------------------------------------------------------
Checking Node.js... ✅ or ❌
Checking npm... ✅ or ❌
Checking Python... ✅ or ❌
...

3️⃣  Project Structure
------------------------------------------------------------
Checking backend structure... ✅ OK: All files present
Checking frontend structure... ✅ OK: All files present
```

**Note:** It's OK if some checks fail at this point (like Node.js or MongoDB). We'll install those in the next guide. The important checks are:
- ✅ Backend structure: OK
- ✅ Frontend structure: OK

---

## ✅ Success Checklist

After completing this guide:

- [ ] Downloaded ZIP file from platform
- [ ] Extracted files to Windows PC
- [ ] Verified folder structure is correct
- [ ] Can see `backend/` and `frontend/` folders
- [ ] Can see `build_windows_exe.bat` file
- [ ] Opened Command Prompt in project folder
- [ ] Ran `check_prerequisites.py` successfully

---

## 🎯 What's Next?

**Now that you have the code on your Windows PC:**

### ➡️ Next Step: Prepare Your Windows PC
**Read:** `WINDOWS_SETUP_GUIDE.md`

This will guide you through:
- Installing Node.js
- Installing Python
- Setting up MongoDB
- Preparing for build

**Time:** 15-20 minutes (one-time setup)

---

## 🚨 Troubleshooting

### Issue: Can't find Download button on platform
**Solutions:**
1. Check platform documentation
2. Look in File menu
3. Look in Settings/Options
4. Try right-clicking on project name
5. Ask platform support: "How do I download my workspace?"
6. Alternative: Use GitHub method (see GITHUB_DOWNLOAD_GUIDE.md)

---

### Issue: Downloaded file is corrupt or won't extract
**Solutions:**
1. Delete downloaded ZIP
2. Clear browser cache
3. Download again
4. Try different browser
5. Check internet connection
6. Disable antivirus temporarily during download

---

### Issue: Extraction fails with error
**Solutions:**
1. Try extracting to Desktop first (fewer permission issues)
2. Run File Explorer as Administrator:
   - Search "File Explorer"
   - Right-click → "Run as administrator"
3. Check available disk space (need 5+ GB)
4. Use different extraction tool (7-Zip, WinRAR)

---

### Issue: Files missing after extraction
**Solutions:**
1. Re-extract (don't drag individual files)
2. Use "Extract All" instead of drag-drop
3. Check if antivirus quarantined files
4. Download ZIP again (might be incomplete)

---

### Issue: Command Prompt won't open in folder
**Solutions:**
1. Open Command Prompt normally
2. Navigate manually:
   ```bash
   cd C:\Path\To\Your\NUAPOS\Folder
   ```
3. Or use PowerShell instead (works the same)

---

### Issue: `python check_prerequisites.py` gives error
**Solutions:**

**If "python is not recognized":**
- Python not installed yet (that's OK!)
- We'll install it in WINDOWS_SETUP_GUIDE.md
- Skip this step for now

**If "No such file":**
- You're in wrong folder
- Run: `dir` to see current files
- Navigate to correct folder: `cd path\to\nuapos`

---

## 💡 Pro Tips

### Organize Your Files
Create a dedicated folder structure:
```
C:\Projects\        (Main projects folder)
  ├── NUAPOS\   (This project)
  └── OtherProjects\
```

### Keep Original ZIP
Don't delete the downloaded ZIP file until you successfully build the .exe. You might need to re-extract.

### Backup
After successful build, copy the entire folder to an external drive or cloud storage.

### Path Length
Keep the extraction path short to avoid Windows path length limits:
- ✅ Good: `C:\Projects\NUAPOS\`
- ❌ Bad: `C:\Users\...\Very\Long\Path\With\Many\Folders\...\NUAPOS\`

---

## 🔄 Re-downloading Updates

If you make changes in the platform:

1. Download new ZIP from platform
2. **Backup your current folder** (rename to `NUAPOS-old`)
3. Extract new ZIP to same location
4. If you made local changes, manually copy them over

**Better approach:** Use GitHub method for easier updates!

---

## 📊 Download Comparison

| Method | Speed | Updates | Version Control | Complexity |
|--------|-------|---------|-----------------|------------|
| **Direct Download** | ⚡⚡⚡ Fast | Manual | None | ⭐ Easy |
| **GitHub** | ⚡⚡ Medium | Automatic | Full | ⭐⭐ Medium |

**Use Direct Download if:**
- ✅ You want quickest path to .exe
- ✅ You don't plan to update frequently
- ✅ You don't need version control
- ✅ You're not familiar with Git

**Use GitHub if:**
- ✅ You want professional workflow
- ✅ You plan to update and maintain
- ✅ You want backup and history
- ✅ You're comfortable with basic Git

---

## ✨ Summary

**What you accomplished:**
1. ✅ Downloaded code from platform
2. ✅ Extracted files to Windows PC
3. ✅ Verified folder structure
4. ✅ Opened Command Prompt in project folder

**What's next:**
1. ➡️ Setup Windows PC (WINDOWS_SETUP_GUIDE.md)
2. ➡️ Build the .exe (WINDOWS_BUILD_GUIDE.md)

---

**🎉 Great job! You have the code on your Windows PC!**

**Next:** Open `WINDOWS_SETUP_GUIDE.md` to prepare your Windows PC for building.
