def make_terminal_link(url, text=None):
    """
    Returns an OSC 8 hyperlink for supported terminals (iTerm2, GNOME Terminal, etc).
    If not supported, the text will just display as normal.
    """
    if not text:
        text = url
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\" 