import unittest

from app.core.slurm_status import parse_sacct, parse_squeue


class SlurmStatusTests(unittest.TestCase):
    def test_parses_pipe_squeue(self):
        rows = parse_squeue("123|relax|RUNNING|00:04|node01\n124|dos|PENDING|0:00|Priority\n")
        self.assertEqual(rows[0], ("123", "relax", "RUNNING", "00:04", "node01"))
        self.assertEqual(len(rows), 2)

    def test_parses_only_top_level_sacct_ids(self):
        states = parse_sacct(
            "123|COMPLETED|\n123.batch|COMPLETED|\n124|OUT_OF_MEMORY+|\n125_7|FAILED|\n"
        )
        self.assertEqual(states["123"], "COMPLETED")
        self.assertEqual(states["124"], "OUT_OF_MEMORY")
        self.assertEqual(states["125"], "FAILED")


if __name__ == "__main__":
    unittest.main()
