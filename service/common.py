#
# This file contains common functionality for Black House Sentry project
#
from configparser import ConfigParser, ExtendedInterpolation
import logging
from threading import Event
import signal
import subprocess
import sys
import os.path
from gpiozero import Button
from datetime import datetime, timezone, time
from flask import Flask, jsonify

from werkzeug.serving import make_server
from threading import Thread
import math

from core.bean import *
from persistence.schema import Persistence


class Configuration:
    """Class being main point accessing the configuration"""
    ROOT = '/etc/bhs'
    EXT = '.ini'
    ENV = 'env.ini'

    SECTION_DB = 'DATABASE'
    SECTION_LOG = 'LOG'
    SECTION_REST = 'REST'

    PARAM_DB = 'db'
    PARAM_USER = 'user'
    PARAM_PASSWORD = 'password'
    PARAM_HOST = 'host'

    PARAM_LOGFILE = 'logfile'
    PARAM_LOGLEV = 'level'
    PARAM_LOGTOSTDOUT = 'log-to-stdout'

    PARAM_REST_PORT = 'port'

    def __init__(self, name: str):
        """Initializes the configuration. Parameter `name` is mandatory as it is used to find the configuration file"""
        self.service_config_path = os.path.join(self.ROOT, name, name + self.EXT)
        self.environment_config_path = os.path.join(self.ROOT, name, self.ENV)
        self.config_parser = None

    def _getConfig(self):
        if self.config_parser is None:
            self.config_parser = ConfigParser(interpolation=ExtendedInterpolation())
            self.config_parser.read([self.environment_config_path, self.service_config_path])

        return self.config_parser

    def getConfigValue(self, section: str, parameter: str, default=None):
        if not self._getConfig().has_section(section):
            return default

        val = self._getConfig()[section].get(parameter)
        if not val:
            return default
        return val

    def getIntConfigValue(self, section: str, parameter: str, default: int = None):
        return int(self.getConfigValue(section, parameter, default))

    def getFloatConfigValue(self, section: str, parameter: str, default: float = None):
        return float(self.getConfigValue(section, parameter, default))

    def getTimeConfigValue(self, section: str, parameter: str, default: str = None):
        val = self.getConfigValue(section, parameter)
        if not val:
            val = default
            if not val:
                return None

        splt = val.split(':')

        return time(hour=int(splt[0]),
                    minute=int(splt[1]) if len(splt) > 1 else 0,
                    second=int(splt[2]) if len(splt) > 2 else 0)

    def getLogFile(self) -> str:
        return self.getConfigValue(self.SECTION_LOG, self.PARAM_LOGFILE)

    def getLogLevel(self) -> int:
        level = self.getConfigValue(self.SECTION_LOG, self.PARAM_LOGLEV)
        if level is None:
            return logging.DEBUG
        return logging.getLevelName(level)

    def getLogToStdout(self) -> bool:
        return self.getConfigValue(self.SECTION_LOG, self.PARAM_LOGTOSTDOUT)

    def getDbUser(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_USER)

    def getDb(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_DB)

    def getDbPassword(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_PASSWORD)

    def getDbHost(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_HOST)

    def getRestPort(self) -> int:
        return self.getIntConfigValue(self.SECTION_REST, self.PARAM_REST_PORT, -1)


class LocalConfiguration(Configuration):
    """To be used only for debugging purposes"""
    def __init__(self, localConfigFile: str):
        Configuration.__init__(self, '')
        self.service_config_path = localConfigFile
        self.environment_config_path = '../deployment/install/.credentials'


class RestServer(Thread):
    """
    Utility class for running REST service in a separate thread
    """
    def __init__(self, port: int, app: Flask):
        super().__init__()
        self.server = make_server('0.0.0.0', port, app)
        self.context = app.app_context()
        self.context.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


