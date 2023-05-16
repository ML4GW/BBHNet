import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy as np
import torch
from gwpy.timeseries import TimeSeries

PATH_LIKE = Union[str, Path]

patterns = {
    "prefix": "[a-zA-Z0-9_:-]+",
    "start": "[0-9]{10}",
    "duration": "[1-9][0-9]*",
    "suffix": "(gwf)|(hdf5)|(h5)",
}
groups = {k: f"(?P<{k}>{v})" for k, v in patterns.items()}
pattern = "{prefix}-{start}-{duration}.{suffix}".format(**groups)
fname_re = re.compile(pattern)


def parse_frame_name(fname: PATH_LIKE) -> Tuple[str, int, int]:
    """Use the name of a frame file to infer its initial timestamp and length

    Expects frame names to follow a standard nomenclature
    where the name of the frame file ends {prefix}_{timestamp}-{length}.gwf

    Args:
        fname: The name of the frame file
    Returns:
        The prefix of the frame file name
        The initial GPS timestamp of the frame file
        The length of the frame file in seconds
    """

    if isinstance(fname, Path):
        fname = fname.name

    match = fname_re.search(fname)
    if match is None:
        raise ValueError(f"Could not parse frame filename {fname}")

    prefix, start, duration, *_ = match.groups()
    return prefix, int(start), int(duration)


def _is_gwf(match):
    return match is not None and match.group("suffix") == "gwf"


def get_prefix(data_dir: Path):
    if not data_dir.exists():
        raise FileNotFoundError(f"No data directory '{data_dir}'")

    fnames = map(str, data_dir.iterdir())
    matches = map(fname_re.search, fnames)
    matches = list(filter(_is_gwf, matches))

    if len(matches) == 0:
        raise ValueError(f"No valid .gwf files in data directory '{data_dir}'")

    t0 = min([int(i.group("start")) for i in matches])
    prefixes = set([i.group("prefix") for i in matches])
    if len(prefixes) > 1:
        raise ValueError(
            "Too many prefixes {} in data directory '{}'".format(
                list(prefixes), data_dir
            )
        )

    durations = set([i.group("duration") for i in matches])
    if len(durations) > 1:
        raise ValueError(
            "Too many lengths {} in data directory '{}'".format(
                list(durations), data_dir
            )
        )
    return list(prefixes)[0], int(list(durations)[0]), t0


def reset_t0(data_dir, last_t0):
    tick = time.time()
    while True:
        matches = [fname_re.search(i.name) for i in data_dir.iterdir()]
        t0s = [int(i.group("start")) for i in matches if _is_gwf(i)]
        t0 = max(t0s)
        if t0 != last_t0:
            logging.info(f"Resetting timestamp to {t0}")
            return t0

        time.sleep(1)
        elapsed = (time.time() - tick) // 1
        if not elapsed % 10:
            logging.info(
                "No new frames available since timestamp {}, "
                "elapsed time {}s".format(last_t0, elapsed)
            )


def data_iterator(
    data_dir: Path,
    channel: str,
    ifos: List[str],
    sample_rate: float,
    timeout: Optional[float] = None,
) -> torch.Tensor:
    prefix, length, t0 = get_prefix(data_dir / ifos[0])
    middle = prefix.split("_")[1]

    # give ourselves a little buffer so we don't
    # try to grab a frame that's been filtered out
    t0 += length * 2
    while True:
        frames = []
        logging.debug(f"Reading frames from timestamp {t0}")

        ready = True
        for ifo in ifos:
            prefix = f"{ifo[0]}-{ifo}_{middle}"
            fname = data_dir / ifo / f"{prefix}-{t0}-{length}.gwf"

            tick = time.time()
            while not fname.exists():
                tock = time.time()
                if timeout is not None and (tock - tick > timeout):
                    logging.warning(
                        "Couldn't find frame file {} after {}s".format(
                            fname, timeout
                        )
                    )
                    yield None, t0, False

                    t0 = reset_t0(data_dir / ifo, t0 - length)
                    break
            else:
                # we never broke, therefore the filename exists,
                # so read the strain data as well as its state
                # vector to see if its analysis ready
                x = read_channel(fname, f"{ifo}:{channel}", sample_rate)
                frames.append(x)

                state_channel = f"{ifo}:GDS-CALIB_STATE_VECTOR"
                state_vector = read_channel(fname, state_channel, 16)
                ifo_ready = ((state_vector.value & 3) == 3).all()

                # if either ifo isn't ready, mark the whole thing
                # as not ready
                if not ifo_ready:
                    logging.warning(f"IFO {ifo} not analysis ready")
                ready &= ifo_ready

                # continue so that we don't break the ifo for-loop
                continue

            # if we're here, the filename didnt' exist and
            # we broke when resetting t0, so don't bother
            # to return any data
            break
        else:
            logging.debug("Read successful")
            yield torch.Tensor(np.stack(frames)), t0, ready
            t0 += length


def resample(x: TimeSeries, sample_rate: float):
    if x.sample_rate.value != sample_rate:
        return x.resample(sample_rate)
    return x


def read_channel(fname, channel, sample_rate):
    for i in range(3):
        try:
            x = TimeSeries.read(fname, channel=channel)
        except ValueError as e:
            if str(e) == (
                "Cannot generate TimeSeries with 2-dimensional data"
            ):
                logging.warning(
                    "Channel {} from file {} got corrupted and was "
                    "read as 2D, attempting reread {}".format(
                        channel, fname, i + 1
                    )
                )
                time.sleep(1e-1)
                continue
            else:
                raise
        except RuntimeError as e:
            if str(e).startswith("Failed to read the core"):
                logging.warning(
                    "Channel {} from file {} had corrupted header, "
                    "attempting reread {}".format(channel, fname, i + 1)
                )
                time.sleep(2e-1)
                continue
            else:
                raise

        x = resample(x, sample_rate)
        if len(x) != sample_rate:
            logging.warning(
                "Channel {} in file {} got corrupted with "
                "length {}, attempting reread {}".format(
                    channel, fname, len(x), i + 1
                )
            )
            del x
            time.sleep(1e-1)
            continue

        return x
    else:
        raise ValueError(
            "Failed to read channel {} in file {}".format(channel, fname)
        )
