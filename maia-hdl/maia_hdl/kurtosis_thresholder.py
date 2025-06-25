from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform
from .pluto_platform import PlutoPlatform


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
    def __init__(self, domain_3x: str, width_cpwr, width_cpwr2, width_exp, nint_width, width_kurt):
        
        self._3x = domain_3x
        self.width_cpwr = width_cpwr
        self.width_cpwr2 = width_cpwr2
        self.width_exp = width_exp
        self.nint_width = nint_width
        self.width_kurt = width_kurt

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

        self.log2_nint = Signal(nint_width)
        self.clken = Signal()
        self.common_edge = Signal()
        self.last_int = Signal()


    @property
    def delay(self):
        return 8

    def model(self):
        # TODO
        return 1
        
    def elaborate(self, platform):
        if isinstance(platform, XilinxPlatform):
            return self.elaborate_xilinx(platform)
        

        m = Module()

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

        add_hh = Signal(signed(width_hh), reset_less=True)
        add_mh = Signal(signed(width_h_18), reset_less=True)
        add_mh_q = Signal(signed(width_h_18+16), reset_less=True)

        # adder 2 input signals
        add2_a = Signal(signed(54), reset_less=True) # ll_q and lm_q are added together
        add2_b = Signal(signed(width_h_18+36), reset_less=True) # mm and lh_q are added together
        add2_c = Signal(signed(width_h_18+69), reset_less=True)

        # adder 3 input signals
        add3_c = Signal(signed(width_h_18+69), reset_less=True)
        add3_ab = Signal(signed(width_h_18+37))

        # output signal
        width_add_out = width_h_18+70
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
        cpwr2_shifted = Signal(signed(self.width_cpwr2 + 4)) # exponent can have maximum value of 4

        cpwr2_delay = [Signal(signed(self.width_cpwr2 + 4), reset_less=True) for _ in range(self.delay)]
        cpwr_delay = [Signal(signed(self.width_cpwr), reset_less=True) for _ in range(self.delay-1)]
        log2_int_delay = [Signal(signed(self.log2_nint), reset_less=True) for _ in range(self.delay)]
        exp_cpwr2_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]
        exp_cpwr_delay = [Signal(signed(self.width_exp), reset_less=True) for _ in range(self.delay)]

        with m.If(self.clken):
            for i in range(1,self.delay-1):
                m.d.sync += cpwr_delay[i].eq(cpwr_delay[i-1])
            for i in range(1,self.delay):
                m.d.sync += exp_cpwr_delay[i].eq(exp_cpwr_delay[i-1])


        with m.If(self.last_int & self.clken):

            m.d.comb += [
                cpwr_l.eq(Cat(self.cpwr2_in[:17], Const(0,1))),
                cpwr_m.eq(Cat(self.cpwr2_in[17:34], Const(0, 1))),
                cpwr_h.eq(Cat(self.cpwr2_in[34:], Const(0,1))),
            ]

            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q)
            ]

            # DSP1
            m.d[self._3x] += [
                dsp1_a1.eq(cpwr_m),
                dsp1_b1.eq(cpwr_l),
                dsp1_m.eq(dsp1_a1*dsp1_b1)
            ]

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    dsp1_a1.eq(cpwr_l),
                    dsp1_b1.eq(cpwr_l)
                ]
            
            with m.If(common_edge_qq):
                m.d[self._3x] += [
                    dsp1_a1.eq(cpwr_m),
                    dsp1_b1.eq(cpwr_m)
                ]
            
            # DSP2



        


        
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

