from abupy import AbuFactorBuyBase, AbuFactorBuyBreak
from abupy import AbuBenchmark
from abupy import AbuCapital, AbuPickTimeWorker, AbuKLManager
import abupy

abupy.env.enable_example_env_ipython()

buy_factors = [{'xd': 60, 'class': AbuFactorBuyBreak}, {'xd': 42, 'class': AbuFactorBuyBreak}]
benchmark = AbuBenchmark()
capital = AbuCapital(1000000, benchmark)
kl_pd_manger = AbuKLManager(benchmark, capital)
kl_pd = kl_pd_manger.get_pick_time_kl_pd('usTSLA')
abu_worker = AbuPickTimeWorker(capital, kl_pd, buy_factors, None)

abu_worker.fit()
