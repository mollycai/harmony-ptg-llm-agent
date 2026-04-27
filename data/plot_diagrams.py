from __future__ import annotations

import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".cache"
MPL_CACHE_DIR = CACHE_DIR / "matplotlib"
CACHE_DIR.mkdir(exist_ok=True)
MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_DIR))
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import pandas as pd


DATA_DIR = SCRIPT_DIR
RESULTS_PATH = DATA_DIR / "results.xlsx"

LLM_RANDOM_SHEET = "LMT vs RT"
LLM_SA_SHEET = "LMT vs SAMT"

METHOD_STYLES = {
    "LLM-PTGC for Testing": {
        "color": "#1D4E89",
        "marker": "o",
        "linestyle": "-",
        "markersize": 4,
    },
    "SA-PTGC for Testing": {
        "color": "#C26A3D",
        "marker": "D",
        "linestyle": "--",
        "markersize": 3.5,
        "markerfacecolor": "white",
        "markeredgewidth": 1.0,
    },
    "Random Testing": {
        "color": "#6C8EAD",
        "marker": "^",
        "linestyle": "-.",
        "markersize": 4,
    },
}

PLOT_CONFIGS = [
    {
        "filename": "pc_vs_time.pdf",
        "x_key": "time",
        "y_key": "pc",
        "xlabel": "Time (seconds)",
        "ylabel": "Page Coverage (PC)",
    },
    {
        "filename": "sc_vs_time.pdf",
        "x_key": "time",
        "y_key": "sc",
        "xlabel": "Time (seconds)",
        "ylabel": "State Coverage (SC)",
    },
    {
        "filename": "an_vs_time.pdf",
        "x_key": "time",
        "y_key": "an",
        "xlabel": "Time (seconds)",
        "ylabel": "Action Number (AN)",
    },
    {
        "filename": "pc_vs_an.pdf",
        "x_key": "an",
        "y_key": "pc",
        "xlabel": "Action Number (AN)",
        "ylabel": "Page Coverage (PC)",
    },
    {
        "filename": "sc_vs_an.pdf",
        "x_key": "an",
        "y_key": "sc",
        "xlabel": "Action Number (AN)",
        "ylabel": "State Coverage (SC)",
    },
]

LEFT_MARGIN_IN = 1.05
RIGHT_MARGIN_IN = 0.18
BOTTOM_MARGIN_IN = 0.72
TOP_MARGIN_IN = 0.18
AXES_WIDTH_IN = 4.0
AXES_HEIGHT_IN = 3.0
Y_TICK_LABEL_WIDTH = 5
Y_TICK_LABEL_FONT = "DejaVu Sans Mono"


def build_method_frame(
    df: pd.DataFrame,
    time_col: str,
    sc_col: str,
    pc_col: str,
    an_col: str,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "time": df[time_col],
            "sc": df[sc_col],
            "pc": df[pc_col],
            "an": df[an_col],
        }
    )
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["time", "sc", "pc", "an"])
    frame = frame.drop_duplicates(subset=["time"], keep="first")
    return frame.sort_values("time").reset_index(drop=True)


def ensure_same_series(
    left: pd.Series,
    right: pd.Series,
    series_name: str,
) -> None:
    left_numeric = pd.to_numeric(left.reset_index(drop=True), errors="coerce")
    right_numeric = pd.to_numeric(right.reset_index(drop=True), errors="coerce")

    if len(left_numeric) != len(right_numeric):
        raise ValueError(f"Inconsistent {series_name} between Excel sheets.")

    if not (left_numeric - right_numeric).abs().fillna(float("inf")).le(1e-9).all():
        raise ValueError(f"Inconsistent {series_name} between Excel sheets.")


