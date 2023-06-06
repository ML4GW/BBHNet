from typing import Optional

import torch

from ml4gw.transforms import SpectralDensity


class Whitener(torch.nn.Module):
    def __init__(
        self,
        fduration: float,
        sample_rate: float,
        highpass: Optional[float] = None,
    ) -> None:
        super().__init__()
        self.fduration = int(fduration * sample_rate)
        window = torch.hann_window(self.fduration, dtype=torch.float64)
        self.register_buffer("window", window)

        self.sample_rate = sample_rate
        self.highpass = highpass

    def truncate_inverse_spectrum(self, psd, timesteps):
        N = (psd.size(-1) - 1) * 2
        inv_asd = 1 / psd**0.5

        if self.highpass is not None:
            idx = int(self.highpass * timesteps / self.sample_rate)
            inv_asd[:, :, :idx] = 0
        if inv_asd.shape[-1] % 2:
            inv_asd[:, :, -1] = 0

        q = torch.fft.irfft(inv_asd, n=N, norm="forward", dim=-1)
        pad = int(self.fduration // 2)

        q[:, :, :pad] *= self.window[-pad:]
        q[:, :, -pad:] *= self.window[:pad]
        if 2 * pad < q.shape[-1]:
            q[:, :, pad : q.shape[-1] - pad] = 0

        inv_asd = torch.fft.rfft(q, n=N, norm="forward", dim=-1)
        inv_asd *= inv_asd.conj()
        psd = 1 / inv_asd.abs()
        return psd / 2

    def forward(self, X, psds):
        num_freqs = X.shape[-1] // 2 + 1
        if psds.shape[-1] != num_freqs:
            psds = torch.nn.functional.interpolate(psds, size=(num_freqs,))
        psds = self.truncate_inverse_spectrum(psds, X.shape[-1])

        # compute the FFT of the section we want to whiten
        # and divide it by the ASD of the background section.
        # If the ASD of any background bin hit inf, set the
        # corresponding bin to 0
        X_tilde = torch.fft.rfft(X.double(), norm="forward", dim=-1)
        X_tilde = X_tilde / psds**0.5
        X_tilde[torch.isnan(X_tilde)] = 0

        # convert back to the time domain and normalize
        # TODO: what's this normalization factor?
        X = torch.fft.irfft(X_tilde, norm="forward", dim=-1)
        X = X.float() / (self.sample_rate) ** 0.5

        # slice off corrupted data at edges of kernel
        pad = int(self.fduration // 2)
        X = X[:, :, pad:-pad]
        return X


class Preprocessor(torch.nn.Module):
    """
    Module for encoding aframe preprocessing procedure.
    """

    def __init__(
        self,
        background_length: float,
        sample_rate: float,
        fduration: float,
        fftlength: float,
        average: str = "mean",
        overlap: Optional[float] = None,
        highpass: Optional[float] = None,
    ) -> None:
        super().__init__()
        self.background_size = int(background_length * sample_rate)
        self.spectral_density = SpectralDensity(
            sample_rate, fftlength, overlap, average, fast=highpass is not None
        )
        self.whitener = Whitener(fduration, sample_rate, highpass)

    def forward(self, X):
        # split X into the section used to compute the PSD
        # and the section we actually want to whiten
        splits = [self.background_size, X.shape[-1] - self.background_size]
        background, X = torch.split(X, splits, dim=-1)

        psds = self.spectral_density(background)
        return self.whitener(X, psds)
