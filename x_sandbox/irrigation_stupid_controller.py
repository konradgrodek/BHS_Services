from gpiozero import Button, LED
from datetime import datetime
import time
import sys

PIN_BTN = 1
PIN_LED_PUMP = 25
PIN_LED_CINTER = 7
PIN_LED_COUTER = 8
PIN_LED_OFF = 16

STATE_OFF = "off"
STATE_INTERN = "intern"
STATE_OUTERN = "outern"


class IrrigationButton(Button):

    def __init__(self, btn_pin: int, pump_led: LED, circ_intern_led: LED, circ_outer_led: LED, off_led: LED):
        Button.__init__(self, btn_pin, pull_up=None, active_state=False)
        self.count = 0
        self.contact_mark = datetime.now()
        self.when_activated = self.contact
        self.when_deactivated = self.nocontact
        self.pump_led = pump_led
        self.circ_intern_led = circ_intern_led
        self.circ_outer_led = circ_outer_led
        self.off_led = off_led
        self.off_led.on()
        self.state = STATE_OFF

    def contact(self, arg):
        self.count += 1
        self.contact_mark = datetime.now()


        # print(f'{self.count} Contact detected @ {arg} @ {datetime.now()}')

    def nocontact(self, arg):
        print(f'{self.count} Contact ended @ {arg} @ {datetime.now()}')
        delta = datetime.now() - self.contact_mark
        print(f'{self.count} {delta.total_seconds():10.3} s     {datetime.now()}')
        self.contact_mark = None

        if self.state == STATE_OFF:
            self.off_led.off()
            self.circ_intern_led.on()
            time.sleep(2)
            self.pump_led.on()
            self.state = STATE_INTERN
        elif self.state == STATE_INTERN:
            self.pump_led.off()
            self.circ_intern_led.off()
            self.circ_outer_led.on()
            time.sleep(2)
            self.pump_led.on()
            self.state = STATE_OUTERN
        elif self.state == STATE_OUTERN:
            self.pump_led.off()
            self.circ_outer_led.off()
            self.off_led.on()
            self.state = STATE_OFF



if __name__ == '__main__':
    button = IrrigationButton(PIN_BTN, LED(PIN_LED_PUMP), LED(PIN_LED_CINTER), LED(PIN_LED_COUTER), LED(PIN_LED_OFF))

    try:
        while 1 == 1:
            print('.')
            time.sleep(60)
    except:
        print('Bum! Something went wrong! ')
        print(sys.exc_info())
