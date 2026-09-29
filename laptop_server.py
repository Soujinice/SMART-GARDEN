"""Smart Indoor Garden - LAPTOP web server.

Run this on your LAPTOP (Windows, macOS or Linux) while app.py runs on the Raspberry Pi.

    Laptop  = web server: serves the website to every phone/browser and keeps the
              latest readings in memory, so pages load instantly.
    Pi      = hardware: sensors, LED, buzzer, automation and the database (app.py).

Browsers only talk to the laptop. The laptop asks the Pi for new readings twice a
second and forwards commands (Water Now, Stop, settings) to the Pi.

How to run:
    1. Start app.py on the Pi (Thonny). It prints the Pi's address.
    2. On the laptop:  pip install flask
    3. Put that address in PI_ADDRESS below (or pass it:  python laptop_server.py 192.168.1.23)
    4. Run:  python laptop_server.py
    5. Open the address it prints, e.g. http://192.168.1.40:8000
"""

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

from flask import Flask, Response, jsonify, render_template, request

import config

# ---------------------------------------------------------------------------
# Settings for the laptop
# ---------------------------------------------------------------------------
PI_ADDRESS = "http://raspberrypi.local:5000"   # <-- the address Thonny prints on the Pi
PORT = 8000                                    # the laptop's website port
POLL_SECONDS = 0.5                             # how often the laptop fetches readings from the Pi
STALE_AFTER_SECONDS = 8                        # older than this = "Garden offline"

if len(sys.argv) > 1:                          # python laptop_server.py 192.168.1.23
    arg = sys.argv[1]
    if not arg.startswith("http"):
        arg = "http://" + arg
    if arg.count(":") < 2:                     # no port given -> use the Pi's default
        arg += ":%d" % config.PORT
    PI_ADDRESS = arg
PI = PI_ADDRESS.rstrip("/")

app = Flask(__name__)
cache = {"status": None, "at": 0.0, "error": "Connecting to the Raspberry Pi…"}


@app.context_processor
def inject_refresh():
    return {"refresh_ms": int(max(0.5, config.WEB_REFRESH_SECONDS) * 1000)}


# ---------------------------------------------------------------------------
# Talking to the Pi
# ---------------------------------------------------------------------------
def pi_request(path, method="GET", body=None, timeout=5):
    """Returns (status_code, body_bytes, headers). Never raises."""
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(PI + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:            # the Pi answered with an error (e.g. 409)
        return e.code, e.read(), e.headers
    except (urllib.error.URLError, OSError):        # the Pi is off, wrong address, no Wi-Fi
        msg = {"ok": False, "error": "Raspberry Pi not reachable at %s" % PI}
        return 503, json.dumps(msg).encode(), {"Content-Type": "application/json"}


def poll_loop():
    """Keeps the newest readings in memory so browsers never wait for the Pi."""
    was_ok = None
    while True:
        code, body, _ = pi_request("/api/status", timeout=3)
        if code == 200:
            cache.update(status=body, at=time.time(), error=None)
            if was_ok is not True:
                print("Connected to the Raspberry Pi at %s" % PI)
            was_ok = True
        else:
            cache["error"] = "Raspberry Pi not reachable at %s" % PI
            if was_ok is not False:
                print("Waiting for the Raspberry Pi at %s … (is app.py running?)" % PI)
            was_ok = False
        time.sleep(POLL_SECONDS)


def cached_status():
    if cache["status"] and time.time() - cache["at"] < STALE_AFTER_SECONDS:
        try:
            return json.loads(cache["status"])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Pages (served by the laptop)
# ---------------------------------------------------------------------------
def moisture_flags():
    s = cached_status()
    if s:
        return s.get("has_moisture", False), s.get("moisture_simulated", False)
    return config.MOISTURE_SENSOR is not None, config.MOISTURE_SENSOR == "simulated"


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
    has_moisture, simulated = moisture_flags()
    return render_template("automation.html", cfg=config, has_moisture=has_moisture,
                           moisture_simulated=simulated)


# ---------------------------------------------------------------------------
# API: live status from memory, everything else forwarded to the Pi
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    if cache["status"] and time.time() - cache["at"] < STALE_AFTER_SECONDS:
        return Response(cache["status"], mimetype="application/json",
                        headers={"Cache-Control": "no-store"})
    return jsonify(ok=False, error=cache["error"] or "Raspberry Pi not reachable"), 503


@app.route("/api/<path:sub>", methods=["GET", "POST"])
def api_forward(sub):
    path = "/api/" + sub
    if request.query_string:
        path += "?" + request.query_string.decode()
    body = (request.get_data() or b"{}") if request.method == "POST" else None
    code, data, headers = pi_request(path, method=request.method, body=body, timeout=10)
    out = Response(data, status=code, mimetype=headers.get("Content-Type", "application/json"))
    if headers.get("Content-Disposition"):          # CSV download keeps its file name
        out.headers["Content-Disposition"] = headers["Content-Disposition"]
    if request.method == "POST" and code == 200:     # show the change right away
        refresh_now()
    return out


def refresh_now():
    code, body, _ = pi_request("/api/status", timeout=3)
    if code == 200:
        cache.update(status=body, at=time.time(), error=None)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    if not port_is_free(PORT):
        print("Port %d is already in use - is laptop_server.py already running?" % PORT)
        sys.exit(1)
    threading.Thread(target=poll_loop, daemon=True).start()
    ip = local_ip()
    print("")
    print("=" * 60)
    print(" LAPTOP web server - the Pi does the sensors and watering")
    print(" Raspberry Pi:  %s" % PI)
    print(" Open the website:")
    if ip and not ip.startswith("127."):
        print("   http://%s:%d     (phones/laptops on this Wi-Fi)" % (ip, PORT))
    print("   http://localhost:%d        (on this laptop)" % PORT)
    print("=" * 60)
    print("")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
