"""Render a source-linked figure from the saved evidence (optional Matplotlib)."""

import csv
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":11, "text.color":"#e6edf7", "axes.labelcolor":"#a9bad0", "xtick.color":"#a9bad0", "ytick.color":"#a9bad0", "axes.edgecolor":"#314460", "axes.facecolor":"#101d30", "figure.facecolor":"#0c1422"})


def main():
    inputs=json.loads((ROOT/"demo/inputs.json").read_text())
    summary=json.loads((ROOT/"demo/summary.json").read_text())
    comparison=list(csv.DictReader((ROOT/"demo/comparison.csv").open()))
    row=next(r for r in comparison if r["decision_id"]=="SME-A-2" and r["source"]=="tax")
    records=[r for r in inputs["observations"] if r["record_id"] in ("tax-a-v1","tax-a-v2")]
    fig,(timeline,bars)=plt.subplots(2,1,figsize=(13,7.5),gridspec_kw={"height_ratios":[1.1,1]},layout="constrained")
    fig.suptitle("PITBridge  |  What was known at decision time?",fontsize=23,fontweight="bold",x=.055,ha="left")
    cutoff=datetime.fromisoformat("2026-02-15T00:00:00+00:00")
    for y,record in zip((1,0),records):
        event=datetime.fromisoformat(record["event_at"])
        available=datetime.fromisoformat(max(record["published_at"],record["ingested_at"]))
        color="#64e5c4" if available<=cutoff else "#efad70"
        timeline.plot([event,available],[y,y],color=color,linewidth=3,marker="o",markersize=8)
        timeline.annotate(f"Available {available:%b %d}",(available,y),xytext=(0,13),textcoords="offset points",color=color,ha="center")
    timeline.axvline(cutoff,color="#97c6ff",linestyle="--",linewidth=1.7)
    timeline.annotate("Decision: Feb 15",(cutoff,.5),xytext=(8,0),textcoords="offset points",color="#97c6ff")
    timeline.set_yticks([0,1],["Revision 2: 180,000 CNY","Revision 1: 100,000 CNY"])
    timeline.set_ylim(-.5,1.55)
    timeline.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    timeline.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    timeline.set_title("The event date is the same. The knowledge date is different.",loc="left",fontsize=13,pad=12)
    values=[float(row["safe_value"]),float(row["unsafe_value"])]
    bars.barh([1,0],values,color=["#64e5c4","#efad70"],height=.5)
    bars.set_yticks([1,0],["Safe snapshot","Unsafe event-only join"])
    bars.set_xlim(0,max(values)*1.25)
    bars.set_xlabel("Invoice revenue / CNY")
    bars.set_title("SME-A / Feb 15: a later correction cannot enter this decision",loc="left",fontsize=13,pad=12)
    for y,value in zip((1,0),values):
        bars.text(value+5000,y,f"{value:,.0f}",va="center",fontweight="bold")
    for ax in (timeline,bars):
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="x",color="#536981",alpha=.18)
        ax.set_axisbelow(True)
    fig.supxlabel(f"Synthetic fixture · {summary['snapshot_rows']} lookups · {summary['future_knowledge_rows']} future-data baseline selections · Source: demo/inputs.json + comparison.csv",fontsize=10,color="#8ca6bf")
    fig.savefig(ROOT/"docs/evidence.png",dpi=150)
    plt.close(fig)


if __name__=="__main__":
    main()
