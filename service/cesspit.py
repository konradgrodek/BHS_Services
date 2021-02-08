#!/usr/bin/python3

from serial import Serial
import time
from mariadb import OperationalError
from gpiozero import LED
from array import array
from scipy import stats

from service.common import Service, ServiceRunner
from persistence.schema import *


class LedSignal:
    def __init__(self, pin_R: int, pin_G: int, pin_B: int):
        self.R = LED(pin_R, initial_value=False)
        self.G = LED(pin_G, initial_value=False)
        self.B = LED(pin_B, initial_value=False)

    def __str__(self):
        return f'RGB LED defined at {self.R.pin} - {self.G.pin} - {self.B.pin}'

    def red(self):
        self.R.on()
        self.G.off()
        self.B.off()

    def violet(self):
        self.R.on()
        self.G.off()
        self.B.on()

    def green_yellow(self):
        self.R.on()
        self.G.on()
        self.B.off()

    def green_blink(self, count):
        self.R.off()
        self.B.off()
        self.G.blink(on_time=0.2, off_time=0.1, n=count)

    def blue_blink(self):
        self.R.off()
        self.G.off()
        self.B.blink(on_time=0.2, off_time=0.1)

    def red_blink(self):
        self.B.off()
        self.G.off()
        self.R.blink(on_time=0.2, off_time=0.1)


