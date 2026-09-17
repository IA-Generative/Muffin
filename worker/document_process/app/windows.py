def sliding_windows(total_pages: int, window_pages: int, slide_pages: int) -> list[tuple[int, int]]:
    """1-indexed inclusive (start, end) page ranges covering every page at
    least once. `slide_pages` is the stride, not the overlap - overlap is
    `window_pages - slide_pages`. Always returns at least one window, even
    for a document shorter than `window_pages`."""
    if total_pages <= 0:
        return []
    window_pages = max(window_pages, 1)
    slide_pages = max(slide_pages, 1)

    windows: list[tuple[int, int]] = []
    start = 1
    while True:
        end = min(start + window_pages - 1, total_pages)
        windows.append((start, end))
        if end >= total_pages:
            break
        start += slide_pages
    return windows
