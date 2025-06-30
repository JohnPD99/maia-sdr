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
  

    Attributes
    ----------
    
   
    """
    def __init__(self, domain_3x: str, width_a):
        
        self._3x = domain_3x
        self.width_a = width_a
        self.width_out = 2*width_a+1

        
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
        cpwr_h = Signal(signed(self.width_a-34+1), reset_less=True)


        # DSPs

        dsp1_a1 = Signal(signed(18), reset_less=True)
        dsp1_b1 = Signal(signed(18), reset_less=True)
        dsp1_m = Signal(signed(48), reset_less=True)
        dsp1_p = Signal(signed(48), reset_less=True)

        dsp2_a1 = Signal(signed(18), reset_less=True)
        dsp2_b1 = Signal(signed(18), reset_less=True)
        dsp2_m = Signal(signed(48), reset_less=True)
        dsp2_p = Signal(signed(48), reset_less=True)

        # adder input signals
        add_ll = Signal(signed(2*dsp2_a1.shape().width-1), reset_less=True)
        add_lm = Signal(signed(2*dsp2_a1.shape().width-1), reset_less=True)
        add_lm_q = Signal(signed(add_lm.shape().width + 18), reset_less=True)
        add_ll_q = Signal(signed(add_lm.shape().width), reset_less=True)


        add_mm = Signal(signed(2*dsp2_a1.shape().width-1), reset_less=True)
        add_lh = Signal(signed(2*dsp2_a1.shape().width-1), reset_less=True)
        add_lh_q = Signal(signed(2*dsp2_a1.shape().width), reset_less=True)

        add_hh = Signal(signed(2*dsp2_a1.shape().width+15), reset_less=True)
        add_mh = Signal(signed(2*dsp2_a1.shape().width-1), reset_less=True)
        add_mh_q = Signal(signed(add_mh.shape().width), reset_less=True)

        # adder 2 input signals
        add2_a = Signal(signed(max(add_lm_q.shape().width, add_ll_q.shape().width)+1), reset_less=True) # ll_q and lm_q are added together
        add2_b = Signal(signed(add_lh_q.shape().width + 35), reset_less=True) # mm and lh_q are added together
        add2_c = Signal(signed(max(add_mh_q.shape().width, add_hh.shape().width)+53), reset_less=True)

        # adder 3 input signals
        add3_c = Signal(signed(add2_c.shape().width), reset_less=True)
        add3_ab = Signal(signed(max(add2_a.shape().width, add2_b.shape().width)+1))

        # additional signals
        common_edge_q = Signal()
        common_edge_qq = Signal()


        # spliting up cpwr for squaring

        m.d.comb += [
            cpwr_l.eq(Cat(self.a[:17], Const(0,1))),
            cpwr_m.eq(Cat(self.a[17:34], Const(0, 1))),
            cpwr_h.eq(Cat(self.a[34:], Const(0,1))),
        ]

        with m.If(self.clken):

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
                add3_c.eq(add2_c),
                self.out.eq(add3_ab + add3_c)
            ]

        return m
    
    def elaborate_xilinx(self, platform):
        m = Module()

        # S1_squarering
        cpwr_l = Signal(signed(18), reset_less=True)
        cpwr_m = Signal(signed(18), reset_less=True)
        cpwr_h = Signal(signed(self.width_a-34+1), reset_less=True)


        # DSPs

        dsp1_a1 = Signal(signed(30), reset_less=True)
        dsp1_b1 = Signal(signed(18), reset_less=True)
        dsp1_p = Signal(signed(48), reset_less=True)

        m.submodules.dsp1 = dsp1 = Instance(
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
            i_OPMODE=Const(0b000_01_01, unsigned(7)),
            i_A=dsp1_a1,
            i_B=dsp1_b1,
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
        

        dsp2_a1 = Signal(signed(30), reset_less=True)
        dsp2_b1 = Signal(signed(18), reset_less=True)
        dsp2_p = Signal(signed(48), reset_less=True)

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
      

        # adder input signals
        add_ll = Signal(signed(2*dsp2_b1.shape().width-1), reset_less=True)
        add_lm = Signal(signed(2*dsp2_b1.shape().width-1), reset_less=True)
        add_lm_q = Signal(signed(add_lm.shape().width + 18), reset_less=True)
        add_ll_q = Signal(signed(add_lm.shape().width), reset_less=True)


        add_mm = Signal(signed(2*dsp2_b1.shape().width-1), reset_less=True)
        add_lh = Signal(signed(2*dsp2_b1.shape().width-1), reset_less=True)
        add_lh_q = Signal(signed(2*dsp2_b1.shape().width), reset_less=True)

        add_hh = Signal(signed(2*dsp2_b1.shape().width+15), reset_less=True)
        add_mh = Signal(signed(2*dsp2_b1.shape().width-1), reset_less=True)
        add_mh_q = Signal(signed(add_mh.shape().width), reset_less=True)

        # adder 2 input signals
        add2_a = Signal(signed(max(add_lm_q.shape().width, add_ll_q.shape().width)+1), reset_less=True) # ll_q and lm_q are added together
        add2_b = Signal(signed(add_lh_q.shape().width + 35), reset_less=True) # mm and lh_q are added together
        add2_c = Signal(signed(max(add_mh_q.shape().width, add_hh.shape().width)+53), reset_less=True)

        # adder 3 input signals
        add3_c = Signal(signed(add2_c.shape().width), reset_less=True)
        add3_ab = Signal(signed(max(add2_a.shape().width, add2_b.shape().width)+1))

        # additional signals
        common_edge_q = Signal()
        common_edge_qq = Signal()

         # spliting up cpwr for squaring

        m.d.comb += [
            cpwr_l.eq(Cat(self.a[:17], Const(0,1))),
            cpwr_m.eq(Cat(self.a[17:34], Const(0, 1))),
            cpwr_h.eq(Cat(self.a[34:], Const(0,1))),
        ]

        # DSP1
        m.d.comb += [
            dsp1_a1.eq(cpwr_m),
            dsp1_b1.eq(cpwr_l),
        ]

        with m.If(self.common_edge):
            m.d.comb += [
                dsp1_a1.eq(cpwr_l),
                dsp1_b1.eq(cpwr_l),
            ]
        
        with m.If(common_edge_qq):
            m.d.comb += [
                dsp1_a1.eq(cpwr_m),
                dsp1_b1.eq(cpwr_m)
            ]

         # DSP2

        m.d.comb += [
            dsp2_a1.eq(cpwr_h),
            dsp2_b1.eq(cpwr_h),
        ]

        with m.If(self.common_edge):
            m.d.comb += [
                dsp2_a1.eq(cpwr_l),
                dsp2_b1.eq(cpwr_h),
            ]
        
        with m.If(common_edge_q):
            m.d.comb += [
                dsp2_a1.eq(cpwr_h),
                dsp2_b1.eq(cpwr_m),
            ]


        with m.If(self.clken):

            # DSPs
            m.d[self._3x] += [
                common_edge_q.eq(self.common_edge),
                common_edge_qq.eq(common_edge_q)
            ]

            with m.If(self.common_edge):
                m.d[self._3x] += add_ll.eq(dsp1_p)

            with m.If(common_edge_q):
                m.d[self._3x] += [
                    add_lm.eq(dsp1_p)
                ]
            
            m.d.sync += [
                add_ll_q.eq(add_ll),
                add_lm_q.eq(add_lm << 18),
                add_mm.eq(dsp1_p)
            ]
            
            # DSP2

            with m.If(self.common_edge):
                m.d[self._3x] += [
                    add_lh.eq(dsp2_p)
                ]
            
            with m.If(common_edge_q):
                m.d[self._3x] += [
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
                add3_c.eq(add2_c),
                self.out.eq(add3_ab + add3_c)
            ]

        return m
        
    


if __name__ == '__main__':
    s1_2 = S1_2(47)
    amaranth.cli.main(
        s1_2, ports=[s1_2.a,s1_2.out],   platform=PlutoPlatform())

