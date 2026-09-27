"""Hardware layer: DHT11, HC-SR04 ultrasonic sensor and the (optional) pump relay.

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
                self._dev = adafruit_dht.DHT11(getattr(board, "D%d" % pin))
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
# Pump relay (optional)
# ---------------------------------------------------------------------------
class PumpRelay:
    def __init__(self, pin, active_low):
        self.pin = pin
        self.on_level = GPIO.LOW if active_low else GPIO.HIGH
        self.off_level = GPIO.HIGH if active_low else GPIO.LOW
        # initial=OFF so the pump never twitches on at start-up
        GPIO.setup(pin, GPIO.OUT, initial=self.off_level)

    def on(self):
        GPIO.output(self.pin, self.on_level)

    def off(self):
        GPIO.output(self.pin, self.off_level)


# ---------------------------------------------------------------------------
# Public facade used by app.py
# ---------------------------------------------------------------------------
class Garden:
    def __init__(self):
        self.simulated = not ON_PI
        self._lock = threading.Lock()
        self.pump = None
        if ON_PI:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            self.dht = DHT11(config.DHT11_PIN)
            self.sonar = Ultrasonic(config.ULTRASONIC_TRIG, config.ULTRASONIC_ECHO)
            if config.PUMP_RELAY_PIN is not None:
                self.pump = PumpRelay(config.PUMP_RELAY_PIN, config.RELAY_ACTIVE_LOW)
        self._sim = {"t": 24.0, "h": 55.0, "d": 8.0}

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
            self._sim["d"] = min(config.TANK_EMPTY_DISTANCE_CM,
                                 self._sim["d"] + 0.01)
            return round(self._sim["d"], 1)
        return self.sonar.distance_cm()

    # -- pump -----------------------------------------------------------------
    @property
    def has_pump(self):
        return self.pump is not None or self.simulated

    def run_pump(self, seconds):
        """Blocking: switch the pump on for `seconds`, always switch off after."""
        with self._lock:
            if self.pump is None:
                if self.simulated:
                    time.sleep(seconds)
                    self._sim["d"] = max(config.TANK_FULL_DISTANCE_CM,
                                         self._sim["d"] - 0.3 * seconds)
                return
            try:
                self.pump.on()
                time.sleep(seconds)
            finally:
                self.pump.off()

    def cleanup(self):
        if not ON_PI:
            return
        try:
            if self.pump:
                self.pump.off()
            self.dht.close()
        finally:
            GPIO.cleanup()
