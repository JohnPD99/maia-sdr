from amaranth import *
import amaranth.back.verilog
import numpy as np
from .pluto_platform import PlutoPlatform


class Radiometer_control(Elaboratable):
    """Radiometer Control

    This module is used for controlling the radiometer. It has two modes: Sweep mode and normal mode. In sweep mode it sweeps through all port selections and frequency selections.

    Parameters
    ----------
    Attributes
    ----------
    """
    def __init__(self):
        self.clken = Signal()
        self.integration_done = Signal()
        self.rf_sw = Signal(3)
        self.gpio_ctl = Signal(4)
        self.sweep_mode = Signal()
        self.port_select = Signal(2)
        self.freq_select = Signal(4)
        self.lpf_select = Signal()
        self.abort = Signal()

        # Internal Signals
        self.selection_mask = Signal(5)
        self.sweep_mode_synq = Signal()
        self.first = Signal(1, reset=1)
        


    def elaborate(self, platform):
        m = Module()

        # need to synchronise sweep mode        
        m.d.sync += self.sweep_mode_synq.eq(self.sweep_mode)


        with m.If(self.sweep_mode_synq):
            with m.If(self.clken):
                with m.If(self.integration_done):
                    # if an integration is done, we send out an abort (adds ~4096 cycles for antenna switch time and frequency switch)
                    m.d.sync += self.abort.eq(1)
                    with m.If(self.first):
                        # if it is the very first measurement, we set the selection mask to 0
                        m.d.sync += self.selection_mask.eq(0)
                        m.d.sync += self.first.eq(0)
                    with m.Else():
                        # if it is not the first measurement, we increment the selection mask
                        m.d.sync += self.selection_mask.eq(self.selection_mask + 1)
                with m.Else():
                    # deselect abort signal (needs to be only one cycle long)
                    m.d.sync += self.abort.eq(0)

            # output the current selection mask correctly
            m.d.comb += [
                self.rf_sw.eq(Cat(self.selection_mask[0:2], self.lpf_select)),
                self.gpio_ctl.eq(Cat(0,self.selection_mask[2:])),
            ]

        with m.Else():
            
            with m.If(self.clken):
                m.d.sync += [
                    self.abort.eq(0),
                    self.first.eq(1)]
                
            # the rf_sw and gpio_ctl are equal to the ones in the sdr registers
            m.d.comb += [
                self.gpio_ctl.eq(self.freq_select),
                self.rf_sw.eq(Cat(self.lpf_select, self.port_select)), 
            ]
            
        return m


if __name__ == '__main__':
    control_unit = Radiometer_control()
    amaranth.cli.main(
        control_unit, ports=[
            control_unit.clken, control_unit.integration_done, control_unit.rf_sw,
            control_unit.gpio_ctl, control_unit.sweep_mode, control_unit.port_select, 
            control_unit.freq_select, control_unit.lpf_select, control_unit.abort],
        platform=PlutoPlatform())

