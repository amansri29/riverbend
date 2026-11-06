"""Build the tutorial video from `scenes.py`.

Steps (run in order; each is idempotent and skips work whose inputs have not changed):

    uv run --with pillow python scripts/tutorial/build.py capture    # run the demo commands, save outputs
    uv run --with pillow python scripts/tutorial/build.py render     # slides and transcripts -> PNG (headless Chrome)
    uv run --with pillow python scripts/tutorial/build.py tts        # narration -> audio (--engine say|elevenlabs)
    uv run --with pillow python scripts/tutorial/build.py assemble   # segments -> one mp4 (ffmpeg)

The ElevenLabs key is read from ELEVENLABS_API_KEY in the environment (or .env), never from code.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "tutorial"))
from scenes import CAPTURES, CLEANUP_SQL, DB, SCENES  # noqa: E402

BUILD = ROOT / "docs" / "tutorial" / "build"
CAP = BUILD / "captures"
SLIDES = BUILD / "slides"
AUDIO = BUILD / "audio"
SEG = BUILD / "segments"
OUT = ROOT / "docs" / "tutorial"
CHROME = next(
    (
        c
        for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium"]
        if Path(c).exists() or shutil.which(c)
    ),
    None,
)
W, H = 1920, 1080
PAD = 0.7  # seconds of silence after each narration


# ----------------------------------------------------------------------------- helpers
def sh(cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def digest(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def stamp_ok(path: Path, key: str) -> bool:
    side = path.with_suffix(path.suffix + ".key")
    return path.exists() and side.exists() and side.read_text() == key


def stamp(path: Path, key: str) -> None:
    path.with_suffix(path.suffix + ".key").write_text(key)


def duration(path: Path) -> float:
    r = sh(f'ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "{path}"')
    return float(r.stdout.strip() or 0)


def load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ----------------------------------------------------------------------------- capture
def capture() -> None:
    CAP.mkdir(parents=True, exist_ok=True)
    sh(f'psql {DB} -q -c "{CLEANUP_SQL}"')  # the demo message is posted fresh on every capture
    for group, cmds in CAPTURES.items():
        for cmd, out in cmds:
            r = sh(cmd, cwd=ROOT)
            text = (r.stdout + (("\n" + r.stderr) if r.stderr.strip() else "")).strip()
            (CAP / out).write_text(text + "\n")
            (CAP / (out + ".cmd")).write_text(cmd)
            print(f"[capture] {group}/{out}: {len(text.splitlines())} lines")


# ----------------------------------------------------------------------------- render
CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: #ffffff;
  font-family: Helvetica, Arial, sans-serif; color: #111827; }
.slide { padding: 84px 110px 70px; height: 1080px; display: flex; flex-direction: column; }
h1 { font-size: 60px; margin: 0 0 18px; letter-spacing: -0.5px; }
.sub { font-size: 36px; color: #374151; line-height: 1.35; max-width: 1500px; }
ul { list-style: none; padding: 0; margin: 28px 0 0; }
li { font-size: 33px; line-height: 1.38; margin: 0 0 18px; padding-left: 44px; position: relative; color: #1f2937; }
li::before { content: ""; position: absolute; left: 0; top: 17px; width: 16px; height: 16px; border-radius: 4px; background: #1f4e9c; }
.foot { margin-top: auto; font-size: 24px; color: #9ca3af; display: flex; justify-content: space-between; }
.term { background: #111827; color: #e5e7eb; border-radius: 14px; padding: 26px 30px; font-family: Menlo, Consolas, monospace;
  font-size: 21.5px; line-height: 1.3; white-space: pre-wrap; word-break: break-all; margin: 0 0 18px; overflow: hidden; }
.term .cmd { color: #93c5fd; }
.term .cmd::before { content: "$ "; color: #6b7280; }
.code { background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 14px; padding: 26px 30px; font-family: Menlo, Consolas, monospace;
  font-size: 23px; line-height: 1.4; white-space: pre-wrap; margin-top: 10px; overflow: hidden; }
.code .ln { color: #9ca3af; display: inline-block; width: 70px; }
.code .kw { color: #1f4e9c; font-weight: bold; }
.file { font-family: Menlo, monospace; font-size: 26px; color: #6b7280; margin-bottom: 6px; }
.title { justify-content: center; }
.title h1 { font-size: 92px; margin-bottom: 30px; }
.title .sub { font-size: 44px; }
.results table { border-collapse: collapse; font-size: 32px; margin-top: 24px; }
.results td { padding: 10px 28px 10px 0; border-bottom: 1px solid #e5e7eb; }
.results td:last-child { font-weight: bold; color: #1f4e9c; }
"""


