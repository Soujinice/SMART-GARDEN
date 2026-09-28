"""Smart Indoor Garden - Flask web server.

Run it from Thonny (open this file, press Run / F5) or from a terminal:
    python3 app.py
Then open http://<raspberry-pi-ip>:5000 on any device on the same Wi-Fi.
"""

import atexit
import csv
import io
import math
import random
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

import config
import storage
from sensors import BEEP_ALERT, Garden, distance_to_percent

app = Flask(__name__)
storage.init_db()
storage.load_settings()
garden = Garden()

state_lock = threading.Lock()
state = {
    "temperature": None,
    "humidity": None,
    "moisture": None,
    "tank_distance": None,
    "water_level": None,
    "updated": None,
    "watering": None,        # {"trigger", "seconds", "started"} while watering
}
last = storage.last_watering()
last_watered = last["ts"] if last and last["completed"] else None


# ---------------------------------------------------------------------------
# Watering (shared by the button, the moisture rule and the schedules)
# ---------------------------------------------------------------------------
def start_watering(seconds, trigger):
    """Starts watering (LED + buzzer) in the background. Returns None, or an error message."""
    global last_watered
    settings = storage.get_settings()
    seconds = max(config.WATER_MIN_SECONDS, min(config.WATER_MAX_SECONDS, int(seconds)))
    with state_lock:
        if state["watering"]:
            return "Already watering"
        if last_watered and time.time() - last_watered < config.WATER_COOLDOWN_SECONDS:
            wait = int(config.WATER_COOLDOWN_SECONDS - (time.time() - last_watered)) + 1
            return "Please wait %d s before watering again" % wait
        level = state["water_level"]
        if level is not None and level < settings["low_water_percent"]:
            return "Tank too low - refill before watering"
        if not garden.has_output:
            return "No LED/buzzer connected (see config.py)"
        moisture_before = state["moisture"]
        state["watering"] = {"trigger": trigger, "seconds": seconds, "started": time.time()}

    def run():
        global last_watered
        started = time.time()
        ran = seconds
        try:
            ran = garden.run_watering(seconds, sound=settings["buzzer_enabled"])
        finally:
            stopped = ran < seconds - 0.5
            with state_lock:
                state["watering"] = None
                last_watered = time.time()
            storage.add_watering(started, ran, trigger, moisture_before, level,
                                 completed=True, note="Stopped early" if stopped else "")

    threading.Thread(target=run, daemon=True).start()
    return None


def log_skipped(trigger, reason):
    with state_lock:
        m, w = state["moisture"], state["water_level"]
    storage.add_watering(time.time(), 0, trigger, m, w, completed=False, note=reason)
    if storage.get_settings()["buzzer_enabled"]:
        garden.beep(BEEP_ALERT)


# ---------------------------------------------------------------------------
# Buzzer alerts: beep when a problem starts, and remind every 30 min while it lasts
# ---------------------------------------------------------------------------
ALERT_REMIND_SECONDS = 30 * 60
alert_state = {"level": "ok", "last_beep": 0}


def check_alert_beep(snap):
    settings = storage.get_settings()
    level, _ = health(snap, settings)
    now = time.time()
    became_alert = level == "alert" and alert_state["level"] != "alert"
    remind = level == "alert" and now - alert_state["last_beep"] > ALERT_REMIND_SECONDS
    alert_state["level"] = level
    if (became_alert or remind) and settings["buzzer_enabled"]:
        alert_state["last_beep"] = now
        garden.beep(BEEP_ALERT)


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------
fired_schedules = set()   # "YYYY-MM-DD HH:MM" already handled
last_auto_check = 0


def run_automation():
    global last_auto_check
    s = storage.get_settings()
    now = datetime.now()

    # 1) Fixed daily schedules
    for item in s["schedules"]:
        key = now.strftime("%Y-%m-%d ") + item["time"]
        if item["enabled"] and now.strftime("%H:%M") == item["time"] and key not in fired_schedules:
            fired_schedules.add(key)
            error = start_watering(item["seconds"], "schedule")
            if error:
                log_skipped("schedule", error)

    # 2) Moisture threshold (once a minute is plenty)
    if not (s["auto_enabled"] and garden.has_moisture) or time.time() - last_auto_check < 60:
        return
    last_auto_check = time.time()
    with state_lock:
        moisture, busy = state["moisture"], state["watering"]
    if moisture is None or busy or moisture >= s["moisture_threshold"]:
        return
    if last_watered and time.time() - last_watered < s["auto_min_gap_minutes"] * 60:
        return   # give the last watering time to soak in
    error = start_watering(s["auto_seconds"], "auto")
    if error and "wait" not in error:
        log_skipped("auto", error)
        last_auto_check = time.time() + 30 * 60   # don't log the same problem every minute


