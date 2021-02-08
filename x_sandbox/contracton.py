import RPi.GPIO as GPIO
from datetime import datetime
import time
import sys

PIN_CON = 18

def contact(pin):
    print('Contact detected @ '+str(pin)+' @ '+str(datetime.now()))
    GPIO.remove_event_detect(pin)
    GPIO.add_event_detect(pin, GPIO.RISING, callback=nocontact)
    print('Waiting for release of contact')


def nocontact(pin):
    print('Contact ended @ '+str(pin)+' @ '+str(datetime.now()))
    GPIO.remove_event_detect(pin)
    GPIO.add_event_detect(pin, GPIO.FALLING, callback=contact)
    print('Waiting for contact')


if __name__ == '__main__':
    GPIO.setmode(GPIO.BCM)

    try:
        GPIO.setup(PIN_CON, GPIO.IN)
        GPIO.add_event_detect(PIN_CON, GPIO.FALLING, callback=contact)
    except:
        print('Bum! Something went wrong! ')
        print(sys.exc_info())

    try:
        while 1 == 1:
            print('.')
            time.sleep(60)

    except:
        print('Bum! Something went wrong! ')
        print(sys.exc_info())

    finally:
        GPIO.cleanup()
