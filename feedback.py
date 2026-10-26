from map import AvaMap
from typing import Callable
class AvaFeedback:
    pass
    on_feedback: Callable

    def start(self):
        # update feedback on loop thread
        pass