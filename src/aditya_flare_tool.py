#!/usr/bin/env python3
"""
aditya_flare_tool.py  —  a plain-words, multi-source X-ray flare analyzer.

READS (auto-detected):
  * Aditya-L1 HEL1OS   (hard X-ray FITS: light curves + spectra)   -- TESTED
  * Aditya-L1 SoLEXS   (soft X-ray FITS: light curves + spectra)   -- format-compatible
  * Chandrayaan-2 XSM  (soft X-ray FITS: .lc light curves, .pha spectra) -- format-compatible
  * GOES XRS           (soft X-ray flux: FITS / CSV / JSON columns) -- format-compatible
  * Generic CSV        (any time + rate/flux columns)

WHAT IT DOES (no FITS knowledge needed):
  - Point it at a file OR a folder. It decides what each file is.
  - Light curves -> plots them, finds flares (adaptive background), and for
    flux data (GOES/XSM) assigns an A/B/C/M/X class. Writes a flare catalog CSV.
  - Spectra -> stacks the flare, subtracts quiet background, prints hardness ratio.

USAGE:
  python aditya_flare_tool.py FILE_OR_FOLDER [options]

  --outdir DIR        where to save outputs (default: next to the data)
  --gain KEV          approx keV/channel for spectra (default 0.35; estimate)
  --time-col NAME     force the time column name   (override auto-detect)
  --rate-col NAME     force the rate/flux column name (override auto-detect)
  --time-format FMT   one of: mjd | iso | sec | unix | cxc   (override)
  --flux              treat the rate column as physical flux (W/m^2) -> A-X class

REQUIREMENTS:  pip install astropy numpy matplotlib
"""
import sys, os, glob, argparse, csv
import numpy as np
from astropy.io import fits
from astropy.time import Time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ----- column-name synonyms (lowercase) -------------------------------------
TIME_COLS = ["mjd", "time", "time_tag", "timestamp", "tstart", "t_start",
             "date", "datetime", "jd", "seconds"]
RATE_COLS = ["ctr", "rate", "count_rate", "counts", "flux", "xrsb", "xrsb_flux",
             "b_flux", "b_avg", "long", "xl", "observed_flux", "irradiance"]
SPEC_COUNT_COLS = ["counts", "counts_per_channel", "rate"]
CHAN_COLS = ["channel", "pi", "pha", "chan"]

