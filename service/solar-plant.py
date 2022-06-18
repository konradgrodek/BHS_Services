#!/usr/bin/python3

import requests
from requests.auth import HTTPBasicAuth
from datetime import timedelta
import statistics

from service.common import *
from persistence.schema import *
from core.util import SunsetCalculator, TimeWindowList, PingIt


class SimpleProductionReading:
    def __init__(self, _daily_kwh: float = None, _current_w: int = 0, _timestamp: datetime = None):
        self.daily_kWh = _daily_kwh
        self.current_W = _current_w
        self.timestamp = _timestamp if _timestamp is not None else datetime.now()

    def __str__(self):
        return f'Production @ {self.timestamp:%Y-%m-%d %H:%M:%S}: {self.daily_kWh} [kWh], {self.current_W} [W]'

    def producing(self):
        return self.daily_kWh is not None and self.current_W > 0 if self.timestamp is not None else None

    def to_json(self):
        return json.dumps([self.daily_kWh, self.current_W, self.timestamp.isoformat()])

    @staticmethod
    def from_json(jsn: str):
        _parsed = json.loads(jsn)
        return SimpleProductionReading(_daily_kwh=_parsed[0],
                                       _current_w=_parsed[1],
                                       _timestamp=datetime.fromisoformat(_parsed[2]))