def next_schedule(s):
    now = datetime.now()
    upcoming = []
    for item in s["schedules"]:
        if not item["enabled"]:
            continue
        hh, mm = map(int, item["time"].split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        upcoming.append(t)
    return min(upcoming).timestamp() if upcoming else None


# ---------------------------------------------------------------------------
# Background sensor loop
# ---------------------------------------------------------------------------
def sensor_loop():
    last_log = 0
    last_prune = 0
    while True:
        climate = garden.read_climate()
        distance = garden.read_tank_distance()
        moisture = garden.read_moisture()
        now = time.time()
        with state_lock:
            if climate:
                state["temperature"], state["humidity"] = climate
            if distance is not None:
                state["tank_distance"] = distance
                state["water_level"] = distance_to_percent(distance)
            if moisture is not None:
                state["moisture"] = moisture
            state["updated"] = now
            snap = dict(state)

        if now - last_log >= config.LOG_INTERVAL_SECONDS and snap["temperature"] is not None:
            last_log = now
            storage.add_reading(now, snap["temperature"], snap["humidity"],
                                snap["moisture"], snap["water_level"])
        if now - last_prune > 86400:
            last_prune = now
            storage.prune(config.KEEP_DAYS)
        try:
            check_alert_beep(snap)
            run_automation()
        except Exception as exc:   # never let automation kill the sensor loop
            print("Automation error:", exc)
        time.sleep(config.SENSOR_INTERVAL_SECONDS)


def seed_demo_history():
    """Simulation only: fills 7 days of believable history so the charts aren't empty."""
    if not storage.is_empty():
        return
    now = time.time()
    moisture, tank = 60.0, 95.0
    for i in range(7 * 24 * 12, 0, -1):          # every 5 minutes, 7 days
        ts = now - i * 300
        hour = datetime.fromtimestamp(ts).hour + datetime.fromtimestamp(ts).minute / 60
        temp = 23 + 3.5 * math.sin((hour - 9) / 24 * 2 * math.pi) + random.uniform(-0.4, 0.4)
        hum = 55 - 8 * math.sin((hour - 9) / 24 * 2 * math.pi) + random.uniform(-1.5, 1.5)
        moisture -= random.uniform(0.15, 0.3)
        if moisture < 35:
            storage.add_watering(ts, 5, "auto", round(moisture), round(tank))
            moisture += 22
            tank -= 6
        if int(hour * 12) == 8 * 12:
            storage.add_watering(ts, 5, "schedule", round(moisture), round(tank))
            moisture += 20
            tank -= 6
        if tank < 30:
            tank = 95.0
        storage.add_reading(ts, round(temp, 1), round(hum), round(moisture, 1), round(tank))
    storage.add_watering(now - 5400, 3, "manual", 41, round(tank))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", cfg=config)


@app.route("/history")
def history():
    return render_template("history.html")


@app.route("/automation")
def automation():
    return render_template("automation.html", cfg=config, has_moisture=garden.has_moisture,
                           moisture_simulated=garden.moisture_simulated)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def health(s, settings):
    """Returns (level, message) - level is ok / warn / alert."""
    if s["temperature"] is None or s["water_level"] is None:
        return "warn", "Waiting for sensor data"
    if s["water_level"] < settings["low_water_percent"]:
        return "alert", "Water tank low - please refill"
    if s["moisture"] is not None and s["moisture"] < settings["moisture_threshold"]:
        return "warn", "Soil is dry"
    if s["temperature"] > settings["temp_max"]:
        return "warn", "Too warm for the plants"
    if s["temperature"] < settings["temp_min"]:
        return "warn", "Too cold for the plants"
    if s["humidity"] < settings["humidity_min"]:
        return "warn", "Air is too dry"
    if s["humidity"] > settings["humidity_max"]:
        return "warn", "Air is too humid"
    return "ok", "Plants are healthy"


def start_of_today():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


@app.route("/api/status")
def api_status():
    settings = storage.get_settings()
    with state_lock:
        s = dict(state)
    level, message = health(s, settings)
    today = [w for w in storage.waterings_since(start_of_today()) if w["completed"]]
    recent = storage.waterings_since(time.time() - 7 * 86400)[:4]
    watering = s["watering"]
    if watering:
        watering = dict(watering, remaining=max(0, watering["started"] + watering["seconds"] - time.time()))
    return jsonify(
        temperature=s["temperature"],
        humidity=s["humidity"],
        moisture=s["moisture"],
        water_level=s["water_level"],
        status=level,
        message=message,
        watering=watering,
        last_watered=last_watered,
        waterings_today=len(today),
        water_used_today_ml=round(sum(w["seconds"] for w in today) * config.PUMP_ML_PER_SECOND),
        recent=recent,
        next_schedule=next_schedule(settings),
        settings=settings,
        has_moisture=garden.has_moisture,
        moisture_simulated=garden.moisture_simulated,
        output_connected=garden.has_output,
        simulated=garden.simulated,
        updated=s["updated"],
    )


@app.route("/api/water", methods=["POST"])
def api_water():
    body = request.get_json(silent=True) or {}
    try:
        seconds = int(body.get("seconds", 5))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Invalid duration"), 400
    error = start_watering(seconds, "manual")
    if error:
        return jsonify(ok=False, error=error), 409
    return jsonify(ok=True, seconds=max(config.WATER_MIN_SECONDS, min(config.WATER_MAX_SECONDS, seconds)))


@app.route("/api/stop", methods=["POST"])
def api_stop():
    garden.stop_watering()
    return jsonify(ok=True)


@app.route("/api/test-outputs", methods=["POST"])
def api_test_outputs():
    """Blinks the LED and beeps once, to check the wiring."""
    with state_lock:
        if state["watering"]:
            return jsonify(ok=False, error="Wait until watering has finished"), 409
    sound = storage.get_settings()["buzzer_enabled"]
    threading.Thread(target=garden.test_outputs, args=(sound,), daemon=True).start()
    return jsonify(ok=True, sound=sound)


@app.route("/api/history")
def api_history():
    days = 7 if request.args.get("range") == "7d" else 1
    since = time.time() - days * 86400
    bucket = 1800 if days == 7 else 300
    points = storage.readings_since(since, bucket)
    for p in points:
        for k in ("temperature", "humidity", "moisture", "water_level"):
            if p[k] is not None:
                p[k] = round(p[k], 1)
    waterings = [w for w in storage.waterings_since(since) if w["completed"]]
    return jsonify(points=points, waterings=waterings, since=since)


@app.route("/api/log")
def api_log():
    try:
        days = max(1, min(config.KEEP_DAYS, int(request.args.get("days", 7))))
    except ValueError:
        days = 7
    events = storage.waterings_since(time.time() - days * 86400)
    return jsonify(events=events, ml_per_second=config.PUMP_ML_PER_SECOND)


@app.route("/api/log.csv")
def api_log_csv():
    events = storage.waterings_since(time.time() - config.KEEP_DAYS * 86400)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "time", "trigger", "seconds", "approx_ml", "soil_moisture_before_%",
                "tank_before_%", "result"])
    for e in events:
        dt = datetime.fromtimestamp(e["ts"])
        w.writerow([dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"), e["trigger"], e["seconds"],
                    round(e["seconds"] * config.PUMP_ML_PER_SECOND),
                    e["moisture_before"], e["water_before"],
                    e["note"] or ("Done" if e["completed"] else "Skipped")])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=watering-log.csv"})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        try:
            s = storage.save_settings(request.get_json(silent=True) or {})
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error="Invalid setting: %s" % exc), 400
        return jsonify(ok=True, settings=s)
    return jsonify(storage.get_settings())


atexit.register(garden.cleanup)
# "Stop" in Thonny / kill: exit normally so cleanup runs and the LED + buzzer switch off
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    if not port_is_free(config.PORT):
        print("\n*** Smart Garden is ALREADY RUNNING (port %d is in use). ***" % config.PORT)
        print("Another copy of app.py is still running (maybe from a terminal or an earlier run).")
        print("Fix: open a Terminal and run:   pkill -f app.py")
        print("     (or simply reboot the Pi), then press Run again.\n")
        sys.exit(1)
    if garden.simulated:
        seed_demo_history()
        last = storage.last_watering()
        last_watered = last["ts"] if last else None
    threading.Thread(target=sensor_loop, daemon=True).start()
    print("Smart Garden running - open http://<your-pi-ip>:%d" % config.PORT)
    if garden.simulated:
        print("(No Raspberry Pi GPIO found - using simulated sensor data)")
    # use_reloader=False: the reloader would start the GPIO code twice (breaks in Thonny)
    app.run(host=config.HOST, port=config.PORT, debug=False,
            threaded=True, use_reloader=False)
