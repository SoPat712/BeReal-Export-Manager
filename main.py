import json
from exiftool import ExifToolHelper as et
from shutil import copy2 as cp
from datetime import datetime as dt

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
  img_names = ["./out/%s_%s.webp" % (memory_dt.strftime('%Y-%m-%d_%H-%M-%S'), i) for i in ['front', 'back']]

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


if __name__ == '__main__':
  f = open('memories.json')
  
  for i in json.load(f):
    apply_memory_on_imgs(i)

  f.close()
