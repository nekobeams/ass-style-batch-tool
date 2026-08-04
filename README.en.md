English | **[繁體中文](README.md)**

# ASS Subtitle Style Batch Tool

Batch-edit ASS/SSA subtitle styles across a whole anime season, without touching files by hand or breaking anything you didn't ask to change.

> **The application UI, in-app text, and full documentation are Traditional Chinese only.** This page is a short summary for browsers who don't read Chinese; it is not a translation of the app itself. The primary audience is the Chinese-speaking anime-subtitling/collecting community.

## What it does

Subtitle files collected from different fansub groups often disagree on resolution and style settings, so the same "normal dialogue" line looks a different size from episode to episode. This tool:

1. **Scales per source resolution** — each file's target-style values are recalculated from its own `PlayResX`/`PlayResY`, so the visual size stays consistent across mixed-resolution sources, instead of forcing one fixed number onto everything.
2. **Touches only the styles you name** — modifies exactly the target Style(s) you pick (e.g. `Default`); OP/ED/signs/other styles, and headers like `PlayResX`/`PlayResY`/`ScaledBorderAndShadow`, are left untouched.
3. **Matches by episode number, not filename** — subtitle and video files don't need matching names; common fansub naming conventions (`[VCB-Studio]`, `[LoliHouse]`, `[DBD-Raws]`, etc.) are recognized.

## Four tabs

- **Subtitle files** — batch-apply a style profile or scale font size, with a live "what will change" preview per episode before you run it.
- **MKV** — edit subtitle tracks embedded inside MKV containers directly.
- **Mux** — mux external subtitle files (optionally style them first) into their matching MKVs.
- **Style & Preview** — an embedded mpv player: click a subtitle line to seek, see the styled result live.

The style-name list is *scanned from your files*, not something you have to look up in another program first.

## How it works, briefly

Set up your style (font, size, colour, outline, shadow, alignment, margins) and a **base resolution** in the *Style & Preview* tab; save it as a reusable JSON profile. Then, in whichever tab suits the job:

- **Subtitle files** — pick a folder (it scans automatically), tick the target style names the scan found, choose in-place (with `.bak` backup) or output-to-folder, check the per-episode "what will change" column, and run.
- **MKV** — pick a folder of MKVs, use *修改既有軌道…* ("modify existing tracks") to select which embedded subtitle tracks to restyle by **language + track name** (not track index, so an extra audio track in one episode won't shift the target), then run.
- **Mux** — pick a video folder and a subtitle folder, they're paired by episode number (unmatched rows can be assigned manually from a dropdown), choose whether to style the subtitles first, set the new track's language/name/default/forced flags, and mux.

Double-clicking any table row loads that episode into the embedded mpv player so you can see the styled result before committing.

Requires MKVToolNix for the MKV and Mux tabs.

## Download

Windows installer on the [Releases](../../releases) page. It auto-detects existing ffmpeg/MKVToolNix installs and only offers to install what's missing; libmpv (for the preview) is always bundled.

## License

[GPLv3](LICENSE). Uses [libmpv](https://github.com/mpv-player/mpv) (GPLv2-or-later); the installer ships its license text under `installer_payload/libmpv/`.

For install-from-source instructions, usage, and everything else, see the [full (Traditional Chinese) README](README.md).
