from gpiozero import Button, LED, OutputDevice
from datetime import datetime
import time

leds = [
    LED(12, initial_value=False),#r
    LED(20, initial_value=False),#g
    LED(21, initial_value=False)# b
    , LED(26, initial_value=False)
]
if __name__ == '__main__':

    def on(one, two):
        leds[one].on()
        leds[two].on()
        time.sleep(2)
        leds[one].off()
        leds[two].off()

    while True:
        for led in leds:
            led.on()
            time.sleep(2)
            led.off()

        # on(0,2) #green-yellow r+g
        # on(1,2) #seledyn b+g
        # on(0,1)# fiolet r+b
        #
        # leds[0].on()
        # leds[1].on()
        # leds[2].on()
        #
        # time.sleep(2)
        #
        # leds[0].off()
        # leds[1].off()
        # leds[2].off()





    # while 1 == 1:
    #     for led in leds:
    #         led.on()
    #         print(f'[{datetime.now()}] LED {led.pin} ON')
    #         time.sleep(2)
    #         print(f'[{datetime.now()}] LED {led.pin} OFF')
    #         led.off()