class Service:
    """
    Base class for all Black House Sentry services
    """

    def __init__(self):
        """Initializes the object responsible for running BHS service"""
        self._exit_event = Event()

        if sys.gettrace() is None:
            self.configuration = Configuration(self.provideName())
        else:
            self.configuration = LocalConfiguration(f'../test/test.{self.provideName()}.ini')

        logging.basicConfig(
            filename=self.configuration.getLogFile(),
            level=self.configuration.getLogLevel(),
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.log = logging.getLogger(self.provideName().upper())
        if self.configuration.getLogToStdout():
            self.log.addHandler(logging.StreamHandler(sys.stdout))
        self.persistence = Persistence(
            self.configuration.getDb(),
            self.configuration.getDbUser(),
            self.configuration.getDbPassword(),
            self.configuration.getDbHost())
        self._hostname = None
        port = self.configuration.getRestPort()
        if port > 0:
            self.rest_app = Flask('BHSCore')
            self.rest_server = RestServer(port, self.rest_app)
        else:
            self.rest_server = None

    def run(self):
        self.log.info(f'Starting service {self.provideName()}')

        signal.signal(getattr(signal, 'SIGTERM'), self._onsigterm)

        self.persistence.connect()
        self.log.info(f'Connected to database {self.persistence.db} as {self.persistence.user}')

        if self.rest_server:
            self.rest_server.start()
            self.log.info(f'REST Service started @ {self.configuration.getRestPort()}')

        while not self._exit_event.is_set():
            wait_time = self.main()
            if wait_time and wait_time > 0:
                try:
                    self._exit_event.wait(wait_time)
                except KeyboardInterrupt:  # this is just for proper handling of stop in debug mode
                    self._exit_event.set()

        self._cleanup()
        self.log.info('All done. Bye')

    def _onsigterm(self, signum, stackframe):
        self.log.critical('Received SIGTERM, terminating. Signum: %i, stractframe: %s', signum, str(stackframe))
        self._exit_event.set()

    def _cleanup(self):
        self.persistence.close()
        if self.rest_server:
            self.rest_server.shutdown()
        self.cleanup()

    # interface

    def main(self) -> float:
        """This method must be overwritten in order to implement the main loop of the service
        Return number of seconds that the main loop should wait for next execution of this method"""
        raise NotImplementedError()

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        pass

    def provideName(self) -> str:
        """This method must be overwritten in order to provide name of the service"""
        raise NotImplementedError()

    # useful methods

    def get_hostname(self):
        if self._hostname is None:
            exec_res = subprocess.run(['hostname'], capture_output=True)

            if exec_res.returncode == 0:
                self._hostname = exec_res.stdout.decode('utf-8').strip()
                self.log.debug(f'Found hostname: {self._hostname}')
            else:
                self.log.critical(f"Execution of [hostname] failed. "
                                  f"Return code: {exec_res}, "
                                  f"stout: {exec_res.stdout.decode('utf-8')}, "
                                  f"stderr: {exec_res.stderr.decode('utf-8')}")
                self._hostname = 'UNKNOWN'

        return self._hostname

    def exit_event(self) -> Event:
        """
        Ensures access to event signalising the process should be ended
        :return: Event, which can be monitored to detect service shut down
        """
        return self._exit_event

    def jsonify(self, to_jsonify):
        """
        Utility method converting json-ready-bean into correct Flask response.
        :param to_jsonify: the entity to be tranferred into Flask response.
        Acceptable types: (1) list of AbstractJsonBean (2) AbstractJsonBean (3) dict
        None will also be accepted and transffered into 'not-available' response
        :return: jsonified object(s)
        """
        if type(to_jsonify) != dict:
            if type(to_jsonify) == list:
                to_jsonify = [bean.to_dict() for bean in to_jsonify]
            else:
                if not to_jsonify:
                    to_jsonify = NotAvailableJsonBean()
                to_jsonify = to_jsonify.to_dict()

        return jsonify(to_jsonify)


class ServiceRunner:
    def __init__(self, service_class):
        self.service_class = service_class
        self.service: Service = None

    def run(self):
        try:
            self.service = self.service_class()
        except:
            logging.getLogger().critical(
                f'Uncaught exception detected when creating instance of service {str(self.service_class)}. '
                f'Check configuration', sys.exc_info())
            print(str(sys.exc_info()))
            sys.stderr.write(str(sys.exc_info()))
            exit()

        try:
            self.service.run()
        except:
            self.service.log.critical(
                f'Uncaught exception detected when running service', sys.exc_info())
            print(str(sys.exc_info()))
            sys.stderr.write(str(sys.exc_info()))
            exit()


class StatelessButton(Button):
    """
    Simple class handling button with no state - the one that is on when you press it,
    but released immediately switches off
    The value added of the class is to report the duration of the press-release activity
    """
    def __init__(self, pin, button_pressed_handler):
        Button.__init__(self, pin, pull_up=None, active_state=False)
        self.when_activated = self.pressed
        self.when_deactivated = self.released
        self.pressed_at = None
        self.button_pressed_handler = button_pressed_handler

    def __str__(self):
        return f"Stateless button configured @ {self.pin}"

    def pressed(self, arg):
        """
        Reaction on button pressed
        :param arg:
        :return:
        """
        self.pressed_at = datetime.now()

    def released(self, arg):
        """
        Reaction on button being released
        :param arg:
        :return:
        """
        duration = (datetime.now() - self.pressed_at).total_seconds()
        self.button_pressed_handler(duration)
        self.pressed_at = None


class SunsetCalculator:
    """
    Utility class for calculating sunset and sunrise times

    Source of calculations: https://www.esrl.noaa.gov/gmd/grad/solcalc/solareqns.PDF
    """
    def __init__(self, dt: datetime = None):
        """
        Constructor. Already pre-calculates most of the useful information
        :param dt: the date for which the calculations must be performed
        """
        self.calculate_for_date = dt if dt else datetime.now()
        self.day_of_year = (self.calculate_for_date - datetime(self.calculate_for_date.year, 1, 1)).days
        # used by equation of time; actually no idea what to put in here; mid-day seems to be reasonable compromise
        hour = 12
        # constant unless the house will be moved or the BHS system will become worldwide standard
        self.lattitude_deg = 49.993906
        self.longitude_deg = 19.96859

        # originally: gamma
        fractional_year = 2*math.pi*(self.day_of_year-1+(hour-12)/24)/365

        declination_angle = 0.006918-0.399912*math.cos(fractional_year)\
                            + 0.070257*math.sin(fractional_year) \
                            - 0.006758*math.cos(2*fractional_year) \
                            + 0.000907*math.sin(2*fractional_year) \
                            - 0.002697*math.cos(3*fractional_year) \
                            + 0.00148*math.sin(3*fractional_year)

        equation_of_time = 229.18 * (0.000075 + 0.001868 * math.cos(fractional_year)
                                     - 0.032077 * math.sin(fractional_year)
                                     - 0.014615 * math.cos(2 * fractional_year)
                                     - 0.040849 * math.sin(2 * fractional_year))

        hour_angle_deg = math.degrees(
            math.acos(
                (math.cos(math.radians(90.833))/(math.cos(math.radians(self.lattitude_deg)) * math.cos(declination_angle)))
                - math.tan(math.radians(self.lattitude_deg))*math.tan(declination_angle)))

        self.sunset_min = 720 - 4 * (self.longitude_deg - hour_angle_deg) - equation_of_time
        self.sunrise_min = 720 - 4 * (self.longitude_deg + hour_angle_deg) - equation_of_time

    def _as_utc(self, mins: float) -> datetime:
        return self.calculate_for_date\
            .astimezone(tz=timezone.utc)\
            .replace(year=self.calculate_for_date.year,
                     month=self.calculate_for_date.month,
                     day=self.calculate_for_date.day,
                     hour=int(mins/60),
                     minute=int(mins % 60),
                     second=int((mins-int(mins))*60),
                     microsecond=0)

    def _sunrise_utc(self) -> datetime:
        return self._as_utc(mins=self.sunrise_min)

    def _sunset_utc(self) -> datetime:
        return self._as_utc(mins=self.sunset_min)

    def _convert_to_cest(self, utc: datetime):
        return utc.astimezone().replace(tzinfo=None)

    def sunset(self) -> datetime:
        return self._convert_to_cest(self._sunset_utc())

    def sunrise(self) -> datetime:
        return self._convert_to_cest(self._sunrise_utc())

#
# if __name__ == '__main__':
#     dt = datetime(year=2020, month=1, day=1)
#
#     for i in range(12):
#         dt = dt + timedelta(days=30)
#         srs = SunsetCalculator(dt)
#         print(f'On {dt} sunrise is at {srs.sunrise()}, sunset: {srs.sunset()}')

