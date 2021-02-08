#!/usr/bin/python3

import subprocess
import json
from datetime import datetime

from service.common import *
from persistence.schema import *


class SpeedtestService(Service):

    def __init__(self):
        Service.__init__(self)

        self.the_speedtest_sensor: Sensor = None
        self.the_last_reading: SpeedtestReading = None
        self.the_last_ping_result = True

        speedtest_section = 'SPEEDTEST'
        self.address_to_ping = self.configuration.getConfigValue(
            section=speedtest_section,
            parameter='address-to-ping')
        self.ping_polling_period = float(self.configuration.getConfigValue(
            section=speedtest_section,
            parameter='ping-polling-period'))
        self.ping_timeout = self.configuration.getIntConfigValue(
            section=speedtest_section,
            parameter='ping-timeout')
        self.speedtest_timeout = self.configuration.getIntConfigValue(
            section=speedtest_section,
            parameter='speedtest-timeout')

    def _get_sensor(self) -> Sensor:
        if not self.the_speedtest_sensor:
            self.the_speedtest_sensor = self.persistence.get_sensor(SENSORTYPE_SPEEDTEST,SPEEDTEST_THE_SENSOR_REFERENCE)
            if not self.the_speedtest_sensor:
                self.the_speedtest_sensor = self.persistence.register_sensor(
                    SENSORTYPE_SPEEDTEST,
                    self.get_hostname(),
                    reference=SPEEDTEST_THE_SENSOR_REFERENCE,
                    polling_period=60*60)
                self.log.info(f"Sensor {SENSORTYPE_SPEEDTEST} "
                              f"has been automatically created: {str(self.the_speedtest_sensor)}")
            else:
                self.log.info(f"Sensor {SENSORTYPE_SPEEDTEST} "
                              f"was restored from the database: {str(self.the_speedtest_sensor)}")

        return self.the_speedtest_sensor

    def _get_last_reading(self) -> SpeedtestReading:
        if not self.the_last_reading:
            self.the_last_reading = self.persistence.get_last_speedtest_reading(self._get_sensor())
            if self.the_last_reading:
                self.log.info(f'Last speedtest execution restored from the database: {str(self.the_last_reading)}')
            else:
                self.log.info("Can't locate last execution of speedtest")

        return self.the_last_reading

    def main(self) -> float:
        """
        One iteration of main loop of the service.
        Suppose to return sleep time im seconds
        """
        last_execution_time = datetime.min

        if self._get_last_reading():
            last_execution_time = self.the_last_reading.timestamp

        current_time = datetime.today()

        # execute ping
        try:
            exec_res = subprocess.run(['ping', '-c 1', self.address_to_ping],
                                      capture_output=True,
                                      timeout=self.ping_timeout)
        except subprocess.TimeoutExpired:
            self.log.error(f'Timeout occurred when executing ping ({self.ping_timeout} s)')
            current_ping_result = False

        if exec_res:
            if exec_res.returncode == 0:
                current_ping_result = True
                self.log.debug(f'Ping succeeded. Stdout: [{exec_res.stdout.decode("utf-8").rstrip()}]')
            elif exec_res.returncode == -15:
                self.log.debug(f'Detected SIGNUM (error code -15). Exiting')
                return None
            else:
                current_ping_result = False
                err_msg = f'Ping failed, error code: {exec_res.returncode}. ' \
                          f'Stderr: [{exec_res.stderr.decode("utf-8")}]'
                if self.the_last_ping_result:
                    self.log.error(err_msg)
                else:
                    self.log.debug(err_msg)

            time_lapsed = current_time - last_execution_time
            self.log.debug(f'Time lapsed: {time_lapsed.seconds} s, '
                           f'polling period is {self._get_sensor().polling_period}')

            if time_lapsed.seconds >= self._get_sensor().polling_period \
                    or current_ping_result != self.the_last_ping_result \
                    or current_ping_result != self.the_last_reading.is_available:
                # execute speedtest
                self.log.debug(f'Executing speedtest with timeout = {self.speedtest_timeout}')
                try:
                    exec_res = subprocess.run(['speedtest', '--accept-gdpr', '--format=json'],
                                              capture_output=True,
                                              timeout=self.speedtest_timeout)
                except subprocess.TimeoutExpired:
                    self.log.error(f'Timeout occurred when executing speedtest ({self.speedtest_timeout} s)')

                # check the return code, react
                if exec_res and exec_res.returncode == 0:
                    # parse the result
                    res = json.loads(exec_res.stdout, encoding='utf-8')
                    # success
                    self.log.debug(f'Speedtest execution succeeded, stdout: {exec_res.stdout.decode("utf-8").rstrip()}')

                    jitterMicroSecs = int(1000 * float(res['ping']['jitter']))
                    pingMicroSecs = int(1000 * float(res['ping']['latency']))
                    downloadKbps = int(int(res['download']['bandwidth']) * 8 / 1000)
                    uploadKbps = int(int(res['upload']['bandwidth']) * 8 / 1000)
                    externalIP = res['interface']['externalIp']

                    self.the_last_reading = self.persistence.add_speedtest_successful_reading(
                        self._get_sensor(),
                        pingMicroSecs,
                        jitterMicroSecs,
                        downloadKbps,
                        uploadKbps,
                        externalIP,
                        current_time)

                    self.log.info(f"Succeeded, result stored in db: {str(self.the_last_reading)}")

                elif exec_res and exec_res.returncode == -15:
                    self.log.debug(f'Detected SIGNUM (error code -15). Exiting')
                    return None

                elif self.the_last_reading.is_available:
                    if exec_res:
                        self.log.error(f'Speedtest failed. Return code: {exec_res.returncode}, '
                                       f'Stderr: [{exec_res.stderr.decode("utf-8").rstrip()}], '
                                       f'Stdout: [{exec_res.stdout.decode("utf-8").rstrip()}], '
                                       f'Args: [{exec_res.args}]')

                    self.the_last_reading = self.persistence.add_speedtest_unsuccessful_reading(
                        self._get_sensor(),
                        current_time)

                    self.log.info(f"Result (failure) stored in db: {str(self.the_last_reading)}")

        self.the_last_ping_result = current_ping_result

        self.log.debug(f'Sleeping for {self.ping_polling_period} [s]')
        return self.ping_polling_period

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.debug('Nothing to clean')
        pass

    def provideName(self):
        return 'BHS.Speedtest'


if __name__ == '__main__':
    ServiceRunner(SpeedtestService).run()
    exit()

