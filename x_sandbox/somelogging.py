import logging

log = logging.getLogger(__name__)
logging.basicConfig(filename='log.log', level=logging.DEBUG, format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
#RotatingFileHandler
#TimedRotatingFileHandler

log.debug('This is debug message')
log.info('Here comes info')
log.warning('And after that it''s warning time, with a parameter %i', 123)
log.error('I do not like errors')
log.critical('Kurwa, ratuj!')

#try:
#    raise Exception('bum!')
#
#except Exception e:
#    logging.