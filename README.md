# 🏋️ GymTracker — Always-On Cloud Workout PWA

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/karthikeyan12089/gym-tracker)

GymTracker is a high-performance, 24/7 cloud Progressive Web App (PWA) with **PostgreSQL dual-mode**, **offline set logging queue**, **4-digit mobile PIN security**, and **smart haptic rest timer**.

---

## ⚡ 1-Click Instant Cloud Deployment

Deploy your own personal 24/7 cloud instance with free PostgreSQL database in 1 click:

👉 **[Deploy to Render (100% Free)](https://render.com/deploy?repo=https://github.com/karthikeyan12089/gym-tracker)**

Render automatically reads [`render.yaml`](render.yaml) and provisions:
1. **Web Service**: Gunicorn WSGI running Python 3.11.
2. **Database**: Free managed PostgreSQL database with auto-injected `DATABASE_URL`.
3. **Environment**: Secure session key, 4-digit PIN (`GYM_APP_PIN=1208`), and `NTFY_TOPIC`.

---

## 📱 Features

- **24/7 Cloud Access**: Accessible on any phone or browser anywhere without needing your laptop to be awake.
- **Gym Basement Offline Queue**: Saves sets to `localStorage` when underground or without reception; auto-syncs atomically when signal is restored.
- **OLED PIN Lock**: 4-digit security PIN screen with physical haptics (`1208` default, 90-day persistence).
- **Multi-Sensory Rest Timer**: Web Audio synth chime + phone vibration + background push alerts via `ntfy.sh`.
- **Strength Tiers & Progress**: Auto-evaluates strength levels across all muscle groups based on historical benchmark thresholds.
