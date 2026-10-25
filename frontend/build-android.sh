#!/bin/bash
# ============================================================
# NUA POS — Android APK Build Script
# ============================================================
# Prerequisites (on your local machine):
#   1. Node.js >= 22.19
#   2. Android Studio with SDK installed
#   3. Java JDK 21+
#   4. ANDROID_HOME environment variable set
#
# Usage:
#   chmod +x build-android.sh
#   ./build-android.sh
# ============================================================

set -e

echo "========================================"
echo "  NUA POS — Android APK Builder"
echo "========================================"

# Step 1: Install dependencies
echo "[1/6] Installing dependencies..."
npm ci

# Step 2: Build the React app for production
echo "[2/6] Building React app..."
: "${REACT_APP_BACKEND_URL:?Set the target HTTPS API origin before building}"
python3 ../scripts/generate_app_icons.py
PUBLIC_URL=/ npm run build

# Step 3: Add Android platform (if not already added)
if [ ! -d "android" ]; then
  echo "[3/6] Adding Android platform..."
  npx cap add android
else
  echo "[3/6] Android platform already exists, syncing..."
fi

# Step 4: Sync web assets to Android
echo "[4/6] Syncing web assets..."
npx cap sync android

# Step 5: Build the APK using Gradle
echo "[5/6] Building APK..."
cd android
if [ -f "gradlew" ]; then
  chmod +x gradlew
  ./gradlew assembleDebug
else
  echo "ERROR: gradlew not found. Open the project in Android Studio first."
  echo "  npx cap open android"
  exit 1
fi

# Step 6: Copy APK to output directory
echo "[6/6] Copying APK..."
APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK_PATH" ]; then
  mkdir -p ../dist
  cp "$APK_PATH" "../dist/NUVA-POS.apk"
  echo ""
  echo "========================================"
  echo "  APK Ready: dist/NUVA-POS.apk"
  echo "========================================"
else
  echo "APK not found at $APK_PATH"
  echo "Try opening in Android Studio: npx cap open android"
fi
