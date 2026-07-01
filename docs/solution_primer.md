# PS15 — The Solution, Explained Simply (every term, every data factor)
*A plain-words companion to PS15_Physics_Primer.md. What we are building, why, and what every piece of the data means. Last updated: 2026-06-30.*

> Read the physics primer first (what a flare is). This file explains **our system**: the two jobs, the two engines, the real data, and — in detail — the "factors" (features) the model reads and why each one is there.

---

## The one-sentence solution
We read Aditya-L1's two X-ray instruments and do two jobs: **(1) spot flares the instant they happen and log them in one master list (nowcasting)**, and **(2) predict the chance of a flare in the next 15–30 minutes (forecasting)**.

- **Nowcasting** = "what is happening *right now*." Detect a flare as the X-rays arrive. Reporting reality.
- **Forecasting** = "what will happen *next*." Predict a flare before its soft X-ray peak, with a probability attached. A bet about the future.

ISRO grades both, so the design has **two engines**, one per job.

---

## Why two instruments, and why combining them is the whole point
A flare emits in two channels: **hard X-rays** (HEL1OS — the instant punch from braking electrons) and **soft X-rays** (SoLEXS — the slower heat glow). Most teams worldwide only have **GOES**, which is soft-only — they can only watch the slow afterglow. We also have the **hard** channel.

This matters because the hard channel **leads** the soft peak (**Neupert effect**). Combining them isn't just "more data" — it's the difference between *reporting* a flare and *predicting* one. The hard rise is the crystal ball; the soft curve is what it predicts. **Combining soft + hard is why our forecast has lead time at all** — and it's only possible because Aditya-L1 carries both. This is our biggest differentiator.

---

## What the real data actually is
Three sources, with clear roles:

