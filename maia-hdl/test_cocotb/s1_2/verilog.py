#!/usr/bin/env python3
#
# Copyright (C) 2022-2023 Daniel Estevez <daniel@destevez.net>
#
# This file is part of maia-sdr
#
# SPDX-License-Identifier: MIT
#

from amaranth import *
from amaranth.back.verilog import convert

from maia_hdl.clknx import ClkNxCommonEdge
from maia_hdl.S1_2 import S1_2
from maia_hdl.pluto_platform import PlutoPlatform


class Tb(Elaboratable):
    def __init__(self):
        self.clk3x = 'clk3x'
        self.dut = S1_2(self.clk3x,width_a=47)

    def elaborate(self, platform):
        m = Module()
        m.submodules.dut = self.dut
        m.submodules.common_edge = common_edge = ClkNxCommonEdge(
            'sync', self.clk3x, 3)
        m.d.comb += self.dut.common_edge.eq(common_edge.common_edge)
        return m


def main():
    tb = Tb()
    platform = PlutoPlatform()
    ports = [tb.dut.clken, tb.dut.common_edge, tb.dut.a, tb.dut.out]
    with open('dut.v', 'w') as f:
        f.write('`timescale 1ps/1ps\n')
        f.write(convert(
            tb, name='dut', ports=ports, platform=platform,
            emit_src=False))


if __name__ == '__main__':
    main()
