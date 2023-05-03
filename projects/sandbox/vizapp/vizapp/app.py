import logging
from pathlib import Path
from typing import TYPE_CHECKING, List

import bilby
import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Div, MultiChoice, TabPanel, Tabs
from vizapp.pages import AnalysisPage, DataPage, SummaryPage

from bbhnet.analysis.ledger.events import (
    RecoveredInjectionSet,
    TimeSlideEventSet,
)
from bbhnet.analysis.ledger.injections import InjectionParameterSet

if TYPE_CHECKING:
    from astropy.cosmology import Cosmology
    from vizapp.vetoes import VetoParser


class VizApp:
    def __init__(
        self,
        base_directory: Path,
        data_directory: Path,
        cosmology: "Cosmology",
        source_prior: "bilby.core.prior.PriorDict",
        ifos: List[str],
        sample_rate: float,
        fduration: float,
        valid_frac: float,
        veto_parser: "VetoParser",
    ) -> None:
        self.logger = logging.getLogger("vizapp")
        self.logger.debug("Loading analyzed distributions")

        # set a bunch of attributes
        self.veto_parser = veto_parser
        self.ifos = ifos
        self.source_prior = source_prior
        self.cosmology = cosmology
        self.sample_rate = sample_rate
        self.fduration = fduration
        self.valid_frac = valid_frac

        # load results and data from the run we're visualizing
        infer_dir = base_directory / "infer"
        rejected = data_directory / "test" / "rejected_parameters.h5"
        self.background = TimeSlideEventSet.read(infer_dir / "background.h5")
        self.foreground = RecoveredInjectionSet.read(
            infer_dir / "foreground.h5"
        )
        self.rejected_params = InjectionParameterSet.read(rejected)

        # move injection masses to source frame
        for obj in [self.foreground, self.rejected_params]:
            for i in range(2):
                attr = f"mass_{i + 1}"
                value = getattr(obj, attr)
                setattr(obj, attr, value / (1 + obj.redshift))

        # initialize all our pages and their constituent plots
        self.pages, tabs = [], []
        for page in [DataPage, SummaryPage, AnalysisPage]:
            page = page(self)
            self.pages.append(page)

            tab = TabPanel(child=page.get_layout(), title=page.name)
            tabs.append(tab)

        # set upour veto selecter and set up the initially
        # blank veto mask, use this to update the sources
        # for all our pages
        self.veto_selecter = self.get_veto_selecter()
        self.veto_selecter.on_change(self.update_vetos)
        self.update_vetos(None, None, [])

        # set up a header with a title and the selecter
        title = Div(text="<h1>BBHNet Performance Dashboard</h1>", width=500)
        header = row(title, self.veto_selecter)

        # generate the final layout
        tabs = Tabs(tabs=tabs)
        self.layout = column(header, tabs)
        self.logger.info("Application ready!")

    def get_veto_selecter(self):
        options = ["CAT1", "CAT2", "CAT3", "GATES"]
        self.vetoes = {}
        for label in options:
            vetos = self.veto_parser.get_vetoes(label)
            veto_mask = False
            for ifo in self.ifos:
                segments = vetos[ifo]

                # this will have shape
                # (len(segments), len(self.background))
                mask = segments[:, :1] < self.background.time
                mask &= segments[:, 1:] > self.background.time

                # mark a background event as vetoed
                # if it falls into _any_ of the segments
                veto_mask |= mask.any(axis=0)
            self.vetoes[label] = veto_mask

        self.veto_mask = np.zeros_like(mask, dtype=bool)
        return MultiChoice(title="Applied Vetoes", value=[], options=options)

    def update_vetos(self, attr, old, new):
        if not new:
            # no vetoes selected, so mark all background
            # events as not-vetoed
            self.veto_mask = np.zeros_like(self.veto_mask, dtype=bool)
        else:
            # mark a background event as vetoed if any
            # of the currently selected labels veto it
            mask = False
            for label in new:
                mask |= self.vetoes[label]
            self.veto_mask = mask

        # now update all our pages to factor
        # in the vetoed data
        for page in self.pages:
            page.update()

    def __call__(self, doc):
        doc.add_root(self.layout)
