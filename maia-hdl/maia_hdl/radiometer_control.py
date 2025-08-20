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
        self.sweep_mode = Signal()
        self.selection_reg = Signal(7) # rf_sw + gpio_ctl, (rf_sw = port_select0, port_select1, lpf_select) (gpio_ctl = 0, pinctrl0, pinctrl1, pinctrl2)
        self.selection_ctrl = Signal(7)
        self.selection_ctrl_q = Signal(7)
        self.abort = Signal(1, reset=0)
        # Internal Signals
        self.selection_mask = Signal(5)
        self.selection_mask_q = Signal(5)
        self.first = Signal(1, reset=1)

        self.DELAY_INTEGRATIONS = 1
        self.ABORT_DELAY = 1600 + 4096*(1-self.DELAY_INTEGRATIONS)

        self.abort_cnt = Signal(range(self.ABORT_DELAY+1), reset=self.ABORT_DELAY)


    def elaborate(self, platform):
        m = Module()


        with m.If(self.sweep_mode):
            with m.If(self.integration_done):
                # reset the abort counter
                m.d.sync += self.abort_cnt.eq(self.ABORT_DELAY)
                with m.If(self.first):
                    # if it is the very first measurement, we set the selection mask to 0
                    m.d.sync += [
                        self.selection_mask.eq(0),
                        self.selection_mask_q.eq(0),
                        self.first.eq(0)
                        ]
                with m.Else():
                    # if it is not the first measurement, we increment the selection mask
                    m.d.sync += [
                        self.selection_mask_q.eq(self.selection_mask),
                        self.selection_mask.eq(self.selection_mask + 1),
                        ]
            with m.Else():
                with m.If(self.abort_cnt == 1):
                    m.d.sync += [
                        self.abort_cnt.eq(0),
                        self.abort.eq(1)]
                with m.Elif(self.abort_cnt == 0):
                    m.d.sync += [
                        self.abort_cnt.eq(0),
                        self.abort.eq(0)]
                with m.Else():
                    m.d.sync += self.abort_cnt.eq(self.abort_cnt - 1)
            
            m.d.comb += [
                self.selection_ctrl.eq(Cat(self.selection_mask[0:2], self.selection_reg[2], 0, self.selection_mask[2:])),
                self.selection_ctrl_q.eq(Cat(self.selection_mask_q[0:2], self.selection_reg[2], 0, self.selection_mask_q[2:]))
            ]

        with m.Else():
            
            with m.If(self.clken):
                m.d.sync += [
                    self.first.eq(1),
                    self.abort.eq(0)]
                
            # write back selection_reg
            m.d.comb += [
                self.selection_ctrl.eq(self.selection_reg),
                self.selection_ctrl_q.eq(self.selection_reg)
            ]
           
            
            
        return m


if __name__ == '__main__':
    control_unit = Radiometer_control()
    amaranth.cli.main(
        control_unit, ports=[
            control_unit.clken, control_unit.integration_done,
            control_unit.selection_ctrl, control_unit.selection_ctrl_q, control_unit.sweep_mode,
            control_unit.selection_reg, control_unit.abort],
        platform=PlutoPlatform())

