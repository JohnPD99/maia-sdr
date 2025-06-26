from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform
from .pluto_platform import PlutoPlatform
from .floating_point import MakeCommonExponent
import numpy as np


class Kurtosis_Tresholder(Elaboratable):
    """Kurtosis_Thresholder

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
    def __init__(self, domain_3x: str, width_cpwr, width_cpwr2, width_exp, nint_width, width_kurt, max_exponent,nint_width_no_log):
        
        self._3x = domain_3x
        self.width_cpwr = width_cpwr
        self.width_cpwr2 = width_cpwr2
        self.width_exp = width_exp
        self.nint_width = nint_width
        self.width_kurt = width_kurt
        self.max_exponent = max_exponent
        self.nint_width_no_log = nint_width_no_log

        self.cpwr_in = Signal(signed(self.width_cpwr), reset_less=True)
        self.cpwr2_in = Signal(signed(self.width_cpwr2), reset_less=True)
        self.cpwr_out = Signal(signed(self.width_cpwr), reset_less=True)
        self.cpwr2_out = Signal(signed(self.width_cpwr2), reset_less=True)
        self.exp_cpwr2_in = Signal(self.width_exp, reset_less=True)
        self.exp_cpwr_in = Signal(self.width_exp, reset_less=True)
        self.exp_cpwr2_out = Signal(self.width_exp, reset_less=True)
        self.exp_cpwr_out = Signal(self.width_exp, reset_less=True)
        self.kurt_shift_1 = Signal(self.width_kurt, reset_less=True)
        self.kurt_shift_2 = Signal(self.width_kurt, reset_less=True)

        self.common_exp = MakeCommonExponent(
            self.width_cpwr, self.width_cpwr2, self.width_exp, self.max_exponent,
            a_power=True, b_power_2=True, b_signed=False, a_signed=False)

        self.log2_nint = Signal(nint_width)
        self.clken = Signal()
        self.common_edge = Signal()
        self.last_int = Signal()


    @property
    def delay(self):
        return 10

    def model(self, cpwr, cpwr2, exp_cpwr, exp_cpwr2, log2_nint, kurt1, kurt2):
        # output (re_a, im_a, re_b, im_b, exponent)
        cpwr_ce, _, cpwr2_ce,_ , exp_ce = self.common_exp.model(cpwr, np.zeros_like(cpwr),exp_cpwr, cpwr2, np.zeros_like(cpwr2),exp_cpwr2)
        S1_2 = cpwr_ce**2
        lower_threshold = ((S1_2*2 - (S1_2>>kurt1) - (S1_2>>kurt2)) < 2**log2_nint*cpwr2_ce)
        upper_threshold = ((S1_2*2 + (S1_2>>kurt1) + (S1_2>>kurt2)) > 2**log2_nint*cpwr2_ce)
        mask = lower_threshold | upper_threshold
        out = cpwr[mask]
        return out
        
    def elaborate(self, platform):
        if isinstance(platform, XilinxPlatform):
            return self.elaborate_xilinx(platform)
        

        m = Module()

        m.submodules.common_exp = common_exp = self.common_exp

        # S1_squarering
        cpwr_l = Signal(signed(18), reset_less=True)
        cpwr_m = Signal(signed(18), reset_less=True)
        cpwr_h = Signal(signed(self.width_cpwr-34), reset_less=True)


        # DSPs
        width_h_18 = self.width_cpwr-34+18 - 1
        width_hh = 2*(self.width_cpwr-34+1)-1

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
        width_add_out = width_hh+70
        add4_result = Signal(signed(width_add_out))

        # kurtshift_signals
        shift_2 = Signal(signed(width_add_out + 1))
        kurt_shift_1 = Signal(signed(width_add_out))
        kurt_shift_2 = Signal(signed(width_add_out))

        # adder 5 input signals
        add5a_a = Signal(signed(width_add_out + 2))
        add5a_b = Signal(signed(width_add_out))
        add5b_a = Signal(signed(width_add_out + 2))
        add5b_b = Signal(signed(width_add_out))

        # adder 5 output signals
        add5a_o = Signal(signed(width_add_out + 3))
        add5b_o = Signal(signed(width_add_out + 3))

        # additional signals
        common_edge_q = Signal()
        common_edge_qq = Signal()

        cpwr2_delay = [Signal(signed(self.width_cpwr2), reset_less=True) for _ in range(self.delay)]
        exp_cpwr2_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]
        exp_cpwr_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]


        cpwr2_mod_delay = [Signal(signed(self.width_cpwr2), reset_less=True) for _ in range(self.delay-4)]

        log2_nint_delay= [Signal(signed(self.width_cpwr2), reset_less=True) for _ in range(self.delay-2)]
        cpwr_delay = [Signal(signed(self.width_cpwr), reset_less=True) for _ in range(self.delay-1)]


        cpwr_mod = Signal(signed(self.width_cpwr), reset_less=True)
        cpwr2_comparison = Signal(signed(self.width_cpwr2 + self.nint_width_no_log))
        cpwr_o_prev = Signal(signed(self.width_cpwr))

        # Entering common exponent module
        
        m.d.comb += [
            common_exp.a_in.eq(self.cpwr_in),
            common_exp.b_in.eq(self.cpwr2_in),
            common_exp.exponent_a_in.eq(self.exp_cpwr_in),
            common_exp.exponent_b_in.eq(self.exp_cpwr2_in),
            common_exp.clken.eq(self.clken)
        ]

        m.d.comb += cpwr2_mod_delay[0].eq(common_exp.b_out)
        m.d.comb += cpwr_mod.eq(common_exp.a_out)

        with m.If(self.clken):

            # Delay pipelines for cpwr, cpwr2, exp_cpwr and exp_cpwr2

            for i in range(1,self.delay-1):
                m.d.sync += cpwr_delay[i].eq(cpwr_delay[i-1])

            for i in range(1,self.delay):
                m.d.sync += [
                    cpwr2_delay[i].eq(cpwr2_delay[i-1]),
                    exp_cpwr_delay[i].eq(exp_cpwr_delay[i-1]),
                    exp_cpwr2_delay[i].eq(exp_cpwr2_delay[i-1]),
                ]
            
            m.d.comb += [
                cpwr_delay[0].eq(self.cpwr_in),
                exp_cpwr_delay[0].eq(self.exp_cpwr_in),
                cpwr2_delay[0].eq(self.cpwr2_in),
                exp_cpwr2_delay[0].eq(self.exp_cpwr2_in),

                self.exp_cpwr_out.eq(exp_cpwr_delay[-1]),
                self.exp_cpwr2_out.eq(exp_cpwr2_delay[-1]),
                self.cpwr2_out.eq(cpwr2_delay[-1])
            ]


        with m.If(self.last_int & self.clken):

            # for bitshifting

            m.d.comb += log2_nint_delay[0].eq(self.log2_nint)

            for i in range(self.delay -2):
                m.d.sync += log2_nint_delay[i].eq(log2_nint_delay[i-1])


            # delay cpwr2_mod
            for i in range(1,self.delay-4):
                m.d.sync += cpwr2_mod_delay[i].eq(cpwr2_mod_delay[i-1])

            # spliting up cpwr for squaring

            m.d.comb += [
                cpwr_l.eq(Cat(cpwr_mod[:17], Const(0,1))),
                cpwr_m.eq(Cat(cpwr_mod[17:34], Const(0, 1))),
                cpwr_h.eq(Cat(cpwr_mod[34:], Const(0,1))),
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

            # Adder 1

            m.d.sync += [
                add2_a.eq(add_lm_q + add_ll_q),
                add2_b.eq((add_lh_q + add_mm) << 34),
                add2_c.eq((add_mh_q + add_hh) << 52),
                add3_ab.eq(add2_a+add2_b),
                add3_c.eq(add3_c),
                add4_result.eq(add3_ab + add3_c)
            ]

            # Kurtosis right shift and left shift

            m.d.comb += [
                shift_2.eq(add4_result << 1),
                kurt_shift_1.eq(add4_result >> self.kurt_shift_1),
                kurt_shift_2.eq(add4_result >> self.kurt_shift_2)
            ]

            m.d.sync += [
                add5a_a.eq(shift_2 + kurt_shift_1),
                add5a_b.eq(kurt_shift_2),
                add5a_o.eq(add5a_a + add5a_b),
                add5b_a.eq(shift_2 - kurt_shift_1),
                add5b_b.eq(kurt_shift_2),
                add5b_o.eq(add5b_a - add5b_b)
            ]

            # Tresholding
            m.d.sync += cpwr2_comparison.eq(cpwr2_mod_delay[-1]<<log2_nint_delay[-1])

            with m.If((add5a_o > cpwr2_comparison) & (add5b_o < cpwr2_comparison)):
                m.d.comb += cpwr_o_prev.eq(cpwr_delay[-1])
            with m.Else:
                m.d.comb += cpwr_o_prev.eq(0b0)
            
            m.d.sync += [
                self.cpwr_out.eq(cpwr_o_prev)
            ]
        
        with m.Else:
            
            m.d.comb += cpwr_o_prev.eq(cpwr_delay[-1])
            m.d.sync += self.cpwr_out.eq(cpwr_o_prev)
        
        return m
    
    def elaborate_xilinx(self, platform):
        print("Todo")
    


if __name__ == '__main__':
    kurt_thresh = Kurtosis_Tresholder(37,81,3,5,5)
    amaranth.cli.main(
        kurt_thresh, ports=[kurt_thresh.cpwr_in, kurt_thresh.cpwr2_in, kurt_thresh.exp_cpwr_in, kurt_thresh.exp_cpwr2_in
                            , kurt_thresh.cpwr_out, kurt_thresh.cpwr2_out, kurt_thresh.exp_cpwr_out, kurt_thresh.exp_cpwr2_out,
                            kurt_thresh.common_edge, kurt_thresh.log2_nint, kurt_thresh.last_int, kurt_thresh.clken, 
                            kurt_thresh.kurt_shift_1, kurt_thresh.kurt_shift_2],   platform=PlutoPlatform())