class TankLevelService(Service):
    def __init__(self):
        Service.__init__(self)

        self.the_cesspit_sensor: Sensor = None
        self.the_last_cesspit_reading: TankLevel = None
        self.device: Serial = None

        tank_level_section = 'TANKLEVEL'

        self._default_polling_period = 60
        self.measure_duration = self.configuration.getFloatConfigValue(
            section=tank_level_section,
            parameter='one-measure-duration-secs', default=10)
        self.measure_attempts_pause_time = self.configuration.getFloatConfigValue(
            section=tank_level_section,
            parameter='measure-attempts-pause-time', default=0.5)
        self.store_results_if_increased_by = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='significant-level-increase', default=1)
        self.store_results_if_decreased_by = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='significant-level-decrease', default=1000)
        self.tank_empty_level = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='tank-empty-level', default=2000)
        self.tank_full_level = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='tank-full-level', default=590)

        pin_led_R = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='pin-led-R')
        pin_led_G = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='pin-led-G')
        pin_led_B = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='pin-led-B')

        self.led_signal = LedSignal(pin_led_R, pin_led_G, pin_led_B)

        signal_levels = self.configuration.getConfigValue(
            section=tank_level_section,
            parameter='tank-fill-percentage-levels')

        self.signal_thresholds = None
        if signal_levels:
            self.signal_thresholds = [int(s) for s in signal_levels.split(',')]

        if not self.signal_thresholds or len(self.signal_thresholds) != 4:
            raise ValueError(f'Wrong configuration. Incorrect provided value of '
                             f'{tank_level_section}.tank-fill-percentage-levels: <{signal_levels}>. '
                             f'Expected comma-separated list of four integers')

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    def provideName(self):
        return 'BHS.Cesspit'

    def _get_cesspit_sensor(self) -> Sensor:
        if not self.the_cesspit_sensor:
            self.the_cesspit_sensor = self.persistence.get_sensor(SENSORTYPE_LEVEL, CESSPIT_THE_SENSOR_REFERENCE)
            if not self.the_cesspit_sensor:
                self.the_cesspit_sensor = self.persistence.register_sensor(
                    SENSORTYPE_LEVEL,
                    self.get_hostname(),
                    reference=CESSPIT_THE_SENSOR_REFERENCE,
                    polling_period=self._default_polling_period)
                self.log.info(f"Sensor {SENSORTYPE_LEVEL}@{CESSPIT_THE_SENSOR_REFERENCE}"
                              f"has been automatically created: {str(self.the_cesspit_sensor)}")
            else:
                self.log.info(f"Sensor {SENSORTYPE_LEVEL}@{CESSPIT_THE_SENSOR_REFERENCE} "
                              f"was restored from the database: {str(self.the_cesspit_sensor)}")

        return self.the_cesspit_sensor

    def _get_last_cesspit_reading(self) -> TankLevel:
        if not self.the_last_cesspit_reading:
            self.the_last_cesspit_reading = self.persistence.get_last_tank_level(self._get_cesspit_sensor())
            if self.the_last_cesspit_reading:
                self.log.info(f'Last cesspit level restored from the database: {str(self.the_last_cesspit_reading)}')
            else:
                self.log.info("Can't locate last reading of cesspit level")

        return self.the_last_cesspit_reading

    def _add_cesspit_reading(self, level: int, retry_count: int = 0):
        try:
            self.the_last_cesspit_reading = self.persistence.add_tank_level(
                self._get_cesspit_sensor(),
                level,
                datetime.now())
        except OperationalError as err:
            self.persistence.reconnect()
            if retry_count < 10:
                self.log.critical(f'An operational error occurred while storing level reading, '
                                  f'details: {str(err)} [attempt: {retry_count+1}]')
                time.sleep(1)
                self._add_cesspit_reading(level, retry_count+1)
            else:
                raise err

        self.log.info(f"New level reading added: {str(self.the_last_cesspit_reading)}")

    def _get_polling_period(self) -> int:
        pp = self._get_cesspit_sensor().polling_period
        return pp if pp else self._default_polling_period

    def _get_device(self):
        if not self.device:
            self.device = Serial("/dev/ttyAMA0", 9600)
            # self.device.setRTS(1)

        return self.device

    def _measure(self) -> int:
        _device = self._get_device()
        if _device.isOpen():
            # wait for device if there is anything to be read
            mark = datetime.now()
            while _device.inWaiting() == 0:
                time.sleep(0.1)
                if (datetime.now() - mark).total_seconds() > 1.0:
                    raise MeasureException('timeout occurred while waiting for anything to be read')

            data = []
            i = 0
            while _device.inWaiting() > 0:
                data.append(ord(_device.read()))
                i += 1
                if data[0] != 0xff:
                    i = 0
                    data = []
                if i == 4:
                    break
            _device.read(_device.inWaiting())
            if i == 4:
                sum = (data[0] + data[1] + data[2]) & 0x00ff
                if sum != data[3]:
                    raise MeasureException(f'checksum error, got {sum}, '
                                           f'expected {data[3]} '
                                           f'data: [{data[0]}]-[{data[1]}]-[{data[2]}]-[{data[3]}]')
                else:
                    measurement = data[1] * 256 + data[2]
            else:
                raise MeasureException(f'Data error, number of read bytes is {i}, read bytes: {data}')

        else:
            raise MeasureException('device is not open')
        return measurement

    def _get_fill_percentage(self, level=None):
        if not level:
            level = self._get_last_cesspit_reading().level
        return 100*(self.tank_empty_level-level)/(self.tank_empty_level-self.tank_full_level)

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time im seconds
        """
        start_mark = datetime.now()

        measurements = array('i')

        attempt = 0
        while (datetime.now() - start_mark).total_seconds() < self.measure_duration and not self._exit_event.is_set():
            try:
                attempt += 1
                measurements.append(self._measure())
            except MeasureException as exception:
                self.log.critical(f'Unsuccessful {attempt} attempt to measure, got: {str(exception)}')
            if self.measure_attempts_pause_time > 0:
                time.sleep(self.measure_attempts_pause_time)

        if len(measurements) > 0:
            measurements_mode = stats.mode(measurements, nan_policy='omit').mode[0]
            self.log.debug(f"Mode: {measurements_mode} [mm], "
                           f"mean: {stats.tmean(measurements):.5} [mm] "
                           f"of last {len(measurements)} readings")
            last_reading = self._get_last_cesspit_reading()

            if not last_reading or last_reading.level - measurements_mode > 0.3:
                self.log.info(f'Current measure as most frequent one '
                              f'of last {len(measurements)} is {measurements_mode} [mm], '
                              f'{self._get_fill_percentage(measurements_mode):.4} [%]')

            try:
                if not last_reading or last_reading.level - measurements_mode > self.store_results_if_increased_by \
                        or measurements_mode - last_reading.level > self.store_results_if_decreased_by:

                    self._add_cesspit_reading(int(measurements_mode))
                    # don't be misled here: "increase" means that new reading is smaller
                    # (distance is decreasing, but level is increasing)

                self._react_on_level(self._get_fill_percentage())
            except OperationalError:
                self._react_on_failure()
        else:
            self.log.critical(f"All attempts to measure the level failed")
            self._react_on_failure()

        return self._get_polling_period() - (datetime.now()-start_mark).total_seconds()

    def _react_on_level(self, fill_percentage):
        if fill_percentage < self.signal_thresholds[0]:
            self.led_signal.green_blink(int(fill_percentage/10)+1)
        elif fill_percentage < self.signal_thresholds[1]:
            self.led_signal.green_yellow()
        elif fill_percentage < self.signal_thresholds[2]:
            self.led_signal.violet()
        elif fill_percentage < self.signal_thresholds[3]:
            self.led_signal.red()
        else:
            self.led_signal.red_blink()

    def _react_on_failure(self):
        self.led_signal.blue_blink()


class MeasureException(BaseException):
    def __init__(self, msg: str):
        self.message = msg

    def __str__(self):
        return f'Fatal error occurred while reading state of UART device: {self.message}'


if __name__ == '__main__':
    ServiceRunner(TankLevelService).run()
    exit()

