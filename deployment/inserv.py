#!/usr/bin/python3

# INstall SERVice script

from datetime import datetime
import sys
import subprocess
import os.path
import logging
from configparser import ConfigParser, ExtendedInterpolation


class InstallationException(Exception):
    """
    Special type of exception, designed to distinguish internal errors from other, more environment specific
    """
    def __init__(self, component: str, message: str):
        """
        Initializes the exception with component name and detailed message
        :param component: the name of particular component / activity of the installer
        :param message: the details about error
        """
        Exception.__init__(self, f'[{component.upper()}] {message}')


class InstallationComponent:
    """
    Base class for all installation activities
    Provides access to the name of component and to logging facility
    """
    def __init__(self):
        pass

    def _component_name(self):
        raise NotImplementedError()

    def log(self) -> logging.Logger:
        return logging.getLogger(self._component_name())

    def raise_exception(self, message: str):
        raise InstallationException(component=self._component_name(), message=message)


class CommandlineConfig:
    """
    Keeps the configuration of the installer passed in commandline arguments
    """

    DBTEST = '--db:test'
    UNINSTALL = ['--uninstall', '-u']
    START = '--start'

    USAGE = 'Usage:\n' \
            'sudo ./inserv.py ./install/configuration_file.ini [optional parameters]\n' \
            'Optional parameters are:\n' \
            f'[{DBTEST}] if present, the service should be installed to write to test database, not production\n' \
            f'[{UNINSTALL}] if present, the installer will uninstall given service\n' \
            f'[{START}] if present, the installer will start the service immediately after installation'

    COMPONENT = 'commandline config'

    def __init__(self):
        """
        Initializes the configuration from sys.argv
        """
        if len(sys.argv) < 2:
            # interactive mode
            self.config_file = input('Enter configuration file, or just try the service short name > ')
        else:
            self.config_file = sys.argv[1]

        self.dbtest_mode = False
        self.install = True
        self.start_immediately = False

        for arg in sys.argv[2:]:
            if arg == CommandlineConfig.DBTEST:
                self.dbtest_mode = True
            elif arg in CommandlineConfig.UNINSTALL:
                self.install = False
            elif arg == CommandlineConfig.START:
                self.start_immediately = True
            else:
                raise InstallationException(CommandlineConfig.COMPONENT,
                                            f'Parameter not recognized: {arg}. {CommandlineConfig.USAGE}')

        if not os.path.exists(self.config_file):
            # try to guess config
            self.config_file = f'./install/{self.config_file}.install.ini'

            if not os.path.exists(self.config_file):
                raise InstallationException(CommandlineConfig.COMPONENT,
                                            f'Path to the file with installation configuration: {self.config_file} '
                                            f'points to an invalid location')

        if not os.path.isfile(self.config_file):
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'Path to the file with installation configuration: {self.config_file} '
                                        f"does not point to an actual file")

        if not self.install and self.start_immediately:
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'Instructed both to uninstall and to start the service. '
                                        f'Make up your mind, the two options are contradicting')

        try:
            with open(self.config_file, 'r'):
                pass
        except PermissionError as pererr:
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'The file with installation configuration: {self.config_file} '
                                        f"cannot be opened using current security context. "
                                        f"Try with sudo. ({str(pererr)})")

        self.install_config_file_name = os.path.split(os.path.splitext(self.config_file)[0])[-1]


