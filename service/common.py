#
# This file contains common functionality for Black House Sentry project
#
from configparser import ConfigParser, ExtendedInterpolation
import logging
import signal
import subprocess
import sys
import os.path
from datetime import time
from flask import Flask, jsonify

from werkzeug.serving import make_server
from threading import Thread

from core.bean import *
from core.util import ExitEvent, HostInfoThread
from persistence.schema import *


class Configuration:
    """Class being main point accessing the configuration"""
    ROOT = '/etc/bhs'
    EXT = '.ini'
    ENV = 'env.ini'

    SECTION_DB = 'DATABASE'
    SECTION_LOG = 'LOG'
    SECTION_REST = 'REST'
    SECTION_HOST_STATUS = 'HOST-STATUS'

    PARAM_DB = 'db'
    PARAM_USER = 'user'
    PARAM_PASSWORD = 'password'
    PARAM_HOST = 'host'

    PARAM_LOGFILE = 'logfile'
    PARAM_LOGLEV = 'level'
    PARAM_LOGTOSTDOUT = 'log-to-stdout'

    PARAM_REST_PORT = 'port'

    PARAM_HOST_STATUS_POLLING = 'polling-period-s'

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

    def getBooleanConfigValue(self, section: str, parameter: str, default: bool = False) -> bool:
        """
        Returns boolean parameter from config file.
        If the entry is missing, the method returns False unless the default=True is provided.
        The values `true`, `1`, `yes`, `ok` are treated as True; all other values will be interpreted as False.
        None will only be returned if the entry is missing and default is explicitly set to None (don't do that)
        :param section: the config section
        :param parameter: the config parameter
        :param default: the default value to be taken if entry is missing; False if not provided
        :return: True or False or None
        """
        val = self.getConfigValue(section, parameter, default)
        if type(val) == str:
            return val.lower() in ("true", "1", "yes", "ok")
        return False if default is not None else None

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

    def getHostStatusPollingPeriod(self) -> int:
        return self.getIntConfigValue(self.SECTION_HOST_STATUS, self.PARAM_HOST_STATUS_POLLING, -1)


class LocalConfiguration(Configuration):
    """To be used only for debugging purposes"""
    def __init__(self, localConfigFile: str):
        Configuration.__init__(self, '')
        self.service_config_path = localConfigFile
        self.environment_config_path = '../../BHS_Deployment/install/.credentials'


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


class ActivityState(ServiceActivityJson):
    """
    A wraper for bean object keeping health-check response of an activity of a service.
    Provides utilitarian methods that allow the services / activities to keep a single instance
    and modify the state with easy calls.
    """

    def __init__(self, name: str):
        """
        Initializes the object with state = STARTING and the provided name of the activity
        :param name: the name of the activity
        """
        ServiceActivityJson.__init__(self, name, ServiceActivityState.STARTING)

    def update(self, state: ServiceActivityState, msg: str = None):
        """
        Updates the state of activity. Sets provided state and message, the timestamp is set to _now_
        :param state: the new state
        :param msg: the optional message
        :return: None
        """
        self.timestamp = datetime.now()
        self.message = msg
        self.state = state

    def mark_dead(self, msg: str = None):
        """
        Sets DEAD as the current state.
        :param msg: optional message
        :return: NOne
        """
        self.update(ServiceActivityState.DEAD, msg)

    def all_fine(self, msg: str = None):
        """
        Sets OK as the current state.
        :param msg: optional detailed message
        :return: None
        """
        self.update(ServiceActivityState.OK, msg)

    def warn(self, msg: str = None):
        """
        Sets WARNING as the current state
        :param msg: the optional detailed message
        :return: None
        """
        self.update(ServiceActivityState.WARNING, msg)


