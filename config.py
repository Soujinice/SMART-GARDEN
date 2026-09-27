"""Smart Indoor Garden - settings.

Edit this file to match your wiring and your water tank.
All GPIO numbers are BCM numbers (the "GPIOxx" names), not physical pin numbers.
See WIRING.md for the full pin-by-pin connection table.
"""

# --- GPIO (BCM numbering) -------------------------------------------------
DHT11_PIN = 4          # GPIO4  = physical pin 7
ULTRASONIC_TRIG = 23   # GPIO23 = physical pin 16
ULTRASONIC_ECHO = 24   # GPIO24 = physical pin 18 (through the 1k/2k voltage divider!)

# Optional water pump relay. Set to None if no pump/relay is connected:
# the "Water now" button then only logs the request (nothing is switched).
PUMP_RELAY_PIN = 17    # GPIO17 = physical pin 11
RELAY_ACTIVE_LOW = True  # most blue 1-channel relay modules switch ON when IN is LOW

# --- Water tank (measured by the HC-SR04 mounted on the lid, facing down) ---
TANK_EMPTY_DISTANCE_CM = 20.0  # sensor -> tank bottom (tank empty)
TANK_FULL_DISTANCE_CM = 4.0    # sensor -> water surface when full (keep >= 3 cm)
LOW_WATER_PERCENT = 15         # below this the pump is blocked (protects it from running dry)

# --- Plant comfort ranges (used for the health status) ---------------------
TEMP_RANGE_C = (18.0, 30.0)
HUMIDITY_RANGE = (40.0, 70.0)

# --- Watering safety -------------------------------------------------------
WATER_MIN_SECONDS = 1
WATER_MAX_SECONDS = 15
WATER_COOLDOWN_SECONDS = 30    # minimum pause between two waterings

# --- Timing ----------------------------------------------------------------
SENSOR_INTERVAL_SECONDS = 3    # DHT11 needs >= 2 s between reads

# --- Web server --------------------------------------------------------------
HOST = "0.0.0.0"               # reachable from other devices on your Wi-Fi
PORT = 5000
