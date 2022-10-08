import numpy as np

gamblers = 10


def casino(win_rate, win_once=1, loss_once=1, commission=0.01):
    my_money = 1000000
    plat_cnt = 10000000
    commission = commission
    for _ in np.arange(0, plat_cnt):
        w = np.random.binomial(1, win_rate)
        if w:
            my_money += win_once
        else:
            my_money -= loss_once
        my_money -= commission
        if my_money < 0:
            break

    return my_money


# heaven_moneys = [casino(0.5, commission=0) for _ in np.arange(0, gamblers)]
# print(heaven_moneys)


# cheat_moneys = [casino(0.4, commission=0) for _ in np.arange(0, gamblers)]
# print(cheat_moneys)
# 输出内容[-1,-1,-1,-1,-1,-1,-1,-1] 全部陪光


# commission_moneys = [casino(0.5, commission=0.01) for _ in np.arange(0, gamblers)]
# print(commission_moneys)
# 输出内容 [900925.9999068677, 897135.9999068677, 896593.9999068677, 901757.9999068677, 900825.9999068677
# , 904645.9999068677, 898105.9999068677, 899785.9999068677, 897515.9999068677, 900499.9999068677] 都赔钱了

# 模拟股票
# commission_moneys_stock = [casino(0.5, commission=0.01, win_once=1.02, loss_once=0.98) for _ in np.arange(0, gamblers)]
# print(commission_moneys_stock)
# 输出内容 [1098726.0000931323, 1098054.0000931323, 1099450.0000931323, 1096808.0000931323, 1106858.0000931323
# , 1100548.0000931323, 1103426.0000931323, 1098108.0000931323, 1102592.0000931323, 1101418.0000931323]
# 基本都是胜利者，如何能获得多盈利，少亏损那？盈利多保持盈利，亏损多及早止损

commission_moneys_stock = [casino(0.45, commission=0.01, win_once=1.02, loss_once=0.98) for _ in np.arange(0, gamblers)]
print(commission_moneys_stock)
# 提高了每一次的胜率就相应降低总体的胜率
# [104026.00005048967, 101348.0000501521, 96144.00005099754, 105202.00005026866, 96500.00005102609
# , 101510.00005035466, 98800.00005071572, 95952.00005089579, 107472.0000498941, 100600.00005110461]

