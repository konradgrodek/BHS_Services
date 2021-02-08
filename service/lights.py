#!/usr/bin/python3

from gpiozero import LED, OutputDevice
from logging import Logger
import time

from service.common import *


class Outputs:
    """
    Collects the outputs: LEDs and PINs controlling pump and electrical valves
    """
    def __init__(self,
                 pin_light_spruce: int,
                 pin_light_oak_middle: int,
                 pin_light_oak_sides: int,
                 pin_led: int):
        """
        Constructor. Initializes the class members responsible for controlling output devices.
        May throw ugly exceptions if the pins are already allocated by other systems.
        """
        self.led = LED(pin_led, initial_value=False)
        self.light_spruce = OutputDevice(pin_light_spruce, active_high=False, initial_value=False)
        self.light_oak_middle = OutputDevice(pin_light_oak_middle, active_high=False, initial_value=False)
        self.light_oak_sides = OutputDevice(pin_light_oak_sides, active_high=False, initial_value=False)

    def __str__(self):
        return f"Light Controller output configured @ led: {self.led.pin}, " \
               f"spruce: {self.light_spruce.pin}, " \
               f"oak (middle-sides): {self.light_oak_middle.pin}-{self.light_oak_sides.pin}"


class IlluminationState:
    """
    Base class of all possible states of the system
    """

    SPRUCE = 'spruce'
    OAK_MIDDLE = 'oak-middle'
    OAK_SIDES = 'oak-sides'

    def __init__(self, outputs: Outputs, logger: Logger, duration_seconds: int):
        """
        Initializes the state using provided entities collecting output devices, configuration and logging
        :param outputs: collects all output devices
        :param logger: provides interface for logging
        :param duration_seconds: defines how long the lights shall be on
        """
        self.outputs = outputs
        self.log = logger
        self.duration_seconds = duration_seconds
        self.next = None
        self.termination_event = Event()

    def is_idle(self) -> bool:
        """
        Defines whether the state of the system is idle or not.
        Must be implemented by all subclasses
        :return: True if the system represents old cat sleeping on a couch
        """
        raise NotImplementedError()

    def on_start(self):
        """
        Key method for the system's state. Here's all the magic must happen. Behold of unicorns!
        :return: None
        """
        raise NotImplementedError()

    def operational_signal(self):
        """
        The method is called upon turning on given state
        and periodically when it is still in progress.
        :return:
        """
        raise NotImplementedError()

    def goto_next(self):
        """
        Rises the state's termination event, which should result in finalizing method on_start,
        which is waiting for the event
        :return: None
        """
        self.termination_event.set()

    def goto(self, state):
        self.next = state
        self.termination_event.set()

    def turn_off(self):
        """
        Sets Idle State as next state and raises event that ends current state
        :return:
        """
        self.termination_event.set()

    def _align(self, new_state: bool, output: OutputDevice, name: str):
        if new_state:
            if not output.is_active:
                output.on()
                self.log.info(f'{name}@{output.pin}:ON')
        else:
            if output.is_active:
                output.off()
                self.log.info(f'{name}@{output.pin}:OFF')

    def to_json(self) -> dict:
        return {self.SPRUCE: self.outputs.light_spruce.is_active,
                self.OAK_MIDDLE: self.outputs.light_oak_middle.is_active,
                self.OAK_SIDES: self.outputs.light_oak_sides.is_active}


class Off(IlluminationState):
    def __init__(self, outputs: Outputs, logger: Logger, default_duration_seconds: int):
        IlluminationState.__init__(self, outputs, logger, default_duration_seconds)

    def __str__(self):
        return "The lights are OFF"

    def is_idle(self) -> bool:
        return True

    def on_start(self):
        self.log.info(f"Aligning state...")

        self._align(False, self.outputs.light_spruce, self.SPRUCE.upper())
        self._align(False, self.outputs.light_oak_sides, self.OAK_MIDDLE.upper())
        self._align(False, self.outputs.light_oak_middle, self.OAK_SIDES.upper())
        self.operational_signal()

        self.log.info(f"Entering idle state ({str(self)}). Awaiting orders!")

        self.termination_event.wait()
        self.on_stop()

    def on_stop(self):
        """
        If there is no other state planned as next one, the AllLightsOn is set as next step
        :return:
        """
        if not self.next:
            self.next = On(self.outputs, self.log, None, self.duration_seconds, True, True, True)

    def operational_signal(self):
        self.log.debug('Signal: OFF')
        self.outputs.led.off()