class Config(InstallationComponent, ConfigParser):
    """
    Keeps parsed content of installation config
    Subclasses built-in configparser.ConfigParser, so all handy methods are already here
    """
    COMPONENT = 'installation config'

    CREDENTIALS_FILE = ".credentials"
    COMMON_CFG_FILE = "common.install.ini"

    SECTION_SERVICE = "SERVICE"
    SECTION_GENERAL = "GENERAL"
    SECTION_PATH = "PATH"
    SECTION_EXTERNAL_MODULES = "EXTERNALS"
    SECTION_COMMON_EXTERNAL_MODULES = "COMMON-EXTERNALS"
    SECTION_MODULES = "MODULES"
    SECTION_COMMON_MODULES = "COMMON-MODULES"
    SECTION_DATABASE = "DATABASE"

    OPTION_NAME = "name"
    OPTION_DESCRIPTION = "description"
    OPTION_VENV = "service-venv"
    OPTION_MAIN_MODULE = "main"
    OPTION_LOOKUP_PATH = 'module-path'
    OPTION_BASE_DIR = 'service-base'
    OPTION_SERVICE_LOG = 'service-log'
    OPTION_SERVICE_INI = 'service-ini'
    OPTION_DB = 'db'
    OPTION_DB_TEST = 'db_test'
    OPTION_HOST = 'host'
    OPTION_SHORT_NAME = "short-name"
    OPTION_USER = 'user'
    OPTION_PASSWORD = 'password'

    REQUIRED_OPTIONS = [(SECTION_SERVICE, OPTION_NAME),
                        (SECTION_GENERAL, OPTION_SHORT_NAME),
                        (SECTION_PATH, OPTION_VENV),
                        (SECTION_PATH, OPTION_SERVICE_INI),
                        (SECTION_MODULES, OPTION_MAIN_MODULE),
                        (SECTION_DATABASE, OPTION_HOST)]

    def _component_name(self):
        return Config.COMPONENT

    def __init__(self, config_file):
        InstallationComponent.__init__(self)
        ConfigParser.__init__(self, interpolation=ExtendedInterpolation(), allow_no_value=True)

        config_dir = os.path.dirname(config_file)
        credentials_file = os.path.join(config_dir, Config.CREDENTIALS_FILE)
        common_cfg = os.path.join(config_dir, Config.COMMON_CFG_FILE)

        if not os.path.exists(credentials_file):
            self.raise_exception(
                f'The file with credentials: {credentials_file} '
                f"does not exist")

        if not os.path.exists(common_cfg):
            self.raise_exception(
                f'The file with common installation configuration: {common_cfg} '
                f"does not exist")

        self.read([credentials_file, common_cfg, config_file])
        self._verfy_config()

    def _verfy_config(self):
        """
        Checks if all required configuration is in place
        """
        violations = list()
        for ropt in self.REQUIRED_OPTIONS:
            val = self.get(section=ropt[0], option=ropt[1])
            if not val:
                violations.append(f'missing option {ropt}')

        if len(violations) > 0:
            self.raise_exception(f'The configuration misses the following required options: {str(violations)}')

    def get_service_full_name(self):
        return self.get(section=self.SECTION_SERVICE, option=self.OPTION_NAME)

    def get_service_short_name(self):
        return self.get(section=self.SECTION_GENERAL, option=self.OPTION_SHORT_NAME)

    def get_service_description(self):
        return self.get(section=self.SECTION_SERVICE, option=self.OPTION_DESCRIPTION, fallback='BHS Service')

    def get_path_venv(self):
        return self.get(section=self.SECTION_PATH, option=self.OPTION_VENV)

    def get_path_base_dir(self):
        return self.get(section=self.SECTION_PATH, option=self.OPTION_BASE_DIR)

    def get_external_modules(self) -> list:
        _modules = list()
        if self.has_section(section=self.SECTION_COMMON_EXTERNAL_MODULES):
            _modules = self.options(section=self.SECTION_COMMON_EXTERNAL_MODULES)

        if self.has_section(section=self.SECTION_EXTERNAL_MODULES):
            _modules.extend(self.options(section=self.SECTION_EXTERNAL_MODULES))

        return _modules

    def get_modules(self) -> list:
        _modules = list()
        if self.has_section(section=self.SECTION_COMMON_MODULES):
            _modules = self.options(section=self.SECTION_COMMON_MODULES)

        if self.has_section(section=self.SECTION_MODULES):
            internal = self.options(section=self.SECTION_MODULES)
            for intern in internal:
                if intern != self.OPTION_MAIN_MODULE:
                    _modules.append(intern)

        return _modules

    def get_main_module(self) -> str:
        return self.get(section=self.SECTION_MODULES, option=self.OPTION_MAIN_MODULE)

    def get_modules_lookup_paths(self) -> list:
        _paths = list()
        if self.has_option(section=self.SECTION_PATH, option=self.OPTION_LOOKUP_PATH):
            split = self.get(section=self.SECTION_PATH, option=self.OPTION_LOOKUP_PATH).split(",")
            for el in split:
                _paths.append(el.strip())
        else:
            _paths.append("../")
        return _paths

    def get_path_service_log(self) -> str:
        # keep the value in self.SECTION_PATH / self.OPTION_SERVICE_LOG
        if self.has_option(self.SECTION_PATH, self.OPTION_SERVICE_LOG):
            return self.get(self.SECTION_PATH, self.OPTION_SERVICE_LOG)

        parser = ConfigParser()
        parser.read(self.get_path_origin_service_ini())

        log_dir = '/var/log/bhs'
        if parser.has_option('LOG', 'logfile'):
            log_dir = os.path.dirname(parser.get('LOG', 'logfile'))

        self.set(self.SECTION_PATH, self.OPTION_SERVICE_LOG, log_dir)

        return log_dir

    def get_path_service_ini(self) -> str:
        return self.get(self.SECTION_PATH, self.OPTION_SERVICE_INI)

    def get_path_origin_service_ini(self) -> str:
        return os.path.join('config', self.get_service_short_name()+'.ini')

    def get_path_service_env_ini(self) -> str:
        return os.path.join(self.get_path_service_ini(), 'env.ini')

    def get_path_systemd(self) -> str:
        return os.path.join('/etc/systemd/system', self.get_service_full_name()+'.service')

    def get_path_systemd_template(self) -> str:
        return './$template.service'

    def get_database_db(self, test_mode: bool) -> str:
        return self.get(self.SECTION_DATABASE, self.OPTION_DB_TEST, fallback='bhs_test') \
            if test_mode else self.get(self.SECTION_DATABASE, self.OPTION_DB, fallback='bhs')

    def get_database_host(self) -> str:
        return self.get(self.SECTION_DATABASE, self.OPTION_HOST)

    def get_database_credentials(self) -> tuple:
        sect = self.get_service_short_name().upper()
        return self.get(sect, self.OPTION_USER), self.get(sect, self.OPTION_PASSWORD)


