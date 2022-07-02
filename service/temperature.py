#!/usr/bin/python3

import glob
import re
import os
from threading import Lock
from scipy import stats

from service.common import *
from core.bean import TemperatureReadingJson
from persistence.schema import *

DEVICES_BASEDIR = '/sys/bus/w1/devices/'
DEVICE_SUBDIR = '/w1_slave'
PIN_ONE_WIRE_INTERFACE = 7  # BCM 4
COMMAND_VCGENCMD = 'vcgencmd'
COMMAND_MEASURETEMP = 'measure_temp'


class SimpleTemperatureReading:
    def __init__(self,
                 succeeded: bool,
                 sensor_reference: str,
                 temperature: float,
                 timestamp: datetime,
                 is_internal: bool = False):
        self.succeeded = succeeded
        self.reference = sensor_reference
        self.temperature = temperature
        self.timestamp = timestamp
        self.is_internal = is_internal


class TemperatureService(Service):

    def __init__(self):
        Service.__init__(self)
        self.sensors = list()
        self.device_file_re_pattern = re.compile('.*t=(-?\\d*)')
        self.measure_temp_output_re_pattern = re.compile('temp=(\\d+\\.\\d*).*')
        self.internal_temp_sensor_refno = self.get_hostname()
        self.human_readable_sensor_names = {}
        self.internal_temp_readings_sum = 0.0
        self.internal_temp_readings_count = 0
        self.last_stored_temperature_readings = {}
        self.current_temperature_readings = {}

        temperature_section = 'TEMPERATURE'
        # read some configuration
        self.polling_period = self.configuration.getIntConfigValue(
            section=temperature_section,
            parameter='polling-period',
            default=10*60)

        self.max_retry_count = self.configuration.getIntConfigValue(
            section=temperature_section,
            parameter='max-retry-count',
            default=10)

        self.retry_delay = self.configuration.getFloatConfigValue(
            section=temperature_section,
            parameter='retry-delay',
            default=1.0)

        self.single_measurement_count = self.configuration.getIntConfigValue(
            section=temperature_section,
            parameter='single-measurements-count',
            default=1
        )

        self.significant_difference = self.configuration.getFloatConfigValue(
            section=temperature_section,
            parameter='significant-temperature-difference',
            default=0.5)

        self.polling_period_internal_temp = self.configuration.getIntConfigValue(
            section=temperature_section,
            parameter='default-polling-period-internal-temp',
            default=4*60*60)

        self.rest_app.add_url_rule('/', 'current_temperature',
                                   self.get_rest_response_current_temperature_readings)
        self.rest_app.add_url_rule('/last', 'last_temperature',
                                   self.get_rest_response_last_temperature_readings)
        self.rest_app.add_url_rule('/realtime', 'realtime_temperature',
                                   self.get_rest_response_realtime_temperature_readings)

        self.reading_lock = Lock()

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time in seconds
        """
        mark = datetime.now()
        self.read_and_store_temperature()

        return self.polling_period - (datetime.now() - mark).total_seconds()

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    def provideName(self):
        return 'temperature'

    def read_and_store_temperature(self):
        self.reading_lock.acquire()

        readings = self.get_readings()
        reporting_sensors_refnos = list()

        for _reading in readings:
            sensor = self.get_sensor_for_reading(_reading)
            self.current_temperature_readings[_reading.reference] = _reading

            if sensor and sensor.host != self.get_hostname():
                self.log.info(f"Sensor id: {sensor.db_id}, refno: {sensor.reference} "
                              f"is updated with host name ({sensor.host} --> {self.get_hostname()})")
                self.persistence.update_host(sensor, self.get_hostname())

            if _reading.succeeded:
                reporting_sensors_refnos.append(_reading.reference)
                if not sensor:
                    self.log.info(f'Found new temperature sensor. '
                                  f'Host: {self.get_hostname()}, reference: {_reading.reference}')
                    sensor = self.register_new_sensor(_reading.reference)
                    self.log.info(f'Inserted new sensor: {str(sensor)}')

                if not sensor.is_active:
                    self.log.info(f"Sensor id: {sensor.db_id}, refno: {sensor.reference} is activated back again")
                    sensor.is_active = True
                    self.persistence.enable_sensor(sensor)

                last_reading = self.get_last_temperature_reading(sensor)

                if _reading.is_internal:
                    if not last_reading:
                        self.add_temperature_reading(sensor, _reading.temperature, _reading.timestamp)
                        self.internal_temp_readings_sum = 0.0
                        self.internal_temp_readings_count = 0
                    else:
                        polling_period = sensor.polling_period \
                            if sensor.polling_period else self.polling_period_internal_temp

                        if (datetime.now() - last_reading.timestamp).total_seconds() > polling_period:
                            if abs(_reading.temperature - last_reading.temperature) > self.significant_difference:
                                self.add_temperature_reading(sensor, _reading.temperature, _reading.timestamp)
                            self.internal_temp_readings_sum = 0.0
                            self.internal_temp_readings_count = 0
                elif not last_reading \
                        or abs(_reading.temperature - last_reading.temperature) > self.significant_difference:
                    self.add_temperature_reading(sensor, _reading.temperature, _reading.timestamp)

            else:  # reading unsuccessful
                if sensor and sensor.is_active:
                    self.disable_sensor(sensor)

        for sensor in self.sensors:
            if sensor.is_active \
                    and sensor.host == self.get_hostname() \
                    and sensor.reference not in reporting_sensors_refnos:
                self.disable_sensor(sensor)

        self.reading_lock.release()

    def get_sensors(self, refresh_cache: bool = False):
        if not self.sensors or refresh_cache:
            self.log.info('Getting all sensors from database')
            self.sensors = self.persistence.get_sensors(SENSORTYPE_TEMPERATURE)
            self.human_readable_sensor_names.clear()
            for _sensor in self.sensors:
                self.human_readable_sensor_names[_sensor.reference] = \
                    _sensor.location if _sensor.location else _sensor.reference
                self.log.info(str(_sensor))
        return self.sensors

    def get_local_active_sensors(self, refresh_cache: bool = False):
        return filter(lambda _s: _s.host == self.get_hostname() and _s.is_active, self.get_sensors(refresh_cache))

    def get_last_temperature_reading(self, _sensor: Sensor):
        """
        Returns last stored in the database reading. Instead of querying the database, uses the cached value (the cache
        is not available after the service restart, before the first reading is stored).
        Important note: the reading is stored in the database if it is significantly different that the last one.
        Therefore, in order to have up-to-date, accurrate reading, use method get_current_temperature_reading
        :param _sensor: the sensor of interest
        :return: last stored reading from the sensor
        """
        from_cache = self.last_stored_temperature_readings.get(_sensor.reference)
        return from_cache if from_cache else self.persistence.get_last_temperature_reading(_sensor)

    def get_current_temperature_reading(self, _sensor: Sensor):
        """
        Returns the current (most recent) reading of temperature. If there is no such reading (at the very beginning of
        the start of the process), the last stored reading is returned.
        :param _sensor: the sensor of interest
        :return: most up-to-date reading from the sensor
        """
        current = self.current_temperature_readings.get(_sensor.reference)
        return current if current else self.persistence.get_last_temperature_reading(_sensor)

    def add_temperature_reading(self, _sensor: Sensor, temperature: float, timestamp: datetime):
        """
        Stores the temperature reading in the database
        :param _sensor: the sensort reporting the temperature
        :param temperature: the temperature in Celsius degrees
        :param timestamp: the exact time of measurement
        :return: None
        """
        self.last_stored_temperature_readings[_sensor.reference] = \
            self.persistence.add_temperature_reading(_sensor, temperature, timestamp)
        self.log.info(f'Inserted new reading: {str(self.last_stored_temperature_readings[_sensor.reference])} '
                      f'@ {self.get_human_readable_sensor_name(_sensor.reference)}')

    def disable_sensor(self, _sensor: Sensor):
        self.log.info(f"Sensor id: {_sensor.db_id}, refno: {_sensor.reference} "
                      f"({self.get_human_readable_sensor_name(_sensor.reference)}) is deactivated "
                      f"as it is no longer reachable")
        _sensor.is_active = False
        self.persistence.disable_sensor(_sensor)

    def get_readings(self):
        """
        Queries one-wire interface for readings from all available devices
        :return:
        """
        readings = list()
        device_dirs = glob.glob(DEVICES_BASEDIR + '28*')

        for device_dir in device_dirs:
            readings.append(self.get_reading(device_dir))

        readings.append(self.get_internal_temperature_reading())

        return readings

    def get_reading(self, device_dir: str) -> SimpleTemperatureReading:
        """
        Performs N measurements for given device. The aggregated result is provided with:
        (i) temperature as mode of all successful attempts
        (ii) success is reported if at least one measurement succeeded
        The rest of attributes (especially the time mark) is inherited from last measurement.
        N = config.single-measurements-count
        :param device_dir: the device to read from
        :return: the simple-temperature-reading
        """
        measurements = list()
        for _i in range(self.single_measurement_count):
            measurements.append(self.get_single_reading(device_dir=device_dir))

        result = measurements[-1]

        succeeded_measurements = list(filter(lambda x: x.succeeded, measurements))
        result.succeeded = len(succeeded_measurements) > 0

        if result.succeeded:
            result.temperature = stats.mode([m.temperature for m in succeeded_measurements], nan_policy='omit').mode[0]
            self.log.info(f'Read {result.temperature} [\u2103] '
                          f'@ {self.get_human_readable_sensor_name(result.reference)}')

        return result

    def get_single_reading(self, device_dir: str, retry_count: int = 0) -> SimpleTemperatureReading:
        """
        Gets reading of the sensor that reports to a specified dir.
        The method may be called in recurrent way, but with limit.
        :param device_dir: the dir for readings
        :param retry_count: the count of previous attempts to get the reading
        :return: the simple-temperature-reading
        """
        device_file = device_dir + DEVICE_SUBDIR
        sensor_reference = os.path.basename(device_dir)

        if retry_count > 0:
            self.log.debug(f'Retrying to read temperature @ {self.get_human_readable_sensor_name(sensor_reference)} '
                           f'(attempt: {retry_count})')

        success = False
        temp = None
        try:
            with open(device_file, 'r') as file:
                lines = file.read()
                lines = lines.splitlines(keepends=False) if lines is not None else None
                sensor_last_modification = datetime.fromtimestamp(os.stat(device_file).st_mtime)
                if lines is not None and len(lines) > 0 and lines[0].endswith('YES') \
                        and not lines[0].startswith('00 00 00 00 00 00 00 00 00'):
                    temp_matched = self.device_file_re_pattern.match(lines[1])
                    if temp_matched:
                        temp = int(temp_matched.group(1)) / 1000
                        self.log.debug(f'Sensor @ {device_file}, '
                                       f'last-modification: {sensor_last_modification}, '
                                       f'lines: {lines}')
                        success = temp < 85.0
                        if success:
                            self.log.debug(
                                f'Read {temp} [\u2103] @ {self.get_human_readable_sensor_name(sensor_reference)}'
                                f'{"" if retry_count == 0 else ", attempt: "+str(retry_count)}')
                    else:
                        self.log.error(f'Temperature reading @ {device_file} failed. '
                                       f'Cannot parse temperature from {lines[1]} using '
                                       f'pattern {self.device_file_re_pattern.pattern}. '
                                       f'First line is: {lines[0]}')

                else:
                    self.log.error(f'Temperature reading failed. '
                                   f'Read lines are: {lines if lines is not None else "NONE"}')
        except FileNotFoundError:
            self.log.error(f'Temperature reading failed. Error reading from IO: {sys.exc_info()}')

        if not success and retry_count < self.max_retry_count:
            ExitEvent().wait(self.retry_delay)
            return self.get_single_reading(device_dir, retry_count + 1)

        return SimpleTemperatureReading(success, sensor_reference, temp, datetime.now())

    def get_internal_temperature_reading(self) -> SimpleTemperatureReading:
        """
        Collects the temperature of this Raspberry's main processor
        :return: SimpleTemperatureReading providing the temperature reading details
        """
        exec_res = subprocess.run([COMMAND_VCGENCMD, COMMAND_MEASURETEMP], capture_output=True)
        succeeded = False
        temp = None

        exec_stdout = exec_res.stdout.decode('utf-8')

        if exec_res.returncode == 0:
            temp_matched = self.measure_temp_output_re_pattern.match(exec_stdout)
            if temp_matched:
                measured = float(temp_matched.group(1))
                succeeded = True
                self.internal_temp_readings_sum += measured
                self.internal_temp_readings_count += 1
                temp = self.internal_temp_readings_sum / self.internal_temp_readings_count
                self.log.info(f'Read {measured} [\u2103] @ {self.internal_temp_sensor_refno}, '
                              f'average: {temp:.5} [\u2103]')
            else:
                self.log.error(f'Internal temperature cannot be properly parsed from {exec_stdout} '
                               f'using pattern {self.measure_temp_output_re_pattern.pattern}')
        else:
            self.log.error(f'Internal temperature measure failed. Stdout: [{exec_stdout}]. '
                           f'Stderr: [{exec_res.stderr.decode("utf-8")}]')

        return SimpleTemperatureReading(
            succeeded, self.internal_temp_sensor_refno, temp, datetime.now(), is_internal=True)

    def get_sensor_for_reading(self, reading: SimpleTemperatureReading) -> Sensor:
        """
        Locates the sensor with the same reference as the sensor.
        :param reading: the reading of the temperature
        :param sensors: list of all temperature sensors in the database
        :return: the sensor with the same reference as the one from reading
        """
        if not self.sensors or len(self.sensors) == 0:
            self.get_sensors(refresh_cache=True)

        for sensor in self.sensors:
            if sensor.reference == reading.reference:
                return sensor

        return None

    def register_new_sensor(self, reference: str) -> Sensor:
        """
        Registers temperature sensor using provided reference
        :param reference: the reference is the name of directory of the senor in the device tree
        :return: the just inserted sensor
        """
        _sensor = self.persistence.register_sensor(
            sensor_type_name=SENSORTYPE_TEMPERATURE,
            host=self.get_hostname(),
            reference=reference,
            pin=PIN_ONE_WIRE_INTERFACE)
        self.human_readable_sensor_names[reference] = reference
        self.sensors.append(_sensor)
        return _sensor

    def get_human_readable_sensor_name(self, sensor_reference: str) -> str:
        """
        Returns the location of the sensor - or the reference if location is not present
        :param sensor_reference: reference number of the sensor (DS20B18: the serial number)
        :return: the name, which can be used for logs to be more readable
        """
        hrn = self.human_readable_sensor_names.get(sensor_reference)
        return hrn if hrn else sensor_reference

    def get_rest_response_last_temperature_readings(self):
        """
        REST interface: returns temperature last stored in the database for all sensors active in this instance
        :return:
        """
        return self.jsonify([TemperatureReadingJson(
            temperature=self.get_last_temperature_reading(_sensor).temperature,
            timestamp=self.get_last_temperature_reading(_sensor).timestamp,
            sensor_location=_sensor.location,
            sensor_reference=_sensor.reference)
            for _sensor in self.get_local_active_sensors()])

    def get_rest_response_realtime_temperature_readings(self):
        """
        Performs the reading and returns the real-time measurement. Takes long time, but returns real-time value.
        :return: jsonified reading
        """
        if self.reading_lock.locked():
            self.reading_lock.acquire()
            self.reading_lock.release()
        else:
            self.read_and_store_temperature()

        return self.get_rest_response_last_temperature_readings()

    def get_rest_response_current_temperature_readings(self):
        """
        Returns result of last measurement. It compromises between accuracy of the reading (the result is not limited
        by "significant difference") and its speed (there is no measurement done, so it returns immediately)
        :return: the readings in JSON form
        """
        return self.jsonify([TemperatureReadingJson(
            temperature=self.get_current_temperature_reading(_sensor).temperature,
            timestamp=self.get_current_temperature_reading(_sensor).timestamp,
            sensor_location=_sensor.location,
            sensor_reference=_sensor.reference)
            for _sensor in self.get_local_active_sensors()])


if __name__ == '__main__':
    ServiceRunner(TemperatureService).run()
    exit()
