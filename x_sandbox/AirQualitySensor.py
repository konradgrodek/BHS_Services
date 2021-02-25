import serial
from datetime import datetime
import struct
import time
from gpiozero import DigitalOutputDevice

CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1


def construct_command(cmd, data=[]):
    assert len(data) <= 12
    data += [0, ] * (12 - len(data))
    checksum = (sum(data) + cmd - 2) % 256
    bts = []
    bts.append(ord('\xaa'))
    bts.append(ord('\xb4'))
    bts.append(cmd)
    for d in data:
        bts.append(d)
    bts.append(ord('\xff'))
    bts.append(ord('\xff'))
    bts.append(checksum)
    bts.append(ord('\xab'))

    return bts


if __name__ == '__main__':
    print(f'Air Quality Sensor. Serial version: {serial.__version__}')


    pinOnOff = DigitalOutputDevice(pin=26, active_high=False)

    while 1:
        #turn on
        pinOnOff.on()

        time.sleep(10)

        device = serial.Serial("/dev/ttyAMA0", 9600)
        device.reset_input_buffer()
        device.reset_output_buffer()

        print(f'Device name: {device.name}. Settings: {device.get_settings()}. Starting @ {datetime.now().isoformat()}')

        # wake up!
        device.write(construct_command(CMD_SLEEP, [0x1, 1]))
        device.write(construct_command(CMD_MODE, [0x1, 1]))
        device.write(construct_command(CMD_QUERY_DATA))
        # device.flushOutput()

        mark = datetime.now()
        while device.inWaiting() > 0:
            btes = device.read_all()

            print(f'{int((datetime.now() - mark).total_seconds()*1000)}\t{btes.hex()}, size: {len(btes)}')
            mark = datetime.now()

            if len(btes) == 10:
                r = struct.unpack('<HHxxBB', btes[2:])
                pm25 = r[0] / 10.0
                pm10 = r[1] / 10.0
                # checksum = sum(v for v in btes[2:8]) % 256
                print(f'PM25: {pm25}, PM10: {pm10}')
                break

        # device.write(construct_command(CMD_MODE, [0x1, 0]))
        # device.write(construct_command(CMD_SLEEP, [0x1, 0]))

        # time.sleep(10)

        pinOnOff.off()
        time.sleep(10)

    print(f'Device {device._component_name} is closed')
