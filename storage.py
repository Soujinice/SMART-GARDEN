"""SQLite history (readings + watering log) and the JSON settings file.

Uses only the Python standard library, so nothing extra to install.
"""

import copy
import json
import os
import sqlite3
import threading
import time

import config

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, config.DATABASE_FILE)
SETTINGS_PATH = os.path.join(BASE, config.SETTINGS_FILE)

_db_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "auto_enabled": True,          # water when soil is drier than the threshold
    "moisture_threshold": 35,      # %
    "auto_seconds": 5,             # how long one automatic watering lasts
    "auto_min_gap_minutes": 60,    # let water soak in before watering again
    "heat_enabled": True,          # water when it gets hot (DHT11 temperature)
    "heat_threshold": 30,          # °C - water at or above this temperature
    "heat_seconds": 5,             # how long one heat watering lasts
    "heat_gap_minutes": 60,        # wait at least this long before watering for heat again
    "schedules": [                 # fixed daily waterings (work without a moisture sensor)
        {"time": "08:00", "seconds": 5, "enabled": False},
    ],
    "temp_min": 18, "temp_max": 30,
    "humidity_min": 40, "humidity_max": 70,
    "low_water_percent": 15,       # watering is blocked below this tank level
    "buzzer_enabled": True,        # beeps for watering start/end and alerts
}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock, _connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS readings (
            ts REAL PRIMARY KEY, temperature REAL, humidity REAL,
            moisture REAL, water_level REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS waterings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, seconds REAL,
            trigger TEXT, moisture_before REAL, water_before REAL, completed INTEGER,
            note TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_water_ts ON waterings(ts)")


def add_reading(ts, temperature, humidity, moisture, water_level):
    with _db_lock, _connect() as c:
        c.execute("INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?)",
                  (ts, temperature, humidity, moisture, water_level))


def add_watering(ts, seconds, trigger, moisture_before, water_before, completed=True, note=""):
    """trigger: manual / auto / schedule. completed=False + note = skipped or stopped."""
    with _db_lock, _connect() as c:
        c.execute("""INSERT INTO waterings (ts, seconds, trigger, moisture_before,
                     water_before, completed, note) VALUES (?,?,?,?,?,?,?)""",
                  (ts, round(seconds, 1), trigger, moisture_before, water_before,
                   int(completed), note))


def readings_since(since, bucket_seconds):
    """Averages per time bucket, so a 7-day chart stays small and fast."""
    with _db_lock, _connect() as c:
        rows = c.execute("""
            SELECT CAST(ts / ? AS INTEGER) * ? AS t,
                   AVG(temperature) AS temperature, AVG(humidity) AS humidity,
                   AVG(moisture) AS moisture, AVG(water_level) AS water_level
            FROM readings WHERE ts >= ? GROUP BY t ORDER BY t""",
                         (bucket_seconds, bucket_seconds, since)).fetchall()
    return [dict(r) for r in rows]


def waterings_since(since):
    with _db_lock, _connect() as c:
        rows = c.execute("SELECT * FROM waterings WHERE ts >= ? ORDER BY ts DESC",
                         (since,)).fetchall()
    return [dict(r) for r in rows]


def last_watering():
    with _db_lock, _connect() as c:
        row = c.execute("SELECT * FROM waterings ORDER BY ts DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def prune(keep_days):
    cutoff = time.time() - keep_days * 86400
    with _db_lock, _connect() as c:
        c.execute("DELETE FROM readings WHERE ts < ?", (cutoff,))


def is_empty():
    with _db_lock, _connect() as c:
        return c.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
_settings_lock = threading.Lock()
_settings = None


def load_settings():
    global _settings
    with _settings_lock:
        s = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_PATH) as f:
                s.update(json.load(f))
        except (OSError, ValueError):
            pass
        _settings = s
        return copy.deepcopy(s)


def get_settings():
    if _settings is None:
        return load_settings()
    with _settings_lock:
        return copy.deepcopy(_settings)


def _num(v, lo, hi, cast=int):
    v = cast(v)
    if not lo <= v <= hi:
        raise ValueError("value %s out of range %s-%s" % (v, lo, hi))
    return v


def save_settings(new):
    """Validates everything coming from the browser before saving it."""
    s = get_settings()
    if "auto_enabled" in new:
        s["auto_enabled"] = bool(new["auto_enabled"])
    if "buzzer_enabled" in new:
        s["buzzer_enabled"] = bool(new["buzzer_enabled"])
    if "moisture_threshold" in new:
        s["moisture_threshold"] = _num(new["moisture_threshold"], 5, 90)
    if "auto_seconds" in new:
        s["auto_seconds"] = _num(new["auto_seconds"], config.WATER_MIN_SECONDS, config.WATER_MAX_SECONDS)
    if "auto_min_gap_minutes" in new:
        s["auto_min_gap_minutes"] = _num(new["auto_min_gap_minutes"], 1, 1440)
    if "heat_enabled" in new:
        s["heat_enabled"] = bool(new["heat_enabled"])
    if "heat_threshold" in new:
        s["heat_threshold"] = _num(new["heat_threshold"], 15, 50)
    if "heat_seconds" in new:
        s["heat_seconds"] = _num(new["heat_seconds"], config.WATER_MIN_SECONDS, config.WATER_MAX_SECONDS)
    if "heat_gap_minutes" in new:
        s["heat_gap_minutes"] = _num(new["heat_gap_minutes"], 1, 1440)
    if "low_water_percent" in new:
        s["low_water_percent"] = _num(new["low_water_percent"], 0, 50)
    for key, lo, hi in (("temp_min", 0, 50), ("temp_max", 0, 50),
                        ("humidity_min", 0, 100), ("humidity_max", 0, 100)):
        if key in new:
            s[key] = _num(new[key], lo, hi)
    if s["temp_min"] >= s["temp_max"] or s["humidity_min"] >= s["humidity_max"]:
        raise ValueError("minimum must be below maximum")
    if "schedules" in new:
        schedules = []
        for item in list(new["schedules"])[:6]:
            hh, mm = str(item["time"]).split(":")
            hh, mm = _num(hh, 0, 23), _num(mm, 0, 59)
            schedules.append({
                "time": "%02d:%02d" % (hh, mm),
                "seconds": _num(item.get("seconds", 5), config.WATER_MIN_SECONDS, config.WATER_MAX_SECONDS),
                "enabled": bool(item.get("enabled", True)),
            })
        s["schedules"] = sorted(schedules, key=lambda x: x["time"])

    global _settings
    with _settings_lock:
        _settings = s
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, SETTINGS_PATH)   # atomic: never leaves a half-written file
    return copy.deepcopy(s)
