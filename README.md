# Smart Indoor Garden

An automated plant-monitoring system for a **Raspberry Pi 3 B**. It tracks temperature and humidity (DHT11), the water-tank level (HC-SR04 ultrasonic sensor) and, optionally, soil moisture. You can water remotely from a web dashboard (Flask), or let the garden water itself. An **LED** lights up while watering and a **buzzer** beeps for watering and alerts; they stand in for a pump.

| Page | What it does |
|---|---|
| `/` | Landing page with live readings |
| `/dashboard` | Live gauges (moisture, temperature, humidity, tank), **Water Now** + **Stop**, auto-watering on/off, recent waterings |
| `/history` | 24-hour / 7-day charts with watering markers, waterings per day, full watering log, CSV export |
| `/automation` | Plant presets, moisture threshold, daily schedules, alert ranges |

**How automatic watering works**

- **Soil moisture rule:** when moisture drops below your threshold, the garden waters for the time you set (LED on + beeps). It then waits (e.g. 1 hour) so the water can soak in before checking again. This needs the optional moisture sensor.
- **Daily schedule:** water at fixed times (e.g. 08:00 for 5 s). This works without a moisture sensor.
- **Safety:** watering is refused when the tank is low, each watering lasts at most 15 s, and there are at least 30 s between waterings. A skipped watering is recorded in the log with the reason.

## 1. Wiring (power the Pi OFF first)

Pin numbers are **physical** header pins. Pin 1 is the square pad at the SD-card end; odd pins (1, 3, 5…) are on the inner row and even pins (2, 4, 6…) are on the outer edge. A picture of every connection is in [`docs/wiring.png`](docs/wiring.png).

### All connections at a glance

| Pi pin | Name | Goes to |
|---|---|---|
| 1 | 3.3V | DHT11 VCC (+) |
| 2 | 5V | HC-SR04 VCC |
| 3 | GPIO2 (SDA) | ADS1115 SDA *(optional moisture)* |
| 4 | 5V | Buzzer (+) *(transistor circuit only)* |
| 5 | GPIO3 (SCL) | ADS1115 SCL *(optional moisture)* |
| 6 | GND | DHT11 GND (−) |
| 7 | GPIO4 | DHT11 DATA |
| 9 | GND | LED short leg (−) |
| 11 | GPIO17 | 330 Ω resistor → LED long leg (+) |
| 13 | GPIO27 | Buzzer (+), or 1 kΩ → transistor base |
| 14 | GND | HC-SR04 GND + bottom of the 2 kΩ resistor |
| 16 | GPIO23 | HC-SR04 TRIG |
| 17 | 3.3V | ADS1115 VDD + moisture sensor VCC *(optional)* |
| 18 | GPIO24 | HC-SR04 ECHO through the voltage divider |
| 20 | GND | Buzzer (−), or transistor emitter |
| 25 | GND | ADS1115 GND + ADDR *(optional)* |
| 30 | GND | Moisture sensor GND *(optional)* |

### DHT11 (temperature & humidity)

| DHT11 | Raspberry Pi |
|---|---|
| VCC (+) | Pin 1 (3.3V) |
| DATA (OUT) | Pin 7 (GPIO4) |
| GND (−) | Pin 6 (GND) |

A bare 4-pin DHT11 (not on a small board) also needs a 10 kΩ resistor between DATA and VCC. Leave the 3rd pin unconnected.

### HC-SR04 (water-tank level, mounted on the tank lid facing down)

| HC-SR04 | Raspberry Pi |
|---|---|
| VCC | Pin 2 (5V) |
| TRIG | Pin 16 (GPIO23) |
| ECHO | **1 kΩ resistor** → Pin 18 (GPIO24) |
| GND | Pin 14 (GND) |

⚠️ ECHO outputs 5V, and the Pi's GPIO pins take a maximum of 3.3V. Always use the voltage divider:

```
ECHO ── 1kΩ ──┬── Pin 18 (GPIO24)
              │
              └── 2kΩ ── GND (Pin 14)
```

No 2 kΩ resistor? Use two 1 kΩ in series.

### LED (watering indicator, on while watering)

```
Pin 11 (GPIO17) ── 330Ω ── LED long leg (+)
                           LED short leg (−) ── Pin 9 (GND)
```

- The resistor is **required** (220–470 Ω all work). Without it the LED can damage the GPIO pin.
- The long leg is + (anode). The short leg, on the flat side of the LED rim, is − (cathode).

### Buzzer (beeps at watering start/end and on alerts)

**Option A – simple (small active buzzer):**

```
Pin 13 (GPIO27) ── Buzzer (+)   (the longer leg / marked "+")
Pin 20 (GND)    ── Buzzer (−)
```

**Option B – safer and louder (recommended if you have an NPN transistor such as S8050, 2N2222 or BC547):**

```
Pin 4 (5V) ──────────────── Buzzer (+)
                            Buzzer (−) ── Collector (C)
Pin 13 (GPIO27) ── 1kΩ ──── Base (B)
Pin 20 (GND) ────────────── Emitter (E)
```

