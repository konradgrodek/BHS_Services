from gpiozero import Button, LED, OutputDevice
from datetime import datetime
import time

if __name__ == '__main__':
    led = LED(26, initial_value=False)
    btn = Button(19, pull_up=None, active_state=False)

    def pressed(arg):
        led.on()

    def released(arg):
        led.off()

    btn.when_activated = pressed
    btn.when_deactivated = released

    while 1 == 1:
        led.blink(on_time=0.2, off_time=0.2, n=3)
        time.sleep(10)


