import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

import h5py

if TYPE_CHECKING:
    import numpy as np

minmax_re = re.compile(r"min-(?P<min>[-0-9.]+)_max-(?P<max>[-0-9.]+)")


def write_data(
    write_dir: str,
    t: "np.ndarray",
    y: "np.ndarray",
    mf: Optional["np.ndarray"] = None,
):
    t0 = t[0]
    if int(t0) == t0:
        t0 = int(t0)

    length = t[-1] - t[0]
    if int(length) == length:
        length = int(length)

    if mf is not None:
        # record max and min values in filename for
        # matched filter outputs so that for a given
        # threshold we can decide whether we need to
        # look in a particular file without having to
        # waste time opening it, or for setting max and
        # min values on histogramming before going through
        # and binning everything
        fname = "min-{}_max-{}_{}-{}.hdf5".format(
            mf.min(), mf.max(), t0, length
        )
    else:
        fname = "{}-{}.hdf5".format(t0, length)

    fname = os.path.join(write_dir, fname)
    with h5py.File(fname, "w") as f:
        f["GPSstart"] = t
        f["out"] = y

        if mf is not None:
            f["filtered"] = mf
    return fname


def read_fname(fname: str) -> Tuple["np.ndarray", "np.ndarray"]:
    with h5py.File(fname, "r") as f:
        t = f["GPSstart"][:]
        y = f["out"][:, 0]
    return t, y
