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

from maia_hdl.kurtosis_thresholder import Kurtosis_Tresholder
from .amaranth_sim import AmaranthSim
from .common_edge import CommonEdgeTb
import random


class Test_kurtosis_thresholder(AmaranthSim):
    def setUp(self):
        self.width_cpwr = 47
        self.width_cpwr2 = 82
        self.width_exp = 3
        self.nint_width = 5
        self.width_kurt = 5
        self.max_exponent = 4
        self.nint_width_nolog = 10
        
        self.domain_3x = 'clk3x'
        self.kurt_thresh = Kurtosis_Tresholder(self.domain_3x,self.width_cpwr, self.width_cpwr2,self.width_exp,
                                               self.nint_width, self.width_kurt, self.max_exponent, self.nint_width_nolog)
        self.dut = CommonEdgeTb(
            self.kurt_thresh, [(self.domain_3x, 3, 'common_edge')])

    def test_random_inputs(self):
        num_inputs = 10000

        cpwr_in = np.array([random.randrange(0, 2**(self.width_cpwr-1) -1)
            for _ in range(num_inputs)
        ], dtype=object)

        cpwr2_in = np.array([random.randrange(0, 2**(self.width_cpwr2-1) -1)
            for _ in range(num_inputs)
        ], dtype=object)

        exp_cpwr = np.array([random.randrange(0, 1)
            for _ in range(num_inputs)
        ], dtype=object)

        exp_cpwr2 = np.array([random.randrange(0, 1)
            for _ in range(num_inputs)
        ], dtype=object)

        last_int = 1
        ks1 = 2
        ks2 = 3
        log2_nint = 8

        async def bench(ctx):
            for j in range(num_inputs):
                await ctx.tick()
                ctx.set(self.kurt_thresh.clken, 1)
                ctx.set(self.kurt_thresh.cpwr_in, int(cpwr_in[j]))
                ctx.set(self.kurt_thresh.cpwr2_in, int(cpwr2_in[j]))
                ctx.set(self.kurt_thresh.exp_cpwr_in, int(exp_cpwr[j]))
                ctx.set(self.kurt_thresh.exp_cpwr2_in, int(exp_cpwr2[j]))
                ctx.set(self.kurt_thresh.last_int, last_int)
                ctx.set(self.kurt_thresh.kurt_shift_1, ks1)
                ctx.set(self.kurt_thresh.kurt_shift_2, ks2)
                ctx.set(self.kurt_thresh.log2_nint, log2_nint) 

                if j >= self.kurt_thresh.delay:
                    out = ctx.get(self.kurt_thresh.cpwr_out)

                    k = j-self.kurt_thresh.delay 

                    expected = self.kurt_thresh.model(cpwr_in[k], cpwr2_in[k], exp_cpwr[k], exp_cpwr2[k], 
                                                    log2_nint,ks1,ks2,last_int)

                    assert out == expected, \
                        f'out = {out}, expected = {expected} @ cycle = {j}'

        self.simulate(bench, named_clocks={self.domain_3x: 4e-9})


if __name__ == '__main__':
    unittest.main()