# GOES / NOAA flare class thresholds in W/m^2 (1-8 Angstrom long channel)
GOES_CLASS = [("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)]


def goes_class(peak_flux):
    for letter, base in GOES_CLASS:
        if peak_flux >= base:
            return f"{letter}{peak_flux / base:.1f}"
    return f"<A ({peak_flux:.1e})"


def channel_type(label):
    """Decide if a source is HARD or SOFT X-ray, from its name."""
    L = (label or "").upper()
    if "HEL1OS" in L or "CDTE" in L:
        return "hard"          # HEL1OS 8-150 keV
    if "SOLEXS" in L or "XSM" in L or "GOES" in L or "XRS" in L:
        return "soft"          # SoLEXS / XSM / GOES soft X-ray
    # fall back on energy band in the label, e.g. "5.00KEV_TO_20.00KEV"
    if "KEV" in L:
        try:
            hi = float(L.split("_TO_")[1].replace("KEV", ""))
            return "hard" if hi >= 30 else "soft"
        except Exception:
            pass
    return "soft"


# ----------------------------------------------------------------------------
# File classification
# ----------------------------------------------------------------------------
def classify_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt", ".json"):
        return "table"
    if ext in (".nc",):
        return "goes_nc"
    try:
        with fits.open(path) as h:
            names = [hdu.name.upper() for hdu in h]
            cols = []
            for hdu in h:
                if getattr(hdu, "columns", None) is not None:
                    cols += [c.upper() for c in hdu.columns.names]
            # event lists: per-photon rows with a real energy column
            if any("EVENT" in n for n in names) or ("ENER" in cols and "MJD" in cols):
                return "events"
            if "SPECTRUM" in names or "CHANNEL" in cols or "PHA" in names or "PI" in cols:
                # spectrum unless it clearly has a per-time rate table only
                if "CHANNEL" in cols or "PI" in cols:
                    return "spectrum"
            if any("LC" in n for n in names) or "CTR" in cols or "RATE" in cols or "FLUX" in cols:
                return "lightcurve"
            if "CHANNEL" in cols:
                return "spectrum"
    except Exception as e:
        print("   ! could not open", path, ":", e)
    return "unknown"


# ----------------------------------------------------------------------------
# Generic time + rate extraction from any table HDU / CSV
# ----------------------------------------------------------------------------
def find_col(available, preferred, candidates):
    avail_lower = {c.lower(): c for c in available}
    if preferred and preferred.lower() in avail_lower:
        return avail_lower[preferred.lower()]
    for cand in candidates:
        if cand in avail_lower:
            return avail_lower[cand]
    return None


def to_mjd(timevals, fmt, hdr=None):
    """Convert an array of time values to MJD floats given a format hint."""
    timevals = np.asarray(timevals)
    if fmt == "mjd":
        return timevals.astype(float)
    if fmt == "iso":
        return Time([str(x) for x in timevals]).mjd
    if fmt == "unix":               # seconds since 1970
        return Time(timevals.astype(float), format="unix").mjd
    if fmt == "cxc":                # seconds since 1998.0 (Chandra/XSM MET style)
        return Time(timevals.astype(float), format="cxcsec").mjd
    if fmt == "sec":                # seconds from observation start in header
        base = None
        if hdr is not None:
            d = hdr.get("DATE_OBS") or hdr.get("DATE-OBS")
            t = hdr.get("TIME_OBS") or "00:00:00"
            if d:
                base = Time(f"{d}T{t}").mjd if "T" not in str(d) else Time(str(d)).mjd
        if base is None:
            base = 0.0
        return base + timevals.astype(float) / 86400.0
    # auto: guess from magnitude
    v = timevals.astype(float)
    if v.max() < 1e5 and v.min() >= 0:        # looks like seconds-from-start
        return to_mjd(v, "sec", hdr)
    if 4e4 < np.median(v) < 8e4:              # looks like MJD
        return v
    if v.max() > 1e8:                          # looks like unix/cxc seconds
        return to_mjd(v, "unix", hdr)
    return v


def guess_time_format(name, hdr):
    n = name.lower()
    if n == "mjd":
        return "mjd"
    if n in ("date", "datetime", "time_tag", "timestamp"):
        return "iso"
    if hdr and hdr.get("DATE_OBS") and n in ("tstart", "time"):
        return "sec"
    return "auto"


def read_lightcurve_table(path, kind, time_col, rate_col, time_fmt):
    """Return (mjd, rate, label, hdr) from a FITS or CSV light curve."""
    if kind == "table":  # CSV
        import numpy.lib.recfunctions as rfn
        data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")
        names = list(data.dtype.names)
        tc = find_col(names, time_col, TIME_COLS)
        rc = find_col(names, rate_col, RATE_COLS)
        if tc is None or rc is None:
            raise ValueError(f"CSV needs time & rate columns; found {names}")
        tvals, rvals = data[tc], data[rc]
        fmt = time_fmt or guess_time_format(tc, None)
        mjd = to_mjd(tvals, fmt, None)
        return mjd, np.asarray(rvals, float), rc, None

    # FITS: pick the widest-band table that has a usable rate column
    with fits.open(path) as h:
        best = None  # (span, idx)
        for i, hdu in enumerate(h):
            if getattr(hdu, "columns", None) is None:
                continue
            names = list(hdu.columns.names)
            tc = find_col(names, time_col, TIME_COLS)
            rc = find_col(names, rate_col, RATE_COLS)
            if tc is None or rc is None:
                continue
            # band span from HDU name if present (prefer widest)
            span = 0.0
            try:
                lo, hi = hdu.name.upper().split("BAND_")[1].replace("KEV", "").split("_TO_")
                span = float(hi) - float(lo)
            except Exception:
                span = 0.0
            if best is None or span > best[0]:
                best = (span, i, tc, rc)
        if best is None:
            raise ValueError("no usable time+rate columns found in FITS")
        _, idx, tc, rc = best
        d = h[idx].data
        hdr = h[idx].header
        label = f"{hdr.get('DETNAM','')} {h[idx].name.split('BAND_')[-1]}".strip()
        fmt = time_fmt or guess_time_format(tc, hdr)
        mjd = to_mjd(d[tc], fmt, hdr)
        return mjd, np.asarray(d[rc], float), label, hdr


# ----------------------------------------------------------------------------
# Flare detection (works on counts OR flux)
# ----------------------------------------------------------------------------
def rolling_median(x, w):
    out = np.empty_like(x); half = w // 2
    for i in range(len(x)):
        out[i] = np.median(x[max(0, i - half): i + half + 1])
    return out


def detect_flares(mjd, rate, is_flux=False):
    order = np.argsort(mjd); mjd, rate = mjd[order], rate[order]
    binsec = 60
    t0 = mjd.min()
    idx = ((mjd - t0) * 86400 / binsec).astype(int)
    nb = idx.max() + 1
    s = np.zeros(nb); n = np.zeros(nb)
    np.add.at(s, idx, rate); np.add.at(n, idx, 1.0)
    br = np.divide(s, n, out=np.zeros(nb), where=n > 0)
    bt = Time(t0 + np.arange(nb) * binsec / 86400, format="mjd").datetime

    bg = rolling_median(br, 41)
    resid = br - bg
    sigma = np.median(np.abs(resid - np.median(resid))) * 1.4826 + 1e-30
    if is_flux:
        # flux spans orders of magnitude -> require a clear multiplicative rise
        flaring = (br > bg * 1.5) & (br > np.nanmedian(br[br > 0]) * 1.3)
        absmin = 0
    else:
        absmin = 3
        flaring = (br > bg + 5 * sigma) & (br > bg + absmin)

    flares = []; i = 0
    while i < nb:
        if flaring[i]:
            j = i
            while j + 1 < nb and flaring[j + 1]:
                j += 1
            if (j - i) >= 2:
                pk = i + int(np.argmax(br[i:j + 1]))
                flares.append(dict(start=bt[i], peak=bt[pk], end=bt[j],
                                   peak_val=float(br[pk]), dur_min=int(j - i + 1)))
            i = j + 1
        else:
            i += 1
    return bt, br, bg, flares


# ----------------------------------------------------------------------------
# Analyzers
# ----------------------------------------------------------------------------
def analyze_lightcurve(path, kind, outdir, args):
    base = os.path.splitext(os.path.basename(path))[0]
    mjd, rate, label, hdr = read_lightcurve_table(
        path, kind, args.time_col, args.rate_col, args.time_format)
    is_flux = args.flux or ("flux" in (args.rate_col or "").lower()) or \
              ("xrs" in label.lower()) or ("flux" in label.lower())
    bt, br, bg, flares = detect_flares(mjd, rate, is_flux=is_flux)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(bt, br, lw=0.9, color="#1f6feb", label=f"{label or base} (60 s)")
    ax.plot(bt, bg, lw=1.0, color="#888", ls="--", label="adaptive background")
    for fl in flares:
        ax.axvspan(fl["start"], fl["end"], color="gold", alpha=0.25)
    ax.set_yscale("log" if is_flux else "symlog")
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Flux (W/m$^2$)" if is_flux else "Count rate (counts/s)")
    ax.set_title(f"{base}  —  {len(flares)} flare(s) detected")
    ax.legend(); ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    png = os.path.join(outdir, base + "_lightcurve.png")
    fig.savefig(png, dpi=130); plt.close(fig)

    print(f"   light curve: {len(flares)} flare(s) -> {os.path.basename(png)}")
    rows = []
    for k, fl in enumerate(flares, 1):
        cls = goes_class(fl["peak_val"]) if is_flux else ""
        extra = f"  class {cls}" if cls else ""
        unit = "W/m^2" if is_flux else "c/s"
        print(f"     flare {k}: {fl['peak'].strftime('%H:%M')} UTC  "
              f"peak {fl['peak_val']:.3g} {unit}{extra}  ({fl['dur_min']} min)")
        ch = channel_type(label)
        desc = (f"{ch.title()} X-ray flare seen by {label or base}, peaking "
                f"{fl['peak'].strftime('%H:%M')} UTC, peak {fl['peak_val']:.3g} {unit}"
                f"{(' (class '+cls+')') if cls else ''}, lasting {fl['dur_min']} min.")
        rows.append(dict(file=base, source=label, channel=ch,
                         start=fl["start"].isoformat(), peak=fl["peak"].isoformat(),
                         end=fl["end"].isoformat(), peak_value=fl["peak_val"], unit=unit,
                         goes_class=cls, duration_min=fl["dur_min"],
                         temperature_MK="", hardness_ratio="", description=desc))
    series = dict(label=label or base, channel=channel_type(label),
                  times=bt, rate=br, is_flux=is_flux)
    return rows, series


def analyze_spectrum(path, outdir, gain_kev=0.35):
    base = os.path.splitext(os.path.basename(path))[0]
    with fits.open(path) as h:
        hdu = None
        for x in h:
            if getattr(x, "columns", None) is not None and \
               find_col(x.columns.names, None, CHAN_COLS):
                hdu = x; break
        if hdu is None:
            print("   ! no spectrum table found"); return
        names = hdu.columns.names
        ccol = find_col(names, None, SPEC_COUNT_COLS) or "COUNTS"
        s = hdu.data
        det = hdu.header.get("DETNAM", "")
        counts = np.array([np.asarray(c, float) for c in s[ccol]])
        if counts.ndim == 1:  # single spectrum stored as one row of arrays differently
            counts = counts.reshape(1, -1)
        exp = np.asarray(s["EXPOSURE"], float) if "EXPOSURE" in names else np.ones(len(counts))
    nch = counts.shape[1]
    E = np.arange(nch) * gain_kev

    tot = counts.sum(axis=1)
    rate_tot = np.divide(tot, exp, out=np.zeros_like(tot), where=exp > 0)
    order = np.argsort(rate_tot)
    bg_sel = order[:max(5, len(order) // 5)]
    fl_sel = order[-max(3, len(order) // 20):]
    net = counts[fl_sel].sum(0) / exp[fl_sel].sum() - counts[bg_sel].sum(0) / exp[bg_sel].sum()
    bg_rate = counts[bg_sel].sum(0) / exp[bg_sel].sum()

    soft = net[(E >= 5) & (E < 15)].sum(); hard = net[(E >= 15) & (E < 40)].sum()
    HR = hard / soft if soft > 0 else float("nan")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.step(E, net + bg_rate, where="mid", color="#e85d04", lw=1.1, label="flare (raw)")
    ax.step(E, bg_rate, where="mid", color="#888", lw=1.0, label="quiet background")
    ax.step(E, net, where="mid", color="#1f6feb", lw=1.4, label="flare - background")
    ax.set_yscale("log"); ax.set_xlim(0, 60); ax.set_ylim(1e-3, None)
    ax.set_xlabel("Approx energy (keV)  [calibration ESTIMATED]")
    ax.set_ylabel("Count rate (c/s/channel)")
    ax.set_title(f"{base}  —  {det} spectrum")
    ax.text(0.96, 0.92, f"Hardness ratio = {HR:.2f}", transform=ax.transAxes,
            ha="right", va="top", bbox=dict(boxstyle="round", fc="#fff3cd", ec="#999"))
    ax.legend(); ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    png = os.path.join(outdir, base + "_spectrum.png")
    fig.savefig(png, dpi=130); plt.close(fig)
    print(f"   spectrum: hardness ratio = {HR:.2f} -> {os.path.basename(png)}")


# ----------------------------------------------------------------------------
# Time-matching: merge per-detector flares into ONE unified catalog
# ----------------------------------------------------------------------------
def build_unified_catalog(catalog, tol_min=8):
    """Group flares whose times overlap (or peaks within tol_min) into events."""
    from datetime import datetime, timedelta
    items = []
    for r in catalog:
        items.append(dict(r,
            _start=datetime.fromisoformat(r["start"]),
            _peak=datetime.fromisoformat(r["peak"]),
            _end=datetime.fromisoformat(r["end"])))
    items.sort(key=lambda x: x["_peak"])

    groups, used = [], [False] * len(items)
    for i, a in enumerate(items):
        if used[i]:
            continue
        grp = [a]; used[i] = True
        for j in range(i + 1, len(items)):
            if used[j]:
                continue
            b = items[j]
            # match if time windows overlap OR peaks within tolerance
            overlap = (a["_start"] <= b["_end"]) and (b["_start"] <= a["_end"])
            close = abs((b["_peak"] - a["_peak"]).total_seconds()) <= tol_min * 60
            if overlap or close:
                grp.append(b); used[j] = True
        groups.append(grp)

    unified = []
    for n, grp in enumerate(groups, 1):
        sources = sorted({g["source"] or g["file"] for g in grp})
        channels = {g["channel"] for g in grp}
        start = min(g["_start"] for g in grp)
        end = max(g["_end"] for g in grp)
        strongest = max(grp, key=lambda g: g["peak_value"])
        peak = strongest["_peak"]
        cls = next((g["goes_class"] for g in grp if g["goes_class"]), "")

        # hard-vs-soft lead time (the early-warning number)
        hard_peaks = [g["_peak"] for g in grp if g["channel"] == "hard"]
        soft_peaks = [g["_peak"] for g in grp if g["channel"] == "soft"]
        lead = ""
        if hard_peaks and soft_peaks:
            dt = (min(soft_peaks) - min(hard_peaks)).total_seconds() / 60.0
            lead = round(dt, 1)

        # plain-words description
        seen = " + ".join(sources)
        chtxt = (" and ".join(sorted(channels)) + " X-ray"
                 if len(channels) > 1 else f"{list(channels)[0]} X-ray")
        desc = (f"Flare peaking {peak.strftime('%H:%M')} UTC on "
                f"{peak.strftime('%Y-%m-%d')}, seen by {seen} ({chtxt}). "
                f"Strongest peak {strongest['peak_value']:.3g} {strongest['unit']}"
                f"{(' = class ' + cls) if cls else ''}, "
                f"total span {int((end - start).total_seconds() // 60)} min. ")
        if lead != "":
            if lead > 0:
                desc += (f"Hard X-rays peaked {lead:.0f} min BEFORE the soft peak "
                         f"-> {lead:.0f} min of early-warning lead time (Neupert effect).")
            else:
                desc += "Hard and soft peaks were ~simultaneous."
        elif channels == {"hard"}:
            desc += "Hard-only (no soft instrument matched this event)."
        elif channels == {"soft"}:
            desc += "Soft-only (no hard instrument matched this event)."

        unified.append(dict(
            event=n, peak=peak.isoformat(), start=start.isoformat(), end=end.isoformat(),
            instruments=seen, channels="+".join(sorted(channels)),
            peak_value=strongest["peak_value"], unit=strongest["unit"],
            goes_class=cls, hard_to_soft_lead_min=lead,
            n_detections=len(grp), description=desc))
    return unified


def fit_temperature(E, net, lo=6, hi=20):
    """Rough thermal temperature from ln(net rate) = a - E/kT over a clean band.
    Uses REAL energies (keV). Returns T in MK, or None if it can't fit."""
    m = (E >= lo) & (E <= hi) & (net > 0)
    if m.sum() < 4:
        return None
    coef = np.polyfit(E[m], np.log(net[m]), 1)
    if coef[0] >= 0:
        return None
    kT = -1.0 / coef[0]
    return 11.6 * kT, kT, coef  # T[MK], kT[keV], fit coefs


def analyze_events(path, outdir, args):
    """Read an event list (evt.fits), detect flares from the event-built light
    curve, and for EACH flare build a real-energy spectrum + fit a temperature."""
    base = os.path.splitext(os.path.basename(path))[0]
    rows = []
    with fits.open(path) as h:
        # group event HDUs by detector material (CdTe vs CZT)
        groups = {}
        for hdu in h:
            if getattr(hdu, "columns", None) is None:
                continue
            cl = [c.lower() for c in hdu.columns.names]
            if "ener" not in cl or "mjd" not in cl:
                continue
            det = (hdu.header.get("DETNAM", "") or hdu.name).upper()
            mat = "CdTe" if "CDTE" in det else ("CZT" if "CZT" in det else det)
            mjd = np.asarray(hdu.data["mjd"], float)
            ener = np.asarray(hdu.data["ener"], float)
            g = groups.setdefault(mat, [[], []])
            g[0].append(mjd); g[1].append(ener)

    for mat, (mjds, eners) in groups.items():
        mjd = np.concatenate(mjds); ener = np.concatenate(eners)
        order = np.argsort(mjd); mjd, ener = mjd[order], ener[order]
        label = f"HEL1OS {mat}-events"

        # build a 1-second light curve from the events
        t0 = mjd.min()
        sec = ((mjd - t0) * 86400).astype(int)
        nb = sec.max() + 1
        counts = np.bincount(sec, minlength=nb).astype(float)
        sec_mjd = t0 + np.arange(nb) / 86400.0
        bt, br, bg, flares = detect_flares(sec_mjd, counts, is_flux=False)

        # quiet background = events in the bottom 30% of per-second rate
        qthresh = np.percentile(counts, 30)
        quiet_sec = np.where(counts <= qthresh)[0]
        quiet_mask = np.isin(sec, quiet_sec)
        bg_dur = max(quiet_mask.sum(), 1)
        bins = np.arange(2, 80, 1.0)
        E = 0.5 * (bins[1:] + bins[:-1])
        bg_hist, _ = np.histogram(ener[quiet_mask], bins=bins)
        bg_rate = bg_hist / bg_dur

        print(f"   [{label}] {len(flares)} flare(s); building real-energy spectra...")
        for fl in flares:
            # select flare events by time window
            ts = Time(fl["start"]).mjd; te = Time(fl["end"]).mjd
            mask = (mjd >= ts) & (mjd <= te)
            fdur = max((te - ts) * 86400, 1)
            fl_hist, _ = np.histogram(ener[mask], bins=bins)
            net = fl_hist / fdur - bg_rate

            tfit = fit_temperature(E, net)
            T_MK = round(tfit[0], 1) if tfit else ""
            soft = net[(E >= 5) & (E < 15)].sum(); hard = net[(E >= 15) & (E < 40)].sum()
            HR = round(hard / soft, 3) if soft > 0 else ""

            # per-flare spectrum plot
            stamp = fl["peak"].strftime("%H%M")
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.step(E, fl_hist / fdur, where="mid", color="#e85d04", lw=1, label="flare (raw)")
            ax.step(E, bg_rate, where="mid", color="#888", lw=1, label="quiet background")
            ax.step(E, net, where="mid", color="#1f6feb", lw=1.4, label="flare - background")
            if tfit:
                Ef = np.linspace(6, 20, 30)
                ax.plot(Ef, np.exp(tfit[2][1] + tfit[2][0] * Ef), "g--", lw=2,
                        label=f"T ≈ {T_MK:.0f} MK")
            ax.set_yscale("log"); ax.set_xlim(2, 50); ax.set_ylim(1e-3, None)
            ax.set_xlabel("Photon energy (keV) — REAL, from event list")
            ax.set_ylabel("Count rate (c/s/keV)")
            ax.set_title(f"{label} flare {fl['peak'].strftime('%H:%M')} UTC  "
                         f"(T≈{T_MK} MK, HR={HR})")
            ax.legend(); ax.grid(alpha=0.3, which="both")
            fig.tight_layout()
            png = os.path.join(outdir, f"{base}_{mat}_flare_{stamp}_spectrum.png")
            fig.savefig(png, dpi=120); plt.close(fig)

            cls = ""
            desc = (f"Hard X-ray flare (event list, {mat}) peaking "
                    f"{fl['peak'].strftime('%H:%M')} UTC, peak {fl['peak_val']:.0f} c/s, "
                    f"{fl['dur_min']} min. Real-energy spectrum gives "
                    f"T≈{T_MK} MK, hardness ratio {HR}.")
            rows.append(dict(file=base, source=label, channel="hard",
                             start=fl["start"].isoformat(), peak=fl["peak"].isoformat(),
                             end=fl["end"].isoformat(), peak_value=fl["peak_val"],
                             unit="c/s", goes_class=cls, duration_min=fl["dur_min"],
                             temperature_MK=T_MK, hardness_ratio=HR, description=desc))
            print(f"      flare {fl['peak'].strftime('%H:%M')} UTC -> "
                  f"T≈{T_MK} MK, HR={HR}  ({os.path.basename(png)})")
    return rows


def make_combined_plot(series_list, unified, outdir):
    """Overlay hard + soft light curves for the biggest matched event,
    normalized to each curve's peak, marking both peaks and the lead gap."""
    from datetime import datetime, timedelta
    # events that have BOTH a hard and a soft detection
    mixed = [u for u in unified if "hard" in u["channels"] and "soft" in u["channels"]]
    if not mixed:
        print("   (combined plot skipped: no event seen by BOTH a hard and a soft "
              "instrument — add a SoLEXS/GOES file for the same day.)")
        return None
    ev = max(mixed, key=lambda u: u["peak_value"])
    start = datetime.fromisoformat(ev["start"]) - timedelta(minutes=20)
    end = datetime.fromisoformat(ev["end"]) + timedelta(minutes=20)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    hard_pk = soft_pk = None
    for s in series_list:
        t = np.array(s["times"]); r = np.array(s["rate"], float)
        m = (t >= start) & (t <= end)
        if m.sum() < 3 or r[m].max() <= 0:
            continue
        norm = r[m] / r[m].max()
        col = "#1f6feb" if s["channel"] == "hard" else "#e85d04"
        ls = "-" if s["channel"] == "hard" else "--"
        ax.plot(t[m], norm, ls, color=col, lw=1.6, alpha=0.9,
                label=f"{s['label']} ({s['channel']})")
        pk = t[m][int(np.argmax(r[m]))]
        if s["channel"] == "hard":
            hard_pk = pk if hard_pk is None else min(hard_pk, pk)
        else:
            soft_pk = pk if soft_pk is None else min(soft_pk, pk)

    if hard_pk: ax.axvline(hard_pk, color="#1f6feb", ls=":", lw=1.5)
    if soft_pk: ax.axvline(soft_pk, color="#e85d04", ls=":", lw=1.5)
    if hard_pk and soft_pk and soft_pk > hard_pk:
        ax.axvspan(hard_pk, soft_pk, color="gold", alpha=0.3)
        mid = hard_pk + (soft_pk - hard_pk) / 2
        lead = (soft_pk - hard_pk).total_seconds() / 60
        ax.annotate(f"lead time\n{lead:.0f} min", (mid, 0.5), ha="center", va="center",
                    fontsize=11, fontweight="bold", color="#b8860b")
    ax.set_xlabel("Time (UTC)"); ax.set_ylabel("Brightness (each curve scaled to its own peak)")
    ax.set_title("Hard X-rays lead Soft X-rays — the early-warning gap (Neupert effect)")
    ax.legend(loc="upper right"); ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    png = os.path.join(outdir, "combined_hard_soft_plot.png")
    fig.savefig(png, dpi=140); plt.close(fig)
    print(f"   combined hard+soft plot -> {os.path.basename(png)}")
    return png


def main():
    ap = argparse.ArgumentParser(description="Multi-source X-ray flare analyzer.")
    ap.add_argument("path")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--gain", type=float, default=0.35)
    ap.add_argument("--time-col", default=None)
    ap.add_argument("--rate-col", default=None)
    ap.add_argument("--time-format", default=None,
                    choices=[None, "mjd", "iso", "sec", "unix", "cxc"])
    ap.add_argument("--flux", action="store_true",
                    help="treat rate column as W/m^2 flux -> assign A-X class")
    args = ap.parse_args()

    if os.path.isdir(args.path):
        files = sorted(sum([glob.glob(os.path.join(args.path, e))
                            for e in ("*.fits", "*.fit", "*.lc", "*.pha",
                                      "*.csv", "*.txt", "*.json", "*.nc")], []))
    else:
        files = [args.path]
    # don't ingest our own output files
    files = [f for f in files if os.path.basename(f) not in
             ("flare_catalog.csv", "unified_flare_catalog.csv")]
    if not files:
        print("No data files found at", args.path); return
    outdir = args.outdir or (args.path if os.path.isdir(args.path)
                             else os.path.dirname(os.path.abspath(args.path)))
    os.makedirs(outdir, exist_ok=True)

    catalog = []
    series_list = []
    print(f"Found {len(files)} file(s). Outputs -> {outdir}\n")
    for f in files:
        kind = classify_file(f)
        print(f"-> {os.path.basename(f)}  [{kind}]")
        try:
            if kind in ("lightcurve", "table", "goes_nc"):
                rows, series = analyze_lightcurve(f, kind, outdir, args)
                catalog += rows
                series_list.append(series)
            elif kind == "events":
                catalog += analyze_events(f, outdir, args)
            elif kind == "spectrum":
                analyze_spectrum(f, outdir, gain_kev=args.gain)
            else:
                print("   (skipped — unrecognized; try --time-col/--rate-col/--time-format)")
        except Exception as e:
            print(f"   ! error: {e}  (try the override flags)")
        print()

    if catalog:
        cpath = os.path.join(outdir, "flare_catalog.csv")
        with open(cpath, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(catalog[0].keys()))
            w.writeheader(); w.writerows(catalog)
        print(f"\nRaw per-detector catalog: {cpath}  ({len(catalog)} detection(s))")

        # ---- unified, time-matched catalog with descriptions ----
        unified = build_unified_catalog(catalog)
        upath = os.path.join(outdir, "unified_flare_catalog.csv")
        with open(upath, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(unified[0].keys()))
            w.writeheader(); w.writerows(unified)
        print(f"UNIFIED catalog:          {upath}  ({len(unified)} flare event(s))\n")
        for u in unified:
            print(f"  Event {u['event']}: {u['description']}")
        print()
        make_combined_plot(series_list, unified, outdir)
    print("\nDone.")


if __name__ == "__main__":
    main()
