"""Pytest 引导：把 backend 根目录加入 sys.path，保证裸 ``import app`` 可用。

隐藏测试无论从哪个工作目录被调用，都会先加载本 conftest。
"""
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
