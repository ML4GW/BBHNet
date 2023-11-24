import astropy.cosmology as cosmo
import numpy as np
from bilby.core.prior import (
    ConditionalPowerLaw,
    ConditionalPriorDict,
    Constraint,
    Cosine,
    Gaussian,
    LogNormal,
    PowerLaw,
    PriorDict,
    Sine,
    Uniform,
)
from bilby.gw.prior import UniformComovingVolume, UniformSourceFrame

from aframe.priors.utils import (
    mass_condition_powerlaw,
    mass_constraints,
    read_priors_from_file,
)

# default cosmology
COSMOLOGY = cosmo.Planck15

# Unit names
msun = r"$M_{\odot}$"
mpc = "Mpc"
rad = "rad"


def uniform_extrinsic() -> PriorDict:
    """
    Define a Bilby `PriorDict` containing distributions that are
    uniform over the allowed ranges of extrinsic binary black hole
    parameters.
    """
    prior = PriorDict()
    prior["dec"] = Cosine()
    prior["ra"] = Uniform(0, 2 * np.pi)
    prior["theta_jn"] = Sine()
    prior["phase"] = Uniform(0, 2 * np.pi)

    return prior


def uniform_spin() -> PriorDict:
    """
    Define a Bilby `PriorDict` containing distributions that are
    uniform over the allowed ranges of binary black hole spin
    parameters.
    """
    prior = PriorDict()
    prior["psi"] = Uniform(0, np.pi)
    prior["a_1"] = Uniform(0, 0.998)
    prior["a_2"] = Uniform(0, 0.998)
    prior["tilt_1"] = Sine(unit=rad)
    prior["tilt_2"] = Sine(unit=rad)
    prior["phi_12"] = Uniform(0, 2 * np.pi)
    prior["phi_jl"] = Uniform(0, 2 * np.pi)
    return prior


def nonspin_bbh(cosmology: cosmo.Cosmology = COSMOLOGY) -> PriorDict:
    """
    Define a Bilby `PriorDict` that describes a reasonable population
    of non-spinning binary black holes

    Masses are defined in the detector frame.

    Args:
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = uniform_extrinsic()
    prior["mass_1"] = Uniform(5, 100, unit=msun)
    prior["mass_2"] = Uniform(5, 100, unit=msun)
    prior["mass_ratio"] = Constraint(0, 1)
    prior["redshift"] = UniformSourceFrame(
        0, 0.5, name="redshift", cosmology=cosmology
    )
    prior["psi"] = 0
    prior["a_1"] = 0
    prior["a_2"] = 0
    prior["tilt_1"] = 0
    prior["tilt_2"] = 0
    prior["phi_12"] = 0
    prior["phi_jl"] = 0

    detector_frame_prior = True
    return prior, detector_frame_prior


def spin_bbh(cosmology: cosmo.Cosmology = COSMOLOGY) -> PriorDict:
    """
    Define a Bilby `PriorDict` that describes a reasonable population
    of spin-aligned binary black holes

    Masses are defined in the detector frame.

    Args:
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = uniform_extrinsic()
    prior["mass_1"] = Uniform(5, 100, unit=msun)
    prior["mass_2"] = Uniform(5, 100, unit=msun)
    prior["mass_ratio"] = Constraint(0, 1)
    prior["redshift"] = UniformSourceFrame(
        0, 0.5, name="redshift", cosmology=cosmology
    )
    prior["psi"] = 0
    prior["a_1"] = Uniform(0, 0.998)
    prior["a_2"] = Uniform(0, 0.998)
    prior["tilt_1"] = Sine(unit=rad)
    prior["tilt_2"] = Sine(unit=rad)
    prior["phi_12"] = 0
    prior["phi_jl"] = 0

    detector_frame_prior = True
    return prior, detector_frame_prior


