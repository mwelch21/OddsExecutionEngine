def build_line_key(line: float | None) -> str:
    if line is None:
        return "none"

    return format(line, ".4f")
