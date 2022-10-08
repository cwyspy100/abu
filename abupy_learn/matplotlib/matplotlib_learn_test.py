import abupy
from abupy import ABuSymbolPd
import matplotlib.pyplot as plt

# import pandas as pd
# import matplotlib.dates as mdates

abupy.env.enable_example_env_ipython()
tsla_df = ABuSymbolPd.make_kl_df('usTSLA', n_folds=2)
tsla_df.tail()

print(tsla_df.close.index)
print(type(tsla_df.close.index))
print(type(tsla_df.close.values))

# fig, ax = plt.subplots()
# ax.plot_date(tsla_df.close.index, tsla_df.close.values + 10, linestyle='solid')

plt.plot(tsla_df.close.index.to_pydatetime(), tsla_df.close.values + 10, c='g')
plt.xlabel('time')
plt.ylabel('close')
plt.title('TSLA CLOSE')
plt.grid(True)
plt.show()

import matplotlib.finance as mpf

__colorup__ = "red"
__colordown__ = "green"
tsla_part_df = tsla_df[:30]
fig, ax = plt.subplots(figsize=(14, 7))
qutotes = []
for index, (d, o, c, h, l) in enumerate(zip(tsla_part_df.index, tsla_part_df.open, tsla_part_df.close
        , tsla_part_df.high, tsla_part_df.low)):
    d = mpf.date2num(d)
    val = (d, o, c, h, l)
    qutotes.append(val)
mpf.candlestick_ochl(ax, qutotes, width=0.6, colorup=__colorup__, colordown=__colordown__)
ax.autoscale_view()
ax.xaxis_date()
plt.show()