def esc(s: str) -> str:
    return html.escape(s)


def shorten_cmd(cmd: str) -> str:
    cmd = cmd.replace("sleep 8; ", "")
    m = re.search(r'psql \S+ (?:-x )?-c "(.+)"$', cmd, re.S)
    if m:
        sql = m.group(1)
        # hide the join boilerplate that only exists to look a row up by the sender's message id
        sql = re.sub(
            r"FROM (\w+) \w+ JOIN inbound_messages m ON [^W]+WHERE m\.message_id", r"FROM \1 … WHERE message_id", sql
        )
        return sql
    cmd = re.sub(r"\| python3 -c \".*\"$", "| python3 (print summary)", cmd, flags=re.S)
    cmd = re.sub(r"\| python3 -m json\.tool$", "", cmd)
    return cmd.replace(" -H 'content-type: application/json'", "")


def trim_output(text: str, max_lines: int) -> str:
    lines = text.rstrip("\n").splitlines()
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return "\n".join(lines)


def results_table() -> list[tuple[str, str]]:
    rows = []
    for line in (ROOT / "docs" / "results.md").read_text().splitlines():
        m = re.match(r"\| (.+?) \| (.+?) \|$", line)
        if m and m.group(1) not in ("Metric", "---"):
            rows.append((m.group(1), m.group(2)))
        if line.startswith("Per shop"):
            break
    return rows


def results_narration(rows: list[tuple[str, str]]) -> str:
    d = dict(rows)
    calls = d.get("Model calls", "")
    spend = d.get("Total model spend (from the ledger)", "")
    cents = ""
    m = re.search(r"USD ([\d.]+)", spend)
    if m:
        cents = f"about {round(float(m.group(1)) * 100)} cents"
    return (
        f"The results of the real run on Azure OpenAI. {d.get('Messages sent', '')} messages were sent. "
        f"{d.get('Work orders open', '')} work orders were opened. {d.get('Follow-up questions asked', '')} follow up "
        f"questions were asked and {d.get('Follow-ups resolved by a scripted reply', '')} were resolved by the scripted "
        f"replies. {d.get('Needs staff review', '')} went to staff review: the wrong shop message and the order matched by "
        f"the cancellation. {d.get('No work order (price inquiry / cancellation)', '')} produced no order: the price "
        f"inquiry and the cancellation itself. {d.get('Could not process (invalid output / provider failure)', '')} could "
        f"not be processed. In total {calls}. Total spend from the ledger was {cents}, at the configured price table. "
        "The brief's limit was twenty dollars. Every raw model response is recorded in the repository."
    )


def scene_html(sc: dict, idx: int) -> str:
    foot = f'<div class="foot"><span>Riverbend work orders</span><span>{idx + 1} / {len(SCENES)}</span></div>'
    k = sc["kind"]
    if k == "slide" and "bullets" not in sc:
        return f'<div class="slide title"><h1>{esc(sc["title"])}</h1><div class="sub">{esc(sc.get("subtitle", ""))}</div></div>'
    if k == "slide":
        items = "".join(f"<li>{esc(b)}</li>" for b in sc["bullets"])
        return f'<div class="slide"><h1>{esc(sc["title"])}</h1><ul>{items}</ul>{foot}</div>'
    if k == "code":
        lines = (ROOT / sc["file"]).read_text().splitlines()
        a, b = sc["lines"]
        body = "\n".join(f'<span class="ln">{n}</span>{esc(lines[n - 1])}' for n in range(a, min(b, len(lines)) + 1))
        return (
            f'<div class="slide"><h1>{esc(sc["title"])}</h1><div class="file">{esc(sc["file"])}</div>'
            f'<div class="code">{body}</div>{foot}</div>'
        )
    if k == "terminal":
        n = len(sc["captures"])
        per = {1: 34, 2: 17, 3: 12}.get(n, 9)
        blocks = []
        for name in sc["captures"]:
            cmd = shorten_cmd((CAP / (name + ".cmd")).read_text())
            out = trim_output((CAP / name).read_text(), per)
            blocks.append(f'<div class="term"><span class="cmd">{esc(cmd)}</span>\n{esc(out)}</div>')
        return f'<div class="slide"><h1>{esc(sc["title"])}</h1>{"".join(blocks)}{foot}</div>'
    if k == "results":
        rows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in results_table())
        return f'<div class="slide results"><h1>{esc(sc["title"])}</h1><table>{rows}</table>{foot}</div>'
    raise ValueError(k)


