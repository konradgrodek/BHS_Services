import serial
import time
from datetime import datetime
from os import system


if __name__ == '__main__':
    print(f'Distance meter. Serial version: {serial.__version__}')

    device = serial.Serial("/dev/ttyAMA0", 9600)
    device.reset_input_buffer()
    device.reset_output_buffer()
    device.setRTS(1)

    print(f'Device name: {device.name}. Settings: {device.get_settings()}. Starting @ {datetime.now().isoformat()}')

    reading = 0
    min_ = 0
    max_ = 0
    summed = 0

    while device.isOpen():
        mark = datetime.now()
        while device.inWaiting() > 0:
            btes = device.read_all()
            reading += 1

            btesInt = [bte for bte in btes]

            sum_ = (btes[0] + btes[1] + btes[2]) & 0x00ff

            measure = btesInt[1] * 256 + btesInt[2]

            summed += measure
            if min_ == 0 or min_ > measure:
                min_ = measure
            if max_ < measure:
                max_ = measure

            system('clear')
            # print(f'{int((datetime.now() - mark).total_seconds()*1000)}\t{btes.hex( )}\t\t{btesInt}\t{sum}\t{"correct" if sum == btesInt[3] else "WRONG!"}\t{btesInt[1]*256+btesInt[2]} [mm]')
            print(f'{reading}\t{int((datetime.now() - mark).total_seconds() * 1000)} [ms] \t{btes.hex()}\t{measure} [mm]\tmin:{min_}\tavg:{int(summed/reading)}\tmax:{max_}')
            mark = datetime.now()

    print(f'Device {device.name} is closed')


"""
Useful:
python -m serial.tools.list_ports

"""