import datetime
import os
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import requests
import seaborn as sns
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from scipy.stats import kurtosis, norm, percentileofscore, skew
from stocksymbol import StockSymbol


def calculate_tpsl(close_prices, tp, sl):
    """
    For each closing price, calculate if T/P or S/L is hit first and after how many days.

    :param close_prices: A pandas Series of closing prices.
    :param tp: Target profit level as a positive float (e.g., 0.05 for 5%).
    :param sl: Stop loss level as a negative float (e.g., -0.05 for -5%).
    :return: A DataFrame with columns 'Hit' (T/P or S/L), 'Wait' days to hit and Returns
    """
    # Calculate daily returns
    returns = close_prices.pct_change()

    # Create a DataFrame to hold results
    results = pd.DataFrame(index=close_prices.index, columns=["Hit", "Wait", "Returns"])

    # Loop over the close prices
    for i in range(len(close_prices)):
        # Calculate the cumulative return from the current day forward
        forward_returns = (1 + returns.iloc[i:]).cumprod() - 1

        # Check if T/P or S/L is hit first
        tp_hit_days = forward_returns[forward_returns >= tp].index.min()
        sl_hit_days = forward_returns[forward_returns <= sl].index.min()

        # Determine which comes first, T/P or S/L
        if pd.isnull(tp_hit_days) and pd.isnull(sl_hit_days):
            # Neither T/P nor S/L is hit
            results.at[close_prices.index[i], "Hit"] = None
            results.at[close_prices.index[i], "Wait"] = None
            results.at[close_prices.index[i], "Returns"] = None
        elif pd.isnull(sl_hit_days) or (
            not pd.isnull(tp_hit_days) and tp_hit_days < sl_hit_days
        ):
            # T/P is hit first
            results.at[close_prices.index[i], "Hit"] = "TP"
            results.at[close_prices.index[i], "Wait"] = (
                tp_hit_days - close_prices.index[i]
            ).days
            results.at[close_prices.index[i], "Returns"] = forward_returns.loc[
                tp_hit_days
            ]
        else:
            # S/L is hit first
            results.at[close_prices.index[i], "Hit"] = "SL"
            results.at[close_prices.index[i], "Wait"] = (
                sl_hit_days - close_prices.index[i]
            ).days
            results.at[close_prices.index[i], "Returns"] = forward_returns.loc[
                sl_hit_days
            ]

    return results.dropna().astype(
        {"Hit": "str", "Wait": "int32", "Returns": "float64"}
    )


def get_fundamentals(symbol):
    load_dotenv()
    api_key = os.getenv("API_KEY_ALPHA_VANTAGE")
    url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={api_key}"
    response = requests.get(url)
    return response.json()


def get_markets(simplify=True):
    response = requests.get("https://stock-symbol.herokuapp.com/api/market/all")
    json_data = response.json()
    if simplify:
        datasets = []
        for item in json_data["data"]:
            temp = pd.DataFrame(item.get("index"))
            temp["market"] = item.get("market")
            temp["abbreviation"] = item.get("abbreviation")
            datasets.append(temp)
        data = (
            pd.concat(datasets).sort_values(by=["market", "id"]).reset_index(drop=True)
        )
        return data
    else:
        return json_data


def get_symbols(market=None, index=None, symbols_only: str = None, simplify=True):
    load_dotenv()
    api_key = os.getenv("API_KEY_STOCK_SYMBOL")
    ss = StockSymbol(api_key)
    results = ss.get_symbol_list(market=market, index=index, symbols_only=symbols_only)
    if simplify:
        return sorted(
            list(
                filter(
                    None,
                    [x.get("symbol") for x in results],
                )
            )
        )
    else:
        return results


def convert_date(x):
    return datetime.datetime.utcfromtimestamp(x).strftime("%Y-%m-%d")


def find_below_threshold_missingness(
    data: pd.DataFrame, threshold: float = 0.0
) -> List:
    return (
        (data.isnull().sum() / data.shape[0])
        .loc[lambda x: x <= threshold]
        .index.tolist()
    )


