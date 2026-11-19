"""Isochrone maps: stations reachable within N minutes from an origin."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .csa import ScanResult


def travel_time_frame(res: ScanResult, stations: pd.DataFrame) -> pd.DataFrame:
    """Station table with travel minutes from the origin."""
    minutes = res.travel_minutes()
    df = stations.loc[[s for s in minutes]].copy()
    df["minutes"] = [minutes[s] for s in df.index]
    return df


def plot_isochrone(
    res: ScanResult,
    stations: pd.DataFrame,
    origin_name: str,
    out_path: str,
    max_minutes: int = 60,
    step: int = 10,
) -> pd.DataFrame:
    """Static scatter map of stations colored by travel time band."""
    df = travel_time_frame(res, stations)
    df = df[df.minutes <= max_minutes]
    fig, ax = plt.subplots(figsize=(9, 9))
    bands = list(range(step, max_minutes + step, step))
    cmap = plt.get_cmap("viridis_r", len(bands))
    for band in reversed(bands):
        sub = df[(df.minutes > band - step) & (df.minutes <= band)]
        if len(sub):
            ax.scatter(sub.stop_lon, sub.stop_lat, s=22, color=cmap(bands.index(band)),
                       label=f"<= {band} min", linewidths=0)
    o = stations.loc[res.origin]
    ax.scatter([o.stop_lon], [o.stop_lat], marker="*", s=260, color="red",
               edgecolor="black", zorder=5, label=origin_name)
    ax.set_title(f"Temps de trajet en metro depuis {origin_name}\n(horaires theoriques IDFM, sans perturbations)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_aspect(1 / 0.67)  # lon/lat aspect at Paris latitude
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return df


def animate_isochrone(
    res: ScanResult,
    stations: pd.DataFrame,
    origin_name: str,
    out_path: str,
    max_minutes: int = 45,
    step: int = 5,
) -> None:
    """GIF of the reachable area growing minute-band by minute-band."""
    from matplotlib.animation import FuncAnimation, PillowWriter

    df = travel_time_frame(res, stations)
    df = df[df.minutes <= max_minutes]
    o = stations.loc[res.origin]
    bands = list(range(step, max_minutes + step, step))

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_xlim(stations.stop_lon.min() - 0.01, stations.stop_lon.max() + 0.01)
    ax.set_ylim(stations.stop_lat.min() - 0.01, stations.stop_lat.max() + 0.01)
    ax.set_aspect(1 / 0.67)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    scat = ax.scatter([], [], s=26, linewidths=0)
    ax.scatter([o.stop_lon], [o.stop_lat], marker="*", s=260, color="red", edgecolor="black", zorder=5)
    title = ax.set_title("")

    def update(frame: int):
        band = bands[frame]
        sub = df[df.minutes <= band]
        scat.set_offsets(list(zip(sub.stop_lon, sub.stop_lat)))
        scat.set_color(plt.get_cmap("viridis_r")(sub.minutes / max_minutes))
        title.set_text(f"Depuis {origin_name} : <= {band} min (horaires theoriques)")
        return scat, title

    anim = FuncAnimation(fig, update, frames=len(bands), interval=700)
    anim.save(out_path, writer=PillowWriter(fps=1.5))
    plt.close(fig)
