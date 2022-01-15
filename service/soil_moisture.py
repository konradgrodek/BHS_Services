#!/usr/bin/python3

import re
from array import array
from scipy import stats

from service.common import *
from util.tendency import TendencyChecker
from persistence.schema import *
from device.dev_spi import *


class Channel:
    def __init__(self, number: int, name: str, tendency_observations_window: int,
                 raw_value_min: int, raw_value_max: int):
        self.number = number
        self.name = name
        self.sensor: Sensor = None
        self.last_stored_value: SoilMoistureReading = None
        self.last_value = None
        self.last_measurement_tm = None
        self.tendency = TendencyChecker(observations_window=tendency_observations_window)
        self.raw_value_min = raw_value_min
        self.raw_value_max = raw_value_max

    def get_reference(self) -> str:
        return f'{self.name}@{self.number}'

    def interpret(self, raw_result: int) -> float:
        """
        The ADC board returns value, that must be transformed into percentage value
        :param raw_result: int
        :return: float, percentage of the value using min and max value, never exceeding 100, always gt0
        """
        perc = 100.0 * (raw_result - self.raw_value_min) / (self.raw_value_max - self.raw_value_min)
        if perc > 100.0:
            perc = 100.0
        if perc < 0.0:
            perc = 0.0
        return perc

    def add_interpreted_reading(self, interpreted_val: float):
        self.last_value = float(interpreted_val)
        self.tendency.tendency(observation=self.last_value)
        self.last_measurement_tm = datetime.now()

    def __str__(self):
        return f'Channel {self.number}:{self.name} | ' \
               f'sensor: {"NA" if not self.sensor else str(self.sensor.db_id)} | ' \
               f'last value: {"NA" if not self.last_value else format(self.last_value,".2f")} ' \
               f'measured @ {"NA" if not self.last_measurement_tm else self.last_measurement_tm.strftime("%y-%m-%d %H:%M:%S")} |'\
               f'last stored: {"NA" if not self.last_stored_value else str(self.last_stored_value.moisture)} | ' \
               f'tendency: {self.tendency.verbose()}'


