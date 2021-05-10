from collections import deque
from core.bean import Tendency
from scipy import stats


class TendencyChecker:
    """
    Implements very basic approach to detecting tendency.
    Stores N last observations divided into two parts: older (80%) and newer (20%)
    Tendency is rising if the average of "older" observations is significantly lower then "newer"
    """

    def __init__(self, observations_window: int, threshold_perc: float = 0.5):
        """
        Initializes the basic tendency checker
        :param observations_window: number of observations that shall be taken into consideration
        :param threshold_perc: defines whether the difference between previous and current observations is significant
        """
        self.previous_readings = deque(maxlen=int(observations_window / 5))
        self.current_readings = deque(maxlen=observations_window - int(observations_window / 5))
        self.threshold = threshold_perc
        self.current_tendency = Tendency.STEADY
        self.current_mean = 0.0
        self.previous_mean = 0.0
        self.current_diff_perc = 0.0

    def tendency(self, observation) -> Tendency:
        """
        Returns current tendency of observations
        :param observation:
        :return:
        """
        if len(self.current_readings) == self.current_readings.maxlen:
            # most recent at the right
            self.previous_readings.append(self.current_readings.popleft())

        self.current_readings.append(observation)

        self.current_mean = stats.tmean(self.current_readings)
        self.previous_mean = self.current_mean if len(self.previous_readings) == 0 \
            else stats.tmean(self.previous_readings)

        self.current_diff_perc = 100 * (self.current_mean - self.previous_mean) / observation

        self.current_tendency = Tendency.RISING if self.current_diff_perc - self.threshold > 0 \
            else Tendency.FALLING if self.current_diff_perc + self.threshold < 0 \
            else Tendency.STEADY

        return self.current_tendency

    def verbose(self) -> str:
        return f'{self.current_tendency} ' \
               f'[{len(self.previous_readings) + len(self.current_readings)}] ' \
               f'{self.previous_mean:.5} --> {self.current_mean:.5}'
