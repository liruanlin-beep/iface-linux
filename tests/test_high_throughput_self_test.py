import unittest

from app.core.high_throughput_self_test import run_high_throughput_self_test


class HighThroughputSelfTestTests(unittest.TestCase):
    def test_local_control_plane_stress_test_passes(self):
        report = run_high_throughput_self_test(workflows=6, max_inflight=3)
        self.assertTrue(report.passed)
        self.assertEqual(report.duplicate_tasks_prevented, 6)
        self.assertLessEqual(report.max_inflight_observed, 3)
        self.assertTrue(report.concurrent_claims_unique)
        self.assertEqual(report.stale_claims_recovered, 2)


if __name__ == "__main__":
    unittest.main()