class On(IlluminationState):
    def __init__(self,
                 outputs: Outputs,
                 logger: Logger,
                 duration_seconds: int,
                 default_duration_seconds: int,
                 spruce_on: bool,
                 oak_sides_on: bool,
                 oak_middle_on: bool):
        """
        Constructor
        :param outputs: collection of GPIO devices for lights controlling signals
        :param logger: for logging purposes
        :param duration_seconds: defines for how long shall the ON state last
        :param default_duration_seconds: if duration_seconds is missing, this is the default ON duration
        :param spruce_on: shall spruce light be ON?
        :param oak_sides_on: shall side lights of oaks be ON?
        :param oak_middle_on: shall middle light of oaks be ON?
        """
        IlluminationState.__init__(self,
                                   outputs,
                                   logger,
                                   duration_seconds if duration_seconds else default_duration_seconds)
        if not spruce_on and not oak_middle_on and not oak_sides_on:
            raise ValueError('The state ON must come with at least one active channels')
        if not duration_seconds and not default_duration_seconds:
            raise ValueError('Cannot turn ON without duration time')
        self.spruce_on = spruce_on
        self.oak_middle_on = oak_middle_on
        self.oak_sides_on = oak_sides_on
        self.default_duration_seconds = default_duration_seconds

    def __str__(self):
        return f"The lights are ON for: " \
               f"{self.SPRUCE if self.spruce_on else ''} " \
               f"{self.OAK_MIDDLE if self.oak_middle_on else ''} " \
               f"{self.OAK_SIDES if self.oak_sides_on else ''}"

    def is_idle(self) -> bool:
        return False

    def operational_signal(self):
        # 111 ALL
        if self.spruce_on and self.oak_sides_on and self.oak_middle_on:
            self.log.debug(f'Signal: {self.outputs.led.pin} BLINK (n=1)')
            self.outputs.led.blink(on_time=0.2, off_time=0.2, n=1, background=False)
            time.sleep(0.2)
            self.outputs.led.on()

        # 011 OAK
        elif not self.spruce_on and self.oak_sides_on and self.oak_middle_on:
            self.log.debug(f'Signal: {self.outputs.led.pin} BLINK (n=2)')
            self.outputs.led.blink(on_time=0.2, off_time=0.2, n=2, background=False)
            time.sleep(0.2)
            self.outputs.led.on()

        # 001 OAK-SIDES
        elif not self.spruce_on and not self.oak_sides_on and self.oak_middle_on:
            self.log.debug(f'Signal: {self.outputs.led.pin} BLINK (n=3)')
            self.outputs.led.blink(on_time=0.2, off_time=0.2, n=3, background=False)
            time.sleep(0.2)
            self.outputs.led.on()

        # 010 OAK-MIDDLE
        elif not self.spruce_on and self.oak_sides_on and not self.oak_middle_on:
            self.log.debug(f'Signal: {self.outputs.led.pin} BLINK (n=4)')
            self.outputs.led.blink(on_time=0.2, off_time=0.2, n=4, background=False)
            time.sleep(0.2)
            self.outputs.led.on()

        # 100 SPRUCE
        elif self.spruce_on and not self.oak_sides_on and not self.oak_middle_on:
            self.log.debug(f'Signal: {self.outputs.led.pin} BLINK (n=5)')
            self.outputs.led.off()
            time.sleep(0.2)
            self.outputs.led.blink(on_time=0.2, off_time=0.2, n=5, background=False)
            self.outputs.led.on()

        else:
            self.log.debug(f'Signal: {self.outputs.led.pin} OFF (unexpected)')
            self.outputs.led.off()

    def on_start(self):
        self.log.info("Aligning current state...")

        self._align(self.spruce_on, self.outputs.light_spruce, self.SPRUCE.upper())
        self._align(self.oak_middle_on, self.outputs.light_oak_sides, self.OAK_SIDES.upper())
        self._align(self.oak_sides_on, self.outputs.light_oak_middle, self.OAK_MIDDLE.upper())
        self.operational_signal()

        self.log.info(f"Current state: {str(self)}")

        self.termination_event.wait(self.duration_seconds)
        self.on_stop()

    def on_stop(self):
        """
        Performs operations upon ending current state.
        Returns next step
        :return:
        """
        if not self.next:
            self.next = Off(self.outputs, self.log, self.default_duration_seconds)

    def goto_next(self):
        """
        Rises the state's termination event, which should result in finalizing method on_start,
        which is waiting for the event
        :return: None
        """
        self.next = self._get_next()
        self.termination_event.set()

    def _get_next(self):
        # 111 --> 011 (ALL --> OAK)
        if self.spruce_on and self.oak_sides_on and self.oak_middle_on:
            return On(self.outputs, self.log, self.duration_seconds, self.default_duration_seconds, False, True, True)

        # 011 --> 001 (OAK --> OAK-SIDES)
        elif not self.spruce_on and self.oak_sides_on and self.oak_middle_on:
            return On(self.outputs, self.log, self.duration_seconds, self.default_duration_seconds, False, False, True)

        # 001 --> 010 (OAK-SIDES --> OAK-MIDDLE)
        elif not self.spruce_on and not self.oak_sides_on and self.oak_middle_on:
            return On(self.outputs, self.log, self.duration_seconds, self.default_duration_seconds, False, True, False)

        # 010 --> 100 (OAK-MIDDLE --> SPRUCE)
        elif not self.spruce_on and self.oak_sides_on and not self.oak_middle_on:
            return On(self.outputs, self.log, self.duration_seconds, self.default_duration_seconds, True, False, False)

        # 100 --> 111 (SPRUCE --> ALL)
        elif self.spruce_on and not self.oak_sides_on and not self.oak_middle_on:
            return On(self.outputs, self.log, self.duration_seconds, self.default_duration_seconds, True, True, True)

        else:
            return Off(self.outputs, self.log, self.default_duration_seconds)


