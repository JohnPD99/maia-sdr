from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform
from .pluto_platform import PlutoPlatform
from .floating_point import MakeCommonExponent
import numpy as np


class S1_2(Elaboratable):
    """Squarer

    Parameters
    ----------
    width_cpwr
    width_cpwr2

    Attributes
    ----------
    cpwr_in: Signal(self.width_cpwr)
        input for cumulated power 
    cpwr2_in: Signal(self.width_cpwr2)
        input for cumulated power^2
    exp_cpwr_in: Signal(self.width_exp)
        input for exponential of cumulated power 
    exp_cpwr2_in: Signal(self.width_exp)
        input for exponential of cumulated power^2 
    cpwr_out

   
    """
    def __init__(self, domain_3x: str, width_a):
        
        self._3x = domain_3x
        self.width_a = width_a
        self.width_out = 2*width_a -1

        
        self.a = Signal(signed(self.width_a), reset_less=True)
       
        self.out = Signal(signed(self.width_out), reset_less=True)
        
        self.clken = Signal()
        self.common_edge = Signal()


    @property
    def delay(self):
        return 5

    def model(self, a):
        return a**2
        
    def elaborate(self, platform):
        if isinstance(platform, XilinxPlatform):
            return self.elaborate_xilinx(platform)
        

        m = Module()

        # S1_squarering
        cpwr_l = Signal(signed(18), reset_less=True)
        cpwr_m = Signal(signed(18), reset_less=True)
        cpwr_h = Signal(signed(self.a-34), reset_less=True)


        # DSPs
        width_h_18 = self.width_a-34+18 - 1
        width_hh = 2*(self.width_a-34)-1

        dsp1_a1 = Signal(signed(18), reset_less=True)
        dsp1_b1 = Signal(signed(18), reset_less=True)
        dsp1_m = Signal(signed(35), reset_less=True)
        dsp1_p = Signal(signed(35), reset_less=True)

        dsp2_a1 = Signal(signed(18), reset_less=True)
        dsp2_b1 = Signal(signed(18), reset_less=True)
        dsp2_m = Signal(signed(width_h_18), reset_less=True)
        dsp2_p = Signal(signed(width_h_18), reset_less=True)

        # adder input signals
        add_ll = Signal(signed(35), reset_less=True)
        add_lm = Signal(signed(35), reset_less=True)
        add_lm_q = Signal(signed(53), reset_less=True)
        add_ll_q = Signal(signed(35), reset_less=True)


        add_mm = Signal(signed(35), reset_less=True)
        add_lh = Signal(signed(width_h_18), reset_less=True)
        add_lh_q = Signal(signed(width_h_18+1), reset_less=True)

        add_hh = Signal(signed(width_hh+16), reset_less=True)
        add_mh = Signal(signed(width_h_18), reset_less=True)
        add_mh_q = Signal(signed(width_h_18), reset_less=True)

        # adder 2 input signals
        add2_a = Signal(signed(54), reset_less=True) # ll_q and lm_q are added together
        add2_b = Signal(signed(width_h_18+36), reset_less=True) # mm and lh_q are added together
        add2_c = Signal(signed(width_hh+69), reset_less=True)

        # adder 3 input signals
        add3_c = Signal(signed(width_hh+69), reset_less=True)
        add3_ab = Signal(signed(width_h_18+37))

        # output signal
        add4_result = Signal(signed(self.width_out))

        # additional signals
        common_edge_q = Signal()
        common_edge_qq = Signal()

        with m.If(self.clken):

            # spliting up cpwr for squaring

            m.d.comb += [
                cpwr_l.eq(Cat(self.a[:17], Const(0,1))),
                cpwr_m.eq(Cat(self.a[17:34], Const(0, 1))),
                cpwr_h.eq(Cat(self.a[34:], Const(0,1))),
            ]

            # DSPs

            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q)
            ]


            # DSP1

            m.d[self._3x] += [
                dsp1_a1.eq(cpwr_m),
                dsp1_b1.eq(cpwr_l),
                dsp1_m.eq(dsp1_a1*dsp1_b1),
                dsp1_p.eq(dsp1_m)
            ]

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    dsp1_a1.eq(cpwr_l),
                    dsp1_b1.eq(cpwr_l),
                    add_ll.eq(dsp1_p)
                ]
            with m.If(common_edge_q):
                m.d[self._3x] += [
                    add_lm.eq(dsp1_p)
                ]
            
            with m.If(common_edge_qq):
                m.d[self._3x] += [
                    dsp1_a1.eq(cpwr_m),
                    dsp1_b1.eq(cpwr_m)
                ]
            
            m.d.sync += [
                add_ll_q.eq(add_ll),
                add_lm_q.eq(add_lm << 18),
                add_mm.eq(dsp1_p)
            ]
            
            # DSP2

            m.d[self._3x] += [
                dsp2_a1.eq(cpwr_h),
                dsp2_b1.eq(cpwr_h),
                dsp2_m.eq(dsp2_a1*dsp2_b1),
                dsp2_p.eq(dsp2_m)
            ]

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    dsp2_a1.eq(cpwr_l),
                    dsp2_b1.eq(cpwr_h),
                    add_lh.eq(dsp2_p)
                ]
            
            with m.If(common_edge_q):
                m.d[self._3x] += [
                    dsp2_a1.eq(cpwr_h),
                    dsp2_b1.eq(cpwr_m),
                    add_mh.eq(dsp2_p)
                ]

            m.d.sync += [
                add_lh_q.eq(add_lh << 1),
                add_mh_q.eq(add_mh),
                add_hh.eq(dsp2_p<<16)
            ]

            # Adder

            m.d.sync += [
                add2_a.eq(add_lm_q + add_ll_q),
                add2_b.eq((add_lh_q + add_mm) << 34),
                add2_c.eq((add_mh_q + add_hh) << 52),
                add3_ab.eq(add2_a+add2_b),
                add3_c.eq(add3_c),
                add4_result.eq(add3_ab + add3_c)
            ]

        return m
    
    def elaborate_xilinx(self, platform):
        print("Todo")
    


if __name__ == '__main__':
    s1_2 = S1_2(47)
    amaranth.cli.main(
        s1_2, ports=[s1_2.a,s1_2.out],   platform=PlutoPlatform())

