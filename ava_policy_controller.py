from typing import Optional

from ava_policy import AvaPolicy, AvaTeleopPolicy
from feedback import AvaFeedback


class AvaPolicyController:
    teleop: Optional[AvaPolicy]
    feedback: Optional[AvaFeedback]
    def __init__(self, policy: Optional[AvaPolicy], feedback: Optional[AvaFeedback]):
        self.policy = policy
        self.feedback = feedback

    def test_loop(self):
        if self.feedback is not None:
            self.feedback.start()
        if self.policy is not None:
            self.policy.start()
        

if __name__ == "__main__":
    a = AvaTeleopPolicy()
    f = AvaFeedback()
    c = AvaPolicyController(
        teleop=a,
        feedback=f
    )
    c.test_loop()
