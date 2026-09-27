# Smart Indoor Garden

An automated plant-monitoring system for a **Raspberry Pi 3 B**. It tracks temperature and humidity (DHT11), the water-tank level (HC-SR04 ultrasonic sensor) and, optionally, soil moisture. You can water your plants remotely from a web dashboard (Flask), or let the garden water itself.

| Page | What it does |
|---|---|
| `/` | Landing page with live readings |
| `/dashboard` | Live gauges (moisture, temperature, humidity, tank), **Water Now** + **Stop**, auto-watering on/off, recent waterings |
| `/history` | 24-hour / 7-day charts with watering markers, waterings per day, full watering log, CSV export |
| `/automation` | Plant presets, moisture threshold, daily schedules, alert ranges |

**How automatic watering works**

- **Soil moisture rule:** when moisture drops below your threshold, the pump runs for the time you set. It then waits (e.g. 1 hour) so the water can soak in before checking again. This needs the optional moisture sensor.
- **Daily schedule:** water at fixed times (e.g. 08:00 for 5 s). This works without a moisture sensor.
- **Safety:** watering is refused when the tank is low (the pump never runs dry), each watering lasts at most 15 s, and there are at least 30 s between waterings. A skipped watering is recorded in the log with the reason.

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

**Soil moisture sensor (optional, for automatic watering by moisture)**

The Pi has no analog inputs, so a capacitive soil moisture sensor v1.2 needs an **ADS1115** ADC board (I2C):

| From | To |
|---|---|
| ADS1115 VDD | Pin 17 (3.3V) |
| ADS1115 GND | Pin 20 (GND) |
| ADS1115 SCL | Pin 5 (GPIO3 / SCL) |
| ADS1115 SDA | Pin 3 (GPIO2 / SDA) |
| ADS1115 ADDR | ADS1115 GND |
| Sensor VCC | Pin 17 (3.3V) - shared with the ADS1115 |
| Sensor GND | Pin 25 (GND) |
| Sensor AOUT | ADS1115 A0 |

Enable I2C once: `sudo raspi-config` → **Interface Options → I2C → Yes**, then reboot. Check it's detected with `i2cdetect -y 1`, which should show `48`.
Without this sensor, set `MOISTURE_SENSOR = None` in `config.py`. Moisture then shows "No sensor", and daily schedules still work.

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

Plant settings (moisture threshold, schedules, alert ranges, low-tank limit) are set on the website's **Automation** page and saved in `settings.json`.

Hardware settings are in `config.py`:

- `TANK_EMPTY_DISTANCE_CM` / `TANK_FULL_DISTANCE_CM`: measure your tank (sensor → bottom, sensor → full water line).
- `MOISTURE_DRY_RAW` / `MOISTURE_WET_RAW`: moisture calibration. Hold the probe in dry air and note the raw value, then put it in a glass of water and note that value. To read the raw value, run this in Thonny's shell with `app.py` stopped: `from sensors import MoistureADS1115; print(MoistureADS1115(0x48, 0).raw())`.
- `PUMP_ML_PER_SECOND`: run the pump for 10 s into a measuring cup and divide the ml by 10. This is used for the "~ml watered" figures.
- `WATER_MAX_SECONDS`, `WATER_COOLDOWN_SECONDS`: hard safety limits.
- `RELAY_ACTIVE_LOW`: set to `False` if your relay clicks ON at start-up.

History is stored in `garden.db` (SQLite, built into Python). Readings are saved once a minute and kept for 30 days. The watering log is kept permanently.

## Testing without a Pi

`python3 app.py` on any computer runs in **simulation mode** with fake sensor data and 7 days of demo history, so you can try every page. Delete `garden.db` before moving to the Pi so the demo history doesn't come along.

## Files

```
app.py            Flask server, automation engine, API
sensors.py        DHT11, HC-SR04, ADS1115 moisture and relay drivers (+ simulator)
storage.py        SQLite history + settings.json
config.py         Pins, tank size, calibration, safety limits
templates/        index, dashboard, history, automation pages
static/           styles.css, app.css, main.js, dashboard.js, history.js, automation.js
```
