from gpiozero import Button
from datetime import datetime
import sys
from threading import Thread, Lock, Event

PIN_CON = 18
BCK = '\b'


class MonitoringThread(Thread, Button):

    def __init__(self, pin: int):
        Thread.__init__(self)
        Button.__init__(self, pin, pull_up=None, active_state=False)
        self.when_activated = self.contact
        self.when_deactivated = self.released
        self.lock_active = Lock()
        self.lock_inactive = Lock()
        self.lock_active.acquire()
        self.exit_event = Event()

    def contact(self):
        self.lock_active.release()
        self.lock_inactive.acquire()

    def released(self):
        self.lock_inactive.release()
        self.lock_active.acquire()

    def exit(self):
        self.exit_event.set()
        if self.lock_active.locked():
            self.lock_active.release()
        if self.lock_inactive.locked():
            self.lock_inactive.release()

    def print_part(self, s: str):
        sys.stdout.write(s)
        sys.stdout.flush()

    def run(self):
        print(f'Starting impulse counter at {self.pin} at {datetime.now():%Y-%m-%d %H:%M:%S}')
        contacts = 0
        while not self.exit_event.is_set():
            self.print_part('waiting...')
            self.lock_active.acquire()
            if self.exit_event.is_set():
                break
            contacts += 1
            mark = datetime.now()
            self.print_part(f'{BCK*10}[{contacts:03d}] {mark:%Y-%m-%d %H:%M:%S} ')
            self.lock_active.release()
            self.lock_inactive.acquire()
            print(f'{(datetime.now() - mark).total_seconds():3.4} seconds')
            self.lock_inactive.release()


if __name__ == '__main__':

    thread = MonitoringThread(PIN_CON)
    try:
        thread.start()
        thread.join()
    except KeyboardInterrupt:
        thread.exit()
        print('Bye')
    except:
        print('Bum! Something went wrong! ')
        print(sys.exc_info())

