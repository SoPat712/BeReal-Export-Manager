import argparse
import curses
import json
import os
import sys
from datetime import datetime as dt
from datetime import timezone
from shutil import copy2 as cp
from typing import Optional

import pytz
from exiftool import ExifToolHelper as et
from PIL import Image, ImageDraw
from timezonefinder import TimezoneFinder


def init_parser() -> argparse.Namespace:
    """
    Initializes the argparse module.
    """
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Explain what is being done."
    )
    parser.add_argument(
        "--exiftool-path", dest="exiftool_path", help="Path to ExifTool executable."
    )
    parser.add_argument(
        "-t",
        "--timespan",
        type=str,
        help="DD.MM.YYYY-DD.MM.YYYY or wildcards with '*'.",
    )
    parser.add_argument("-y", "--year", type=int, help="Exports the given year.")
    parser.add_argument(
        "-p",
        "--out-path",
        dest="out_path",
        default="./out",
        help="Export output path (default ./out).",
    )
    parser.add_argument(
        "--bereal-path",
        dest="bereal_path",
        default=".",
        help="Path to BeReal data (default ./).",
    )
    parser.add_argument(
        "--no-memories",
        dest="memories",
        default=True,
        action="store_false",
        help="Don't export memories.",
    )
    parser.add_argument(
        "--no-realmojis",
        dest="realmojis",
        default=True,
        action="store_false",
        help="Don't export realmojis.",
    )
    parser.add_argument(
        "--no-composites",
        dest="composites",
        default=True,
        action="store_false",
        help="Don't create a composite image front-on-back for each memory.",
    )
    parser.add_argument(
        "--default-timezone",
        dest="default_tz",
        type=str,
        default=None,
        help="If no lat/lon or time zone lookup fails, fall back to this time zone (e.g. 'America/New_York').",
    )
    return parser.parse_args()


class CursesLogger:
    """
    When verbose is True and curses is available, we keep a multi-line log above
    and a pinned progress bar at the bottom. This might restart if the window is resized too small.
    """

    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)  # hide cursor

        self.max_y, self.max_x = self.stdscr.getmaxyx()
        self.log_height = self.max_y - 2  # keep bottom line(s) for the progress bar

        # create log window
        self.logwin = curses.newwin(self.log_height, self.max_x, 0, 0)
        self.logwin.scrollok(True)

        # create progress bar window
        self.pbwin = curses.newwin(1, self.max_x, self.log_height, 0)

        self.log_count = 0

    def print_log(self, text: str, force: bool = False):
        # Force doesn't matter in curses; we always show
        self.logwin.addstr(self.log_count, 0, text)
        self.logwin.clrtoeol()
        self.log_count += 1
        if self.log_count >= self.log_height:
            self.logwin.scroll(1)
            self.log_count -= 1
        self.logwin.refresh()

    def show_progress(self, iteration: int, total: int, prefix="", date_str=""):
        if total == 0:
            percent = 100
        else:
            percent = int(100 * iteration / total)

        bar_length = self.max_x - 30
        if bar_length < 10:
            bar_length = 10

        filled_len = bar_length * iteration // max(1, total)
        bar = "█" * filled_len + "-" * (bar_length - filled_len)

        line_str = f"{prefix} |{bar}| {percent}% - {date_str}"
        self.pbwin.clear()
        # Clip if the line is longer than the terminal
        self.pbwin.addstr(0, 0, line_str[: self.max_x - 1])
        self.pbwin.refresh()


class BasicLogger:
    """
    A fallback / minimal logger if curses fails or if verbose isn't set.
    """

    def __init__(self, verbose: bool):
        self.verbose = verbose

    def print_log(self, text: str, force: bool = False):
        if self.verbose or force:
            print(text)

    def show_progress(self, iteration: int, total: int, prefix="", date_str=""):
        # Overwrites one line with a simple bar
        if total == 0:
            percent = 100
        else:
            percent = int(100 * iteration / total)

        bar_length = 40
        filled_len = bar_length * iteration // max(1, total)
        bar = "=" * filled_len + "-" * (bar_length - filled_len)

        line_str = f"{prefix} |{bar}| {percent}% - {date_str}"
        sys.stdout.write("\r" + line_str)
        sys.stdout.flush()

        if iteration == total:
            print()  # newline after finishing