def render() -> None:
    from PIL import Image  # noqa: PLC0415

    SLIDES.mkdir(parents=True, exist_ok=True)
    for i, sc in enumerate(SCENES):
        if sc["kind"] in ("image", "video"):
            continue
        body = scene_html(sc, i)
        doc = f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'
        png = SLIDES / f"{sc['id']}.png"
        key = digest(doc)
        if stamp_ok(png, key):
            continue
        tmp = SLIDES / f"{sc['id']}.html"
        tmp.write_text(doc)
        r = sh(
            f'"{CHROME}" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 '
            f'--window-size={W},{H + 140} --screenshot="{png}" "{tmp.as_uri()}"'
        )
        if r.returncode != 0:
            raise SystemExit(r.stderr)
        im = Image.open(png)
        im.crop((0, 0, W, H)).save(png)
        tmp.unlink()
        stamp(png, key)
        print(f"[render] {png.name}")


# ----------------------------------------------------------------------------- tts
def narration_text(sc: dict) -> str:
    if sc["narration"] == "RESULTS_NARRATION":
        return results_narration(results_table())
    return sc["narration"]


def tts(engine: str, voice: str | None, ids: list[str] | None = None) -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    load_dotenv()
    for sc in SCENES:
        if ids and sc["id"] not in ids:
            continue
        text = narration_text(sc)
        m4a = AUDIO / f"{sc['id']}.m4a"
        key = digest(engine, voice or "", text)
        if stamp_ok(m4a, key):
            continue
        raw = AUDIO / f"{sc['id']}.raw"
        if engine == "say":
            v = voice or "Samantha"
            raw = raw.with_suffix(".aiff")
            r = sh(f'say -v "{v}" -r 172 -o "{raw}" "{text.replace(chr(34), chr(39))}"')
        elif engine == "elevenlabs":
            import httpx  # noqa: PLC0415

            key_env = os.environ.get("ELEVENLABS_API_KEY")
            if not key_env:
                raise SystemExit("ELEVENLABS_API_KEY not set (put it in .env)")
            vid = voice or os.environ.get("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM"
            raw = raw.with_suffix(".mp3")
            resp = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key_env, "accept": "audio/mpeg"},
                json={"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")},
                timeout=120,
            )
            if resp.status_code != 200:
                raise SystemExit(f"elevenlabs {resp.status_code}: {resp.text[:200]}")
            raw.write_bytes(resp.content)
            r = subprocess.CompletedProcess("", 0, "", "")
        else:
            raise SystemExit(f"unknown engine {engine}")
        if r.returncode != 0:
            raise SystemExit(r.stderr)
        r = sh(f'ffmpeg -y -v error -i "{raw}" -ar 48000 -ac 2 -c:a aac -b:a 128k "{m4a}"')
        if r.returncode != 0:
            raise SystemExit(r.stderr)
        raw.unlink()
        stamp(m4a, key)
        print(f"[tts:{engine}] {m4a.name} {duration(m4a):.1f}s")


# ----------------------------------------------------------------------------- assemble
VF_FIT = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:white,format=yuv420p"
VCODEC = "-c:v libx264 -preset medium -crf 20 -r 30 -pix_fmt yuv420p"
ACODEC = "-c:a aac -b:a 128k -ar 48000 -ac 2"


