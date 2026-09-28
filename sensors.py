"""Hardware layer: DHT11, HC-SR04, optional soil moisture sensor, LED and buzzer.

Runs on a Raspberry Pi 3 B with RPi.GPIO (pre-installed on Raspberry Pi OS).
On a computer without GPIO it switches to a simulator so the website can
still be developed and tested.
"""

import random
import statistics
import threading
import time

import config

try:
    import RPi.GPIO as GPIO
    ON_PI = True
except (ImportError, RuntimeError):
    GPIO = None
    ON_PI = False

# Adafruit's driver is the most reliable DHT11 reader, but it is optional:
# without it we fall back to the pure RPi.GPIO reader below.
try:
    if ON_PI:
        import adafruit_dht
        import board
    else:
        adafruit_dht = None
except (ImportError, NotImplementedError, RuntimeError):
    adafruit_dht = None


# ---------------------------------------------------------------------------
# DHT11
# ---------------------------------------------------------------------------
def _read_dht11_gpio(pin):
    """Bit-banged DHT11 read. Returns (temp_c, humidity) or None on a bad read."""
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.HIGH)
    time.sleep(0.05)
    GPIO.output(pin, GPIO.LOW)        # start signal: >= 18 ms low
    time.sleep(0.02)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    samples = []
    unchanged, last = 0, -1
    while unchanged < 100:
        cur = GPIO.input(pin)
        samples.append(cur)
        if cur != last:
            unchanged, last = 0, cur
        else:
            unchanged += 1

    # Measure the length of every HIGH pulse after the sensor's 80us/80us response.
    lengths, state, run = [], "init_down", 0
    for s in samples:
        run += 1
        if state == "init_down" and s == 0:
            state = "init_up"
        elif state == "init_up" and s == 1:
            state = "first_down"
        elif state == "first_down" and s == 0:
            state = "down"
        elif state == "down" and s == 1:
            state, run = "up", 0
        elif state == "up" and s == 0:
            lengths.append(run)
            state = "down"

    if len(lengths) < 40:
        return None
    lengths = lengths[:40]
    threshold = (min(lengths) + max(lengths)) / 2
    bits = [1 if n > threshold else 0 for n in lengths]
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, 40, 8)]
    if (sum(data[:4]) & 0xFF) != data[4]:
        return None
    humidity, temp = data[0], data[2] + data[3] / 10
    if not (0 <= humidity <= 100 and 0 <= temp <= 60):
        return None
    return float(temp), float(humidity)


class DHT11:
    def __init__(self, pin):
        self.pin = pin
        self._dev = None
        if adafruit_dht is not None:
            try:
                # use_pulseio=False: no background helper process, so the pin is
                # always released when the app stops (avoids "Unable to set line 4 to input")
                self._dev = adafruit_dht.DHT11(getattr(board, "D%d" % pin), use_pulseio=False)
            except Exception:
                self._dev = None

    def read(self):
        """Try a few times (the DHT11 often misses a read). Returns (t, h) or None."""
        for _ in range(4):
            try:
                if self._dev is not None:
                    t, h = self._dev.temperature, self._dev.humidity
                    if t is not None and h is not None:
                        return float(t), float(h)
                else:
                    result = _read_dht11_gpio(self.pin)
                    if result:
                        return result
            except RuntimeError:
                pass  # normal for DHT sensors - just retry
            time.sleep(2.1)
        return None

    def close(self):
        if self._dev is not None:
            try:
                self._dev.exit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# HC-SR04 ultrasonic (water tank level)
