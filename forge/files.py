"""Workdir tree browser — adapted from bob's TreeWorker.pyw.

Shows the FORGE working directory as a tree with human-readable sizes,
so it's easy to see what datasets, checkpoints and voice packages exist
(and what's eating disk).
"""
import os


def _readable(size_in_bytes):
    if size_in_bytes == 0:
        return "0B"
    suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    size = float(size_in_bytes)
    while size >= 1024 and i < len(suffixes) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f}{suffixes[i]}"


def _dir_size(path):
    total = 0
    try:
        for _root, _dirs, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(_root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def tree_string(startpath, max_depth=4):
    """Directory tree with sizes, as plain text."""
    startpath = os.path.abspath(startpath)
    lines = []
    for root, dirs, files in os.walk(startpath):
        depth = root.replace(startpath, "").count(os.sep)
        if depth > max_depth:
            dirs[:] = []
            continue
        indent = "│   " * depth
        name = os.path.basename(root) or root
        lines.append(f"{indent}├── {name} ({_readable(_dir_size(root))})")
        subindent = "│   " * (depth + 1)
        for i, f in enumerate(sorted(files)):
            fp = os.path.join(root, f)
            try:
                sz = _readable(os.path.getsize(fp))
            except OSError:
                sz = "?"
            connector = "└──" if i == len(files) - 1 else "├──"
            lines.append(f"{subindent}{connector} {f} ({sz})")
    return "\n".join(lines) if lines else "(empty)"
