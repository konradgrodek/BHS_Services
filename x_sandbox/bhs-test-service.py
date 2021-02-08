#!/usr/bin/python3

from configparser import ConfigParser
import mysql.connector as mariadb
import logging
import random
import time

config = ConfigParser()
config.read('/etc/bhs/bhstestservice.config')
# config.read('bhstestservice.config')

db = config['DATABASE'].get(' db')
user = config['DATABASE'].get('user')
passwd = config['DATABASE'].get('password')
host = config['DATABASE'].get('host')

logfile = config['LOG'].get('logfile')

logging.basicConfig(
    filename=logfile,
    level=logging.DEBUG,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger(__name__)

try:
    conn = mariadb.connect(user=user, password=passwd, database=db, host=host)

    cursor = conn.cursor()

    cursor.execute('select st_id, st_name from sensor_types order by st_id asc;')

    for (st_id, st_name) in cursor:
        log.info('ID: %i', st_id)
        log.info('name: %s', st_name)

except mariadb.Error as e:
    log.critical('Something went terribly wrong')
    log.error(e, exc_info=True)

finally:
    cursor.close()
    conn.close()

val = int(100000*random.random())
div = int(1000*random.random())
while True:
    log.info('Calculating %i %% %i', val, div)
    res = val % div
    log.info('Result = %i', res)
    val = int(100000 * random.random())
    if res != 0:
        div = res

    slp = random.random()/2
    log.info('Let me think now for %f seconds', slp)
    time.sleep(slp)

# EOF
