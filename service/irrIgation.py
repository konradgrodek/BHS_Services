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
                 pin_pump: int,
                 pin_pump_led: int,
                 pin_inner_valve: int,
                 pin_inner_valve_led: int,
                 pin_outer_valve: int,
                 pin_outer_valve_led: int):
        """
        Constructor. Initializes the class members responsible for controlling output devices.
        May throw ugly exceptions if the pins are already allocated by other systems.
        """
        self.led_pump = LED(pin_pump_led, initial_value=False)
        self.led_inner_circuit = LED(pin_inner_valve_led, initial_value=False)
        self.led_outer_circuit = LED(pin_outer_valve_led, initial_value=False)
        self.pump = OutputDevice(pin_pump, active_high=False, initial_value=False)
        self.inner_circuit = OutputDevice(pin_inner_valve, active_high=False, initial_value=False)
        self.outer_circuit = OutputDevice(pin_outer_valve, active_high=False, initial_value=False)

    def __str__(self):
        return f"Irrigation output configured @ pump: {self.pump.pin}-{self.led_pump.pin}, " \
               f"inner circuit: {self.inner_circuit.pin}-{self.led_inner_circuit.pin}, " \
               f"outer circuit: {self.outer_circuit.pin}-{self.led_outer_circuit.pin}"


class IrrigationConfiguration:
    def __init__(self):
        self.default_irrigation_duration_for_inner_section = None
        self.default_irrigation_duration_for_outer_section = None
        self.irrigation_duration_for_inner_section = None
        self.irrigation_duration_for_outer_section = None
        self.pump_start_delay = None
        self.pump_stop_delay = None

    def get_duration_for_inner_section(self) -> int:
        return self.irrigation_duration_for_inner_section if self.irrigation_duration_for_inner_section \
            else self.default_irrigation_duration_for_inner_section

    def get_duration_for_outer_section(self) -> int:
        return self.irrigation_duration_for_outer_section if self.irrigation_duration_for_outer_section \
            else self.default_irrigation_duration_for_outer_section


class IrrigationState:
    """
    Base class of all possible states of the system
    """
    def __init__(self, outputs: Outputs, logger: Logger, config: IrrigationConfiguration):
        """
        Initializes the state using provided entities collecting output devices, configuration and logging
        :param outputs: collects all output devices
        :param logger: provides interface for logging
        :param config: encapsulates configuration
        """
        self.outputs = outputs
        self.log = logger
        self.config = config
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

    def goto_next(self):
        """
        Rises the state's termination event, which should result in finalizing method on_start,
        which is waiting for the event
        :return: None
        """
        self.termination_event.set()

    def turn_off(self):
        """
        Sets Idle State as next state and raises event that ends current state
        :return:
        """
        self.next = IrrigationIdle(self.outputs, self.log, self.config)
        self.termination_event.set()


class IrrigationIdle(IrrigationState):
    def __init__(self, outputs: Outputs, logger: Logger, config: IrrigationConfiguration):
        IrrigationState.__init__(self, outputs, logger, config)

    def __str__(self):
        return "Irrigation idle state"

    def is_idle(self) -> bool:
        """
        Yes, I'm idle!
        :return: True
        """
        return True

    def on_start(self):
        """
        The idle state is designed to do nothing. Well, maybe not simply like that...
        Will do some logging and then anchor to an event that suppose to wake us up.
        :return: really nothing
        """
        self.log.info("Entering idle state. Awaiting orders!")
        self.termination_event.wait()
        self.on_stop()

    def on_stop(self):
        """
        If there is no other state planned as next one, the Inner Section is set as next step
        :return:
        """
        if not self.next:
            self.next = IrrigationInnerSection(self.outputs, self.log, self.config)


class IrrigationInProgress(IrrigationState):
    """
    Abstract class representing state of irrigation in progress.
    """
    def __init__(self, outputs: Outputs, logger: Logger, config: IrrigationConfiguration):
        IrrigationState.__init__(self, outputs, logger, config)

    def is_idle(self) -> bool:
        """
        No, I'm not lazy.
        :return: False
        """
        return False

    def _pump_on(self):
        """
        Turns the pump on. Pay attention! Any delay between opening valves and running the pump shall be done elsewhere!
        :return:
        """
        self.outputs.pump.on()
        self.outputs.led_pump.on()
        self.log.info("Pump is ON")

    def _pump_off(self):
        """
        Switches the pump off. No delay is implemented here, effect is imminent
        :return:
        """
        self.outputs.pump.off()
        self.outputs.led_pump.off()
        self.log.info("Pump is OFF")

    def _valve_on(self):
        """
        The method opens valve (inner or outer, depending on implementation) and switches on associated LED
        :return:
        """
        raise NotImplementedError()

    def _valve_off(self):
        """
        The method closes valve (inner or outer, depending on implementation) and switches off associated LED
        :return:
        """
        raise NotImplementedError()

    def _irrigation_duration(self) -> int:
        """
        Returns duration of irrigation
        :return: duration of irrigation in seconds
        """
        raise NotImplementedError()

    def _get_next(self) -> IrrigationState:
        """
        Goes to next step. Default implementation goes to Idle.
        :return: IrrigationState: next state
        """
        return IrrigationIdle(self.outputs, self.log, self.config)

    def on_start(self):
        self._valve_on()
        self.termination_event.wait(self.config.pump_start_delay)
        if not self.termination_event.is_set():
            self._pump_on()
            self.termination_event.wait(self._irrigation_duration())
        self.on_stop()

    def on_stop(self):
        self._pump_off()
        time.sleep(self.config.pump_stop_delay)
        self._valve_off()

        if not self.next:
            self.next = self._get_next()


