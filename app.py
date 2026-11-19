import os
import json
import time
import hmac
import requests
from functools import wraps
from datetime import datetime, date, timezone, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory, make_response, session
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc

# ---------------------------------------------------------------------------
# App & DB setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

# Cloud Postgres (Render / Railway / Neon / Supabase / Vercel) vs Local SQLite Dual-Mode
raw_db_url = os.environ.get("DATABASE_URL", "").strip()
if raw_db_url:
    # Normalize postgres:// to postgresql:// for SQLAlchemy 1.4+ compatibility
    if raw_db_url.startswith("postgres://"):
        raw_db_url = "postgresql://" + raw_db_url[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_url
else:
    # If running on Vercel serverless without DATABASE_URL, write to /tmp to prevent read-only filesystem crash
    if os.environ.get("VERCEL"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////tmp/gym.db"
    else:
        db_path = os.path.join(BASE_DIR, "gym.db").replace("\\", "/")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gymtracker-phase4-production-secret-key-9988")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=90)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Enforce secure cookies on HTTPS or cloud platforms (Render / Vercel / HTTPS)
if os.environ.get("VERCEL") or os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production" or os.environ.get("HTTPS") == "on":
    app.config["SESSION_COOKIE_SECURE"] = True

# 4-Digit Security PIN (Default: 1208 or overridden via GYM_APP_PIN)
APP_PIN = str(os.environ.get("GYM_APP_PIN", "1208")).strip()

# ---------------------------------------------------------------------------
# Phase 4 — ntfy.sh config
# ---------------------------------------------------------------------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "gym-rest-alerts-9988")
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"

db = SQLAlchemy(app)


def is_authenticated() -> bool:
    """Check whether the client is authenticated via session."""
    if not APP_PIN:
        return True
    return session.get("authenticated") is True


def login_required(f):
    """Decorator to protect mutating endpoints from unauthenticated requests."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if APP_PIN and not session.get("authenticated"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Authentication required. Please enter your PIN."}), 401
            flash("Please enter your PIN to continue.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function


_pin_attempts: dict[str, list[float]] = {}


@app.template_filter("from_json")
def from_json_filter(value):
    """Parse a JSON string inside a Jinja2 template."""
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Exercise(db.Model):
    """
    Exercise library.
    category: 'weight_reps' | 'time'
    """
    __tablename__ = "exercises"

    id                       = db.Column(db.Integer, primary_key=True)
    name                     = db.Column(db.String(120), nullable=False, unique=True)
    category                 = db.Column(db.String(20),  nullable=False)
    target_muscle_primary    = db.Column(db.String(80),  nullable=False)
    target_muscle_secondary  = db.Column(db.String(200), nullable=True)
    strength_level_benchmark = db.Column(db.Text,        nullable=True)

    logs = db.relationship("WorkoutLog", backref="exercise", lazy=True)

    def __repr__(self):
        return f"<Exercise {self.name}>"


class WorkoutLog(db.Model):
    """Individual workout set entry."""
    __tablename__ = "workout_logs"

    id           = db.Column(db.Integer, primary_key=True)
    date         = db.Column(db.Date,    nullable=False, default=date.today)
    exercise_id  = db.Column(db.Integer, db.ForeignKey("exercises.id"), nullable=False)
    weight       = db.Column(db.Float,   nullable=True)
    reps         = db.Column(db.Integer, nullable=True)
    sets         = db.Column(db.Integer, nullable=True)
    time_seconds = db.Column(db.Integer, nullable=True)
    notes        = db.Column(db.Text,    nullable=True)

    def __repr__(self):
        return f"<WorkoutLog id={self.id} exercise_id={self.exercise_id} date={self.date}>"


class MuscleProgress(db.Model):
    """Tracks strength tier per muscle group."""
    __tablename__ = "muscle_progress"

    id             = db.Column(db.Integer, primary_key=True)
    muscle_group   = db.Column(db.String(80), nullable=False, unique=True)
    strength_level = db.Column(db.String(20), nullable=False, default="beginner")
    updated_at     = db.Column(db.DateTime,   nullable=False,
                               default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<MuscleProgress {self.muscle_group}: {self.strength_level}>"


# ---------------------------------------------------------------------------
# Phase 4 — Expanded Exercise Seed (34 total: 6 original + 28 new)
# ---------------------------------------------------------------------------

def _bm(b, i, a):
    """Helper: build a JSON benchmark string."""
    return json.dumps({"beginner": b, "intermediate": i, "advanced": a})


EXERCISES_SEED = [
    # ── Original 6 ─────────────────────────────────────────────────────────
    {"name": "Bench Press",       "category": "weight_reps", "target_muscle_primary": "Chest",
     "target_muscle_secondary": "Triceps, Front Deltoids",
     "strength_level_benchmark": _bm("< 0.75x bodyweight", "1.0x bodyweight", "> 1.5x bodyweight")},

    {"name": "Dead Hang",         "category": "time",        "target_muscle_primary": "Forearms",
     "target_muscle_secondary": "Lats, Biceps, Shoulders",
     "strength_level_benchmark": _bm("< 30 seconds", "30–60 seconds", "> 90 seconds")},

    {"name": "Barbell Bicep Curl","category": "weight_reps", "target_muscle_primary": "Biceps",
     "target_muscle_secondary": "Forearms, Brachialis",
     "strength_level_benchmark": _bm("< 0.3x bodyweight", "0.5x bodyweight", "> 0.75x bodyweight")},

    {"name": "Overhead Press",    "category": "weight_reps", "target_muscle_primary": "Shoulders",
     "target_muscle_secondary": "Triceps, Upper Chest, Upper Traps",
     "strength_level_benchmark": _bm("< 0.4x bodyweight", "0.65x bodyweight", "> 1.0x bodyweight")},

    {"name": "Pull-ups",          "category": "weight_reps", "target_muscle_primary": "Lats",
     "target_muscle_secondary": "Biceps, Rear Deltoids, Rhomboids",
     "strength_level_benchmark": _bm("< 3 reps", "8–12 reps", "> 15 reps or weighted")},

    {"name": "Squats",            "category": "weight_reps", "target_muscle_primary": "Quadriceps",
     "target_muscle_secondary": "Glutes, Hamstrings, Core",
     "strength_level_benchmark": _bm("< 0.75x bodyweight", "1.25x bodyweight", "> 1.75x bodyweight")},

    # ── Chest ───────────────────────────────────────────────────────────────
    {"name": "Incline Bench Press","category": "weight_reps","target_muscle_primary": "Chest",
     "target_muscle_secondary": "Triceps, Front Deltoids, Upper Chest",
     "strength_level_benchmark": _bm("< 0.6x bodyweight", "0.85x bodyweight", "> 1.2x bodyweight")},

    {"name": "Cable Fly",         "category": "weight_reps", "target_muscle_primary": "Chest",
     "target_muscle_secondary": "Front Deltoids, Inner Chest",
     "strength_level_benchmark": _bm("< 0.3x bodyweight", "0.5x bodyweight", "> 0.75x bodyweight")},

    {"name": "Push-ups",          "category": "weight_reps", "target_muscle_primary": "Chest",
     "target_muscle_secondary": "Triceps, Front Deltoids, Core",
     "strength_level_benchmark": _bm("< 15 reps", "25 reps", "> 40 reps")},

    {"name": "Chest Dips",        "category": "weight_reps", "target_muscle_primary": "Chest",
     "target_muscle_secondary": "Triceps, Front Deltoids",
     "strength_level_benchmark": _bm("< 8 reps", "15 reps", "> 25 reps / weighted")},

    # ── Back ────────────────────────────────────────────────────────────────
    {"name": "Deadlift",          "category": "weight_reps", "target_muscle_primary": "Lower Back",
     "target_muscle_secondary": "Glutes, Hamstrings, Traps, Core",
     "strength_level_benchmark": _bm("< 1.5x bodyweight", "2.0x bodyweight", "> 2.5x bodyweight")},

    {"name": "Barbell Row",       "category": "weight_reps", "target_muscle_primary": "Lats",
     "target_muscle_secondary": "Biceps, Rear Deltoids, Lower Back",
     "strength_level_benchmark": _bm("< 0.75x bodyweight", "1.0x bodyweight", "> 1.5x bodyweight")},

    {"name": "Lat Pulldown",      "category": "weight_reps", "target_muscle_primary": "Lats",
     "target_muscle_secondary": "Biceps, Rear Deltoids",
     "strength_level_benchmark": _bm("< 0.6x bodyweight", "0.9x bodyweight", "> 1.1x bodyweight")},

    {"name": "Seated Cable Row",  "category": "weight_reps", "target_muscle_primary": "Lats",
     "target_muscle_secondary": "Biceps, Rear Deltoids",
     "strength_level_benchmark": _bm("< 0.6x bodyweight", "0.9x bodyweight", "> 1.2x bodyweight")},

    {"name": "T-Bar Row",         "category": "weight_reps", "target_muscle_primary": "Lats",
     "target_muscle_secondary": "Biceps, Rear Deltoids, Lower Back",
     "strength_level_benchmark": _bm("< 0.6x bodyweight", "1.0x bodyweight", "> 1.5x bodyweight")},

    # ── Shoulders ───────────────────────────────────────────────────────────
    {"name": "Lateral Raise",     "category": "weight_reps", "target_muscle_primary": "Shoulders",
     "target_muscle_secondary": "Upper Traps",
     "strength_level_benchmark": _bm("< 0.12x bodyweight", "0.2x bodyweight", "> 0.3x bodyweight")},

    {"name": "Face Pull",         "category": "weight_reps", "target_muscle_primary": "Rear Deltoids",
     "target_muscle_secondary": "Rhomboids, Upper Traps",
     "strength_level_benchmark": _bm("< 0.3x bodyweight", "0.5x bodyweight", "> 0.7x bodyweight")},

    {"name": "Arnold Press",      "category": "weight_reps", "target_muscle_primary": "Shoulders",
     "target_muscle_secondary": "Triceps, Upper Chest",
     "strength_level_benchmark": _bm("< 0.3x bodyweight", "0.5x bodyweight", "> 0.75x bodyweight")},

    # ── Biceps ──────────────────────────────────────────────────────────────
    {"name": "Hammer Curl",       "category": "weight_reps", "target_muscle_primary": "Biceps",
     "target_muscle_secondary": "Forearms, Brachialis",
     "strength_level_benchmark": _bm("< 0.25x bodyweight", "0.4x bodyweight", "> 0.6x bodyweight")},

    {"name": "Incline Dumbbell Curl","category":"weight_reps","target_muscle_primary": "Biceps",
     "target_muscle_secondary": "Forearms",
     "strength_level_benchmark": _bm("< 0.2x bodyweight", "0.35x bodyweight", "> 0.5x bodyweight")},

    {"name": "Preacher Curl",     "category": "weight_reps", "target_muscle_primary": "Biceps",
     "target_muscle_secondary": "Forearms",
     "strength_level_benchmark": _bm("< 0.25x bodyweight", "0.4x bodyweight", "> 0.6x bodyweight")},

    # ── Triceps ─────────────────────────────────────────────────────────────
    {"name": "Tricep Pushdown",   "category": "weight_reps", "target_muscle_primary": "Triceps",
     "target_muscle_secondary": "Forearms",
     "strength_level_benchmark": _bm("< 0.35x bodyweight", "0.6x bodyweight", "> 0.9x bodyweight")},

    {"name": "Skull Crusher",     "category": "weight_reps", "target_muscle_primary": "Triceps",
     "target_muscle_secondary": "Forearms",
     "strength_level_benchmark": _bm("< 0.4x bodyweight", "0.65x bodyweight", "> 0.9x bodyweight")},

    {"name": "Close-Grip Bench Press","category":"weight_reps","target_muscle_primary":"Triceps",
     "target_muscle_secondary": "Chest, Front Deltoids",
     "strength_level_benchmark": _bm("< 0.65x bodyweight", "1.0x bodyweight", "> 1.3x bodyweight")},

    # ── Legs ────────────────────────────────────────────────────────────────
    {"name": "Romanian Deadlift", "category": "weight_reps", "target_muscle_primary": "Hamstrings",
     "target_muscle_secondary": "Glutes, Lower Back",
     "strength_level_benchmark": _bm("< 1.0x bodyweight", "1.5x bodyweight", "> 2.0x bodyweight")},

    {"name": "Leg Press",         "category": "weight_reps", "target_muscle_primary": "Quadriceps",
     "target_muscle_secondary": "Glutes, Hamstrings, Calves",
     "strength_level_benchmark": _bm("< 1.5x bodyweight", "2.25x bodyweight", "> 3.0x bodyweight")},

    {"name": "Leg Curl",          "category": "weight_reps", "target_muscle_primary": "Hamstrings",
     "target_muscle_secondary": "Glutes",
     "strength_level_benchmark": _bm("< 0.4x bodyweight", "0.65x bodyweight", "> 0.9x bodyweight")},

    {"name": "Calf Raise",        "category": "weight_reps", "target_muscle_primary": "Calves",
     "target_muscle_secondary": "Soleus",
     "strength_level_benchmark": _bm("< 1.0x bodyweight", "1.75x bodyweight", "> 2.5x bodyweight")},

    {"name": "Bulgarian Split Squat","category":"weight_reps","target_muscle_primary":"Quadriceps",
     "target_muscle_secondary": "Glutes, Hamstrings",
     "strength_level_benchmark": _bm("< 0.4x bodyweight", "0.7x bodyweight", "> 1.0x bodyweight")},

    {"name": "Hip Thrust",        "category": "weight_reps", "target_muscle_primary": "Glutes",
     "target_muscle_secondary": "Hamstrings, Core",
     "strength_level_benchmark": _bm("< 1.0x bodyweight", "1.75x bodyweight", "> 2.5x bodyweight")},

    # ── Core ────────────────────────────────────────────────────────────────
    {"name": "Plank",             "category": "time",        "target_muscle_primary": "Core",
     "target_muscle_secondary": "Lower Back, Shoulders, Glutes",
     "strength_level_benchmark": _bm("< 45 seconds", "90 seconds", "> 180 seconds")},

    {"name": "L-Sit",             "category": "time",        "target_muscle_primary": "Core",
     "target_muscle_secondary": "Hip Flexors, Triceps, Lats",
     "strength_level_benchmark": _bm("< 5 seconds", "15 seconds", "> 30 seconds")},

    {"name": "Hanging Leg Raise", "category": "weight_reps", "target_muscle_primary": "Core",
     "target_muscle_secondary": "Hip Flexors, Lats",
     "strength_level_benchmark": _bm("< 6 reps", "12 reps", "> 20 reps")},

    {"name": "Ab Rollout",        "category": "weight_reps", "target_muscle_primary": "Core",
     "target_muscle_secondary": "Lower Back, Shoulders",
     "strength_level_benchmark": _bm("< 5 reps", "12 reps", "> 20 reps")},
]

MUSCLE_PROGRESS_SEED = [
    "Chest", "Triceps", "Forearms", "Biceps",
    "Shoulders", "Rear Deltoids", "Lats", "Lower Back", "Traps",
    "Quadriceps", "Hamstrings", "Glutes", "Calves",
    "Core", "Hip Flexors",
]


def seed_database():
    """
    Idempotent seed: inserts any exercise or muscle-group row that doesn't
    already exist by name, so it's safe to call on every startup.
    """
    existing_ex = {ex.name for ex in Exercise.query.all()}
    added = 0
    for ex_data in EXERCISES_SEED:
        if ex_data["name"] not in existing_ex:
            db.session.add(Exercise(**ex_data))
            added += 1

    existing_mp = {mp.muscle_group for mp in MuscleProgress.query.all()}
    for muscle in MUSCLE_PROGRESS_SEED:
        if muscle not in existing_mp:
            db.session.add(MuscleProgress(muscle_group=muscle, strength_level="beginner"))

    db.session.commit()
    print(f"[seed] Database seeded — {added} new exercise(s) added.")


# ---------------------------------------------------------------------------
# Strength tier helpers
# ---------------------------------------------------------------------------

ASSUMED_BODYWEIGHT_KG = 75.0

# Exercises evaluated on reps rather than load
REPS_BASED_EXERCISES = {
    "Pull-ups", "Push-ups", "Chest Dips",
    "Hanging Leg Raise", "Ab Rollout",
}

# (intermediate_threshold, advanced_threshold)
# time-based  → seconds | reps-based → reps | weight-based → weight/BW ratio
STRENGTH_THRESHOLDS: dict[str, tuple] = {
    # Original 6
    "Bench Press":           (1.0,   1.5),
    "Barbell Bicep Curl":    (0.5,   0.75),
    "Overhead Press":        (0.65,  1.0),
    "Pull-ups":              (8,     15),
    "Squats":                (1.25,  1.75),
    "Dead Hang":             (30,    90),
    # Chest
    "Incline Bench Press":   (0.85,  1.2),
    "Cable Fly":             (0.5,   0.75),
    "Push-ups":              (15,    30),
    "Chest Dips":            (10,    20),
    # Back
    "Deadlift":              (2.0,   2.5),
    "Barbell Row":           (1.0,   1.5),
    "Lat Pulldown":          (0.9,   1.1),
    "Seated Cable Row":      (0.9,   1.2),
    "T-Bar Row":             (1.0,   1.5),
    # Shoulders
    "Lateral Raise":         (0.2,   0.3),
    "Face Pull":             (0.5,   0.7),
    "Arnold Press":          (0.5,   0.75),
    # Biceps
    "Hammer Curl":           (0.4,   0.6),
    "Incline Dumbbell Curl": (0.35,  0.5),
    "Preacher Curl":         (0.4,   0.6),
    # Triceps
    "Tricep Pushdown":       (0.6,   0.9),
    "Skull Crusher":         (0.65,  0.9),
    "Close-Grip Bench Press":(1.0,   1.3),
    # Legs
    "Romanian Deadlift":     (1.5,   2.0),
    "Leg Press":             (2.25,  3.0),
    "Leg Curl":              (0.65,  0.9),
    "Calf Raise":            (1.75,  2.5),
    "Bulgarian Split Squat": (0.7,   1.0),
    "Hip Thrust":            (1.75,  2.5),
    # Core
    "Plank":                 (90,    180),
    "L-Sit":                 (15,    30),
    "Hanging Leg Raise":     (12,    20),
    "Ab Rollout":            (12,    20),
}


def calculate_strength_tier(exercise: Exercise) -> str:
    """Return 'beginner' | 'intermediate' | 'advanced' for the latest log."""
    latest = (
        WorkoutLog.query
        .filter_by(exercise_id=exercise.id)
        .order_by(desc(WorkoutLog.date), desc(WorkoutLog.id))
        .first()
    )
    if not latest:
        return "beginner"

    thresholds = STRENGTH_THRESHOLDS.get(exercise.name)

    if exercise.category == "time":
        metric = latest.time_seconds or 0
        if thresholds is None:
            thresholds = (30, 60)          # generic time default
    elif exercise.name in REPS_BASED_EXERCISES:
        metric = latest.reps or 0
        if thresholds is None:
            thresholds = (10, 20)          # generic reps default
    else:
        raw_weight = latest.weight or 0
        metric = raw_weight / ASSUMED_BODYWEIGHT_KG
        if thresholds is None:
            thresholds = (1.0, 1.5)        # generic weight-ratio default

    inter_thresh, adv_thresh = thresholds
    if metric >= adv_thresh:
        return "advanced"
    elif metric >= inter_thresh:
        return "intermediate"
    else:
        return "beginner"


def recalculate_muscle_progress():
    """
    Re-evaluate strength tiers for every muscle group and persist to DB.
    Creates MuscleProgress rows for new custom-exercise muscles automatically.
    """
    exercises = Exercise.query.all()
    tier_rank = {"beginner": 0, "intermediate": 1, "advanced": 2}
    best_tier: dict[str, str] = {}

    for ex in exercises:
        tier   = calculate_strength_tier(ex)
        muscle = ex.target_muscle_primary
        if tier_rank[tier] > tier_rank.get(best_tier.get(muscle, "beginner"), 0):
            best_tier[muscle] = tier
        elif muscle not in best_tier:
            best_tier[muscle] = tier

    for muscle, tier in best_tier.items():
        mp = MuscleProgress.query.filter_by(muscle_group=muscle).first()
        if mp:
            mp.strength_level = tier
            mp.updated_at = datetime.now(timezone.utc)
        else:
            db.session.add(MuscleProgress(muscle_group=muscle, strength_level=tier))

    db.session.commit()


def calculate_progress(exercise_id: int) -> dict:
    """
    Returns delta % between last two distinct-date sessions.
    trend: 'up' | 'down' | 'same' | None
    """
    exercise = db.session.get(Exercise, exercise_id)
    if not exercise:
        return {"last_log": None, "prev_log": None, "delta_pct": None, "trend": None}

    logs = (
        WorkoutLog.query
        .filter_by(exercise_id=exercise_id)
        .order_by(desc(WorkoutLog.date), desc(WorkoutLog.id))
        .all()
    )
    if not logs:
        return {"last_log": None, "prev_log": None, "delta_pct": None, "trend": None}

    last_log  = logs[0]
    last_date = last_log.date
    prev_log  = next((l for l in logs[1:] if l.date != last_date), None)

    if prev_log is None:
        return {"last_log": last_log, "prev_log": None, "delta_pct": None, "trend": None}

    if exercise.category == "time":
        current_val, prev_val = last_log.time_seconds, prev_log.time_seconds
    else:
        current_val, prev_val = last_log.weight, prev_log.weight

    if current_val is None or prev_val is None or prev_val == 0:
        return {"last_log": last_log, "prev_log": prev_log, "delta_pct": None, "trend": None}

    delta_pct = round(((current_val - prev_val) / prev_val) * 100, 1)
    trend = "up" if delta_pct > 0 else ("down" if delta_pct < 0 else "same")

    return {"last_log": last_log, "prev_log": prev_log,
            "delta_pct": delta_pct, "trend": trend}


# ---------------------------------------------------------------------------
# Phase 4 — ntfy.sh helpers
# ---------------------------------------------------------------------------

def send_rest_done_notification(exercise_name: str, rest_seconds: int,
                                 is_test: bool = False) -> bool:
    """
    POST to ntfy.sh with a rich push notification.
    Title:   "Gym Rest Over!"
    Message: "Time for your next set!" (or test variant)
    Returns True on HTTP 200, False otherwise.
    """
    if is_test:
        body  = "🧪 Test notification from GymTracker — ntfy is working!"
        title = "GymTracker Test ✅"
    else:
        body  = f"Time for your next set of {exercise_name}! 💪"
        title = "Gym Rest Over! 🏋️"

    try:
        response = requests.post(
            NTFY_URL,
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": "high",
                "Tags":     "muscle,stopwatch,gym",
            },
            timeout=5,
        )
        ok = response.status_code == 200
        print(f"[ntfy] {'OK' if ok else 'FAIL'} ({response.status_code}) — {title}")
        return ok
    except requests.RequestException as exc:
        print(f"[ntfy] Request error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    recalculate_muscle_progress()

    exercises       = Exercise.query.order_by(Exercise.target_muscle_primary, Exercise.name).all()
    muscle_progress = MuscleProgress.query.order_by(MuscleProgress.muscle_group).all()

    exercise_data = []
    for ex in exercises:
        recent_logs = (
            WorkoutLog.query
            .filter_by(exercise_id=ex.id)
            .order_by(desc(WorkoutLog.date), desc(WorkoutLog.id))
            .limit(5)
            .all()
        )
        exercise_data.append({
            "exercise":      ex,
            "recent_logs":   recent_logs,
            "progress":      calculate_progress(ex.id),
            "strength_tier": calculate_strength_tier(ex),
        })

    return render_template(
        "index.html",
        exercise_data=exercise_data,
        muscle_progress=muscle_progress,
        total_logs=WorkoutLog.query.count(),
        today_str=date.today().isoformat(),
        exercises=exercises,
        ntfy_topic=NTFY_TOPIC,
        is_authenticated=is_authenticated(),
    )


@app.route("/api/verify-pin", methods=["POST"])
def verify_pin():
    """Validate 4-digit PIN with brute-force throttling and constant-time comparison."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "client").split(",")[0].strip()
    now = time.time()

    # Retain attempts within the last 5 minutes (300s)
    attempts = [t for t in _pin_attempts.get(client_ip, []) if now - t < 300]
    _pin_attempts[client_ip] = attempts

    if len(attempts) >= 5:
        wait_sec = int(300 - (now - attempts[0]))
        return jsonify({
            "status": "error",
            "message": f"Too many incorrect attempts. Please wait {wait_sec} seconds."
        }), 429

    data = request.get_json(silent=True) or {}
    entered_pin = str(data.get("pin", request.form.get("pin", ""))).strip()

    if not entered_pin:
        return jsonify({"status": "error", "message": "PIN is required."}), 400

    if hmac.compare_digest(entered_pin, APP_PIN):
        session["authenticated"] = True
        session.permanent = True
        if client_ip in _pin_attempts:
            _pin_attempts.pop(client_ip, None)
        return jsonify({"status": "ok", "message": "PIN verified successfully!"}), 200
    else:
        attempts.append(now)
        _pin_attempts[client_ip] = attempts
        time.sleep(0.3)  # Anti-timing / brute-force throttle
        remaining = 5 - len(attempts)
        return jsonify({
            "status": "error",
            "message": f"Incorrect PIN. {remaining} attempt(s) remaining."
        }), 401


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """Clear session and log out."""
    session.clear()
    flash("App locked. Enter your PIN to continue.", "info")
    return redirect(url_for("index"))


@app.route("/api/sync-queue", methods=["POST"])
@login_required
def sync_queue():
    """
    Batch-insert offline workout logs in a single atomic transaction.
    Accepts JSON list or { "logs": [...] }.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "message": "No JSON payload provided."}), 400

    logs_data = payload.get("logs") if isinstance(payload, dict) else payload
    if not isinstance(logs_data, list) or len(logs_data) == 0:
        return jsonify({"status": "ok", "synced": 0, "message": "No logs to sync."}), 200

    synced_count = 0
    affected_muscles = set()

    try:
        for item in logs_data:
            ex_id = int(item.get("exercise_id", 0))
            exercise = db.session.get(Exercise, ex_id)
            if not exercise:
                continue

            date_str = item.get("date")
            if date_str:
                try:
                    log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    log_date = date.today()
            else:
                log_date = date.today()

            sets_raw = item.get("sets")
            reps_raw = item.get("reps")
            weight_raw = item.get("weight")
            time_raw = item.get("time_seconds")
            notes_raw = str(item.get("notes", "")).strip() or None

            new_log = WorkoutLog(
                date=log_date,
                exercise_id=ex_id,
                sets=int(sets_raw) if sets_raw is not None and str(sets_raw).strip() != "" else None,
                reps=int(reps_raw) if reps_raw is not None and str(reps_raw).strip() != "" else None,
                weight=float(weight_raw) if weight_raw is not None and str(weight_raw).strip() != "" else None,
                time_seconds=int(time_raw) if time_raw is not None and str(time_raw).strip() != "" else None,
                notes=notes_raw,
            )
            db.session.add(new_log)
            synced_count += 1
            affected_muscles.add(exercise.target_muscle_primary)

        db.session.commit()

        if affected_muscles:
            recalculate_muscle_progress()

        return jsonify({
            "status": "ok",
            "synced": synced_count,
            "message": f"Successfully synced {synced_count} workout set(s)."
        }), 200

    except Exception as exc:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Failed to sync batch: {str(exc)}"}), 500


@app.route("/log", methods=["POST"])
@login_required
def log_workout():
    """Save a new workout log entry."""
    try:
        exercise_id  = int(request.form.get("exercise_id", 0))
        log_date_str = request.form.get("date", date.today().isoformat())
        sets         = request.form.get("sets")
        reps         = request.form.get("reps")
        weight       = request.form.get("weight")
        time_seconds = request.form.get("time_seconds")
        notes        = request.form.get("notes", "").strip()

        exercise = db.session.get(Exercise, exercise_id)
        if not exercise:
            flash("Invalid exercise selected.", "error")
            return redirect(url_for("index"))

        new_log = WorkoutLog(
            date         = datetime.strptime(log_date_str, "%Y-%m-%d").date(),
            exercise_id  = exercise_id,
            sets         = int(sets)         if sets         else None,
            reps         = int(reps)         if reps         else None,
            weight       = float(weight)     if weight       else None,
            time_seconds = int(time_seconds) if time_seconds else None,
            notes        = notes or None,
        )
        db.session.add(new_log)
        db.session.commit()
        flash(f"✅ {exercise.name} logged successfully!", "success")

    except (ValueError, TypeError) as e:
        db.session.rollback()
        flash(f"Error saving log: {e}", "error")

    return redirect(url_for("index") + "#log-workout")


@app.route("/add-exercise", methods=["POST"])
@login_required
def add_exercise():
    """
    Phase 4 — Custom Exercise Creator.
    Accepts form fields: name, category, primary_muscle, secondary_muscle,
    benchmark_beginner, benchmark_intermediate, benchmark_advanced.
    """
    try:
        name      = request.form.get("name", "").strip()
        category  = request.form.get("category", "weight_reps")
        primary   = request.form.get("primary_muscle", "").strip()
        secondary = request.form.get("secondary_muscle", "").strip()
        b_beg     = request.form.get("benchmark_beginner",     "").strip()
        b_int     = request.form.get("benchmark_intermediate", "").strip()
        b_adv     = request.form.get("benchmark_advanced",     "").strip()

        if not name or not primary:
            flash("Exercise name and primary muscle are required.", "error")
            return redirect(url_for("index"))

        if Exercise.query.filter_by(name=name).first():
            flash(f"'{name}' already exists in your library.", "error")
            return redirect(url_for("index"))

        new_ex = Exercise(
            name                     = name,
            category                 = category,
            target_muscle_primary    = primary,
            target_muscle_secondary  = secondary or None,
            strength_level_benchmark = _bm(b_beg or "—", b_int or "—", b_adv or "—"),
        )
        db.session.add(new_ex)

        # Ensure a MuscleProgress row exists for this muscle
        if not MuscleProgress.query.filter_by(muscle_group=primary).first():
            db.session.add(MuscleProgress(muscle_group=primary, strength_level="beginner"))

        db.session.commit()
        flash(f"✅ '{name}' added to your exercise library!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error adding exercise: {e}", "error")

    return redirect(url_for("index"))


@app.route("/api/notify-rest-done", methods=["POST"])
def notify_rest_done():
    """
    Called by JS rest timer on completion.
    JSON body: { "exercise": "Bench Press", "seconds": 90 }
    """
    data          = request.get_json(silent=True) or {}
    exercise_name = data.get("exercise", "your exercise")
    rest_seconds  = int(data.get("seconds", 0))

    success = send_rest_done_notification(exercise_name, rest_seconds)
    if success:
        return jsonify({"status": "ok",    "message": "Notification sent"}), 200
    return jsonify({"status": "error", "message": "Failed to send notification"}), 500


@app.route("/api/test-notification", methods=["POST"])
def test_notification():
    """
    Phase 4 — One-tap test to verify the phone is receiving ntfy alerts.
    """
    success = send_rest_done_notification("", 0, is_test=True)
    if success:
        return jsonify({"status": "ok",    "message": "Test notification sent!"}), 200
    return jsonify({"status": "error", "message": "Failed — check ntfy topic"}), 500


# ---------------------------------------------------------------------------
# PWA Routes: Service Worker & Web App Manifest
# ---------------------------------------------------------------------------

@app.route("/sw.js")
def service_worker():
    """Serve service worker with root scope permissions."""
    response = make_response(send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/manifest.json")
def manifest():
    """Serve Web App Manifest."""
    response = make_response(send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.json"))
    response.headers["Content-Type"] = "application/manifest+json"
    return response


# ---------------------------------------------------------------------------
# Database Auto-Initialization (Runs for both WSGI / Gunicorn and Direct run)
# ---------------------------------------------------------------------------

def init_app_database():
    """Ensure database tables and initial exercise seed exist."""
    with app.app_context():
        try:
            db.create_all()
            seed_database()
        except Exception as exc:
            print(f"[init_app_database] Notice: Database setup skipped or deferred ({exc})")

init_app_database()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # host='0.0.0.0' → accessible on local Wi-Fi at http://<your-ip>:5000
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