class BeRealExporter:
    """
    Main exporter logic, with curses or fallback for logs.
    Using timezone_at only (not closest_timezone_at).
    """

    def __init__(self, args: argparse.Namespace, logger):
        self.args = args
        self.logger = logger
        self.verbose = args.verbose
        self.exiftool_path = args.exiftool_path
        self.out_path = args.out_path.rstrip("/")
        self.bereal_path = args.bereal_path.rstrip("/")
        self.create_composites = args.composites
        self.default_tz = args.default_tz

        # parse timespan/year
        self.time_span = self.init_time_span(args)

        # For lat/lon lookups
        self.tf = TimezoneFinder()

    def init_time_span(self, args: argparse.Namespace) -> tuple:
        if args.timespan:
            try:
                start_str, end_str = args.timespan.strip().split("-")
                if start_str == "*":
                    start = dt(1970, 1, 1, tzinfo=timezone.utc)
                else:
                    naive_start = dt.strptime(start_str, "%d.%m.%Y")
                    start = naive_start.replace(tzinfo=timezone.utc)
                if end_str == "*":
                    end = dt.now(tz=timezone.utc)
                else:
                    naive_end = dt.strptime(end_str, "%d.%m.%Y")
                    naive_end = naive_end.replace(hour=23, minute=59, second=59)
                    end = naive_end.replace(tzinfo=timezone.utc)
                return start, end
            except ValueError:
                raise ValueError(
                    "Invalid timespan format. Use 'DD.MM.YYYY-DD.MM.YYYY' or '*' wildcard."
                )
        elif args.year:
            naive_start = dt(args.year, 1, 1)
            naive_end = dt(args.year, 12, 31, 23, 59, 59)
            return (
                naive_start.replace(tzinfo=timezone.utc),
                naive_end.replace(tzinfo=timezone.utc),
            )
        else:
            return (
                dt(1970, 1, 1, tzinfo=timezone.utc),
                dt.now(tz=timezone.utc),
            )

    def verbose_msg(self, msg: str):
        if self.verbose:
            self.logger.print_log(msg)

    def log(self, text: str, force: bool = False):
        self.logger.print_log(text, force=force)

    def show_progress(self, i: int, total: int, prefix="", date_str=""):
        self.logger.show_progress(i, total, prefix, date_str)

    def resolve_img_path(self, path_str: str) -> Optional[str]:
        if "/post/" in path_str:
            candidate = os.path.join(
                self.bereal_path, "Photos/post", os.path.basename(path_str)
            )
            if os.path.isfile(candidate):
                return candidate
        elif "/bereal/" in path_str:
            candidate = os.path.join(
                self.bereal_path, "Photos/bereal", os.path.basename(path_str)
            )
            if os.path.isfile(candidate):
                return candidate

        # fallback
        p1 = os.path.join(self.bereal_path, "Photos/post", os.path.basename(path_str))
        p2 = os.path.join(self.bereal_path, "Photos/bereal", os.path.basename(path_str))
        if os.path.isfile(p1):
            return p1
        if os.path.isfile(p2):
            return p2
        return None

    def localize_datetime(self, dt_utc: dt, lat: float, lon: float) -> dt:
        """
        Use tf.timezone_at(...) only. If lat/lon missing or fails, fallback to default tz or stay UTC.
        """
        if lat is None or lon is None:
            # fallback
            if self.default_tz:
                try:
                    fallback_zone = pytz.timezone(self.default_tz)
                    return dt_utc.astimezone(fallback_zone)
                except Exception as e:
                    self.verbose_msg(
                        f"Warning: fallback time zone '{self.default_tz}' invalid: {e}"
                    )
            return dt_utc

        try:
            tz_name = self.tf.timezone_at(lng=lon, lat=lat)
            if tz_name:
                local_zone = pytz.timezone(tz_name)
                return dt_utc.astimezone(local_zone)
            else:
                # fallback
                if self.default_tz:
                    try:
                        fallback_zone = pytz.timezone(self.default_tz)
                        return dt_utc.astimezone(fallback_zone)
                    except Exception as e:
                        self.verbose_msg(
                            f"Warning: fallback time zone '{self.default_tz}' invalid: {e}"
                        )
                return dt_utc
        except Exception as e:
            self.verbose_msg(
                f"Warning: Time zone lookup failed for lat={lat}, lon={lon}: {e}"
            )
            if self.default_tz:
                try:
                    fallback_zone = pytz.timezone(self.default_tz)
                    return dt_utc.astimezone(fallback_zone)
                except Exception as e2:
                    self.verbose_msg(
                        f"Warning: fallback time zone '{self.default_tz}' invalid: {e2}"
                    )
            return dt_utc

    def embed_exif(
        self, file_name: str, dt_utc: dt, lat: float = None, lon: float = None
    ):
        final_dt = self.localize_datetime(dt_utc, lat, lon)
        naive_local = final_dt.replace(tzinfo=None)

        tags = {
            "EXIF:DateTimeOriginal": naive_local.strftime("%Y:%m:%d %H:%M:%S"),
        }
        if lat is not None and lon is not None:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if lon >= 0 else "W"
            tags.update(
                {
                    "EXIF:GPSLatitude": abs(lat),
                    "EXIF:GPSLatitudeRef": lat_ref,
                    "EXIF:GPSLongitude": abs(lon),
                    "EXIF:GPSLongitudeRef": lon_ref,
                }
            )

        try:
            with (
                et(executable=self.exiftool_path) if self.exiftool_path else et()
            ) as ex:
                ex.set_tags(file_name, tags=tags, params=["-P", "-overwrite_original"])
        except Exception as e:
            self.log(f"Error embedding EXIF to {file_name}: {e}", force=True)

    def copy_and_embed(
        self, old_path: str, new_path: str, dt_utc: dt, lat=None, lon=None
    ) -> Optional[str]:
        if not old_path or not os.path.isfile(old_path):
            self.log(f"File not found: {old_path}", force=True)
            return None

        ext = os.path.splitext(old_path)[1] or ".webp"
        new_path = os.path.splitext(new_path)[0] + ext
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        cp(old_path, new_path)

        self.embed_exif(new_path, dt_utc, lat, lon)
        self.verbose_msg(f"Copied & embedded {old_path} -> {new_path}")
        return new_path

    def create_composite(
        self,
        front_path: str,
        back_path: str,
        out_path: str,
        dt_utc: dt,
        lat=None,
        lon=None,
    ) -> Optional[str]:
        ext = os.path.splitext(out_path)[1] or ".webp"
        out_path = os.path.splitext(out_path)[0] + ext
        try:
            with Image.open(back_path) as b_img, Image.open(front_path) as f_img:
                b_img = b_img.convert("RGBA")
                f_img = f_img.convert("RGBA")

                b_w, b_h = b_img.size
                f_w, f_h = f_img.size
                scale_factor = max(1, b_w // 4)
                new_f_h = int((scale_factor / f_w) * f_h)
                front_resized = f_img.resize((scale_factor, new_f_h), Image.LANCZOS)

                # Round corners
                mask = Image.new("L", front_resized.size, 0)
                draw = ImageDraw.Draw(mask)
                radius = min(front_resized.size) // 8
                draw.rounded_rectangle(
                    [(0, 0), front_resized.size], radius=radius, fill=255
                )
                front_resized.putalpha(mask)

                b_img.alpha_composite(front_resized, (0, 0))

                final = b_img.convert("RGB")
                final.save(out_path)

        except Exception as e:
            self.log(
                f"Error creating composite for {front_path} & {back_path}: {e}",
                force=True,
            )
            return None

        # embed exif
        self.embed_exif(out_path, dt_utc, lat, lon)
        self.verbose_msg(f"Composite saved: {out_path}")
        return out_path

    def filter_memories_in_timespan(self, memories):
        valid = []
        start_dt, end_dt = self.time_span
        for m in memories:
            try:
                raw = m["takenTime"].replace("Z", "+00:00")
                d = dt.fromisoformat(raw).astimezone(timezone.utc)
            except:
                continue
            if start_dt <= d <= end_dt:
                valid.append(m)
        return valid

    def export_memories(self, memories):
        memories = self.filter_memories_in_timespan(memories)

        def dt_key(x):
            try:
                return dt.fromisoformat(x["takenTime"].replace("Z", "+00:00"))
            except:
                return dt.min.replace(tzinfo=timezone.utc)

        memories.sort(key=dt_key)

        out_mem = os.path.join(self.out_path, "memories")
        out_cmp = os.path.join(self.out_path, "composites")
        os.makedirs(out_mem, exist_ok=True)
        os.makedirs(out_cmp, exist_ok=True)

        total = len(memories)
        for i, mem in enumerate(memories, start=1):
            raw = mem["takenTime"].replace("Z", "+00:00")
            m_dt_utc = dt.fromisoformat(raw).astimezone(timezone.utc)
            loc = mem.get("location", {})
            lat = loc.get("latitude")
            lon = loc.get("longitude")

            front_src = self.resolve_img_path(mem["frontImage"]["path"])
            back_src = self.resolve_img_path(mem["backImage"]["path"])
            if not front_src or not back_src:
                self.log(
                    "Skipping memory due to missing front/back images.", force=True
                )
                self.show_progress(i, total, prefix="Exporting Memories")
                continue

            base_ts = m_dt_utc.strftime("%Y-%m-%d_%H-%M-%S")
            front_out = os.path.join(out_mem, f"{base_ts}_front")
            back_out = os.path.join(out_mem, f"{base_ts}_back")

            final_front = self.copy_and_embed(front_src, front_out, m_dt_utc, lat, lon)
            final_back = self.copy_and_embed(back_src, back_out, m_dt_utc, lat, lon)

            if self.create_composites and final_front and final_back:
                comp_out = os.path.join(out_cmp, f"{base_ts}_composite")
                self.create_composite(
                    final_front, final_back, comp_out, m_dt_utc, lat, lon
                )

            self.show_progress(
                i,
                total,
                prefix="Exporting Memories",
                date_str=m_dt_utc.strftime("%Y-%m-%d"),
            )

    def filter_realmojis_in_timespan(self, realmojis):
        valid = []
        start_dt, end_dt = self.time_span
        for r in realmojis:
            try:
                raw = r["postedAt"].replace("Z", "+00:00")
                d = dt.fromisoformat(raw).astimezone(timezone.utc)
            except:
                continue
            if start_dt <= d <= end_dt:
                valid.append(r)
        return valid

    def export_realmojis(self, realmojis):
        realmojis = self.filter_realmojis_in_timespan(realmojis)

        def dt_key(x):
            try:
                return dt.fromisoformat(x["postedAt"].replace("Z", "+00:00"))
            except:
                return dt.min.replace(tzinfo=timezone.utc)

        realmojis.sort(key=dt_key)

        out_rm = os.path.join(self.out_path, "realmojis")
        os.makedirs(out_rm, exist_ok=True)

        total = len(realmojis)
        for i, rm in enumerate(realmojis, start=1):
            raw = rm["postedAt"].replace("Z", "+00:00")
            rm_dt_utc = dt.fromisoformat(raw).astimezone(timezone.utc)
            media_path = os.path.basename(rm["media"]["path"])
            old_path = os.path.join(self.bereal_path, "Photos", "Realmoji", media_path)

            base_ts = rm_dt_utc.strftime("%Y-%m-%d_%H-%M-%S")
            out_file = os.path.join(out_rm, base_ts)

            self.copy_and_embed(old_path, out_file, rm_dt_utc)

            self.show_progress(
                i,
                total,
                prefix="Exporting Realmojis",
                date_str=rm_dt_utc.strftime("%Y-%m-%d"),
            )


def run_in_curses():
    """
    Attempts to run with curses-based logs/progress if verbose is True.
    If window is too small, might restart or fallback if curses.error triggers.
    """
    args = init_parser()

    if not args.verbose:
        # if not verbose, skip curses
        run_no_curses(args)
        return

    def main_curses(stdscr):
        logger = CursesLogger(stdscr)
        exporter = BeRealExporter(args, logger=logger)

        if args.memories:
            try:
                with open(
                    os.path.join(args.bereal_path, "memories.json"), encoding="utf-8"
                ) as f:
                    mems = json.load(f)
                    exporter.export_memories(mems)
            except FileNotFoundError:
                logger.print_log("Error: memories.json file not found.", force=True)
            except json.JSONDecodeError:
                logger.print_log("Error decoding memories.json file.", force=True)

        if args.realmojis:
            try:
                with open(
                    os.path.join(args.bereal_path, "realmojis.json"), encoding="utf-8"
                ) as f:
                    rms = json.load(f)
                    exporter.export_realmojis(rms)
            except FileNotFoundError:
                logger.print_log("Error: realmojis.json file not found.", force=True)
            except json.JSONDecodeError:
                logger.print_log("Error decoding realmojis.json file.", force=True)

        logger.print_log("\nAll done. Press any key to exit.")
        stdscr.getch()

    try:
        curses.wrapper(main_curses)
    except curses.error:
        print("Curses failed. Fallback to non-curses run.")
        run_no_curses(args)


def run_no_curses(args: argparse.Namespace):
    """
    Basic logger with inline progress bar, no curses.
    """
    logger = BasicLogger(verbose=args.verbose)
    exporter = BeRealExporter(args, logger=logger)

    if args.memories:
        try:
            with open(
                os.path.join(args.bereal_path, "memories.json"), encoding="utf-8"
            ) as f:
                mems = json.load(f)
                exporter.export_memories(mems)
        except FileNotFoundError:
            logger.print_log("Error: memories.json file not found.", force=True)
        except json.JSONDecodeError:
            logger.print_log("Error decoding memories.json file.", force=True)

    if args.realmojis:
        try:
            with open(
                os.path.join(args.bereal_path, "realmojis.json"), encoding="utf-8"
            ) as f:
                rms = json.load(f)
                exporter.export_realmojis(rms)
        except FileNotFoundError:
            logger.print_log("Error: realmojis.json file not found.", force=True)
        except json.JSONDecodeError:
            logger.print_log("Error decoding realmojis.json file.", force=True)


if __name__ == "__main__":
    run_in_curses()
