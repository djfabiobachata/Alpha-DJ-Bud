"""In-app updates from GitHub releases.

The installed app lives in ~/Library/Application Support/Alpha DJ Bud/app.
`check()` asks GitHub for the latest release; `install()` downloads it,
verifies that the new code imports, swaps it in (keeping a backup) and
installs any new requirements. The caller then restarts the app.
"""
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from . import __version__

REPO = "djfabiobachata/Alpha-DJ-Bud"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
COPY_ITEMS = ["alpha_dj_bud", "assets", "requirements.txt"]


class UpdateError(Exception):
    """`code` is translated by the UI (upd.err.<code>)."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def parse_version(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v or ""))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "AlphaDJBud/%s" % __version__,
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_context()) as r:
            return r.read()
    except Exception as e:
        raise UpdateError("network", str(e))


def installed_app_dir(home):
    """The folder the installer copies the app into, if we run from it."""
    target = os.path.join(home, "app")
    here = os.path.dirname(PACKAGE_DIR)
    try:
        if os.path.samefile(here, target):
            return target
    except OSError:
        pass
    return None


def check():
    """Return info about the latest GitHub release."""
    data = json.loads(_get(API_LATEST).decode("utf-8"))
    tag = data.get("tag_name") or ""
    return {
        "current": __version__,
        "latest": tag.lstrip("vV"),
        "tag": tag,
        "available": is_newer(tag),
        "notes": (data.get("body") or "")[:3000],
        "url": data.get("html_url"),
        "zip": data.get("zipball_url"),
    }


def _extract(zip_bytes, dest):
    zpath = os.path.join(dest, "release.zip")
    with open(zpath, "wb") as f:
        f.write(zip_bytes)
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():  # refuse paths escaping the folder
            if name.startswith("/") or ".." in name.split("/"):
                raise UpdateError("badZip", name)
        z.extractall(os.path.join(dest, "x"))
    roots = os.listdir(os.path.join(dest, "x"))
    root = os.path.join(dest, "x", roots[0]) if len(roots) == 1 else os.path.join(dest, "x")
    if not os.path.isfile(os.path.join(root, "alpha_dj_bud", "__init__.py")):
        raise UpdateError("badZip", "alpha_dj_bud missing")
    return root


def install(home, info=None, zip_bytes=None, python=None):
    """Download and install the release. Returns the new version."""
    app_dir = installed_app_dir(home) if zip_bytes is None else os.path.join(home, "app")
    if not app_dir:
        raise UpdateError("notInstalled")
    info = info or check()
    if zip_bytes is None:
        if not info.get("available"):
            raise UpdateError("upToDate")
        zip_bytes = _get(info["zip"], timeout=120)
    python = python or sys.executable
    tmp = tempfile.mkdtemp(prefix="adb-update-")
    try:
        root = _extract(zip_bytes, tmp)
        new_dir = app_dir + ".new"
        shutil.rmtree(new_dir, ignore_errors=True)
        os.makedirs(new_dir)
        for item in COPY_ITEMS:
            src = os.path.join(root, item)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(new_dir, item))
            elif os.path.isfile(src):
                shutil.copy2(src, os.path.join(new_dir, item))
        # the new code must at least import before we switch to it
        r = subprocess.run([python, "-c", "import alpha_dj_bud.server, alpha_dj_bud.app;"
                            "import alpha_dj_bud as a; print(a.__version__)"],
                           cwd=new_dir, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            shutil.rmtree(new_dir, ignore_errors=True)
            raise UpdateError("verify", (r.stderr or r.stdout)[-500:])
        new_version = r.stdout.strip().splitlines()[-1]
        old_req = os.path.join(app_dir, "requirements.txt")
        new_req = os.path.join(new_dir, "requirements.txt")
        req_changed = (not os.path.exists(old_req) or
                       open(old_req, "rb").read() != open(new_req, "rb").read())
        backup = app_dir + ".old"
        shutil.rmtree(backup, ignore_errors=True)
        if os.path.exists(app_dir):
            os.rename(app_dir, backup)
        os.rename(new_dir, app_dir)
        if req_changed and os.path.exists(new_req):
            subprocess.run([python, "-m", "pip", "install", "--quiet", "-r", new_req],
                           capture_output=True, timeout=600)
        return new_version
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restart(home):
    """Start the freshly installed app in a new process and exit this one."""
    app_dir = os.path.join(home, "app")
    bundle = os.path.expanduser("~/Applications/Alpha DJ Bud.app")
    if sys.platform == "darwin" and os.path.isdir(bundle):
        cmd = ["/bin/sh", "-c", "sleep 1.5; /usr/bin/open -n %s" % _sh(bundle)]
    else:
        cmd = ["/bin/sh", "-c", "sleep 1.5; cd %s && exec %s -m alpha_dj_bud.app" % (_sh(app_dir), _sh(sys.executable))]
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os._exit(0)


def _sh(s):
    return "'" + s.replace("'", "'\\''") + "'"
