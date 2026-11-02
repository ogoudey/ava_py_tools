from typing import Optional

from ava_policy import AvaPolicy, AvaTeleopPolicy
from feedback import AvaFeedback

import ava_base as ab

        
class AvaTeleopPolicyController:
    policy: Optional[AvaPolicy]
    feedback: Optional[AvaFeedback]
    
    def __init__(self):
        ava_base = ab.AvaBaseAPI()
        self.policy = AvaTeleopPolicy(ava_base)
        self.feedback = AvaFeedback(ava_base)

    def test_loop(self):
        if self.feedback is not None:
            self.feedback.start()
        if self.policy is not None:
            self.policy.start()
        if self.feedback is not None:
            self.feedback.join()
if __name__ == "__main__":
    
    c = AvaTeleopPolicyController()
    c.test_loop()
