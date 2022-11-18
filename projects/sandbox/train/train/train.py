from pathlib import Path
from typing import Literal, Optional

import h5py
import numpy as np
from train.utils import prepare_augmentation, split
from train.validation import (
    BackgroundRecall,
    GlitchRecall,
    Recorder,
    Validator,
)

from bbhnet.architectures import Preprocessor
from bbhnet.data.dataloader import BBHInMemoryDataset
from bbhnet.logging import configure_logging
from bbhnet.trainer import trainify


def load_background(*backgrounds: Path):
    # TODO: maybe package up hanford and livingston
    # (or any arbitrary set of ifos) background files into one
    # for simplicity
    background = []
    for fname in backgrounds:
        with h5py.File(fname, "r") as f:
            hoft = f["hoft"][:]
        background.append(hoft)
    return np.stack(background)


# note that this function decorator acts both to
# wrap this function such that the outputs of it
# (i.e. the training and possible validation data)
# get passed as inputs to bbhnet.trainer.trainer.train,
# as well as to expose these arguments _as well_ as those
# from bbhnet.trainer.trainer.train to command line
# execution and parsing
@trainify
def main(
    # paths and environment args
    hanford_background: Path,
    livingston_background: Path,
    glitch_dataset: Path,
    waveform_dataset: Path,
    outdir: Path,
    logdir: Path,
    # data generation args
    glitch_prob: float,
    waveform_prob: float,
    kernel_length: float,
    sample_rate: float,
    batch_size: int,
    mean_snr: float = 8,
    std_snr: float = 4,
    min_snr: Optional[float] = None,
    highpass: Optional[float] = None,
    batches_per_epoch: Optional[int] = None,
    # preproc args
    fduration: Optional[float] = None,
    trigger_distance: float = 0,
    # validation args
    valid_frac: Optional[float] = None,
    valid_stride: Optional[float] = None,
    monitor_metric: Literal["background", "glitch"] = "glitch",
    threshold: float = 1.0,
    early_stop: Optional[int] = None,
    checkpoint_every: Optional[int] = None,
    # misc args
    device: str = "cpu",
    verbose: bool = False,
    **kwargs,
):
    """
    Prepare a dataset of background, pre-computed glitches,
    and pre-computed event waveforms to train and validate
    a BBHNet architecture.

    Args:
        hanford_background:
            Path to file containing background data for
            Hanford strain channel to train on. Should be
            an HDF5 archive with an `"hoft"` dataset
            containing the strain data.
        livingston_background:
            Path to file containing background data for
            Livingston strain channel to train on. Should be
            an HDF5 archive with an `"hoft"` dataset
            containing the strain data.
        glitch_dataset:
            Path to file containing short segments of data
            with non-Gaussian noise transients. Should be
            an HDF5 archive with datasets `"<IFO ID>_glitches"`,
            where `IFO_ID` is the short ID for each interferometer
            used for training (H1 and L1 for now). These glitches
            will be used to randomly replace the corresponding
            interferometer channel during training with some
            probability given by `glitch_prob`. Note that the
            samples selected for insertion on each channel are
            sample independently, so glitches will be inserted
            into both channels with probability `glitch_prob**2`.
        waveform_dataset:
            Path to file containing pre-computed gravitational
            wave polarization waveforms for binary-blackhole
            merger events. Should be an HDF5 archive with a
            `"signals"` dataset consisting of a tensor of shape
            `(num_waveforms, num_polarizations, waveform_size)`.
            At data-loading time, extrinsic parameters will be
            sampled for these events, which will be used to project
            them to interferometer responses which will then be
            injected into the corresponding channel with probability
            given by `waveform_prob`. Note that the samples selected
            for injection will be chosen independently of those
            selected for glitch insertion, so there is a nonzero
            likelihood that a waveform will be injected over
            a glitch. This will still be marked as a positive
            event in the training target.
        glitch_prob:
            The probability with which each sample in a batch
            will have each of its interferometer channels
            replaced with a glitch from the `glitch_dataset`.
        waveform_prob:
            The probability with which each sample in a batch
            will have a BBH waveform injected into its background.
        sample_rate:
            The rate at which all relevant input data has
            been sampled.
        kernel_length:
            The length, in seconds, of each batch element
            to produce during iteration.
        batch_size:
            Number of samples to over which to compute each
            gradient update during training.
        mean_snr:
            Mean SNR of the log-normal distribution from which
            to sample SNR values for injected waveforms at
            data loading-time.
        std_snr:
            Standard deviation of the log-normal distribution
            from which to sample SNR values for injected waveforms
            at data loading-time.
        min_snr:
            Minimum SNR to use for SNR values for injected waveforms
            at data loading-time. Samples drawn from the log-normal
            SNR distribution below this value will be clipped to it.
            If left as `None`, all sampled SNRs will be used as-is.
        highpass:
            Minimum frequency over which to compute SNR values
            for waveform injection, in Hz. If left as `None`, the
            SNR will be computed over all frequency bins.
        batches_per_epoch:
            Number of gradient updates in between each validation
            step. Implicitly controls the rate at which the learning
            can be decayed when training plateaus (since this is
            based on validation scores).
        fduration:
            Duration of the time domain filter used
            to whiten the data as a preprocessing step.
            Note that `fduration / 2` seconds worth of
            data will be cropped from both ends of the
            kernel of length `kernel_length` before passing
            it to the neural network.
        trigger_distance:
            The max length, in seconds, from the center of
            each waveform or glitch segment that a sampled
            kernel's edge can fall. The default value of `0`
            means that every kernel must contain the center
            of the corresponding segment (where the "trigger"
            or its equivalent is assumed to lie).
        valid_frac:
            Fraction of background, glitch, and waveform data
            to reserve for validation. Glitches and waveforms
            will be sampled once each, with the center of the
            segment in the center of the kernel, and either
            inserted or injected into windows of background.
        valid_stride:
            Distance, in seconds, between windows taken from
            the validation timeseries to pass to the network
            for validation.
        monitor_metric:
            Indicates whether model selection should be done
            using measurements of recall against performance
            on `"background"` or `"glitch"` data.
        threshold:
            Threshold of the indicated monitor metric against
            which to select the best-performing model. If
            `monitor_metric == "background"`, the allowed values
            are `[1, 2, 3, 4, 5]`. If `monitor_metric == "glitch"`,
            the allowed values are `[0.75, 0.9, 1]`.
        early_stop:
            Number of epochs without improvement in the indicated
            `monitor_metric` at the indicated `threshold` before
            training should be terminated. If left as `None`,
            training will continue all the way through `max_epochs`.
        checkpoint_every:
            Indicates the frequency with which model weights
            should be checkpointed regardless of validation
            metric performance. If left as `None`, no
            checkpointing will occur and only the best
            performing weights will be saved.
        device:
            Device on which to perform training. Either `"cpu"`,
            `"cuda"`, or `"cuda:<device index>"` to train on a
            specific GPU.
        verbose:
            Controls log verbosity, with the default value of
            `False` logging at level `INFO`, and `True` logging
            at level `DEBUG`.
    """

    # make out dir and configure logging file
    outdir.mkdir(exist_ok=True, parents=True)
    logdir.mkdir(exist_ok=True, parents=True)
    configure_logging(logdir / "train.log", verbose)

    # build a torch module that we'll use for doing
    # random augmentation at data-loading time
    augmenter, valid_glitches, valid_injector = prepare_augmentation(
        glitch_dataset,
        waveform_dataset,
        glitch_prob=glitch_prob,
        waveform_prob=waveform_prob,
        sample_rate=sample_rate,
        highpass=highpass,
        mean_snr=mean_snr,
        std_snr=std_snr,
        min_snr=min_snr,
        trigger_distance=trigger_distance,
        valid_frac=valid_frac,
    )

    # TODO: maybe package up hanford and livingston
    # (or any arbitrary set of ifos) background files
    # into one file for simplicity
    background = load_background(hanford_background, livingston_background)
    if valid_frac is not None:
        # split up our background data into train and validation splits
        background, valid_background = split(background, 1 - valid_frac, -1)

        # build a couple validation metrics to evaluate during training
        background_recall = BackgroundRecall(
            kernel_size=int(4 / valid_stride),
            stride=int(4 / valid_stride),
            k=5,
        )
        glitch_recall = GlitchRecall(specs=[0.75, 0.9, 1])

        # pop out one of them to monitor for model selection
        # and early-stopping purposes.
        additional = [background_recall, glitch_recall]
        if monitor_metric == "background":
            monitor = additional.pop(0)
        elif monitor_metric == "glitch":
            monitor = additional.pop(1)
        else:
            raise ValueError(f"Unknown validation metric {monitor_metric}")

        # set up a recorder which will perform evaluation,
        # model selection, and checkpointing.
        recorder = Recorder(
            outdir,
            monitor,
            threshold=threshold,
            additional=additional,
            early_stop=early_stop,
            checkpoint_every=checkpoint_every,
        )

        # pass this all to a validation callable which will
        # build the necessary datasets, compute predictions
        # on them using the model, and pass the predictions
        # to the recorder
        validator = Validator(
            recorder,
            background=valid_background,
            glitches=valid_glitches,
            injector=valid_injector,
            kernel_length=kernel_length,
            stride=valid_stride,
            sample_rate=sample_rate,
            batch_size=4 * batch_size,
            glitch_frac=glitch_prob,
            device=device,
        )
    else:
        validator = None

    # fit our waveform injector to this background
    # to facilitate the SNR remapping
    augmenter._modules["injector"].fit(H1=background[0], L1=background[1])
    for module in augmenter._modules.values():
        module.to(device)

    # create full training dataloader
    train_dataset = BBHInMemoryDataset(
        background,
        int(kernel_length * sample_rate),
        batch_size=batch_size,
        batches_per_epoch=batches_per_epoch,
        preprocessor=augmenter,
        coincident=False,
        shuffle=True,
        device=device,
    )

    # TODO: hard-coding num_ifos into preprocessor. Should
    # we just expose this as an arg? How will this fit in
    # to the broader-generalization scheme?
    preprocessor = Preprocessor(
        2,
        sample_rate,
        kernel_length,
        highpass=highpass,
        fduration=fduration,
    )

    # fit the whitening module to the background then
    # move eveyrthing to the desired device
    preprocessor.whitener.fit(background)
    preprocessor.whitener.to(device)
    return train_dataset, validator, preprocessor
