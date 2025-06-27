from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform
from .pluto_platform import PlutoPlatform
from .floating_point import MakeCommonExponent
from .S1_2 import S1_2
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

        #test signals
        self.max_widths = max(self.width_cpwr2 + self.nint_width_no_log, 2*self.width_cpwr +2)
        self.test = Signal(signed( self.max_widths), reset_less=True)
        self.test2 = Signal(signed( self.max_widths), reset_less=True)
        self.test3 = Signal(signed( self.max_widths), reset_less=True)
        self.test4 = Signal(signed( self.max_widths), reset_less=True)
        self.test5 = Signal(signed( self.max_widths), reset_less=True)

        self.common_exp = MakeCommonExponent(
            self.width_cpwr, self.width_cpwr2, self.width_exp, self.max_exponent,
            a_power=True, b_power_2=True, b_signed=False, a_signed=False)
        
        self.s1_2 = S1_2(self._3x, self.width_cpwr)

        self.log2_nint = Signal(unsigned(nint_width))
        self.clken = Signal()
        self.common_edge = Signal()
        self.last_int = Signal()


    @property
    def delay(self):
        return self.common_exp.delay + 8

    def model(self, cpwr, cpwr2, exp_cpwr, exp_cpwr2, log2_nint, kurt1, kurt2, last_int):
        if not last_int:
            return cpwr
        else:
            cpwr_ce, _, cpwr2_ce,_ , exp_ce = self.common_exp.model2(cpwr, 0,exp_cpwr, cpwr2, 0,exp_cpwr2)
            cpwr_ce_2 = self.s1_2.model(cpwr_ce)
            upper =  (cpwr_ce_2)*2 + (cpwr_ce_2)//(2**kurt1) + (cpwr_ce_2)//(2**kurt2)
            lower =  (cpwr_ce_2)*2 - (cpwr_ce_2)//(2**kurt1) - (cpwr_ce_2)//(2**kurt2)
            val = cpwr2_ce<<log2_nint
            
            mask = ((val>lower) & (val<upper))
            return mask*cpwr
        
    def elaborate(self, platform):
        m = Module()

        m.submodules.common_exp = common_exp = self.common_exp
        m.submodules.s1_2 = s1_2 = self.s1_2

        # DSPs

        # output signal
        width_s1_2_out = 2*self.width_cpwr -1
        add4_result = Signal(signed(width_s1_2_out))

        # kurtshift_signals
        shift_2 = Signal(signed(width_s1_2_out + 1))
        kurt_shift_1 = Signal(signed(width_s1_2_out))
        kurt_shift_2 = Signal(signed(width_s1_2_out))

        # adder 5 input signals
        add5a_a = Signal(signed(width_s1_2_out + 2))
        add5a_b = Signal(signed(width_s1_2_out))
        add5b_a = Signal(signed(width_s1_2_out + 2))
        add5b_b = Signal(signed(width_s1_2_out))

        max_width = max(self.width_cpwr2 + self.nint_width_no_log, width_s1_2_out + 3)

        # adder 5 output signals
        add5a_o = Signal(signed(max_width))
        add5b_o = Signal(signed(max_width))

        cpwr2_delay = [Signal(signed(self.width_cpwr2), reset_less=True) for _ in range(self.delay)]
        exp_cpwr2_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]
        exp_cpwr_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]


        cpwr2_mod_delay = [Signal(signed(self.width_cpwr2), reset_less=True) for _ in range(self.delay-4)]

        log2_nint_delay= [Signal(unsigned(self.nint_width+1), reset_less=True) for _ in range(self.delay-2)]
        cpwr_delay = [Signal(signed(self.width_cpwr), reset_less=True) for _ in range(self.delay-1)]


        
        cpwr2_comparison = Signal(signed(max_width))
        cpwr_o_prev = Signal(signed(self.width_cpwr))

        # Entering common exponent module
        
        m.d.comb += [
            common_exp.a_in.eq(self.cpwr_in),
            common_exp.b_in.eq(self.cpwr2_in),
            common_exp.exponent_a_in.eq(self.exp_cpwr_in),
            common_exp.exponent_b_in.eq(self.exp_cpwr2_in),
            common_exp.clken.eq(self.clken),
        ]


        m.d.sync += cpwr2_mod_delay[0].eq(common_exp.b_out)

        m.d.comb += [
            s1_2.clken.eq(1),
            s1_2.a.eq(common_exp.a_out),
            s1_2.common_edge.eq(self.common_edge),
            add4_result.eq(s1_2.out)
        ]

        with m.If(self.clken):

            # Delay pipelines for cpwr, cpwr2, exp_cpwr and exp_cpwr2

            for i in range(self.delay-1):
                m.d.sync += cpwr_delay[i].eq(cpwr_delay[i-1])

            for i in range(1,self.delay):
                m.d.sync += [
                    cpwr2_delay[i].eq(cpwr2_delay[i-1]),
                    exp_cpwr_delay[i].eq(exp_cpwr_delay[i-1]),
                    exp_cpwr2_delay[i].eq(exp_cpwr2_delay[i-1]),
                ]

            m.d.sync += [
                cpwr_delay[0].eq(self.cpwr_in),
                exp_cpwr_delay[0].eq(self.exp_cpwr_in),
                cpwr2_delay[0].eq(self.cpwr2_in),
                exp_cpwr2_delay[0].eq(self.exp_cpwr2_in),
            ]
            
            m.d.comb += [
                self.exp_cpwr_out.eq(exp_cpwr_delay[-1]),
                self.exp_cpwr2_out.eq(exp_cpwr2_delay[-1]),
                self.cpwr2_out.eq(cpwr2_delay[-1])
            ]


        with m.If(self.last_int & self.clken):

            # for bitshifting

            m.d.sync += log2_nint_delay[0].eq(self.log2_nint)

            for i in range(1,self.delay -2):
                m.d.sync += log2_nint_delay[i].eq(log2_nint_delay[i-1])


            # delay cpwr2_mod
            for i in range(1,self.delay-4):
                m.d.sync += cpwr2_mod_delay[i].eq(cpwr2_mod_delay[i-1])


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

            m.d.comb += self.test.eq(((add5a_o > cpwr2_comparison) ))
            m.d.comb += self.test2.eq((add5b_o < cpwr2_comparison))

            m.d.comb += self.test3.eq((cpwr2_comparison))
            m.d.comb += self.test4.eq((add5a_o))
            m.d.comb += self.test5.eq((add5b_o))

            with m.If((add5a_o > cpwr2_comparison) & (add5b_o < cpwr2_comparison)):
                m.d.comb += cpwr_o_prev.eq(cpwr_delay[-1])
            with m.Else():
                m.d.comb += cpwr_o_prev.eq(0b0)
            
            m.d.sync += [
                self.cpwr_out.eq(cpwr_o_prev)
            ]
        
        with m.Else():
            
            m.d.comb += cpwr_o_prev.eq(cpwr_delay[-1])
            m.d.sync += self.cpwr_out.eq(cpwr_o_prev)
        
        return m



if __name__ == '__main__':
    kurt_thresh = Kurtosis_Tresholder(37,82,3,5,5,5,4,10)
    amaranth.cli.main(
        kurt_thresh, ports=[kurt_thresh.cpwr_in, kurt_thresh.cpwr2_in, kurt_thresh.exp_cpwr_in, kurt_thresh.exp_cpwr2_in
                            , kurt_thresh.cpwr_out, kurt_thresh.cpwr2_out, kurt_thresh.exp_cpwr_out, kurt_thresh.exp_cpwr2_out,
                            kurt_thresh.common_edge, kurt_thresh.log2_nint, kurt_thresh.last_int, kurt_thresh.clken, 
                            kurt_thresh.kurt_shift_1, kurt_thresh.kurt_shift_2],   platform=PlutoPlatform())