class IlluminationSingleStepThread(Thread):
    """
    This class represents the thread realizing single step in the flow
    """
    def __init__(self, executing_state: IlluminationState):
        Thread.__init__(self)
        self.executing_state = executing_state

    def run(self):
        self.executing_state.on_start()


class LightsControllerServiceThread(Thread):
    """
    Class managing the process of executing flow of turning on and off the lights
    """
    def __init__(self, exit_event: Event, outputs: Outputs, log: Logger, default_duration_seconds: int):
        Thread.__init__(self)
        self._exit_event = exit_event
        self._self_exit_event = Event()
        self.current_state = Off(outputs, log, default_duration_seconds)

    def run(self):
        while not self._exit_event.is_set():
            self.current_state = self.wait_for(self.current_state)

    def wait_for(self, i_state: IlluminationState) -> IlluminationState:
        single_step_thread = IlluminationSingleStepThread(i_state)
        single_step_thread.start()
        while True:
            single_step_thread.join(1)
            if not single_step_thread.is_alive():
                break
            elif self._exit_event.is_set() or self._self_exit_event.is_set():
                single_step_thread.executing_state.termination_event.set()

        return i_state.next

    def interrupt(self):
        self._self_exit_event.set()


class LightsControllerService(Service):
    def provideName(self) -> str:
        return "BHS.LightsController"

    def __init__(self):
        Service.__init__(self)
        # read config
        section = 'LIGHTS'
        self.evaluation_period = self.configuration.getIntConfigValue(
            section=section,
            parameter='evaluation-period',
            default=10*60)
        self.button_off_threshold = self.configuration.getFloatConfigValue(
            section=section,
            parameter='button-off-threshold',
            default=3.0)

        self.default_duration_seconds = self.configuration.getIntConfigValue(
            section=section,
            parameter='default-illumination-duration',
            default=2*60*60)

        pin_signal_led = self.configuration.getIntConfigValue(
            section=section,
            parameter='pin-signal-led')
        pin_light_spruce = self.configuration.getIntConfigValue(
            section=section,
            parameter='pin-light-spruce')
        pin_light_oak_middle = self.configuration.getIntConfigValue(
            section=section,
            parameter='pin-light-oak-middle')
        pin_light_oak_sides = self.configuration.getIntConfigValue(
            section=section,
            parameter='pin-light-oak-sides')
        pin_button = self.configuration.getIntConfigValue(
            section=section,
            parameter='pin-button')

        self.auto_off_time_sun_thu = self.configuration.getTimeConfigValue(
            section=section,
            parameter='auto-off-time-sunday-to-thursday', default='22:15')

        self.auto_off_time_fri_sat = self.configuration.getTimeConfigValue(
            section=section,
            parameter='auto-off-time-friday-to-saturday', default='23:00')

        self.auto_on_seconds_after_sunset = self.configuration.getIntConfigValue(
            section=section,
            parameter='auto-on-minutes-after-sunset',
            default=30) * 60

        self.outputs = Outputs(pin_light_spruce, pin_light_oak_middle, pin_light_oak_sides, pin_signal_led)
        self.button = StatelessButton(pin_button, self.button_pressed)
        self._thread = LightsControllerServiceThread(self._exit_event, self.outputs, self.log,
                                                     self.default_duration_seconds)
        self.rest_app.add_url_rule('/', 'current_state', self.get_current_state_for_rest)
        self.rest_app.add_url_rule('/on', 'light', self.turn_em_on_via_rest)
        self.rest_app.add_url_rule('/off', 'darkness', self.turn_em_off_via_rest)

    def auto_on(self) -> bool:
        return (datetime.now() - SunsetCalculator().sunset()).total_seconds() > self.auto_on_seconds_after_sunset
        # TODO add also checking the luminosity sensor

    def auto_off_in_seconds(self) -> int:
        now = datetime.now()
        tme = self.auto_off_time_fri_sat \
            if now.isoweekday() == 5 or now.isoweekday() == 6 else self.auto_off_time_sun_thu
        secs = int((now.replace(hour=tme.hour, minute=tme.minute, second=tme.second)-now).total_seconds())

        return secs if secs > 0 else None

    def main(self) -> float:
        """
        One iteration of main loop of the service. Obligated to return sleep time in seconds
        This method will be executed each X seconds (config) and evaluate whether the lightning is needed.
        """
        if not self._thread.is_alive():
            self.log.info("BHS Lights Controller system is starting")
            self.log.info(str(self.outputs))
            self.log.info(str(self.button))
            self._thread.start()

        auto_on = self.auto_on()
        auto_off_s = self.auto_off_in_seconds()
        if self._thread.current_state.is_idle() and auto_on and auto_off_s:
            self.turn_em_on(auto_off_s)

        self._thread.current_state.operational_signal()

        return self.evaluation_period

    def button_pressed(self, duration_in_seconds: float):
        if duration_in_seconds > self.button_off_threshold:
            self.log.info(f"Received OFF (button pressed for {duration_in_seconds} seconds, "
                          f"more than the threshold: {self.button_off_threshold})")
            self._thread.current_state.turn_off()
        else:
            self.log.info(f"Received NEXT (button pressed for {duration_in_seconds}, "
                          f"less than the OFF threshold: {self.button_off_threshold})")
            self._thread.current_state.goto_next()

    def cleanup(self):
        self.button.close()
        self._thread.interrupt()
        self._thread.join()

    def get_current_state_for_rest(self):
        return jsonify({"state": self._thread.current_state.to_json()})

    def turn_em_on(self, duration: int = None):
        self._thread.current_state.goto(
            On(self.outputs, self.log, duration, self.default_duration_seconds, True, True, True))

    def turn_em_off(self):
        self._thread.current_state.goto(Off(self.outputs, self.log, self.default_duration_seconds))

    def turn_em_on_via_rest(self):
        self.turn_em_on()
        return self.get_current_state_for_rest()

    def turn_em_off_via_rest(self):
        self.turn_em_off()
        return self.get_current_state_for_rest()


if __name__ == '__main__':
    ServiceRunner(LightsControllerService).run()
    exit()
