from amaranth import *
import amaranth.cli
from amaranth.vendor import XilinxPlatform

from .pluto_platform import PlutoPlatform


class Cpwr2TR(Elaboratable):
    def __init__(self, domain_3x: str, width: int, real_width: int = 0,
                 real_shift: int = 0, truncate: int = 0):
        """Cumulated squared power

        This module uses a two DSP48 running at 3 clock cycles per sample and a fabric adder  to
        compute the cumulated squared power.

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
        out : Signal(signed(output_width)), out
            Output, ``((re_in**2 + im_in**2)**2 + real_in) >> truncate``,
            with the appropriate shifts and truncations.
        """
        self._3x = domain_3x
        self.w = width
        self.outpwrw = 2 * width # max allowable width is 18 bits, leading to outpwrw of 36 bits, including sign bit
        
        self.add_width = (
            2 * self.outpwrw  # outwidth = multiplication of two 36 bit signed numbers, plus addition with real
            if 2 * self.outpwrw - 1 >= real_width + real_shift
            else real_width + real_shift + 1 ) # outwidth = real_width plus addition of one number < real_width 
        self.outw = self.add_width - truncate

        self.real_width = real_width
        self.real_shift = real_shift
        self.truncate = truncate
    
        self.common_edge = Signal()
        self.clken = Signal()
        self.re_in = Signal(signed(self.w))
        self.im_in = Signal(signed(self.w))
        self.real_in = Signal(signed(real_width))
        self.out = Signal(signed(self.outw), reset_less=True)
        #self.test = Signal(signed(self.add_width), reset_less=True)

    @property
    def delay(self):
        return 7

    def model(self, re_in, im_in, real_in):
        pwr = (re_in**2 + im_in**2)
        pwr2 = pwr**2
        real = real_in << self.real_shift
        out = (pwr2 + real) >> self.truncate
        return out


    def elaborate(self, platform):
        if isinstance(platform, XilinxPlatform):
            return self.elaborate_xilinx(platform)

        # Pure Amaranth design. Vivado doesn't infer a single DSP48E1
        # from this.
        m = Module()

        # power calculation
        preg_a1 = Signal(signed(self.w), reset_less=True)
        preg_a2 = Signal(signed(self.w), reset_less=True)
        preg_b1 = Signal(signed(self.w), reset_less=True)
        preg_b2 = Signal(signed(self.w), reset_less=True)
        preg_m = Signal(signed(2 * self.w), reset_less=True)
        preg_p = Signal(signed(2 * self.w), reset_less=True)
        preg_out = Signal(signed(2 * self.w), reset_less=True)


        # power^2 calculator
        p2reg_a = Signal(signed(self.w), reset_less=True)
        p2reg_b = Signal(signed(self.w), reset_less=True)
        p2reg_m = Signal(signed(2*self.w-1), reset_less=True)
        p2reg_p = Signal(signed(2*self.w-1), reset_less=True)
        pwr_x = Signal()
        pwr_x_q = Signal()
        pwr_l = Signal(signed(self.w))
        pwr_h = Signal(signed(self.w))
        p2reg_hh_temp = Signal(signed(2*self.w - 1))
        p2reg_ll_temp = Signal(signed(2*self.w - 1))


        # fabric adder 1 (38s)
        add1_res = Signal(signed(2*self.w + 2))
        add1_a = Signal(signed(2*self.w + 1))
        add1_b = Signal(signed(2*self.w + 1))
        add1_a_q = Signal(signed(2*self.w + 1))
        add1_b_q = Signal(signed(2*self.w + 1))


       

        # fabric adder 2
        add_hh = Signal(signed(4*self.w-1))
        add_ll = Signal(signed(2*self.w + 1))
        add_hl = Signal(signed(3*self.w + 1))
        add_real = Signal(signed(self.add_width))
        add_h_l_x = Signal(signed(2*self.w+1))
        add_hh_ll = Signal(signed(4*self.w))
        add_hl_real = Signal(signed(self.add_width))
        add_h_l_x_q = Signal(signed(2*self.w+1))
        add_c = Signal(signed(self.add_width))
        add_h_l_x_qq = Signal(signed(2*self.w+1))
        #out = Signal(signed(self.outw))
        

        # additional signal wires
        real_delay = [Signal(signed(self.add_width), reset_less=True) for _ in range(self.delay -4)]
        common_edge_q = Signal()
        common_edge_qq = Signal()
    

        with m.If(self.clken):

            # pwr
            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q),
                preg_a1.eq(self.im_in),
                preg_b1.eq(self.im_in),
                preg_a2.eq(preg_a1),
                preg_b2.eq(preg_b1),
                preg_m.eq(preg_a2 * preg_b2),
                preg_p.eq(preg_m)
            ]
            with m.If(self.common_edge):
                m.d[self._3x] += [
                    preg_a1.eq(self.re_in),
                    preg_b1.eq(self.re_in),
                ]
            with m.If(common_edge_q):
                m.d[self._3x] += [
                    preg_p.eq(preg_m + preg_p),
                ]

            m.d.sync += preg_out.eq(preg_p)

            # cpwr2

        m.d.comb += [pwr_x.eq(preg_out[0]),
                        pwr_l.eq(Cat(preg_out[1:self.w], Const(0, 1))),
                        pwr_h.eq(Cat(preg_out[self.w:2*self.w-1], Const(0,1))),
                        add1_a.eq(pwr_h.as_unsigned() << self.w+1),
                        add1_b.eq((pwr_l.as_unsigned() << 2) | 1),
                        add1_res.eq(add1_a_q + add1_b_q),
                        #self.test.eq(add_real)
                        ]

        with m.If(self.clken):
            
            m.d[self._3x] += [
                p2reg_a.eq(pwr_l),
                p2reg_b.eq(pwr_h),
                p2reg_m.eq(p2reg_a * p2reg_b),
                p2reg_p.eq(p2reg_m),

            ]

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    p2reg_a.eq(pwr_h),
                    p2reg_b.eq(pwr_h),
                    p2reg_hh_temp.eq(p2reg_p)
                ]
            
            with m.If(common_edge_q):

                m.d[self._3x] += [
                    p2reg_a.eq(pwr_l),
                    p2reg_b.eq(pwr_l),
                    p2reg_ll_temp.eq(p2reg_p)
                ]

            m.d.sync += [
                real_delay[0].eq(self.real_in << self.real_shift),
                add_real.eq(real_delay[-1]),
                add_hl.eq(p2reg_p.as_unsigned() << self.w + 2),
                add_hh.eq(p2reg_hh_temp.as_unsigned() << 2*self.w),
                add_ll.eq(p2reg_ll_temp.as_unsigned() << 2),
                add1_a_q.eq(add1_a),
                add1_b_q.eq(add1_b),
                add_hh_ll.eq(add_hh + add_ll),
                add_hl_real.eq(add_hl + add_real),
                add_h_l_x_q.eq(add_h_l_x),
                add_h_l_x_qq.eq(add_h_l_x_q),
                add_c.eq(add_hh_ll + add_hl_real),
                self.out.eq((add_c + add_h_l_x_qq)>>self.truncate),
                pwr_x_q.eq(pwr_x)
            ]

            with m.If(pwr_x_q):
                m.d.sync += add_h_l_x.eq(add1_res)
            with m.Else():
                m.d.sync += add_h_l_x.eq(0)


            for i in range(1,self.delay-4):
                m.d.sync += real_delay[i].eq(real_delay[i-1])

        return m

    def elaborate_xilinx(self, platform):
        # Design with two instantiated DSP48E1

      
        m = Module()

        #DSP1
        dsp1_a1 = Signal(signed(30), reset_less=True)
        dsp1_b1 = Signal(signed(18), reset_less=True)
        dsp1_p = Signal(48, reset_less=True)
        dsp1_opmode = Signal(7, reset_less=True)

        m.submodules.dsp = dsp1 = Instance(
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
            o_P=dsp1_p,
            o_PATTERNBDETECT=Signal(),
            o_PATTERNDETECT=Signal(),
            o_PCOUT=Signal(48),
            o_UNDERFLOW=Signal(),
            i_ACIN=Const(0, unsigned(30)),
            i_BCIN=Const(0, unsigned(18)),
            i_CARRYCASCIN=0,
            i_MULTSIGNIN=0,
            i_PCIN=Const(0, unsigned(48)),
            i_ALUMODE=Const(0, unsigned(4)),
            i_CARRYINSEL=Const(0, unsigned(3)),
            i_CLK=ClockSignal(self._3x),
            i_INMODE=Const(0, unsigned(5)),  # A2, B2
            i_OPMODE=dsp1_opmode,
            i_A=dsp1_a1,
            i_B=dsp1_b1,
            i_C=Const(0, unsigned(48)),
            i_CARRYIN=0,
            i_D=Const(0, unsigned(25)),
            i_CEA1=self.clken,
            i_CEA2=self.clken,
            i_CEAD=self.clken,
            i_CEALUMODE=self.clken,
            i_CEB1=self.clken,
            i_CEB2=self.clken,
            i_CEC=0,
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

        
        preg_out = Signal(signed(2 * self.w), reset_less=True)
    
        #DSP2
        dsp2_a1 = Signal(signed(30), reset_less=True)
        dsp2_b1 = Signal(signed(18), reset_less=True)
        dsp2_p = Signal(48, reset_less=True)

        m.submodules.dsp2 = dsp2 = Instance(
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
            p_ACASCREG=1,  # number of A register stages
            p_ADREG=1,
            p_ALUMODEREG=1,
            p_AREG=1,
            p_BCASCREG=1,
            p_BREG=1,
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
            o_P=dsp2_p,
            o_PATTERNBDETECT=Signal(),
            o_PATTERNDETECT=Signal(),
            o_PCOUT=Signal(48),
            o_UNDERFLOW=Signal(),
            i_ACIN=Const(0, unsigned(30)),
            i_BCIN=Const(0, unsigned(18)),
            i_CARRYCASCIN=0,
            i_MULTSIGNIN=0,
            i_PCIN=Const(0, unsigned(48)),
            i_ALUMODE=Const(0, unsigned(4)),
            i_CARRYINSEL=Const(0, unsigned(3)),
            i_CLK=ClockSignal(self._3x),
            i_INMODE=Const(0, unsigned(5)),  # A2, B2
            i_OPMODE=Const(0b000_01_01, unsigned(7)),
            i_A=dsp2_a1,
            i_B=dsp2_b1,
            i_C=Const(0, unsigned(48)),
            i_CARRYIN=0,
            i_D=Const(0, unsigned(25)),
            i_CEA1=0,
            i_CEA2=self.clken,
            i_CEAD=self.clken,
            i_CEALUMODE=self.clken,
            i_CEB1=0,
            i_CEB2=self.clken,
            i_CEC=0,
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

        
        pwr_x = Signal()
        pwr_x_q = Signal()
        pwr_l = Signal(signed(self.w))
        pwr_h = Signal(signed(self.w))
        p2reg_hh_temp = Signal(signed(2*self.w - 1))
        p2reg_ll_temp = Signal(signed(2*self.w - 1))

        # fabric adder 1 (38s)
        add1_res = Signal(signed(2*self.w + 2))
        add1_a = Signal(signed(2*self.w + 1))
        add1_b = Signal(signed(2*self.w + 1))
        add1_a_q = Signal(signed(2*self.w + 1))
        add1_b_q = Signal(signed(2*self.w + 1))


        # fabric adder 2
        add_hh = Signal(signed(4*self.w-1))
        add_ll = Signal(signed(2*self.w + 1))
        add_hl = Signal(signed(3*self.w + 1))
        add_real = Signal(signed(self.add_width))
        add_h_l_x = Signal(signed(2*self.w+1))
        add_hh_ll = Signal(signed(4*self.w))
        add_hl_real = Signal(signed(self.add_width))
        add_h_l_x_q = Signal(signed(2*self.w+1))
        add_c = Signal(signed(self.add_width))
        add_h_l_x_qq = Signal(signed(2*self.w+1))

        real_delay = [Signal(signed(self.real_width + self.real_shift), reset_less=True) for _ in range(self.delay -4)]
        common_edge_q = Signal()
        common_edge_qq = Signal()


        m.d.comb += [
            dsp1_a1.eq(self.im_in),
            dsp1_b1.eq(self.im_in),
            # M
            dsp1_opmode.eq(0b000_01_01),  
        ]

        with m.If(self.common_edge):
            m.d.comb += [
                dsp1_a1.eq(self.re_in),
                dsp1_b1.eq(self.re_in),
                    # M + P
                dsp1_opmode.eq(0b010_01_01),
            ]

        m.d.comb += [
            # spliting up pwr into 3 parts
            pwr_x.eq(preg_out[0]),
            pwr_l.eq(Cat(preg_out[1:self.w], Const(0, 1))),
            pwr_h.eq(Cat(preg_out[self.w:2*self.w-1], Const(0,1))),
            # small fabric adder
            add1_a.eq(pwr_h.as_unsigned() << self.w+1),
            add1_b.eq((pwr_l.as_unsigned() << 2) | 1),
            add1_res.eq(add1_a_q + add1_b_q),
            dsp2_a1.eq(pwr_l),
            dsp2_b1.eq(pwr_h)
        ]

        with m.If(self.common_edge):
            m.d.comb += [
                dsp2_a1.eq(pwr_h),
                dsp2_b1.eq(pwr_h),
            ]
        
        with m.If(common_edge_q):
                m.d.comb += [
                    dsp2_a1.eq(pwr_l),
                    dsp2_b1.eq(pwr_l),
                ]


        with m.If(self.clken):

            # Power calculation

            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q),
            ]
           
            m.d.sync += preg_out.eq(dsp1_p),

           
            # Squaring power and adding it to real_in

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    p2reg_hh_temp.eq(dsp2_p)
                ]
            
            with m.If(common_edge_q):

                m.d[self._3x] += [
                    p2reg_ll_temp.eq(dsp2_p)
                ]

            m.d.sync += [
                real_delay[0].eq(self.real_in << self.real_shift),
                add_real.eq(real_delay[-1]),
                add_hl.eq(dsp2_p.as_unsigned() << self.w + 2),
                add_hh.eq(p2reg_hh_temp.as_unsigned() << 2*self.w),
                add_ll.eq(p2reg_ll_temp.as_unsigned() << 2),
                add1_a_q.eq(add1_a),
                add1_b_q.eq(add1_b),
                add_hh_ll.eq(add_hh + add_ll),
                add_hl_real.eq(add_hl + add_real),
                add_h_l_x_q.eq(add_h_l_x),
                add_h_l_x_qq.eq(add_h_l_x_q),
                add_c.eq(add_hh_ll + add_hl_real),
                self.out.eq((add_c + add_h_l_x_qq)>>self.truncate),
                pwr_x_q.eq(pwr_x)
            ]

            with m.If(pwr_x_q):
                m.d.sync += add_h_l_x.eq(add1_res)
            with m.Else():
                m.d.sync += add_h_l_x.eq(0)


            for i in range(1,self.delay-4):
                m.d.sync += real_delay[i].eq(real_delay[i-1])




        return m


if __name__ == '__main__':
    cpwr = Cpwr2TR('clk3x', width=16, real_width=24, real_shift=16,
                    truncate=16)
    amaranth.cli.main(
        cpwr, ports=[
            cpwr.common_edge, cpwr.clken, cpwr.re_in, cpwr.im_in,
            cpwr.real_in, cpwr.out],
        platform=PlutoPlatform())
