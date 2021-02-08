from gpiozero import Button, LED
from datetime import datetime
import time
import sys

PIN_CON = [17]
PIN_LED = 16


class PressCounter(Button):

    def __init__(self, pin: int, led: LED):
        Button.__init__(self, pin, pull_up=None, active_state=False)
        self.count = 0
        self.contact_mark = datetime.now()
        self.when_activated = self.contact
        self.when_deactivated = self.nocontact
        self.led = led

    def contact(self, arg):
        self.count += 1
        self.contact_mark = datetime.now()
        self.led.on()
        print(f'{self.count} Contact detected @ {arg} @ {datetime.now()}')

    def nocontact(self, arg):
        print(f'{self.count} Contact ended @ {arg} @ {datetime.now()}')
        delta = datetime.now() - self.contact_mark
        print(f'{self.count} {delta.total_seconds():10.3} s     {datetime.now()}')
        self.contact_mark = None
        self.led.off()



if __name__ == '__main__':
    led = LED(PIN_LED)
    buttons = [PressCounter(pin, led) for pin in PIN_CON]

    try:
        while 1 == 1:
            print('.')
            time.sleep(60)
    except:
        print('Bum! Something went wrong! ')
        print(sys.exc_info())
