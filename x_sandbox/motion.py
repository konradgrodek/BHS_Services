import RPi.GPIO as GPIO
import time

PIN_LED = 8
PIN_MSENS = 11

if __name__ == '__main__':
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(PIN_LED, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(PIN_MSENS, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    try:
        while True:
            if GPIO.input(PIN_MSENS) == GPIO.HIGH:
                print('Motion detected!')
                GPIO.output(PIN_LED, GPIO.HIGH)

            else:
                print('No motion, blink!')
                GPIO.output(PIN_LED, GPIO.HIGH)
                time.sleep(0.1)
                GPIO.output(PIN_LED, GPIO.LOW)

            time.sleep(0.5)
    except:
        GPIO.cleanup()
