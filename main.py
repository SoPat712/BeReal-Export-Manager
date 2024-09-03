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


def print_memory_info(memory: json):
  """
  Takes a memory object from the ``memories.json`` file and prints out all necessarily information like:
   - names from the images
   - the taken time
   - the location if available
  """
  print(" - BeReal Moment: %s\n - Time Taken: %s\n - Front Image: %s\n - Back Image: %s\n - Location: %s\n - isLate: %s"
         % (memory['berealMoment'],
            memory['takenTime'],
            get_img_filename(memory['frontImage']), get_img_filename(memory['backImage']),
            get_memory_location(memory),
            memory['isLate']))
  

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
  
  apply_memory_on_imgs(json.load(f)[0])

  # et().set_tags("2024-09-01_12-54-39_front.jpg", tags={"File:FileCreateDate": dt.strftime(dt.now(), "%Y:%m:%d %H:%M:%S")}, params=["-P", "-overwrite_original"])
  # n = 0
  # for i in json.load(f):
  #   print("\nBeReal Nr. %s: " % n)
  #   print_memory_info(i)
  #   n+=1

  # for d in et().get_metadata("./Photos/post/ZB_-vUE7j2JePeEN.webp"):
  #   for k, v in d.items():
  #     print(f"{k} = {v}")
  

  f.close()
