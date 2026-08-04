"""
Shared chart color palette, so every board's charts read as one system
instead of each picking its own default: blue for postings/activity (a
count), orange for anything denominated in dollars.

No streamlit/altair/matplotlib imports -- just constants, so any board or
chart module can use it regardless of rendering library.
"""
VOLUME_COLOR = '#2a78d6'
PAY_COLOR = '#eb6834'
