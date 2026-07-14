"""PyInstaller 打包進入點。

用絕對 import(而非 ass_style_tool/__main__.py 的相對 import),讓 PyInstaller
的靜態分析能追進 ass_style_tool 套件、正確收集 PySide6 等相依。開發時仍可用
`py -m ass_style_tool`(走 __main__.py);打包走這支。
"""
from ass_style_tool.qt.main_window import main

if __name__ == "__main__":
    main()
