from abc import ABCMeta, abstractmethod
import six
import numpy as np

# 75 * 365 = 27375
K_INIT_LIVING_DAYS = 27375


class Person(object):
    def __init__(self):
        self.living = K_INIT_LIVING_DAYS
        self.happiness = 0
        self.wealth = 0
        self.fame = 0
        self.living_day = 0

    def live_one_day(self, seek):
        consume_living, happiness, wealth, fame = seek.do_seek_day()
        self.living -= consume_living
        self.happiness += happiness
        self.wealth += wealth
        self.fame += fame
        self.living_day += 1


class BaseSeekDay(six.with_metaclass(ABCMeta, object)):
    def __init__(self):
        self.living_consume = 0
        self.happiness_base = 0
        self.wealth_base = 0
        self.fame_base = 0

        self.living_factor = [0]
        self.happiness_factor = [0]
        self.wealth_factor = [0]
        self.fame_factor = [0]
        self.do_seek_day_cnt = 0
        self._init_self()

    @abstractmethod
    def _gen_living_days(self, *args, **kwargs):
        pass

    def do_seek_day(self):
        if self.do_seek_day_cnt >= len(self.living_factor):
            consume_living = self.living_factor[-1] * self.living_consume
        else:
            consume_living = self.living_factor[self.do_seek_day_cnt] * self.living_consume

        if self.do_seek_day_cnt >= len(self.happiness_factor):
            happiness = self.happiness_factor[-1] * self.happiness_base
        else:
            happiness = self.happiness_factor[self.do_seek_day_cnt] * self.happiness_base

        if self.do_seek_day_cnt >= len(self.wealth_factor):
            wealth = self.wealth_factor[-1] * self.wealth_base
        else:
            wealth = self.wealth_factor[self.do_seek_day_cnt] * self.wealth_base

        if self.do_seek_day_cnt >= len(self.fame_factor):
            fame = self.fame_factor[-1] * self.fame_base
        else:
            fame = self.fame_factor[self.do_seek_day_cnt] * self.fame_base

        self.do_seek_day_cnt += 1
        return consume_living, happiness, wealth, fame


def regular_mm(group):
    return (group - group.min()) / (group.max() - group.min())


class HealthSeekDay(BaseSeekDay):
    def _init_self(self):
        self.living_consume = 1
        self.happiness_base = 1
        self._gen_living_days()

    def _gen_living_days(self):
        days = np.arange(1, 12000)
        living_day = np.sqrt(days)
        self.living_factor = regular_mm(living_day) * 2 - 1
        self.happiness_factor = regular_mm(days)[::-1]


class StockSeekDay(BaseSeekDay):
    def _init_self(self, show=False):
        self.living_consume = 2
        self.happiness_base = 0.5
        self.wealth_base = 10
        self._gen_living_days()

    def _gen_living_days(self):
        days = np.arange(1, 10000)
        living_days = np.sqrt(days)
        self.living_factor = regular_mm(living_days)
        happiness_days = np.power(days, 4)
        self.happiness_factor = regular_mm(happiness_days)[::-1]
        self.wealth_factor = self.living_factor


class FameSeekDay(BaseSeekDay):
    def _init_self(self, show=False):
        self.living_consume = 3
        self.happiness_base = 0.6
        self.fame_base = 10
        self._gen_living_days()

    def _gen_living_days(self):
        days = np.arange(1, 12000)
        living_days = np.sqrt(days)
        self.living_factor = regular_mm(living_days)
        happiness_days = np.power(days, 2)
        self.happiness_factor = regular_mm(happiness_days)[::-1]
        self.fame_factor = self.living_factor


me = Person()
seek_health = HealthSeekDay()
while me.living > 0:
    me.live_one_day(seek_health)
print({'只追求健康长寿快乐活了{}年, 幸福指数{}, 积累财富{}, 名望权力{}'.format(
    round(me.living_day / 365, 2), round(me.happiness, 2), me.wealth, me.fame)})

# me = Person()
# seek_stock = StockSeekDay()
# while me.living > 0:
#     me.live_one_day(seek_stock)
# print({'只追求健康长寿快乐活了{}年, 幸福指数{}, 积累财富{}, 名望权力{}'.format(
#         round(me.living_day/365, 2), round(me.happiness, 2), me.wealth, me.fame)})


# me = Person()
# seek_fame = FameSeekDay()
# while me.living > 0:
#     me.live_one_day(seek_fame)
# print({'只追求健康长寿快乐活了{}年, 幸福指数{}, 积累财富{}, 名望权力{}'.format(
#     round(me.living_day / 365, 2), round(me.happiness, 2), me.wealth, round(me.fame, 2))})


# def my_life(weights):
#     seek_health = HealthSeekDay()
#     seek_stock = StockSeekDay()
#     seek_fame = FameSeekDay()
#     seek_list = [seek_health, seek_stock, seek_fame]
#     me = Person()
#     seek_choice = np.random.choice([0, 1, 2], 80000, p=weights)
#     while me.living > 0:
#         seek_ind = seek_choice[me.living_day]
#         seek = seek_list[seek_ind]
#         me.live_one_day(seek)
#     return round(me.living_day / 365, 2), round(me.happiness, 2), round(me.wealth, 2), round(me.fame, 2)
#
#
# living_day, happiness, wealth, fame = my_life([0.4, 0.3, 0.3])
# print({'只追求健康长寿快乐活了{}年, 幸福指数{}, 积累财富{}, 名望权力{}'.format(
#     living_day, happiness, wealth, fame)})
#
#
# result = []
# for _ in range(2000):
#     weights = np.random.random(3)
#     weights /= np.sum(weights)
#     result.append((weights, my_life(weights)))
#
# # result 中 tuple[1] = my_life 返回的结果, my_life[1][1] = 幸福指数 , 因此 x[1][1]
# sorted_scores = sorted(result, key=lambda x: x[1][2], reverse=True)
# living_day, happiness, wealth, fame = my_life(sorted_scores[0][0])
# print({'只追求健康长寿快乐活了{}年, 幸福指数{}, 积累财富{}, 名望权力{}'.format(
#     living_day, happiness, wealth, fame)})
# print('人生最优权重:追求健康{:.3f}, 追求幸福{:.3f},追求财富{:.3f},追求名望{:.3f}'.format(sorted_scores[0][0][0],
#                                                                    sorted_scores[0][0][1], sorted_scores[0][0][2]))