def segment(sc: dict) -> Path:
    SEG.mkdir(parents=True, exist_ok=True)
    out = SEG / f"{sc['id']}.mp4"
    audio = AUDIO / f"{sc['id']}.m4a"
    dur = duration(audio) + PAD
    if sc["kind"] in ("slide", "code", "terminal", "results"):
        src = SLIDES / f"{sc['id']}.png"
        key = digest("still", str(src.stat().st_mtime), str(audio.stat().st_mtime))
        if stamp_ok(out, key):
            return out
        cmd = (
            f'ffmpeg -y -v error -loop 1 -framerate 30 -i "{src}" -i "{audio}" -vf "{VF_FIT}" -af "apad" '
            f'-t {dur:.2f} {VCODEC} -tune stillimage {ACODEC} "{out}"'
        )
    elif sc["kind"] == "image":
        src = ROOT / sc["image"]
        key = digest("image", str(src.stat().st_mtime), str(audio.stat().st_mtime))
        if stamp_ok(out, key):
            return out
        cmd = (
            f'ffmpeg -y -v error -loop 1 -framerate 30 -i "{src}" -i "{audio}" -vf "{VF_FIT}" -af "apad" '
            f'-t {dur:.2f} {VCODEC} -tune stillimage {ACODEC} "{out}"'
        )
    elif sc["kind"] == "video":
        src = ROOT / sc["video"]
        key = digest("video", str(src.stat().st_mtime), str(audio.stat().st_mtime))
        if stamp_ok(out, key):
            return out
        vdur = duration(src) or 10.0
        factor = dur / vdur  # stretch the clip to the narration length
        cmd = (
            f'ffmpeg -y -v error -i "{src}" -i "{audio}" -filter_complex '
            f'"[0:v]setpts={factor:.4f}*PTS,{VF_FIT},fps=30[v];[1:a]apad[a]" -map "[v]" -map "[a]" '
            f'-t {dur:.2f} {VCODEC} {ACODEC} "{out}"'
        )
    else:
        raise ValueError(sc["kind"])
    r = sh(cmd)
    if r.returncode != 0:
        raise SystemExit(f"{sc['id']}: {r.stderr}")
    stamp(out, key)
    print(f"[segment] {out.name} {dur:.1f}s")
    return out


def assemble(ids: list[str] | None, out_name: str) -> None:
    chosen = [s for s in SCENES if not ids or s["id"] in ids]
    segs = [segment(s) for s in chosen]
    lst = SEG / f"{out_name}.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in segs))
    final = OUT / f"{out_name}.mp4"
    r = sh(f'ffmpeg -y -v error -f concat -safe 0 -i "{lst}" -c copy -movflags +faststart "{final}"')
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    total = sum(duration(p) for p in segs)
    print(f"[assemble] {final.relative_to(ROOT)}  {total / 60:.1f} min, {final.stat().st_size / 1e6:.1f} MB")


def script_md() -> None:
    lines = ["# Tutorial narration\n", "Read verbatim by the voice. Edit in `scripts/tutorial/scenes.py`.\n"]
    for i, sc in enumerate(SCENES):
        lines.append(f"\n## {i + 1}. {sc.get('title', sc['id'])}\n\n{narration_text(sc)}\n")
    (OUT / "script.md").write_text("".join(lines))
    print("[script] docs/tutorial/script.md")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["capture", "render", "tts", "assemble", "script", "all"])
    ap.add_argument("--engine", default="say")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--ids", default=None, help="comma-separated scene ids for a partial assemble")
    ap.add_argument("--out", default="riverbend-tutorial")
    a = ap.parse_args()
    if a.step in ("capture", "all"):
        capture()
    if a.step in ("render", "all"):
        render()
    if a.step in ("tts", "all"):
        tts(a.engine, a.voice, a.ids.split(",") if a.ids else None)
    if a.step in ("script", "all"):
        script_md()
    if a.step in ("assemble", "all"):
        assemble(a.ids.split(",") if a.ids else None, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
