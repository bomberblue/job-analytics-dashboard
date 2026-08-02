"""
Supporting utilities for the dashboard.
Data formatting, caching, and common functions.
"""
import streamlit as st
import pandas as pd
from functools import lru_cache


@st.cache_data
def format_currency(value):
    """Format value as SGD currency."""
    if pd.isna(value):
        return "N/A"
    return f"${value:,.0f}"


@st.cache_data
def format_percentage(value):
    """Format value as percentage."""
    if pd.isna(value):
        return "N/A"
    return f"{value:.1f}%"


def filter_selectbox(label, options, all_label, **kwargs):
    """Selectbox whose first choice is an "all" sentinel meaning "don't filter".

    Returns the chosen option, or None when the sentinel is picked -- the form
    the data layer expects for "don't narrow on this dimension". `all_label` is
    passed per call rather than derived, because the boards word it differently
    ("All Sectors" against "All sectors"). Extra kwargs (`key`, `help`, ...) go
    straight to st.selectbox.
    """
    choice = st.selectbox(label, [all_label] + list(options), **kwargs)
    return None if choice == all_label else choice


def create_metric_columns(data_dict):
    """Create a row of metric columns."""
    cols = st.columns(len(data_dict))
    for col, (label, value) in zip(cols, data_dict.items()):
        with col:
            st.metric(label, value)


def create_comparison_table(df, title="", columns_to_show=None):
    """Create a styled comparison table."""
    if df.empty:
        st.info("No data available")
        return
    
    if columns_to_show:
        df = df[columns_to_show]
    
    st.dataframe(df, use_container_width=True, hide_index=True)


def load_sample_data(db_manager, table_name, limit=100):
    """Load sample data from a table."""
    df = db_manager.query(f"SELECT * FROM {table_name} LIMIT {limit}")
    return df
