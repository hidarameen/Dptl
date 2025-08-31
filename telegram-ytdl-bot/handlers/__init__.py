"""
Handlers package initialization
Import all handlers to register them with Pyrogram
"""

# Import all handler modules to register them
from . import (
    start,
    download,
    admin,
    referral,
    subscription,
    callbacks
)

__all__ = [
    'start',
    'download', 
    'admin',
    'referral',
    'subscription',
    'callbacks'
]