# ---------------------------------------------------------------------------
class Ultrasonic:
    def __init__(self, trig, echo):
        self.trig, self.echo = trig, echo
        GPIO.setup(trig, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(echo, GPIO.IN)
        time.sleep(0.05)

    def _ping(self):
        GPIO.output(self.trig, GPIO.HIGH)
        time.sleep(0.00001)           # 10 us trigger pulse
        GPIO.output(self.trig, GPIO.LOW)

        deadline = time.monotonic() + 0.03
        while GPIO.input(self.echo) == 0:
            if time.monotonic() > deadline:
                return None
        start = time.monotonic()
        while GPIO.input(self.echo) == 1:
            if time.monotonic() - start > 0.03:  # > ~5 m: no echo
                return None
        cm = (time.monotonic() - start) * 34300 / 2
        return cm if 2 <= cm <= 400 else None

    def distance_cm(self):
        """Median of 5 pings - filters out the occasional stray echo."""
        readings = []
        for _ in range(5):
            d = self._ping()
            if d is not None:
                readings.append(d)
            time.sleep(0.06)
        return round(statistics.median(readings), 1) if readings else None


def distance_to_percent(distance):
    empty, full = config.TANK_EMPTY_DISTANCE_CM, config.TANK_FULL_DISTANCE_CM
    pct = (empty - distance) / (empty - full) * 100
    return round(max(0.0, min(100.0, pct)))


# ---------------------------------------------------------------------------
# Soil moisture: capacitive sensor -> ADS1115 ADC (I2C)
# ---------------------------------------------------------------------------
class MoistureADS1115:
    def __init__(self, address, channel):
        import smbus  # python3-smbus, pre-installed on Raspberry Pi OS
        self.bus = smbus.SMBus(1)
        self.address = address
        # single-shot, AINx vs GND, +/-4.096 V range, 128 samples/s, comparator off
        self.cfg = 0x8000 | ((4 + channel) << 12) | 0x0200 | 0x0100 | 0x0080 | 0x0003

    def _raw(self):
        self.bus.write_i2c_block_data(self.address, 0x01, [self.cfg >> 8, self.cfg & 0xFF])
        time.sleep(0.01)
        hi, lo = self.bus.read_i2c_block_data(self.address, 0x00, 2)
        value = (hi << 8) | lo
        return value - 65536 if value > 0x7FFF else value

    def raw(self):
        return int(statistics.median(self._raw() for _ in range(5)))


def raw_to_moisture_percent(raw):
    dry, wet = config.MOISTURE_DRY_RAW, config.MOISTURE_WET_RAW
    pct = (dry - raw) / (dry - wet) * 100
    return round(max(0.0, min(100.0, pct)))


# ---------------------------------------------------------------------------
# Watering indicator: LED (on while "watering") + buzzer (beeps)
# ---------------------------------------------------------------------------
class Led:
    def __init__(self, pin):
        self.pin = pin
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)   # starts OFF

    def on(self):
        GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        GPIO.output(self.pin, GPIO.LOW)


class Buzzer:
    """Active buzzer: just switched on/off. Passive buzzer: needs a tone (PWM)."""

    def __init__(self, pin, passive):
        self.pin = pin
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)   # silent at start-up
        self.pwm = GPIO.PWM(pin, config.BUZZER_TONE_HZ) if passive else None

    def on(self):
        if self.pwm:
            self.pwm.start(50)
        else:
            GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        if self.pwm:
            self.pwm.stop()
        GPIO.output(self.pin, GPIO.LOW)


# Beep patterns: list of (on_seconds, off_seconds)
BEEP_START = [(0.08, 0.08), (0.08, 0)]           # two short beeps: watering starts
BEEP_END = [(0.35, 0)]                            # one long beep: watering done
BEEP_ALERT = [(0.15, 0.12)] * 3                   # three beeps: problem (e.g. tank low)
BEEP_TEST = [(0.1, 0.1), (0.1, 0.1), (0.4, 0)]


