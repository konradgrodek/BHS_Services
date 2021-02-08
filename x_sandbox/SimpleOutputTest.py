from gpiozero import Button, LED, OutputDevice
from datetime import datetime
import time

def blink(out: OutputDevice, count: int):
    for i in range(count):
        out.on()
        print(f'Output @ {out.pin} is ON [{i+1}/{count}]')
        time.sleep(1)
        out.off()
        print(f'Output @ {out.pin} is OFF')
        time.sleep(1)

if __name__ == '__main__':
    outs = [
        OutputDevice(5, active_high=False, initial_value=False),
        OutputDevice(6, active_high=False, initial_value=False),
        OutputDevice(13, active_high=False, initial_value=False)
    ]

    while 1 == 1:
        for i in range(len(outs)):
            blink(outs[i], i+1)
