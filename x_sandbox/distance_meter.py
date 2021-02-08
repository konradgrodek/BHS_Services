import serial
import time

if __name__ == '__main__':
    print(f'Distance meter. Serial version: {serial.__version__}')

    device = serial.Serial("/dev/ttyAMA0", 9600)

    if not device.isOpen():
        print('Error, device not opened')

    # device.setRTS(1)

    while 1 == 1:
        data = []
        i = 0
        while device.inWaiting() == 0:
          i += 1
          time.sleep(0.05)
          if i > 4:
            break
        i = 0
        while device.inWaiting() > 0:
          data.append(ord(device.read()))
          i += 1
          if data[0] != 0xff:
            i = 0
            data = []
          if i == 4:
            break
        device.read(device.inWaiting())
        if i == 4:
          sum = (data[0] + data[1] + data[2]) & 0x00ff
          if sum != data[3]:
            print('checksum error')
          else:
            distance = data[1]*256 + data[2]
            print(f'OK. Distance: {distance}')
        else:
          print(f'Data error: {data}')
        time.sleep(10)