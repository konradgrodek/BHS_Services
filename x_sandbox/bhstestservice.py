#!/usr/bin/python3

from configparser import ConfigParser
import logging
from threading import Event
import signal

import random

class Configuration:
    """Class being main point accessing the configuration"""
    ROOT = '/etc/bhs'
    EXT ='.config'

    SECTION_DB = 'DATABASE'
    SECTION_LOG = 'LOG'

    PARAM_DB = 'db'
    PARAM_USER = 'user'
    PARAM_PASSWORD = 'password'
    PARAM_HOST = 'host'

    PARAM_LOGFILE = 'logfile'
    PARAM_LOGLEV = 'level'

    def __init__(self, name: str):
        """Initializes the configuration. Parameter `name` is mandatory as it is used to find the configuration file"""
        self.configPath = self.ROOT + '/' + name.lower() + self.EXT
        self.configParser = None

    def getConfig(self):
        if self.configParser is None:
            self.configParser = ConfigParser()
            self.configParser.read(self.configPath)

        return self.configParser

    def getConfigValue(self, section: str, parameter: str):
        return self.getConfig()[section].get(parameter)

    def getLogFile(self) -> str:
        #return "./log.log"
        return self.getConfigValue(self.SECTION_LOG, self.PARAM_LOGFILE)

    def getLogLevel(self) -> int:
        level = self.getConfigValue(self.SECTION_LOG, self.PARAM_LOGLEV)
        if level is None:
            return logging.DEBUG
        return logging.getLevelName(level)

    def getDbUser(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_USER)

    def getDb(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_DB)

    def getDbPassword(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_PASSWORD)

    def getDbHost(self) -> str:
        return self.getConfigValue(self.SECTION_DB, self.PARAM_HOST)



class Service:
    """Base class for all Black House Sentry services"""

    def __init__(self):
        """Initializes the object responsible for running BHS service"""
        self.exitEvent = Event()
        self.configuration = Configuration(self.provideName())
        logging.basicConfig(
            filename=self.configuration.getLogFile(),
            level=self.configuration.getLogLevel(),
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.log = logging.getLogger(self.provideName().upper())

    def run(self):
        signal.signal(getattr(signal, 'SIGTERM'), self.onSigterm)

        while not self.exitEvent.is_set():
            sleeptime = self.main()
            self.exitEvent.wait(sleeptime)

        self.cleanup()
        self.log.info('All done. Bye')

    def main(self) -> float:
        """This method must be overwriten in order to implement the main loop of the service
        Return number of seconds that the main loop should wait for next execution of this method"""
        raise NotImplementedError()

    def cleanup(self):
        '''Override this method to react on SIGTERM'''
        pass

    def onSigterm(self, signum, stackframe):
        self.log.critical('Received SIGTERM, terminating. Signum: %i', signum)
        self.exitEvent.set()

    def provideName(self) -> str:
        """This method must be overwriten in order to provide name of the service"""
        raise NotImplementedError()


class ExampleService(Service):
    def main(self):
        """This method must be overwriten in order to implement the main loop of the service"""
        self.log.debug('Entering main method')
        sleeptime = 60*random.random()
        self.log.info('Waiting for %f seconds', sleeptime)
        return sleeptime

    def cleanup(self):
        """Override this method to react on SIGTERM"""
        self.log.info('Nothing to clean')
        pass

    def provideName(self):
        return 'BHSTestService'


if __name__ == '__main__':
    ExampleService().run()
