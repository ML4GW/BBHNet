import logging
from pathlib import Path
from typing import List

import h5py
import numpy as np
from gwdatafind import find_urls
from gwpy.segments import DataQualityDict
from gwpy.timeseries import TimeSeries
from hermes.typeo import typeo


@typeo
def main(
    start: float,
    stop: float,
    ifos: List[str],
    sample_rate: float,
    channel: str,
    frame_type: str,
    segment_name: str,
    minimum_length: float,
    outdir: Path,
):
    """Generates background data for training BBHnet

    Args:
        start: start gpstime
        stop: stop gpstime
        ifos: which ifos to query data for
        outdir: where to store data
    """

    # query segments for each ifo
    # I think a certificate is needed for this
    segments = DataQualityDict.query_dqsegdb(
        [f"{ifo}:{segment_name}" for ifo in ifos],
        start,
        stop,
    )

    # create copy of first ifo segment list to start
    intersection = segments[f"{ifos[0]}:{segment_name}"].active.copy()

    # loop over ifos finding segment intersection
    for ifo in ifos:
        intersection &= segments[f"{ifo}:{segment_name}"].active

    # find first continuous segment of minimum length
    segment_lengths = np.array(
        [float(seg[1] - seg[0]) for seg in intersection]
    )
    continuous_segments = np.where(segment_lengths >= minimum_length)[0]

    if len(continuous_segments) == 0:
        raise ValueError(
            "No segments of minimum length, not producing background"
        )

    # choose first of such segments
    segment = intersection[continuous_segments[0]]

    logging.info(
        "Querying coincident, continuous segment "
        "from {segment[0]} to {segment[1]}"
    )

    for ifo in ifos:

        # find frame files
        files = find_urls(
            site=ifo.strip("1"),
            frametype=f"{ifo}_{frame_type}",
            gpsstart=start,
            gpsend=stop,
            urltype="file",
        )
        data = TimeSeries.read(
            files, channel=f"{ifo}:{channel}", start=segment[0], end=segment[1]
        )

        # resample
        data = data.resample(sample_rate)

        with h5py.File(outdir / f"{ifo}_background.h5", "a") as f:
            f.create_dataset("hoft", data=data)
