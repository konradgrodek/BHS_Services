import serial
import time
from datetime import datetime
from os import system
from gpiozero import DigitalOutputDevice

if __name__ == '__main__':
    print(f'Distance meter. Serial version: {serial.__version__}')

    device = serial.Serial("/dev/ttyAMA0", 9600)
    device.reset_input_buffer()
    device.reset_output_buffer()

    # tx = DigitalOutputDevice(pin=14, active_high=True)
    # tx.on()

    bck = '\b'

    print(f'Device name: {device.name}. Settings: {device.get_settings()}. Starting @ {datetime.now().isoformat()}')

    while device.isOpen():
        mark = datetime.now()
        device.flush()

        while device.inWaiting() > 0:

            btes = device.read_all()

            btesInt = [bte for bte in btes]

            sum = (btes[0] + btes[1] + btes[2]) & 0x00ff

            distance = btesInt[1]*256+btesInt[2]

            msg = f'DISTANCE: {distance:04} [mm]\tDuration {int((datetime.now() - mark).total_seconds()*1000000):04} [us]'

            system('clear')
            print('ME007YS distance meter')
            print(msg, end='')
            print(bck*len(msg))


    print(f'Device {device.name} is closed')


"""
Useful:
python -m serial.tools.list_ports

"""