> Historical packaging guide. The old frontend Electron/CRA commands below are retired. Use the [current shared/native build guide](../docs/platform/CURRENT_BUILD_GUIDE.md) and `apps/windows` for Windows releases.

# NUA POS — Desktop & Mobile Build Guide

## Overview
NUA POS can be packaged as:
- **Android APK** — via Capacitor (WebView wrapper)
- **Windows .exe** — via Electron + electron-builder

Both builds wrap the same React web app into native containers.

---

## Android APK Build

### Prerequisites
- Node.js >= 18
- Android Studio with SDK installed (API level 33+)
- Java JDK 17+
- `ANDROID_HOME` environment variable set

### Steps

```bash
cd frontend

# 1. Install dependencies
yarn install

# 2. Build React app (set your production API URL)
REACT_APP_BACKEND_URL="https://your-api.com" npx craco build

# 3. Add Android platform (first time only)
npx cap add android

# 4. Sync web assets to Android project
npx cap sync android

# 5. Open in Android Studio for building
npx cap open android
```

### Building the APK in Android Studio
1. Open the project in Android Studio via `npx cap open android`
2. Wait for Gradle sync to complete
3. Go to **Build > Build Bundle(s) / APK(s) > Build APK(s)**
4. The APK will be at: `android/app/build/outputs/apk/debug/app-debug.apk`

### Or use the build script
```bash
chmod +x build-android.sh
./build-android.sh
```

The APK will be copied to `dist/NUA-POS.apk`.

### Customization
- App icon: Replace `android/app/src/main/res/mipmap-*/ic_launcher.png`
- Splash screen: Configure in `capacitor.config.json`
- App name: Already set to "NUA POS" in `capacitor.config.json`

---

## Windows .exe Build

### Prerequisites
- Node.js >= 18
- yarn (`npm install -g yarn`)
- Windows OS (or cross-compile on Mac/Linux)

### Steps

```bash
cd frontend

# 1. Install dependencies
yarn install

# 2. Build React app
set REACT_APP_BACKEND_URL=https://your-api.com
npx craco build

# 3. Package as Windows .exe
npx electron-builder --win --publish never
```

### Or use the build script
```
build-windows.bat
```

The installer will be at: `dist/NUA POS Setup {version}.exe`

### Development Mode
```bash
yarn electron-dev
```
This starts both the React dev server and Electron window pointing to it.

### Customization
- Window size: Edit `electron/main.js` → `width`/`height`
- App icon: Replace `public/favicon.ico` (must be .ico format, 256x256px)
- Installer options: Edit `package.json` → `"build"` → `"nsis"` section

---

## Configuration

Both builds need the backend API URL set before building:

| Platform | Set API URL |
|----------|-------------|
| Android  | `REACT_APP_BACKEND_URL` env var before `craco build` |
| Windows  | `REACT_APP_BACKEND_URL` env var before `craco build` |

The API URL gets baked into the build at compile time.

---

## Troubleshooting

### Android: "SDK not found"
Set `ANDROID_HOME`:
```bash
export ANDROID_HOME=$HOME/Library/Android/sdk  # macOS
export ANDROID_HOME=$HOME/Android/Sdk           # Linux
```

### Windows: "electron-builder failed"
Make sure you have the Visual C++ Build Tools installed:
```
npm install --global windows-build-tools
```

### Both: "API calls fail in built app"
Make sure `REACT_APP_BACKEND_URL` is set to your production server URL before building. The URL is hardcoded at build time.
