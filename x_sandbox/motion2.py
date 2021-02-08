import RPi.GPIO as GPIO
from datetime import datetime
import time
import sys

PIN_LED = 8
PINS_MSENS = [13]

def motionStarted(pin):
    print('Motion detected @ '+str(pin)+' @ '+str(datetime.now()))
    #GPIO.output(PIN_LED, GPIO.HIGH)
    GPIO.remove_event_detect(pin)
    GPIO.add_event_detect(pin, GPIO.FALLING, callback=motionEnded)


def motionEnded(pin):
    print('Motion stopped @ '+str(pin)+' @ '+str(datetime.now()))
    #GPIO.output(PIN_LED, GPIO.LOW)
    GPIO.remove_event_detect(pin)
    GPIO.add_event_detect(pin, GPIO.RISING, callback=motionStarted)


if __name__ == '__main__':
    GPIO.setmode(GPIO.BOARD)
    #GPIO.setup(PIN_LED, GPIO.OUT, initial=GPIO.LOW)
    for pin in PINS_MSENS:
        GPIO.setup(pin, GPIO.IN)

        try:
            GPIO.add_event_detect(pin, GPIO.RISING, callback=motionStarted)

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
