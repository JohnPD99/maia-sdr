#
# Copyright (C) 2022-2024 Daniel Estevez <daniel@destevez.net>
#
# This file is part of maia-sdr
#
# SPDX-License-Identifier: MIT
#

from amaranth import *
import numpy as np
import unittest

from maia_hdl.cpwr2TR import Cpwr2TR
from .amaranth_sim import AmaranthSim
from .common_edge import CommonEdgeTb


class TestCpwrPeak(AmaranthSim):
    def setUp(self):
        self.width = 16
        self.real_width = 66
        self.domain_3x = 'clk3x'

    def test_random_inputs(self):
        for truncate in [0, 4]:
            for real_shift in [8, 16]:
                with self.subTest(  truncate=truncate,
                                    real_shift=real_shift):
                    self.cpwr = Cpwr2TR(
                        self.domain_3x, width=self.width,
                        real_width=self.real_width, real_shift=real_shift,
                        truncate=truncate)
                    self.dut = CommonEdgeTb(
                        self.cpwr, [(self.domain_3x, 3, 'common_edge')])
                    self.common_random_inputs()

    def common_random_inputs(self, vcd=None):
        num_inputs = 1000
        re = np.random.randint(-2**(self.width-1), 2**(self.width-1),
                               size=num_inputs)
        im = np.random.randint(-2**(self.width-1), 2**(self.width-1),
                               size=num_inputs)
        real = np.random.randint(
            -2**(self.real_width-1), 2**(self.real_width-1),
            size=num_inputs)

        async def bench(ctx):
            for j in range(num_inputs):
                await ctx.tick()
                ctx.set(self.cpwr.clken, 1)
                ctx.set(self.cpwr.re_in, int(re[j]))
                ctx.set(self.cpwr.im_in, int(im[j]))
                ctx.set(self.cpwr.real_in, int(real[j]))
                if j >= self.cpwr.delay:
                    out = ctx.get(self.cpwr.out)
                    k = j - self.cpwr.delay
                    expected = self.cpwr.model(
                        re[k], im[k], real[k])
                    assert out == expected, \
                        f'out = {out}, expected = {expected} @ cycle = {j}'
        self.simulate(bench, vcd=vcd, named_clocks={self.domain_3x: 4e-9})


if __name__ == '__main__':
    unittest.main()
