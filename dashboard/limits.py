# -*- coding: utf-8 -*-
"""Shared rate-limiter instance for dashboard routes."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