class IrrigationInnerSection(IrrigationInProgress):
    def __init__(self, outputs: Outputs, logger: Logger, config: IrrigationConfiguration):
        IrrigationInProgress.__init__(self, outputs, logger, config)

    def __str__(self):
        return f"Irrigating inner section. " \
               f"Will do that for {self._irrigation_duration()} seconds"

    def _valve_on(self):
        self.outputs.inner_circuit.on()
        self.outputs.led_inner_circuit.on()
        self.log.info("Inner section valve is OPEN")

    def _valve_off(self):
        self.outputs.inner_circuit.off()
        self.outputs.led_inner_circuit.off()
        self.log.info("Inner section valve is CLOSED")

    def _irrigation_duration(self) -> int:
        return self.config.get_duration_for_inner_section()

    def _get_next(self) -> IrrigationState:
        return IrrigationOuterSection(self.outputs, self.log, self.config)


class IrrigationOuterSection(IrrigationInProgress):
    def __init__(self, outputs: Outputs, logger: Logger, config: IrrigationConfiguration):
        IrrigationInProgress.__init__(self, outputs, logger, config)

    def __str__(self):
        return f"Irrigating outer section. " \
               f"Will do that for {self._irrigation_duration()} seconds"

    def _valve_on(self):
        self.outputs.outer_circuit.on()
        self.outputs.led_outer_circuit.on()
        self.log.info("Outer section valve is OPEN")

    def _valve_off(self):
        self.outputs.outer_circuit.off()
        self.outputs.led_outer_circuit.off()
        self.log.info("Outer section valve is CLOSED")

    def _irrigation_duration(self) -> int:
        return self.config.get_duration_for_outer_section()


class IrrigationSingleStepThread(Thread):
    """
    This class represents the thread realizing single step in the irrigation cycle
    """
    def __init__(self, executing_state: IrrigationState):
        Thread.__init__(self)
        self.executing_state = executing_state

    def run(self):
        self.executing_state.on_start()


class IrrigationServiceThread(Thread):
    """
    Class representing for single
    """
    def __init__(self, exit_event: Event, outputs: Outputs, log: Logger, irrigation_config: IrrigationConfiguration):
        Thread.__init__(self)
        self._exit_event = exit_event
        self._self_exit_event = Event()
        self.current_state = IrrigationIdle(outputs, log, irrigation_config)

    def run(self):
        while not self._exit_event.is_set():
            self.current_state = self.wait_for(self.current_state)

    def wait_for(self, irrigation_state: IrrigationState) -> IrrigationState:
        single_step_thread = IrrigationSingleStepThread(irrigation_state)
        single_step_thread.start()
        while True:
            single_step_thread.join(1)
            if not single_step_thread.is_alive():
                break
            elif self._exit_event.is_set() or self._self_exit_event.is_set():
                single_step_thread.executing_state.termination_event.set()

        return irrigation_state.next

    def interrupt(self):
        self._self_exit_event.set()


class IrrigationService(Service):
    def provideName(self) -> str:
        return "BHS.Irrigation"

    def __init__(self):
        Service.__init__(self)
        # read config
        irrigation_section = 'IRRIGATION'
        self.evaluation_period = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='evaluation-period',
            default=10*60)
        self.button_off_threshold = self.configuration.getFloatConfigValue(
            section=irrigation_section,
            parameter='button-off-threshold',
            default=3.0)

        self.irrigation_config = IrrigationConfiguration()
        self.irrigation_config.default_irrigation_duration_for_inner_section = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='default-inner-section-irrigation-duration')
        self.irrigation_config.default_irrigation_duration_for_outer_section = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='default-outer-section-irrigation-duration')
        self.irrigation_config.pump_start_delay = self.configuration.getFloatConfigValue(
            section=irrigation_section,
            parameter='pump-start-delay',
            default=2.0)
        self.irrigation_config.pump_stop_delay = self.configuration.getFloatConfigValue(
            section=irrigation_section,
            parameter='pump-stop-delay',
            default=0.5)

        pin_pump = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-pump')
        pin_pump_led = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-pump-led')
        pin_valve_inner = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-valve-inner')
        pin_valve_inner_led = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-valve-inner-led')
        pin_valve_outer = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-valve-outer')
        pin_valve_outer_led = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-valve-outer-led')

        self.outputs = Outputs(pin_pump,
                               pin_pump_led,
                               pin_valve_inner,
                               pin_valve_inner_led,
                               pin_valve_outer,
                               pin_valve_outer_led)

        pin_button = self.configuration.getIntConfigValue(
            section=irrigation_section,
            parameter='pin-button')
        self.button = StatelessButton(pin_button, self.button_pressed)
        self._thread = IrrigationServiceThread(self._exit_event, self.outputs, self.log, self.irrigation_config)

    def main(self) -> float:
        """
        One iteration of main loop of the service. Obligated to return sleep time in seconds
        This method will be executed each X seconds (config) and evaluate whether the irrigation is needed.
        """
        if not self._thread.is_alive():
            self.log.info("BHS Irrigation system is starting")
            self.log.info(str(self.outputs))
            self.log.info(str(self.button))
            self._thread.start()

        # TODO for now the process just reacts on button
        # I have to add support for some sort of scheduling
        # scenario: this method is executed each 10 minutes and checks various conditions (was it raining? temperature?
        # soil moisturises? etc) in order to start - or not irrigation - and to define how long should it take

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


if __name__ == '__main__':
    ServiceRunner(IrrigationService).run()
    exit()
