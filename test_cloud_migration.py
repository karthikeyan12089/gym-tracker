"""
Automated Test Suite for GymTracker Cloud Migration
===================================================
Verifies:
1. App import & configuration
2. Database schema & initial seeding (34 exercises)
3. PIN verification API (valid, invalid, throttling)
4. Protected routes authentication enforcement
5. Batch offline queue synchronization (/api/sync-queue)
6. PWA endpoints (/sw.js, /manifest.json)
"""

import os
import sys
import json
import unittest

# Ensure Gym directory is in sys.path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)

# Force test configuration
os.environ["GYM_APP_PIN"] = "1208"
os.environ["SECRET_KEY"] = "test-secret-key-12345"

from app import app, db, Exercise, WorkoutLog, MuscleProgress, APP_PIN, _pin_attempts

class GymTrackerCloudTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        with app.app_context():
            db.create_all()
            from app import seed_database
            seed_database()
            WorkoutLog.query.delete()
            db.session.commit()

        # Clear throttle attempts
        _pin_attempts.clear()

    def tearDown(self):
        with app.app_context():
            WorkoutLog.query.delete()
            db.session.commit()
            db.session.remove()

    def test_database_seeding(self):
        """Verify all 34 exercises are seeded into SQLite/Postgres schema."""
        with app.app_context():
            ex_count = Exercise.query.count()
            self.assertGreaterEqual(ex_count, 34, f"Expected at least 34 exercises, got {ex_count}")
            bench = Exercise.query.filter_by(name="Bench Press").first()
            self.assertIsNotNone(bench)
            self.assertEqual(bench.target_muscle_primary, "Chest")

    def test_pwa_routes(self):
        """Verify Service Worker and Manifest routes serve valid headers."""
        res_sw = self.client.get("/sw.js")
        self.assertEqual(res_sw.status_code, 200)
        self.assertIn("application/javascript", res_sw.content_type)
        self.assertEqual(res_sw.headers.get("Service-Worker-Allowed"), "/")

        res_manifest = self.client.get("/manifest.json")
        self.assertEqual(res_manifest.status_code, 200)
        self.assertIn("application/manifest+json", res_manifest.content_type)

    def test_pin_verification_success(self):
        """Verify entering the correct 4-digit PIN returns 200 and authenticates session."""
        res = self.client.post("/api/verify-pin", json={"pin": "1208"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("verified", data["message"].lower())

    def test_pin_verification_failure(self):
        """Verify wrong PIN returns 401 with remaining attempt count."""
        res = self.client.post("/api/verify-pin", json={"pin": "9999"})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Incorrect PIN", data["message"])

    def test_pin_brute_force_throttling(self):
        """Verify 5 rapid failed attempts triggers HTTP 429 lockout."""
        for _ in range(5):
            self.client.post("/api/verify-pin", json={"pin": "0000"})
        # 6th attempt should be blocked with 429
        res = self.client.post("/api/verify-pin", json={"pin": "0000"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn("Too many incorrect attempts", data["message"])

    def test_protected_routes_require_auth(self):
        """Verify mutating endpoints reject unauthenticated requests."""
        # Unauthenticated /log
        res = self.client.post("/log", data={"exercise_id": 1, "weight": 60, "reps": 10})
        # Should redirect or flash error
        self.assertEqual(res.status_code, 302)

        # Unauthenticated JSON /api/sync-queue
        res_sync = self.client.post("/api/sync-queue", json={"logs": []})
        self.assertEqual(res_sync.status_code, 401)

    def test_batch_offline_sync(self):
        """Verify /api/sync-queue atomically inserts multiple offline sets."""
        # 1. Authenticate session
        self.client.post("/api/verify-pin", json={"pin": "1208"})

        # 2. Sync batch of 3 sets
        batch = [
            {"exercise_id": 1, "date": "2026-11-17", "weight": 70.0, "sets": 3, "reps": 10, "notes": "Set 1 offline"},
            {"exercise_id": 1, "date": "2026-11-17", "weight": 75.0, "sets": 3, "reps": 8, "notes": "Set 2 offline"},
            {"exercise_id": 2, "date": "2026-11-17", "weight": 35.0, "sets": 3, "reps": 12, "notes": "Biceps offline"},
        ]

        res = self.client.post("/api/sync-queue", json={"logs": batch})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["synced"], 3)

        # 3. Verify in database
        with app.app_context():
            logs = WorkoutLog.query.all()
            self.assertEqual(len(logs), 3)
            self.assertEqual(logs[0].weight, 70.0)
            self.assertEqual(logs[1].weight, 75.0)

    def test_logout(self):
        """Verify /logout clears authentication."""
        self.client.post("/api/verify-pin", json={"pin": "1208"})
        res = self.client.get("/logout")
        self.assertEqual(res.status_code, 302)

        # Confirm unauthenticated again
        res_sync = self.client.post("/api/sync-queue", json={"logs": []})
        self.assertEqual(res_sync.status_code, 401)

    def test_frontend_template_elements(self):
        """Verify HTML renders PIN lock modal, offline queue indicators, and haptic timer components."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 1. PIN Lock Screen components
        self.assertIn('id="pin-screen"', html)
        self.assertIn('id="pin-dots"', html)
        self.assertIn('id="pin-keypad"', html)
        self.assertIn("pressPinDigit", html)
        self.assertIn("submitPin", html)

        # 2. Offline Queue components
        self.assertIn('id="queue-pill"', html)
        self.assertIn('id="offline-banner"', html)
        self.assertIn('id="offline-sync-indicator"', html)
        self.assertIn("gym_offline_queue", html)
        self.assertIn("/api/sync-queue", html)

        # 3. Rest Timer & Multi-Sensory Haptics
        self.assertIn("navigator.vibrate", html)
        self.assertIn("playRestDoneChime", html)
        self.assertIn("AudioContext", html)


if __name__ == "__main__":
    unittest.main()