def rebalance_weights(weights: np.ndarray, threshold: float = 0.0001) -> np.ndarray:
    weights[weights < threshold] = 0
    total_weight = np.sum(weights)
    if total_weight < 0:
        weights = weights / total_weight
    return weights


def annual_risk_return(
    data: pd.DataFrame, risk_free_rate: float = 0.017
) -> pd.DataFrame:
    pl_data = pl.from_pandas(data)
    returns = pl_data.select(
        [(pl.col(column).mean().alias(column)) for column in pl_data.columns]
    )
    risk = pl_data.select(
        [(pl.col(column).std().alias(column)) for column in pl_data.columns]
    )
    pd_returns = returns.to_pandas().T
    pd_risk = risk.to_pandas().T
    summary = pd.DataFrame(
        {
            "Returns": pd_returns.sum(axis=1) * 252,
            "Risk": pd_risk.sum(axis=1) * np.sqrt(252),
        }
    )
    summary["Sharpe"] = (summary.Returns - risk_free_rate) / summary.Risk
    return summary


def rank_fundamentals(fundamentals):
    pass
    # for column, preference in metrics.items():
    #     col_name = f"{column}_{preference}"
    #     if preference == "high_is_better":
    #         fundamentals[f"{column}_rank"] = fundamentals[col_name].rank(ascending=False)
    #     else:
    #         fundamentals[f"{column}_rank"] = fundamentals[col_name].rank(ascending=True)
    # fundamentals["overall_score"] = fundamentals[
    #     [f"{column}_rank" for column in metrics.keys()]
    # ].sum(axis=1)
    # return fundamentals.sort_values(by="overall_score")


def plot_assets_density(df):
    # Number of assets
    n_assets = df.shape[1]
    # Create a grid of plots
    fig, axes = plt.subplots(
        nrows=(n_assets + 1) // 2, ncols=2, figsize=(14, 2.5 * n_assets)
    )
    # Flatten the axes for easy iteration
    axes = axes.flatten()
    # Define the standard deviations and their corresponding probabilities
    stds = [1, 2, 3]
    probs = [0.68, 0.95, 0.997]
    outprobs = [0.16, 0.025, 0.0015]
    for i, col in enumerate(df.columns):
        # Calculate the first four moments
        mu = df[col].mean()
        sigma = df[col].std()
        skewness = skew(df[col])
        kurt = kurtosis(df[col])
        # Plot the density of the returns
        sns.kdeplot(df[col], ax=axes[i], shade=True, label="Observed Returns")
        # Plot the normal distribution for comparison
        x = np.linspace(df[col].min(), df[col].max(), 100)
        y = norm.pdf(x, mu, sigma)
        axes[i].plot(x, y, "r--", label="Normal Distribution")
        # Add vertical barriers and annotations
        for std, prob, outprob in zip(stds, probs, outprobs):
            # Theoretical barriers
            left_theoretical = mu - std * sigma
            right_theoretical = mu + std * sigma
            axes[i].axvline(left_theoretical, color="blue", linestyle="--", alpha=0.5)
            axes[i].axvline(right_theoretical, color="blue", linestyle="--", alpha=0.5)
            # Observed barriers
            left_observed = np.percentile(df[col], (1 - prob) / 2 * 100)
            right_observed = np.percentile(df[col], (1 + prob) / 2 * 100)
            axes[i].axvline(left_observed, color="green", linestyle="-.", alpha=0.5)
            axes[i].axvline(right_observed, color="green", linestyle="-.", alpha=0.5)
            # Annotations
            theoretical_pct = prob
            theoretical_pct_out = outprob
            observed_pct_left = percentileofscore(df[col], left_theoretical) / 100
            observed_pct_right = 1 - percentileofscore(df[col], right_theoretical) / 100
            axes[i].annotate(
                f"{theoretical_pct*100:.1f}% or {theoretical_pct_out:.2%} outside",
                (left_theoretical, 0),
                textcoords="offset points",
                # xytext=(-10, -10),
                xytext=(0, 60),
                ha="center",
                fontsize=8,
                color="blue",  # Color for theoretical
                rotation=25,
            )
            axes[i].annotate(
                f"{observed_pct_left*100:.1f}% outside",
                (left_theoretical, 0),
                textcoords="offset points",
                # xytext=(-10, -25),
                xytext=(0, 30),
                ha="center",
                fontsize=8,
                color="green",  # Color for observed
                rotation=25,
            )
            axes[i].annotate(
                f"{theoretical_pct*100:.1f}% or {theoretical_pct_out:.2%} outside",
                (right_theoretical, 0),
                textcoords="offset points",
                # xytext=(10, -10),
                xytext=(20, 60),
                ha="center",
                fontsize=8,
                color="blue",  # Color for theoretical
                rotation=25,
            )
            axes[i].annotate(
                f"{observed_pct_right*100:.1f}% outside",
                (right_theoretical, 0),
                textcoords="offset points",
                # xytext=(10, -25),
                xytext=(20, 30),
                ha="center",
                fontsize=8,
                color="green",  # Color for observed
                rotation=25,
            )
        # Set the title and subtitle
        title = f"Asset: {col}"
        subtitle = f"Mean: {mu:.2f}, Std: {sigma:.2f}, Skewness: {skewness:.2f}, Kurtosis: {kurt:.2f}"
        axes[i].set_title(title)
        axes[i].set_xlabel(subtitle)
        axes[i].legend()
    # Remove any unused subplots
    if n_assets % 2 != 0:
        fig.delaxes(axes[-1])
    plt.tight_layout()
    plt.show()