class SoilMoistureService(Service):

    def __init__(self):
        Service.__init__(self)
        self.channels = list()

        soil_moisture_section = 'SOIL-MOISTURE'
        channels_section = 'CHANNELS'

        # read the configuration
        self.polling_period = self.configuration.getIntConfigValue(
            section=soil_moisture_section,
            parameter='polling-period',
            default=5*60)

        self.significant_difference = self.configuration.getFloatConfigValue(
            section=soil_moisture_section,
            parameter='significant-moisture-difference',
            default=0.5)

        self.attempts = self.configuration.getIntConfigValue(
            section=soil_moisture_section,
            parameter='measure-attempts',
            default=30)

        # how many observations should be monitored for a tendency
        # let's assume it is last 5 hours
        tendency_observations_window = int((5 * 60 * 60) / self.polling_period)

        # REST config
        self.rest_app.add_url_rule('/', 'current_soil_moisture',
                                   self.get_rest_response_current_humidity_readings)

        # read channels
        channel_pattern = re.compile('channel\\.(\\d+)')
        channel_config_pattern = re.compile("(.*)\\|(\\d+)\\|(\\d+)")

        for ch_opt in self.configuration.config_parser.options(channels_section):
            ch_opt_matched = channel_pattern.match(ch_opt)
            if ch_opt_matched:
                ch_val_matched = channel_config_pattern.match(self.configuration.getConfigValue(channels_section, ch_opt))
                if ch_val_matched:
                    self.channels.append(Channel(number=int(ch_opt_matched.group(1)),
                                                 name=ch_val_matched.group(1),
                                                 tendency_observations_window=tendency_observations_window,
                                                 raw_value_min=int(ch_val_matched.group(2)),
                                                 raw_value_max=int(ch_val_matched.group(3))))

        if len(self.channels) < 1:
            self.log.critical('The configuration does not specify a single channel to monitor. '
                              'The service will now go down')
            ExitEvent().set()
        else:
            self.device = ADCBoard(exit_event=ExitEvent())

    def initialize(self):
        if len(self.channels) > 0:

            self.device.init()

            # initialize sensors
            sensors = self.persistence.get_sensors(sensor_type_name=SENSORTYPE_SOIL_MOISTURE)
            for sensr in sensors:
                channel_for_sensor = None
                for channel in self.channels:
                    if channel.get_reference() == sensr.reference:
                        channel_for_sensor = channel
                        channel_for_sensor.sensor = sensr

                if channel_for_sensor:
                    if sensr.host != self.get_hostname():
                        self.persistence.update_host(_sensor=sensr, _host=self.get_hostname())
                        self.log.info(f'Sensor {sensr.db_id} updated with hostname: '
                                      f'{sensr.host} --> {self.get_hostname()}')
                        sensr.host = self.get_hostname()
                    if not sensr.is_active:
                        self.persistence.enable_sensor(_sensor=sensr)
                        self.log.info(f'Sensor {sensr.db_id} is now ENABLED')
                else:
                    # channel not found
                    if sensr.host == self.get_hostname() and sensr.is_active:
                        self.persistence.disable_sensor(_sensor=sensr)
                        self.log.info(f'Sensor {sensr.db_id} is now DISABLED')

            for channel in self.channels:
                if not channel.sensor:
                    # missing sensor, add it
                    channel.sensor = self.persistence.register_sensor(
                        sensor_type_name=SENSORTYPE_SOIL_MOISTURE,
                        host=self.get_hostname(),
                        reference=channel.get_reference(),
                        location=channel.name)
                    self.log.info(f'Registered new sensor: {str(channel.sensor)}')

                if not channel.last_stored_value:
                    # fetch last stored value
                    channel.last_stored_value = self.persistence.get_last_soil_moisture_reading(channel.sensor)
                    if channel.last_stored_value:
                        self.log.info(f'Last reading restored: {str(channel.last_stored_value)}')

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time in seconds
        """
        mark = datetime.now()

        try:
            for channel in self.channels:
                self.read_and_store_humidity(channel)

        except InterruptedError:
            self.log.info(f'Exit event detected while querying ADC board for the state')

        return self.polling_period - (datetime.now() - mark).total_seconds()

    def provideName(self) -> str:
        return 'soil_moisture'

    def read_and_store_humidity(self, channel: Channel):
        tm = datetime.now()
        measurements = array('f')
        timeouts = 0
        while not ExitEvent().is_set() and len(measurements) < self.attempts and timeouts < self.attempts:
            try:
                measurements.append(channel.interpret(self.device.read_adc(channel.number)))

            except TimeoutError:
                timeouts += 1

        if len(measurements) > 0:
            humidity_avg = stats.tmean(measurements)
            humidity_var = stats.variation(measurements)
            humidity_kur = stats.kurtosis(measurements)

            channel.add_interpreted_reading(humidity_avg)

            self.log.info(f'Hum. ch {channel.number}:{channel.name} {humidity_avg:.2f}%, '
                          f'var: {humidity_var:.4f}, kurtosis: {humidity_kur:.4f}. '
                          f'tend: {channel.tendency.verbose()}, timeouts: {timeouts}, '
                          f'duration: {int((datetime.now()-tm).total_seconds()*1000):04} [ms]')

            # store the result
            if not channel.last_stored_value \
                    or abs(channel.last_stored_value.moisture - humidity_avg) > self.significant_difference:
                channel.last_stored_value = self.persistence.store_soil_moisture_reading(
                    _sensor=channel.sensor,
                    moisture=humidity_avg,
                    timestamp=datetime.now())
                self.log.info(f'Stored new reading: {str(channel.last_stored_value)}')
            # open question: does the variance\kurtosis provide anything meaningful for later analysis?
        else:
            self.log.critical(f'Querying for state of channel {str(channel)} resulted in timeout error. '
                              f'If persists, check hardware and wireing')

    def get_rest_response_current_humidity_readings(self):
        """
        REST response
        :return: jsonified array of results
        """
        return self.jsonify([
            ValueTendencyJson(value=channel.last_value,
                              tendency=channel.tendency.current_tendency,
                              timestamp=channel.last_measurement_tm,
                              current_mean=channel.tendency.current_mean,
                              previous_mean=channel.tendency.previous_mean)
            for channel in self.channels
        ])


if __name__ == '__main__':
    ServiceRunner(SoilMoistureService).run()
    exit()
