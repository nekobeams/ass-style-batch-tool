"""內嵌 mpv 播放器 widget:載入影片、外掛字幕熱重載、seek;缺 libmpv 時優雅降級。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget


def _import_mpv():
    """獨立函式以便測試 monkeypatch;缺 libmpv 時 python-mpv 會丟 OSError。"""
    try:
        import mpv
        return mpv
    except (ImportError, OSError):
        return None


class MpvPlayerWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        # mpv 以原生視窗控制代碼(wid)嵌入,需要真正的原生視窗
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self._mpv = None
        self._video_path: Optional[Path] = None
        self._sub_added = False

        self._hint = QLabel("尚未載入影片\n(缺 libmpv 時預覽停用,不影響批次功能)")
        self._hint.setAlignment(Qt.AlignCenter)
        layout = QStackedLayout(self)
        layout.addWidget(self._hint)
        self.setMinimumSize(320, 180)
        # 點擊取得鍵盤焦點,空白/方向鍵才會送到本 widget
        self.setFocusPolicy(Qt.StrongFocus)

    # ---------- 可用性 ----------
    def available(self) -> bool:
        return _import_mpv() is not None

    def _ensure_player(self) -> bool:
        if self._mpv is not None:
            return True
        mpv_module = _import_mpv()
        if mpv_module is None:
            return False
        # mpv 以 wid 嵌入時會在此 widget 下建一個「停用(WS_DISABLED)」的
        # 子視窗:真實滑鼠/鍵盤輸入永遠不會送達停用視窗,而是穿透到父視窗
        # (本 widget)。因此輸入一律在 Qt 層處理(mouse/key/wheelEvent),
        # mpv 端關閉預設綁定即可。
        self._mpv = mpv_module.MPV(
            wid=str(int(self.winId())),
            osc=False,
            input_default_bindings=False,
            keep_open="yes",
        )
        return True

    # ---------- 操作(缺 mpv 時皆安全 no-op) ----------
    def load_video(self, path: Path) -> bool:
        if not self._ensure_player():
            return False
        self._video_path = Path(path)
        self._sub_added = False
        self._hint.hide()
        self._mpv.play(str(path))
        self._mpv.pause = True
        return True

    def video_loaded(self) -> bool:
        return self._mpv is not None and self._video_path is not None

    def show_subtitle(self, ass_path: Path) -> None:
        """外掛字幕:首次 sub-add,之後同一路徑熱重載(sub-reload)。"""
        if not self.video_loaded():
            return
        if not self._sub_added:
            self._mpv.command("sub-add", str(ass_path), "select")
            self._sub_added = True
        else:
            self._mpv.command("sub-reload")

    def seek(self, seconds: float) -> None:
        if not self.video_loaded():
            return
        self._mpv.command("seek", seconds, "absolute")
        self._mpv.pause = True

    def seek_relative(self, seconds: float) -> None:
        """相對快進/快退;不改變播放/暫停狀態。"""
        if not self.video_loaded():
            return
        self._mpv.command("seek", seconds, "relative")

    def toggle_pause(self) -> None:
        if self.video_loaded():
            self._mpv.pause = not self._mpv.pause

    def position(self) -> Optional[float]:
        """目前播放位置(秒);缺 mpv 或尚未就緒時回 None。"""
        if not self.video_loaded():
            return None
        try:
            return self._mpv.time_pos
        except Exception:
            return None

    def duration(self) -> Optional[float]:
        """影片總長度(秒);缺 mpv 或尚未就緒時回 None。"""
        if not self.video_loaded():
            return None
        try:
            return self._mpv.duration
        except Exception:
            return None

    def shutdown(self) -> None:
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:
                pass  # 關閉階段的清理失敗不影響程式結束
            self._mpv = None
        self._video_path = None

    # ---------- Qt 層輸入(mpv 子視窗停用,事件穿透到本 widget) ----------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.video_loaded():
            self.toggle_pause()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if self.video_loaded():
            key = event.key()
            if key == Qt.Key_Space:
                self.toggle_pause()
                event.accept()
                return
            if key == Qt.Key_Right:
                self.seek_relative(10)
                event.accept()
                return
            if key == Qt.Key_Left:
                self.seek_relative(-10)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if self.video_loaded():
            delta = event.angleDelta().y()
            if delta:
                self.seek_relative(10 if delta > 0 else -10)
                event.accept()
                return
        super().wheelEvent(event)
