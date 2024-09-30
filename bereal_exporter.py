import json
import os
from exiftool import ExifToolHelper as et
from shutil import copy2 as cp
from datetime import datetime as dt
import argparse



def init_parser() -> argparse.Namespace:
  """
  Initializes the argparse module.
  """
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('-v', '--verbose', default=False, action='store_true', help="Explain what is being done")
  parser.add_argument('--exiftool-path', dest='exiftool_path', type=str, help="Set the path to the ExifTool executable (needed if it isn't on the $PATH)")
  parser.add_argument('-t', '--timespan', type=str, help="Exports the given timespan\n"
                                                         "Valid format: 'DD.MM.YYYY-DD.MM.YYYY'\n"
                                                         "Wildcards can be used: 'DD.MM.YYYY-*'")
  parser.add_argument('-y', '--year', type=int, help="Exports the given year")
  parser.add_argument('-p', '--out-path', dest='out_path', type=str, default="./out", help="Set a custom output path (default ./out)")
  parser.add_argument('--bereal-path', dest='bereal_path', type=str, default=".", help="Set a custom BeReal path (default ./)")
  parser.add_argument('--no-memories', dest='memories', default=True, action='store_false', help="Don't export the memories")
  parser.add_argument('--no-realmojis', dest='realmojis', default=True, action='store_false', help="Don't export the realmojis")
  args = parser.parse_args()
  if args.year and args.timespan:
      print("Timespan argument will be prioritized")
  return args