# ---------------------------------------------------------------------------
# Public facade used by app.py
# ---------------------------------------------------------------------------
class Garden:
    def __init__(self):
        self.simulated = not ON_PI
        self._lock = threading.Lock()
        self._beep_lock = threading.Lock()
        self.led = None
        self.buzzer = None
        self.beep_log = []   # simulation only: what the buzzer would have played
        if ON_PI:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            self.dht = DHT11(config.DHT11_PIN)
            self.sonar = Ultrasonic(config.ULTRASONIC_TRIG, config.ULTRASONIC_ECHO)
            if config.LED_PIN is not None:
                self.led = Led(config.LED_PIN)
            if config.BUZZER_PIN is not None:
                self.buzzer = Buzzer(config.BUZZER_PIN, config.BUZZER_TYPE == "passive")
        self.moisture_sensor = None
        if config.MOISTURE_SENSOR == "ads1115":
            if self.simulated:
                self.moisture_sensor = "sim"
            else:
                try:
                    self.moisture_sensor = MoistureADS1115(config.ADS1115_ADDRESS,
                                                           config.ADS1115_CHANNEL)
                    self.moisture_sensor.raw()   # probe once: fails fast if not wired
                except Exception as exc:
                    hint = ("I2C is off - enable it in raspi-config" if "No such file" in str(exc)
                            else "check the ADS1115 wiring")
                    print("Moisture sensor not found (%s). Continuing without it." % hint)
                    print("  No moisture sensor? Set MOISTURE_SENSOR = None in config.py to hide this.")
                    self.moisture_sensor = None
        self._stop = threading.Event()
        self._sim = {"t": 24.0, "h": 55.0, "d": 8.0, "m": 48.0}

    # -- readings -----------------------------------------------------------
    def read_climate(self):
        if self.simulated:
            s = self._sim
            s["t"] = min(32, max(17, s["t"] + random.uniform(-0.3, 0.3)))
            s["h"] = min(80, max(35, s["h"] + random.uniform(-1, 1)))
            return round(s["t"], 1), round(s["h"])
        return self.dht.read()

    def read_tank_distance(self):
        if self.simulated:
            return round(self._sim["d"], 1)
        return self.sonar.distance_cm()

    @property
    def has_moisture(self):
        return self.moisture_sensor is not None

    def read_moisture(self):
        if self.moisture_sensor is None:
            return None
        if self.simulated:
            self._sim["m"] = max(5.0, self._sim["m"] - random.uniform(0, 0.05))
            return round(self._sim["m"])
        try:
            return raw_to_moisture_percent(self.moisture_sensor.raw())
        except OSError:
            return None   # loose I2C wire - try again next cycle

    # -- buzzer -------------------------------------------------------------------
    def beep(self, pattern, wait=False):
        """Plays a beep pattern in the background (never blocks the web server)."""
        def play():
            with self._beep_lock:          # one pattern at a time, never overlapping
                if self.simulated:
                    self.beep_log.append(len(pattern))
                for on, off in pattern:
                    if self.buzzer:
                        self.buzzer.on()
                    time.sleep(on)
                    if self.buzzer:
                        self.buzzer.off()
                    time.sleep(off)
        if wait:
            play()
        else:
            threading.Thread(target=play, daemon=True).start()

    # -- watering output (LED + buzzer) --------------------------------------------
    @property
    def has_output(self):
        return self.led is not None or self.buzzer is not None or self.simulated

    def stop_watering(self):
        self._stop.set()

    def run_watering(self, seconds, sound=True):
        """Blocking: LED on for `seconds` (or until stop_watering()), always off after.
        Returns the number of seconds it actually ran."""
        with self._lock:
            self._stop.clear()
            if sound:
                self.beep(BEEP_START, wait=True)
            start = time.monotonic()
            try:
                if self.led:
                    self.led.on()
                self._stop.wait(seconds)
            finally:
                if self.led:
                    self.led.off()
            ran = time.monotonic() - start
            if sound:
                self.beep(BEEP_END)
            if self.simulated:
                self._sim["d"] = min(config.TANK_EMPTY_DISTANCE_CM, self._sim["d"] + 0.15 * ran)
                self._sim["m"] = min(90.0, self._sim["m"] + 4 * ran)
            return ran

    def test_outputs(self, sound=True):
        """LED blinks 3 times while the buzzer plays a test pattern."""
        if sound:
            self.beep(BEEP_TEST)
        for _ in range(3):
            if self.led:
                self.led.on()
            time.sleep(0.25)
            if self.led:
                self.led.off()
            time.sleep(0.2)

    def cleanup(self):
        if not ON_PI:
            return
        try:
            if self.led:
                self.led.off()
            if self.buzzer:
                self.buzzer.off()
            self.dht.close()
        finally:
            GPIO.cleanup()
