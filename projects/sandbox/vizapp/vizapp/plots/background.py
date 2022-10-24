import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    BoxSelectTool,
    ColumnDataSource,
    HoverTool,
    LogAxis,
    Range1d,
    TapTool,
)
from bokeh.plotting import figure
from vizapp import palette


def find_glitches(events, times, shifts):
    unique_times, counts = np.unique(times, return_counts=True)
    mask = counts > 1
    unique_times, counts = unique_times[mask], counts[mask]

    centers, shift_groups = [], []
    for t in unique_times:
        mask = times == t
        values = events[mask]
        shift_values = shifts[mask]
        centers.append(np.median(values))
        shift_groups.append(shift_values)
    return unique_times, counts, centers, shift_groups


class BackgroundPlot:
    def __init__(
        self,
        height: int,
        width: int,
        event_inspector,
    ) -> None:
        self.configure_sources()
        self.configure_plots(height, width)
        self.event_inspector = event_inspector

    def configure_plots(self, height: int, width: int):
        self.distribution_plot = figure(
            height=height // 2,
            width=width,
            y_axis_type="log",
            x_axis_label="Detection statistic",
            y_axis_label="Survival function",
            # dummy range values to allow
            # updating later
            y_range=(0, 1),
            tools="box_zoom,reset",
        )
        # self.distribution_plot.toolbar.autohide = True
        self.distribution_plot.yaxis.axis_label_text_color = palette[0]

        self.distribution_plot.vbar(
            "center",
            top="top",
            bottom=0.1,
            width="width",
            fill_color=palette[0],
            line_color="#000000",
            fill_alpha=0.4,
            line_alpha=0.6,
            line_width=0.5,
            selection_fill_alpha=0.6,
            selection_line_alpha=0.8,
            nonselection_fill_alpha=0.2,
            nonselection_line_alpha=0.3,
            legend_label="Background",
            source=self.bar_source,
        )

        box_select = BoxSelectTool(dimensions="width")
        self.distribution_plot.add_tools(box_select)
        self.bar_source.selected.on_change("indices", self.update_background)

        self.distribution_plot.extra_y_ranges = {"SNR": Range1d(1, 10)}
        axis = LogAxis(
            axis_label="SNR",
            axis_label_text_color=palette[1],
            y_range_name="SNR",
        )
        self.distribution_plot.add_layout(axis, "right")

        r = self.distribution_plot.circle(
            "detection_statistic",
            "snr",
            size="size",
            fill_color=palette[1],
            line_color=palette[1],
            line_width=0.5,
            fill_alpha=0.2,
            line_alpha=0.4,
            selection_fill_alpha=0.2,
            selection_line_alpha=0.3,
            nonselection_fill_alpha=0.2,
            nonselection_line_alpha=0.3,
            y_range_name="SNR",
            legend_label="Events",
            source=self.foreground_source,
        )

        hover = HoverTool(
            tooltips=[
                ("Hanford GPS time", "@{event_time}{0.000}"),
                ("Shift", "@shift"),
                ("SNR", "@snr"),
                ("Detection statistic", "@{detection_statistic}"),
                ("Chirp Mass", "@{chirp_mass}"),
            ],
            renderers=[r],
        )
        self.distribution_plot.add_tools(hover)

        tap = TapTool()
        self.foreground_source.selected.on_change(
            "indices", self.inspect_event
        )
        self.distribution_plot.add_tools(tap)

        self.background_plot = figure(
            height=height // 2,
            width=width,
            title="",
            x_axis_label="GPS Time [s]",
            y_axis_label="Detection statistic",
            tools="box_zoom,reset",
        )
        # self.background_plot.toolbar.autohide = True

        self.background_plot.circle(
            "x",
            "detection_statistic",
            fill_color="color",
            fill_alpha=0.5,
            line_color="color",
            line_alpha=0.7,
            hover_fill_color="color",
            hover_fill_alpha=0.7,
            hover_line_color="color",
            hover_line_alpha=0.9,
            size="size",
            legend_group="label",
            source=self.background_source,
        )

        hover = HoverTool(
            tooltips=[
                ("GPS time", "@{event_time}{0.000}"),
                ("Detection statistic", "@{detection_statistic}"),
                ("Count", "@count"),
            ]
        )
        self.background_plot.add_tools(hover)
        self.background_plot.legend.click_policy = "hide"

        tap = TapTool()
        self.background_source.selected.on_change(
            "indices", self.inspect_glitch
        )
        self.background_plot.add_tools(tap)

        self.layout = column([self.distribution_plot, self.background_plot])

    def configure_sources(self):
        self.bar_source = ColumnDataSource(dict(center=[], top=[], width=[]))

        self.foreground_source = ColumnDataSource(
            dict(
                detection_statistic=[],
                event_time=[],
                shift=[],
                snr=[],
                chirp_mass=[],
                size=[],
            )
        )

        self.background_source = ColumnDataSource(
            dict(
                x=[],
                event_time=[],
                detection_statistic=[],
                color=[],
                label=[],
                count=[],
                shift=[],
                size=[],
            )
        )

    def update_source(self, source, **kwargs):
        source.data = kwargs

    def update(self, foreground, background, norm):
        self.background = background
        self.norm = norm

        title = (
            "Distribution of {} background events from "
            "{:0.2f} days worth of data; SNR vs. detection "
            "statistic of {} injections overlayed"
        ).format(
            len(background.events),
            background.Tb / 3600 / 24,
            len(foreground.event_times),
        )
        self.distribution_plot.title = title
        self.distribution_plot.extra_y_ranges["SNR"].start = (
            0.5 * foreground.snrs.min()
        )
        self.distribution_plot.extra_y_ranges["SNR"].end = (
            2 * foreground.snrs.max()
        )

        hist, bins = np.histogram(background.events, bins=100)
        hist = np.cumsum(hist[::-1])[::-1]
        self.distribution_plot.y_range.start = 0.1
        self.distribution_plot.y_range.end = 2 * hist.max()

        self.update_source(
            self.bar_source,
            center=(bins[:-1] + bins[1:]) / 2,
            top=hist,
            width=0.95 * (bins[1:] - bins[:-1]),
        )

        self.update_source(
            self.foreground_source,
            detection_statistic=foreground.detection_statistics,
            event_time=foreground.event_times,
            shift=foreground.shifts,
            snr=foreground.snrs,
            chirp_mass=foreground.chirps,
            size=foreground.chirps / 8,
        )

        # clear the background plot until we select another
        # range of detection characteristics to plot
        self.update_source(
            self.background_source,
            x=[],
            event_time=[],
            detection_statistic=[],
            color=[],
            label=[],
            count=[],
            shift=[],
            size=[],
        )
        self.background_plot.title.text = (
            "Select detection characteristic range above"
        )
        self.background_plot.xaxis.axis_label = "GPS Time [s]"

    def update_background(self, attr, old, new):
        if len(new) < 2:
            return

        stats = np.array(self.bar_source.data["center"])
        min_ = min([stats[i] for i in new])
        max_ = max([stats[i] for i in new])
        mask = self.background.events >= min_
        mask &= self.background.events <= max_

        self.background_plot.title.text = (
            f"{mask.sum()} events with detection statistic in the range"
            f"({min_:0.1f}, {max_:0.1f})"
        )
        events = self.background.events[mask]
        h1_times = self.background.event_times[mask]
        shifts = self.background.shifts[mask][:, 1]
        l1_times = h1_times + shifts

        unique_h1_times, h1_counts, h1_centers, h1_shifts = find_glitches(
            events, h1_times, shifts
        )
        unique_l1_times, l1_counts, l1_centers, l1_shifts = find_glitches(
            events, l1_times, shifts
        )

        centers = h1_centers + l1_centers
        times = np.concatenate([unique_h1_times, unique_l1_times])
        counts = np.concatenate([h1_counts, l1_counts])
        shifts = h1_shifts + l1_shifts
        colors = [palette[0]] * len(h1_counts) + [palette[1]] * len(l1_counts)
        labels = ["Hanford"] * len(h1_counts) + ["Livingston"] * len(l1_counts)

        t0 = h1_times.min()
        self.background_plot.xaxis.axis_label = f"Time from {t0:0.3f} [s]"
        self.background_plot.legend.visible = True
        self.update_source(
            self.background_source,
            x=times - t0,
            event_time=times,
            detection_statistic=centers,
            color=colors,
            label=labels,
            count=counts,
            shift=shifts,
            size=2 * (counts**0.8),
        )

    def inspect_event(self, attr, old, new):
        if len(new) != 1:
            return

        idx = new[0]
        event_time = self.foreground_source.data["event_time"][idx]
        shift = self.foreground_source.data["shift"][idx]
        snr = self.foreground_source.data["snr"][idx]
        chirp_mass = self.foreground_source.data["chirp_mass"][idx]
        self.event_inspector.update(
            event_time,
            "foreground",
            shift,
            norm=self.norm,
            SNR=snr,
            chirp_mass=chirp_mass,
        )

    def inspect_glitch(self, attr, old, new):
        if len(new) != 1:
            return
        idx = new[0]
        event_time = self.background_source.data["event_time"][idx]
        shift = self.background_source.data["shift"][idx][0]
        self.event_inspector.update(
            event_time, "background", [0.0, shift], self.norm
        )
