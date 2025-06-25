from amaranth import *
import amaranth.cli


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
    def __init__(self, width_cpwr, width_cpwr2, width_exp, nint_width, width_kurt):
        
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
        
    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.cpwr_out.eq(Cat(self.cpwr_in[:-1], self.cpwr2_in[0]))
        return m
    


if __name__ == '__main__':
    kurt_thresh = Kurtosis_Tresholder(37,81)
    amaranth.cli.main(
        kurt_thresh, ports=[kurt_thresh.cpwr_in, kurt_thresh.cpwr2_in, kurt_thresh.cpwr_out])