def align_on_common_time(
    datasets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    common_time = None
    for df in datasets.values():
        time_set = set(df["time"].tolist())
        common_time = time_set if common_time is None else common_time & time_set

    if not common_time:
        raise ValueError("No shared time points found across the Excel sheets.")

    ordered_time = sorted(common_time)
    aligned = {}
    for method_name, df in datasets.items():
        aligned_df = df[df["time"].isin(ordered_time)].copy()
        aligned_df = aligned_df.sort_values("time").reset_index(drop=True)
        aligned[method_name] = aligned_df

    return aligned


def load_comparison_data() -> dict[str, pd.DataFrame]:
    llm_random_df = pd.read_excel(RESULTS_PATH, sheet_name=LLM_RANDOM_SHEET)
    llm_sa_df = pd.read_excel(RESULTS_PATH, sheet_name=LLM_SA_SHEET)

    llm_df = build_method_frame(
        llm_random_df,
        time_col="Times(s)",
        sc_col="LLM PTG-based Testing SC",
        pc_col="LLM PTG-based Testing PC",
        an_col="LLM PTG-based Testing AN",
    )
    llm_df_from_sa_sheet = build_method_frame(
        llm_sa_df,
        time_col="Times(s)",
        sc_col="LLM PTG-based Testing SC",
        pc_col="LLM PTG-based Testing PC",
        an_col="LLM PTG-based Testing AN",
    )
    sa_df = build_method_frame(
        llm_sa_df,
        time_col="Times(s)",
        sc_col="SA PTG-based Testing SC",
        pc_col="SA PTG-based Testing PC",
        an_col="SA PTG-based Testing AN",
    )
    random_df = build_method_frame(
        llm_random_df,
        time_col="Times(s)",
        sc_col="Random Testing SC",
        pc_col="Random Testing PC",
        an_col="Random Testing AN",
    )

    datasets = align_on_common_time(
        {
            "LLM PTG-based Testing": llm_df,
            "SA PTG-based Testing": sa_df,
            "Random Testing": random_df,
            "__llm_from_sa_sheet__": llm_df_from_sa_sheet,
        }
    )

    ensure_same_series(
        datasets["LLM PTG-based Testing"]["time"],
        datasets["__llm_from_sa_sheet__"]["time"],
        "time axis",
    )
    ensure_same_series(
        datasets["LLM PTG-based Testing"]["sc"],
        datasets["__llm_from_sa_sheet__"]["sc"],
        "LLM SC",
    )
    ensure_same_series(
        datasets["LLM PTG-based Testing"]["pc"],
        datasets["__llm_from_sa_sheet__"]["pc"],
        "LLM PC",
    )
    ensure_same_series(
        datasets["LLM PTG-based Testing"]["an"],
        datasets["__llm_from_sa_sheet__"]["an"],
        "LLM AN",
    )

    return {
        "LLM-PTGC for Testing": datasets["LLM PTG-based Testing"],
        "SA-PTGC for Testing": datasets["SA PTG-based Testing"],
        "Random Testing": datasets["Random Testing"],
    }


def create_figure_with_fixed_axes() -> tuple[plt.Figure, plt.Axes]:
    fig_width = LEFT_MARGIN_IN + AXES_WIDTH_IN + RIGHT_MARGIN_IN
    fig_height = BOTTOM_MARGIN_IN + AXES_HEIGHT_IN + TOP_MARGIN_IN
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    fig.subplots_adjust(
        left=LEFT_MARGIN_IN / fig_width,
        right=1 - RIGHT_MARGIN_IN / fig_width,
        bottom=BOTTOM_MARGIN_IN / fig_height,
        top=1 - TOP_MARGIN_IN / fig_height,
    )
    return fig, ax


def save_figure(fig: plt.Figure, output_path: Path) -> None:
    fig.savefig(output_path, bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def format_y_axis(ax: plt.Axes, y_key: str) -> None:
    if y_key in {"pc", "sc"}:
        ax.yaxis.set_major_formatter(
            StrMethodFormatter(f"{{x:>{Y_TICK_LABEL_WIDTH}.3f}}")
        )
    elif y_key == "an":
        ax.yaxis.set_major_formatter(
            StrMethodFormatter(f"{{x:>{Y_TICK_LABEL_WIDTH}.0f}}")
        )

    for label in ax.get_yticklabels():
        label.set_fontfamily(Y_TICK_LABEL_FONT)


def plot_metric(
    datasets: dict[str, pd.DataFrame],
    x_key: str,
    y_key: str,
    xlabel: str,
    ylabel: str,
    output_path: Path,
) -> None:
    fig, ax = create_figure_with_fixed_axes()

    for method_name, df in datasets.items():
        style = METHOD_STYLES[method_name]
        plot_df = df.sort_values(x_key).reset_index(drop=True)
        ax.plot(
            plot_df[x_key],
            plot_df[y_key],
            label=method_name,
            color=style["color"],
            marker=style["marker"],
            linestyle=style["linestyle"],
            linewidth=1.8,
            markersize=style.get("markersize", 5.5),
            markevery=style.get("markevery"),
            markerfacecolor=style.get("markerfacecolor", style["color"]),
            markeredgewidth=style.get("markeredgewidth", 0.8),
        )

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    format_y_axis(ax, y_key)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    save_figure(fig, output_path)


def main() -> None:
    datasets = load_comparison_data()

    for config in PLOT_CONFIGS:
        plot_metric(
            datasets=datasets,
            x_key=config["x_key"],
            y_key=config["y_key"],
            xlabel=config["xlabel"],
            ylabel=config["ylabel"],
            output_path=DATA_DIR / config["filename"],
        )


if __name__ == "__main__":
    main()
