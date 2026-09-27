"""Smart Indoor Garden - Flask web server.

Run it from Thonny (open this file, press Run / F5) or from a terminal:
    python3 app.py
Then open http://<raspberry-pi-ip>:5000 on any device on the same Wi-Fi.
"""

import atexit
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
from sensors import Garden, distance_to_percent

app = Flask(__name__)
garden = Garden()

state_lock = threading.Lock()
state = {
    "temperature": None,
    "humidity": None,
    "tank_distance": None,
    "water_level": None,
    "updated": None,
    "watering": False,
    "last_watered": None,
    "waterings": [],   # timestamps of today's waterings
}


def sensor_loop():
    """Reads the sensors in the background so web requests never wait on hardware."""
    while True:
        climate = garden.read_climate()
        distance = garden.read_tank_distance()
        with state_lock:
            if climate:
                state["temperature"], state["humidity"] = climate
            if distance is not None:
                state["tank_distance"] = distance
                state["water_level"] = distance_to_percent(distance)
            state["updated"] = time.time()
        time.sleep(config.SENSOR_INTERVAL_SECONDS)


def health(s):
    """Returns (level, message) - level is ok / warn / alert."""
    if s["temperature"] is None or s["water_level"] is None:
        return "warn", "Waiting for sensor data"
    if s["water_level"] < config.LOW_WATER_PERCENT:
        return "alert", "Water tank low - please refill"
    lo, hi = config.TEMP_RANGE_C
    if s["temperature"] > hi:
        return "warn", "Too warm for the plants"
    if s["temperature"] < lo:
        return "warn", "Too cold for the plants"
    lo, hi = config.HUMIDITY_RANGE
    if s["humidity"] < lo:
        return "warn", "Air is too dry"
    if s["humidity"] > hi:
        return "warn", "Air is too humid"
    return "ok", "Plants are healthy"


def today_count(stamps):
    today = datetime.now().date()
    return sum(1 for t in stamps if datetime.fromtimestamp(t).date() == today)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", cfg=config)


# Raspberry Pi 3 B 40-pin header: physical pin -> label
HEADER = {
    1: "3.3V", 2: "5V", 3: "GPIO2", 4: "5V", 5: "GPIO3", 6: "GND", 7: "GPIO4",
    8: "GPIO14", 9: "GND", 10: "GPIO15", 11: "GPIO17", 12: "GPIO18", 13: "GPIO27",
    14: "GND", 15: "GPIO22", 16: "GPIO23", 17: "3.3V", 18: "GPIO24", 19: "GPIO10",
    20: "GND", 21: "GPIO9", 22: "GPIO25", 23: "GPIO11", 24: "GPIO8", 25: "GND",
    26: "GPIO7", 27: "ID_SD", 28: "ID_SC", 29: "GPIO5", 30: "GND", 31: "GPIO6",
    32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "GPIO19", 36: "GPIO16", 37: "GPIO26",
    38: "GPIO20", 39: "GND", 40: "GPIO21",
}


def phys(bcm):
    """BCM number -> physical header pin."""
    return next(p for p, name in HEADER.items() if name == "GPIO%d" % bcm)


def wiring_table():
    parts = [
        {"id": "dht", "name": "DHT11 (temperature & humidity)", "rows": [
            ("VCC / +", 1, "3.3V power - not 5V, keeps DATA at a safe 3.3V"),
            ("DATA / OUT", phys(config.DHT11_PIN), "Bare 4-pin sensor: add 10 k\u03a9 from DATA to VCC"),
            ("GND / -", 6, "Ground"),
        ]},
        {"id": "sonar", "name": "HC-SR04 ultrasonic (water tank level)", "rows": [
            ("VCC", 2, "5V power"),
            ("TRIG", phys(config.ULTRASONIC_TRIG), "Direct connection is safe (Pi -> sensor)"),
            ("ECHO", phys(config.ULTRASONIC_ECHO), "Through a voltage divider only - see below"),
            ("GND", 14, "Ground (also the bottom of the 2 k\u03a9 resistor)"),
        ]},
    ]
    if config.PUMP_RELAY_PIN is not None:
        parts.append({"id": "relay", "name": "Relay module + pump (optional, for watering)", "rows": [
            ("VCC", 4, "5V power for the relay coil"),
            ("IN", phys(config.PUMP_RELAY_PIN), "Control signal"),
            ("GND", 9, "Ground"),
        ]})
    used = {pin: part["id"] for part in parts for _, pin, _ in part["rows"]}
    return parts, used


@app.route("/wiring")
def wiring():
    parts, used = wiring_table()
    return render_template("wiring.html", parts=parts, used=used, header=HEADER)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    with state_lock:
        s = dict(state)
    level, message = health(s)
    return jsonify(
        temperature=s["temperature"],
        humidity=s["humidity"],
        water_level=s["water_level"],
        tank_distance=s["tank_distance"],
        status=level,
        message=message,
        watering=s["watering"],
        last_watered=s["last_watered"],
        waterings_today=today_count(s["waterings"]),
        pump_connected=garden.has_pump,
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
    seconds = max(config.WATER_MIN_SECONDS, min(config.WATER_MAX_SECONDS, seconds))

    with state_lock:
        if state["watering"]:
            return jsonify(ok=False, error="Already watering"), 409
        last = state["last_watered"]
        if last and time.time() - last < config.WATER_COOLDOWN_SECONDS:
            wait = int(config.WATER_COOLDOWN_SECONDS - (time.time() - last))
            return jsonify(ok=False, error="Please wait %ds before watering again" % wait), 429
        level = state["water_level"]
        if level is not None and level < config.LOW_WATER_PERCENT:
            return jsonify(ok=False, error="Tank too low - refill before watering"), 409
        if not garden.has_pump:
            return jsonify(ok=False, error="No pump connected (see config.py)"), 409
        state["watering"] = True

    def run():
        try:
            garden.run_pump(seconds)
        finally:
            with state_lock:
                now = time.time()
                state["watering"] = False
                state["last_watered"] = now
                state["waterings"] = [t for t in state["waterings"] if now - t < 86400] + [now]

    threading.Thread(target=run, daemon=True).start()
    return jsonify(ok=True, seconds=seconds)


atexit.register(garden.cleanup)

if __name__ == "__main__":
    threading.Thread(target=sensor_loop, daemon=True).start()
    print("Smart Garden running - open http://<your-pi-ip>:%d" % config.PORT)
    if garden.simulated:
        print("(No Raspberry Pi GPIO found - using simulated sensor data)")
    # use_reloader=False: the reloader would start the GPIO code twice (breaks in Thonny)
    app.run(host=config.HOST, port=config.PORT, debug=False,
            threaded=True, use_reloader=False)
