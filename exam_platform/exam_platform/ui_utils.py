def esc(text) -> str:
    """Stop Streamlit's markdown from eating underscores (fill-in-the-blank) and $ signs."""
    return str(text or "").replace("_", "\\_").replace("$", "\\$")
