import json
import os
from exiftool import ExifToolHelper as et
from shutil import copy2 as cp
import datetime
from datetime import datetime as dt
import argparse


def init_parser():
  """
  Initializes the argparse module
  """
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('-t', '--timespan', type=str, help="Exports the given timespan\n"\
                                                         "Valid format: 'DD.MM.YYYY-DD.MM.YYYY'\n"\
                                                         "Wildcards can be used: 'DD.MM.YYYY-*'")
  parser.add_argument('-y', '--year', type=int, help="Exports the given year")
  parser.add_argument('-p', '--path', type=str, help="Set a custom output path (default ./out)")
  parser.add_argument('-v', '--verbose', action='store_true', default=False, help="Explain what is being done")
  parser.add_argument('--no-memories', action='store_false', default=True, dest='memories', help="Don't export the memories")
  parser.add_argument('--no-realmojis', action='store_false', default=True, dest='realmojis', help="Don't export the realmojis")

  args = parser.parse_args()
  if args.year and args.timespan:
    print("Timespan argument will be prioritized")

  return args


def init_global_var(args: argparse.Namespace):
  """
  Initializes global variables
  """
  global time_span
  global out_path
  global verbose

  # Initialize time_span
  if args.timespan:
    temp_times = args.timespan.strip().split("-")
    time_span = (dt.fromtimestamp(0) if temp_times[0] == '*' else dt.strptime(temp_times[0], '%d.%m.%Y'),
                 dt.now() if temp_times[1] == '*' else dt.strptime(temp_times[1], '%d.%m.%Y'))
  elif args.year:
    time_span = (dt(args.year, 1, 1), dt(args.year, 12, 31))
  else:
    time_span = (dt.fromtimestamp(0), dt.now())
  
  # Initialize out_path
  if args.path:
    out_path = args.path.strip().removesuffix('/')
  else:
    out_path = "./out"

  verbose = args.verbose


def verbose_msg(msg: str):
  """
  Prints an explanation what is being done to the terminal
  """
  if verbose: print(msg)


def printProgressBar (iteration: int, total: int, prefix: str='', suffix: str='', decimals: str=1, length: int=60, fill: str='█', printEnd: str="\r"):
    """
    Call in a loop to create terminal progress bar
    Not my creation: https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end = printEnd)
    # Print New Line on Complete
    if iteration == total: 
        print()


def get_img_filename(image: json):
  """
  Returns the image filename from a image object (frontImage, backImage, primary, secondary)
  """
  return image['path'].split("/")[-1]


def get_datetime_from_str(time: str):
  """
  Returns a datetime object form a time key
  """
  format_string = "%Y-%m-%dT%H:%M:%S.%fZ"
  return dt.strptime(time, format_string)


def export_img(old_img_name: str, img_name: str, img_dt: datetime, img_location=None):
  """
  Makes a copy of the image and adds exif tags to the image
  """

  # Makes a copy of the images
  verbose_msg("Export %s image to %s" % (old_img_name, img_name))
  cp(old_img_name, img_name)

  # Add metadata to the images with or without location
  if img_location:
    verbose_msg("Add metadata to image:\n - DateTimeOriginal=%s\n - GPS=(%s, %s)" % (img_dt, img_location['latitude'], img_location['longitude']))
    et().set_tags(img_name,
                  tags={"DateTimeOriginal": img_dt.strftime("%Y:%m:%d %H:%M:%S"),
                        "GPSLatitude*": img_location['latitude'],
                        "GPSLongitude*": img_location['longitude']},
                  params=["-P", "-overwrite_original"])
  else:
    verbose_msg("Add metadata to image:\n - DateTimeOriginal=%s" % img_dt)
    et().set_tags(img_name,
                  tags={"DateTimeOriginal": img_dt.strftime("%Y:%m:%d %H:%M:%S")},
                  params=["-P", "-overwrite_original"])


def export_memories(memories: json):
  """
  Exports all memories from the Photos/post directory to the corresponding output folder
  """
  out_path_memories = out_path + "/memories"
  memory_count = len(memories)

  if not os.path.exists(out_path_memories):
    verbose_msg("Create %s folder for memories output" % out_path_memories)
    os.makedirs(out_path_memories)

  for i, n in zip(memories, range(memory_count)):
    memory_dt = get_datetime_from_str(i['takenTime'])
    types = ['front', 'back']
    img_names = ["%s/%s_%s.webp" % (out_path_memories, memory_dt.strftime('%Y-%m-%d_%H-%M-%S'), type)
                 for type in types]

    # Checks if the memory is in the time span
    if time_span[0] <= memory_dt <= time_span[1]:
      for img_name, type in zip(img_names, types):
        old_img_name = "./Photos/post/" + get_img_filename(i[type+'Image'])

        verbose_msg("\nExport Memory nr %s %s:" % (n, type))
        if 'location' in i:
          export_img(old_img_name, img_name, memory_dt, i['location'])
        else:
          export_img(old_img_name, img_name, memory_dt)

    if verbose:
      printProgressBar(n+1, memory_count, prefix="Exporting Memories", suffix=("- " + memory_dt.strftime("%Y-%m-%d")), printEnd='\n')
    else:
      printProgressBar(n+1, memory_count, prefix="Exporting Memories", suffix=("- " + memory_dt.strftime("%Y-%m-%d")))


def export_realmojis(realmojis: json):
  """
  Exports all realmojis from the Photos/realmoji directory to the corresponding output folder
  """
  realmoji_count = len(realmojis)
  out_path_realmojis = out_path + "/realmojis"

  if not os.path.exists(out_path_realmojis):
    verbose_msg("Create %s folder for memories output" % out_path_realmojis)
    os.makedirs(out_path_realmojis)

  for i, n in zip(realmojis, range(realmoji_count)):
    realmoji_dt = get_datetime_from_str(i['postedAt'])
    img_name = "%s/%s.webp" % (out_path_realmojis, realmoji_dt.strftime('%Y-%m-%d_%H-%M-%S'))

    # Checks if the realmojis is in the time span
    if time_span[0] <= realmoji_dt <= time_span[1] and i['isInstant']:
      verbose_msg("\nExport Memory nr %s:" % n)
      export_img("./Photos/realmoji/" + get_img_filename(i['media']), img_name, realmoji_dt)

    if verbose:
      printProgressBar(n+1, realmoji_count, prefix="Exporting Realmojis", suffix=("- Current Date: %s" % realmoji_dt.strftime("%Y-%m-%d")), printEnd='\n')
    else:
      printProgressBar(n+1, realmoji_count, prefix="Exporting Realmojis", suffix=("- Current Date: %s" % realmoji_dt.strftime("%Y-%m-%d")))


if __name__ == '__main__':
  args = init_parser()
  init_global_var(args)

  if args.memories:
    verbose_msg("Open memories.json file")
    with open('memories.json', encoding='utf-8') as memories:
      verbose_msg("Start exporting memories")
      export_memories(json.load(memories))

  if args.realmojis:
    verbose_msg("Open realmojis.json file")
    with open('realmojis.json', encoding='utf-8') as realmojis:
      verbose_msg("Start exporting realmojis")
      export_realmojis(json.load(realmojis))