def nonspin_bns(cosmology: cosmo.Cosmology = COSMOLOGY) -> PriorDict:
    """
    Define a Bilby `PriorDict` that describes a reasonable population
    of non-spinning binary black holes

    Masses are defined in the detector frame.

    Args:
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = PriorDict()
    prior["mass1"] = Uniform(0.5, 5, unit=msun)
    prior["mass2"] = Uniform(0.5, 5, unit=msun)
    prior["mass_ratio"] = UniformInComponentsMassRatio(
        name='mass_ratio', minimum=0.125, maximum=1)

    #tidal deformability parameter
    prior['lambda_tilde'] = Uniform(0, 5000, name='lambda_tilde')
    prior['delta_lambda'] = Uniform(-5000, 5000, name='delta_lambda')

    prior["redshift"] = UniformSourceFrame(
        0, 0.5, name="redshift", cosmology=cosmology)
    prior["chirp_mass"] = UniformInComponentsChirpMass(
        name='chirp_mass', minimum=0.4, maximum=4.4)
    prior["distance"] = UniformSourceFrame(
        name='luminosity_distance', minimum=1e2, maximum=5e3)
    prior["dec"] = Cosine(name='dec')
    prior["ra"] = Uniform(name='ra', minimum=0, maximum=2 * np.pi, boundary='periodic')
    prior["theta_jn"] = Sine(name='theta_jn')
    prior["phase"] = Uniform(name='phase', minimum=0, maximum=2 * np.pi, boundary='periodic')
    prior["psi"] = Uniform(name='psi', minimum=0, maximum=np.pi, boundary='periodic')
    prior["chi_1"] = AlignedSpin(name='chi_1', a_prior=Uniform(minimum=0, maximum=0.99))
    prior["chi_2"] = AlignedSpin(name='chi_2', a_prior=Uniform(minimum=0, maximum=0.99))

    prior["phi_jl"] = 0

    detector_frame_prior = True

    return prior, detector_frame_prior


def end_o3_ratesandpops(
    cosmology: cosmo.Cosmology = COSMOLOGY,
) -> ConditionalPriorDict:
    """
    Define a Bilby `PriorDict` that matches the distributions used
    by the LIGO Rates and Populations group for pipeline searches
    at the end of the third observing run.

    Masses are defined in the source frame.

    Args:
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = ConditionalPriorDict(uniform_extrinsic())
    prior["mass_1"] = PowerLaw(alpha=-2.35, minimum=5, maximum=100, unit=msun)
    prior["mass_2"] = ConditionalPowerLaw(
        condition_func=mass_condition_powerlaw,
        alpha=1,
        minimum=5,
        maximum=100,
        unit=msun,
    )
    prior["redshift"] = UniformComovingVolume(
        0, 2, name="redshift", cosmology=cosmology
    )
    spin_prior = uniform_spin()
    for key, value in spin_prior.items():
        prior[key] = value
    detector_frame_prior = False
    return prior, detector_frame_prior


def power_law_dip_break():
    """
    Create a Bilby `PriorDict` from a set of sampled parameters
    following the Power Law + Dip + Break model,
    see https://dcc.ligo.org/LIGO-T2100512/public

    Masses are defined in the source frame.

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = uniform_extrinsic()
    event_file = "./event_files/\
        O1O2O3all_mass_h_iid_mag_iid_tilt_powerlaw_redshift_maxP_events_bbh.h5"
    prior |= read_priors_from_file(event_file)

    detector_frame_prior = False
    return prior, detector_frame_prior


def gaussian_masses(
    m1: float,
    m2: float,
    sigma: float = 2,
    cosmology: cosmo.Cosmology = COSMOLOGY,
):
    """
    Construct a gaussian bilby prior for masses.

    Masses are defined in the source frame.

    Args:
        m1:
            Mean of the Gaussian distribution for mass 1
        m2:
            Mean of the Gaussian distribution for mass 2
        sigma:
            Standard deviation of the Gaussian distribution for both masses
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = PriorDict(conversion_function=mass_constraints)
    prior["mass_1"] = Gaussian(name="mass_1", mu=m1, sigma=sigma)
    prior["mass_2"] = Gaussian(name="mass_2", mu=m2, sigma=sigma)
    prior["redshift"] = UniformSourceFrame(
        name="redshift", minimum=0, maximum=2, cosmology=cosmology
    )
    prior["dec"] = Cosine(name="dec")
    prior["ra"] = Uniform(
        name="ra", minimum=0, maximum=2 * np.pi, boundary="periodic"
    )

    detector_frame_prior = False
    return prior, detector_frame_prior


def get_log_normal_params(mean, std):
    """
    Calculate the mean and standard deviation of the normal
    distribution associated with the lognormal distribution
    defined by the given mean and standard deviation
    """
    sigma = np.log((std / mean) ** 2 + 1) ** 0.5
    mu = 2 * np.log(mean / (mean**2 + std**2) ** 0.25)
    return mu, sigma


def log_normal_masses(
    m1: float,
    m2: float,
    sigma: float = 2,
    cosmology: cosmo.Cosmology = COSMOLOGY,
):
    """
    Construct a log normal bilby prior for masses.

    Masses are defined in the source frame.

    Args:
        m1:
            Mean of the Log Normal distribution for mass 1
        m2:
            Mean of the Log Normal distribution for mass 2
        sigma:
            Standard deviation for m1 and m2
        cosmology:
            An `astropy` cosmology, used to determine redshift sampling

    Returns:
        prior:
            `PriorDict` describing the binary black hole population
        detector_frame_prior:
            Boolean indicating which frame masses are defined in
    """
    prior = PriorDict(conversion_function=mass_constraints)

    mu1, sigma1 = get_log_normal_params(m1, sigma)
    mu2, sigma2 = get_log_normal_params(m2, sigma)
    prior["mass_1"] = LogNormal(name="mass_1", mu=mu1, sigma=sigma1)
    prior["mass_2"] = LogNormal(name="mass_2", mu=mu2, sigma=sigma2)
    prior["mass_ratio"] = Constraint(0.02, 1)

    prior["redshift"] = UniformSourceFrame(
        name="redshift", minimum=0, maximum=2, cosmology=cosmology
    )
    prior["dec"] = Cosine(name="dec")
    prior["ra"] = Uniform(
        name="ra", minimum=0, maximum=2 * np.pi, boundary="periodic"
    )

    detector_frame_prior = False
    return prior, detector_frame_prior
