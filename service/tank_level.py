from array import array
from scipy import stats

from service.common import *
from persistence.schema import *
from device.dev_serial import DistanceMeasureException, DistanceMeterDevice


class TankLevelService(Service):

    def provideName(self):
        raise NotImplementedError()

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    def __init__(self):
        Service.__init__(self)

        self.device: DistanceMeterDevice = None
        self.the_last_stored_reading: TankLevel = None
        self.the_last_reliable_reading: TankLevel = None

        self.the_sensor: Sensor = None

        self.tank_level_section = 'TANKLEVEL'

        self._default_polling_period = 60
        self.measure_duration = self.configuration.getFloatConfigValue(
            section=self.tank_level_section,
            parameter='one-measure-duration-secs', default=10)
        self.measure_attempts_pause_time = self.configuration.getFloatConfigValue(
            section=self.tank_level_section,
            parameter='measure-attempts-pause-time', default=0.5)
        self.store_results_if_increased_by = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='significant-level-increase', default=1)
        self.store_results_if_decreased_by = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='significant-level-decrease', default=1000)

        self.tank_empty_level = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='tank-empty-level', default=2000)
        self.tank_full_level = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='tank-full-level', default=590)

        self.rest_app.add_url_rule('/', 'config',
                                   self.get_rest_response_config)

    def get_polling_period(self) -> int:
        pp = self.get_the_sensor().polling_period
        return pp if pp else self._default_polling_period

    def get_device(self):
        if not self.device:
            self.device = DistanceMeterDevice()

        return self.device

    def measure(self) -> int:
        return self.get_device().measure()

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
                measurements.append(self.measure())
            except DistanceMeasureException as exception:
                self.log.critical(f'Unsuccessful {attempt} attempt to measure, details: {exception.message}')
            if self.measure_attempts_pause_time > 0:
                ExitEvent().wait(self.measure_attempts_pause_time)

        if len(measurements) > 0:
            # assumed the reading was successful in technical terms
            # unfortunately the reading sometimes (quite often) can be invalid - unreliable

            current_level = int(stats.mode(measurements, nan_policy='omit').mode[0])
            current_readings_mean = stats.tmean(measurements)
            current_readings_var_perc = 100*stats.variation(measurements)

            last_reliable_reading = self.get_last_reliable_reading()
            last_stored_reading = self.get_last_stored_reading()

            if self.is_reliable(current_level, last_reliable_reading) \
                    or self.is_reliable(current_level, last_stored_reading):
                self.log.info(f'OK {len(measurements)} measurements, '
                              f'mode: {current_level} [mm] ({self.get_fill_percentage(current_level):.2f} [%]), '
                              f'mean: {current_readings_mean:.2f}, '
                              f'variance.: {current_readings_var_perc:.2f}%')

                self.set_last_reliable_reading(current_level)

                if self.do_store_reading(current_level, last_stored_reading):
                    self.add_reading(current_level)

                self.react_on_level(self.get_fill_percentage())

            else:
                speed = (last_reliable_reading.level - current_level) / \
                        ((datetime.now() - last_reliable_reading.timestamp).total_seconds()/3600)
                self.log.info(f'UNRELIABLE! {len(measurements)} measurements, '
                              f'mode: {current_level} [mm] ({self.get_fill_percentage(current_level):.2f} [%]), '
                              f'increase {last_reliable_reading.level - current_level} [mm],'
                              f'mean: {current_readings_mean:.2f}, '
                              f'variance.: {current_readings_var_perc:.2f}%, '
                              f'increase speed: {speed:.4f} [mmph]')
                # signalize failure
                self.react_on_failure()

        else:
            self.log.critical(f"All attempts to measure the level failed")
            self.react_on_failure()

        return self.get_polling_period() - (datetime.now() - start_mark).total_seconds()

    def get_the_sensor(self) -> Sensor:
        if not self.the_sensor:
            self.the_sensor = self.persistence.get_sensor(SENSORTYPE_LEVEL, self.get_the_sensor_reference())
            if not self.the_sensor:
                self.the_sensor = self.persistence.register_sensor(
                    SENSORTYPE_LEVEL,
                    self.get_hostname(),
                    reference=self.get_the_sensor_reference(),
                    polling_period=self._default_polling_period)
                self.log.info(f"Sensor {SENSORTYPE_LEVEL}@{self.get_the_sensor_reference()}"
                              f"has been automatically created: {str(self.the_sensor)}")
            else:
                self.log.info(f"Sensor {SENSORTYPE_LEVEL}@{self.get_the_sensor_reference()} "
                              f"was restored from the database: {str(self.the_sensor)}")

        return self.the_sensor

    def get_the_sensor_reference(self) -> str:
        raise NotImplementedError()

    def get_last_stored_reading(self) -> TankLevel:
        if not self.the_last_stored_reading:
            self.the_last_stored_reading = self.persistence.get_last_tank_level(self.get_the_sensor())
            if self.the_last_stored_reading:
                self.log.info(f'Last tank level restored from the database: {str(self.the_last_stored_reading)}')
            else:
                self.log.info("Can't locate last reading of tank level")

        return self.the_last_stored_reading

    def get_last_reliable_reading(self) -> TankLevel:
        if not self.the_last_reliable_reading:
            self.the_last_reliable_reading = self.get_last_stored_reading()
        return self.the_last_reliable_reading

    def set_last_reliable_reading(self, current_level: int):
        self.the_last_reliable_reading = TankLevel(
            sensor=None,
            db_id=None,
            sensor_id=None,
            level=current_level,
            timestamp=datetime.now())

    def add_reading(self, level: int):
        self.the_last_stored_reading = self.persistence.add_tank_level(
            self.get_the_sensor(),
            level,
            datetime.now())

        self.log.info(f"New level reading added: {str(self.the_last_stored_reading)}")

    def get_fill_percentage(self, level=None):
        if not level:
            level = self.get_last_stored_reading().level
        return int(10000.0*(self.tank_empty_level-level)/(self.tank_empty_level-self.tank_full_level))/100.0

    def is_reliable(self, current_level: int, last_reliable_reading: TankLevel) -> bool:
        raise NotImplementedError()

    def do_store_reading(self, current_level: int, last_stored_reading: TankLevel) -> bool:
        if not last_stored_reading:
            return True

        increase = self._increase(current_level, last_stored_reading.level)
        return increase <= (-self.store_results_if_decreased_by) or increase >= self.store_results_if_increased_by

    @staticmethod
    def _increase(current_level: int, previous_level: int):
        """
        Returns the volume of increase (if positive) or decrease (if negative) of tank level
        :param current_level: the level just measured
        :param previous_level: the previously measured level
        :return: positive value for growing level, negative for level decrease
        """
        return previous_level - current_level

    def react_on_failure(self):
        pass

    def react_on_level(self, fill_percentage):
        pass

    def get_rest_response_config(self):
        return self.jsonify(TankConfigJson(
            full_level_mm=self.tank_full_level,
            empty_level_mm=self.tank_empty_level))