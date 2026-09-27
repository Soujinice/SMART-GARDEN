# Smart Indoor Garden

An automated plant-monitoring system for a **Raspberry Pi 3 B**. It tracks temperature and humidity (DHT11) and the water-tank level (HC-SR04 ultrasonic sensor), and lets you water your plants remotely from a web dashboard (Flask).

| Page | What it shows |
|---|---|
| `/` | Landing page with live readings |
| `/dashboard` | Health status, temperature, humidity, tank level, **Water Now** |
| `/wiring` | Pin-by-pin wiring and safety checklist |

## 1. Wiring (power the Pi OFF first)

Pin numbers are **physical** header pins (Pin 1 is the square pad at the SD-card end).

**DHT11** (temperature & humidity)

| DHT11 | Raspberry Pi |
|---|---|
| VCC (+) | Pin 1 (3.3V) |
| DATA | Pin 7 (GPIO4) |
| GND (−) | Pin 6 (GND) |

A bare 4-pin DHT11 (not on a small board) also needs a 10 kΩ resistor between DATA and VCC.

**HC-SR04** (water-tank level, mounted on the tank lid facing down)

| HC-SR04 | Raspberry Pi |
|---|---|
| VCC | Pin 2 (5V) |
| TRIG | Pin 16 (GPIO23) |
| ECHO | **1 kΩ resistor** → Pin 18 (GPIO24) |
| GND | Pin 14 (GND) |

⚠️ ECHO outputs 5V, and the Pi's GPIO pins take a maximum of 3.3V. Always use the voltage divider:

```
ECHO ── 1k ──┬── Pin 18 (GPIO24)
             │
             └── 2k ── GND (Pin 14)
```

**Relay + pump (optional, only needed for real watering)**

| Relay module | Raspberry Pi |
|---|---|
| VCC | Pin 4 (5V) |
| IN | Pin 11 (GPIO17) |
| GND | Pin 9 (GND) |

The pump gets its **own** 5V supply: supply (+) → relay COM, relay NO → pump (+), pump (−) → supply (−). Never power the pump from the Pi.
Without a relay, set `PUMP_RELAY_PIN = None` in `config.py`. The dashboard then shows "No pump connected".

## 2. Install (on the Pi)

Flask and RPi.GPIO come pre-installed on Raspberry Pi OS (with desktop). If Flask is missing:

```bash
sudo apt install python3-flask
```

Optional, for more reliable DHT11 readings (the app uses its own built-in reader if this isn't installed):

```bash
pip3 install adafruit-circuitpython-dht --break-system-packages
```

(In Thonny you can also use **Tools → Manage packages…** and search for `adafruit-circuitpython-dht`.)

## 3. Run with Thonny

1. Copy this folder to the Pi, e.g. `/home/pi/SMART-GARDEN`.
2. Open `app.py` in Thonny and press **Run** (F5).
3. Find the Pi's IP address with `hostname -I` in a terminal.
4. On your phone or laptop (same Wi-Fi), open `http://<pi-ip>:5000`.

Press **Stop** in Thonny to shut it down. The pump relay is always switched off on exit.

## 4. Configure

Edit `config.py`:

- `TANK_EMPTY_DISTANCE_CM` / `TANK_FULL_DISTANCE_CM`: measure your tank (sensor → bottom, sensor → full water line).
- `LOW_WATER_PERCENT`: watering is blocked below this level, so the pump never runs dry.
- `TEMP_RANGE_C`, `HUMIDITY_RANGE`: the comfort range for your plants.
- `WATER_MAX_SECONDS`, `WATER_COOLDOWN_SECONDS`: safety limits for remote watering.
- `RELAY_ACTIVE_LOW`: set to `False` if your relay clicks ON at start-up.

## Testing without a Pi

`python3 app.py` on any computer runs in **simulation mode** with fake sensor data, so you can work on the website.

## Files

```
app.py            Flask server + API (/api/status, /api/water)
sensors.py        DHT11, HC-SR04 and relay drivers (+ simulator)
config.py         Pins, tank size, thresholds
templates/        index.html, dashboard.html, wiring.html
static/           styles.css, app.css, main.js, dashboard.js, assets/, fonts/
```