The transistor takes the buzzer's current, so the GPIO pin only supplies a tiny base current. Check your transistor's datasheet for which leg is E, B and C.

**Active or passive buzzer?** An *active* buzzer has a sealed black bottom and beeps as soon as it gets power. A *passive* buzzer shows a green circuit board underneath and needs a tone. The default is active; for a passive one, set `BUZZER_TYPE = "passive"` in `config.py`.

**What the beeps mean:** 2 short beeps = watering starts, 1 long beep = watering done, 3 beeps = problem (tank low; repeated every 30 min). You can mute the buzzer and test both parts on the **Automation** page.

### Soil moisture sensor (optional, for automatic watering by moisture)

The Pi has no analog inputs, so a capacitive soil moisture sensor v1.2 needs an **ADS1115** ADC board (I2C):

| From | To |
|---|---|
| ADS1115 VDD | Pin 17 (3.3V) |
| ADS1115 GND | Pin 25 (GND) |
| ADS1115 ADDR | ADS1115 GND (same row on the breadboard) |
| ADS1115 SCL | Pin 5 (GPIO3 / SCL) |
| ADS1115 SDA | Pin 3 (GPIO2 / SDA) |
| Sensor VCC | ADS1115 VDD row on the breadboard (3.3V) |
| Sensor GND | Pin 30 (GND) |
| Sensor AOUT | ADS1115 A0 |

Enable I2C once: `sudo raspi-config` → **Interface Options → I2C → Yes**, then reboot. Check it's detected with `i2cdetect -y 1`, which should show `48`.
Then set `MOISTURE_SENSOR = "ads1115"` in `config.py`. The default is `None` (no moisture sensor): moisture then shows "No sensor", and daily schedules still work.

### Safety checklist

- Power the Pi off before changing any wire.
- Never connect HC-SR04 ECHO straight to the Pi. Always use the divider.
- The DHT11 and moisture parts go on 3.3V (Pins 1 / 17), not 5V.
- Always use the LED resistor.
- Never touch a 5V pin (2 / 4) to any GPIO pin.
- Keep water away from the Pi and the breadboard.

## Troubleshooting

| Message in Thonny | Fix |
|---|---|
| `Smart Garden is ALREADY RUNNING (port 5000 is in use)` or `Address already in use` | An old copy is still running. In a Terminal run `pkill -f app.py` (or reboot), then press Run again. |
| `Unable to set line 4 to input` | Same cause: the old copy still holds the DHT11 pin. Run `pkill -f app.py` and `pkill -f libgpiod_pulsein`, then Run again. |
| `Moisture sensor not found (I2C is off …)` | Only matters if you have the ADS1115: enable I2C in `raspi-config`. Otherwise keep `MOISTURE_SENSOR = None`. |
| Temperature shows `--` | Check the DHT11 wires (Pins 1, 7, 6). The first reading can take up to 10 s. |

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

Press **Stop** in Thonny to shut it down. The LED and buzzer are always switched off on exit.

## 4. Configure

Plant settings (moisture threshold, schedules, alert ranges, low-tank limit) are set on the website's **Automation** page and saved in `settings.json`.

Hardware settings are in `config.py`:

- `TANK_EMPTY_DISTANCE_CM` / `TANK_FULL_DISTANCE_CM`: measure your tank (sensor → bottom, sensor → full water line).
- `MOISTURE_DRY_RAW` / `MOISTURE_WET_RAW`: moisture calibration. Hold the probe in dry air and note the raw value, then put it in a glass of water and note that value. To read the raw value, run this in Thonny's shell with `app.py` stopped: `from sensors import MoistureADS1115; print(MoistureADS1115(0x48, 0).raw())`.
- `PUMP_ML_PER_SECOND`: the estimate behind the "~ml watered" figures. It's only meaningful if you add a real pump later.
- `WATER_MAX_SECONDS`, `WATER_COOLDOWN_SECONDS`: hard safety limits.
- `LED_PIN`, `BUZZER_PIN`, `BUZZER_TYPE`: the watering indicator. Set a pin to `None` if that part isn't connected.

History is stored in `garden.db` (SQLite, built into Python). Readings are saved once a minute and kept for 30 days. The watering log is kept permanently.

## Testing without a Pi

`python3 app.py` on any computer runs in **simulation mode** with fake sensor data and 7 days of demo history, so you can try every page. Delete `garden.db` before moving to the Pi so the demo history doesn't come along.

## Files

```
app.py            Flask server, automation engine, API
sensors.py        DHT11, HC-SR04, ADS1115 moisture, LED and buzzer drivers (+ simulator)
storage.py        SQLite history + settings.json
config.py         Pins, tank size, calibration, safety limits
templates/        index, dashboard, history, automation pages
static/           styles.css, app.css, main.js, dashboard.js, history.js, automation.js
```
