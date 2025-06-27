#
# Copyright (C) 2023 Daniel Estevez <daniel@destevez.net>
#
# This file is part of maia-sdr
#
# SPDX-License-Identifier: MIT
#

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, FallingEdge
from cocotb.regression import TestFactory

import random


async def run_test(dut):
    dut.rst.value = 1
    dut.clk3x_rst.value = 1
    dut.clken.value = 1
    dut.a.value = 0
    cocotb.start_soon(Clock(dut.clk, 12, units='ns').start())
    cocotb.start_soon(Clock(dut.clk3x_clk, 4, units='ns').start())
    # We need to wait for 100 ns for GSR to go low
    await ClockCycles(dut.clk, 20)
    dut.rst.value = 0
    dut.clk3x_rst.value = 0

    rising = RisingEdge(dut.clk)
    num_inputs = 1000
    dut_delay = 6  # needs to be one more than the DUT delay @property
    real_in = [random.randrange(0, 2**46-1) for _ in range(num_inputs)]

    for j in range(num_inputs):
        await rising
        dut.a.value = real_in[j]
        if j >= dut_delay:
            val = real_in[j - dut_delay]
            out = dut.out.value.signed_integer
            expected = val**2
            assert out == expected


factory = TestFactory(run_test)
#factory.add_option('peak_detect', [False, True])
factory.generate_tests()
