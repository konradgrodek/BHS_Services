from configparser import ConfigParser

config = ConfigParser()
config.read('module.ini')

print(config['DATABASE'].get('user'))
print(config['DATABASE'].get('userA'))
print(config['DATABASE'].get('dupa'))
