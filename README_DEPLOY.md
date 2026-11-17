# 🏋️ GymTracker — 24/7 Cloud Deployment Guide

GymTracker is now fully configured as an always-on, 24/7 cloud Progressive Web App (PWA) with **PostgreSQL dual-mode**, **offline set logging queue**, **4-digit mobile PIN security**, and **smart haptic rest timer**.

---

## 🚀 Key Features Built

1. **Always-On Cloud Architecture**:
   - Ready for **Render**, **Railway**, **Heroku**, or any Docker/WSGI cloud host.
   - Dual-mode database: Automatically connects to cloud PostgreSQL via `DATABASE_URL` or falls back to local `gym.db` (SQLite).
   - Automatically normalizes legacy `postgres://` URLs to `postgresql://` for modern SQLAlchemy 2.0+ compatibility.

2. **Mobile 4-Digit PIN Lock**:
   - Clean OLED dark modal with tactile virtual numpad and physical haptics (`navigator.vibrate`).
   - Default PIN: `1208` (customizable via `GYM_APP_PIN` environment variable).
   - Session persists for **90 days** on your phone so you don't have to keep re-entering it every workout.
   - Brute-force throttling and constant-time HMAC check to protect against unauthorized access.

3. **Gym Basement Offline Queue & Batch Sync**:
   - Zero data loss: If you enter sets in a gym basement without cell signal, the app saves them to `localStorage`.
   - Floating sync badge in header displays the number of queued offline sets.
   - Automatically performs an atomic batch sync (`POST /api/sync-queue`) the moment your phone reconnects to 4G/5G/Wi-Fi.

4. **Multi-Sensory Rest Timer**:
   - Web Audio API dual-harmonic synth chime (587Hz → 880Hz → 1174Hz) that plays reliably without downloading external audio files.
   - Tactile phone vibration pattern (`[300ms vibe, 150ms pause, 300ms vibe]`).
   - Background push notifications via `ntfy.sh` (topic: `gym-rest-alerts-9988`) even when your phone screen is locked in your pocket.

---

## 🛠 Option 1: Deploy on Render (Recommended • 100% Free)

Render provides a completely free Python web service and free PostgreSQL database.

### Step 1: Push your Gym repository to GitHub
1. In your `D:\Gym` folder, initialize git and push to your private or public GitHub repo:
   ```bash
   cd D:\Gym
   git init
   git add .
   git commit -m "feat: 24/7 cloud workout tracker with offline sync & PIN auth"
   git branch -M main
   git remote add origin https://github.com/<your-username>/gym-tracker.git
   git push -u origin main
   ```

### Step 2: Deploy with Blueprint (`render.yaml`)
1. Log into [Render.com](https://render.com).
2. Click **New +** → **Blueprint**.
3. Connect your `gym-tracker` GitHub repository.
4. Render will read `render.yaml` automatically and create:
   - Web Service: `gym-tracker` (Python runtime, `gunicorn app:app`)
   - Managed Database: `gym-db` (Free PostgreSQL)
5. Under Environment Variables:
   - `GYM_APP_PIN`: Set your preferred 4-digit PIN (default is `1208`).
   - `NTFY_TOPIC`: `gym-rest-alerts-9988` (or your custom topic).
6. Click **Apply**. Within 2 minutes, your live URL will be active (e.g., `https://gym-tracker-xxxx.onrender.com`).

---

## 🚂 Option 2: Deploy on Railway

1. Log into [Railway.app](https://railway.app).
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select your `gym-tracker` repository.
4. Click **Add Service** → **Database** → **PostgreSQL**.
5. In your Gym service settings:
   - Under **Variables**, add:
     - `GYM_APP_PIN` = `1208`
     - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
     - `SECRET_KEY` = `your-random-secret-key`
     - `NTFY_TOPIC` = `gym-rest-alerts-9988`
6. Railway will build and deploy your app with Gunicorn automatically!

---

## 📱 How to Install on Your Phone (PWA)

### iPhone (iOS Safari)
1. Open Safari and navigate to your cloud URL (e.g., `https://gym-tracker.onrender.com`).
2. Tap the **Share** button (box with an arrow pointing up at the bottom).
3. Scroll down and tap **Add to Home Screen**.
4. Name it **Gym** and tap **Add**.
5. It will now open as a full-screen, standalone app with its own icon on your home screen!

### Android (Chrome)
1. Open Chrome and navigate to your cloud URL.
2. Tap the **Install** banner on screen, or tap the three dots (⋮) in the top right.
3. Select **Add to Home screen** or **Install app**.
4. Tap **Install**.

---

## 🔄 Migrating Local Logs to Cloud Postgres (Optional)

If you already logged workouts locally on your laptop in `gym.db` and want them copied to your new cloud database:

1. Obtain your cloud PostgreSQL connection string from Render or Railway (e.g. `postgresql://user:pass@ep-cool.aws.neon.tech/gymdb`).
2. Run the migration script on your laptop:
   ```bash
   cd D:\Gym
   python migrate_sqlite_to_cloud.py "postgresql://user:pass@ep-cool.aws.neon.tech/gymdb"
   ```
3. All your exercises, historical sets, and muscle progress tiers will instantly transfer!

---

## 🔔 Background Rest Alerts on Phone (via ntfy)

1. Install the free **ntfy** app from Google Play Store or iOS App Store.
2. Open the ntfy app and tap **Subscribe to topic**.
3. Enter your topic: `gym-rest-alerts-9988`.
4. Now, whenever your rest timer completes, you'll receive a push notification even if your phone screen is turned off!
