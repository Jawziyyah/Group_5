import time

import streamlit as st

# Works two ways:
#   new style: show_timer(deadline_timestamp) and seconds_left(deadline_timestamp)
#   old style: start_timer(minutes, key), show_timer(key), seconds_left(key),
#              is_time_up(key), reset_timer(key)


def _deadline(x="exam"):
    if isinstance(x, (int, float)):
        return float(x)
    return st.session_state.get(f"{x}_deadline")


def start_timer(minutes: int, key: str = "exam"):
    k = f"{key}_deadline"
    if k not in st.session_state:
        st.session_state[k] = time.time() + minutes * 60


def seconds_left(x="exam") -> int:
    d = _deadline(x)
    if d is None:
        return 0
    return max(0, int(d - time.time()))


def is_time_up(x="exam") -> bool:
    return seconds_left(x) <= 0


def reset_timer(key: str = "exam"):
    st.session_state.pop(f"{key}_deadline", None)


@st.fragment(run_every=1)
def show_timer(x="exam"):
    """Live countdown. Refreshes itself every second without reloading the questions."""
    remaining = seconds_left(x)
    mins, secs = divmod(remaining, 60)
    text = f"⏱️ Time left: {mins:02d}:{secs:02d}"
    if remaining <= 60:
        st.error(text)
    elif remaining <= 300:
        st.warning(text)
    else:
        st.info(text)
    if remaining == 0:
        st.rerun()      # reruns the whole page, which then auto-submits