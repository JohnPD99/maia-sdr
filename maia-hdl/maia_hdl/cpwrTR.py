from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform

from .pluto_platform import PlutoPlatform


class CpwrTR(Elaboratable):
    def __init__(self, domain_3x: str, width: int, real_width: int = 0,
                 real_shift: int = 0, truncate: int = 0):
        """Average power

        This module uses a single DSP48 running at 3 clock cycles per sample to
        compute the power (amplitude squared) of a complex input and adds it 
        with another real input

        Parameters
        ----------
        domain_3x : str
            Name of the clock domain of the 3x clock.
        width : int
            Width of the input sample.
        real_width : int
            Width of the real input to be added / maximized.
        real_shift : int
            Number of bits to shift the real input to the left.
            This is used because the power has a large bit growth and
            is often truncated after the addition.
        truncate : int
            Number of bits to truncate the output.

        Attributes
        ----------
        delay : int, out
            Delay (in samples) introduced by this module to the complex
            input data.
        common_edge : Signal(), in
            A signal that changes with the 3x clock and is high on the cycles
            immediately after the rising edge of the 1x clock.
        clken : Signal(), in
            Clock enable.
        re_in : Signal(signed(width)), in
            Complex input real part.
        im_in : Signal(signed(width)), in
            Complex input imaginary part.
        real_in : Signal(signed(real_width)), in
            Real value to be added / maximized.
        peak_detect : Signal(), in
            Enables peak detect mode (instead of average mode). --> won't be used in this version
        out : Signal(signed(output_width)), out
            Output, formally either ``re_in**2 + im_in**2 + real_in``
            (in average mode) or ``re_in**2 + im_in**2`` (in peak detect mode),
            with the appropriate shifts and truncations.
            The output width is computed according to ``width``, ``real_width``
            and ``truncate`` assuming that addition is done (because it has bit
            growth, unlike the maximum).
        is_greater : Signal(), out
            In peak detect mode, this signal is high when the computed
            ``re_in**2 + im_in**2`` is greater than ``real_in``. This can be
            used as a write enable to overwrite the memory holding ``real_in``
            so as to compute the maximum. --> won't be used in this version
        """
        self._3x = domain_3x
        self.w = width
        self.outw = (
            2 * width + 2 - truncate
            if 2 * width >= real_width + real_shift
            else real_width + real_shift + 1 - truncate)
        self.real_width = real_width
        self.real_shift = real_shift
        self.truncate = truncate

        self.common_edge = Signal()
        self.clken = Signal()
        self.re_in = Signal(signed(self.w))
        self.im_in = Signal(signed(self.w))
        self.real_in = Signal(signed(real_width))
        #self.peak_detect = Signal()
        self.out = Signal(signed(self.outw), reset_less=True)
        #self.is_greater = Signal(reset_less=True) 
    @property
    def delay(self):
        # We delay the output, since it has to align with cpwr_2, a new module that calculates the accumulation of the squared powers
        return 8

    def model(self, re_in, im_in, real_in):
        pwr = re_in**2 + im_in**2
        real = real_in << self.real_shift
        out = (pwr + real) >> self.truncate
        return out

    def elaborate(self, platform):
        if isinstance(platform, XilinxPlatform):
            return self.elaborate_xilinx(platform)

        # Pure Amaranth design. Vivado doesn't infer a single DSP48E1
        # from this.
        # m = Module()
        # reg_a1 = Signal(signed(self.w), reset_less=True)
        # reg_a2 = Signal(signed(self.w), reset_less=True)
        # reg_b1 = Signal(signed(self.w), reset_less=True)
        # reg_b2 = Signal(signed(self.w), reset_less=True)
        # reg_m = Signal(signed(2 * self.w + 1), reset_less=True)
        # reg_c = Signal(signed(self.real_width + self.real_shift),
        #                reset_less=True)
        # reg_p = Signal(signed(self.outw + self.truncate), reset_less=True)
        # common_edge_q = Signal()
        # common_edge_qq = Signal()
        # out_prev = Signal(signed(self.outw), reset_less=True)
        # is_greater_prev = Signal(reset_less=True)

        # with m.If(self.clken):
        #     m.d[self._3x] += [
        #         common_edge_q.eq(self.common_edge),
        #         common_edge_qq.eq(common_edge_q),
        #         reg_a1.eq(self.im_in),
        #         reg_b1.eq(self.im_in),
        #         reg_a2.eq(reg_a1),
        #         reg_b2.eq(reg_b1),
        #         reg_m.eq(reg_a2 * reg_b2),
        #     ]
        #     with m.If(self.common_edge):
        #         m.d[self._3x] += [
        #             reg_a1.eq(self.re_in),
        #             reg_b1.eq(self.re_in),
        #             reg_p.eq(Mux(self.peak_detect, reg_m, reg_m + reg_c)),
        #             is_greater_prev.eq(reg_p[-1]),
        #         ]
        #     with m.If(common_edge_q):
        #         m.d[self._3x] += [
        #             reg_p.eq(reg_m + reg_p),
        #         ]
        #     with m.If(common_edge_qq):
        #         m.d[self._3x] += [
        #             reg_c.eq(self.real_in << self.real_shift),
        #             reg_p.eq(reg_c - reg_p),
        #         ]
        #     m.d.sync += [
        #         out_prev.eq(reg_p >> self.truncate),
        #         self.out.eq(out_prev),
        #         self.is_greater.eq(is_greater_prev),
        #     ]
        # return m

    def elaborate_xilinx(self, platform):
        # Design with an instantiated DSP48E1
        m = Module()
        port_a = Signal(signed(30), reset_less=True)
        port_b = Signal(signed(18), reset_less=True)
        port_c = Signal(48, reset_less=True)
        port_p = Signal(48, reset_less=True)
        port_p_clken = Signal(reset_less=True)
        alumode = Signal(4, reset_less=True)
        opmode = Signal(7, reset_less=True)
        #cec = Signal(reset_less=True)
        m.submodules.dsp = dsp = Instance(
            'DSP48E1',
            p_A_INPUT='DIRECT',  # A port rather than ACIN
            p_B_INPUT='DIRECT',  # B port rather than BCIN
            p_USE_DPORT='FALSE',
            p_USE_MULT='MULTIPLY',
            p_USE_SIMD='ONE48',
            p_AUTORESET_PATDET='NO_RESET',
            p_MASK=2**48-1,  # ignore all bits
            p_PATTERN=0,
            p_SEL_MASK='MASK',
            p_SEL_PATTERN='PATTERN',
            p_USE_PATTERN_DETECT='NO_PATDET',
            p_ACASCREG=2,  # number of A register stages
            p_ADREG=1,
            p_ALUMODEREG=1,
            p_AREG=2,
            p_BCASCREG=2,
            p_BREG=2,
            p_CARRYINREG=1,
            p_CARRYINSELREG=1,
            p_CREG=1,
            p_DREG=1,
            p_INMODEREG=1,
            p_MREG=1,
            p_OPMODEREG=1,
            p_PREG=1,
            o_ACOUT=Signal(30),
            o_BCOUT=Signal(18),
            o_CARRYCASCOUT=Signal(),
            o_CARRYOUT=Signal(4),
            o_MULTSIGNOUT=Signal(),
            o_OVERFLOW=Signal(),
            o_P=port_p,
            o_PATTERNBDETECT=Signal(),
            o_PATTERNDETECT=Signal(),
            o_PCOUT=Signal(48),
            o_UNDERFLOW=Signal(),
            i_ACIN=Const(0, unsigned(30)),
            i_BCIN=Const(0, unsigned(18)),
            i_CARRYCASCIN=0,
            i_MULTSIGNIN=0,
            i_PCIN=Const(0, unsigned(48)),
            i_ALUMODE=alumode,
            i_CARRYINSEL=Const(0, unsigned(3)),
            i_CLK=ClockSignal(self._3x),
            i_INMODE=Const(0, unsigned(5)),  # A2, B2
            i_OPMODE=opmode,
            i_A=port_a,
            i_B=port_b,
            i_C=port_c,
            i_CARRYIN=0,
            i_D=Const(0, unsigned(25)),
            i_CEA1=self.clken,
            i_CEA2=self.clken,
            i_CEAD=self.clken,
            i_CEALUMODE=self.clken,
            i_CEB1=self.clken,
            i_CEB2=self.clken,
            i_CEC=self.clken,
            i_CECARRYIN=0,
            i_CECTRL=self.clken,
            i_CED=0,
            i_CEINMODE=self.clken,
            i_CEM=self.clken,
            i_CEP=self.clken,
            i_RSTA=0,
            i_RSTALLCARRYIN=0,
            i_RSTALUMODE=0,
            i_RSTB=0,
            i_RSTC=0,
            i_RSTCTRL=0,
            i_RSTD=0,
            i_RSTINMODE=0,
            i_RSTM=0,
            i_RSTP=0)

        common_edge_q = Signal()
        common_edge_qq = Signal()
        output_delay = [Signal(signed(self.outw), reset_less=True) for _ in range(self.delay -1)]
        #is_greater_prev = Signal(reset_less=True)
        with m.If(self.clken):
            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q),
            ]
            # with m.If(self.common_edge):
            #     m.d[self._3x] += is_greater_prev.eq(port_p[47])
            m.d.sync += output_delay[0].eq(port_p >> self.truncate),
            for i in range(1,self.delay - 1):
                m.d.sync += output_delay[i].eq(output_delay[i-1]),
                #self.is_greater.eq(is_greater_prev),
            m.d.sync += self.out.eq(output_delay[-1])
            
        m.d.comb += [
            port_a.eq(self.im_in),
            port_b.eq(self.im_in),
            port_c.eq(self.real_in << self.real_shift),
            # Z + X + Y + CIN (used in most cases)
            alumode.eq(0b0000),
            opmode.eq(0b010_01_01)  # P + M
        ]
        with m.If(self.common_edge):
            m.d.comb += [
                port_a.eq(self.re_in),
                port_b.eq(self.re_in),
            ]
        with m.If(common_edge_qq):
            m.d.comb += [
                # M (peak) or C + M (avg)
                opmode.eq(0b011_01_01),
            ]
        return m


if __name__ == '__main__':
    cpwr = CpwrTR('clk3x', width=16, real_width=24, real_shift=16,
                    truncate=16)
    amaranth.cli.main(
        cpwr, ports=[
            cpwr.common_edge, cpwr.clken, cpwr.re_in, cpwr.im_in,
            cpwr.real_in, cpwr.out],
        platform=PlutoPlatform())
