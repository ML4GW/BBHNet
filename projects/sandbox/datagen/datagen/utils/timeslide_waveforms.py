import math
import time
from pathlib import Path
from typing import List, Tuple

import h5py
import numpy as np
import torch

from ml4gw.spectral import normalize_psd


def calc_shifts_required(Tb: float, T: float, delta: float) -> int:
    r"""
    The algebra to get this is gross but straightforward.
    Just solving
    $$\sum_{i=1}^{N}(T - i\delta) \geq T_b$$
    for the lowest value of N, where \delta is the
    shift increment.

    TODO: generalize to multiple ifos and negative
    shifts, since e.g. you can in theory get the same
    amount of Tb with fewer shifts if for each shift
    you do its positive and negative. This should just
    amount to adding a factor of 2 * number of ifo
    combinations in front of the sum above.
    """

    discriminant = (delta / 2 - T) ** 2 - 2 * delta * Tb
    N = (T - delta / 2 - discriminant**0.5) / delta
    return math.ceil(N)


def get_num_shifts(
    segments: List[Tuple[float, float]], Tb: float, shift: float
) -> int:
    T = sum([stop - start for start, stop in segments])
    return calc_shifts_required(Tb, T, shift)


def io_with_blocking(f, fname, timeout=10):
    start_time = time.time()
    while True:
        try:
            return f(fname)
        except BlockingIOError:
            if (time.time() - start_time) > timeout:
                raise


def load_psds(
    background: Path, ifos: List[str], sample_rate: float, df: float
):
    with h5py.File(background, "r") as f:
        psds = []
        for ifo in ifos:
            hoft = f[ifo][:]
            psd = normalize_psd(hoft, df, sample_rate)
            psds.append(psd)
    psds = torch.tensor(np.stack(psds), dtype=torch.float64)
    return psds


def calc_segment_injection_times(
    start: float,
    stop: float,
    spacing: float,
    buffer: float,
    waveform_duration: float,
):
    """
    Calculate the times at which to inject signals into a segment

    Args:
        start: The start time of the segment
        stop: The stop time of the segment
        spacing: The spacing between signals
        jitter: The jitter to apply to the signal times
        buffer: The buffer to apply to the start and end of the segment
        waveform_duration: The duration of the waveform

    Returns np.ndarray of injection times
    """

    buffer += waveform_duration // 2
    spacing += waveform_duration
    injection_times = np.arange(start + buffer, stop - buffer, spacing)
    return injection_times
