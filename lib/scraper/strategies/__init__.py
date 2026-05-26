from .ssense import SSENSEStrategy
from .tessabit import TESSABITStrategy
from .generic import GenericStrategy

# 定番
from .farfetch import FARFETCHStrategy
from .matchesfashion import MATCHESFASHIONStrategy
from .mytheresa import MYTHERESAStrategy

# デパート
from .selfridges import SELFRIDGESStrategy
from .saks import SAKSStrategy
from .harrods import HARRODSStrategy
from .harveynichols import HARVEYNICHOLSStrategy
from .neimanmarcus import NEIMANMARCUSStrategy

# 欧州セレクト
from .luisaviaroma import LUISAVIAROMAStrategy
from .giglio import GIGLIOStrategy
from .biffi import BIFFIStrategy

# YNAP グループ（多ブランドEC）
from .netaporter import NETAPORTERStrategy
from .mrporter import MRPORTERStrategy
from .yoox import YOOXStrategy
from .theoutnet import THEOUTNETStrategy

# LVMH グループ
from .twentyfoursevens import TWENTYFOURSStrategy

__all__ = [
    "SSENSEStrategy",
    "TESSABITStrategy",
    "GenericStrategy",
    "FARFETCHStrategy",
    "MATCHESFASHIONStrategy",
    "MYTHERESAStrategy",
    "SELFRIDGESStrategy",
    "SAKSStrategy",
    "HARRODSStrategy",
    "HARVEYNICHOLSStrategy",
    "NEIMANMARCUSStrategy",
    "LUISAVIAROMAStrategy",
    "GIGLIOStrategy",
    "BIFFIStrategy",
    "NETAPORTERStrategy",
    "MRPORTERStrategy",
    "YOOXStrategy",
    "THEOUTNETStrategy",
    "TWENTYFOURSStrategy",
]
