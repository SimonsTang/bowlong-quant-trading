#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略库：导入各模块触发 @register 注册。"""
from . import base, trend, mean_revert, momentum, factor, pairs_grid, breakout  # noqa: F401

__all__ = ["base"]
