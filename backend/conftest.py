"""Pytest 引导：保证从任意目录调用 pytest 都能导入 backend/app 包。"""
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
