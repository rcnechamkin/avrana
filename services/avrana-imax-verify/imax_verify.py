#!/usr/bin/env python3
"""Determine whether a movie file actually contains expanded IMAX framing.

WHY THIS EXISTS
    Release names and TRaSH custom formats are SELECTION heuristics only. A release tagged
    "IMAX" may carry ordinary scope framing, and a 3840x2160 file proves nothing on its own:
    a 2.39:1 film is routinely stored in a 2160-high frame with black bars encoded into the
    picture. The only way to know is to look at the ACTIVE image inside the frame.

HOW
    ffprobe for container/stream facts, then ffmpeg cropdetect on many short samples spread
    across the runtime. Each sample yields the bounding box of the non-black picture; that box
    gives the true active aspect ratio. Samples are aggregated so credits, fades, dark scenes
    and isolated misdetections cannot decide the result.

    No model is involved at any point. Everything here is deterministic.

TWO PRESENTATIONS ARE DETECTED
    full      one expanded ratio for essentially the whole film (e.g. ~1.90 throughout)
    variable  the film alternates between a base scope ratio (~2.39) and expanded sections
              (~1.90 or ~1.78), which is how Nolan-style IMAX sequences are delivered

VERDICTS
    PASS      the expected expanded framing was detected
    FAIL      expansion was expected or claimed, and was NOT detected
    UNKNOWN   no expectation exists for this title, so no judgement is made

    UNKNOWN is a real answer, not a failure. Nothing here guesses at a film's intended
    presentation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTATIONS = Path(os.environ.get("IMAX_EXPECTATIONS", HERE / "expectations.json"))
RESULTS_DIR = Path(os.environ.get("IMAX_RESULTS", HERE / "results"))
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# Sampling. 60 samples across the runtime is enough to catch IMAX sequences that run only a few
# minutes, while staying cheap: each sample decodes a handful of frames, not a segment.
DEFAULT_SAMPLES = 60
FRAMES_PER_SAMPLE = 4
HEAD_SKIP = 0.04          # skip the first 4% (logos, studio idents, fades from black)
TAIL_SKIP = 0.08          # skip the last 8% (credits are letterboxed differently or full-frame)
# cropdetect's black threshold is expressed in the PIXEL FORMAT's range, not 0-255. 24 is the
# usual 8-bit value; on 10-bit HDR it is ~4x too strict and the bars are never detected, so every
# file looks full-frame and every title falsely "passes" as expanded. Measured on a 10-bit HDR
# remux: limit=24 -> 3840x2160 (bars missed), limit=96 -> 3840x1600 (correct). Scale by depth.
CROP_LIMIT_8BIT = 24
AR_ROUND = 2              # aspect ratios bucketed to 2 decimal places (1.90, 2.39, ...)

# What counts as "expanded" versus ordinary scope framing. IMAX presentations land at ~1.43
# (full 15/70), ~1.78 or ~1.90; theatrical scope is ~2.35-2.40.
#
# The band needs a FLOOR as well as a ceiling. Without one, 4:3 academy content (1.33) counts as
# "expanded" and a 1440x1080 cartoon falsely PASSES an IMAX claim -- which is exactly what
# happened on the first run against Batman Beyond: Return of the Joker.
EXPANDED_MIN_AR = 1.40
EXPANDED_MAX_AR = 1.96
SCOPE_MIN_AR = 2.30
# Share of usable samples that must be expanded before an IMAX claim is considered substantiated.
MIN_EXPANDED_SHARE = 0.10
# Below this share of samples surviving, the run is inconclusive rather than negative.
MIN_USABLE_FRACTION = 0.5
MIN_USABLE_ABSOLUTE = 8

# A sample whose detected picture is a tiny sliver of the frame is a fade or a dark scene, not a
# framing change. Discard rather than let it skew the histogram.
MIN_ACTIVE_HEIGHT_FRAC = 0.35
MIN_ACTIVE_WIDTH_FRAC = 0.50

# A real framing change occupies many contiguous minutes, so it always lands in several samples.
# A single sample sitting alone in its own bucket is a dark scene, a fade, or a shot with black
# down one side -- not a presentation change. Buckets below this floor are still REPORTED for
# diagnostics but are excluded from verdict arithmetic.
# Without this, three unrelated one-off buckets in a 12-sample run summed to 25% and produced a
# false FAIL on a film that is scope throughout.
NOISE_FLOOR_COUNT = 2
NOISE_FLOOR_SHARE = 0.05


def _signal(dist: list[dict], total_samples: int) -> list[dict]:
    """Drop buckets too small to be a real framing change, then RENORMALISE.

    Renormalising matters: verdict thresholds are fractions, and if shares keep referring to the
    full sample count while the noise buckets have been removed, they no longer sum to 1 and
    every threshold is silently understated. A scope-throughout film measured 69% scope instead
    of ~100% and came out UNKNOWN instead of FAIL for exactly this reason.
    """
    floor = max(NOISE_FLOOR_COUNT, round(total_samples * NOISE_FLOOR_SHARE))
    kept = [d for d in dist if d["count"] >= floor]
    n = sum(d["count"] for d in kept)
    if not n:
        return []
    return [{**d, "share": round(d["count"] / n, 4)} for d in kept]


class ProbeError(RuntimeError):
    pass


# ffmpeg defaults to one thread per core. This box has 4 and Jellyfin needs them more than we
# do, so every invocation is pinned to a single thread and dropped to the lowest CPU and I/O
# priority available. Verification is never urgent; playback always is.
FFMPEG_THREADS = int(os.environ.get("IMAX_FFMPEG_THREADS", "1"))


def _deprioritise() -> None:
    """Run in the child before exec: lowest CPU niceness and idle I/O class."""
    try:
        os.nice(19)
    except OSError:
        pass
    try:
        # Linux ioprio_set(IOPRIO_WHO_PROCESS=1, self, IOPRIO_CLASS_IDLE=3)
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).syscall(251, 1, 0, 3 << 13)
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          preexec_fn=_deprioritise)


def ffprobe_info(path: str) -> dict:
    """Container and video-stream facts. Raises ProbeError if the file is unreadable."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", "-select_streams", "v:0", path]
    p = _run(cmd)
    if p.returncode != 0:
        raise ProbeError(f"ffprobe failed: {p.stderr.strip()[:200]}")
    d = json.loads(p.stdout or "{}")
    streams = d.get("streams") or []
    if not streams:
        raise ProbeError("no video stream found")
    v = streams[0]
    fmt = d.get("format") or {}
    dur = float(v.get("duration") or fmt.get("duration") or 0)
    # Sample aspect ratio matters: a 1920x1080 stream with SAR 4:3 is really 2.37:1.
    sar = v.get("sample_aspect_ratio") or "1:1"
    try:
        sn, sd = (int(x) for x in sar.split(":"))
        sar_f = (sn / sd) if sd and sn else 1.0
    except Exception:
        sar_f = 1.0
    # Bit depth decides the cropdetect threshold, so it has to come from the probe.
    depth = v.get("bits_per_raw_sample")
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        pf = (v.get("pix_fmt") or "")
        m = re.search(r"p(\d+)", pf)
        depth = int(m.group(1)) if m else 8
    return {
        "bit_depth": depth,
        "crop_limit": CROP_LIMIT_8BIT * (2 ** max(0, depth - 8)),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "codec": v.get("codec_name"),
        "profile": v.get("profile"),
        "pix_fmt": v.get("pix_fmt"),
        "duration_s": dur,
        "sample_aspect_ratio": sar,
        "sar_factor": sar_f,
        "display_aspect_ratio": v.get("display_aspect_ratio"),
        "container_ar": round((int(v.get("width") or 0) * sar_f) / int(v.get("height") or 1), 3)
        if v.get("height") else None,
        "bit_rate": int(fmt.get("bit_rate") or 0) or None,
        "size_bytes": int(fmt.get("size") or 0) or None,
    }


CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def sample_crop(path: str, when: float, limit: int = CROP_LIMIT_8BIT,
                timeout: int = 60) -> tuple[int, int] | None:
    """Detect the active picture box at one timestamp. Returns (width, height) or None.

    `-ss` before `-i` seeks by keyframe, which is what keeps this cheap: a handful of frames are
    decoded per sample instead of a continuous stretch of a 4K HEVC stream.
    """
    cmd = [FFMPEG, "-hide_banner", "-nostdin",
           "-threads", str(FFMPEG_THREADS), "-filter_threads", str(FFMPEG_THREADS),
           "-ss", f"{when:.3f}", "-i", path,
           "-frames:v", str(FRAMES_PER_SAMPLE),
           "-vf", f"cropdetect=limit={limit}:round=2:reset=1",
           "-an", "-sn", "-f", "null", "-"]
    try:
        p = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    hits = CROP_RE.findall(p.stderr or "")
    if not hits:
        return None
    w, h, _, _ = hits[-1]          # last detection for this sample is the settled one
    return int(w), int(h)


def analyse(path: str, samples: int = DEFAULT_SAMPLES, progress=None) -> dict:
    """Sample the file and return the active-picture aspect-ratio distribution."""
    info = ffprobe_info(path)
    dur = info["duration_s"]
    if dur <= 0:
        raise ProbeError("could not determine duration")
    start, end = dur * HEAD_SKIP, dur * (1 - TAIL_SKIP)
    span = max(end - start, 1.0)
    points = [start + span * i / max(samples - 1, 1) for i in range(samples)]

    fw, fh, sar = info["width"], info["height"], info["sar_factor"]
    ratios: list[float] = []
    rejected = {"no_detection": 0, "too_dark": 0}
    per_sample = []
    for i, t in enumerate(points):
        box = sample_crop(path, t, limit=info["crop_limit"])
        if not box:
            rejected["no_detection"] += 1
            per_sample.append({"t": round(t, 1), "ar": None, "why": "no detection"})
            continue
        w, h = box
        if h < fh * MIN_ACTIVE_HEIGHT_FRAC or w < fw * MIN_ACTIVE_WIDTH_FRAC:
            rejected["too_dark"] += 1
            per_sample.append({"t": round(t, 1), "ar": None, "why": "fade/dark frame"})
            continue
        ar = round((w * sar) / h, AR_ROUND)
        ratios.append(ar)
        per_sample.append({"t": round(t, 1), "ar": ar, "crop": f"{w}x{h}"})
        if progress:
            progress(i + 1, len(points))

    if not ratios:
        return {"info": info, "usable_samples": 0, "distribution": [],
                "rejected": rejected, "per_sample": per_sample}

    hist = Counter(ratios)
    total = len(ratios)
    dist = [{"ar": ar, "count": n, "share": round(n / total, 4),
             "approx_runtime_s": round(dur * n / total)}
            for ar, n in hist.most_common()]
    return {"info": info, "usable_samples": total, "requested_samples": samples,
            "distribution": dist, "rejected": rejected, "per_sample": per_sample}


