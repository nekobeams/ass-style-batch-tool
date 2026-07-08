"""tkinter GUI:拖放資料夾、編輯目標樣式、掃描預覽、批次套用。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, ttk

from .batch_runner import run_batch, scan_folder
from .profile import (Profile, TargetStyle, load_profile, parse_ass_color,
                      save_profile)
from .resolution import ffprobe_available

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:  # 未安裝 tkinterdnd2 -> 退回純按鈕模式
    _HAS_DND = False

_STATUS_LABELS = {
    "matched": "已配對",
    "no_video": "無對應影片",
    "no_episode": "無法判斷集數",
    "ambiguous": "配對模糊",
}
_REPORT_LABELS = {"ok": "完成", "skipped": "跳過", "error": "錯誤"}


def _ass_to_hex_rgb(ass_colour: str) -> str:
    c = parse_ass_color(ass_colour)
    return f"#{c.r:02x}{c.g:02x}{c.b:02x}"


class App:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.root.title("ASS 字幕樣式批次工具")
        self.scan_result = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self.folder_var = tk.StringVar()
        self.output_mode_var = tk.StringVar(value="inplace")
        self.output_dir_var = tk.StringVar()
        self.profile_name_var = tk.StringVar(value="我的字幕標準")
        self.target_styles_var = tk.StringVar(value="Default")
        self.base_w_var = tk.StringVar(value="1920")
        self.base_h_var = tk.StringVar(value="1080")
        self.fontname_var = tk.StringVar(value="思源黑體 CN")
        self.fontsize_var = tk.StringVar(value="72")
        self.bold_var = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)
        self.colour_vars = {
            "主色": tk.StringVar(value="&H00FFFFFF"),
            "外框色": tk.StringVar(value="&H00000000"),
            "陰影色": tk.StringVar(value="&H00000000"),
        }
        self.outline_var = tk.StringVar(value="3.6")
        self.shadow_var = tk.StringVar(value="1.0")
        self.alignment_var = tk.StringVar(value="2")
        self.margin_l_var = tk.StringVar(value="20")
        self.margin_r_var = tk.StringVar(value="20")
        self.margin_v_var = tk.StringVar(value="24")

        self._build()
        if not ffprobe_available():
            self._log("提示: 找不到 ffprobe,預覽將不含影片解析度資訊與長寬比警告")
        self.root.after(100, self._poll_log)

    # ---------- UI 構建 ----------
    def _build(self) -> None:
        pad = {"padx": 4, "pady": 2}

        folder_frame = ttk.LabelFrame(self.root, text="輸入資料夾(可拖放)")
        folder_frame.pack(fill="x", **pad)
        entry = ttk.Entry(folder_frame, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True, **pad)
        ttk.Button(folder_frame, text="瀏覽...",
                   command=self._browse_folder).pack(side="left", **pad)
        if _HAS_DND:
            for widget in (self.root, entry):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        style_frame = ttk.LabelFrame(self.root, text="目標樣式")
        style_frame.pack(fill="x", **pad)
        text_rows = [
            ("設定檔名稱", self.profile_name_var),
            ("目標 Style 名稱(逗號分隔)", self.target_styles_var),
            ("字型名稱", self.fontname_var),
            ("字體大小", self.fontsize_var),
            ("外框寬度", self.outline_var),
            ("陰影深度", self.shadow_var),
        ]
        row = 0
        for label, var in text_rows:
            ttk.Label(style_frame, text=label).grid(
                row=row, column=0, sticky="w", **pad)
            ttk.Entry(style_frame, textvariable=var, width=32).grid(
                row=row, column=1, sticky="we", **pad)
            row += 1

        ttk.Label(style_frame, text="基準解析度(寬 x 高)").grid(
            row=row, column=0, sticky="w", **pad)
        res_box = ttk.Frame(style_frame)
        res_box.grid(row=row, column=1, sticky="w")
        ttk.Entry(res_box, textvariable=self.base_w_var, width=6).pack(side="left")
        ttk.Label(res_box, text=" x ").pack(side="left")
        ttk.Entry(res_box, textvariable=self.base_h_var, width=6).pack(side="left")
        row += 1

        ttk.Label(style_frame, text="粗體 / 斜體").grid(
            row=row, column=0, sticky="w", **pad)
        flag_box = ttk.Frame(style_frame)
        flag_box.grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(flag_box, text="粗體",
                        variable=self.bold_var).pack(side="left")
        ttk.Checkbutton(flag_box, text="斜體",
                        variable=self.italic_var).pack(side="left")
        row += 1

        ttk.Label(style_frame, text="對齊(1-9,小鍵盤方位)").grid(
            row=row, column=0, sticky="w", **pad)
        ttk.Combobox(style_frame, textvariable=self.alignment_var,
                     values=[str(i) for i in range(1, 10)], width=4,
                     state="readonly").grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ttk.Label(style_frame, text="邊距 L / R / V").grid(
            row=row, column=0, sticky="w", **pad)
        margin_box = ttk.Frame(style_frame)
        margin_box.grid(row=row, column=1, sticky="w")
        for var in (self.margin_l_var, self.margin_r_var, self.margin_v_var):
            ttk.Entry(margin_box, textvariable=var, width=6).pack(
                side="left", padx=2)
        row += 1

        self._swatches: dict[str, tk.Label] = {}
        for label, var in self.colour_vars.items():
            ttk.Label(style_frame, text=label).grid(
                row=row, column=0, sticky="w", **pad)
            colour_box = ttk.Frame(style_frame)
            colour_box.grid(row=row, column=1, sticky="w")
            swatch = tk.Label(colour_box, width=3, relief="sunken",
                              background=_ass_to_hex_rgb(var.get()))
            swatch.pack(side="left", padx=2)
            ttk.Entry(colour_box, textvariable=var, width=12).pack(
                side="left", padx=2)
            ttk.Button(colour_box, text="選色...",
                       command=lambda v=var: self._pick_colour(v)).pack(side="left")
            self._swatches[label] = swatch
            var.trace_add("write", lambda *_: self._refresh_swatches())
            row += 1
        style_frame.columnconfigure(1, weight=1)

        profile_frame = ttk.Frame(self.root)
        profile_frame.pack(fill="x", **pad)
        ttk.Button(profile_frame, text="載入設定檔...",
                   command=self._load_profile).pack(side="left", **pad)
        ttk.Button(profile_frame, text="另存設定檔...",
                   command=self._save_profile).pack(side="left", **pad)

        out_frame = ttk.LabelFrame(self.root, text="輸出模式")
        out_frame.pack(fill="x", **pad)
        ttk.Radiobutton(out_frame, text="原地覆蓋(自動備份 .bak)",
                        variable=self.output_mode_var,
                        value="inplace").pack(anchor="w")
        out_row = ttk.Frame(out_frame)
        out_row.pack(fill="x")
        ttk.Radiobutton(out_row, text="輸出到新資料夾:",
                        variable=self.output_mode_var,
                        value="outdir").pack(side="left")
        ttk.Entry(out_row, textvariable=self.output_dir_var).pack(
            side="left", fill="x", expand=True, **pad)
        ttk.Button(out_row, text="瀏覽...",
                   command=self._browse_output_dir).pack(side="left", **pad)

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **pad)
        self.scan_button = ttk.Button(action_frame, text="掃描並預覽配對",
                                      command=self._start_scan)
        self.scan_button.pack(side="left", **pad)
        self.run_button = ttk.Button(action_frame, text="開始套用樣式",
                                     command=self._start_run, state="disabled")
        self.run_button.pack(side="left", **pad)

        self.log_text = scrolledtext.ScrolledText(
            self.root, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, **pad)

    # ---------- 檔案/顏色選擇 ----------
    def _browse_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.folder_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_dir_var.set(path)
            self.output_mode_var.set("outdir")

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.folder_var.set(paths[0])

    def _pick_colour(self, var: tk.StringVar) -> None:
        try:
            initial = _ass_to_hex_rgb(var.get())
        except ValueError:
            initial = "#ffffff"
        rgb, _ = colorchooser.askcolor(color=initial)
        if rgb is None:
            return
        try:
            alpha = parse_ass_color(var.get()).a
        except ValueError:
            alpha = 0
        r, g, b = (int(round(x)) for x in rgb)
        var.set(f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}")

    def _refresh_swatches(self) -> None:
        for label, var in self.colour_vars.items():
            try:
                self._swatches[label].configure(
                    background=_ass_to_hex_rgb(var.get()))
            except (ValueError, tk.TclError):
                pass  # 使用者輸入到一半,先不更新色塊

    # ---------- Profile 欄位 <-> 物件 ----------
    def _collect_profile(self) -> Profile:
        style = TargetStyle(
            fontname=self.fontname_var.get().strip(),
            fontsize=float(self.fontsize_var.get()),
            bold=self.bold_var.get(),
            italic=self.italic_var.get(),
            primary_colour=self.colour_vars["主色"].get().strip(),
            outline_colour=self.colour_vars["外框色"].get().strip(),
            back_colour=self.colour_vars["陰影色"].get().strip(),
            outline=float(self.outline_var.get()),
            shadow=float(self.shadow_var.get()),
            alignment=int(self.alignment_var.get()),
            margin_l=int(self.margin_l_var.get()),
            margin_r=int(self.margin_r_var.get()),
            margin_v=int(self.margin_v_var.get()),
        )
        for colour in (style.primary_colour, style.outline_colour,
                       style.back_colour):
            parse_ass_color(colour)
        if not style.fontname:
            raise ValueError("字型名稱不可為空")
        names = [n.strip() for n in self.target_styles_var.get().split(",")
                 if n.strip()]
        if not names:
            raise ValueError("目標 Style 名稱不可為空")
        return Profile(
            profile_name=self.profile_name_var.get().strip() or "未命名",
            target_style_names=names,
            base_width=int(self.base_w_var.get()),
            base_height=int(self.base_h_var.get()),
            style=style,
        )

    def _apply_profile_to_fields(self, profile: Profile) -> None:
        self.profile_name_var.set(profile.profile_name)
        self.target_styles_var.set(", ".join(profile.target_style_names))
        self.base_w_var.set(str(profile.base_width))
        self.base_h_var.set(str(profile.base_height))
        t = profile.style
        self.fontname_var.set(t.fontname)
        self.fontsize_var.set(str(t.fontsize))
        self.bold_var.set(t.bold)
        self.italic_var.set(t.italic)
        self.colour_vars["主色"].set(t.primary_colour)
        self.colour_vars["外框色"].set(t.outline_colour)
        self.colour_vars["陰影色"].set(t.back_colour)
        self.outline_var.set(str(t.outline))
        self.shadow_var.set(str(t.shadow))
        self.alignment_var.set(str(t.alignment))
        self.margin_l_var.set(str(t.margin_l))
        self.margin_r_var.set(str(t.margin_r))
        self.margin_v_var.set(str(t.margin_v))

    def _load_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self._apply_profile_to_fields(load_profile(Path(path)))
        except Exception as exc:
            messagebox.showerror("載入失敗", str(exc))
            return
        self._log(f"已載入設定檔: {path}")

    def _save_profile(self) -> None:
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            messagebox.showerror("欄位錯誤", str(exc))
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        save_profile(profile, Path(path))
        self._log(f"已儲存設定檔: {path}")

    # ---------- Log ----------
    def _log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_log(self) -> None:
        try:
            while True:
                self._log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    # ---------- 掃描 ----------
    def _start_scan(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("錯誤", "請先選擇有效的輸入資料夾")
            return
        self.scan_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        threading.Thread(target=self._scan_worker, args=(Path(folder),),
                         daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            scan = scan_folder(folder)
        except Exception as exc:
            self.log_queue.put(f"掃描失敗: {exc}")
            self.root.after(0, lambda: self.scan_button.configure(state="normal"))
            return
        self.scan_result = scan
        for warning in scan.warnings:
            self.log_queue.put(f"警告: {warning}")
        self.log_queue.put(f"=== 掃描結果: 共 {len(scan.matches)} 個字幕檔 ===")
        for m in scan.matches:
            label = _STATUS_LABELS.get(m.status, m.status)
            ep = f"ep{m.episode:02d}" if m.episode is not None else "ep??"
            video = m.video_path.name if m.video_path else "-"
            res = (f" ({m.video_resolution[0]}x{m.video_resolution[1]})"
                   if m.video_resolution else "")
            self.log_queue.put(
                f"[{label}] {ep}  {m.sub_path.name}  <->  {video}{res}")
        if scan.matches:
            self.log_queue.put("請確認以上配對無誤後,按「開始套用樣式」")
        self.root.after(0, self._after_scan)

    def _after_scan(self) -> None:
        self.scan_button.configure(state="normal")
        if self.scan_result is not None and self.scan_result.matches:
            self.run_button.configure(state="normal")

    # ---------- 執行 ----------
    def _start_run(self) -> None:
        if self.scan_result is None:
            return
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            messagebox.showerror("欄位錯誤", str(exc))
            return
        output_dir = None
        if self.output_mode_var.get() == "outdir":
            out = self.output_dir_var.get().strip()
            if not out:
                messagebox.showerror("錯誤", "請先選擇輸出資料夾")
                return
            output_dir = Path(out)
        self.scan_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        threading.Thread(target=self._run_worker,
                         args=(profile, output_dir), daemon=True).start()

    def _run_worker(self, profile: Profile, output_dir) -> None:
        def on_progress(report) -> None:
            label = _REPORT_LABELS.get(report.status, report.status)
            self.log_queue.put(f"[{label}] {report.sub_path.name}")
            for message in report.messages:
                self.log_queue.put(f"    {message}")

        reports = run_batch(self.scan_result, profile, output_dir,
                            progress_cb=on_progress)
        ok = sum(1 for r in reports if r.status == "ok")
        skipped = sum(1 for r in reports if r.status == "skipped")
        errors = sum(1 for r in reports if r.status == "error")
        self.log_queue.put(
            f"=== 全部完成: 成功 {ok},跳過 {skipped},錯誤 {errors} ===")
        self.root.after(0, self._after_run)

    def _after_run(self) -> None:
        self.scan_button.configure(state="normal")
        self.run_button.configure(state="normal")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
