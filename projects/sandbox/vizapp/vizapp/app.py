import itertools
import logging
from pathlib import Path
from typing import TYPE_CHECKING, List

import h5py
import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Div, MultiChoice, Panel, Select, Tabs
from vizapp.distributions import get_foreground, load_results
from vizapp.plots import BackgroundPlot, EventInspectorPlot, PerfSummaryPlot

if TYPE_CHECKING:
    from vizapp.vetoes import VetoeParser


class VizApp:
    def __init__(
        self,
        timeslides_results_dir: Path,
        timeslides_strain_dir: Path,
        train_data_dir: Path,
        vetoe_parser: "VetoeParser",
        ifos: List[str],
        sample_rate: float,
        fduration: float,
        valid_frac: float,
    ) -> None:
        self.logger = logging.getLogger("vizapp")
        self.logger.debug("Loading analyzed distributions")
        self.vetoe_parser = vetoe_parser
        self.ifos = ifos

        # load in foreground and background distributions
        self.distributions = load_results(timeslides_results_dir)

        self.logger.debug("Structuring distribution events")
        self.foregrounds = {}
        for norm, results in self.distributions.items():

            foreground = get_foreground(
                results, timeslides_strain_dir, timeslides_results_dir, norm
            )
            self.foregrounds[norm] = foreground

        self.logger.debug("Configuring widgets")
        self.configure_widgets()

        # create version with vetoes
        self.logger.debug("Calculating all vetoe combinations")
        self.calculate_vetoe_distributions()

        self.logger.debug("Configuring plots")
        self.configure_plots(
            sample_rate,
            fduration,
            1 - valid_frac,
            train_data_dir,
            timeslides_strain_dir,
            timeslides_results_dir,
        )
        self.update_norm(None, None, self.norm_select.options[0])

        self.logger.info("Application ready!")

    def configure_widgets(self):
        header = Div(text="<h1>BBHNet Performance Dashboard</h1>", width=500)

        norm_options = list(self.distributions)
        if None in norm_options:
            value = None
            options = [None] + sorted([i for i in norm_options if i])
        else:
            options = sorted(norm_options)
            value = options[0]

        self.norm_select = Select(
            title="Normalization period [s]",
            value=str(value),
            options=list(map(str, options)),
        )
        self.norm_select.on_change("value", self.update_norm)

        self.vetoe_labels = ["CAT1", "CAT2", "CAT3", "GATES"]
        self.vetoe_choices = MultiChoice(
            title="Applied Vetoes", value=[], options=self.vetoe_labels
        )
        self.vetoe_choices.on_change("value", self.update_vetoes)

        self.widgets = row(header, self.norm_select, self.vetoe_choices)

    # Calculate all combinations of vetoes for each norm up front
    # so changing vetoe configurations in app is faster

    # TODO: This could also probably be a part of the
    # analysis project, and just loaded in here.
    def calculate_vetoe_distributions(self):

        self.vetoed_distributions = {}
        self.vetoed_foregrounds = {}

        # create all combos of vetoes
        for n in range(len(self.vetoe_labels) + 1):
            combos = list(itertools.combinations(self.vetoe_labels, n))
            for combo in combos:
                # sort vetoes and join to create label
                vetoe_label = "_".join(sorted(combo))
                self.logger.debug(
                    f"Calculating vetoe comboe {vetoe_label} for all norms"
                )
                # create vetoed foreground and background distributions
                self.vetoed_distributions[vetoe_label] = {}
                self.vetoed_foregrounds[vetoe_label] = {}
                # calculate this vetoe combo for each norm and store
                for norm, result in self.distributions.items():

                    background = result.background.copy()
                    for category in combo:

                        vetoes = self.vetoe_parser.get_vetoes(category)
                        background.apply_vetoes(**vetoes)

                    foreground = self.foregrounds[norm].copy()

                    foreground.fars = background.far(
                        foreground.detection_statistics
                    )
                    self.vetoed_foregrounds[vetoe_label][norm] = foreground
                    self.vetoed_distributions[vetoe_label][norm] = background

    def configure_plots(
        self,
        sample_rate,
        fduration,
        train_frac,
        train_data_dir,
        timeslides_strain_dir,
        timeslides_results_dir,
    ):
        self.perf_summary_plot = PerfSummaryPlot(300, 800)

        backgrounds = {}
        for ifo in self.ifos:
            with h5py.File(train_data_dir / f"{ifo}_background.h5", "r") as f:
                bkgd = f["hoft"][:]
                bkgd = bkgd[: int(train_frac * len(bkgd))]
                backgrounds[ifo] = bkgd

        self.event_inspector = EventInspectorPlot(
            height=300,
            width=1500,
            response_dir=timeslides_results_dir,
            strain_dir=timeslides_strain_dir,
            fduration=fduration,
            sample_rate=sample_rate,
            freq_low=30,
            freq_high=300,
            **backgrounds,
        )

        self.background_plot = BackgroundPlot(300, 1200, self.event_inspector)

        summary_tab = Panel(
            child=self.perf_summary_plot.layout, title="Summary"
        )

        analysis_layout = column(
            self.background_plot.layout, self.event_inspector.layout
        )
        analysis_tab = Panel(child=analysis_layout, title="Analysis")
        tabs = Tabs(tabs=[summary_tab, analysis_tab])
        self.layout = column(self.widgets, tabs)

    def update_norm(self, attr, old, new):
        current_vetoe_label = "_".join(sorted(self.vetoe_choices.value))
        norm = None if new == "None" else float(new)

        self.logger.debug(f"Updating plots with normalization value {norm}")
        background = self.vetoed_distributions[current_vetoe_label][norm]
        foreground = self.vetoed_foregrounds[current_vetoe_label][norm]

        self.perf_summary_plot.update(foreground)
        self.background_plot.update(foreground, background, norm)
        self.event_inspector.reset()

    def update_vetoes(self, attr, old, new):

        # retrieve the current normalization value
        current_norm = float(self.norm_select.value)

        # calculate vetoe label for this combo
        vetoe_label = "_".join(sorted(new))
        self.logger.debug(f"Applying vetoe comboe {vetoe_label}")

        # get background and foreground for this vetoe label
        background = self.vetoed_distributions[vetoe_label][current_norm]
        foreground = self.vetoed_foregrounds[vetoe_label][current_norm]
        self.logger.debug(f"{np.mean(foreground.fars)}")
        # update plots
        self.logger.debug(
            "Updating plots with new distributions after changing vetoes"
        )
        # update plots
        self.perf_summary_plot.update(foreground)
        self.background_plot.update(foreground, background, current_norm)
        self.event_inspector.reset()

    def __call__(self, doc):
        doc.add_root(self.layout)