def load_expectations() -> dict:
    if not EXPECTATIONS.exists():
        return {"titles": {}}
    return json.loads(EXPECTATIONS.read_text())


def _sourced(expectation: dict | None) -> bool:
    """A usable expectation must be attributable. Unsourced data must never cause a FAIL."""
    if not expectation:
        return False
    return bool(expectation.get("source_url")) and \
        str(expectation.get("confidence", "")).lower() in ("high", "medium")


def classify(analysis: dict, expectation: dict | None = None,
             claimed_imax: bool | None = None) -> dict:
    """Decide PASS / FAIL / UNKNOWN.

    THE FILE IS THE FINAL AUTHORITY. The normal path needs no expectation at all: a release
    claimed IMAX, so either the frames show substantial expanded framing or they do not.

    A *sourced* expectation (source_url + confidence) can refine that judgement -- it knows,
    for instance, that a title should be expanded for its whole runtime rather than in
    sequences. An unsourced note is advisory only and can never turn a result into FAIL.
    """
    raw_dist = analysis.get("distribution") or []
    usable = analysis.get("usable_samples") or 0
    requested = analysis.get("requested_samples") or max(usable, 1)
    if not raw_dist or usable == 0:
        return {"verdict": "UNKNOWN", "reason": "no usable samples (unreadable or all-dark)"}
    if usable < max(MIN_USABLE_ABSOLUTE, requested * MIN_USABLE_FRACTION):
        return {"verdict": "UNKNOWN",
                "reason": f"inconclusive: only {usable} of {requested} samples were usable"}

    dist = _signal(raw_dist, usable) or raw_dist[:1]
    expanded = [d for d in dist if EXPANDED_MIN_AR <= d["ar"] <= EXPANDED_MAX_AR]
    scope = [d for d in dist if d["ar"] >= SCOPE_MIN_AR]
    expanded_share = round(sum(d["share"] for d in expanded), 4)
    scope_share = round(sum(d["share"] for d in scope), 4)
    top = dist[0]
    shape = ("constant expanded" if expanded_share >= 0.90 else
             "variable (expanded sequences)" if expanded_share >= MIN_EXPANDED_SHARE else
             "scope throughout" if scope_share >= 0.90 else "mixed")
    facts = {"expanded_share": expanded_share, "scope_share": scope_share,
             "observed_dominant_ar": top["ar"], "presentation": shape,
             "expanded_runtime_min": round(sum(d["approx_runtime_s"] for d in expanded) / 60)}

    # ---- sourced expectation: may tighten the judgement ------------------------------------
    if _sourced(expectation):
        exp_ar = float(expectation["expected_ratio"])
        tol = float(expectation.get("tolerance", 0.06))
        mode = expectation.get("mode", "variable")
        matched = [d for d in dist if abs(d["ar"] - exp_ar) <= tol]
        matched_share = round(sum(d["share"] for d in matched), 4)
        need = float(expectation.get("min_expanded_share",
                                     0.80 if mode == "full" else MIN_EXPANDED_SHARE))
        if mode == "none":
            ok = expanded_share < 0.05
            return {"verdict": "PASS" if ok else "FAIL",
                    "reason": (f"sourced expectation says scope throughout; measured "
                               f"{expanded_share:.0%} expanded"), **facts}
        ok = matched_share >= need
        return {"verdict": "PASS" if ok else "FAIL",
                "reason": (f"sourced expectation {exp_ar} ({mode}): matched {matched_share:.0%} "
                           f"of samples, needed {need:.0%}"),
                "expected_ratio_share": matched_share, **facts}

    # ---- the normal path: the release claimed IMAX, the frames decide ----------------------
    if claimed_imax:
        if expanded_share >= MIN_EXPANDED_SHARE:
            return {"verdict": "PASS",
                    "reason": (f"IMAX claim substantiated: {expanded_share:.0%} of samples are "
                               f"expanded ({EXPANDED_MIN_AR}-{EXPANDED_MAX_AR}), ~{facts['expanded_runtime_min']} min, "
                               f"{shape}"), **facts}
        if scope_share >= 0.90 and expanded_share < 0.03:
            return {"verdict": "FAIL",
                    "reason": (f"IMAX claimed but not present: {scope_share:.0%} of samples are "
                               f"scope (>={SCOPE_MIN_AR}), dominant {top['ar']}"), **facts}
        return {"verdict": "UNKNOWN",
                "reason": (f"inconclusive framing: {expanded_share:.0%} expanded / "
                           f"{scope_share:.0%} scope, dominant {top['ar']}"), **facts}

    # ---- nothing claimed and nothing sourced: measure, do not judge -------------------------
    note = ("an unsourced expectation exists and was ignored; add source_url + confidence to "
            "make it authoritative") if expectation else None
    out = {"verdict": "UNKNOWN",
           "reason": "release did not claim IMAX and no sourced expectation exists", **facts}
    if note:
        out["note"] = note
    return out


