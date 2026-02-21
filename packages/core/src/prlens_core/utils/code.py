NON_CODE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".bmp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".mp4",
    ".mp3",
    ".wav",
    ".ogg",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    ".lock",  # e.g. package-lock.json, Pipfile.lock
}


def is_code_file(file_name: str) -> bool:
    return not any(file_name.lower().endswith(ext) for ext in NON_CODE_EXTENSIONS)
