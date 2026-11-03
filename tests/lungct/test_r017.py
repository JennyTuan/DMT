import unittest
from tools.lungct.acceptance_r017 import run


class R017Acceptance(unittest.TestCase):
    def test_review_snapshot_export_has_three_ai_one_manual_two_confirmed(self):
        evidence=run()
        self.assertEqual(evidence['export_counts'],dict(studies=1,nodules=2,observations=4))
        self.assertEqual(evidence['A04'],'BLOCKED, NOT RUN')
