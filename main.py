import json


def print_memories_info(data):
  n = 0
  for i in data:
    print("\nBeReal Nr. %s: " % n)
    f_image = i['frontImage']
    b_image = i['backImage']
    print(" - Time Taken: %s\n - Front Image: %s\n - Back Image: %s\n - Location: %s"
           % (i['takenTime'],
           f_image['path'].split("/")[-1], b_image['path'].split("/")[-1],
           i['location'] if 'location' in i else 'N/A'))
    n+=1
  

if __name__ == '__main__':
  f = open('memories.json')
  print_memories_info(json.load(f))
  f.close()
