> Historical. Written for deployment to the Emergent platform itself (`*.emergent.sh`), superseded by the Vercel-only pivot — see `docs/VERCEL_ONLY.md` for the actual current hosting target and `docs/platform/CURRENT_BUILD_GUIDE.md` for current build/deploy steps.

# 📥 NUA POS - Deployment & Access Guide

**Version:** 2.0.0
**Status:** Production Ready

---

## 🚀 How to Deploy & Access Your Application

### 1️⃣ Deploy to Emergent Platform

**Steps:**

1. **Save to GitHub First** (Recommended)
   - Click "Save to GitHub" button in chat
   - This creates a backup of your complete codebase
   - You'll get a GitHub repository link

2. **Deploy to Emergent**
   - Your application is already ready for deployment
   - Click "Deploy" or use the deployment button
   - Wait ~10 minutes for deployment to complete

3. **Get Your Public URL**
   - After deployment: `https://your-app-name.emergent.sh`
   - Example: `https://nua-pos.emergent.sh`
   - Access from any device with internet

---

## 🌐 Accessing After Deployment

### Option 1: Web Access (Recommended)
**URL:** Your deployment URL (e.g., `nua-pos.emergent.sh`)

**Access From:**
- 💻 Desktop computers (any browser)
- 📱 Mobile phones (touch-optimized)
- 📲 Tablets (perfect for POS use)
- 🖥️ Multiple devices simultaneously

**Features:**
- No installation needed
- Works offline (PWA capability)
- Auto-updates
- Cross-platform

### Option 2: Download Source Code

**Via GitHub:**
```bash
# 1. Get your repository URL from "Save to GitHub"
# 2. Clone to any computer
git clone https://github.com/yourusername/nua-pos.git

# 3. Run locally
cd nua-pos

# Backend
cd backend
pip install -r requirements.txt
python seed_data.py
supervisorctl start backend

# Frontend
cd ../frontend
yarn install
yarn start
```

**Local Access:** `http://localhost:3000`

---

## 📦 What You Get After Deployment

### Deployed Application:
✅ **Live URL** - Access from anywhere
✅ **Managed Database** - MongoDB on Emergent
✅ **Auto-scaling** - Handles traffic automatically
✅ **24/7 Uptime** - Always available
✅ **SSL Certificate** - Secure HTTPS
✅ **Automatic Backups** - Daily snapshots

### Source Code Access:
✅ **GitHub Repository** - Complete codebase
✅ **Download Anytime** - Git clone to any device
✅ **Local Development** - Run on your computer
✅ **Version Control** - Track all changes
✅ **Easy Updates** - Push and redeploy

---

## 💻 Running Locally (After Download)

### Prerequisites:
- Node.js 18+ (Frontend)
- Python 3.11+ (Backend)
- MongoDB (Local or cloud)

### Quick Start:
```bash
# 1. Clone from GitHub
git clone YOUR_GITHUB_URL
cd nua-pos

# 2. Backend Setup
cd backend
pip install -r requirements.txt
# Edit .env file with your MongoDB URL
python seed_data.py
python -m uvicorn server:app --reload --port 8001

# 3. Frontend Setup (new terminal)
cd frontend
yarn install
# Edit .env file if needed
yarn start

# 4. Access
# Frontend: http://localhost:3000
# Backend API: http://localhost:8001/api
```

---

## 🔐 Environment Configuration

### For Deployed Version:
Configure in Emergent dashboard:
- `MONGO_URL` - Managed by Emergent
- `DB_NAME` - pos_db (or custom)
- `REACT_APP_BACKEND_URL` - Auto-configured

### For Local Version:
Edit `.env` files:

**Backend (.env):**
```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=pos_db
CORS_ORIGINS=*
```

**Frontend (.env):**
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

---

## 🌍 Multi-Device Setup

### Corporate Setup (Multiple Locations):

**Option A: Cloud-First**
```
Store 1 Tablet ─┐
Store 2 Tablet ─┼─→ nua-pos.emergent.sh → Cloud Database
Store 3 Desktop ─┘
```
- All devices connect to deployed URL
- Real-time data sync
- Centralized management

**Option B: Hybrid (Local + Cloud)**
```
Store 1: Local server → Sync to cloud
Store 2: Local server → Sync to cloud
Store 3: Direct to cloud
```
- Each store runs local instance
- Periodic cloud sync
- Works during internet outage