**Primary — Aditya-L1 SoLEXS + HEL1OS, "Level-1" products, in FITS files** (ISRO's PRADAN/ISSDC archive).
- *Level-1* = cleaned-up, calibrated instrument data — counts of photons over time and energy, not yet interpreted into science conclusions. (Level-0 = totally raw; higher levels = more processed.) Level-1 is the sweet spot: raw enough to run our own detection, clean enough not to fight the hardware.

**Supplementary — Chandrayaan-2 XSM** (another *Indian* mission, soft X-rays).
- Published catalog of **6,266 flares, incl. 1,469 faint A-class (2019–2022)**. Why we need it: Aditya-L1 is new and hasn't recorded many flares yet, and a model needs many examples to learn. XSM supplies a big pile of labeled flares — *especially the faint ones ISRO insists we detect* — while keeping the data story Indian.

**Supplementary — GOES X-ray flux** (decades of labeled soft-X-ray flares).
- The reliable "backbone" of labeled events (the official A/B/C/M/X classes) for training and sanity checks.

In every case the raw form is the same two things: **light curves** (counts vs time) and **spectra** (counts vs energy). Everything we build sits on those.

---

## Engine A — Detection & Unified Catalog (the nowcasting job)
**What it does:** watch the live light curves, decide "flare / no flare," mark each flare's **start, peak, end, and class** for *each* instrument, then merge both instruments into one **unified catalog** (a master table: time, peak, class, which instruments saw it, and how much the hard channel led the soft).

**Method = "adaptive-background detection in log-flux."** Unpacked:
- **Background** = the Sun's normal quiet X-ray level when nothing is flaring. A flare is a **rise above background**, so we must know the background to see the rise.
- **Adaptive** = the quiet level drifts over hours/days, so the code keeps **re-estimating** it from recent data (a rolling estimate) instead of using a fixed line. This stops missed flares when the baseline shifts.
- **Log-flux** = work with the *logarithm* of flux. Flares span ~10,000× (A→X); on a normal scale giant X-flares dwarf everything and tiny A-flares vanish. The log compresses the range so faint and giant rises are both detectable by the same rules. ("10× bigger" becomes "one even step up.")
- **Per-instrument tuning** = soft rises *gradually*, hard rises *impulsively* — so we use gentle-rise logic for SoLEXS and sharp-spike logic for HEL1OS.

Also detects two fine structures most teams ignore:
- **Pre-flare rise** = a small climb *before* the main flare — an early hint.
- **QPP (quasi-periodic pulsations)** = rhythmic flickers in the hard channel that often accompany flares; a confirming signature and precursor.

**Why this design:** a rules-based adaptive detector gives a **defensible, explainable catalog** (we can say exactly *why* each flare was flagged), and the log-flux + adaptive-background combo is precisely what covers the full faint→giant range ISRO grades on.

---

## Engine B — The Forecaster (the forecasting job)
**What it does:** every few moments, look at a **sliding window** of the recent past (last N minutes of soft + hard data) and output:
1. **Probability of a flare in the next 15–30 minutes** (yes/no with a percentage — "binary").
2. **Likely intensity class** if one comes (A/B/C/M/X — "multi-class").

**Model = XGBoost** ("gradient-boosted decision trees"). In plain words: it builds many small decision rules and stacks them so each new rule fixes the previous ones' mistakes. Chosen because it's accurate on feature/tabular data, fast, doesn't need huge datasets like deep neural nets, and can report *which features mattered* (explainability) — which we need to fight false alarms.

The model doesn't eat raw light curves — it eats **features** ("factors"), below.

---

## The factors of the data (the features) — every one explained
Each row the model sees is a snapshot of "the Sun's recent behavior," described by these numbers:

- **Current flux** — how bright the Sun is in X-rays right now. The baseline "where are we."
- **Rate of rise / slope** — how *fast* flux is climbing right now. A steep climb is the strongest sign a flare is starting — more predictive than the level itself.
- **Rolling max** — highest flux in the recent window. Context for how active it's been, so a rise can be judged as unusual or not.
- **Hard-to-soft ratio** — hard level ÷ soft level. A jump means the *impulsive* (hard) channel is firing — the leading edge of a flare. An **early-warning** feature, straight from the physics.
- **Hard-channel rise** — how fast the *hard* X-rays are climbing. Because hard leads soft (Neupert), this is an advance signal of a coming soft peak. **This feature buys the lead time.**
- **Background-subtracted flux** — flux *minus* the quiet-Sun background, so the model sees genuine excess, not drifting baseline. Kills false signals from drift.
- **Time since last flare** — active regions flare in clusters, so "we just had one" changes the odds of another.
- **Pre-flare flags** — yes/no marker that the detector saw a pre-flare rise or QPP. Tells the model a precursor is present.
- **Spectral-derived features (T, EM, δ trends)** — from fitting the *spectrum*, not raw brightness. The deep edge:
  - **Temperature (T) trend** — captures **hot onset**: plasma jumps to ~10–15 MK *before* brightness climbs, so rising T flags a flare *earlier than flux* and catches faint ones → more lead time.
  - **Emission measure (EM) trend** — how the *amount* of hot plasma changes; helps judge how big the event will get (its class).
  - **δ (spectral index) trend** — the "soft→hard→soft" evolution of the hard spectrum. Real flares follow it; noise doesn't → helps **reject false alarms**.

**The point:** these features turn raw photon counts into *physically meaningful* signals about whether a flare is imminent and how big. Several of them (hard rise, hard-to-soft ratio, T, δ) exist **only because we use the hard channel and the spectra** — exactly why our forecast can lead, not just follow.

---

## Fighting false alarms (the field's #1 problem)
Flares are **rare**, so a lazy model that always says "no flare" looks ~99% accurate but is useless; a jumpy model that cries "flare!" constantly gets ignored. So we build in:
- **Class weighting** — make the model care more about rare flare examples so it doesn't ignore them.
- **Threshold tuning** — choose the alert cutoff deliberately, trading "catch everything" vs "don't false-alarm."
- **Calibration** — make the model's "70%" actually mean 70% in reality, so the probability is trustworthy.
- **SHAP explainability** — shows *which feature* drove each prediction ("alert because hard rise + temperature jump"). A forecast becomes a *reason*, not a black box — so operators trust it.

---

## How we prove it works (evaluation)
Not plain "accuracy" (misleading when flares are rare). Instead:
- **TSS (True Skill Statistic)** = true-positive rate − false-positive rate. Rewards real catches, punishes false alarms. ISRO's main metric.
- **HSS (Heidke Skill Score)** = how much better than lucky guessing.
- **Precision–recall curves & confusion matrices** = show trade-offs and exactly what was right/wrong.
- **Lead-time-vs-skill curve** = warning time vs accuracy — directly proves the 15–30 min target.
- **Chronological (time-ordered) train/test split** = train on earlier data, test on *later* data. Never random — random splitting lets the model "peek" at the future (temporal leakage) and fakes good scores. Time-ordered is honest and matches real operation.

---

## What makes it right or wrong (accuracy factors, in simple words)

There are two different "correct" here, with different failure modes. **Counting** = reading
data that already arrived and saying "that was a flare, this big." **Predicting** = reading the
early signal and saying "a flare is *about to* happen." Prediction sits on top of counting — if
the counting is wrong, the model learns from wrong examples.

**How prediction even works (the logic):** some signals appear *early* — the hard X-ray rise and
the hot-onset temperature jump happen *before* the soft peak. The model learns from history:
"when the hard channel rose like this and temperature jumped like this, how often did a flare
follow within 15–30 min?" If 80% of the time, it outputs 80%. Prediction is correct to the degree
the early signal genuinely carries information about the future — and physics says it does, partly.

### What makes the COUNTING wrong → the fix
- **Background drifts** (quiet level moves) → *adaptive rolling background* (tool already does this).
- **Noise / cosmic-ray spikes** (one-second false blips) → *require multi-minute rise + both detectors to agree* (we saw CdTe1 & CdTe2 confirm the same flares).
- **Detector quirks — deadtime, pile-up, disabled pixels** (mis-counts, worst on big flares) → *deadtime/pile-up correction before counting*.
- **Overlapping flares** (one starts on another's tail) → *fit each flare's shape and decompose blends* (we literally saw the tool split a flare into shoulders).
- **Sensitivity threshold** (too low = noise counted; too high = faint A-class missed) → *log-flux + per-band threshold tuning*.
- **Data gaps** (instrument off) → *use the GTI good-time files so a gap isn't read as "quiet"*.
- **Calibration** (we saw 83 MK with a guessed energy axis vs ~25 MK with real energies) → *use real energies / RMF+ARF response files*.

### What makes the PREDICTION wrong → the fix
- **Flares are partly random** — the exact trigger moment isn't fully understood, so there's an irreducible uncertainty floor → *output a probability, not yes/no; honesty about uncertainty is part of being correct*.
- **Flares are rare (imbalance)** — a lazy model drifts to "no flare" and looks accurate but is useless → *weight rare examples; score with TSS not accuracy*.
- **Too few examples** (Aditya-L1 is new) → *add Chandrayaan-2 XSM + GOES history*.
- **X-ray-only = short horizon** — the deeper cause lives in the active-region magnetic field → *(later) add magnetograms/active-region data for longer lead*.
- **Lead-time vs accuracy trade-off** — earlier prediction = less revealed signal = harder → *report skill as a function of lead time; lean on the earliest physical signals (hard rise, hot onset)*.
- **Temporal leakage** (random train/test split lets the model peek at the future) → *always split by time: train earlier, test later*.
- **False alarms vs misses** (can't minimize both) → *tune the alert threshold deliberately; calibrate so "70%" means 70%*.

**The honest bottom line:** "correct" can't mean perfect (the trigger physics is partly unknown).
It means: clean counting (real flares, right sizes), honest probabilities (calibrated, beating the
dumb baselines on time-ordered data), and transparency about the lead-time/false-alarm trade-off.
Judges reward "we knew this failure mode and handled it on purpose" more than a big accuracy number.

---

## The operational layer (the demo)
A lightweight real-time service + dashboard: live soft + hard light curves, markers on detected flares, a forecast-probability gauge, and an optional plain-language alert ("Elevated flare risk in next 20 min; hard-channel rise detected"). ISRO called the dashboard "nice-to-have" — it's polish. The **catalog + forecaster** are the substance.

---

## Why we're not the prompt-baseline (the differentiators, in one place)
1. **Use the hard X-ray channel for lead time** (Neupert) — most teams have soft-only GOES.
2. **Train on Chandrayaan-2 XSM** (Indian, 6,266 flares, many faint A-class) + GOES backbone — beats the data-scarcity problem and the "must detect faint flares" criterion.
3. **Engineer for the real instruments** — SoLEXS dual-aperture for dynamic range; HEL1OS pile-up/saturation/deadtime handling.
4. **Use the spectra → physical features (T, EM, δ)**, not just brightness — hot-onset precursor most teams ignore.
5. **Attack false alarms head-on** — calibration + threshold tuning + SHAP.
6. **Ship a real deployable system**, not a notebook — fills the documented operational gap.

---

## Quick glossary (one-liners)
- **Nowcasting:** detect flares happening now → unified catalog.
- **Forecasting:** P(flare in next 15–30 min) + likely class.
- **Engine A:** adaptive-background, log-flux detector → catalog.
- **Engine B:** XGBoost on windowed features → probability + class.
- **Level-1 data:** calibrated counts vs time/energy; raw enough to detect, clean enough to trust.
- **Light curve / spectrum:** counts vs time / counts vs energy.
- **Adaptive background:** rolling re-estimate of the quiet-Sun level.
- **Log-flux:** log scale so faint and giant flares share one rule set.
- **Feature/factor:** a number describing recent behavior that the model reads.
- **Hard-to-soft ratio & hard rise:** the early-warning, lead-time features.
- **T / EM / δ:** plasma temperature / amount of hot plasma / hard-spectrum slope (from spectral fitting).
- **TSS / HSS:** honest scoring given rare events.
- **Chronological split:** train past → test future; prevents cheating.
- **SHAP:** shows which feature caused each prediction (trust).
