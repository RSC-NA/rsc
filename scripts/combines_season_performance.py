#!/usr/bin/env python3

import argparse
import os
from statistics import mean, stdev

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as stats


def parse_csv(csv_file: str):
    df = pd.read_csv(csv_file)
    df.set_index('RSC ID', inplace=True)
    print(df)

    return df










if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check combines participation')
    parser.add_argument(
        'combines_csv', type=str, default=None,
        help='Combines CSV file')
    parser.add_argument(
        'rpv_csv', type=str, default=None,
        help='Combines CSV file')

    argv = parser.parse_args()

    combines = parse_csv(argv.combines_csv)
    rpv = parse_csv(argv.rpv_csv)

    total_combine_players = len(combines)
    total_season_players = len(rpv)
    print(f"Total combine players: {total_combine_players}")
    print(f"Total Season players: {total_season_players}")

    average_rpv = rpv['RPV'].mean()
    print(f"Average RPV: {average_rpv}")

    pdata = {}
    for rscid, rpv in rpv.iterrows():

        try:
            cperf = combines.loc[rscid]
        except KeyError:
            print(f"No combines data for {rscid}")
            continue

        pdata[rscid] = {
            'rpv': rpv['RPV'],
            'idr': rpv['IDR'],
            'sbv': rpv['SBV'],
            'combine_games': cperf['Games'],
            'combine_win_prcnt': cperf['Win %'],
            'season_games': rpv["GP"]
        }

    print(f"Len combined: {len(pdata)}")

    zero_combines = [v["rpv"] for v in pdata.values() if v["combine_games"] == 0]
    has_combines = [v["rpv"] for v in pdata.values() if v["combine_games"] > 0]

    print(f"Total with 0 combines: {len(zero_combines)}")
    print(f"Zero Combines Mean: {mean(zero_combines)}")
    print(f"Zero Combines StdDev: {stdev(zero_combines)}")

    print(f"Total with combines: {len(has_combines)}")
    print(f"Played Combines Mean: {mean(has_combines)}")
    print(f"Played Combines StdDev: {stdev(has_combines)}")


    tresult = stats.ttest_ind(zero_combines, has_combines, equal_var=False)
    print(f"2-T: {tresult}")


    y = []
    x = []
    for v in pdata.values():
        if v['season_games'] <= 10:
            continue

        #if v["combine_games"] == 0:
        #    continue

        y.append(v['rpv'])
        x.append(v['combine_win_prcnt'])


    plt.scatter(x, y)
    plt.plot(np.unique(x), np.poly1d(np.polyfit(x, y, 1))(np.unique(x)), color="red")
    plt.xlabel("Combine Win %")
    plt.ylabel("RPV")
    plt.title("Combine Win % vs RPV (More than 10 GP in season)")
    plt.show()
