#!/usr/bin/env python3
"""
Spectrogram + NICV feature selection for the EM traces.

This implements the paper's preprocessing (Pham et al., ACSAC '21 §6):

  1. STFT spectrogram of each trace: window M = 8192, overlap O = 4096,
     magnitude squared.
  2. NICV per time-frequency bin against the class label,
     NICV(X, Y) = Var[E[X|Y]] / Var[X].
  3. Keep the `epsilon` frequency bands with the highest mean NICV over time.

It runs on the host, needs no scope and no Pi, and works on traces already
captured. Nothing here produces data: a dataset directory that this tool
accepts must be built from a join of *real* capture records, and records that
say otherwise (a bench smoke test, a dry run) are refused rather than
silently averaged in with the rest.

Why streaming
-------------
A campaign is thousands of traces of 5 000 000 float64 samples: ~40 MB each,
240 GB for 6 000 traces. Loading the set to compute a variance is not
possible, so NICV is accumulated in one pass per class:

    Var[X]        = sum(x^2)/n      - (sum(x)/n)^2
    Var[E[X|Y]]   = sum_c n_c*(m_c - m)^2 / n        (between-class)

Both are exact, and the per-class accumulators are D x F arrays, not
n_traces x D x F. With the paper's window the accumulators are ~20 MB each.

Usage::

    python -I em_analysis.py --joined run01/joined.jsonl --epsilon 20 \\
        --out run01/features.npz

    python -I em_analysis.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

# Paper values (§6.2). M and O are samples, not seconds.
STFT_WINDOW = 8192
STFT_OVERLAP = 4096

# The paper searched epsilon in {4, 8, ..., 28}.
EPSILON_CHOICES = tuple(range(4, 29, 4))

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE = 2


class SyntheticDataError(RuntimeError):
    """
    The dataset contains traces that are not measurements.

    The lab invariant is absolute: EM traces come only from physical silicon.
    A trace captured with the trigger gate bypassed, or one from a dry run, is
    rehearsal data. Averaging it into a NICV makes the result look like a
    measurement of the workload when it is a measurement of a fake.
    """


# --------------------------------------------------------------------------- #
# Spectrogram
# --------------------------------------------------------------------------- #
def frame_signal(signal, window=STFT_WINDOW, overlap=STFT_OVERLAP):
    """
    Split a 1-D signal into overlapping frames.

    Returns (n_frames, window). Trailing samples that do not fill a whole
    window are dropped, which is what the paper's definition does: it sums
    over m windows of length M.
    """
    signal = np.asarray(signal)
    if signal.ndim != 1:
        raise ValueError(f"expected a 1-D trace, got shape {signal.shape}")
    if window <= 0 or overlap < 0 or overlap >= window:
        raise ValueError(
            f"invalid framing: window={window}, overlap={overlap}. "
            f"Overlap must be in [0, window)."
        )
    hop = window - overlap
    if signal.size < window:
        raise ValueError(
            f"a {signal.size}-sample trace is shorter than the "
            f"{window}-sample STFT window; nothing to transform"
        )
    n_frames = 1 + (signal.size - window) // hop
    index = np.arange(window)[None, :] + hop * np.arange(n_frames)[:, None]
    return signal[index]


def spectrogram(signal, window=STFT_WINDOW, overlap=STFT_OVERLAP,
                detrend=True):
    """
    Magnitude-squared STFT, shape (n_frames, window//2 + 1).

    The signal is mean-centred per frame by default. A DC offset from the
    amplifier would otherwise dominate the lowest bin and make every other
    band look uninformative under NICV.
    """
    frames = frame_signal(signal, window=window, overlap=overlap)
    if detrend:
        frames = frames - frames.mean(axis=1, keepdims=True)
    tapered = frames * np.hanning(window)[None, :]
    spectrum = np.fft.rfft(tapered, axis=1)
    return (np.abs(spectrum) ** 2).astype(np.float64)


# --------------------------------------------------------------------------- #
# NICV
# --------------------------------------------------------------------------- #
class NicvAccumulator:
    """
    Streaming Var[E[X|Y]] / Var[X] over traces, for 2-D features per trace.

    Fed one spectrogram at a time; never holds more than one trace plus the
    per-class accumulators.
    """

    def __init__(self, shape):
        self.shape = tuple(shape)
        self.n = 0
        self.total_sum = np.zeros(self.shape, dtype=np.float64)
        self.total_sumsq = np.zeros(self.shape, dtype=np.float64)
        self.class_counts: dict = {}
        self.class_sums: dict = {}

    def add(self, features, label):
        features = np.asarray(features, dtype=np.float64)
        if features.shape != self.shape:
            raise ValueError(
                f"feature shape {features.shape} does not match {self.shape}; "
                f"all traces must share a window and length")
        self.n += 1
        self.total_sum += features
        self.total_sumsq += features * features
        self.class_counts[label] = self.class_counts.get(label, 0) + 1
        if label in self.class_sums:
            self.class_sums[label] += features
        else:
            self.class_sums[label] = features.copy()

    def nicv(self):
        """
        The NICV matrix, same shape as one trace's features.

        Bins with zero variance carry no information and produce 0 rather than
        a NaN; a NaN there would propagate through the band ranking and turn
        an all-idle dataset into a silent empty selection.
        """
        if self.n == 0:
            raise ValueError("no traces were added")
        if len(self.class_counts) < 2:
            raise ValueError(
                "NICV needs at least two classes; got "
                f"{sorted(self.class_counts)}. A single-class dataset measures "
                f"the workload, not the difference between workloads."
            )
        mean = self.total_sum / self.n
        var_total = np.maximum(self.total_sumsq / self.n - mean * mean, 0.0)

        between = np.zeros(self.shape, dtype=np.float64)
        for label, count in self.class_counts.items():
            class_mean = self.class_sums[label] / count
            between += count * (class_mean - mean) ** 2
        between /= self.n

        out = np.zeros(self.shape, dtype=np.float64)
        nonzero = var_total > 0
        out[nonzero] = between[nonzero] / var_total[nonzero]
        return np.clip(out, 0.0, 1.0)


def select_bands(nicv_matrix, epsilon=20):
    """
    The epsilon frequency bands with the highest mean NICV over time.

    Returns a sorted list of frequency-bin indices. Ties are broken by index so
    the same input always yields the same bands.
    """
    nicv_matrix = np.asarray(nicv_matrix)
    if nicv_matrix.ndim != 2:
        raise ValueError(f"expected a D x F NICV matrix, got shape {nicv_matrix.shape}")
    n_freq = nicv_matrix.shape[1]
    if not 1 <= epsilon <= n_freq:
        raise ValueError(
            f"epsilon={epsilon} must be in [1, {n_freq}], the number of "
            f"frequency bins")
    means = nicv_matrix.mean(axis=0)
    order = np.lexsort((np.arange(n_freq), -means))
    return sorted(int(i) for i in order[:epsilon])


# --------------------------------------------------------------------------- #
# Dataset loading
# --------------------------------------------------------------------------- #
def _require_real(records, captures_by_index):
    """
    Refuse a dataset whose manifest says the traces are not measurements.

    Checks the join record *and* the capture record it points at. A join alone
    can be built by hand; the capture record is what the scope wrote.
    """
    problems = []
    for pair in records:
        index = pair.get("capture_trace_index")
        capture = captures_by_index.get(index)
        if capture is None:
            problems.append(
                f"capture trace_index={index} is in the join but not in the "
                f"capture manifest")
            continue
        if capture.get("trigger_real") is False:
            problems.append(
                f"capture trace_index={index} recorded trigger_real=false: "
                f"the block did not start on the trigger edge")
        invariants = capture.get("invariants") or {}
        if invariants.get("trigger_alignment_enforced") is False:
            problems.append(
                f"capture trace_index={index} was captured with the trigger "
                f"gate bypassed")
        if pair.get("runner_status") not in (None, "ok"):
            problems.append(
                f"capture trace_index={index} is joined to a runner trace "
                f"with status {pair['runner_status']!r}")
    return problems


def load_dataset(joined_path, capture_manifest_path=None,
                 allow_non_measurements=False):
    """
    Read a joined manifest into (paths, labels, metadata).

    `joined_path` is the output of `manifest_join.py --out`. The capture
    manifest is needed to check the provenance of each trace; without it the
    check cannot run, and that is a refusal rather than a warning.

    Raises SyntheticDataError when the records say a trace is not a
    measurement.
    """
    pairs, errors = _read_jsonl(joined_path)
    if errors:
        raise ValueError("; ".join(errors))
    if not pairs:
        raise ValueError(f"{joined_path}: no joined pairs")

    if capture_manifest_path is None:
        capture_manifest_path = _default_capture_manifest(joined_path)
    captures, cap_errors = _read_jsonl(capture_manifest_path)
    if cap_errors:
        raise ValueError("; ".join(cap_errors))
    captures_by_index = {
        r.get("trace_index"): r for r in captures
        if r.get("type", "trace") == "trace"
    }

    problems = _require_real(pairs, captures_by_index)
    if problems and not allow_non_measurements:
        raise SyntheticDataError(
            f"{len(problems)} trace(s) in {joined_path} are not measurements: "
            + "; ".join(problems[:3])
            + (" ..." if len(problems) > 3 else "")
            + ". Refusing to compute features over them. This is the "
              "'traces come only from physical silicon' invariant."
        )

    paths, labels = [], []
    for pair in pairs:
        path = pair.get("capture_file")
        if not path:
            raise ValueError(
                f"joined record for capture {pair.get('capture_trace_index')} "
                f"has no capture_file")
        if not os.path.exists(path):
            raise ValueError(f"trace file is missing: {path}")
        paths.append(path)
        labels.append(pair.get("runner_mode") or "unknown")
    return paths, labels, {"pairs": pairs, "captures": captures}


def _default_capture_manifest(joined_path):
    """The capture manifest next to the join output, by the usual name."""
    return os.path.join(os.path.dirname(os.path.abspath(joined_path)),
                        "manifest.jsonl")


def _read_jsonl(path):
    records, errors = [], []
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    errors.append(f"{path}:{lineno}: {exc}")
    except OSError as exc:
        errors.append(f"{path}: {exc}")
    return records, errors


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def compute_nicv(paths, labels, window=STFT_WINDOW, overlap=STFT_OVERLAP):
    """Stream every trace through the accumulator; return the NICV matrix."""
    if len(set(labels)) < 2:
        raise ValueError(
            f"this dataset has one class ({sorted(set(labels))}), so NICV is "
            f"undefined. Capture both classes before selecting bands.")

    accumulator = None
    for i, (path, label) in enumerate(zip(paths, labels)):
        trace = np.load(path)
        spec = spectrogram(trace, window=window, overlap=overlap)
        if accumulator is None:
            accumulator = NicvAccumulator(spec.shape)
        accumulator.add(spec, label)
        if (i + 1) % 100 == 0 or i + 1 == len(paths):
            print(f"  [{i + 1}/{len(paths)}] {label}", flush=True)
    return accumulator.nicv()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="STFT + NICV feature selection for EM traces.")
    parser.add_argument("--joined", help="joined.jsonl from manifest_join.py")
    parser.add_argument("--captures", default=None,
                        help="capture manifest.jsonl to check provenance "
                             "(default: next to --joined)")
    parser.add_argument("--epsilon", type=int, default=20,
                        help=f"frequency bands to keep (paper searched "
                             f"{EPSILON_CHOICES}); default 20")
    parser.add_argument("--window", type=int, default=STFT_WINDOW,
                        help=f"STFT window in samples (default {STFT_WINDOW})")
    parser.add_argument("--overlap", type=int, default=STFT_OVERLAP,
                        help=f"STFT overlap in samples (default {STFT_OVERLAP})")
    parser.add_argument("--out", help="write selected bands and NICV to .npz")
    parser.add_argument("--allow-non-measurements", action="store_true",
                        help="Compute features over records flagged as dry "
                             "runs or gate-bypassed traces. ONLY for testing "
                             "this tool; the output is not a dataset.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.joined:
        parser.error("--joined is required (or use --self-test)")

    try:
        paths, labels, meta = load_dataset(
            args.joined, args.captures,
            allow_non_measurements=args.allow_non_measurements)
        print(f"dataset: {len(paths)} traces, classes {sorted(set(labels))}")
        nicv = compute_nicv(paths, labels, window=args.window,
                            overlap=args.overlap)
    except (ValueError, SyntheticDataError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    bands = select_bands(nicv, args.epsilon)
    print(f"kept {len(bands)} of {nicv.shape[1]} frequency bands")

    if args.out:
        np.savez_compressed(args.out, nicv=nicv,
                            bands=np.asarray(bands, dtype=np.int64),
                            window=np.int64(args.window),
                            overlap=np.int64(args.overlap),
                            epsilon=np.int64(args.epsilon))
        print(f"wrote {args.out}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def self_test():
    failures, checks = [], [0]

    def expect(cond, label):
        checks[0] += 1
        if not cond:
            failures.append(label)

    rng = np.random.default_rng(1234)

    # 1. Framing arithmetic
    frames = frame_signal(np.arange(100), window=10, overlap=5)
    expect(frames.shape == (19, 10), f"framing shape: {frames.shape}")
    expect(frames[1][0] == 5, "consecutive frames advance by window-overlap")
    try:
        frame_signal(np.arange(5), window=10)
        expect(False, "a too-short trace is rejected")
    except ValueError:
        expect(True, "a too-short trace is rejected")
    try:
        frame_signal(np.arange(100), window=10, overlap=10)
        expect(False, "overlap >= window is rejected")
    except ValueError:
        expect(True, "overlap >= window is rejected")

    # 2. Spectrogram of a pure tone peaks at the right bin
    n = 8192 * 3
    t = np.arange(n)
    tone_hz = 0.05  # cycles per sample
    signal = np.sin(2 * np.pi * tone_hz * t)
    spec = spectrogram(signal, window=8192, overlap=4096)
    expect(spec.shape[1] == 8192 // 2 + 1, f"rfft bin count: {spec.shape[1]}")
    peak = int(np.argmax(spec.mean(axis=0)))
    expected = int(round(tone_hz * 8192))
    expect(abs(peak - expected) <= 1,
           f"a pure tone peaks at its bin ({peak} vs {expected})")
    expect(np.all(spec >= 0), "magnitude squared is non-negative")

    # 3. NICV is 0 for a feature that does not depend on the label and 1 for a
    #    feature that is constant within each class and differs between them.
    acc = NicvAccumulator((4, 2))
    for _ in range(10):
        acc.add(np.array([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]), "a")
    for _ in range(10):
        acc.add(np.array([[2.0, 1.0], [2.0, 1.0], [2.0, 1.0], [2.0, 1.0]]), "b")
    nicv = acc.nicv()
    expect(abs(nicv[0, 0] - 1.0) < 1e-9,
           f"a perfectly separating bin has NICV 1: {nicv[0, 0]}")
    expect(abs(nicv[0, 1]) < 1e-9,
           f"a constant bin has NICV 0: {nicv[0, 1]}")

    # 4. A single class is refused rather than silently returning zeros
    one = NicvAccumulator((2, 2))
    one.add(np.ones((2, 2)), "a")
    try:
        one.nicv()
        expect(False, "a single-class NICV is refused")
    except ValueError:
        expect(True, "a single-class NICV is refused")

    # 5. Streaming NICV equals the two-pass definition
    features = rng.normal(size=(40, 3, 2))
    labels = np.array([0] * 20 + [1] * 20)
    features[labels == 1] += 0.5
    acc = NicvAccumulator((3, 2))
    for f, lab in zip(features, labels):
        acc.add(f, int(lab))
    streamed = acc.nicv()
    var_total = features.var(axis=0)
    conditional = np.stack([features[labels == c].mean(axis=0)
                            for c in (0, 1)])[labels]
    var_between = conditional.var(axis=0)
    expected = np.where(var_total > 0, var_between / var_total, 0.0)
    expect(np.allclose(streamed, expected, atol=1e-12),
           "streaming NICV matches the two-pass definition")

    # 6. Band selection
    matrix = np.zeros((10, 8))
    matrix[:, 3] = 0.9
    matrix[:, 6] = 0.8
    matrix[:, 1] = 0.7
    bands = select_bands(matrix, epsilon=2)
    expect(bands == [3, 6], f"the highest-mean bands are kept: {bands}")
    expect(select_bands(matrix, epsilon=8) == list(range(8)),
           "epsilon = F keeps every band")
    try:
        select_bands(matrix, epsilon=9)
        expect(False, "epsilon > F is rejected")
    except ValueError:
        expect(True, "epsilon > F is rejected")
    # Ties resolve by index, so the selection is reproducible
    flat = np.zeros((2, 4))
    expect(select_bands(flat, epsilon=2) == [0, 1],
           "ties resolve by frequency index")

    # 7. Provenance: a gate-bypassed capture is refused
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        npy = os.path.join(tmp, "t.npy")
        np.save(npy, np.zeros(8192 * 2))
        joined = os.path.join(tmp, "joined.jsonl")
        with open(joined, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "capture_trace_index": 0, "capture_file": npy,
                "runner_trace_index": 0, "runner_mode": "goodware-idle",
                "runner_status": "ok",
            }) + "\n")
        captures = os.path.join(tmp, "manifest.jsonl")
        with open(captures, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "trace", "trace_index": 0, "file": npy,
                "trigger_real": False,
                "invariants": {"trigger_alignment_enforced": False},
            }) + "\n")
        try:
            load_dataset(joined, captures)
            expect(False, "a gate-bypassed trace is refused")
        except SyntheticDataError:
            expect(True, "a gate-bypassed trace is refused")

        # The same dataset is accepted when provenance is clean.
        with open(captures, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "trace", "trace_index": 0, "file": npy,
                "trigger_real": True,
                "invariants": {"trigger_alignment_enforced": True},
            }) + "\n")
        paths, labels, _ = load_dataset(joined, captures)
        expect(paths == [npy] and labels == ["goodware-idle"],
               "a clean trace loads with its runner mode as the label")

        # Opting out is possible, but explicit.
        with open(captures, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "trace", "trace_index": 0, "file": npy,
                "trigger_real": False,
            }) + "\n")
        paths, _, _ = load_dataset(joined, captures,
                                   allow_non_measurements=True)
        expect(len(paths) == 1, "the opt-out is honoured when asked for")

    print(f"self-test: {checks[0]} checks", file=sys.stderr)
    if failures:
        for f in failures:
            print(f"  FAIL: {f}", file=sys.stderr)
        return 1
    print("self-test: all checks passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
