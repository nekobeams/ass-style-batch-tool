from __future__ import annotations


def test_run_app_entrypoint_importable():
    import run_app
    assert callable(run_app.main)
