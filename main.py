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
  parser.add_argument('-v', '--verbose', action=argparse.BooleanOptionalAction, help="Explain what is being done")

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


def printProgressBar (iteration: int, total: int, prefix: str='', suffix: str='', decimals: str=1, length: int=100, fill: str='█', printEnd: str="\r"):
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


def export_memory(memory: json, memory_dt: datetime):
  """
  Makes a copy of the front and back images and adds information from the memory object as exif tags to the image
  """
  # The new image file names
  img_names = ["%s/%s_%s.webp" % (out_path, memory_dt.strftime('%Y-%m-%d_%H-%M-%S'), temp_times)
               for temp_times in ['front', 'back']]

  # Makes a copy of the images
  for img_type, img_name in zip(['frontImage', 'backImage'], img_names):
    img_filename = get_img_filename(memory[img_type])
    verbose_msg("Export %s image to %s" % (img_filename, img_name))
    cp("./Photos/post/%s" % img_filename, img_name)

  # Add metadata to the images with or without location
  if 'location' in memory:
    verbose_msg("Add metadata to image:\n - DateTimeOriginal=%s\n - GPS=(%s, %s)" % (memory_dt, memory['location']['latitude'], memory['location']['longitude']))
    et().set_tags(img_names,
                  tags={"DateTimeOriginal": memory_dt.strftime("%Y:%m:%d %H:%M:%S"),
                        "GPSLatitude*": memory['location']['latitude'],
                        "GPSLongitude*": memory['location']['longitude']},
                  params=["-P", "-overwrite_original"])
  else:
    verbose_msg("Add metadata to image:\n - DateTimeOriginal=%s" % memory_dt)
    et().set_tags(img_names,
                  tags={"DateTimeOriginal": memory_dt.strftime("%Y:%m:%d %H:%M:%S")},
                  params=["-P", "-overwrite_original"])


def export_memories(memories: json):
  """
  Exports all memories from the Photos/post directory to the corresponding output folder
  """
  memory_count = len(memories)

  for i, n in zip(memories, range(memory_count)):
    memory_dt = get_datetime_from_str(i['takenTime'])

    # Checks if the memory is in the time span
    if time_span[0] <= memory_dt <= time_span[1]:
      verbose_msg("\nExport Memory nr %s:" % n)
      export_memory(i, memory_dt)

    if verbose:
      printProgressBar(n+1, memory_count, prefix="Exporting Images", suffix=("- Current Date: %s" % memory_dt.strftime("%Y-%m-%d")), printEnd='\n')
    else:
      printProgressBar(n+1, memory_count, prefix="Exporting Images")


def export_realmojis(realmojis: json):
  """
  Exports all realmojis from the Photos/realmoji directory to the corresponding output folder
  """
  realmoji_count = len(realmojis)

  for i, n in zip(realmojis, realmoji_count):
    realmoji_dt = get_datetime_from_str(i['postedAt'])

    # Checks if the memory is in the time span
    if time_span[0] <= realmoji_dt <= time_span[1]:
      verbose_msg("\nExport Memory nr %s:" % n)
      # export_memory(i, realmoji_dt)

    if verbose:
      printProgressBar(n+1, realmoji_dt, prefix="Exporting Images", suffix=("- Current Date: %s" % realmoji_dt.strftime("%Y-%m-%d")), printEnd='\n')
    else:
      printProgressBar(n+1, realmoji_dt, prefix="Exporting Images")


if __name__ == '__main__':
  args = init_parser()
  init_global_var(args)

  if not os.path.exists(out_path):
    verbose_msg("Create %s folder for output" % out_path)
    os.makedirs(out_path)

  verbose_msg("Open memories.json file")
  f = open('memories.json')
  
  
  verbose_msg("Start exporting images")
  export_memories(json.load(f))

  f.close()