class SubprocessAction(InstallationComponent):

    def __init__(self):
        InstallationComponent.__init__(self)
        self.error = None

    def _component_name(self):
        return 'COMMAND'

    def execute(self, command: list, must_succeed: bool = False):

        exec_res = subprocess.run(command, capture_output=True)

        if exec_res and exec_res.returncode == 0:
            # success, catch output
            self.log().debug(f'Executing {str(command)} SUCCEEDED. '
                             f'Stdout: <{exec_res.stdout.decode("utf-8").rstrip()}>')
        else:
            self.error = f'Executing {str(command)} FAILED.\n' \
                         f'Return code: {exec_res.returncode if exec_res else "N/A"};\n' \
                         f'Stdout: <{exec_res.stdout.decode("utf-8").rstrip() if exec_res and exec_res.stdout else "N/A"}>;\n' \
                         f'Stderr: <{exec_res.stderr.decode("utf-8").rstrip() if exec_res and exec_res.stderr else "N/A"}>'

            if must_succeed:
                self.raise_exception(self.error)
            else:
                self.log().warning(self.error)


class ServiceControl(SubprocessAction):

    def __init__(self, service_name: str):
        SubprocessAction.__init__(self)
        self.service_name = service_name

    def _component_name(self):
        return 'SYSTEMCTL'

    def stop(self):
        self.execute(command=['sudo', 'systemctl', 'stop', self.service_name], must_succeed=False)

    def disable(self):
        self.execute(command=['sudo', 'systemctl', 'disable', self.service_name], must_succeed=False)

    def install(self):
        self.execute(command=['sudo', 'systemctl', 'daemon-reload'], must_succeed=True)
        self.execute(command=['sudo', 'systemctl', 'enable', self.service_name+".service"], must_succeed=True)

    def start(self):
        self.execute(command=['sudo', 'systemctl', 'start', self.service_name], must_succeed=True)


class VenvManager(SubprocessAction):

    def __init__(self, venv_path: str):
        SubprocessAction.__init__(self)
        self._path = venv_path

    def _component_name(self):
        return 'VENV'

    def create(self):
        self.execute(command=['sudo', 'python3', '-m', 'venv', '--clear', self._path], must_succeed=True)

    def remove(self):
        self.execute(command=['sudo', 'rm', '-rd', self._path], must_succeed=False)

    def install_module(self, _module: str):
        self.execute(command=['sudo', os.path.join(self._path, 'bin', 'pip3'), 'install', _module], must_succeed=True)


