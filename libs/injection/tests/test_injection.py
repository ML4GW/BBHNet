#!/usr/bin/env python
# coding: utf-8
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

import bbhnet.injection

TEST_DIR = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def data_dir():
    data_dir = "tmp"
    os.makedirs(data_dir, exist_ok=True)
    yield Path(data_dir)
    shutil.rmtree(data_dir)


@pytest.fixture(scope="session")
def H1_frame():
    frame_path = "H1_test_frame.gwf"
    if not os.path.exists(frame_path):
        H1_frame = TimeSeries.fetch_open_data(
            "H1", 1185587200, 1185591296 + 1e-5
        )
        H1_frame.write(frame_path)
    yield frame_path
    os.remove(frame_path)


@pytest.fixture(scope="session")
def L1_frame():
    frame_path = "L1_test_frame.gwf"
    if not os.path.exists(frame_path):
        L1_frame = TimeSeries.fetch_open_data(
            "L1", 1185587200, 1185591296 + 1e-5
        )
        L1_frame.write(frame_path)
    yield frame_path
    os.remove(frame_path)


@pytest.fixture(params=[["H1"], ["H1", "L1"]])
def ifos(request):
    return request.param


@pytest.fixture(params=[50, 10, 50])
def n_samples(request):
    return request.param


@pytest.fixture(params=[60, 8, 60])
def waveform_duration(request):
    return request.param


@pytest.fixture(params=["nonspin_BBH.prior", "precess_tides.prior"])
def prior_file(request):
    return str(TEST_DIR / "prior_files" / request.param)


@pytest.fixture(params=[[2, 5], [25, 50], [100, 500]])
def snr_range(request):
    return request.param


@pytest.mark.parametrize(
    "kwargs",
    [
        (dict(duration=16),),
        (dict(sampling_frequency=128, waveform_approximant="TaylorF2"),),
    ],
)
def test_get_waveform_generator(kwargs):
    (kwargs,) = kwargs
    waveform_generator = bbhnet.injection.injection.get_waveform_generator(
        **kwargs
    )
    sampling_kwargs = {
        "duration",
        "sampling_frequency",
        "frequency_domain_source_model",
        "parameter_conversion",
    }
    waveform_kwargs = {
        "waveform_approximant",
        "reference_frequency",
        "minimum_frequency",
    }

    for k in sampling_kwargs:
        assert hasattr(waveform_generator, k)
        if k in kwargs:
            assert getattr(waveform_generator, k) == kwargs[k]

    assert hasattr(waveform_generator, "waveform_arguments")

    for k in waveform_kwargs:
        assert waveform_generator.waveform_arguments.get(k)
        if k in kwargs:
            assert waveform_generator.waveform_arguments.get(k) == kwargs[k]


@patch("bbhnet.injection.injection.apply_high_pass_filter")
def test_generate_gw(mock_filter):
    """Test generate_gw using supplied waveform generator, or
    initializing generator
    """
    import bilby

    sample_params = bilby.gw.prior.BBHPriorDict().sample(10)

    with patch("bilby.gw.waveform_generator.WaveformGenerator") as mock_gen:
        bbhnet.injection.injection.generate_gw(
            sample_params,
            waveform_generator=None,
            waveform_approximant="TaylorF2",
            sampling_frequency=128,
        )

    assert mock_gen.call_count == 1

    dummy_waveform_generator = bilby.gw.waveform_generator.WaveformGenerator(
        frequency_domain_source_model=bilby.gw.source.lal_binary_black_hole,
        duration=1,
        sampling_frequency=128,
    )
    mock_gen.reset_mock()
    with patch("bilby.gw.waveform_generator.WaveformGenerator") as mock_gen:
        bbhnet.injection.injection.generate_gw(
            sample_params, waveform_generator=dummy_waveform_generator
        )

    assert mock_gen.call_count == 0


