#!/usr/bin/python3

from array import array
from scipy import stats
from collections import deque, Counter
import re

from service.common import *
from device.dev_i2c import *
from device.dev_serial import *
from device.dev_spi import *
from device.buttons import StatelessButton
from core.bean import *
from core.util import TimeWindowList
from util.tendency import TendencyChecker
from persistence.schema import *
from datetime import timedelta


class WeatherStationService(Service):
    """
    Main class responsible for running Wheather Station, compatible with BHS Service (see parent class for details).
    The class hosts:
    - functionality of air quality measure
    - thread objects for measuring other values (pressure, humidity, sunlight luminescence, rain)
    - thread object controlling cooling of the hosting Raspberry
    """

    def __init__(self):
        Service.__init__(self)

        # read configuration
        air_quality_section = 'AIR_QUALITY'
        self.air_quality_warmup_time_s = self.configuration.getIntConfigValue(
            section=air_quality_section,
            parameter='warmup-duration',
            default=60)
        self.air_quality_measure_time_s = self.configuration.getIntConfigValue(
            section=air_quality_section,
            parameter='measure-duration',
            default=60)
        air_quality_power_pin = self.configuration.getIntConfigValue(
            section=air_quality_section,
            parameter='power-pin',
            default=26)

        daylight_section = 'DAYLIGHT'
        daylight_measure_each_ms = self.configuration.getIntConfigValue(
            section=daylight_section,
            parameter='measure-each-milliseconds',
            default=200)
        daylight_detection_threshold = self.configuration.getIntConfigValue(
            section=daylight_section,
            parameter='threshold_percentage',
            default=94
        )
        daylight_detection_threshold_hysteresis = self.configuration.getFloatConfigValue(
            section=daylight_section,
            parameter='threshold_hysteresis',
            default=0.5
        )
        daylight_noticeable_duration = self.configuration.getIntConfigValue(
            section=daylight_section,
            parameter='noticeable-duration',
            default=60
        )

        wind_section = 'WIND'
        wind_direction_measure_each_ms = self.configuration.getIntConfigValue(
            section=wind_section,
            parameter='direction-measure-each-milliseconds',
            default=200)
        anemometer_pin = self.configuration.getIntConfigValue(
            section=wind_section,
            parameter='anemometer-pin',
            default=5)

        rain_gauge_section = 'RAIN-GAUGE'
        rain_gauge_pin = self.configuration.getIntConfigValue(
            section=rain_gauge_section,
            parameter='rain-gauge-pin',
            default=6)
        rain_current_observations_last_hours = self.configuration.getIntConfigValue(
            section=rain_gauge_section,
            parameter='current-observations-last-hours',
            default=12)

        multisensor_section = 'MULTISENSOR'
        multisensor_polling_period = self.configuration.getIntConfigValue(
            section=multisensor_section,
            parameter='measure-polling-period-seconds',
            default=4 * 60 * 60)
        multisensor_measure_each_ms = self.configuration.getIntConfigValue(
            section=multisensor_section,
            parameter='measure-each-milliseconds',
            default=200)
        multisensor_measurement_duration = self.configuration.getIntConfigValue(
            section=multisensor_section,
            parameter='measure-duration-seconds',
            default=200)

        internal_section = 'INTERNAL'
        internal_cooling = self.configuration.getConfigValue(
            section=internal_section,
            parameter='cooling-active',
            default=CoolingConfig.Active.value)
        self.cooling_config = CoolingConfig(internal_cooling)
        internal_fan_pin = self.configuration.getIntConfigValue(
            section=internal_section,
            parameter='cooling-fan-pin',
            default=16)
        internal_cool_down_on_temp = self.configuration.getIntConfigValue(
            section=internal_section,
            parameter='cool-down-temp-on',
            default=43)
        internal_cool_down_off_temp = self.configuration.getIntConfigValue(
            section=internal_section,
            parameter='cool-down-temp-off',
            default=35)

        # polling period will be read from Air Quality Sensor; the default below is actually useless
        self.polling_period = 60 * 60

        # air_quality device
        self.air_quality_device = AirQualityDevice(air_quality_power_pin)
        # last result, utilized by REST interface
        self.last_air_quality_result = None

        # analogue-to-digital device
        self.adc_device = ADCDevice()

        # BME280 device
        self.multisensor_device = MultisensorBME280()

        # sensors cache
        self.sensors = dict()

        # internal threads ('observers')
        self.luminosity_observer = LuminosityObserver(
            parent=self,
            sleep_time_between_measures_s=daylight_measure_each_ms / 1000,
            threshold_percentage=daylight_detection_threshold,
            threshold_hysteresis=daylight_detection_threshold_hysteresis,
            min_duration_s=daylight_noticeable_duration)

        self.multisensor_observer = MultisensorObserver(
            parent=self,
            sleep_time_between_measures_s=multisensor_measure_each_ms / 1000,
            measure_polling_period_s=multisensor_polling_period,
            measure_duration_s=multisensor_measurement_duration)

        self.wind_observer = WindObserver(
            parent=self,
            anemometer_pin=anemometer_pin,
            temp_file_loc='/var/tmp',
            wind_direction_measure_each_ms=wind_direction_measure_each_ms)

        self.rain_gauge_observer = RainGaugeObserver(
            parent=self, gauge_pin=rain_gauge_pin, current_rain_hours=rain_current_observations_last_hours)

        # cooling down fellow host
        self.fan_control = RPiCoolDown(
            parent_service=self,
            pin_fan=internal_fan_pin,
            day_only=self.cooling_config == CoolingConfig.DayOnly,
            on_temperature=internal_cool_down_on_temp,
            off_temperature=internal_cool_down_off_temp)

        # REST URLs configuration
        self.rest_app.add_url_rule('/air_quality', 'air_quality',
                                   self.get_rest_response_last_air_quality)
        self.rest_app.add_url_rule('/daylight', 'daylight',
                                   self.get_rest_response_daylight)
        self.rest_app.add_url_rule('/wind', 'wind',
                                   self.get_rest_response_wind)
        self.rest_app.add_url_rule('/humidity_in', 'humidity_in',
                                   self.get_rest_response_humidity)
        self.rest_app.add_url_rule('/pressure', 'pressure',
                                   self.get_rest_response_pressure)
        self.rest_app.add_url_rule('/rain', 'rain',
                                   self.get_rest_response_rain)

    def main(self) -> float:
        """
        A method called each N seconds as defined by Air Quality Sesnsor.
        Ensures other threads are alive and executes Air Quality scan
        :return: The returned value is period in seconds after which the main method shall be called again.
        """

        mark = datetime.now()

        # check if threads are running
        if not self.luminosity_observer.is_alive():
            self.luminosity_observer.start()

        if not self.multisensor_observer.is_alive():
            self.multisensor_observer.start()

        if self.cooling_config != CoolingConfig.Inactive:
            if not self.fan_control.is_alive():
                self.fan_control.start()

        if not self.wind_observer.is_alive():
            self.wind_observer.start()

        if not self.rain_gauge_observer.is_alive():
            self.rain_gauge_observer.start()

        # air quality
        self.measure_air_quality()

        return self.polling_period - (datetime.now() - mark).total_seconds()

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.luminosity_observer.join()
        self.multisensor_observer.join()
        self.fan_control.join()
        self.wind_observer.join()
        self.rain_gauge_observer.join()

    def provideName(self):
        return 'weather_station'

    def measure_air_quality(self):
        """
        Method responsible for performing Air Quality Scan and storing results to database
        :return:
        """
        # power on
        self.air_quality_device.power.on()

        self.log.debug('Air Quality Sensor is powered. Warming up')

        # warm up
        ExitEvent().wait(self.air_quality_warmup_time_s)

        # mark start time
        time_mark = datetime.now()

        self.log.debug('Sending READ-DATA command to Air Quality Sensor')

        # command to read data
        self.air_quality_device.execute_command_read_data()

        # initialize arrays to store data
        pm10 = array('i')
        pm25 = array('i')

        self.log.debug('Measuring air quality')

        while not ExitEvent().is_set() \
                and (datetime.now() - time_mark).total_seconds() < self.air_quality_measure_time_s:
            try:
                result = self.air_quality_device.read_single()
                pm25.append(int(result.PM_2_5() / 10))
                pm10.append(int(result.PM_10() / 10))

            except AirQualityMeasurementException:
                self.log.error(f'Error occurred during measurement. '
                               f'Additional info: {sys.exc_info()}')
            except IOError:
                self.log.error(f'Error reading from UART device. '
                               f'Additional info: {sys.exc_info()}')

        if len(pm25) > 0:
            final_result = AirQualityMeasurement(
                stats.mode(pm25, nan_policy='omit').mode[0],
                stats.mode(pm10, nan_policy='omit').mode[0])

            self.log.info(f'Air quality results: '
                          f'PM10 = {final_result.PM_2_5()} (mode of {len(pm25)} samples) '
                          f'PM2.5 = {final_result.PM_10()} (mode of {len(pm10)} samples)')

            self.store_air_quality(final_result)
            self.last_air_quality_result = AirQualityReadingJson(
                pm_2_5=final_result.PM_2_5(),
                pm_10=final_result.PM_10())

        else:
            self.last_air_quality_result = ErrorJsonBean(f'All attempts to measure air quality failed')
            self.log.critical(self.last_air_quality_result.error)

        self.air_quality_device.power.off()
        self.log.debug('Air Quality Sensor is turned OFF')

    def store_air_quality(self, pm: AirQualityMeasurement):
        """
        Stores given results of air quality scan to the database.
        :param pm: the result of air quality measure
        :return:
        """
        now = datetime.now()
        self.persistence.store_air_quality_reading(
            self.get_air_quality_pm2_5_sensor(),
            pm.PM_2_5(), now)
        self.persistence.store_air_quality_reading(
            self.get_air_quality_pm10_sensor(),
            pm.PM_10(), now)

    def get_air_quality_pm2_5_sensor(self) -> Sensor:
        """
        Ensures the sensor for measuring Particular Matter 2.5 is initialized (stored in database) and returns it
        :return: the persistence-bean of the sensor
        """
        return self.get_air_quality_sensor(AIRQUALITY_PM2_5_THE_SENSOR_REFERENCE)

    def get_air_quality_pm10_sensor(self) -> Sensor:
        """
        Ensures the sensor for measuring Particular Matter 10 is initialized (stored in database) and returns it
        :return: the persistence-bean of the sensor
        """
        return self.get_air_quality_sensor(AIRQUALITY_PM10_THE_SENSOR_REFERENCE)

    def get_air_quality_sensor(self, reference: str) -> Sensor:
        """
        Ensures the sensor for measuring air quality - as per given reference - exists in the database.
        :param reference: unique identification of given a.q. sensor (either PM 2.5 or 10)
        :return: the persistence-bean of the sensor
        """

        sensor = self.sensors.get(reference)

        if not sensor:
            if reference not in (AIRQUALITY_PM2_5_THE_SENSOR_REFERENCE, AIRQUALITY_PM10_THE_SENSOR_REFERENCE):
                raise ValueError(f'Internal error. Trying to get air quality sensor with reference <{reference}>, '
                                 f'which is not one of air-quality sensor references')

            sensor = self.sensors[reference] = self.persistence.get_sensor(
                sensor_type_name=SENSORTYPE_AIR_QUALITY, reference=reference)

        if not sensor:
            sensor = self.sensors[reference] = self.persistence.register_sensor(
                sensor_type_name=SENSORTYPE_AIR_QUALITY,
                host=self.get_hostname(),
                reference=reference,
                pin=self.air_quality_device.power.pin.number)

            self.log.info(f'New sensor registered: {str(sensor)}')

        return sensor

    def get_luminousity_sensor(self) -> Sensor:
        """
        Method ensures that the sensor measuring daylight has its database representation and then returns it.
        :return: the persistence-bean representing the sensor as fetched from the database
        """
        sensor = self.sensors.get(SUNLIGHT_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[SUNLIGHT_THE_SENSOR_REFERENCE] = self.persistence.get_sensor(
                sensor_type_name=SENSORTYPE_INTENSITY, reference=SUNLIGHT_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[SUNLIGHT_THE_SENSOR_REFERENCE] = self.persistence.register_sensor(
                sensor_type_name=SENSORTYPE_INTENSITY,
                host=self.get_hostname(),
                reference=SUNLIGHT_THE_SENSOR_REFERENCE,
                pin=None)

        return sensor

    def get_rain_gauge_sensor(self) -> Sensor:
        """
        Method ensures that the sensor measuring rain volumes has its database representation and then returns it.
        :return: the persistence-bean representing the sensor as fetched from the database
        """
        sensor = self.sensors.get(RAIN_GAUGE_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[RAIN_GAUGE_THE_SENSOR_REFERENCE] = self.persistence.get_sensor(
                sensor_type_name=SENSORTYPE_IMPLULSE, reference=RAIN_GAUGE_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[RAIN_GAUGE_THE_SENSOR_REFERENCE] = self.persistence.register_sensor(
                sensor_type_name=SENSORTYPE_IMPLULSE,
                host=self.get_hostname(),
                reference=RAIN_GAUGE_THE_SENSOR_REFERENCE,
                pin=self.rain_gauge_observer.observed_pin.pin.number)

        return sensor

    def get_wind_sensor(self) -> Sensor:
        """
        Method ensures that the sensor measuring wind speed and direction has its database representation
        and then returns it.
        :return: the persistence-bean representing the sensor as fetched from the database
        """
        sensor = self.sensors.get(WIND_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[WIND_THE_SENSOR_REFERENCE] = self.persistence.get_sensor(
                sensor_type_name=SENSORTYPE_WIND, reference=WIND_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[WIND_THE_SENSOR_REFERENCE] = self.persistence.register_sensor(
                sensor_type_name=SENSORTYPE_WIND,
                host=self.get_hostname(),
                reference=WIND_THE_SENSOR_REFERENCE,
                pin=self.wind_observer.anemometer.observed_pin.pin.number)

        return sensor

    def store_wind_observation(self) -> WindObservation:
        _direction = self.wind_observer.direction.get_dominant_direction_1hour()
        _speed = self.wind_observer.anemometer.get_observations_1hour()
        _pressure = int(self.multisensor_observer.pressure_tendency_checker.current_mean)
        return self.persistence.store_wind_observation(
            _sensor=self.get_wind_sensor(),
            started_at=min(_direction.started_at, _speed.started_at),
            ended_at=max(_direction.ended_at, _speed.ended_at),
            wind_avg=_speed.average_speed,
            wind_peak=_speed.peak,
            wind_variance=_speed.variance,
            pressure=_pressure,
            direction_dominant=_direction.dominant_direction.value,
            direction_variance=_direction.direction_variance)

    def store_rain_gauge_impulse(self) -> ImpulseCounter:
        _now = datetime.now()
        return self.persistence.store_impulse_counter(
            _sensor=self.get_rain_gauge_sensor(),
            period_start=_now,
            period_end=_now,
            impulse_count=1)

    def get_rest_response_last_air_quality(self):
        """
        Method, which will be called by REST interface when encountering /air_quality URL.
        In response, JSON with the last air quality result is sent.
        :return: FLASK JSON response
        """
        if not self.last_air_quality_result:
            aq_2_5 = self.persistence.get_last_air_quality_reading(self.get_air_quality_pm2_5_sensor())
            aq_10 = self.persistence.get_last_air_quality_reading(self.get_air_quality_pm10_sensor())

            if aq_10 and aq_2_5:
                self.last_air_quality_result = AirQualityReadingJson(
                    pm_2_5=aq_2_5.pm_level,
                    pm_10=aq_10.pm_level,
                    timestamp=aq_2_5.timestamp)

        return self.jsonify(self.last_air_quality_result)

    def get_rest_response_daylight(self):
        """
        Method, which will be called by REST interface when encountering /daylight URL.
        In response, JSON with the last measurement of the luminousity is sent
        together with flag indicating if direct sunlight is detected
        :return: FLASK JSON response
        """
        return self.jsonify(self.luminosity_observer.get_current_observation())

    def get_rest_response_humidity(self):
        """
        Method, which will be called by REST interface when encountering /humidity_in URL.
        In response, JSON with the last measurement of the internal humidity (attic) is sent
        together with tendency basic and detailed information
        :return: FLASK JSON response
        """
        return self.jsonify(self.multisensor_observer.get_humidity_reading())

    def get_rest_response_pressure(self):
        """
        Method, which will be called by REST interface when encountering /pressure URL.
        In response, JSON with the last measurement of the atmospheric pressure is sent
        together with  basic and detailed information on tendency
        :return: FLASK JSON response
        """
        return self.jsonify(self.multisensor_observer.get_pressure_reading())

    def get_rest_response_wind(self):
        """
        This method will be called by REST interface upon an request for wind observation.
        As a response WindObservationsReadingJson will be jsonified and returned
        :return: FLASK JSON response
        """
        return self.jsonify(self.wind_observer.get_current_observation())

    def get_rest_response_rain(self):
        """
        This method will be called by REST interface upon an request for rain gauge (count of impulses) observation.
        As a response RainGaugeObservationReadingJson will be jsonified and returned
        :return: FLASK JSON response
        """
        return self.jsonify(self.rain_gauge_observer.get_current_observations())


class AbstractIntensityObserver(Thread):
    """
    Abstract class collecting common functionality of Daylight and Rain sensors
    Note: since 05.2022 Rain Observer is retired, replaced with Rain Gauge
    """

    def __init__(
            self,
            parent: WeatherStationService,
            sleep_time_between_measures_s: float,
            threshold_percentage: int,
            threshold_hysteresis: float,
            min_duration_s: int):
        """
        Initializes Daylight or Rain observer (separate thread responsible for performing measurements)
        Note: since 05.2022 Rain Observer is retired and replaced by Rain Gauge
        :param parent: the Whether Station service starting the thread
        :param sleep_time_between_measures_s: defines how long the thread should wait until next measure
        :param threshold_percentage: defines the 'starting point' of the direct sunlight or rain
        :param threshold_hysteresis: the allowed deviation from the 'starting point', which will be ignored
        :param min_duration_s: defines minimal time in seconds of duration of 'incident' (direct sunlight or rain)
        to be stored in the database
        """
        Thread.__init__(self)
        self.parent_service = parent
        self.sleep_time_between_measures_s = sleep_time_between_measures_s
        self.is_observation_active = False
        self.failure = False
        self.active_observations = array('i')
        self.active_observations_since: datetime = None
        self.current_observations = deque(maxlen=100)
        self.observation_start_threshold_per_mille = threshold_percentage * 10
        self.observation_stop_threshold_per_mille = \
            self.observation_start_threshold_per_mille - int(threshold_hysteresis * 10)
        self.observation_minimum_duration_seconds = min_duration_s
        self.observation_outliers_count = 0

    def run(self):
        """
        Main method for the thread.
        Once finished, the thread is dead and cannot be resumed.
        :return:
        """
        while not ExitEvent().is_set():
            measurement = self.measure()

            # it is assumed that 100% is not reachable, therefore indicates error
            self.failure = measurement == 1000
            if self.failure:
                continue

            current_state = self.is_active(measurement)

            if current_state != self.is_observation_active:

                if current_state:
                    self.init_measure(measurement)

                if not current_state:
                    self.close_measure((datetime.now() - self.active_observations_since).total_seconds())

                self.is_observation_active = current_state

            if self.is_observation_active:
                self.active_observations.append(measurement)

            self.current_observations.append(measurement)

            ExitEvent().wait(self.sleep_time_between_measures_s)

    def measure(self) -> int:
        """
        Must-have implementaiton that returns the actual measurement
        :return: value in  in per milles
        """
        raise NotImplementedError('Attempt to call abstract method without implementation')

    def is_active(self, measurement: int) -> bool:
        """
        Given the most recent measurement, returns boolean flag denoting if the incident is active
        :param measurement: the current measure
        :return: True if the incident is active
        """
        max_outliers_count = 9
        # detect and ignore outliers: return active if at least one of 10 observations is above 'stop' threshold
        if self.is_observation_active:
            for last_observation in \
                    self.active_observations[-(max_outliers_count + 1)
                    if len(self.active_observations) >= 0 else len(self.active_observations):]:
                if last_observation >= self.observation_stop_threshold_per_mille:
                    return True

        return measurement >= self.observation_start_threshold_per_mille if not self.is_observation_active \
            else measurement >= self.observation_stop_threshold_per_mille

    def init_measure(self, first_measure: int):
        """
        Method called upon incident start.
        :param first_measure: the initiating measure
        :return:
        """
        self.parent_service.log.info(
            f'Threshold for {str(self)} is exceeded: {first_measure}, observation is starting')

        self.active_observations_since = datetime.now()
        self.active_observations = array('i')

    def provide_sensor(self) -> Sensor:
        """
        Must-have implemenation returning the database sensor
        :return:
        """
        raise NotImplementedError('Attempt to call abstract method without implementation')

    def close_measure(self, duration):
        """
        Method call upon end of an incident. If the duration is apprpriate, the observation will be stored in db
        :param duration:
        :return:
        """
        if duration > self.observation_minimum_duration_seconds:

            mean = stats.tmean(self.active_observations) / 10
            variance = stats.variation(self.active_observations) / 10

            self.parent_service.log.info(f'Closing reading for {str(self)}. '
                                         f'During {duration} seconds, '
                                         f'{len(self.active_observations)} observations were made. '
                                         f'Average intensity: {mean}, variance: {variance}')

            stored_reading = self.parent_service.persistence.store_intensity_reading(
                self.provide_sensor(),
                self.active_observations_since,
                duration,
                mean,
                variance,
                datetime.now())

            self.parent_service.log.debug(f'Stored new intensity reading: {str(stored_reading)}')

        else:
            self.parent_service.log.debug(f'Duration of an observation {str(self)} is too short. Resetting')

        del self.active_observations

    def get_current_observation(self) -> AbstractJsonBean:
        """
        Must-have method providing current observation for REST interface
        :return: either DaylightReadingJson or RainReadingJson
        """
        raise NotImplementedError()


class AbstractADCObserver(AbstractIntensityObserver):
    """
    Another abstract layer for Luminosity and Rain sensors' observers
    """

    def __init__(
            self,
            parent: WeatherStationService,
            sleep_time_between_measures_s: float,
            threshold_percentage: int,
            threshold_hysteresis: float,
            min_duration_s: int):
        AbstractIntensityObserver.__init__(
            self,
            parent,
            sleep_time_between_measures_s,
            threshold_percentage,
            threshold_hysteresis,
            min_duration_s)

    def provide_channel(self) -> int:
        """
        Abstract method, which must be implemented by all subclasses providing the channel number
        :return: channel no
        """
        raise NotImplementedError('Attempt to call abstract method without implementation')

    def provide_sensor(self) -> Sensor:
        raise NotImplementedError('Attempt to call abstract method without implementation')

    def get_current_observation(self) -> AbstractJsonBean:
        """
        Must-have method providing current observation for REST interface
        :return: either DaylightReadingJson or RainReadingJson
        """
        raise NotImplementedError()

    def measure(self) -> int:
        return self.parent_service.adc_device.read_percentile(self.provide_channel())


class LuminosityObserver(AbstractADCObserver):
    """
    Class responsible for measuring daylight
    """

    def __init__(
            self,
            parent: WeatherStationService,
            sleep_time_between_measures_s: float,
            threshold_percentage: int,
            threshold_hysteresis: float,
            min_duration_s: int):
        """
        Initializes Daylight observer (separate thread responsible for performing measurements)
        :param parent: the Whether Station service starting the thread
        :param sleep_time_between_measures_s: defines how long the thread should wait until next measure
        :param threshold_percentage: defines the 'starting point' of the direct sunlight
        :param threshold_hysteresis: the allowed deviation from the 'starting point', which will be ignored
        :param min_duration_s: defines minimal time in seconds of duration of direct sunlight
        to be stored in the database
        """
        AbstractADCObserver.__init__(
            self,
            parent,
            sleep_time_between_measures_s,
            threshold_percentage,
            threshold_hysteresis,
            min_duration_s)

    def __str__(self):
        return f'Luminosity observer ' \
               f'[threshold: {self.observation_start_threshold_per_mille} \u2030, ' \
               f'min duration: {self.observation_minimum_duration_seconds} seconds]'

    def provide_channel(self) -> int:
        """
        Returns appropriate channel in AD converter device
        :return: 1
        """
        return 1

    def provide_sensor(self) -> Sensor:
        """
        Calls parent service to obtain luminosity sensor object
        :return:
        """
        return self.parent_service.get_luminousity_sensor()

    def get_current_observation(self) -> AbstractJsonBean:
        """
        Method invoked by REST interface to get current observation as JSON-ready object
        :return: ErrorJsonBean if the thread is dead. NotAvailableJsonBean if there are no observations made
        (highly improbable). DaylightReadingJson if the observation is up and running, containg average percentage
        value of the current luminescence and flag denoting if observation is active
        """
        if not self.is_alive():
            return ErrorJsonBean('Error occurred')

        if self.failure:
            return ErrorJsonBean('Reading is 100%, which is interpreted as failure')

        if len(self.current_observations) == 0:
            return NotAvailableJsonBean()

        return DaylightReadingJson(
                luminescence_perc=int(stats.tmean(self.current_observations) / 10),
                is_sunlight=self.is_observation_active)


class Impulse:
    def __init__(self,
                 time_mark: datetime = datetime.now(),
                 duration_s: float = 0.0, time_since_previous_s: float = 0.0):
        self.time_mark = time_mark
        self.duration_s = duration_s
        self.time_since_previous_s = time_since_previous_s

    def get_time_mark(self):
        return self.time_mark

    def to_json(self):
        return json.dumps([self.time_mark.isoformat(), self.duration_s, self.time_since_previous_s])

    @staticmethod
    def from_json(jsn: str):
        _parsed = json.loads(jsn)
        return Impulse(time_mark=datetime.fromisoformat(_parsed[0]),
                       duration_s=float(_parsed[1]),
                       time_since_previous_s=float(_parsed[2]))


class WinDirReading:
    def __init__(self, time_mark: datetime, direction: WindDirection):
        self.time_mark = time_mark
        self.direction = direction

    def get_time_mark(self):
        return self.time_mark

    def to_json(self):
        return json.dumps([self.time_mark.isoformat(), self.direction.value])

    @staticmethod
    def from_json(jsn: str):
        _parsed = json.loads(jsn)
        return WinDirReading(
            time_mark=datetime.fromisoformat(_parsed[0]),
            direction=WindDirection(int(_parsed[1])))


class WindDirectionObservation:
    """
    Simple bean-like class, which purpose is to collect all wind direction observation attributes
    """
    def __init__(self,
                 dominant_direction: WindDirection,
                 direction_variance: int,
                 started_at: datetime,
                 ended_at: datetime):
        self.dominant_direction = dominant_direction
        self.direction_variance = direction_variance
        self.started_at = started_at
        self.ended_at = ended_at

    def duration_s(self) -> int:
        return 0 if self.started_at is None or self.ended_at is None \
            else int((self.ended_at - self.started_at).total_seconds())


class WindSpeedObservation:
    """
    Simple bean-like class, which aim is to collect all the outputs of wind speed observation
    """
    def __init__(self, average_speed: float, peak: float, variance: float, started_at: datetime, ended_at: datetime):
        self.average_speed = average_speed
        self.peak = peak
        self.variance = variance
        self.started_at = started_at
        self.ended_at = ended_at

    def duration_s(self) -> int:
        return 0 if self.started_at is None or self.ended_at is None \
            else int((self.ended_at - self.started_at).total_seconds())


class WindObserver(Thread):
    DURATION_1MIN_S = 60
    DURATION_1HOUR_S = 60 * 60

    def __init__(self,
                 parent: WeatherStationService,
                 anemometer_pin: int,
                 temp_file_loc: str,
                 wind_direction_measure_each_ms: int):
        Thread.__init__(self)
        self.parent = parent
        self.anemometer = self.AnemometerObserver(pin=anemometer_pin, temp_file_loc=temp_file_loc)
        self.direction = self.WindDirectionObserver(
            parent=parent,
            temp_file_loc=temp_file_loc,
            sleep_time_between_measures_s=wind_direction_measure_each_ms/1000)

    def run(self) -> None:
        # restore last reading

        # start sub-threads
        self.anemometer.start()
        self.direction.start()

        while not ExitEvent().is_set():
            # sleeps till full hour
            ExitEvent().wait(
                timeout=(
                    (datetime.now() + timedelta(hours=1)).
                    replace(minute=0, second=0, microsecond=0) - datetime.now()).total_seconds())
            # store the reading to database
            if not ExitEvent().is_set() and self.anemometer.last_observation_at is not None:
                try:
                    db_bean = self.parent.store_wind_observation()
                    self.parent.log.info(f'Wind observation stored to database: {str(db_bean)}')

                    _unknown_dir = self.direction.unknown_readings_1hour()
                    mc_unknown_dir_list = ",".join([f"{_mc}: {int(100*_mc[1]/len(_unknown_dir))}%"
                                                    for _mc in Counter(_unknown_dir).most_common(10)])
                    _all_dir_readings = self.direction.all_readings_1hour()
                    mc_all_dir_list = ",".join([f"{_mc[0].name}: {int(100*_mc[1]/len(_all_dir_readings))}%"
                                                for _mc in Counter(_all_dir_readings).most_common()])
                    if db_bean.direction_dominant == WindDirection.UNKNOWN.value:
                        self.parent.log.warning(f'There is a lot of wind direction unknown readings '
                                                f'({len(_unknown_dir)}): {mc_unknown_dir_list}')
                        self.parent.log.info(f'All detected directions: {mc_all_dir_list}')
                    else:
                        self.parent.log.debug(f'There is {len(_unknown_dir)} unknown wind direction readings. '
                                              f'Most common are: {mc_unknown_dir_list}')
                        self.parent.log.debug(f'All detected directions: {mc_all_dir_list}')

                except Exception as e:
                    self.parent.log.critical(f'ERROR during storing wind observation: {str(e)}', exc_info=e)

        # wait for other threads to die
        self.anemometer.join()
        self.direction.join()

    def get_current_observation(self) -> WindObservationsReadingJson:
        direction_1min = self.direction.get_dominant_direction_1min()
        speed_1min = self.anemometer.get_observations_1min()
        direction_1hour = self.direction.get_dominant_direction_1hour()
        speed_1hour = self.anemometer.get_observations_1hour()

        return WindObservationsReadingJson(
            short_term_observation=WindObservationReadingJson(
                duration_s=direction_1min.duration_s() if direction_1min.duration_s() > speed_1min.duration_s()
                else speed_1min.duration_s(),
                direction=direction_1min.dominant_direction,
                direction_var=direction_1min.direction_variance,
                wind_speed=speed_1min.average_speed,
                wind_peak=speed_1min.peak,
                wind_variance=speed_1min.variance),
            long_term_observation=WindObservationReadingJson(
                duration_s=direction_1hour.duration_s() if direction_1hour.duration_s() > speed_1hour.duration_s()
                else speed_1hour.duration_s(),
                direction=direction_1hour.dominant_direction,
                direction_var=direction_1hour.direction_variance,
                wind_speed=speed_1hour.average_speed,
                wind_peak=speed_1hour.peak,
                wind_variance=speed_1hour.variance))

    class AnemometerObserver(Thread):
        ONE_IMPULSE_PER_SEC_IS_KMPH = 2.4
        STORE_TEMP_DATA_EACH_S = 600

        def __init__(self, pin: int, temp_file_loc: str):
            Thread.__init__(self)
            self.last_observation_at: datetime = None
            self.observed_pin = StatelessButton(pin, self._on_signal)
            self._observations_1min = TimeWindowList(
                validity_time_s=WindObserver.DURATION_1MIN_S, get_time_mark_function=lambda x: x.get_time_mark())
            self._observations_1hour = TimeWindowList(
                validity_time_s=WindObserver.DURATION_1HOUR_S, get_time_mark_function=lambda x: x.get_time_mark())
            self._temp_file_1min = os.path.join(temp_file_loc, f'anemometer_1min.json')
            self._temp_file_1hour = os.path.join(temp_file_loc, f'anemometer_1hour.json')
            self._observations_1min.from_file(file_path=self._temp_file_1min, from_json=Impulse.from_json)
            self._observations_1hour.from_file(file_path=self._temp_file_1hour, from_json=Impulse.from_json)

        def run(self) -> None:
            while not ExitEvent().is_set():
                ExitEvent().wait(timeout=self.STORE_TEMP_DATA_EACH_S)
                # store temp data
                self._observations_1min.to_file(file_path=self._temp_file_1min, to_json=Impulse.to_json)
                self._observations_1hour.to_file(file_path=self._temp_file_1hour, to_json=Impulse.to_json)

            self.observed_pin.close()

        def _on_signal(self, duration: float, pin: int):
            _now = datetime.now()
            _impulse = Impulse(time_mark=_now,
                               duration_s=duration,
                               time_since_previous_s=0.0 if self.last_observation_at is None
                               else (_now - self.last_observation_at).total_seconds())
            self.last_observation_at = _now
            self._observations_1min.append(_impulse)
            self._observations_1hour.append(_impulse)

        def get_observations_1min(self) -> WindSpeedObservation:
            return self._get_observations(self._observations_1min)

        def get_observations_1hour(self) -> WindSpeedObservation:
            return self._get_observations(self._observations_1hour)

        def _get_observations(self, obs: TimeWindowList) -> WindSpeedObservation:
            _wind_speed = obs.as_list()
            if len(_wind_speed) == 0:
                return WindSpeedObservation(
                    average_speed=0, peak=0, variance=0, started_at=datetime.now(), ended_at=datetime.now())

            _tw = obs.time_window()
            _duration = (_tw[1] - _tw[0]).total_seconds()

            # the below defines the outliers for wind speed
            # 200 kmph is an arbitrary number, taken out of thumb
            _outliers = (0, 200)
            _outliers_are_included = (False, False)

            # WIND SPEED
            # from documentation of the sensor:
            # "a wind speed of 2.4km/h causes the switch to close once per second"

            # Calculation the average is not so easy.
            # The best option is to use the "count of impulses per period", but as the impulses can be
            # stored\restored with gaps between, it is better to measure the average of momentary speeds
            # Therefore, start with detecting if there are gaps
            _momentary_speed = [
                self.ONE_IMPULSE_PER_SEC_IS_KMPH/_imp.time_since_previous_s if _imp.time_since_previous_s > 0 else 0
                for _imp in _wind_speed]
            if min(_momentary_speed) == 0:
                # calculate the average from momentary speeds
                _average = stats.tmean(_momentary_speed, limits=_outliers, inclusive=_outliers_are_included)
            else:
                # there are no gaps in measurements; calculate the speed by couting all impulses within obs. window
                _average = (self.ONE_IMPULSE_PER_SEC_IS_KMPH * len(_wind_speed) / _duration) if _duration > 0 else 0

            _variance = stats.tvar(_momentary_speed, limits=_outliers, inclusive=_outliers_are_included)
            _peak = stats.tmax(_momentary_speed, upperlimit=_outliers[1], inclusive=_outliers_are_included[1])

            return WindSpeedObservation(
                average_speed=_average,
                peak=_peak,
                variance=_variance,
                started_at=_tw[0], ended_at=_tw[1])

    class WindDirectionObserver(Thread):
        STORE_TEMP_DATA_EACH_S = 600

        def __init__(self, parent: WeatherStationService, temp_file_loc: str, sleep_time_between_measures_s: float):
            Thread.__init__(self)
            self._parent_service = parent
            self._temp_file_1min = os.path.join(temp_file_loc, f'windir_1min.json')
            self._temp_file_1hour = os.path.join(temp_file_loc, f'windir_1hour.json')
            self._observations_1min = TimeWindowList(
                validity_time_s=WindObserver.DURATION_1MIN_S, get_time_mark_function=lambda x: x.get_time_mark())
            self._observations_1hour = TimeWindowList(
                validity_time_s=WindObserver.DURATION_1HOUR_S, get_time_mark_function=lambda x: x.get_time_mark())
            self._observations_1min.from_file(file_path=self._temp_file_1min, from_json=WinDirReading.from_json)
            self._observations_1hour.from_file(file_path=self._temp_file_1hour, from_json=WinDirReading.from_json)
            self._temp_file_last_stored = datetime.now()
            self._sleep_time_between_measures_s = sleep_time_between_measures_s
            self._measurement_to_direction = {}
            for _p in range(101):
                if 35 < _p <= 50:
                    self._measurement_to_direction[_p] = WindDirection.N
                elif 50 < _p <= 54:
                    self._measurement_to_direction[_p] = WindDirection.NE
                elif 54 < _p <= 58:
                    self._measurement_to_direction[_p] = WindDirection.E
                elif 58 < _p <= 70:
                    self._measurement_to_direction[_p] = WindDirection.NW
                elif 70 < _p <= 77:
                    self._measurement_to_direction[_p] = WindDirection.SE
                elif 77 < _p <= 84:
                    self._measurement_to_direction[_p] = WindDirection.W
                elif 84 < _p <= 90:
                    self._measurement_to_direction[_p] = WindDirection.SW
                elif 90 < _p <= 99:
                    self._measurement_to_direction[_p] = WindDirection.S
                else:
                    self._measurement_to_direction[_p] = WindDirection.UNKNOWN
            self._unknown_readings = TimeWindowList(validity_time_s=60*60, get_time_mark_function=lambda x: x[1])

        def run(self) -> None:
            while not ExitEvent().is_set():
                # read
                _reading = self._read()
                self._observations_1min.append(_reading)
                self._observations_1hour.append(_reading)

                ExitEvent().wait(timeout=self._sleep_time_between_measures_s)

                if (datetime.now() - self._temp_file_last_stored).total_seconds() > self.STORE_TEMP_DATA_EACH_S \
                        or ExitEvent().is_set():
                    # store temp data
                    self._observations_1min.to_file(file_path=self._temp_file_1min, to_json=WinDirReading.to_json)
                    self._observations_1hour.to_file(file_path=self._temp_file_1hour, to_json=WinDirReading.to_json)
                    self._temp_file_last_stored = datetime.now()

        def _read(self) -> WinDirReading:
            _raw_reading = int(self._parent_service.adc_device.read_percentile(2) / 10)
            _direction = self._measurement_to_direction[_raw_reading]
            if _direction == WindDirection.UNKNOWN:
                self._unknown_readings.append((_raw_reading, datetime.now()))
            return WinDirReading(
                time_mark=datetime.now(),
                direction=_direction
            )

        def get_dominant_direction_1min(self) -> WindDirectionObservation:
            return self._get_dominant_direction(self._observations_1min)

        def get_dominant_direction_1hour(self) -> WindDirectionObservation:
            return self._get_dominant_direction(self._observations_1hour)

        def unknown_readings_1hour(self) -> list:
            return [_ur[0] for _ur in self._unknown_readings.as_list()]

        def all_readings_1hour(self) -> list:
            return [_r.direction for _r in self._observations_1hour.as_list()]

        @staticmethod
        def _get_dominant_direction(window_observations: TimeWindowList) -> WindDirectionObservation:
            _observations = window_observations.as_list()
            _tw = window_observations.time_window()
            if len(_observations) == 0:
                return WindDirectionObservation(
                    dominant_direction=WindDirection.UNKNOWN,
                    direction_variance=0,
                    started_at=_tw[0], ended_at=_tw[1])

            _counter = Counter([_obs.direction for _obs in _observations])
            _dominant = _counter.most_common(1)
            return WindDirectionObservation(
                dominant_direction=_dominant[0][0],
                direction_variance=100-int(100.0*_dominant[0][1]/len(_observations)),
                started_at=_tw[0], ended_at=_tw[1])


class RainGaugeObserver(Thread):

    def __init__(self, parent: WeatherStationService, gauge_pin: int, current_rain_hours: int):
        Thread.__init__(self)
        self.parent = parent
        self.observed_pin = StatelessButton(gauge_pin, self._on_signal)
        self.current_rain_hours = current_rain_hours
        self.current_rain_observations = TimeWindowList(
            validity_time_s=current_rain_hours * 60 * 60, get_time_mark_function=lambda x: x)

    def run(self) -> None:
        # restore the rain observations for last hours
        self.current_rain_observations.extend(
            self.parent.persistence.rain_observations_last_hours(
                the_sensor=self.parent.get_rain_gauge_sensor(),
                the_date=datetime.now(),
                hours_in_the_past=self.current_rain_hours))

        ExitEvent().wait()
        self.observed_pin.close()

    def _on_signal(self, duration: float, pin: int):
        try:
            # TBC: what if the database is down? Maybe the process should be asynchronous?
            db_bean = self.parent.store_rain_gauge_impulse()
            self.parent.log.info(f'Impulse has been stored to database: {str(db_bean)}')
            self.current_rain_observations.append(db_bean.period_start)
        except Exception as e:
            self.parent.log.critical(f'ERROR during handling rain gauge signal: {str(e)}', exc_info=e)

    def get_current_observations(self):
        return RainGaugeObservationsReadingJson(
            observation_duration_h=self.current_rain_hours,
            observations=self.current_rain_observations.as_list(),
            timestamp=datetime.now())


class MultisensorReading:
    """
    A simple class concatenating results of Multisensor measurements.
    """

    def __init__(self, temperature: float, humidity: int, pressure: int,
                 temperature_tendency: TendencyChecker,
                 humidity_tendency: TendencyChecker,
                 pressure_tendency: TendencyChecker,
                 timestamp: datetime = datetime.now()):
        """
        Initializes the measurement coming from Multisensor

        :param temperature: the current reading of the temperature
        :param humidity: the current reading of the humidity
        :param pressure: the current reading of the pressure
        :param temperature_tendency: TendencyChecker object used to determine tendency of the temperature
        :param humidity_tendency: TendencyChecker object used to determine tendency of the humidity
        :param pressure_tendency: TendencyChecker object used to determine tendency of the pressure
        :param timestamp: the current time, defult is _now_
        """
        self.temperature = temperature
        self.humidity = humidity
        self.pressure = pressure

        self.temperature_tendency = temperature_tendency.tendency(temperature)
        self.humidity_tendency = humidity_tendency.tendency(humidity)
        self.pressure_tendency = pressure_tendency.tendency(pressure)

        self.temperature_tendency_explained = temperature_tendency.verbose()
        self.humidity_tendency_explained = humidity_tendency.verbose()
        self.pressure_tendency_explained = pressure_tendency.verbose()

        self.timestamp = timestamp

    def __str__(self):
        return f'Pressure: {self.pressure} [hPa] ({self.pressure_tendency_explained}), ' \
               f'humidity: {self.humidity} [%] ({self.humidity_tendency_explained}), ' \
               f'temperature: {self.temperature} [\u2103] ({self.temperature_tendency_explained})'


class MultisensorObserver(Thread):
    def __init__(
            self,
            parent: WeatherStationService,
            sleep_time_between_measures_s: float,
            measure_polling_period_s: int,
            measure_duration_s: int):
        Thread.__init__(self)
        self.parent_service = parent
        self.sleep_time_between_measures_s = sleep_time_between_measures_s
        self.measure_pooling_period = measure_polling_period_s
        self.measure_duration = measure_duration_s
        self.current_reading: MultisensorReading = None
        # 1h
        self.temperature_tendency_checker = TendencyChecker(
            observations_window=int(1 * 60 * 60 / (measure_polling_period_s + measure_duration_s)), threshold_perc=0.2)
        # 2h
        self.humidity_tendency_checker = TendencyChecker(
            observations_window=int(2 * 60 * 60 / (measure_polling_period_s + measure_duration_s)), threshold_perc=0.1)
        # 10h
        self.pressure_tendency_checker = TendencyChecker(
            observations_window=int(10 * 60 * 60 / (measure_polling_period_s + measure_duration_s)),
            threshold_perc=0.05)

    def run(self):
        while not ExitEvent().is_set():
            temperature_observations = array('i')
            pressure_observations = array('i')
            humidity_observations = array('i')

            # mark start time
            time_mark = datetime.now()

            try:
                while not ExitEvent().is_set() \
                        and (datetime.now() - time_mark).total_seconds() < self.measure_pooling_period:
                    current = self.parent_service.multisensor_device.read(
                        timeout_seconds=self.sleep_time_between_measures_s)

                    temperature_observations.append(int(current.temperature() * 10))
                    pressure_observations.append(current.pressure())
                    humidity_observations.append(int(current.humidity()))

                    ExitEvent().wait(self.sleep_time_between_measures_s)

                self.current_reading = MultisensorReading(
                    temperature=float(stats.mode(temperature_observations, nan_policy='omit').mode[0] / 10),
                    humidity=int(stats.mode(humidity_observations, nan_policy='omit').mode[0]),
                    pressure=int(stats.mode(pressure_observations, nan_policy='omit').mode[0]),
                    temperature_tendency=self.temperature_tendency_checker,
                    humidity_tendency=self.humidity_tendency_checker,
                    pressure_tendency=self.pressure_tendency_checker)

                self.parent_service.log.debug(f'Multisensor results: {str(self.current_reading)}')

            except MultisensorReadingException as e:
                self.parent_service.log.critical(f'Multisenor malfunctioned. Details: {str(e)}')

            ExitEvent().wait(self.measure_pooling_period)

    def get_temperature_reading(self) -> AbstractJsonBean:
        if not self.is_alive():
            return ErrorJsonBean('Error occurred')

        if not self.current_reading:
            return NotAvailableJsonBean()

        return ValueTendencyJson(
            value=self.current_reading.temperature,
            tendency=self.current_reading.temperature_tendency,
            timestamp=self.current_reading.timestamp,
            current_mean=self.temperature_tendency_checker.current_mean,
            previous_mean=self.temperature_tendency_checker.previous_mean)

    def get_pressure_reading(self) -> AbstractJsonBean:
        if not self.is_alive():
            return ErrorJsonBean('Error occurred')

        if not self.current_reading:
            return NotAvailableJsonBean()

        return ValueTendencyJson(
            value=self.current_reading.pressure,
            tendency=self.current_reading.pressure_tendency,
            timestamp=self.current_reading.timestamp,
            current_mean=self.pressure_tendency_checker.current_mean,
            previous_mean=self.pressure_tendency_checker.previous_mean)

    def get_humidity_reading(self) -> AbstractJsonBean:
        if not self.is_alive():
            return ErrorJsonBean('Error occurred')

        if not self.current_reading:
            return NotAvailableJsonBean()

        return ValueTendencyJson(
            value=self.current_reading.humidity,
            tendency=self.current_reading.humidity_tendency,
            timestamp=self.current_reading.timestamp,
            current_mean=self.humidity_tendency_checker.current_mean,
            previous_mean=self.humidity_tendency_checker.previous_mean)


class CoolingConfig(Enum):
    Inactive = 'inactive'
    Active = 'active'
    DayOnly = 'day-only'


class RPiCoolDown(Thread):
    def __init__(self, parent_service: Service, pin_fan: int, day_only: bool, on_temperature: int,
                 off_temperature: int):
        Thread.__init__(self)
        self.parent_service = parent_service
        self.fan = DigitalOutputDevice(pin=pin_fan, active_high=False)
        self.on_temp = on_temperature
        self.off_temp = off_temperature
        self.probing_period = 1
        self.day_only = day_only
        self.day_only_hour_on = 8
        self.day_only_hour_off = 22

        self.COMMAND_VCGENCMD = 'vcgencmd'
        self.COMMAND_MEASURETEMP = 'measure_temp'

        self.measure_temp_output_re_pattern = re.compile('temp=(\\d+\\.\\d*).*')

    def run(self):
        while not ExitEvent().is_set():
            exec_res = subprocess.run([self.COMMAND_VCGENCMD, self.COMMAND_MEASURETEMP], capture_output=True)

            exec_stdout = exec_res.stdout.decode('utf-8')

            if exec_res.returncode == 0:
                temp_matched = self.measure_temp_output_re_pattern.match(exec_stdout)
                if temp_matched:
                    temp = float(temp_matched.group(1))

                    if temp > self.on_temp and not self.fan.is_active and (
                            not self.day_only
                            or (self.day_only_hour_on <= datetime.now().hour < self.day_only_hour_off)):
                        self.parent_service.log.info(f'{self.parent_service.get_hostname()} '
                                                     f'reached temperature {temp}, '
                                                     f'turning on cooling at {self.fan.pin}')
                        self.fan.on()
                    elif temp < self.off_temp and self.fan.is_active:
                        self.parent_service.log.info(f'{self.parent_service.get_hostname()} '
                                                     f'reached temperature {temp}, '
                                                     f'stopping cooling at {self.fan.pin}')
                        self.fan.off()

                else:
                    self.parent_service.log.error(f'Internal temperature cannot be properly parsed from {exec_stdout} '
                                                  f'using pattern {self.measure_temp_output_re_pattern.pattern}')
            else:
                self.parent_service.log.error(f'Internal temperature measure failed. Stdout: [{exec_stdout}]. '
                                              f'Stderr: [{exec_res.stderr.decode("utf-8")}]')

            ExitEvent().wait(self.probing_period)
        self.fan.close()


if __name__ == '__main__':
    ServiceRunner(WeatherStationService).run()
    exit()
