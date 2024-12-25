import argparse
import json
import os
from datetime import datetime as dt
from shutil import copy2 as cp

from exiftool import ExifToolHelper as et


def init_parser() -> argparse.Namespace:
    """
    Initializes the argparse module.
    """
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "-v",
        "--verbose",
        default=False,
        action="store_true",
        help="Explain what is being done",
    )
    parser.add_argument(
        "--exiftool-path",
        dest="exiftool_path",
        type=str,
        help="Set the path to the ExifTool executable (needed if it isn't on the $PATH)",
    )
    parser.add_argument(
        "-t",
        "--timespan",
        type=str,
        help="Exports the given timespan\n"
        "Valid format: 'DD.MM.YYYY-DD.MM.YYYY'\n"
        "Wildcards can be used: 'DD.MM.YYYY-*'",
    )
    parser.add_argument("-y", "--year", type=int, help="Exports the given year")
    parser.add_argument(
        "-p",
        "--out-path",
        dest="out_path",
        type=str,
        default="./out",
        help="Set a custom output path (default ./out)",
    )
    parser.add_argument(
        "--bereal-path",
        dest="bereal_path",
        type=str,
        default=".",
        help="Set a custom BeReal path (default ./)",
    )
    parser.add_argument(
        "--no-memories",
        dest="memories",
        default=True,
        action="store_false",
        help="Don't export the memories",
    )
    parser.add_argument(
        "--no-realmojis",
        dest="realmojis",
        default=True,
        action="store_false",
        help="Don't export the realmojis",
    )
    args = parser.parse_args()
    if args.year and args.timespan:
        print("Timespan argument will be prioritized")
    return args


