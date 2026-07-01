# How to use `aditya_flare_tool.py` (no FITS knowledge needed)

This tool turns confusing X-ray data files into plots, detected flares, and a flare catalog — automatically.

## What it can read (auto-detected)
| Source | Type | Status |
|---|---|---|
| **Aditya-L1 HEL1OS** | hard X-ray FITS (light curves + spectra) | tested on real data |
| **Aditya-L1 SoLEXS** | soft X-ray FITS (light curves + spectra) | format-compatible* |
| **Chandrayaan-2 XSM** | soft X-ray `.lc` / `.pha` FITS | format-compatible* |
| **GOES XRS** | soft X-ray flux (`.csv` / `.json` / FITS) | format-compatible* |
| **HEL1OS event list** (`evt.fits`) | per-photon events w/ real energy | tested on real data |
| **Generic CSV** | any time + rate/flux columns | works |

### Event files (`evt.fits`) — automatic temperature
If you point the tool at a HEL1OS **event list** (the `events/evt.fits` in a PRADAN
bundle), it does extra work: it detects flares from the events, then for **each flare**
builds a spectrum using the **real photon energies (keV)** in the file, fits a rough
**temperature (MK)**, and computes the **hardness ratio** — adding `temperature_MK` and
`hardness_ratio` columns to the catalog and saving a spectrum plot per flare.
(Temperatures are first-order estimates; a publication-grade value still needs the
RMF/ARF response files.)

\*Built to the documented format. Because I couldn't test against the *real* SoLEXS/XSM/GOES
files, if a real file uses unexpected column names, use the override flags (below) — the tool
will then read it. It was verified on synthetic stand-ins of each format.

## 1. One-time setup
Install the three libraries it needs (only once):

```
pip install astropy numpy matplotlib
```

## 2. Run it
Point it at a single file **or** a whole folder of files:

```
# one file
python aditya_flare_tool.py path/to/lightcurve_cdte1.fits

# a whole folder (it handles every .fits inside)
python aditya_flare_tool.py path/to/folder/

# choose where outputs go
python aditya_flare_tool.py path/to/folder/ --outdir results/

# GOES (or any flux data): add --flux so it assigns A/B/C/M/X classes
python aditya_flare_tool.py goes_xray.csv --flux
```

That's it. You don't tell it what kind of file it is — it figures that out.

## Override flags (use only if a real file isn't read automatically)
The tool guesses the time and rate columns. If it can't, tell it directly:

```
--time-col NAME      e.g. --time-col TIME      (force the time column)
--rate-col NAME      e.g. --rate-col xrsb_flux (force the rate/flux column)
--time-format FMT    one of: mjd | iso | sec | unix | cxc
                       mjd  = Modified Julian Date number   (HEL1OS/SoLEXS light curves)
                       iso  = text timestamps like 2026-06-29T21:36:00  (GOES CSV)
                       sec  = seconds from the file's start time         (HEL1OS spectra)
                       cxc  = seconds since 1998.0 (Chandrayaan-2 XSM / Chandra style)
                       unix = seconds since 1970
--flux               treat the rate column as physical flux (W/m^2) -> A-X class
--gain KEV           approx keV per channel for spectra (default 0.35; estimate)
```

Example for a real XSM light curve if auto-detect struggles:
```
python aditya_flare_tool.py xsm_lc.fits --time-col TIME --rate-col RATE --time-format cxc
```

## 3. What you get
For every file it finds, it saves outputs next to the data (or in `--outdir`):

- **`*_lightcurve.png`** — the brightness-over-time graph, with the adaptive background drawn in and every detected flare shaded gold.
- **`*_spectrum.png`** — for spectrum files: the flare's energy breakdown, background-subtracted, with the **hardness ratio** printed on it.
- **`flare_catalog.csv`** — one row per detected flare: file, detector, energy band, **start / peak / end time**, peak count rate, and duration. This is your "unified catalog" starting point.

## 4. How the flare detection works (plain words)
1. It averages the 1-second data into 1-minute points so random noise smooths out.
2. It tracks the **adaptive background** — the quiet-Sun level — as a rolling median, so it keeps up when the baseline drifts.
3. It flags a **flare** wherever the brightness rises clearly above that background (5× the noise, and at least ~3 minutes long) so single-second blips and cosmic-ray hits are ignored.

## 5. Important caveat about the spectrum / energy axis
The spectrum files give photons by **channel number, not keV**. The tool assumes an
**approximate** calibration (`--gain`, default 0.35 keV/channel) just to label the axis.
- The **shape** and the **hardness ratio** are trustworthy.
- The **absolute energy (keV) and any temperature** are NOT, until you download the
  official HEL1OS **gain calibration + response files (RMF/ARF)** from PRADAN and do a
  proper forward-fit (XSPEC-style). That step is the real "moat" for the build phase.

You can try a different calibration guess with, e.g., `--gain 0.1`.

## 6. Tips
- Works the same on SoLEXS light curves if their columns match (MJD/CTR) — try it.
- To build a bigger catalog, drop many days of files in one folder and run once; all
  flares land in a single `flare_catalog.csv`.
- If a file is an unfamiliar format, the tool says `[unknown]` and skips it safely.
