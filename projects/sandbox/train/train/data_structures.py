from typing import Callable, Optional, Tuple

import numpy as np
import torch

from ml4gw.dataloading import InMemoryDataset
from ml4gw.transforms.injection import RandomWaveformInjection
from ml4gw.utils.slicing import sample_kernels


class ChannelSwapper(torch.nn.Module):
    """
    Data augmentation module that randomly swaps channels
    of a fraction of batch elements.

    Args:
        frac:
            Fraction of batch that will have channels swapped.
    """

    def __init__(self, frac: float = 0.5):
        super().__init__()
        self.frac = frac

    def forward(self, X):
        num = int(X.shape[0] * self.frac)
        indices = None
        if num > 0:
            num = num if not num % 2 else num - 1
            num = max(2, num)
            channel = torch.randint(X.shape[1], size=(num // 2,)).repeat(2)
            # swap channels from the first num / 2 elements with the
            # second num / 2 elements
            indices = torch.arange(num)
            target_indices = torch.roll(indices, shifts=num // 2, dims=0)
            X[indices, channel] = X[target_indices, channel]

        return X, indices


class ChannelMuter(torch.nn.Module):
    """
    Data augmentation module that randomly mutes 1 channel
    of a fraction of batch elements.

    Args:
        frac:
            Fraction of batch that will have channels muted.
    """

    def __init__(self, frac: float = 0.5):
        super().__init__()
        self.frac = frac

    def forward(self, X):
        num = int(X.shape[0] * self.frac)
        indices = None
        if num > 0:
            channel = torch.randint(X.shape[1], size=(num,))
            indices = torch.randint(X.shape[0], size=(num,))
            X[indices, channel] = torch.zeros(X.shape[-1], device=X.device)

        return X, indices


class BBHInMemoryDataset(InMemoryDataset):
    """
    Dataloader which samples batches of kernels
    from a single timeseries array and prepares
    corresponding target array of all 0s. Optionally
    applies a preprocessing step to both the sampled
    kernels and their targets.

    Args:
        X: Array containing multi-channel timeseries data
        kernel_size:
            The size of the kernels, in terms of number of
            samples, to sample from the timeseries.
        batch_size:
            Number of kernels to produce at each iteration.
            Represents the 0th dimension of the returned tensor.
        batches_per_epoch:
            Number of iterations dataset will perform before
            raising a `StopIteration` exception.
        preprocessor:
            Optional preprocessing step to apply to both the
            sampled kernels and their targets. If left as
            `None`, the batches and targets will be returned
            as-is.
        coincident:
            Whether to sample kernels from all channels using
            the same timesteps, or whether to sample them
            independently from across the whole timeseries.
        shuffle:
            Whether to samples kernels uniformly from the
            timeseries, or iterate through them in order.
        device:
            Device on which to host the timeseries dataset.
    """

    def __init__(
        self,
        X: np.ndarray,
        kernel_size: int,
        batch_size: int = 32,
        batches_per_epoch: Optional[int] = None,
        preprocessor: Optional[Callable] = None,
        coincident: bool = True,
        shuffle: bool = True,
        device: str = "cpu",
    ) -> None:
        super().__init__(
            X,
            kernel_size,
            batch_size=batch_size,
            stride=1,
            batches_per_epoch=batches_per_epoch,
            coincident=coincident,
            shuffle=shuffle,
            device=device,
        )
        self.preprocessor = preprocessor

    def __next__(self) -> Tuple[torch.Tensor, torch.Tensor]:
        X = super().__next__()
        y = torch.zeros((len(X), 1)).to(X.device)

        if self.preprocessor is not None:
            X, y = self.preprocessor(X, y)
        return X, y


class aframeWaveformInjection(RandomWaveformInjection):
    def __init__(
        self,
        *args,
        prob: float = 1.0,
        swap_frac: float = 0.0,
        mute_frac: float = 0.0,
        downweight: float = 1.0,
        glitch_prob: float = 0.5,
        **kwargs
    ):
        self.downweight = downweight
        self.prob = prob
        # not to sound like Fermat but I have a
        # derivation of this somewhere that I
        # can't quite find at the moment
        prob = prob / (1 - glitch_prob * (1 - downweight)) ** 2
        # account for the fact that some waveforms will have a channel
        # swapped with another waveform and labeled as noise
        prob = prob / (1 - (swap_frac + mute_frac - (swap_frac * mute_frac)))

        if not 0 < prob <= 1.0:
            raise ValueError(
                "Probability must be between 0 and 1. "
                "Adjust the value(s) of waveform_prob, "
                "glitch_prob, swap_frac, mute_frac, and/or downweight"
            )
        kwargs["prob"] = prob

        super().__init__(*args, **kwargs)
        self.channel_swapper = ChannelSwapper(frac=swap_frac)
        self.channel_muter = ChannelMuter(frac=mute_frac)

    def forward(self, X: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        if not self.training:
            return X, y

        # y == -2 means one glitch, y == -6 means two
        probs = torch.ones_like(y) * self.prob
        probs[y < 0] *= self.downweight
        probs[y < -4] *= self.downweight
        rvs = torch.rand(size=X.shape[:1], device=probs.device)
        mask = rvs < probs[:, 0]

        # sample the desired number of waveforms and inject them
        N = mask.sum().item()
        waveforms, _ = self.sample(N)
        waveforms = sample_kernels(
            waveforms,
            kernel_size=X.shape[-1],
            max_center_offset=self.trigger_offset,
            coincident=True,
        )

        waveforms, swap_indices = self.channel_swapper(waveforms)
        waveforms, mute_indices = self.channel_muter(waveforms)
        X[mask] += waveforms

        # make targets negative if they have had a channel swapped or muted
        if mute_indices is not None:
            mask[mask][mute_indices] = False

        if swap_indices is not None:
            mask[mask][swap_indices] = False

        # make targets positive if they're injected
        y[mask] = -y[mask] + 1
        return X, y


class GlitchSampler(torch.nn.Module):
    def __init__(
        self, prob: float, max_offset: int, **glitches: np.ndarray
    ) -> None:
        super().__init__()
        for ifo, glitch in glitches.items():
            self.register_buffer(ifo, torch.Tensor(glitch))

        self.prob = prob
        self.max_offset = max_offset

    def forward(self, X: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        glitch_channels = len(list(self.buffers()))
        if X.shape[1] < glitch_channels:
            raise ValueError(
                "Can't insert glitches into tensor with {} channels "
                "using glitches from {} ifos".format(
                    X.shape[1], glitch_channels
                )
            )

        # sample batch indices which will be replaced with
        # a glitch independently from each interferometer
        masks = torch.rand(size=(glitch_channels, len(X))) < self.prob
        for i, glitches in enumerate(self.buffers()):
            mask = masks[i]

            # now sample from our bank of glitches for this
            # interferometer the number we want to insert
            N = mask.sum().item()
            idx = torch.randint(len(glitches), size=(N,))

            # finally sample kernels from the selected glitches.
            # Add a dummy dimension so that sample_kernels
            # doesn't think this is a single multi-channel
            # timeseries, but rather a batch of single
            # channel timeseries
            glitches = glitches[idx, None]
            glitches = sample_kernels(
                glitches,
                kernel_size=X.shape[-1],
                max_center_offset=self.max_offset,
            )

            # replace the appropriate channel in our
            # strain data with the sampled glitches
            X[mask, i] = glitches[:, 0]

            # use bash file permissions style
            # numbers to indicate which channels
            # go inserted on
            y[mask] -= 2 ** (i + 1)
        return X, y


class SignalInverter(torch.nn.Module):
    def __init__(self, prob: float = 0.5):
        super().__init__()
        self.prob = prob

    def forward(self, X, y):
        if self.training:
            mask = torch.rand(size=X.shape[:-1]) < self.prob
            X[mask] *= -1
        return X, y


class SignalReverser(torch.nn.Module):
    def __init__(self, prob: float = 0.5):
        super().__init__()
        self.prob = prob

    def forward(self, X, y):
        if self.training:
            mask = torch.rand(size=X.shape[:-1]) < self.prob
            X[mask] = X[mask].flip(-1)
        return X, y
