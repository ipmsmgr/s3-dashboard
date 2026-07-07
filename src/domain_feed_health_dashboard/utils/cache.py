"""Caching utilities for dashboard."""

import streamlit as st
from typing import Callable, Any, TypeVar, Optional
from datetime import timedelta

T = TypeVar("T")


def cache_data(
    max_entries: int = 32,
    ttl: Optional[int] = 3600,
) -> Callable:
    """Decorator for caching Streamlit data.
    
    Args:
        max_entries: Maximum cache entries
        ttl: Time to live in seconds
        
    Returns:
        Decorated function with caching
    """
    return st.cache_data(
        max_entries=max_entries,
        ttl=ttl,
    )


def clear_cache() -> None:
    """Clear Streamlit cache."""
    st.cache_data.clear()