class LocalModuleManager(SubprocessAction):

    def __init__(self, lookup_paths: list, venv_path: str):
        SubprocessAction.__init__(self)
        self._lookup_paths = lookup_paths
        self.modules_target_path = os.path.join(venv_path, 'lib', 'python3.7', 'site-packages')
        self._venv_path = venv_path
        self.base_dir = os.path.dirname(self._venv_path)
        self.main_module_target_path = None  # will be intialized during installation

    def _component_name(self):
        return 'MODULE'

    def _module_file(self, _module: str):
        return _module if _module.endswith('.py') else _module + '.py'

    def _find_module(self, _module):
        module_path = list()
        module_file = self._module_file(_module)
        for path in self._lookup_paths:
            p = os.path.join(path, module_file)
            if os.path.exists(p) and os.path.isfile(p):
                module_path.append(p)

        if len(module_path) > 1:
            self.raise_exception(
                message=f'The module {_module} has been located in multiple locations: {str(module_path)}. '
                        f'The installation cannot continue')

        if len(module_path) == 0:
            self.raise_exception(message=f'The module {_module} was not located in none of: {str(self._lookup_paths)}')

        return module_path[0]

    def install_module(self, _module: str):
        module_path = self._find_module(_module=_module)

        # copy the located .py file to target directory
        target_path = os.path.join(self.modules_target_path, self._module_file(_module=_module))
        self.execute(['sudo', 'mkdir', '-p', os.path.dirname(target_path)], must_succeed=True)
        self.execute(['sudo', 'cp', '-u', '-r', module_path, target_path], must_succeed=True)

    def install_main_module(self, _main_module: str):
        main_module_file = self._find_module(_main_module)

        # ensure target dir exists
        self.main_module_target_path = os.path.join(self.base_dir,
                                                    os.path.basename(self._module_file(_module=_main_module)))

        with open(main_module_file, 'r') as _origin, open(self.main_module_target_path, 'w', encoding='utf-8') as _target:
            shebang = _origin.readline()
            if not shebang.startswith('#!'):
                self.raise_exception(f'First code line in main module {_main_module} does not seem to contain shebang')

            shebang = '#!'+os.path.join(self._venv_path, 'bin', 'python3')+'\n'
            _target.write(shebang)
            _target.writelines(_origin.readlines())

        # ensure it is executable!
        self.execute(['chmod', '-v', 'u+x', self.main_module_target_path])

    def remove_all(self):
        self.execute(command=['sudo', 'rm', '-rd', self.base_dir], must_succeed=False)


class EnvIniCreator(InstallationComponent, ConfigParser):
    SECTION_DATABASE = 'DATABASE'
    OPTION_DB = 'db'
    OPTION_USER = 'user'
    OPTION_PASSWORD = 'password'
    OPTION_HOST = 'host'

    def __init__(self, target_file: str):
        InstallationComponent.__init__(self)
        ConfigParser.__init__(self)
        self.target_file = target_file

    def _component_name(self):
        return 'ENV-INI'

    def create(self, host: str, db: str, credentials: tuple):
        self.add_section(self.SECTION_DATABASE)
        self.set(section=self.SECTION_DATABASE, option=self.OPTION_DB, value=db)
        self.set(section=self.SECTION_DATABASE, option=self.OPTION_USER, value=credentials[0])
        self.set(section=self.SECTION_DATABASE, option=self.OPTION_PASSWORD, value=credentials[1])
        self.set(section=self.SECTION_DATABASE, option=self.OPTION_HOST, value=host)

        with open(self.target_file, 'w', encoding='utf-8') as _w_file:
            self.write(_w_file)


class IniManager(SubprocessAction):

    def __init__(self, target_dir: str, ini_file: str):
        SubprocessAction.__init__(self)
        self.ini_base_dir = target_dir
        self.ini_target_file_path = os.path.join(target_dir, os.path.basename(ini_file))
        self.ini_origin_file_path = ini_file

    def _component_name(self):
        return 'SERVICE-INI'

    def copy_ini(self):
        # ensure the target dir exists
        self.execute(['sudo', 'mkdir', '-p', self.ini_base_dir], must_succeed=True)
        self.log().debug(f'Ensured that service config (ini) basedir exists')

        # copy the file
        self.execute(['sudo', 'cp', '-u', '-r', self.ini_origin_file_path, self.ini_target_file_path],
                     must_succeed=True)
        self.log().debug(f'Service config file {self.ini_origin_file_path} is copied to {self.ini_target_file_path}')

    def remove(self):
        self.execute(command=['sudo', 'rm', '-rd', self.ini_base_dir], must_succeed=False)


class SystemdServiceCreator(SubprocessAction, ConfigParser):
    SECTION_UNIT = 'Unit'
    SECTION_SERVICE = 'Service'

    OPTION_DESCRIPTION = 'Description'
    OPTION_EXEC_START = 'ExecStart'
    OPTION_WORKING_DIRECTORY = 'WorkingDirectory'

    def __init__(self, template_file: str,  target_file: str):
        InstallationComponent.__init__(self)
        ConfigParser.__init__(self)
        self.optionxform = str # preserves case-sensitivity of options
        self.target_file = target_file
        self.read(template_file)

    def _component_name(self):
        return 'SYSTEMD-INI'

    def create(self, script_path: str, service_descripton: str, working_directory: str):
        self.set(self.SECTION_UNIT, self.OPTION_DESCRIPTION, service_descripton)
        self.set(self.SECTION_SERVICE, self.OPTION_EXEC_START, script_path)
        self.set(self.SECTION_SERVICE, self.OPTION_WORKING_DIRECTORY, working_directory)

        with open(self.target_file, 'w', encoding='utf-8') as _w_file:
            self.write(_w_file, space_around_delimiters=False)

    def remove(self):
        self.execute(command=['sudo', 'rm', '-fv', self.target_file], must_succeed=False)


