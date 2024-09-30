from warnings import filterwarnings

from beartype.claw import beartype_this_package
from beartype.roar import BeartypeDecorHintPep585DeprecationWarning

beartype_this_package()

filterwarnings("ignore", category=BeartypeDecorHintPep585DeprecationWarning)