**Option C: Fully Local**
```
Local Server (Your Office)
  ↓
Tablets/Devices in same network
```
- Download from GitHub
- Run on local server
- LAN access only
- Full offline capability

---

## 📱 Mobile Access

### As Progressive Web App (PWA):

1. **Open on Mobile Browser**
   - Visit: `https://nua-pos.emergent.sh`

2. **Install as App**
   - **iOS:** Safari → Share → "Add to Home Screen"
   - **Android:** Chrome → Menu → "Install App"

3. **Works Like Native App**
   - Home screen icon
   - Full-screen mode
   - Offline capability
   - Push notifications (ready)

---

## 💾 Backup & Export Options

### 1. Code Backup (GitHub)
- Complete source code
- All configurations
- Easy restore

### 2. Database Backup
**Via Emergent:**
- Automatic daily backups
- Manual export available
- MongoDB dump commands

**Manual Backup:**
```bash
# Export all data
mongodump --uri="YOUR_MONGO_URL" --out=./backup

# Import to another database
mongorestore --uri="NEW_MONGO_URL" ./backup
```

### 3. Data Export
**From Application:**
- Reports → Export to CSV
- Accounting → Download reports
- Transactions → Export history

**Via API:**
```bash
# Export all products
curl https://nua-pos.emergent.sh/api/products > products.json

# Export all transactions
curl https://nua-pos.emergent.sh/api/transactions > transactions.json
```

---

## 🔄 Deployment Workflow

### Development → Production:

1. **Develop Locally**
   - Make changes on your computer
   - Test thoroughly

2. **Save to GitHub**
   - Commit changes
   - Push to repository

3. **Deploy to Emergent**
   - Automatic or manual deploy
   - Zero downtime update

4. **Access Anywhere**
   - Use deployment URL
   - No app store needed

---

## 💰 Cost Breakdown

### Emergent Deployment:
- **50 credits/month** - Hosting & infrastructure
- **Included:** Database, SSL, backups, auto-scaling
- **No per-transaction fees** (unlike Square)

### Local Hosting (Free):
- Download from GitHub
- Run on your server
- No monthly fees
- You manage infrastructure

---

## 🆘 Common Questions

**Q: Can I download the deployed app?**
A: No, but you can download the source code from GitHub and run it anywhere.

**Q: Can I use it offline?**
A: Yes! The app works offline and syncs when online. Download from GitHub for 100% offline use.

**Q: Can I move to another platform?**
A: Absolutely! Your GitHub repository can be deployed to AWS, Azure, Digital Ocean, or any hosting provider.

**Q: Can I run multiple instances?**
A: Yes! Deploy to Emergent for main store, run local copies in other locations.

**Q: Do I need app store approval?**
A: No! It's a web app (PWA) - install directly from browser.

**Q: Can I customize after deployment?**
A: Yes! Update code in GitHub, redeploy to Emergent.

**Q: What if Emergent goes down?**
A: Your GitHub backup lets you deploy anywhere instantly.

---

## 🎯 Recommended Setup

### For Single Store:
```
✅ Deploy to Emergent
✅ Access via web URL
✅ Install as PWA on tablets
✅ Backup to GitHub weekly
```

### For Multiple Stores:
```
✅ Deploy to Emergent (central)
✅ GitHub backup
✅ Local servers at each store (optional)
✅ Hybrid sync setup
```

### For Maximum Control:
```
✅ Download from GitHub
✅ Host on your own server
✅ Complete control
✅ No monthly fees
```

---

## 📞 Next Steps

1. **Deploy Now**
   - Click deploy button
   - Wait 10 minutes
   - Get your URL

2. **Save to GitHub**
   - Create backup
   - Enable version control
   - Future-proof your investment

3. **Configure Custom Domain** (Optional)
   - Point `pos.yourbusiness.com` to deployment
   - Professional branding
   - Easy to remember

4. **Start Using**
   - Access from any device
   - Train your staff
   - Start selling!

---

## 📊 Access Summary

| Method | Access | Internet | Cost | Best For |
|--------|--------|----------|------|----------|
| **Emergent Deployed** | Web URL | Required | 50 credits/mo | Cloud-first |
| **GitHub Download** | localhost | Not required | Free | Full control |
| **PWA Install** | Any device | Initial only | Included | Mobile POS |
| **Hybrid Setup** | Both | Optional | Mixed | Multi-location |

---

<div align="center">

**Your NUA POS is Ready for Deployment!**

Access it anywhere, anytime - on any device

[Deploy Now] • [Save to GitHub] • [Download Guide]

</div>
