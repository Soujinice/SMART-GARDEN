"""Smart Indoor Garden - hardware settings.

Edit this file to match your wiring and your water tank.
All GPIO numbers are BCM numbers (the "GPIOxx" names), not physical pin numbers.
See README.md for the full pin-by-pin wiring table.

Plant settings (moisture threshold, schedules, comfort ranges) are changed
from the website's Automation page and saved in settings.json.
"""

# --- GPIO (BCM numbering) -------------------------------------------------
DHT11_PIN = 4          # GPIO4  = physical pin 7
ULTRASONIC_TRIG = 23   # GPIO23 = physical pin 16
ULTRASONIC_ECHO = 24   # GPIO24 = physical pin 18 (through the 1k/2k voltage divider!)

# Watering indicator (stands in for a pump):
# the LED is ON for the whole watering, the buzzer beeps at start/end and on alerts.
LED_PIN = 17           # GPIO17 = physical pin 11 (through a 330 ohm resistor)
BUZZER_PIN = 27        # GPIO27 = physical pin 13
BUZZER_TYPE = "active"  # "active" (beeps on its own) or "passive" (needs a tone)
BUZZER_TONE_HZ = 2000   # only used for a passive buzzer

# --- Soil moisture (optional) ----------------------------------------------
# The Pi has no analog inputs, so a capacitive soil sensor needs an ADS1115 ADC (I2C).
# Set to None if you don't have one: moisture then shows "No sensor" and
# automatic watering uses the schedules only.
MOISTURE_SENSOR = "ads1115"    # "ads1115" or None
ADS1115_ADDRESS = 0x48         # ADDR pin to GND
ADS1115_CHANNEL = 0            # sensor AOUT -> A0
# Calibration: raw ADC value with the probe in dry air and in a glass of water.
MOISTURE_DRY_RAW = 22000
MOISTURE_WET_RAW = 10000

# --- Water tank (measured by the HC-SR04 mounted on the lid, facing down) ---
TANK_EMPTY_DISTANCE_CM = 20.0  # sensor -> tank bottom (tank empty)
TANK_FULL_DISTANCE_CM = 4.0    # sensor -> water surface when full (keep >= 3 cm)

# --- Watering safety (hard limits, not editable from the website) -----------
WATER_MIN_SECONDS = 1
WATER_MAX_SECONDS = 15
WATER_COOLDOWN_SECONDS = 30    # minimum pause between two waterings
PUMP_ML_PER_SECOND = 25        # estimate used for the "~ml" figures (for a future real pump)

# --- Timing / storage --------------------------------------------------------
SENSOR_INTERVAL_SECONDS = 3    # DHT11 needs >= 2 s between reads
LOG_INTERVAL_SECONDS = 60      # how often a reading is saved for the charts
KEEP_DAYS = 30                 # history older than this is deleted
DATABASE_FILE = "garden.db"    # created next to app.py
SETTINGS_FILE = "settings.json"

# --- Web server --------------------------------------------------------------
HOST = "0.0.0.0"               # reachable from other devices on your Wi-Fi
PORT = 5000