class BeRealExporter:
    def __init__(self, args: argparse.Namespace):
        self.time_span = self.init_time_span(args)
        self.exiftool_path = args.exiftool_path
        self.out_path = args.out_path.rstrip("/")
        self.bereal_path = args.bereal_path.rstrip("/")
        self.verbose = args.verbose

    @staticmethod
    def init_time_span(args: argparse.Namespace) -> tuple:
        """
        Initializes time span based on the arguments.
        """
        if args.timespan:
            try:
                start_str, end_str = args.timespan.strip().split("-")
                start = (
                    dt.fromtimestamp(0)
                    if start_str == "*"
                    else dt.strptime(start_str, "%d.%m.%Y")
                )
                end = dt.now() if end_str == "*" else dt.strptime(end_str, "%d.%m.%Y")
                return start, end
            except ValueError:
                raise ValueError(
                    "Invalid timespan format. Use 'DD.MM.YYYY-DD.MM.YYYY'."
                )
        elif args.year:
            return dt(args.year, 1, 1), dt(args.year, 12, 31)
        else:
            return dt.fromtimestamp(0), dt.now()

    def verbose_msg(self, msg: str):
        """
        Prints an explanation of what is being done to the terminal.
        """
        if self.verbose:
            print(msg)

    @staticmethod
    def get_img_filename(image: dict) -> str:
        """
        Returns the image filename from an image object (frontImage, backImage, primary, secondary).
        """
        return os.path.basename(image["path"])

    @staticmethod
    def get_datetime_from_str(time: str) -> dt:
        """
        Returns a datetime object from a time key.
        """
        try:
            format_string = "%Y-%m-%dT%H:%M:%S.%fZ"
            return dt.strptime(time, format_string)
        except ValueError:
            raise ValueError(f"Invalid datetime format: {time}")

    def export_img(
        self, old_img_name: str, img_name: str, img_dt: dt, img_location=None
    ):
        """
        Makes a copy of the image and adds EXIF tags to the image.
        """
        self.verbose_msg(f"Exporting {old_img_name} to {img_name}")

        # Adjust path if not found in the given location
        if not os.path.isfile(old_img_name):
            # Older format fallback
            fallback_img_name = os.path.join(
                self.bereal_path, "Photos/bereal", os.path.basename(old_img_name)
            )
            if os.path.isfile(fallback_img_name):
                old_img_name = fallback_img_name
            else:
                # Newer format fallback
                newer_img_name = os.path.join(
                    self.bereal_path, "Photos/post", os.path.basename(old_img_name)
                )
                if os.path.isfile(newer_img_name):
                    old_img_name = newer_img_name
                else:
                    print(f"File not found in expected locations: {old_img_name}")
                    return

        # Create output directory and copy file
        os.makedirs(os.path.dirname(img_name), exist_ok=True)
        cp(old_img_name, img_name)

        # Add EXIF metadata
        tags = {"DateTimeOriginal": img_dt.strftime("%Y:%m:%d %H:%M:%S")}
        if img_location:
            tags.update(
                {
                    "GPSLatitude": img_location["latitude"],
                    "GPSLongitude": img_location["longitude"],
                }
            )

        try:
            with (
                et(executable=self.exiftool_path) if self.exiftool_path else et()
            ) as exif_tool:
                exif_tool.set_tags(
                    img_name, tags=tags, params=["-P", "-overwrite_original"]
                )
            self.verbose_msg(f"Metadata added to {img_name}")
        except Exception as e:
            print(f"Error adding metadata to {img_name}: {e}")

    def export_memories(self, memories: list):
        """
        Exports all memories from the Photos directory to the corresponding output folder.
        """
        out_path_memories = os.path.join(self.out_path, "memories")
        os.makedirs(out_path_memories, exist_ok=True)

        for i, memory in enumerate(memories, start=1):
            memory_dt = self.get_datetime_from_str(memory["takenTime"])
            if not (self.time_span[0] <= memory_dt <= self.time_span[1]):
                continue

            # Loop through the front and back images
            for img_type, extension in [("frontImage", "webp"), ("backImage", "webp")]:
                # Handle both older and newer formats
                img_path = memory[img_type]["path"]
                if img_path.startswith("/"):
                    img_path = img_path[1:]  # Remove leading slash if present

                # Construct output filename
                img_name = f"{out_path_memories}/{memory_dt.strftime('%Y-%m-%d_%H-%M-%S')}_{img_type.replace('Image', '').lower()}.{extension}"

                # Construct the old image path
                old_img_name = os.path.join(self.bereal_path, img_path)

                # Export image
                img_location = memory.get("location", None)
                self.export_img(old_img_name, img_name, memory_dt, img_location)

            self.verbose_msg(f"Exported memory {i}/{len(memories)}")

    def export_realmojis(self, realmojis: list):
        """
        Exports all realmojis from the Photos directory to the corresponding output folder.
        """
        out_path_realmojis = os.path.join(self.out_path, "realmojis")
        os.makedirs(out_path_realmojis, exist_ok=True)

        for i, realmoji in enumerate(realmojis, start=1):
            realmoji_dt = self.get_datetime_from_str(realmoji["postedAt"])
            if not (self.time_span[0] <= realmoji_dt <= self.time_span[1]):
                continue

            img_name = (
                f"{out_path_realmojis}/{realmoji_dt.strftime('%Y-%m-%d_%H-%M-%S')}.webp"
            )
            old_img_name = os.path.join(
                self.bereal_path,
                realmoji["media"]["path"],
            )
            self.export_img(old_img_name, img_name, realmoji_dt)

            self.verbose_msg(f"Exported realmoji {i}/{len(realmojis)}")


if __name__ == "__main__":
    args = init_parser()
    exporter = BeRealExporter(args)

    if args.memories:
        try:
            with open(
                os.path.join(args.bereal_path, "memories.json"), encoding="utf-8"
            ) as f:
                memories = json.load(f)
                exporter.export_memories(memories)
        except FileNotFoundError:
            print("Error: memories.json file not found.")
        except json.JSONDecodeError:
            print("Error decoding memories.json file.")

    if args.realmojis:
        try:
            with open(
                os.path.join(args.bereal_path, "realmojis.json"), encoding="utf-8"
            ) as f:
                realmojis = json.load(f)
                exporter.export_realmojis(realmojis)
        except FileNotFoundError:
            print("Error: realmojis.json file not found.")
        except json.JSONDecodeError:
            print("Error decoding realmojis.json file.")