def plot_portfolios(
    assets_data: pd.DataFrame,
    portfolio_data: pd.DataFrame,
    optimization_data: pd.DataFrame = None,
    annotate: bool = False,
    size: int = 15,
):
    # TODO vmin & vmax should be calculated based on the data
    # calculate max sharpe ratio portfolio
    max_sharpe_idx = portfolio_data.Sharpe.idxmax()
    max_sharpe = portfolio_data.loc[max_sharpe_idx]
    plt.figure(figsize=(15, 8))
    # plot generated portfolios
    plt.scatter(
        x=portfolio_data.loc[:, "Risk"],
        y=portfolio_data.loc[:, "Returns"],
        c=portfolio_data.loc[:, "Sharpe"],
        cmap="coolwarm",
        s=15,
        vmin=0.5,
        vmax=1.00,
        alpha=0.8,
    )
    plt.colorbar()
    # plot original assets used to generate portfolios
    plt.scatter(
        x=assets_data.loc[:, "Risk"],
        y=assets_data.loc[:, "Returns"],
        c=assets_data.loc[:, "Sharpe"],
        cmap="coolwarm",
        s=60,
        vmin=0.5,
        vmax=1.00,
        alpha=0.8,
        marker="D",
    )
    if annotate:
        for i in assets_data.index:
            plt.annotate(
                i,
                xy=(
                    assets_data.loc[assets_data.index == i, "Risk"].squeeze(),
                    assets_data.loc[assets_data.index == i, "Returns"].squeeze(),
                ),
                size=size,
            )
    # plot max sharpe ratio portfolio
    plt.scatter(
        x=max_sharpe["Risk"],
        y=max_sharpe["Returns"],
        c="orange",
        s=400,
        marker="*",
    )
    # plot optimization portfolio
    if not optimization_data is None:
        plt.scatter(
            x=optimization_data["Risk"],
            y=optimization_data["Returns"],
            c="red",
            s=400,
            marker="X",
        )
    plt.xlabel("Ann Risk (std)", fontsize=15)
    plt.ylabel("Ann Returns", fontsize=15)
    plt.title("Risk/Return/Sharpe Ratio", fontsize=20)
    plt.show()
