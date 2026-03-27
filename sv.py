# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pygithub",
#     "python-daemon",
#     "lockfile",
#     "schedule",
#     "requests",
#     "semver",
# ]
# ///

import sys
import requests
import os
import platform
import socket
import logging
import logging.handlers
import shutil
import subprocess
import tarfile
import daemon
import schedule
import signal
import traceback
import functools
import github
import requests
from semver import Version
from time import sleep
from argparse import ArgumentParser
from schedule import every, repeat, run_pending, clear, CancelJob
from github import Github, Auth
from pathlib import Path
from lockfile.pidlockfile import PIDLockFile, AlreadyLocked
from urllib.parse import urlparse

GITHUB_AUTH_TOKEN = os.getenv("GITHUB_AUTH_TOKEN", "")
SERVER_BASE_URL = os.getenv("DROPME_SERVER_BASE_URL", "https://dropme.up.railway.app").rstrip("/")
MACHINE_API_KEY = os.getenv("MACHINE_API_KEY", "")

LOGGER_FORMAT = "%(asctime)s %(levelname)s:%(name)s %(message)s"
LOGGER_DATEFMT = "%Y-%m-%d %H:%M:%S"
LOG_ROTATION_BACKUP_COUNT = int(os.getenv("SV_LOG_BACKUP_COUNT", "14"))


def _default_state_home() -> Path:
    xdg_state = os.getenv("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser()
    if platform.system().lower().startswith("win"):
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "dropme" / "state"
    return Path("~/.local/state").expanduser()


def _default_data_home() -> Path:
    xdg_data = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return Path(xdg_data).expanduser()
    if platform.system().lower().startswith("win"):
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data)
    return Path("~/.local/share").expanduser()


STATE_DIR = Path(os.getenv("DROPME_STATE_DIR", str(_default_state_home() / "dropme"))).expanduser()
DATA_DIR = Path(os.getenv("DROPME_DATA_DIR", str(_default_data_home() / "dropme" / "gui"))).expanduser()

logger = logging.getLogger(__name__)


def update_videos() -> None:
    if not MACHINE_API_KEY:
        logger.error("MACHINE_API_KEY is not set; cannot update videos")
        return
    with requests.get(
        f"{SERVER_BASE_URL}/machines/videos",
        headers={
            "Authorization": f"Api-Key {MACHINE_API_KEY}",
        },
    ) as resp:
        latest_videos = resp.json()
    latest_videos_ids = list(map(lambda v: v["id"], latest_videos))
    current_videos_ids = get_current_gui_videos()
    downloaded_video_files: list[Path] = []
    removed_videos_ids: list[int] = []
    for video in latest_videos:
        if video["id"] not in current_videos_ids:
            downloaded_video_files.append(download_video(video))
    for video_id in current_videos_ids:
        if video_id not in latest_videos_ids:
            removed_videos_ids.append(video_id)
    if not latest_videos and not removed_videos_ids:
        return
    for video_id in removed_videos_ids:
        remove_video(video_id)
    for video_file in downloaded_video_files:
        os.rename(video_file, DATA_DIR / "videos" / video_file.name)


def update_gui() -> None:
    if not GITHUB_AUTH_TOKEN:
        logger.error("GITHUB_AUTH_TOKEN is not set; cannot update GUI from GitHub releases")
        return
    with Github(auth=Auth.Token(GITHUB_AUTH_TOKEN)) as gh:
        repo = gh.get_repo("dropmeteamwork/GUI")
        release = repo.get_latest_release()
        latest_version = release.tag_name
        latest_tarball = release.tarball_url
    current_version = get_current_gui_version()
    if not is_greater_version(latest_version, current_version):
        logger.info("gui version %s is up to date", latest_version)
        return
    logger.info("current gui version %s is outdated", current_version)
    logger.info("downloading latest gui version %s from %s", latest_version, latest_tarball)
    latest_tarball_file = STATE_DIR.joinpath(latest_version + ".tar.gz")
    try:
        with requests.get(
            latest_tarball,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {GITHUB_AUTH_TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28"
            },
            stream=True
        ) as resp:
            if resp.status_code != 200:
                logger.error(f"failed to download latest gui: {resp.status_code}, {resp.text}")
                return
            with latest_tarball_file.open("wb") as file:
                shutil.copyfileobj(resp.raw, file)
    except requests.RequestException as exc:
        logger.error(f"failed to download latest gui: {exc!s}")
        return
    logger.info("downloaded latest gui version to %s", latest_tarball_file)
    with tarfile.open(latest_tarball_file, "r:gz") as tf:
        tf.extractall(path=STATE_DIR, members=strip1(tf, f"gui-{latest_version}"), filter="data")
    latest_gui_dir = STATE_DIR.joinpath("gui-" + latest_version)
    current_gui_dir = STATE_DIR.joinpath("gui")
    current_gui_dir.unlink(missing_ok=True)
    current_gui_dir.symlink_to(latest_gui_dir, target_is_directory=True)
    running_gui_pid = get_current_gui_pid()
    if running_gui_pid is not None:
        try:
            os.kill(running_gui_pid, signal.SIGTERM)
        except OSError:
            pass
        else:
            logger.info("killed the currently running gui process")
    logger.info("launching updated gui")
    subprocess.Popen(["uv", "run", "gui"], cwd=current_gui_dir, start_new_session=True)


