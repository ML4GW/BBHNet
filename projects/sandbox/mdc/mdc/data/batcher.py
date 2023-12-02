from typing import Iterator

import numpy as np
from ratelimiter import RateLimiter


def batch_chunks(
    it: Iterator,
    num_steps: int,
    batch_size: int,
    inference_sampling_rate: float,
    sample_rate: float,
    throughput: float,
):
    """
    Generate streaming snapshot state updates
    from a chunked dataloader at the specified
    throughput.
    """
    window_stride = int(sample_rate / inference_sampling_rate)
    step_size = batch_size * window_stride

    # enforce throughput by limiting the rate
    # at which we generate data. Factor of 1.5
    # necessary to get tests passing at the moment
    # but will need to see how this bears out in
    # production, and if it's a problem we'll just
    # have to relax the test constraints
    inf_per_second = throughput / inference_sampling_rate
    batches_per_second = inf_per_second / batch_size

    max_calls = 2
    period = 0.75 * max_calls / batches_per_second
    rate_limiter = RateLimiter(max_calls=max_calls, period=period)

    # grab data up front and refresh it when we need it
    try:
        x = next(it)
    except StopIteration:
        raise ValueError("Iterator produced no values")

    chunk_idx = 0
    for i in range(num_steps):
        start = chunk_idx * step_size
        stop = (chunk_idx + 1) * step_size

        # if we can't build an entire batch with
        # whatever data we have left, grab the
        # next chunk of data
        if stop > x.shape[-1]:
            # check if there will be any data
            # leftover at the end of this chunk
            if start < x.shape[-1]:
                remainder = x[:, :, start:]
            else:
                remainder = None

            # step the iterator and complain if
            # it has run out of data before generating
            # the amount that it advertised
            try:
                x = next(it)
            except StopIteration:
                raise ValueError(
                    "Ran out of data at iteration {} when {} "
                    "iterations were expected".format(i, num_steps)
                )

            # prepend any data leftover from the last chunk
            if remainder is not None:
                x = np.concatenate([remainder, x], axis=-1)

            # reset our per-chunk counters
            chunk_idx = 0
            start, stop = 0, step_size

        with rate_limiter:
            yield x[:, :, start:stop]

        chunk_idx += 1

    try:
        next(it)
    except StopIteration:
        return
    else:
        if x.shape[-1] < step_size:
            # It's fine that there's data available as long as it's
            # less than step_size, but we still need to iterate the
            # data loader to line up queue entries in loader.py
            try:
                x, _ = next(it)
            except StopIteration:
                return
        raise ValueError(
            "Data iterator expected to have {} "
            "steps, but data still available".format(num_steps)
        )
