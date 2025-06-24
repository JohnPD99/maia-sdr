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
    dut.re_in.value = 0
    dut.im_in.value = 0
    dut.real_in.value = 0
    cocotb.start_soon(Clock(dut.clk, 12, units='ns').start())
    cocotb.start_soon(Clock(dut.clk3x_clk, 4, units='ns').start())
    # We need to wait for 100 ns for GSR to go low
    await ClockCycles(dut.clk, 20)
    dut.rst.value = 0
    dut.clk3x_rst.value = 0

    rising = RisingEdge(dut.clk)
    num_inputs = 1000
    dut_delay = 8  # needs to be one more than the DUT delay @property

    re_in, im_in = (
        [0 for _ in range(num_inputs)]
        for _ in range(2))
    real_in = [random.randrange(-2**80, 2**80-1) for _ in range(num_inputs)]

    for j in range(num_inputs):
        await rising
        dut.re_in.value = re_in[j]
        dut.im_in.value = im_in[j]
        dut.real_in.value = real_in[j]

        if j >= dut_delay:
            a = re_in[j - dut_delay]
            b = im_in[j - dut_delay]
            c = real_in[j - dut_delay]
            out = dut.out.value.signed_integer
            result = ((a**2 + b**2)**2 + c<<1)>>1
            print(result)
            print(out)
            assert out == result

def min_signed_bitwidth(x: int) -> int:
    """Determine the minimum bit width needed to represent x as a signed integer."""
    if x == 0:
        return 1
    elif x > 0:
        return x.bit_length() + 1  # Add sign bit
    else:
        return (-x).bit_length() + 1

def sign_extend(value: int, from_bits: int, to_bits: int = 81) -> int:
    """Sign-extend a signed integer from from_bits to to_bits."""
    sign_bit = 1 << (from_bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)



factory = TestFactory(run_test)
#factory.add_option('peak_detect', [False, True])
factory.generate_tests()