def test_signal_data_shape(
    data_dir,
    ifos,
    H1_frame,
    L1_frame,
    n_samples,
    waveform_duration,
    prior_file,
):

    if len(ifos) == 1:
        frame_files = [H1_frame]
        channels = ["Strain"]
    else:
        frame_files = [H1_frame, L1_frame]
        channels = ["Strain", "Strain"]

    frames, signal_file = bbhnet.injection.inject_signals(
        frame_files,
        channels,
        ifos,
        prior_file,
        n_samples,
        data_dir,
        waveform_duration=waveform_duration,
    )

    sample_rate = TimeSeries.read(
        frame_files[0], channels[0]
    ).sample_rate.value
    signal_length = waveform_duration * sample_rate

    with h5py.File(signal_file, "r") as f:
        for key in f["signal_params"].keys():
            act_shape = f["signal_params"][key].shape
            exp_shape = (n_samples,)
            assert (
                act_shape == exp_shape
            ), f"Expected shape {exp_shape} for {key}, found {act_shape}"

        for ifo in ifos:
            act_shape = f[ifo]["snr"].shape
            exp_shape = (n_samples,)
            assert (
                act_shape == exp_shape
            ), f"Expected shape {exp_shape} for {key}, found {act_shape}"

            act_shape = f[ifo]["signal"].shape
            exp_shape = (n_samples, signal_length)
            assert (
                act_shape == exp_shape
            ), f"Expected shape {exp_shape} for {key}, found {act_shape}"

        act_shape = f["GPS-start"].shape
        exp_shape = (n_samples,)
        assert (
            act_shape == exp_shape
        ), f"Expected shape {exp_shape} for {key}, found {act_shape}"


def test_snr_range(data_dir, ifos, H1_frame, L1_frame, snr_range):
    n_samples = 10
    waveform_duration = 8

    if len(ifos) == 1:
        frame_files = [H1_frame]
        channels = ["Strain"]
    else:
        frame_files = [H1_frame, L1_frame]
        channels = ["Strain", "Strain"]

    _, signal_file = bbhnet.injection.inject_signals(
        frame_files,
        channels,
        ifos,
        prior_file=str(TEST_DIR / "prior_files" / "nonspin_BBH.prior"),
        n_samples=n_samples,
        outdir=data_dir,
        waveform_duration=waveform_duration,
        snr_range=snr_range,
    )

    snr_list = []
    with h5py.File(signal_file, "r") as f:
        for ifo in ifos:
            snr_list.append(f[ifo]["snr"][:])
        mean_snrs = np.sqrt(np.sum(np.square(snr_list), axis=0))
        if mean_snrs.size > 0:
            assert all(snr_range[0] < mean_snrs) and all(
                mean_snrs < snr_range[1]
            ), f"Some of {mean_snrs} not in {snr_range}"


def test_signal_injected(data_dir, ifos, H1_frame, L1_frame):
    n_samples = 1
    waveform_duration = 8

    if len(ifos) == 1:
        frame_files = [H1_frame]
        channels = ["Strain"]
    else:
        frame_files = [H1_frame, L1_frame]
        channels = ["Strain", "Strain"]

    out_frames, signal_file = bbhnet.injection.inject_signals(
        frame_files,
        channels,
        ifos,
        prior_file=str(TEST_DIR / "prior_files" / "nonspin_BBH.prior"),
        n_samples=n_samples,
        outdir=data_dir,
        waveform_duration=waveform_duration,
    )

    with h5py.File(signal_file, "r") as f:
        signal_times = f["signal_params"]["geocent_time"][:]

        for n in range(n_samples):
            for i, ifo in enumerate(ifos):
                orig_data = TimeSeries.read(frame_files[i], channels[i])
                inj_data = TimeSeries.read(out_frames[i], channels[i])
                sample_rate = orig_data.sample_rate.value
                signal_time = signal_times[n]
                signal = f[ifo]["signal"][n, :]

                idx1 = int((signal_time - waveform_duration / 2) * sample_rate)
                idx2 = int(idx1 + waveform_duration * sample_rate)

                exp_output = signal + orig_data.value[idx1:idx2]
                act_output = inj_data.value[idx1:idx2]

                assert all(
                    exp_output == act_output
                ), f"Sum of signal {n} and orignal data does not match \
                    injected data for {ifo}"