class BeRealExporter:
  def __init__(self, args: argparse.Namespace):
    self.time_span = self.init_time_span(args)
    self.exiftool_path = args.exiftool_path
    self.out_path = args.out_path.strip().removesuffix('/')
    self.bereal_path = args.bereal_path.strip().removesuffix('/')
    self.verbose = args.verbose


  @staticmethod
  def init_time_span(args: argparse.Namespace) -> tuple:
    """
    Initializes time span based on the arguments.
    """
    if args.timespan:
        start_str, end_str = args.timespan.strip().split("-")
        start = dt.fromtimestamp(0) if start_str == '*' else dt.strptime(start_str, '%d.%m.%Y')
        end = dt.now() if end_str == '*' else dt.strptime(end_str, '%d.%m.%Y')
        return start, end
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
  def print_progress_bar(iteration: int, total: int, prefix: str = '', suffix: str = '', decimals: int = 1, length: int = 60, fill: str = '█', print_end: str = "\r"):
    """
    Call in a loop to create terminal progress bar.
    Not my creation: https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=print_end)
    if iteration == total:
        print()


  @staticmethod
  def get_img_filename(image: dict) -> str:
    """
    Returns the image filename from an image object (frontImage, backImage, primary, secondary).
    """
    return image['path'].split("/")[-1]


  @staticmethod
  def get_datetime_from_str(time: str) -> dt:
    """
    Returns a datetime object from a time key.
    """
    format_string = "%Y-%m-%dT%H:%M:%S.%fZ"
    return dt.strptime(time, format_string)


  def export_img(self, old_img_name: str, img_name: str, img_dt: dt, img_location=None):
    """
    Makes a copy of the image and adds EXIF tags to the image.
    """
    self.verbose_msg(f"Export {old_img_name} image to {img_name}")

    if os.path.isfile(old_img_name):
      cp(old_img_name, img_name)
      tags = {"DateTimeOriginal": img_dt.strftime("%Y:%m:%d %H:%M:%S")}
      if img_location:
          self.verbose_msg(f"Add metadata to image:\n - DateTimeOriginal={img_dt}\n - GPS=({img_location['latitude']}, {img_location['longitude']})")
          tags.update({
              "GPSLatitude*": img_location['latitude'],
              "GPSLongitude*": img_location['longitude']
          })
      else:
          self.verbose_msg(f"Add metadata to image:\n - DateTimeOriginal={img_dt}")
 
      if self.exiftool_path:
        et(executable=self.exiftool_path).set_tags(img_name, tags=tags, params=["-P", "-overwrite_original"])
      else:
        et().set_tags(img_name, tags=tags, params=["-P", "-overwrite_original"])
    else:
      self.verbose_msg(f"File {old_img_name} not found. Skipping this image.")


  def export_memories(self, memories: list):
    """
    Exports all memories from the Photos/post directory to the corresponding output folder.
    """
    out_path_memories = os.path.join(self.out_path, "memories")
    memory_count = len(memories)
    if not os.path.exists(out_path_memories):
        self.verbose_msg(f"Create {out_path_memories} folder for memories output")
        os.makedirs(out_path_memories)

    for i, memory in enumerate(memories):
      memory_dt = self.get_datetime_from_str(memory['takenTime'])
      types = [('frontImage', 'webp'), ('backImage', 'webp')]
      if 'btsMedia' in memory:
          types.append(('btsMedia', 'mp4'))
      img_names = [f"{out_path_memories}/{memory_dt.strftime('%Y-%m-%d_%H-%M-%S')}_{t[0].removesuffix('Image').removesuffix('Media')}.{t[1]}"
                   for t in types]

      if self.time_span[0] <= memory_dt <= self.time_span[1]:
        for img_name, type in zip(img_names, types):
          old_img_name = os.path.join(self.bereal_path, f"Photos/post/{self.get_img_filename(memory[type[0]])}")
          self.verbose_msg(f"Export Memory nr {i} {type[0]}:")
          if 'location' in memory:
            self.export_img(old_img_name, img_name, memory_dt, memory['location'])
          else:
            self.export_img(old_img_name, img_name, memory_dt)

      self.print_progress_bar(i + 1, memory_count, prefix="Exporting Memories", suffix=f"- {memory_dt.strftime('%Y-%m-%d')}")
      self.verbose_msg(f"\n\n{'#'*100}\n")


  def export_realmojis(self, realmojis: list):
    """
    Exports all realmojis from the Photos/realmoji directory to the corresponding output folder.
    """
    realmoji_count = len(realmojis)
    out_path_realmojis = os.path.join(self.out_path, "realmojis")
    if not os.path.exists(out_path_realmojis):
      self.verbose_msg(f"Create {out_path_realmojis} folder for memories output")
      os.makedirs(out_path_realmojis)

    for i, realmoji in enumerate(realmojis):
      realmoji_dt = self.get_datetime_from_str(realmoji['postedAt'])
      img_name = f"{out_path_realmojis}/{realmoji_dt.strftime('%Y-%m-%d_%H-%M-%S')}.webp"
      if self.time_span[0] <= realmoji_dt <= self.time_span[1] and realmoji['isInstant']:
        self.verbose_msg(f"Export Realmoji nr {i}:")
        self.export_img(os.path.join(self.bereal_path, f"Photos/realmoji/{self.get_img_filename(realmoji['media'])}"), img_name, realmoji_dt)
      self.print_progress_bar(i + 1, realmoji_count, prefix="Exporting Realmojis", suffix=f"- {realmoji_dt.strftime('%Y-%m-%d')}")
      self.verbose_msg(f"\n\n{'#'*100}\n")


if __name__ == '__main__':
  args = init_parser()
  exporter = BeRealExporter(args)

  if args.memories:
    exporter.verbose_msg("Open memories.json file")
    try:
      with open(os.path.join(exporter.bereal_path, 'memories.json'), encoding='utf-8') as memories_file:
        exporter.verbose_msg("Start exporting memories")
        exporter.export_memories(json.load(memories_file))
    except FileNotFoundError:
      print("memories.json file not found.")
    except json.JSONDecodeError:
      print("Error decoding memories.json file.")

  if args.realmojis:
    exporter.verbose_msg("Open realmojis.json file")
    try:
      with open(os.path.join(exporter.bereal_path, 'realmojis.json'), encoding='utf-8') as realmojis_file:
        exporter.verbose_msg("Start exporting realmojis")
        exporter.export_realmojis(json.load(realmojis_file))
    except FileNotFoundError:
      print("realmojis.json file not found.")
    except json.JSONDecodeError:
      print("Error decoding realmojis.json file.")
