#!/usr/bin/python3

from array import array
from scipy import stats
from collections import deque
import re

from service.common import *
from device.dev_i2c import *
from device.dev_serial import *
from device.dev_spi import *
from core.bean import *
from persistence.schema import *


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
            default=97
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

        rain_section = 'RAIN'
        rain_measure_each_ms = self.configuration.getIntConfigValue(
            section=rain_section,
            parameter='measure-each-milliseconds',
            default=200)
        rain_detection_threshold = self.configuration.getIntConfigValue(
            section=rain_section,
            parameter='threshold_percentage',
            default=50
        )
        rain_detection_threshold_hysteresis = self.configuration.getFloatConfigValue(
            section=rain_section,
            parameter='threshold_hysteresis',
            default=1
        )
        rain_noticeable_duration = self.configuration.getIntConfigValue(
            section=rain_section,
            parameter='noticeable-duration',
            default=60
        )

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

        self.rain_observer = RainObserver(
            parent=self,
            sleep_time_between_measures_s=rain_measure_each_ms / 1000,
            threshold_percentage=rain_detection_threshold,
            threshold_hysteresis=rain_detection_threshold_hysteresis,
            min_duration_s=rain_noticeable_duration)

        self.multisensor_observer = MultisensorObserver(
            parent=self,
            sleep_time_between_measures_s=multisensor_measure_each_ms / 1000,
            measure_polling_period_s=multisensor_polling_period,
            measure_duration_s=multisensor_measurement_duration)

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
        self.rest_app.add_url_rule('/rain', 'rain',
                                   self.get_rest_response_rain)
        self.rest_app.add_url_rule('/humidity_in', 'humidity_in',
                                   self.get_rest_response_humidity)
        self.rest_app.add_url_rule('/pressure', 'pressure',
                                   self.get_rest_response_pressure)

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

        if not self.rain_observer.is_alive():
            self.rain_observer.start()

        if not self.multisensor_observer.is_alive():
            self.multisensor_observer.start()

        if self.cooling_config != CoolingConfig.Inactive:
            if not self.fan_control.is_alive():
                self.fan_control.start()

        # air quality
        self.measure_air_quality()

        return self.polling_period - (datetime.now() - mark).total_seconds()

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

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

    def get_rain_sensor(self):
        """
        Method ensures that the sensor measuring rain intensity has its database representation and then returns it.
        :return: the persistence-bean representing the sensor as fetched from the database
        """
        sensor = self.sensors.get(RAIN_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[RAIN_THE_SENSOR_REFERENCE] = self.persistence.get_sensor(
                sensor_type_name=SENSORTYPE_INTENSITY, reference=RAIN_THE_SENSOR_REFERENCE)

        if not sensor:
            sensor = self.sensors[RAIN_THE_SENSOR_REFERENCE] = self.persistence.register_sensor(
                sensor_type_name=SENSORTYPE_INTENSITY,
                host=self.get_hostname(),
                reference=RAIN_THE_SENSOR_REFERENCE,
                pin=None)

        return sensor

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

    def get_rest_response_rain(self):
        """
        Method, which will be called by REST interface when encountering /rain URL.
        In response, JSON with the last measurement of the rain detector is sent
        together with flag indicating if the actual rain is detected
        :return: FLASK JSON reponse
        """
        return self.jsonify(self.rain_observer.get_current_observation())

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


class AbstractIntensityObserver(Thread):
    """
    Abstract class collecting common functionality of Daylight and Rain sensors
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
                break

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


class RainObserver(AbstractADCObserver):

    def __init__(
            self,
            parent: WeatherStationService,
            sleep_time_between_measures_s: float,
            threshold_percentage: int,
            threshold_hysteresis: float,
            min_duration_s: int):
        """
        Initializes Rain Observer (separate thread responsible for performing measurements)
        :param parent: the Whether Station service starting the thread
        :param sleep_time_between_measures_s: defines how long the thread should wait until next measure
        :param threshold_percentage: defines the 'starting point' of the rain
        :param threshold_hysteresis: the allowed deviation from the 'starting point', which will be ignored
        :param min_duration_s: defines minimal time in seconds of duration of rain to be stored in the database
        """
        AbstractADCObserver.__init__(
            self,
            parent,
            sleep_time_between_measures_s,
            threshold_percentage,
            threshold_hysteresis,
            min_duration_s)

    def __str__(self):
        return f'Rain observer ' \
               f'[threshold: {self.observation_start_threshold_per_mille} \u2030, ' \
               f'min duration: {self.observation_minimum_duration_seconds} seconds]'

    def provide_channel(self) -> int:
        """
        Returns appropriate channel in AD converter device
        :return: 2
        """
        return 2

    def provide_sensor(self) -> Sensor:
        """
        Calls parent service to obtain rain sensor object
        :return:
        """
        return self.parent_service.get_rain_sensor()

    def get_current_observation(self) -> AbstractJsonBean:
        """
        Method invoked by REST interface to get current observation as JSON-ready object
        :return: ErrorJsonBean if the thread is dead. NotAvailableJsonBean if there are no observations made
        (highly improbable). DaylightReadingJson if the observation is up and running, containg average percentage
        value of the current rain intensity and flag denoting if observation is active
        """
        if not self.is_alive():
            return ErrorJsonBean('Error occurred')

        if len(self.current_observations) == 0:
            return NotAvailableJsonBean()

        return RainReadingJson(
            volume_perc=int(stats.tmean(self.current_observations) / 10),
            is_raining=self.is_observation_active)


class TendencyChecker:
    """
    Implements very basic appoach to detecting tendency.
    Stores N last observations divided into two parts: older (80%) and newer (20%)
    Tendency is rising if the average of "older" observations is significantly lower then "newer"
    """

    def __init__(self, observations_window: int, threshold_perc: float = 0.5):
        """
        Initializes the basic tendency checker
        :param observations_window: number of observations that shall be taken into consideration
        :param threshold_perc: defines whether the difference between previous and current observations is significant
        """
        self.previous_readings = deque(maxlen=int(observations_window / 5))
        self.current_readings = deque(maxlen=observations_window - int(observations_window / 5))
        self.threshold = threshold_perc
        self.current_tendency = Tendency.STEADY
        self.current_mean = 0.0
        self.previous_mean = 0.0
        self.current_diff_perc = 0.0

    def tendency(self, observation) -> Tendency:
        """
        Returns current tendency of observations
        :param observation:
        :return:
        """
        if len(self.current_readings) == self.current_readings.maxlen:
            # most recent at the right
            self.previous_readings.append(self.current_readings.popleft())

        self.current_readings.append(observation)

        self.current_mean = stats.tmean(self.current_readings)
        self.previous_mean = self.current_mean if len(self.previous_readings) == 0 \
            else stats.tmean(self.previous_readings)

        self.current_diff_perc = 100 * (self.current_mean - self.previous_mean) / observation

        self.current_tendency = Tendency.RISING if self.current_diff_perc - self.threshold > 0 \
            else Tendency.FALLING if self.current_diff_perc + self.threshold < 0 \
            else Tendency.STEADY

        return self.current_tendency

    def verbose(self) -> str:
        return f'{self.current_tendency} ' \
               f'[{len(self.previous_readings) + len(self.current_readings)}] ' \
               f'{self.previous_mean:.5} --> {self.current_mean:.5}'


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

            self.parent_service.log.debug('Multisensor is up and measuring')

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


if __name__ == '__main__':
    ServiceRunner(WeatherStationService).run()
    exit()
