"""
GymTracker — SQLite to Cloud Postgres Migration Utility
=========================================================
Exports existing local SQLite records (exercises, logs, and progress)
and pushes them into your cloud PostgreSQL database (Render / Railway / Neon).

Usage:
    python migrate_sqlite_to_cloud.py "postgresql://user:pass@ep-cool.region.neon.tech/gymdb"
"""

import sys
import os
import sqlite3

def run_migration(cloud_db_url: str):
    local_sqlite_path = os.path.join(os.path.dirname(__file__), "gym.db")
    if not os.path.exists(local_sqlite_path):
        print(f"[-] Local database '{local_sqlite_path}' not found.")
        return

    # Normalize postgres URL if needed
    if cloud_db_url.startswith("postgres://"):
        cloud_db_url = "postgresql://" + cloud_db_url[len("postgres://"):]

    print(f"[+] Connecting to local SQLite database: {local_sqlite_path}")
    conn_sqlite = sqlite3.connect(local_sqlite_path)
    conn_sqlite.row_factory = sqlite3.Row
    c_sqlite = conn_sqlite.cursor()

    # Read local records
    exercises = c_sqlite.execute("SELECT * FROM exercises").fetchall()
    logs = c_sqlite.execute("SELECT * FROM workout_logs").fetchall()
    progress = c_sqlite.execute("SELECT * FROM muscle_progress").fetchall()
    print(f"[+] Found {len(exercises)} exercises, {len(logs)} workout logs, and {len(progress)} muscle progress entries.")

    conn_sqlite.close()

    if not logs and not exercises:
        print("[!] No records found to migrate.")
        return

    print(f"[+] Connecting to cloud target via SQLAlchemy...")
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(cloud_db_url)
        with engine.connect() as conn:
            # Check connection
            conn.execute(text("SELECT 1"))
            print("[+] Successfully connected to cloud database.")

            # Migrate exercises
            migrated_ex = 0
            for ex in exercises:
                exists = conn.execute(
                    text("SELECT id FROM exercises WHERE name = :name"),
                    {"name": ex["name"]}
                ).fetchone()
                if not exists:
                    conn.execute(
                        text("""
                            INSERT INTO exercises (name, category, target_muscle_primary, target_muscle_secondary, strength_level_benchmark)
                            VALUES (:name, :category, :primary, :secondary, :benchmark)
                        """),
                        {
                            "name": ex["name"],
                            "category": ex["category"],
                            "primary": ex["target_muscle_primary"],
                            "secondary": ex["target_muscle_secondary"],
                            "benchmark": ex["strength_level_benchmark"],
                        }
                    )
                    migrated_ex += 1
            print(f"[+] Inserted {migrated_ex} exercises.")

            # Migrate logs
            migrated_logs = 0
            for log in logs:
                conn.execute(
                    text("""
                        INSERT INTO workout_logs (date, exercise_id, weight, reps, sets, time_seconds, notes)
                        VALUES (:date, :exercise_id, :weight, :reps, :sets, :time_seconds, :notes)
                    """),
                    {
                        "date": log["date"],
                        "exercise_id": log["exercise_id"],
                        "weight": log["weight"],
                        "reps": log["reps"],
                        "sets": log["sets"],
                        "time_seconds": log["time_seconds"],
                        "notes": log["notes"],
                    }
                )
                migrated_logs += 1
            print(f"[+] Inserted {migrated_logs} workout logs.")

            # Commit transaction
            conn.commit()
            print("[✓] Migration completed successfully!")

    except Exception as e:
        print(f"[-] Migration error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_sqlite_to_cloud.py <CLOUD_POSTGRES_DATABASE_URL>")
        sys.exit(1)
    run_migration(sys.argv[1].strip())