class Service:
    """
    Base class for all Black House Sentry services
    """

    def __init__(self):
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
            db=self.configuration.getDb(),
            user=self.configuration.getDbUser(),
            password=self.configuration.getDbPassword(),
            host=self.configuration.getDbHost(),
            exit_event=ExitEvent())
        self._hostname = None
        self.main_activity_state = ActivityState(name=f"{self.provideName()}-main")
        port = self.configuration.getRestPort()
        if port > 0:
            self.rest_app = Flask('service/common')
            self.rest_server = RestServer(port, self.rest_app)
            self.rest_app.add_url_rule('/hc', 'service_health_check',
                                       self.get_rest_response_health_check)
            host_status_pp = self.configuration.getHostStatusPollingPeriod()
            if host_status_pp > 0 and port > 0:
                self.host_status_thread = HostInfoThread(host_status_pp)
                self.host_status_thread.start()
                self.rest_app.add_url_rule('/hs', 'host_status',
                                           self.get_rest_response_host_status)
        else:
            self.rest_server = None
            self.host_status_thread = None

    def run(self):
        self.log.info(f'Starting service {self.provideName()}')

        signal.signal(getattr(signal, 'SIGTERM'), self._onsigterm)

        self.persistence.connect()
        self.log.info(f'Connected to database {self.persistence.db} as {self.persistence.user}')

        self.initialize()

        if self.rest_server:
            self.rest_server.start()
            self.log.info(f'REST Service started @ {self.configuration.getRestPort()}')
            logging.getLogger('werkzeug').setLevel(logging.ERROR)

        self.main_activity_state.all_fine("Started.")
        while not ExitEvent().is_set():
            try:
                wait_time = self.main()
            except Exception as e:
                self.log.error('Fatal error detected in main loop', exc_info=e)
                self.main_activity_state.mark_dead(str(e))
                break
            if wait_time and wait_time > 0:
                try:
                    ExitEvent().wait(wait_time)
                except KeyboardInterrupt:  # this is just for proper handling of stop in debug mode
                    ExitEvent().set()

        self.main_activity_state.mark_dead("Peacefully deceased")
        self._cleanup()
        self.log.info('All done. Bye')

    def _onsigterm(self, signum, stackframe):
        self.log.critical('Received SIGTERM, terminating. Signum: %i, stractframe: %s', signum, str(stackframe))
        ExitEvent().set()

    def _cleanup(self):
        self.persistence.close()
        if self.rest_server:
            self.rest_server.shutdown()
        if self.host_status_thread:
            self.host_status_thread.join()
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

    def initialize(self):
        """
        The method is called prior to starting processing, when connection to persistence layer is already established.
        REST is not started yet when the method is called.
        :return:
        """
        pass

    def service_activities_states(self) -> list:
        """
        Override this method to add states of service sub-activities.
        :return: list of ServiceActivityJson
        """
        return []

    # health check
    def get_rest_response_health_check(self):
        return self.jsonify(
            ServiceStateJson(
                name=self.provideName(),
                activities_state=[self.main_activity_state] + self.service_activities_states()
            )
        )

    # host status
    def get_rest_response_host_status(self):
        return self.jsonify(
            self.host_status_thread.host_status if self.host_status_thread is not None else NotAvailableJsonBean()
        )

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

    def jsonify(self, to_jsonify):
        """
        Utility method converting json-ready-bean into correct Flask response.
        :param to_jsonify: the entity to be transferred into Flask response.
        Acceptable types: (1) list of AbstractJsonBean (2) AbstractJsonBean (3) dict
        None will also be accepted and transferred into 'not-available' response
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
                f'Check configuration', exc_info=sys.exc_info())
            print(str(sys.exc_info()))
            sys.stderr.write(str(sys.exc_info()))
            exit()

        try:
            self.service.run()

        except DatabaseNotAvailableError as exc:
            # in order to properly close, shutdown REST service and ensure the exit event is set
            if self.service.rest_server:
                self.service.rest_server.shutdown()

            eevent = ExitEvent()
            if not eevent.is_set():
                eevent.set()

            logging.getLogger().critical(
                f'As the database is not available at the moment, the service is turning down', exc_info=exc)

        except DatabaseOperationAborted as exc:
            logging.getLogger().info(
                f'The database operation was aborted due to received exit event')

        except:
            self.service.log.critical(
                f'Uncaught exception detected when running service', exc_info=sys.exc_info())
            print(str(sys.exc_info()))
            sys.stderr.write(str(sys.exc_info()))
            exit()

#
# if __name__ == '__main__':
#     dt = datetime(year=2020, month=1, day=1)
#
#     for i in range(12):
#         dt = dt + timedelta(days=30)
#         srs = SunsetCalculator(dt)
#         print(f'On {dt} sunrise is at {srs.sunrise()}, sunset: {srs.sunset()}')

