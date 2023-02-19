from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import List, Tuple

import h5py
import numpy as np
import torch

from ml4gw.spectral import normalize_psd


def calc_shifts_required(
    segments: List[Tuple[int, int]], Tb: float, shift: float
):
    """
    Based off of the lengths of the segments and the
    amount of data that will need to be sloughed off
    the ends due to shifting, calculate how many shifts
    will be required to achieve Tb seconds worth of background
    """

    livetime = np.sum([stop - start for start, stop in segments])
    n_segments = len(segments)
    shifts_required = 1
    while True:
        max_shift = shift * shifts_required
        total_livetime = (livetime - n_segments * max_shift) * shifts_required
        if total_livetime < Tb:
            shifts_required += 1
            continue
        break

    return shifts_required


def merge_output(datadir: Path):
    files = datadir.glob("*.hdf5")
    datasets = defaultdict(list)
    n_rejected = 0
    for f in files:
        with h5py.File(f, "r") as h5f:
            for key, value in h5f.items():
                datasets[key].extend(value)
            n_rejected += h5f.attrs["n_rejected"]
        f.unlink()

    with h5py.File(datadir / "timeslide_waveforms.hdf5", "w") as f:
        for key, value in datasets.items():
            f.create_dataset(key, data=value)
        f.attrs.update(
            {
                "n_rejected": n_rejected,
            }
        )


def load_psds(*backgrounds: Path, sample_rate: float, df: float):

    psds = []
    for fname in backgrounds:
        with h5py.File(fname, "r") as f:
            hoft = f["hoft"][:]
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

    buffer += waveform_duration // 2 + buffer
    spacing = waveform_duration + spacing
    injection_times = np.arange(start + buffer, stop - buffer, spacing)
    return injection_times


def create_submit_file(
    executable,
    condor_dir,
    accounting_group,
    accounting_group_user,
    request_memory,
    request_disk,
    arguments,
):

    logdir = condor_dir / "logs"
    logdir.mkdir(exist_ok=True, parents=True)
    subfile = dedent(
        f"""\
        universe = vanilla
        executable = {executable}
        arguments = {arguments}
        log = {logdir}/timeslide_waveforms.log
        output = {logdir}/timeslide_waveforms.out
        error = {logdir}/timeslide_waveforms.err
        accounting_group = {accounting_group}
        accounting_group_user = {accounting_group_user}
        request_memory = {request_memory}
        request_disk = {request_disk}
        queue start,stop from {condor_dir}/segments.txt
    """
    )
    return subfile