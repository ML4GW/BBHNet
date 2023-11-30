from dataclasses import dataclass

import numpy as np

from aframe.analysis.ledger.injections import LigoResponseSet


@dataclass
class Injector:
    """
    Callable class to add interferometer responses from the injection set
    onto background noise.

    Args:
        injection_set:
            A `LigoResponseSet`, which contains the responses and parameters
            of the signals to be injected.
        start:
            Initial GPS time of the background being injected
        sample_rate:
            Sample rate of the background data, specified in Hz
    """

    injection_set: LigoResponseSet
    start: float
    sample_rate: float

    def __call__(self, x):
        x_inj = self.injection_set.inject(x.copy(), self.start)
        self.start += x.shape[-1] / self.sample_rate
        return np.stack([x, x_inj])
