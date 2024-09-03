import json
import exiftool

def get_img_filename(image: json):
  return image['path'].split("/")[-1]

def get_memory_location(memory: json):
  return memory['location'] if 'location' in memory else 'N/A'

def print_memories_info(data: json):
  n = 0
  for i in data:
    print("\nBeReal Nr. %s: " % n)
    print(" - Time Taken: %s\n - Front Image: %s\n - Back Image: %s\n - Location: %s"
           % (i['takenTime'],
           get_img_filename(i['frontImage']), get_img_filename(i['backImage']),
           get_memory_location(i)))
    n+=1
  

if __name__ == '__main__':
  f = open('memories.json')
  print_memories_info(json.load(f))
  f.close()