def verify(path: str, tmdb_id: str | None, samples: int = DEFAULT_SAMPLES,
           title: str | None = None, claimed_imax: bool | None = None,
           progress=None) -> dict:
    started = time.time()
    analysis = analyse(path, samples=samples, progress=progress)
    exps = load_expectations().get("titles", {})
    exp = exps.get(str(tmdb_id)) if tmdb_id else None
    verdict = classify(analysis, exp, claimed_imax=claimed_imax)
    if verdict["verdict"] == "UNKNOWN" and claimed_imax and exp is None:
        verdict["note"] = ("release name claimed IMAX but no expectation exists; "
                           "add a TMDB entry to expectations.json to make this judgeable")
    return {
        "schema": 1,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file": path,
        "tmdb_id": str(tmdb_id) if tmdb_id else None,
        "title": title or (exp or {}).get("title"),
        "claimed_imax": claimed_imax,
        "expectation": exp,
        **verdict,
        "analysis": analysis,
        "elapsed_s": round(time.time() - started, 1),
    }


def write_result(res: dict) -> Path:
    """Persist a result. Writes atomically so a crash cannot leave a half-written report.

    NOTE: run the CLI with the SAME uid as the service (`docker run --user 1000:1000`). A root
    -owned file here is unwritable by the service and costs a full re-analysis, which is how this
    was found: an 8-minute verification completed and then failed to save.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    key = (res.get("tmdb_id") or Path(res["file"]).stem)[:80]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)
    out = RESULTS_DIR / f"{safe}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, indent=1))
    tmp.replace(out)
    return out


def summarise(res: dict) -> str:
    a = res["analysis"]; i = a["info"]
    lines = [
        f"{res['verdict']}  {res.get('title') or Path(res['file']).name}",
        f"  file      : {res['file']}",
        f"  container : {i['width']}x{i['height']} {i['codec']} SAR {i['sample_aspect_ratio']} "
        f"-> frame AR {i['container_ar']}",
        f"  duration  : {round(i['duration_s']/60,1)} min",
        f"  depth     : {i['bit_depth']}-bit  -> cropdetect limit {i['crop_limit']}",
        f"  samples   : {a['usable_samples']} usable of {a.get('requested_samples','?')} "
        f"(rejected: {a['rejected']})",
        f"  reason    : {res.get('reason')}",
        "  active-picture aspect ratios:",
    ]
    for d in a["distribution"][:6]:
        bar = "#" * max(1, round(d["share"] * 40))
        lines.append(f"    {d['ar']:<6} {d['share']:>6.1%}  ~{round(d['approx_runtime_s']/60):>3} min  {bar}")
    if res.get("note"):
        lines.append(f"  note      : {res['note']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a movie's actual IMAX/expanded framing.")
    ap.add_argument("path", help="path to the movie file")
    ap.add_argument("--tmdb", help="TMDB id, used to look up the expectation")
    ap.add_argument("--title", help="title for the report")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--claimed-imax", action="store_true",
                    help="the release name claimed IMAX")
    ap.add_argument("--json", action="store_true", help="print the full JSON result")
    ap.add_argument("--save", action="store_true", help="write the result into results/")
    a = ap.parse_args()
    if not Path(a.path).exists():
        print(f"no such file: {a.path}", file=sys.stderr)
        return 2
    try:
        res = verify(a.path, a.tmdb, samples=a.samples, title=a.title,
                     claimed_imax=a.claimed_imax or None)
    except ProbeError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 3
    if a.save:
        print(f"  written: {write_result(res)}")
    print(json.dumps(res, indent=1) if a.json else summarise(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
