import pandas as pd
import unittest
from TradeVolumeStrategy import TradeVolumeStrategy


class TestTradeVolumeStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = TradeVolumeStrategy(day_num=5)

    def test_fit_pick(self):
        kl_pd = pd.DataFrame({'volume': [100, 200, 300, 400, 500, 600]})
        target_symbol = 'AAPL'
        result = self.strategy.fit_pick(kl_pd, target_symbol)
        self.assertTrue(result)

        kl_pd = pd.DataFrame({'volume': [100, 200, 300, 400, 500, 100]})
        target_symbol = 'AAPL'
        result = self.strategy.fit_pick(kl_pd, target_symbol)
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()