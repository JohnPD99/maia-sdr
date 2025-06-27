#
# Copyright (C) 2023-2024 John Dornbierer
#
# This file is part of maia-sdr
#
# SPDX-License-Identifier: MIT
#

from amaranth import *
import numpy as np

import unittest

from maia_hdl.S1_2 import S1_2
from .amaranth_sim import AmaranthSim
from .common_edge import CommonEdgeTb
import random


class Test_s1_2(AmaranthSim):
    def setUp(self):
        self.width = 47
        self.domain_3x = 'clk3x'
        self.mult = S1_2(self.domain_3x, self.width)
        self.dut = CommonEdgeTb(
            self.mult, [(self.domain_3x, 3, 'common_edge')])

    def test_random_inputs(self):
        num_inputs = 1000

        real = np.array([random.randrange(0, 2**self.width -1)
            for _ in range(num_inputs)
        ], dtype=object)

        async def bench(ctx):
            for j in range(num_inputs):
                await ctx.tick()
                ctx.set(self.mult.clken, 1)
                ctx.set(self.mult.a, int(real[j]))
                if j >= self.mult.delay:
                    out = ctx.get(self.mult.out) 
                    expected = self.mult.model(int(real[j-self.mult.delay]))
                    assert out == expected, \
                        f'out = {out}, expected = {expected} @ cycle = {j}'
        self.simulate(bench, named_clocks={self.domain_3x: 4e-9})


if __name__ == '__main__':
    unittest.main()