def init_logging(cmdline: CommandlineConfig) -> logging.Logger:
    logging.basicConfig(
        filename=f'{datetime.today().strftime("%Y%m%d%H%M%S")}_{cmdline.install_config_file_name}.log',
        level=logging.DEBUG,
        format='%(asctime)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger()
    stream_hdlr = logging.StreamHandler(sys.stdout)
    stream_hdlr.setLevel(logging.INFO)
    stream_hdlr.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(stream_hdlr)
    return logger


if __name__ == '__main__':
    try:
        cmdline = CommandlineConfig()
        log = init_logging(cmdline)
        config = Config(config_file=cmdline.config_file)
        service_ctrl = ServiceControl(service_name=config.get_service_full_name())
        venv_mngr = VenvManager(venv_path=config.get_path_venv())
        module_mngr = LocalModuleManager(lookup_paths=config.get_modules_lookup_paths(),
                                         venv_path=config.get_path_venv())
        systemd_creator = SystemdServiceCreator(template_file=config.get_path_systemd_template(),
                                                target_file=config.get_path_systemd())
        ini_mngr = IniManager(target_dir=config.get_path_service_ini(),
                              ini_file=config.get_path_origin_service_ini())
        envini_creator = EnvIniCreator(target_file=config.get_path_service_env_ini())

        if cmdline.install:
            # install

            log.info(f'Installation initialized for service {config.get_service_full_name()}')

            service_ctrl.stop()
            log.info(f'Service {config.get_service_full_name()} stopped')

            service_ctrl.disable()
            log.info(f'Service {config.get_service_full_name()} disabled')

            venv_mngr.create()
            log.info(f'Virtual environment created @ {config.get_path_venv()}')

            externals = config.get_external_modules()
            for external in externals:
                venv_mngr.install_module(external)
                log.info(f'Module {external} installed')
            log.info(f'All external modules installed')

            modules = config.get_modules()
            for module in modules:
                module_mngr.install_module(module)
                log.info(f'Module {module} installed')
            log.info(f'All modules installed')

            main_module = config.get_main_module()
            module_mngr.install_main_module(_main_module=main_module)
            log.info(f'Main module {main_module} installed')

            service_log_dir = config.get_path_service_log()
            if not os.path.exists(service_log_dir):
                SubprocessAction().execute(['mkdir', '-p', service_log_dir])
                log.info(f'Service log dir {service_log_dir} created')

            SubprocessAction().execute(['chmod', 'ugo+rw', service_log_dir])
            log.info(f'Access rights to service log dir {service_log_dir} amended')

            ini_mngr.copy_ini()
            log.info(f'Service configuration file is copied to {ini_mngr.ini_target_file_path}')

            envini_creator.create(host=config.get_database_host(),
                                  db=config.get_database_db(cmdline.dbtest_mode),
                                  credentials=config.get_database_credentials())
            log.info(f'File with environment-specific settings created: {config.get_path_service_env_ini()}')

            systemd_creator.create(script_path=module_mngr.main_module_target_path,
                                   service_descripton=config.get_service_description(),
                                   working_directory= os.path.dirname(module_mngr.main_module_target_path))
            log.info(f'Systemd configuration file created @ {config.get_path_systemd()}')

            service_ctrl.install()
            log.info(f'Systemd instructed to enable new service')

            log.info(f'{config.get_service_full_name()} installed successfully')

            if cmdline.start_immediately:
                service_ctrl.start()
                log.info(f'{config.get_service_full_name()} started')

        else:
            # uninstall

            log.info(f'De-installation initialized for service {config.get_service_full_name()}')

            service_ctrl.stop()
            log.info(f'Service {config.get_service_full_name()} stopped')

            service_ctrl.disable()
            log.info(f'Service {config.get_service_full_name()} disabled')

            module_mngr.remove_all()
            log.info(f'The directory {module_mngr.base_dir} removed with all the content')

            systemd_creator.remove()
            log.info(f'The SYSTEMD file {systemd_creator.target_file} removed')

            #TODO systemctl reload?

            ini_mngr.remove()
            log.info(f'The directory {ini_mngr.ini_base_dir} removed')

            log.info(f'{config.get_service_full_name()} uninstalled')

    except InstallationException as e:
        sys.stderr.write(str(e))
