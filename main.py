import json
import exiftool

def get_img_filename(image: json):
  return image['path'].split("/")[-1]

def get_memory_location(memory: json):
  return memory['location'] if 'location' in memory else 'N/A'

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
  

if __name__ == '__main__':
  f = open('memories.json')
  n = 0
  for i in json.load(f):
    print("\nBeReal Nr. %s: " % n)
    print_memory_info(i)
    n+=1
    
  f.close()
