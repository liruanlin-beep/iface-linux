"""Native file dialogs with purpose-specific folder history across app restarts."""

from tkinter import filedialog


def _options(config, purpose, options):
    options = dict(options)
    if config is not None:
        directory = config.get_dialog_directory(purpose, options.get("initialdir"))
        if directory:
            options["initialdir"] = directory
    return options


def askopenfilename(config, purpose, **options):
    path = filedialog.askopenfilename(**_options(config, purpose, options))
    if path and config is not None:
        config.remember_dialog_path(purpose, path)
    return path


def askopenfilenames(config, purpose, **options):
    paths = filedialog.askopenfilenames(**_options(config, purpose, options))
    if paths and config is not None:
        first = paths if isinstance(paths, str) else paths[0]
        config.remember_dialog_path(purpose, first)
    return paths


def asksaveasfilename(config, purpose, **options):
    path = filedialog.asksaveasfilename(**_options(config, purpose, options))
    if path and config is not None:
        config.remember_dialog_path(purpose, path)
    return path


def askdirectory(config, purpose, **options):
    path = filedialog.askdirectory(**_options(config, purpose, options))
    if path and config is not None:
        config.remember_dialog_path(purpose, path, is_directory=True)
    return path
