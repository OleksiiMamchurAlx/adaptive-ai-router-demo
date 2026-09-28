"""Regression checks for the public browser demo's numeric core."""
import unittest

from web.core.experience_store import calculate
from web.core.numeric_validation import validate_numeric


class BrowserNumericCoreTests(unittest.TestCase):
    def test_mean_preserves_small_term_after_large_cancellation(self):
        values = (1e100, 1.0, -1e100)
        # A plain left-to-right sum loses the middle term in this order.
        self.assertEqual(sum(values), 0.0)

        actual = calculate("mean", list(values))
        self.assertAlmostEqual(actual, 1 / 3, places=15)
        self.assertEqual(
            validate_numeric("mean", values, actual),
            (True, "NUMERIC_CONTRACT_ACCEPT"),
        )
        self.assertEqual(
            validate_numeric("mean", values, 0.0),
            (False, "NUMERIC_MISMATCH"),
        )


if __name__ == "__main__":
    unittest.main()