class SolarPlantMonitor(Service):
    HTML_PART_CURRENT_POWER = "var webdata_now_p"
    HTML_PART_DAILY_PRODUCTION = "var webdata_today_e"

    def __init__(self):
        Service.__init__(self)

        solar_plant_section = 'SOLAR-PLANT'
        self.polling_period_s = self.configuration.getIntConfigValue(
            section=solar_plant_section, parameter='polling-period-s', default=60)
        self.solar_plant_hostname = self.configuration.getConfigValue(
            section=solar_plant_section, parameter='web-host')
        self.solar_plant_status_page = self.configuration.getConfigValue(
            section=solar_plant_section, parameter='web-status-page', default='/status.html')
        self.solar_plant_web_user = self.configuration.getConfigValue(
            section=solar_plant_section, parameter='web-user')
        self.solar_plant_web_password = self.configuration.getConfigValue(
            section=solar_plant_section, parameter='web-password')
        ping_timeout_ms = self.configuration.getIntConfigValue(
            section=solar_plant_section, parameter='web-ping-timeout-ms', default=100)
        self.get_timeout_s = self.configuration.getIntConfigValue(
            section=solar_plant_section, parameter='web-timeout-s', default=10)
        self.last_hour_readings_storage_file_path = self.configuration.getConfigValue(
            section=solar_plant_section, parameter='readings-storage-file-path', default='/tmp/.bhs.solar.plant.tmp')

        if self.solar_plant_hostname is None or self.solar_plant_hostname == '':
            raise ValueError(f'The configuration does not provide inverters web interface host')
        if self.solar_plant_web_user is None or self.solar_plant_web_user == '':
            raise ValueError(f'The configuration does not provide inverters web interface user')
        if self.solar_plant_web_password is None or self.solar_plant_web_password == '':
            raise ValueError(f'The configuration does not provide inverters web interface password')

        self.machine_that_goes_ping = PingIt(target=self.solar_plant_hostname, exec_timeout_ms=ping_timeout_ms)
        self.sensor_daily = None
        self.sensor_hourly = None
        self.last_daily_stored_reading = None
        self.last_hourly_stored_reading = None
        self.recorded_readings = TimeWindowList(validity_time_s=60*60, get_time_mark_function=lambda x: x.timestamp)

        self.rest_app.add_url_rule('/', 'current_production', self.get_rest_response_current_reading)

    def initialize(self):
        self.last_daily_stored_reading = self.persistence.get_last_solar_plant_production(self._get_daily_sensor())
        self.last_hourly_stored_reading = self.persistence.get_last_solar_plant_production(self._get_hourly_sensor())
        self.recorded_readings.from_file(
            file_path=self.last_hour_readings_storage_file_path,
            from_json=SimpleProductionReading.from_json)

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time in seconds
        """
        _today_sunrise, _today_sunset, _tomorrow_sunrise = SolarPlantMonitor._get_sun_timing()
        _mark = datetime.now()

        _current_reading = self._read_production()
        self.log.debug(str(_current_reading))
        self.recorded_readings.append(_current_reading)

        if _today_sunrise < _mark < _today_sunset or (_mark > _today_sunset and _current_reading.producing()):
            # during the day or in the evening, till production is reported (current watts is more than 0)
            self._store_readings(_current_reading)
        elif _mark > _today_sunset:
            # end of the day
            self._store_readings()

        sleep_time_s = self.polling_period_s - (datetime.now() - _mark).total_seconds()
        if not _current_reading.producing():
            if _mark < _today_sunrise:
                sleep_time_s = (_today_sunrise - _mark).total_seconds()
            elif _mark > _today_sunset:
                sleep_time_s = (_tomorrow_sunrise - _mark).total_seconds()

        return sleep_time_s

    def provideName(self) -> str:
        return 'solar-plant'

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    @staticmethod
    def _get_sun_timing() -> tuple:
        """
        Returns sunrise and sunset for current day and sunrise for the next one
        :return: tuple sunrise (today), sunset(today), sunrise(tomorrow)
        """
        _today = SunsetCalculator()
        _tomorrow = SunsetCalculator(datetime.now() + timedelta(days=1))
        return _today.sunrise(), _today.sunset(), _tomorrow.sunrise()

    def _get_sensor(self, reference: str):
        _sensor = self.persistence.get_sensor(sensor_type_name=SENSORTYPE_SOLAR_PLANT, reference=reference)
        if _sensor is None:
            _sensor = self.persistence.register_sensor(sensor_type_name=SENSORTYPE_SOLAR_PLANT,
                                                       host=self.get_hostname(),
                                                       reference=reference,
                                                       location=self.solar_plant_hostname)
            self.log.info(f"Sensor {reference}"
                          f"has been automatically created: {str(_sensor)}")

        if _sensor.host != self.get_hostname():
            self.log.info(f"Sensor id: {_sensor.db_id}, refno: {_sensor.reference} "
                          f"is updated with host name ({_sensor.host} --> {self.get_hostname()})")
            _sensor = self.persistence.update_host(_sensor, self.get_hostname())

        return _sensor

    def _get_daily_sensor(self) -> Sensor:
        if self.sensor_daily is None:
            self.sensor_daily = self._get_sensor(SOLARPLANT_THE_DAILY_REFERENCE)
        return self.sensor_daily

    def _get_hourly_sensor(self) -> Sensor:
        if self.sensor_hourly is None:
            self.sensor_hourly = self._get_sensor(SOLARPLANT_THE_HOURLY_REFERENCE)
        return self.sensor_hourly

    def _init_last_stored(self):
        if self.last_daily_stored_reading is None:
            self.last_daily_stored_reading = self.persistence.get_last_solar_plant_production(
                _sensor=self._get_daily_sensor())

        if self.last_hourly_stored_reading is None:
            self.last_hourly_stored_reading = self.persistence.get_last_solar_plant_production(
                _sensor=self._get_hourly_sensor())

    def _ping(self) -> bool:
        ping_result = self.machine_that_goes_ping.ping()

        if ping_result.error():
            self.log.error(ping_result.message())
        else:
            self.log.debug(ping_result.message())

        return ping_result.alive()

    def _read_production(self) -> SimpleProductionReading:
        _production = SimpleProductionReading()

        if self._ping():
            try:
                get_response = requests.get(url=f'http://{self.solar_plant_hostname}{self.solar_plant_status_page}',
                                            auth=HTTPBasicAuth(self.solar_plant_web_user,
                                                               self.solar_plant_web_password),
                                            timeout=self.get_timeout_s)

                if get_response.status_code != 200:
                    self.log.error(
                        f'Inverter responds to ping, but the web interface @ {get_response.url} is not available. '
                        f'Response code: {get_response.status_code} {get_response.reason}')
                else:
                    html = get_response.text
                    # the data is stored in JavaScript variables
                    # var webdata_now_p = "?"
                    # var webdata_today_e = "?";
                    # maybe it would be nicer to have it as regex pattern, but undoubtedly also more expensive

                    curr_pow_begins_at = html.find(self.HTML_PART_CURRENT_POWER)
                    if curr_pow_begins_at < 0:
                        self.log.error(f'Inverter returned with valid HTML document, '
                                       f'but keyword {self.HTML_PART_CURRENT_POWER} cannot be located within it')
                    else:
                        curr_pow_start = curr_pow_begins_at + len(self.HTML_PART_CURRENT_POWER) + 4
                        curr_pow_ends = html.find('";', curr_pow_start)
                        try:
                            _production.current_W = int(html[curr_pow_start:curr_pow_ends])
                        except ValueError as e:
                            self.log.error(f'The current produced power cant be extracted '
                                           f'from "{html[curr_pow_start:curr_pow_ends]}" (not a number), {str(e)}')

                    daily_pow_begins_at = html.find(self.HTML_PART_DAILY_PRODUCTION)
                    if daily_pow_begins_at < 0:
                        self.log.error(f'Inverter returned with valid HTML document, '
                                       f'but keyword {self.HTML_PART_DAILY_PRODUCTION} cannot be located within it')
                    else:
                        daily_pow_start = daily_pow_begins_at + len(self.HTML_PART_DAILY_PRODUCTION) + 4
                        daily_pow_ends = html.find('";', daily_pow_start)
                        # inverter has a strange bug, if there is production X.Y, in reality it is X.0Y
                        # on the other hand, production X.YZ is perfectly fine
                        _var_value = html[daily_pow_start:daily_pow_ends]
                        _i_point = _var_value.find('.')
                        if _i_point > 0 and len(_var_value) - _i_point <= 2:
                            _var_value = _var_value[:_i_point+1]+'0'+_var_value[_i_point+1:]
                        try:
                            _production.daily_kWh = float(_var_value)
                        except ValueError as e:
                            self.log.error(f'The daily production cant be extracted '
                                           f'from "{html[daily_pow_start:daily_pow_ends]}" '
                                           f'(not a floating point number), {str(e)}')
            except requests.exceptions.RequestException as conn_err:
                self.log.error(f'Getting the inverter status failed due to connection error: {str(conn_err)}')

        else:
            self.log.info(f'The solar plant inverter is unavailable (ping failed)')

        return _production

    def _store_readings(self, _current_reading: SimpleProductionReading = None):
        if _current_reading is not None and _current_reading.daily_kWh is not None:
            if self.last_daily_stored_reading is None \
                    or self.last_daily_stored_reading.inserted_at.day != _current_reading.timestamp.day:
                self.last_daily_stored_reading = self.persistence.store_solar_plant_daily_production(
                    self._get_daily_sensor(),
                    _current_reading.daily_kWh,
                    _current_reading.timestamp)
                self.log.info(f'Daily production inserted: {str(self.last_daily_stored_reading)}')
            elif self.last_daily_stored_reading.production_kwh != _current_reading.daily_kWh:
                self.last_daily_stored_reading.production_kwh = _current_reading.daily_kWh
                self.last_daily_stored_reading.modified_at = _current_reading.timestamp
                self.persistence.update_solar_plant_production(self.last_daily_stored_reading)
                self.log.debug(f'Daily production updated: {str(self.last_daily_stored_reading)}')

        if _current_reading is not None and _current_reading.producing():
            self.recorded_readings.to_file(
                file_path=self.last_hour_readings_storage_file_path, to_json=lambda x: x.to_json())

        if _current_reading is None \
                or (
                        self.last_hourly_stored_reading is None
                        and self.last_daily_stored_reading is not None
                        and self.last_daily_stored_reading.inserted_at.hour < _current_reading.timestamp.hour
                        and self.last_daily_stored_reading.inserted_at.day == _current_reading.timestamp.day
                ) \
                or (
                        self.last_hourly_stored_reading is not None
                        and self.last_hourly_stored_reading.inserted_at.hour < _current_reading.timestamp.hour
                        and self.last_hourly_stored_reading.inserted_at.day == _current_reading.timestamp.day
                ) \
                or (
                        self.last_hourly_stored_reading is not None
                        and self.last_hourly_stored_reading.inserted_at.day != _current_reading.timestamp.day
                        and self.last_daily_stored_reading.inserted_at.hour < _current_reading.timestamp.hour
                        and self.last_daily_stored_reading.inserted_at.day == _current_reading.timestamp.day
                ):
            if _current_reading is None:
                _current_reading = self.recorded_readings.newest()

            if _current_reading is not None:
                _oldest_reading = self.oldest_successful_recorded_reading()
                _current_daily_kWh = _current_reading.daily_kWh \
                    if _current_reading.daily_kWh is not None \
                    else self.newest_successful_recorded_reading().daily_kWh \
                    if self.newest_successful_recorded_reading() is not None \
                    else None
                _previous_daily_kWh = _oldest_reading.daily_kWh \
                    if _oldest_reading is not None and _current_reading.timestamp > _oldest_reading.timestamp else 0

                _hourly_delta = _current_daily_kWh - _previous_daily_kWh \
                    if _current_daily_kWh is not None and _previous_daily_kWh is not None else 0
                if _hourly_delta < 0:
                    _hourly_delta = 0

                _min_w, _avg_w, _max_w = self._last_hour_statistics()

                self.last_hourly_stored_reading = self.persistence.store_solar_plant_hourly_production(
                    _sensor=self._get_hourly_sensor(),
                    hourly_production_kwh=_hourly_delta,
                    min_w=_min_w,
                    avg_w=_avg_w,
                    max_w=_max_w,
                    timestamp=_current_reading.timestamp)

                self.log.info(f'Hourly production inserted: {str(self.last_hourly_stored_reading)}')

    def newest_successful_recorded_reading(self) -> SimpleProductionReading:
        _reading = None
        for _r in self.recorded_readings.as_list():
            if _r.daily_kWh is not None:
                _reading = _r
                break
        return _reading

    def oldest_successful_recorded_reading(self) -> SimpleProductionReading:
        _reading = None
        for _r in reversed(self.recorded_readings.as_list()):
            if _r.daily_kWh is not None:
                _reading = _r
                break
        return _reading

    def _last_hour_statistics(self) -> tuple:
        """
        Calculates min-avg-max production (in Watts) from last hour
        :return: tuple min-avg-max
        """
        _current_w_history = [_rr.current_W for _rr in self.recorded_readings.as_list()]
        if len(_current_w_history) == 0:
            return 0, 0, 0
        return min(_current_w_history), int(statistics.mean(_current_w_history)), max(_current_w_history)

    def get_rest_response_current_reading(self):
        _newest_reading = self.recorded_readings.newest()
        daily_production = self.last_daily_stored_reading.production_kwh if self.last_daily_stored_reading is not None \
            else _newest_reading.daily_kWh if _newest_reading is not None \
            else 0
        current_production = _newest_reading.current_W if _newest_reading is not None \
            else self.last_hourly_stored_reading.hourly_avg_w if self.last_hourly_stored_reading is not None \
            else 0

        _min_w, _avg_w, _max_w = self._last_hour_statistics()

        return self.jsonify(SolarPlantReadingJson(
            d_production=daily_production,
            production=current_production,
            h_min=_min_w, h_avg=_avg_w, h_max=_max_w,
            last_production_at=self.last_daily_stored_reading.modified_at if self.last_daily_stored_reading is not None
            else None,
            timestamp=datetime.now()))


if __name__ == '__main__':
    ServiceRunner(SolarPlantMonitor).run()
    exit()
