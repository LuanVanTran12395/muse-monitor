"""Find and load extensions from folders and from entry points of pip packages."""
import importlib.util
import inspect
import os
import sys
import traceback
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from .api import Extension

ENTRY_POINT_GROUP = "musemonitor.extensions"
ENV_VAR = "MUSEMONITOR_EXTENSIONS"
PROJECT_DIR = Path(__file__).resolve().parents[3] / "extensions"   # <repo>/extensions (when running from src/)
USER_DIR = Path.home() / ".musemonitor" / "extensions"


def search_dirs():
    """Extension folders in priority order: environment variable → project folder → user folder."""
    dirs = [Path(p).expanduser() for p in os.environ.get(ENV_VAR, "").split(os.pathsep) if p]
    dirs += [PROJECT_DIR, USER_DIR]
    out = []
    for d in dirs:
        if d.is_dir() and d.resolve() not in [o.resolve() for o in out]: out.append(d)
    return out


def default_dir():
    """Default folder for creating new extensions / opening from the UI."""
    return PROJECT_DIR if PROJECT_DIR.is_dir() else USER_DIR


@dataclass
class Discovered:
    id: str
    source: str
    cls: type = None
    error: str = None


def _import_path(path):
    """Load a .py file or a package folder under a private module name so it cannot clash with other modules."""
    pkg = path.is_dir()
    name = f"musemonitor_ext_{path.stem if not pkg else path.name}"
    init = path / "__init__.py" if pkg else path
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(path)] if pkg else None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                 # allows relative imports inside the package
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None); raise
    return mod


def extension_class(obj):
    """Get the Extension class from a module (EXTENSION variable, or the only subclass defined in the module)."""
    if inspect.isclass(obj) and issubclass(obj, Extension): return obj
    cls = getattr(obj, "EXTENSION", None)
    if cls is not None: return cls
    found = [c for _, c in inspect.getmembers(obj, inspect.isclass)
             if issubclass(c, Extension) and c is not Extension and c.__module__ == obj.__name__]
    if len(found) != 1:
        raise ImportError("module must define EXTENSION = <Extension subclass> "
                          f"(found {len(found)} Extension subclasses)")
    return found[0]


def _candidates(d):
    for child in sorted(d.iterdir()):
        if child.name.startswith(("_", ".")): continue          # _template, __pycache__, .DS_Store…
        if child.is_dir() and (child / "__init__.py").exists(): yield child
        elif child.suffix == ".py": yield child


def discover(dirs=None, use_entry_points=True, skip=()):
    """Find and import extensions. ``skip``: ``source`` values already loaded — skipped, NOT re-imported
    (used when checking for new extensions while the app is running)."""
    out = []
    skip = set(skip)
    for d in (search_dirs() if dirs is None else [Path(x) for x in dirs]):
        for path in _candidates(d):
            if str(path) in skip: continue
            item = Discovered(id=path.stem if path.is_file() else path.name, source=str(path))
            try:
                item.cls = extension_class(_import_path(path))
                item.id = item.cls.id or item.id
            except BaseException:
                item.error = traceback.format_exc()
            out.append(item)
    if use_entry_points:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if f"package: {ep.value}" in skip: continue
            item = Discovered(id=ep.name, source=f"package: {ep.value}")
            try:
                item.cls = extension_class(ep.load())
                item.id = item.cls.id or item.id
            except BaseException:
                item.error = traceback.format_exc()
            out.append(item)
    return out
