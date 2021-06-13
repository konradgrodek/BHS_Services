#!/usr/bin/python3

from gpiozero import LED
from array import array
from scipy import stats

from service.common import *
from persistence.schema import *
from device.dev_serial import DistanceMeasureException, DistanceMeterDevice


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
    """
    In future this class must be adapted to host both tank levels: cesspit and rain-water level
    It will be then subclassed and common functionality extracted to separate file
    """
    def __init__(self):
        Service.__init__(self)

        self.the_cesspit_sensor: Sensor = None
        self.the_last_stored_cesspit_reading: TankLevel = None
        self.the_last_reliable_cesspit_reading: TankLevel = None
        self.device: DistanceMeterDevice = None

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
        self.reliable_level_increase = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='reliable-level-increase', default=5)
        self.reliable_level_increase_per_hour = self.configuration.getIntConfigValue(
            section=tank_level_section,
            parameter='reliable-level-increase-per-hour', default=20)

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

        self.rest_app.add_url_rule('/', 'current',
                                   self.get_rest_response_current_reading)

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    def provideName(self):
        return 'cesspit'

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

    def _get_last_stored_cesspit_reading(self) -> TankLevel:
        if not self.the_last_stored_cesspit_reading:
            self.the_last_stored_cesspit_reading = self.persistence.get_last_tank_level(self._get_cesspit_sensor())
            if self.the_last_stored_cesspit_reading:
                self.log.info(f'Last cesspit level restored from the database: {str(self.the_last_stored_cesspit_reading)}')
            else:
                self.log.info("Can't locate last reading of cesspit level")

        return self.the_last_stored_cesspit_reading

    def _get_last_reliable_cesspit_reading(self) -> TankLevel:
        if not self.the_last_reliable_cesspit_reading:
            self.the_last_reliable_cesspit_reading = self._get_last_stored_cesspit_reading()
        return self.the_last_reliable_cesspit_reading

    def _set_last_reliable_cesspit_reading(self, current_level: int):
        self.the_last_reliable_cesspit_reading = TankLevel(
            sensor=None,
            db_id=None,
            sensor_id=None,
            level=current_level,
            timestamp=datetime.now())

    def _add_cesspit_reading(self, level: int):
        self.the_last_stored_cesspit_reading = self.persistence.add_tank_level(
            self._get_cesspit_sensor(),
            level,
            datetime.now())

        self.log.info(f"New level reading added: {str(self.the_last_stored_cesspit_reading)}")

    def _get_polling_period(self) -> int:
        pp = self._get_cesspit_sensor().polling_period
        return pp if pp else self._default_polling_period

    def _get_device(self):
        if not self.device:
            self.device = DistanceMeterDevice()

        return self.device

    def _measure(self) -> int:
        return self._get_device().measure()

    def _get_fill_percentage(self, level=None):
        if not level:
            level = self._get_last_stored_cesspit_reading().level
        return int(10000.0*(self.tank_empty_level-level)/(self.tank_empty_level-self.tank_full_level))/100.0

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time im seconds
        """
        start_mark = datetime.now()

        measurements = array('i')

        attempt = 0
        while (datetime.now() - start_mark).total_seconds() < self.measure_duration and not ExitEvent().is_set():
            try:
                attempt += 1
                measurements.append(self._measure())
            except DistanceMeasureException as exception:
                self.log.critical(f'Unsuccessful {attempt} attempt to measure', exception)
            if self.measure_attempts_pause_time > 0:
                ExitEvent().wait(self.measure_attempts_pause_time)

        if len(measurements) > 0:
            # assumed the reading was successful in technical terms
            # unfortunately the reading sometimes (quite often) can be invalid - unreliable

            current_level = int(stats.mode(measurements, nan_policy='omit').mode[0])
            current_level_mean = stats.tmean(measurements)

            last_reliable_reading = self._get_last_reliable_cesspit_reading()
            last_stored_reading = self._get_last_stored_cesspit_reading()

            if self._is_reliable(current_level, last_reliable_reading) \
                    or self._is_reliable(current_level, last_stored_reading):
                self.log.info(f'OK {len(measurements)} measurements, '
                              f'mode: {current_level} [mm] ({self._get_fill_percentage(current_level):.2f} [%]), '
                              f'mean: {current_level_mean:.2f}')

                self._set_last_reliable_cesspit_reading(current_level)

                if self._do_store_reading(current_level, last_stored_reading):
                    self._add_cesspit_reading(current_level)

                self._react_on_level(self._get_fill_percentage())

            else:
                speed = (last_reliable_reading.level - current_level) / \
                        ((datetime.now() - last_reliable_reading.timestamp).total_seconds()/3600)
                self.log.info(f'UNRELIABLE! {len(measurements)} measurements, '
                              f'mode: {current_level} [mm] ({self._get_fill_percentage(current_level):.2f} [%]), '
                              f'increase {last_reliable_reading.level - current_level} [mm],'
                              f'mean: {current_level_mean:.2f}, '
                              f'variance: {stats.variation(measurements):.2f}, '
                              f'increase speed: {speed:.4f} [mmph]')
                # signalize failure
                self._react_on_failure()

        else:
            self.log.critical(f"All attempts to measure the level failed")
            self._react_on_failure()

        return self._get_polling_period() - (datetime.now()-start_mark).total_seconds()

    @staticmethod
    def _increase(current_level: int, previous_level: int):
        """
        Returns the volume of increase (if positive) or decrease (if negative) of tank level
        :param current_level: the level just measured
        :param previous_level: the previously measured level
        :return: positive value for growing level, negative for level decrease
        """
        return previous_level - current_level

    def _is_reliable(self, current_level: int, last_reliable_reading: TankLevel) -> bool:
        # the decrease is always reliable
        if not last_reliable_reading or self._increase(current_level, last_reliable_reading.level) <= 0:
            return True

        # the increase is reliable if it does not exceed reliable-level-increase
        if self._increase(current_level, last_reliable_reading.level) < self.reliable_level_increase:
            return True

        # the increase is also reliable if the last reliable increase is in the past and the speed of increase
        # does not exceed reliable-level-increase-per-day

        return self._increase(current_level, last_reliable_reading.level) / \
               (datetime.now() - last_reliable_reading.timestamp).total_seconds() \
               < (self.reliable_level_increase_per_hour / (60 * 60))

    def _do_store_reading(self, current_level: int, last_stored_reading: TankLevel) -> bool:
        if not last_stored_reading:
            return True

        increase = self._increase(current_level, last_stored_reading.level)
        return increase <= (-self.store_results_if_decreased_by) or increase >= self.store_results_if_increased_by

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

    def get_rest_response_current_reading(self):
        pessimistic_reading = self._get_last_reliable_cesspit_reading() \
            if self._get_last_reliable_cesspit_reading().level < self._get_last_stored_cesspit_reading().level \
            else self._get_last_stored_cesspit_reading()
        return self.jsonify(CesspitReadingJson(
            level_mm=pessimistic_reading.level,
            fill_perc=self._get_fill_percentage(pessimistic_reading.level),
            timestamp=pessimistic_reading.timestamp)
        )


if __name__ == '__main__':
    ServiceRunner(TankLevelService).run()
    exit()

