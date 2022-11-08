import logging
from pathlib import Path
from typing import List

from mldatafind.find import data_generator
from typeo import scriptify

from bbhnet.logging import configure_logging


@scriptify
def main(
    start: float,
    stop: float,
    sample_rate: float,
    channels: List[str],
    state_flags: List[str],
    minimum_length: float,
    datadir: Path,
    logdir: Path,
    force_generation: bool = False,
    verbose: bool = False,
):
    """
    Finds the first contiguous, coincident segments ifos`
    consistent with `segment_names`, and `minimum_length`,
    and queries strain data from `channels` training BBHnet.

    Args:
        start: start gpstime
        stop: stop gpstime
        sample_rate: Rate to sample strain data
        channels: Strain channels to query
        state_flags: Name of segments to query
        minimum_length: minimum segment length
        datadir: Directory to store data
        logdir: Directory to store log file
        force_generation: Force data to be generated even if path exists
        verbose: log verbosely

    Returns path to data
    """

    logdir.mkdir(exist_ok=True, parents=True)
    datadir.mkdir(exist_ok=True, parents=True)
    configure_logging(logdir / "generate_background.log", verbose)

    path = datadir / "background.h5"

    if path.exists() and not force_generation:
        logging.info(
            "Background data already exists"
            " and forced generation is off. Not generating background"
        )
        return

    # create and loop over generator that will query data
    # that satisfies segment criteria.
    # break since we only need one segment
    generator = data_generator(
        start, stop, channels, minimum_length, state_flags, retain_order=True
    )

    for data in generator:
        data.resample(sample_rate)
        break

    data.write(path)
    return path
