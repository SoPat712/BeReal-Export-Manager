import json
from exiftool import ExifToolHelper as et
from shutil import copy2 as cp
import datetime
from datetime import datetime as dt
import argparse


def init_parser():
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('-t', '--timespan', type=str, help="Exports the given timespan\n"\
                                                         "Valid format: 'DD.MM.YYYY-DD.MM.YYYY'\n"\
                                                         "Wildcards can be used: 'DD.MM.YYYY-*'")
  parser.add_argument('-y', '--year', type=int, help="Exports the given year")

  args = parser.parse_args()
  if args.year and args.timespan:
    print("Timespan will be prioritized")

  return args


def init_global_var(args: argparse.Namespace):
  global time_span

  if args.timespan:
    temp_times = args.timespan.strip().split("-")
    time_span = ('*' if temp_times[0] == '*' else dt.strptime(temp_times[0], '%d.%m.%Y'),
                 '*' if temp_times[1] == '*' else dt.strptime(temp_times[1], '%d.%m.%Y'))
  elif args.year:
    time_span = (dt(args.year, 1, 1), dt(args.year, 12, 31))



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


def apply_memory_on_imgs(memory: json):
  """
  Makes a copy of the front and back images and adds information from the memory object as exif tags to the image
  """
  memory_dt = get_datetime_from_str(memory['takenTime'])
  img_names = ["./out/%s_%s.webp" % (memory_dt.strftime('%Y-%m-%d_%H-%M-%S'), temp_times) for temp_times in ['front', 'back']]

  cp("./Photos/post/%s" % get_img_filename(memory['frontImage']), img_names[0])
  cp("./Photos/post/%s" % get_img_filename(memory['backImage']), img_names[1])

  if 'location' in memory:
    et().set_tags(img_names,
                  tags={"DateTimeOriginal": memory_dt.strftime("%Y:%m:%d %H:%M:%S"),
                        "GPSLatitude*": memory['location']['latitude'],
                        "GPSLongitude*": memory['location']['longitude']},
                  params=["-P", "-overwrite_original"])
  else:
    et().set_tags(img_names,
                  tags={"DateTimeOriginal": memory_dt.strftime("%Y:%m:%d %H:%M:%S")},
                  params=["-P", "-overwrite_original"])


def export_images(memories: json):


  for temp_times in memories:
    apply_memory_on_imgs(temp_times)



if __name__ == '__main__':
  args = init_parser()
  init_global_var(args)

  f = open('memories.json')
  
  # export_images(json.load(f))

  f.close()
