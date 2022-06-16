from gpiozero import Button
from datetime import datetime


class StatelessButton(Button):
    """
    Simple class handling button with no state - the one that is on when you press it,
    but released immediately switches off
    The value added of the class is to report the duration of the press-release activity
    """
    def __init__(self, pin, button_pressed_handler):
        Button.__init__(self, pin, pull_up=None, active_state=False)
        self.when_activated = self.pressed
        self.when_deactivated = self.released
        self.pressed_at = None
        self.button_pressed_handler = button_pressed_handler

    def __str__(self):
        return f"Stateless button configured @ {self.pin}"

    def pressed(self, arg):
        """
        Reaction on button pressed
        :param arg:
        :return:
        """
        self.pressed_at = datetime.now()

    def released(self, arg):
        """
        Reaction on button being released
        :param arg:
        :return:
        """
        duration = (datetime.now() - self.pressed_at).total_seconds() if self.pressed_at is not None else 0
        self.button_pressed_handler(duration, self.pin.number)
        self.pressed_at = None