def download_video(video) -> Path:
    video_file = DATA_DIR.joinpath(str(video["id"]) + os.path.splitext(urlparse(video["video"]).path)[1])
    with requests.get(video["video"], stream=True) as resp:
        if resp.status_code != 200:
            logger.error(f"failed to download video: {resp.status_code}, {resp.text}")
            return
        with video_file.open("wb") as file:
            shutil.copyfileobj(resp.raw, file)
    return video_file


def remove_video(video_id):
    for file in DATA_DIR.joinpath("videos").glob(str(video_id) + ".*"):
        file.unlink()


def strip1(tf: tarfile.TarFile, new1: str | os.PathLike[str] = ""):
    for member in tf.getmembers():
        member.name = str(Path(new1, *Path(member.path).parts[1:]))
        yield member


def is_greater_version(tag1: str, tag2: str) -> bool:
    return Version.parse(tag1.lstrip("v")) > Version.parse(tag2.lstrip("v"))


def get_current_gui_videos() -> list[int]:
    return list(map(lambda p: int(p.stem), DATA_DIR.joinpath("videos").glob("*")))


def get_current_gui_socket() -> str:
    return str(DATA_DIR.joinpath("socket.pipe"))


def get_current_gui_pid() -> int | None:
    try:
        return int(DATA_DIR.joinpath("gui.pid").read_text().strip())
    except Exception:
        return None


def get_current_gui_version() -> str:
    try:
        return STATE_DIR.joinpath("gui/version.txt").read_text().strip()
    except Exception:
        return "0.0.0"


def catch_exceptions(job_func):
    @functools.wraps(job_func)
    def wrapper(*args, **kwargs):
        try:
            return job_func(*args, **kwargs)
        except:
            logger.critical(traceback.format_exc())
    return wrapper


def schedule_jobs() -> None:
    every(1).hours.do(catch_exceptions(update_gui))
    every(2).hours.do(catch_exceptions(update_videos))


def run() -> int | None:
    schedule_jobs()
    while True:
        run_pending()
        sleep(1)


def shutdown(signum, frame) -> None:
    logger.info("shutdown")
    clear()
    sys.exit()


def main(argv: list[str] | None = None) -> int | None:
    STATE_DIR.mkdir(exist_ok=True)

    if argv is None:
        argv = sys.argv[1:]

    parser = ArgumentParser(add_help=False)
    parser.add_argument("-d", dest="dev", action="store_true", help="Equivalent to -n -l -")
    parser.add_argument("-n", dest="no_daemon", action="store_true", help="Don't run as daemon")
    parser.add_argument("-l", dest="log_file", metavar="FILE", type=str, help="Log to file")
    parser.add_argument("-L", dest="log_level", metavar="LEVEL", default=logging.INFO, type=int, help="Set logging threshold")
    parser.add_argument("-h", "--help", action="help", help="Print usage and exit")
    parser.add_argument("-v", "--version", action="version", version="%(prog)s 0.1.0", help="Print sv version and exit")
    parser.add_argument("mode", nargs="?", choices=["start", "stop", "update-gui", "update-videos"], default="start", type=str)

    args = parser.parse_args(argv)

    if args.dev:
        if args.mode == "start" and (args.no_daemon or args.log_file):
            parser.error("-l or -n should not be specified together with -d")
        args.no_daemon = True
        args.log_file = "-"

    if args.mode != "start":
        if args.no_daemon:
            parser.error("not a daemon")
        if not args.log_file:
            args.log_file = "-"

    if not args.log_file:
        args.log_file = str(STATE_DIR / "sv.log")

    if args.log_file == "-":
        log_handler = logging.StreamHandler(sys.stdout)
    else:
        log_handler = logging.handlers.TimedRotatingFileHandler(
            args.log_file,
            when="midnight",
            interval=1,
            backupCount=LOG_ROTATION_BACKUP_COUNT,
            encoding="utf-8",
        )

    logging.basicConfig(format=LOGGER_FORMAT, datefmt=LOGGER_DATEFMT, level=args.log_level, handlers=[log_handler])

    if args.mode == "update-gui":
        update_gui()
        return

    if args.mode == "update-videos":
        update_videos()
        return

    pidpath = STATE_DIR / "sv.lock"
    logger.info("PID lock file set to %s", pidpath)

    if args.mode == "stop":
        pid = None
        try:
            with pidpath.open("r") as pidfile:
                line = pidfile.readline().strip()
        except OSError as exc:
            logger.critical("%s: %s", exc.filename, exc.strerror)
            return 1
        try:
            pid = int(line)
        except ValueError:
            logger.critical("invalid pidfile format")
            return 1
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            logger.critical("%d: %s", pid, exc.strerror)
            return 1
        logger.info("stopped")
        return

    pidfile = PIDLockFile(pidpath)

    if args.no_daemon:
        signal.signal(signal.SIGTERM, shutdown)
        try:
            with pidfile:
                return run()
        except AlreadyLocked as exc:
            logger.critical("%s", *exc.args)
            return 1

    if isinstance(log_handler, logging.FileHandler):
        daemon_files_preserve = [log_handler.stream.fileno()]
        daemon_stdout = None
    elif isinstance(log_handler, logging.StreamHandler):
        daemon_files_preserve = []
        daemon_stdout = log_handler.stream
    else:
        daemon_files_preserve = []
        daemon_stdout = None

    try:
        with daemon.DaemonContext(
            files_preserve=daemon_files_preserve,
            umask=0o022,
            pidfile=pidfile,
            stdout=daemon_stdout,
            signal_map={
                signal.SIGTERM: shutdown,
            }
        ):
            return run()
    except AlreadyLocked as exc:
        logger.critical("%s", *exc.args)
        return 1


if __name__ == "__main__":
    sys.exit(main())
