import argparse
import json
import os
import glob
from datetime import datetime as dt
from shutil import copy2 as cp
from PIL import Image, ImageDraw
import pytz
from timezonefinder import TimezoneFinder
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging

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
        default="./output",
        help="Set a custom output path (default ./output)",
    )
    parser.add_argument(
        "--input-path",
        dest="input_path",
        type=str,
        default="./input",
        help="Set the input folder path containing BeReal export (default ./input)",
    )
    parser.add_argument(
        "--max-workers",
        dest="max_workers",
        type=int,
        default=4,
        help="Maximum number of parallel workers (default 4)",
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
    parser.add_argument(
        "--no-posts",
        dest="posts",
        default=True,
        action="store_false",
        help="Don't export the posts",
    )
    parser.add_argument(
        "--no-conversations",
        dest="conversations",
        default=True,
        action="store_false",
        help="Don't export the conversations",
    )
    parser.add_argument(
        "--conversations-only",
        dest="conversations_only",
        default=False,
        action="store_true",
        help="Export only conversations (for debugging)",
    )
    parser.add_argument(
        "--interactive-conversations",
        dest="interactive_conversations",
        default=False,
        action="store_true",
        help="Manually choose front/back camera for conversation images",
    )
    parser.add_argument(
        "--web-ui",
        dest="web_ui",
        default=False,
        action="store_true",
        help="Use web UI for interactive conversation selection",
    )

    args = parser.parse_args()
    if args.year and args.timespan:
        print("Timespan argument will be prioritized")
    
    # Handle conversations-only flag
    if args.conversations_only:
        args.memories = False
        args.posts = False
        args.realmojis = False
        args.conversations = True
        print("Running in conversations-only mode for debugging")
    
    return args


class BeRealExporter:
    def __init__(self, args: argparse.Namespace):
        self.time_span = self.init_time_span(args)
        self.exiftool_path = args.exiftool_path
        self.out_path = args.out_path.rstrip("/")
        self.input_path = args.input_path.rstrip("/")
        self.verbose = args.verbose
        self.max_workers = args.max_workers
        self.interactive_conversations = args.interactive_conversations
        self.web_ui = args.web_ui
        
        # Setup logging for clean progress bars
        if self.verbose:
            logging.basicConfig(level=logging.INFO, format='%(message)s')
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None
        
        # Find the BeReal export folder inside input
        self.bereal_path = self.find_bereal_export_folder()

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

    def find_bereal_export_folder(self) -> str:
        """
        Finds the BeReal export folder inside the input directory.
        """
        if not os.path.exists(self.input_path):
            raise FileNotFoundError(f"Input path not found: {self.input_path}")
        
        # Look for folders that contain the expected structure
        for item in os.listdir(self.input_path):
            item_path = os.path.join(self.input_path, item)
            if os.path.isdir(item_path):
                # Check if this folder contains the expected JSON files
                if (os.path.exists(os.path.join(item_path, "memories.json")) or 
                    os.path.exists(os.path.join(item_path, "posts.json"))):
                    return item_path
        
        raise FileNotFoundError("No BeReal export folder found in input directory")

    def verbose_msg(self, msg: str):
        """
        Prints an explanation of what is being done to the terminal.
        Uses logging to work nicely with progress bars.
        """
        if self.verbose and self.logger:
            self.logger.info(msg)

    def convert_to_local_time(self, utc_dt: dt, location=None) -> dt:
        """
        Converts UTC datetime to local timezone based on location or defaults to America/New_York.
        """
        # Ensure the datetime is timezone-aware (UTC)
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        elif utc_dt.tzinfo != pytz.UTC:
            utc_dt = utc_dt.astimezone(pytz.UTC)
        
        # Default timezone
        local_tz = pytz.timezone('America/New_York')
        
        # Try to get timezone from location if available
        if location and "latitude" in location and "longitude" in location:
            try:
                tf = TimezoneFinder()
                timezone_str = tf.timezone_at(
                    lat=location["latitude"], 
                    lng=location["longitude"]
                )
                if timezone_str:
                    local_tz = pytz.timezone(timezone_str)
                    self.verbose_msg(f"Using timezone {timezone_str} from GPS location")
                else:
                    self.verbose_msg("GPS location found but timezone lookup failed, using America/New_York")
            except Exception as e:
                self.verbose_msg(f"Error determining timezone from GPS: {e}, using America/New_York")
        else:
            self.verbose_msg("No GPS location, using America/New_York timezone")
        
        # Convert to local time and return naive datetime for EXIF
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.replace(tzinfo=None)

    def process_memory(self, memory, out_path_memories):
        """
        Processes a single memory (for parallel execution).
        Saves to posts folder and skips if files already exist to avoid duplicates.
        """
        memory_dt = self.get_datetime_from_str(memory["takenTime"])
        if not (self.time_span[0] <= memory_dt <= self.time_span[1]):
            return None

        # Get front and back image paths
        front_path = os.path.join(self.bereal_path, memory["frontImage"]["path"])
        back_path = os.path.join(self.bereal_path, memory["backImage"]["path"])
        
        # Convert to local time for filename (to match EXIF metadata)
        img_location = memory.get("location", None)
        local_dt = self.convert_to_local_time(memory_dt, img_location)
        
        # Create output filenames with descriptive names
        base_filename = f"{local_dt.strftime('%Y-%m-%d_%H-%M-%S')}"
        secondary_output = f"{out_path_memories}/{base_filename}_selfie-view.webp"  # front camera
        primary_output = f"{out_path_memories}/{base_filename}_main-view.webp"     # back camera
        composite_output = f"{out_path_memories}/{base_filename}_composited.webp"
        
        # Skip if files already exist (avoid duplicates from posts)
        if os.path.exists(primary_output) and os.path.exists(secondary_output) and os.path.exists(composite_output):
            self.verbose_msg(f"Skipping {base_filename} - already exists from posts export")
            return f"{base_filename} (skipped - duplicate)"
        
        # Export individual images (front=secondary, back=primary)
        if not os.path.exists(secondary_output):
            self.export_img(front_path, secondary_output, memory_dt, img_location)
        if not os.path.exists(primary_output):
            self.export_img(back_path, primary_output, memory_dt, img_location)
        
        # Create composite image (back/primary as background, front/secondary as overlay - BeReal style)
        if not os.path.exists(composite_output) and os.path.exists(secondary_output) and os.path.exists(primary_output):
            self.create_composite_image(primary_output, secondary_output, composite_output, memory_dt, img_location)

        return base_filename

    def process_post(self, post, out_path_posts):
        """
        Processes a single post (for parallel execution).
        """
        post_dt = self.get_datetime_from_str(post["takenAt"])
        if not (self.time_span[0] <= post_dt <= self.time_span[1]):
            return None

        # Get primary and secondary image paths
        primary_path = os.path.join(self.bereal_path, post["primary"]["path"])
        secondary_path = os.path.join(self.bereal_path, post["secondary"]["path"])
        
        # Convert to local time for filename (to match EXIF metadata)
        post_location = post.get("location", None)
        local_dt = self.convert_to_local_time(post_dt, post_location)
        
        # Create output filename
        base_filename = f"{local_dt.strftime('%Y-%m-%d_%H-%M-%S')}"
        
        # Export individual images
        primary_output = f"{out_path_posts}/{base_filename}_main-view.webp"
        secondary_output = f"{out_path_posts}/{base_filename}_selfie-view.webp"
        composite_output = f"{out_path_posts}/{base_filename}_composited.webp"
        

        
        # Export primary image
        self.export_img(primary_path, primary_output, post_dt, post_location)
        
        # Export secondary image  
        self.export_img(secondary_path, secondary_output, post_dt, post_location)
        
        # Create composite image
        if os.path.exists(primary_output) and os.path.exists(secondary_output):
            self.create_composite_image(primary_output, secondary_output, composite_output, post_dt, post_location)

        return base_filename

    def interactive_choose_primary_overlay(self, original_files, exported_files, conversation_id, file_id, progress_info=None):
        """
        Interactive mode to let user choose which image is main view vs selfie view.
        Opens images in system viewer for preview.
        """
        if len(exported_files) != 2:
            return exported_files[0], exported_files[1] if len(exported_files) > 1 else exported_files[0]
        
        print(f"\n--- Conversation {conversation_id}, Message ID {file_id} ---")
        if progress_info:
            print(f"Progress: {progress_info}")
        
        # Show image info
        try:
            from PIL import Image
            img1 = Image.open(exported_files[0])
            img2 = Image.open(exported_files[1])
            print(f"Image 1: {os.path.basename(exported_files[0])} ({img1.width}x{img1.height}, {img1.width/img1.height:.2f} ratio)")
            print(f"Image 2: {os.path.basename(exported_files[1])} ({img2.width}x{img2.height}, {img2.width/img2.height:.2f} ratio)")
            img1.close()
            img2.close()
        except Exception:
            print(f"Image 1: {os.path.basename(exported_files[0])}")
            print(f"Image 2: {os.path.basename(exported_files[1])}")
        
        # Open images in system viewer
        print("\nOpening images in system viewer...")
        try:
            import subprocess
            import platform
            
            system = platform.system()
            for i, img_path in enumerate(exported_files, 1):
                print(f"Opening Image {i}...")
                if system == "Darwin":  # macOS
                    subprocess.run(["open", img_path], check=False)
                elif system == "Windows":
                    subprocess.run(["start", img_path], shell=True, check=False)
                else:  # Linux
                    subprocess.run(["xdg-open", img_path], check=False)
                
                # Small delay between opening images
                import time
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Could not open images automatically: {e}")
            print("Please manually open the images to view them.")
        
        print("\nWhich image should be the SELFIE VIEW (front camera/overlay)?")
        print("1. Image 1")
        print("2. Image 2") 
        print("3. Skip composite creation")
        
        while True:
            try:
                choice = input("Enter choice (1, 2, or 3): ").strip()
                if choice == "1":
                    return exported_files[1], exported_files[0]  # img2 main, img1 selfie
                elif choice == "2":
                    return exported_files[0], exported_files[1]  # img1 main, img2 selfie
                elif choice == "3":
                    return None, None  # Skip composite
                else:
                    print("Please enter 1, 2, or 3")
            except (KeyboardInterrupt, EOFError):
                print("\nSkipping composite creation...")
                return None, None

    def web_ui_choose_primary_overlay(self, exported_files, conversation_id, file_id, progress_info=None):
        """
        Web UI mode to let user choose which image is selfie view.
        Creates a simple HTML page with side-by-side images.
        """
        if len(exported_files) != 2:
            return exported_files[0], exported_files[1] if len(exported_files) > 1 else exported_files[0]
        
        import tempfile
        import webbrowser
        import base64
        
        # Create temporary HTML file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            # Convert images to base64 for embedding
            img1_b64 = ""
            img2_b64 = ""
            try:
                with open(exported_files[0], 'rb') as img_file:
                    img1_b64 = base64.b64encode(img_file.read()).decode()
                with open(exported_files[1], 'rb') as img_file:
                    img2_b64 = base64.b64encode(img_file.read()).decode()
            except Exception as e:
                print(f"Error reading images: {e}")
                return self.interactive_choose_primary_overlay([], exported_files, conversation_id, file_id)
            
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>BeReal Conversation Selector</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .images {{ display: flex; gap: 20px; justify-content: center; margin-bottom: 30px; }}
        .image-container {{ text-align: center; cursor: pointer; border: 3px solid #ddd; border-radius: 10px; padding: 10px; transition: all 0.3s; }}
        .image-container:hover {{ border-color: #007bff; transform: scale(1.02); }}
        .image-container.selected {{ border-color: #28a745; background: #f8fff8; }}
        .image-container img {{ max-width: 400px; max-height: 400px; border-radius: 5px; }}
        .buttons {{ text-align: center; }}
        .btn {{ padding: 10px 20px; margin: 0 10px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }}
        .btn-primary {{ background: #007bff; color: white; }}
        .btn-success {{ background: #28a745; color: white; }}
        .btn-secondary {{ background: #6c757d; color: white; }}
        .btn:hover {{ opacity: 0.8; }}
        .instruction {{ text-align: center; margin-bottom: 20px; font-size: 18px; color: #333; }}
        .result {{ display: none; text-align: center; font-size: 20px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>BeReal Conversation Selector</h1>
            <p>Conversation: {conversation_id} | Message ID: {file_id}</p>
            <div id="progress-info" style="background: #e9ecef; padding: 10px; border-radius: 5px; margin: 10px 0;">
                <small>{progress_info if progress_info else 'Processing conversation images...'}</small>
            </div>
        </div>
        
        <div class="instruction">
            <strong>Click on the image that should be the SELFIE VIEW (front camera/overlay)</strong><br>
            <small>Or press: <kbd>1</kbd> for left image, <kbd>2</kbd> for right image, <kbd>S</kbd> to skip</small>
        </div>
        
        <div class="images">
            <div class="image-container" id="img1" onclick="selectImage(1)">
                <img src="data:image/webp;base64,{img1_b64}" alt="Image 1">
                <h3>Image 1</h3>
                <p>{os.path.basename(exported_files[0])}</p>
            </div>
            <div class="image-container" id="img2" onclick="selectImage(2)">
                <img src="data:image/webp;base64,{img2_b64}" alt="Image 2">
                <h3>Image 2</h3>
                <p>{os.path.basename(exported_files[1])}</p>
            </div>
        </div>
        
        <div class="buttons">
            <button class="btn btn-secondary" onclick="skip()">Skip Composite</button>
        </div>
        
        <div class="result" id="result"></div>
    </div>
    
    <script>
        let selectedImage = 0;
        
        function selectImage(num) {{
            // Immediately confirm selection
            document.getElementById('img1').classList.remove('selected');
            document.getElementById('img2').classList.remove('selected');
            document.getElementById('img' + num).classList.add('selected');
            
            // Write result to file immediately
            writeResult(num.toString());
            
            document.getElementById('result').innerHTML = 
                '<p style="color: green; font-size: 24px; font-weight: bold;">✓ Image ' + num + ' selected as SELFIE VIEW</p>' +
                '<p style="color: #666;">Processing... You can close this window.</p>';
            document.getElementById('result').style.display = 'block';
            
            // Hide the interface
            document.querySelector('.buttons').style.display = 'none';
            document.querySelector('.instruction').style.display = 'none';
            document.querySelector('.images').style.opacity = '0.5';
        }}
        
        function writeResult(value) {{
            // Use a simple approach - create a temporary anchor to trigger download
            const blob = new Blob([value], {{type: 'text/plain'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'bereal_selection.txt';
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }}
        
        // Add keyboard shortcuts
        document.addEventListener('keydown', function(e) {{
            if (e.key === '1') {{
                selectImage(1);
            }} else if (e.key === '2') {{
                selectImage(2);
            }} else if (e.key === 's' || e.key === 'S') {{
                skip();
            }}
        }});
        
        function skip() {{
            writeResult('skip');
            
            document.getElementById('result').innerHTML = 
                '<p style="color: orange; font-size: 24px; font-weight: bold;">⏭ Composite creation SKIPPED</p>' +
                '<p style="color: #666;">Processing... You can close this window.</p>';
            document.getElementById('result').style.display = 'block';
            
            // Hide the interface
            document.querySelector('.buttons').style.display = 'none';
            document.querySelector('.instruction').style.display = 'none';
            document.querySelector('.images').style.opacity = '0.5';
        }}
    </script>
</body>
</html>
            """
            
            f.write(html_content)
            html_path = f.name
        
        # Open in browser
        print(f"Opening web UI for conversation {conversation_id}, message {file_id}...")
        webbrowser.open('file://' + html_path)
        
        # Wait for user to make selection in browser
        print("Make your selection in the web browser (click image or press 1/2/S)...")
        
        import time
        selection = None
        timeout = 300  # 5 minutes timeout
        start_time = time.time()
        
        # Look for result file in Downloads folder or current directory
        possible_result_files = [
            os.path.expanduser("~/Downloads/bereal_selection.txt"),
            "bereal_selection.txt",
            os.path.expanduser("~/Downloads/bereal_selection*.txt")
        ]
        
        while selection is None and (time.time() - start_time) < timeout:
            try:
                # Check for result files
                for pattern in possible_result_files:
                    if '*' in pattern:
                        import glob
                        files = glob.glob(pattern)
                        if files:
                            result_file = max(files, key=os.path.getctime)  # Get newest
                        else:
                            continue
                    else:
                        result_file = pattern
                        if not os.path.exists(result_file):
                            continue
                    
                    # Read the result
                    try:
                        with open(result_file, 'r') as f:
                            result = f.read().strip()
                            if result == "1":
                                selection = 1
                            elif result == "2":
                                selection = 2
                            elif result == "skip":
                                selection = "skip"
                            
                            # Clean up the result file
                            os.unlink(result_file)
                            break
                    except Exception:
                        continue
                
                if selection is not None:
                    break
                    
                # Small delay to avoid busy waiting
                time.sleep(1)
                
            except (KeyboardInterrupt, EOFError):
                print("\nSkipping composite creation...")
                selection = "skip"
                break
        
        if selection is None:
            print("Timeout waiting for selection, skipping...")
            selection = "skip"
        
        # Clean up
        try:
            os.unlink(html_path)
        except:
            pass
        
        if selection == "skip":
            return None, None
        elif selection == 1:
            return exported_files[1], exported_files[0]  # img2 main, img1 selfie
        elif selection == 2:
            return exported_files[0], exported_files[1]  # img1 main, img2 selfie
        
        # Clean up
        try:
            os.unlink(html_path)
        except:
            pass

    def detect_primary_overlay_conversation(self, original_files, exported_files):
        """
        Tries to detect which image should be primary (back camera) vs overlay (front camera)
        for conversation images based on filename patterns and image properties.
        """
        if len(original_files) != 2 or len(exported_files) != 2:
            return exported_files[0], exported_files[1]
        
        # Get original filenames for pattern detection
        file1_name = os.path.basename(original_files[0]).lower()
        file2_name = os.path.basename(original_files[1]).lower()
        
        # Pattern 1: Look for "secondary" keyword (usually front camera)
        if "secondary" in file1_name and "secondary" not in file2_name:
            # file1 is secondary (front), file2 is primary (back)
            return exported_files[1], exported_files[0]
        elif "secondary" in file2_name and "secondary" not in file1_name:
            # file2 is secondary (front), file1 is primary (back)
            return exported_files[0], exported_files[1]
        
        # Pattern 2: Look for "front" vs "back" keywords
        if "front" in file1_name and "back" in file2_name:
            return exported_files[1], exported_files[0]  # back primary, front overlay
        elif "back" in file1_name and "front" in file2_name:
            return exported_files[0], exported_files[1]  # back primary, front overlay
        
        # Pattern 3: Check image dimensions (front camera often different aspect ratio)
        try:
            from PIL import Image
            img1 = Image.open(exported_files[0])
            img2 = Image.open(exported_files[1])
            
            # If one image is significantly smaller or different aspect ratio, it might be front camera
            ratio1 = img1.width / img1.height
            ratio2 = img2.width / img2.height
            
            # If aspect ratios are very different, assume the more square one is front camera
            if abs(ratio1 - ratio2) > 0.2:
                if abs(ratio1 - 1.0) < abs(ratio2 - 1.0):  # ratio1 is closer to square
                    return exported_files[1], exported_files[0]  # img2 primary, img1 overlay
                else:
                    return exported_files[0], exported_files[1]  # img1 primary, img2 overlay
            
            img1.close()
            img2.close()
        except Exception:
            pass
        
        # Pattern 4: Alphabetical order heuristic - often the first file alphabetically is the back camera
        if file1_name < file2_name:
            return exported_files[0], exported_files[1]  # first alphabetically as primary
        else:
            return exported_files[1], exported_files[0]  # second alphabetically as primary

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
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",  # With microseconds
            "%Y-%m-%dT%H:%M:%S.000Z",  # Without microseconds
            "%Y-%m-%dT%H:%M:%SZ"       # No milliseconds at all
        ]
        
        for format_string in formats:
            try:
                return dt.strptime(time, format_string)
            except ValueError:
                continue
        
        # Try parsing timestamp if it's a number
        try:
            timestamp = float(time)
            return dt.fromtimestamp(timestamp)
        except (ValueError, TypeError):
            pass
            
        raise ValueError(f"Invalid datetime format: {time}")

    def export_img(
        self, old_img_name: str, img_name: str, img_dt: dt, img_location=None
    ):
        self.verbose_msg(f"Exporting {old_img_name} to {img_name}")
        if img_location:
            self.verbose_msg(f"Location data available: {img_location['latitude']}, {img_location['longitude']}")
        else:
            self.verbose_msg(f"No location data for {img_name}")

        if not os.path.isfile(old_img_name):
            # Try different fallback locations
            fallback_locations = [
                # Direct path from bereal_path
                os.path.join(self.bereal_path, old_img_name.lstrip("/")),
                # Try with just the filename in different folders
                os.path.join(self.bereal_path, "Photos/post", os.path.basename(old_img_name)),
                os.path.join(self.bereal_path, "Photos/bereal", os.path.basename(old_img_name)),
                os.path.join(self.bereal_path, "Photos/realmoji", os.path.basename(old_img_name)),
                # Original fallback
                os.path.join(self.bereal_path, old_img_name)
            ]
            
            for fallback in fallback_locations:
                if os.path.isfile(fallback):
                    old_img_name = fallback
                    break
            else:
                print(f"File not found in expected locations: {old_img_name}")
                return

        os.makedirs(os.path.dirname(img_name), exist_ok=True)
        
        # Detect actual file format and adjust extension accordingly
        try:
            with Image.open(old_img_name) as img:
                actual_format = img.format.lower()
                self.verbose_msg(f"Detected format: {actual_format} for {old_img_name}")
                
                if actual_format == 'jpeg' and img_name.endswith('.webp'):
                    # Original is JPEG but we're naming it .webp - fix the extension
                    img_name = img_name.replace('.webp', '.jpg')
                    self.verbose_msg(f"Corrected extension to .jpg for JPEG file: {img_name}")
                elif actual_format == 'webp' and img_name.endswith('.jpg'):
                    # Original is WEBP but we're naming it .jpg - fix the extension  
                    img_name = img_name.replace('.jpg', '.webp')
                    self.verbose_msg(f"Corrected extension to .webp for WEBP file: {img_name}")
        except Exception as e:
            self.verbose_msg(f"Could not detect format for {old_img_name}: {e}, using original extension")
        
        cp(old_img_name, img_name)

        # Convert to local time based on location
        local_dt = self.convert_to_local_time(img_dt, img_location)
        
        # Use appropriate tags based on file format
        if img_name.endswith('.jpg') or img_name.endswith('.jpeg'):
            # JPEG supports full EXIF metadata
            tags = {
                "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
            }
            if img_location:
                self.verbose_msg(f"Adding GPS to JPEG {img_name}: {img_location['latitude']}, {img_location['longitude']}")
                tags.update({
                    "GPSLatitude": img_location["latitude"],
                    "GPSLongitude": img_location["longitude"],
                    "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                    "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                })
        else:
            # WEBP has limited EXIF support, use minimal essential tags
            tags = {
                "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
            }
            # Add GPS data if available (WEBP supports basic GPS)
            if img_location:
                self.verbose_msg(f"Adding GPS to WEBP {img_name}: {img_location['latitude']}, {img_location['longitude']}")
                tags.update({
                    "GPSLatitude": img_location["latitude"],
                    "GPSLongitude": img_location["longitude"],
                    "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                    "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                })

        try:
            with (
                et(executable=self.exiftool_path) if self.exiftool_path else et()
            ) as exif_tool:
                result = exif_tool.set_tags(
                    img_name, tags=tags, params=["-overwrite_original", "-m", "-q", "-overwrite_original_in_place"]
                )
                self.verbose_msg(f"ExifTool result: {result}")
            self.verbose_msg(f"Metadata added to {img_name} (local time: {local_dt.strftime('%Y-%m-%d %H:%M:%S')})")
        except Exception as e:
            # WEBP files often have limited EXIF support, try with fewer tags
            self.verbose_msg(f"Primary metadata write failed for {img_name}, trying fallback approach")
            try:
                # Try with just DateTimeOriginal which is more widely supported
                fallback_tags = {"DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S")}
                if img_location:
                    fallback_tags.update({
                        "GPSLatitude": img_location["latitude"],
                        "GPSLongitude": img_location["longitude"],
                        "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                        "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                    })
                
                with (
                    et(executable=self.exiftool_path) if self.exiftool_path else et()
                ) as exif_tool:
                    result = exif_tool.set_tags(
                        img_name, tags=fallback_tags, params=["-overwrite_original", "-m", "-q"]
                    )
                self.verbose_msg(f"Fallback metadata added to {img_name}")
            except Exception as e2:
                print(f"WEBP metadata failed for {img_name}, trying JPEG conversion...")
                # Convert to JPEG as final fallback for reliable EXIF
                try:
                    jpeg_name = img_name.replace('.webp', '.jpg')
                    with Image.open(img_name) as img:
                        # Convert to RGB if necessary (JPEG doesn't support transparency)
                        if img.mode in ('RGBA', 'LA', 'P'):
                            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                            img = rgb_img
                        img.save(jpeg_name, 'JPEG', quality=95, optimize=True)
                    
                    # Add EXIF to JPEG (should work reliably)
                    jpeg_tags = {
                        "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                        "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                        "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
                    }
                    if img_location:
                        jpeg_tags.update({
                            "GPSLatitude": img_location["latitude"],
                            "GPSLongitude": img_location["longitude"],
                            "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                            "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                        })
                    
                    with (
                        et(executable=self.exiftool_path) if self.exiftool_path else et()
                    ) as exif_tool:
                        exif_tool.set_tags(
                            jpeg_name, tags=jpeg_tags, params=["-overwrite_original"]
                        )
                    
                    # Remove the original WEBP file since JPEG worked
                    os.remove(img_name)
                    self.verbose_msg(f"Converted to JPEG with full EXIF: {jpeg_name}")
                    
                except Exception as e3:
                    print(f"JPEG conversion also failed for {img_name}: {e3}")
                    # Set file modification time as absolute last resort
                    try:
                        timestamp = local_dt.timestamp()
                        os.utime(img_name, (timestamp, timestamp))
                        self.verbose_msg(f"Set file modification time for {img_name}")
                    except Exception as e4:
                        print(f"Could not set any timestamp for {img_name}: {e4}")

    def create_rounded_mask(self, size, radius):
        """
        Creates a rounded rectangle mask for the given size and radius with anti-aliasing.
        """
        # Use supersampling for smoother edges (4x resolution)
        scale = 4
        large_size = (size[0] * scale, size[1] * scale)
        large_radius = radius * scale
        
        # Create mask at higher resolution
        mask = Image.new('L', large_size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, large_size[0], large_size[1]), radius=large_radius, fill=255)
        
        # Downsample with high-quality resampling for anti-aliasing
        mask = mask.resize(size, Image.Resampling.LANCZOS)
        return mask

    def create_composite_image(self, primary_path: str, secondary_path: str, output_path: str, img_dt: dt = None, img_location=None):
        """
        Creates a composite image with the secondary image overlaid on the primary image
        with padding from the top and left edges and rounded corners.
        Applies the same metadata as the source images.
        """
        try:
            # Open both images
            primary = Image.open(primary_path)
            secondary = Image.open(secondary_path)
            
            # Calculate secondary image size (about 1/4 of primary width)
            secondary_width = primary.width // 4
            secondary_height = int(secondary.height * (secondary_width / secondary.width))
            
            # Resize secondary image
            secondary_resized = secondary.resize((secondary_width, secondary_height), Image.Resampling.LANCZOS)
            
            # Create rounded corners for the secondary image
            corner_radius = min(secondary_width, secondary_height) // 10  # 10% of the smaller dimension
            border_width = 4
            
            # Create secondary image with border
            bordered_width = secondary_width + (border_width * 2)
            bordered_height = secondary_height + (border_width * 2)
            
            # Create a black background for the border
            bordered_image = Image.new('RGBA', (bordered_width, bordered_height), (0, 0, 0, 255))
            
            # Create a mask with rounded corners for the bordered image
            border_mask = self.create_rounded_mask((bordered_width, bordered_height), corner_radius + border_width)
            
            # Apply the border mask
            bordered_image.putalpha(border_mask)
            
            # Create a mask with rounded corners for the inner image
            inner_mask = self.create_rounded_mask((secondary_width, secondary_height), corner_radius)
            
            # Apply the mask to create rounded corners on the secondary image
            secondary_with_alpha = Image.new('RGBA', (secondary_width, secondary_height), (0, 0, 0, 0))
            secondary_rgba = secondary_resized.convert('RGBA')
            secondary_with_alpha.paste(secondary_rgba, (0, 0))
            secondary_with_alpha.putalpha(inner_mask)
            
            # Paste the secondary image onto the bordered background
            bordered_image.paste(secondary_with_alpha, (border_width, border_width), secondary_with_alpha)
            
            # Create a copy of the primary image and convert to RGBA for proper alpha blending
            composite = primary.convert('RGBA')
            
            # Add padding (20 pixels from top and left)
            padding = 20
            
            # Paste the bordered secondary image onto the primary with padding
            composite.paste(bordered_image, (padding, padding), bordered_image)
            
            # Convert back to RGB for saving as WEBP
            final_composite = Image.new('RGB', composite.size, (255, 255, 255))
            final_composite.paste(composite, mask=composite.split()[-1] if composite.mode == 'RGBA' else None)
            
            # Save the composite image
            final_composite.save(output_path, "WEBP", quality=95)
            
            # Apply metadata to composite if datetime is provided
            if img_dt:
                # Convert to local time based on location
                local_dt = self.convert_to_local_time(img_dt, img_location)
                
                tags = {
                    "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                    "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                    "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
                }
                
                if img_location:
                    tags.update(
                        {
                            "GPSLatitude": img_location["latitude"],
                            "GPSLongitude": img_location["longitude"],
                            "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                            "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                        }
                    )

                try:
                    with (
                        et(executable=self.exiftool_path) if self.exiftool_path else et()
                    ) as exif_tool:
                        exif_tool.set_tags(
                            output_path, tags=tags, params=["-P", "-overwrite_original", "-m"]
                        )
                    self.verbose_msg(f"Metadata added to composite: {output_path}")
                except Exception as e:
                    # Try fallback approach for composite
                    try:
                        fallback_tags = {"DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S")}
                        if img_location:
                            fallback_tags.update({
                                "GPSLatitude": img_location["latitude"],
                                "GPSLongitude": img_location["longitude"],
                            })
                        
                        with (
                            et(executable=self.exiftool_path) if self.exiftool_path else et()
                        ) as exif_tool:
                            exif_tool.set_tags(
                                output_path, tags=fallback_tags, params=["-overwrite_original", "-m", "-q"]
                            )
                        self.verbose_msg(f"Fallback metadata added to composite: {output_path}")
                    except Exception as e2:
                        print(f"WEBP metadata failed for composite {output_path}, trying JPEG conversion...")
                        # Convert composite to JPEG as fallback
                        try:
                            jpeg_path = output_path.replace('.webp', '.jpg')
                            with Image.open(output_path) as img:
                                if img.mode in ('RGBA', 'LA', 'P'):
                                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                                    if img.mode == 'P':
                                        img = img.convert('RGBA')
                                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                                    img = rgb_img
                                img.save(jpeg_path, 'JPEG', quality=95, optimize=True)
                            
                            # Add full EXIF to JPEG
                            jpeg_tags = {
                                "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                                "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                                "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
                            }
                            if img_location:
                                jpeg_tags.update({
                                    "GPSLatitude": img_location["latitude"],
                                    "GPSLongitude": img_location["longitude"],
                                    "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                                    "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                                })
                            
                            with (
                                et(executable=self.exiftool_path) if self.exiftool_path else et()
                            ) as exif_tool:
                                exif_tool.set_tags(
                                    jpeg_path, tags=jpeg_tags, params=["-overwrite_original"]
                                )
                            
                            os.remove(output_path)  # Remove WEBP since JPEG worked
                            self.verbose_msg(f"Converted composite to JPEG with full EXIF: {jpeg_path}")
                            
                        except Exception as e3:
                            # Set file modification time as absolute last resort
                            try:
                                timestamp = local_dt.timestamp()
                                os.utime(output_path, (timestamp, timestamp))
                                self.verbose_msg(f"Set file modification time for composite: {output_path}")
                            except Exception:
                                pass
            
            self.verbose_msg(f"Created composite image with rounded corners: {output_path}")
            
        except Exception as e:
            print(f"Error creating composite image: {e}")
            # Fallback to just copying the primary image WITH METADATA
            cp(primary_path, output_path)
            
            # Apply metadata to fallback copy if datetime is provided
            if img_dt:
                # Convert to local time based on location
                local_dt = self.convert_to_local_time(img_dt, img_location)
                
                tags = {
                    "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                    "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                    "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
                }
                
                if img_location:
                    tags.update(
                        {
                            "GPSLatitude": img_location["latitude"],
                            "GPSLongitude": img_location["longitude"],
                            "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                            "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                        }
                    )

                try:
                    with (
                        et(executable=self.exiftool_path) if self.exiftool_path else et()
                    ) as exif_tool:
                        exif_tool.set_tags(
                            output_path, tags=tags, params=["-P", "-overwrite_original", "-m"]
                        )
                    self.verbose_msg(f"Metadata added to fallback composite: {output_path}")
                except Exception as e:
                    # Try fallback approach for fallback composite
                    try:
                        fallback_tags = {"DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S")}
                        if img_location:
                            fallback_tags.update({
                                "GPSLatitude": img_location["latitude"],
                                "GPSLongitude": img_location["longitude"],
                            })
                        
                        with (
                            et(executable=self.exiftool_path) if self.exiftool_path else et()
                        ) as exif_tool:
                            exif_tool.set_tags(
                                output_path, tags=fallback_tags, params=["-overwrite_original", "-m", "-q"]
                            )
                        self.verbose_msg(f"Fallback metadata added to fallback composite: {output_path}")
                    except Exception as e2:
                        print(f"WEBP metadata failed for fallback composite {output_path}, trying JPEG conversion...")
                        # Convert fallback composite to JPEG
                        try:
                            jpeg_path = output_path.replace('.webp', '.jpg')
                            with Image.open(output_path) as img:
                                if img.mode in ('RGBA', 'LA', 'P'):
                                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                                    if img.mode == 'P':
                                        img = img.convert('RGBA')
                                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                                    img = rgb_img
                                img.save(jpeg_path, 'JPEG', quality=95, optimize=True)
                            
                            # Add full EXIF to JPEG
                            jpeg_tags = {
                                "DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                                "CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
                                "ModifyDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
                            }
                            if img_location:
                                jpeg_tags.update({
                                    "GPSLatitude": img_location["latitude"],
                                    "GPSLongitude": img_location["longitude"],
                                    "GPSLatitudeRef": "N" if img_location["latitude"] >= 0 else "S",
                                    "GPSLongitudeRef": "E" if img_location["longitude"] >= 0 else "W",
                                })
                            
                            with (
                                et(executable=self.exiftool_path) if self.exiftool_path else et()
                            ) as exif_tool:
                                exif_tool.set_tags(
                                    jpeg_path, tags=jpeg_tags, params=["-overwrite_original"]
                                )
                            
                            os.remove(output_path)  # Remove WEBP since JPEG worked
                            self.verbose_msg(f"Converted fallback composite to JPEG with full EXIF: {jpeg_path}")
                            
                        except Exception as e3:
                            # Set file modification time as absolute last resort
                            try:
                                timestamp = local_dt.timestamp()
                                os.utime(output_path, (timestamp, timestamp))
                                self.verbose_msg(f"Set file modification time for fallback composite: {output_path}")
                            except Exception:
                                pass

    def export_memories(self, memories: list):
        """
        Exports all memories to the posts folder to avoid duplicates.
        
        MEMORIES vs POSTS:
        - Often contain the same images with different metadata formats
        - Memories: frontImage/backImage, takenTime, berealMoment, location data
        - Posts: primary/secondary, takenAt, limited metadata
        - Combined into posts folder to avoid duplication
        
        Creates composite images with backImage as primary and frontImage overlaid (BeReal style).
        Uses parallel processing for faster execution.
        """
        out_path_memories = os.path.join(self.out_path, "posts")  # Use posts folder
        os.makedirs(out_path_memories, exist_ok=True)

        # Filter memories within time span first
        valid_memories = []
        for memory in memories:
            memory_dt = self.get_datetime_from_str(memory["takenTime"])
            if self.time_span[0] <= memory_dt <= self.time_span[1]:
                valid_memories.append(memory)

        if not valid_memories:
            self.verbose_msg("No memories found in the specified time range")
            return

        self.verbose_msg(f"Processing {len(valid_memories)} memories with {self.max_workers} workers (saving to posts folder)...")

        # Process memories in parallel with progress bar
        with logging_redirect_tqdm() if self.verbose else tqdm(disable=False):
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_memory = {
                    executor.submit(self.process_memory, memory, out_path_memories): i 
                    for i, memory in enumerate(valid_memories, 1)
                }
                
                # Process completed tasks with progress bar
                with tqdm(total=len(valid_memories), desc="Exporting memories", unit="memory", 
                         leave=True, position=0) as pbar:
                    for future in as_completed(future_to_memory):
                        memory_index = future_to_memory[future]
                        try:
                            result = future.result()
                            if result:
                                pbar.set_postfix_str(f"Latest: {result}")
                            pbar.update(1)
                        except Exception as e:
                            tqdm.write(f"Error processing memory {memory_index}: {e}")
                            pbar.update(1)

        self.verbose_msg(f"Completed exporting {len(valid_memories)} memories")

    def export_realmojis(self, realmojis: list):
        """
        Exports all realmojis from the Photos directory to the corresponding output folder.
        """
        out_path_realmojis = os.path.join(self.out_path, "realmojis")
        os.makedirs(out_path_realmojis, exist_ok=True)

        # Filter realmojis within time span first
        valid_realmojis = []
        for realmoji in realmojis:
            realmoji_dt = self.get_datetime_from_str(realmoji["postedAt"])
            if self.time_span[0] <= realmoji_dt <= self.time_span[1]:
                valid_realmojis.append((realmoji, realmoji_dt))

        if not valid_realmojis:
            self.verbose_msg("No realmojis found in the specified time range")
            return

        # Process with progress bar
        with logging_redirect_tqdm() if self.verbose else tqdm(disable=False):
            with tqdm(valid_realmojis, desc="Exporting realmojis", unit="realmoji",
                     leave=True, position=0) as pbar:
                for realmoji, realmoji_dt in pbar:
                    # Convert to local time for filename (to match EXIF metadata)
                    local_dt = self.convert_to_local_time(realmoji_dt, None)
                    
                    img_name = (
                        f"{out_path_realmojis}/{local_dt.strftime('%Y-%m-%d_%H-%M-%S')}.webp"
                    )
                    old_img_name = os.path.join(
                        self.bereal_path,
                        realmoji["media"]["path"],
                    )
                    self.export_img(old_img_name, img_name, realmoji_dt, None)
                    pbar.set_postfix_str(f"Latest: {local_dt.strftime('%Y-%m-%d_%H-%M-%S')}")

    def export_posts(self, posts: list):
        """
        Exports all posts from the Photos directory to the corresponding output folder.
        
        POSTS vs MEMORIES:
        - Posts: Older BeReal format with basic metadata (single timestamp, less location data)
        - Memories: More recent format with rich metadata (location, multiple timestamps)
        - Posts have: primary/secondary images, takenAt timestamp, limited metadata
        - Memories have: frontImage/backImage, takenTime/berealMoment, location data
        
        Creates composite images with primary as background and secondary overlaid (BeReal style).
        Uses parallel processing for faster execution.
        """
        out_path_posts = os.path.join(self.out_path, "posts")
        os.makedirs(out_path_posts, exist_ok=True)

        # Filter posts within time span first
        valid_posts = []
        for post in posts:
            post_dt = self.get_datetime_from_str(post["takenAt"])
            if self.time_span[0] <= post_dt <= self.time_span[1]:
                valid_posts.append(post)

        if not valid_posts:
            self.verbose_msg("No posts found in the specified time range")
            return

        self.verbose_msg(f"Processing {len(valid_posts)} posts with {self.max_workers} workers...")

        # Process posts in parallel with progress bar
        with logging_redirect_tqdm() if self.verbose else tqdm(disable=False):
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_post = {
                    executor.submit(self.process_post, post, out_path_posts): i 
                    for i, post in enumerate(valid_posts, 1)
                }
                
                # Process completed tasks with progress bar
                with tqdm(total=len(valid_posts), desc="Exporting posts", unit="post",
                         leave=True, position=0) as pbar:
                    for future in as_completed(future_to_post):
                        post_index = future_to_post[future]
                        try:
                            result = future.result()
                            if result:
                                pbar.set_postfix_str(f"Latest: {result}")
                            pbar.update(1)
                        except Exception as e:
                            tqdm.write(f"Error processing post {post_index}: {e}")
                            pbar.update(1)

        self.verbose_msg(f"Completed exporting {len(valid_posts)} posts")

    def export_conversations(self):
        """
        Exports all conversation images from the conversations directory.
        Groups images by number prefix and creates composite images when pairs exist.
        """
        conversations_path = os.path.join(self.bereal_path, "conversations")
        if not os.path.exists(conversations_path):
            self.verbose_msg("No conversations folder found")
            return

        out_path_conversations = os.path.join(self.out_path, "conversations")
        os.makedirs(out_path_conversations, exist_ok=True)

        # Get all conversation folders
        conversation_folders = [f for f in os.listdir(conversations_path) 
                             if os.path.isdir(os.path.join(conversations_path, f))]

        # Count total interactive pairs if in interactive mode
        total_interactive_pairs = 0
        if self.interactive_conversations:
            for conversation_id in conversation_folders:
                conversation_folder = os.path.join(conversations_path, conversation_id)
                image_files = glob.glob(os.path.join(conversation_folder, "*.webp"))
                
                # Quick grouping to count pairs
                temp_groups = {}
                for image_file in image_files:
                    filename = os.path.basename(image_file)
                    try:
                        file_id = filename.split('-')[0]
                        if file_id not in temp_groups:
                            temp_groups[file_id] = []
                        temp_groups[file_id].append(image_file)
                    except (ValueError, IndexError):
                        pass
                
                # Count pairs (groups with exactly 2 images)
                for file_id, files in temp_groups.items():
                    if len(files) == 2:
                        total_interactive_pairs += 1

        with logging_redirect_tqdm() if self.verbose else tqdm(disable=False):
            # Create main progress bar
            main_pbar = tqdm(conversation_folders, desc="Exporting conversations", unit="conversation",
                           leave=True, position=0)
            
            # Create interactive progress bar if needed
            if self.interactive_conversations and total_interactive_pairs > 0:
                interactive_pbar = tqdm(total=total_interactive_pairs, 
                                      desc="Interactive selections", unit="pair",
                                      leave=True, position=1)
                interactive_count = 0
            else:
                interactive_pbar = None
                interactive_count = 0
            
            for conversation_id in main_pbar:
                    conversation_folder = os.path.join(conversations_path, conversation_id)
                    out_conversation_folder = os.path.join(out_path_conversations, conversation_id)
                    os.makedirs(out_conversation_folder, exist_ok=True)

                    # Get all image files in the conversation
                    image_files = glob.glob(os.path.join(conversation_folder, "*.webp"))
                    
                    # Check for chat log to get timestamps and user info
                    chat_log_path = os.path.join(conversation_folder, "chat_log.json")
                    chat_log = []
                    chat_log_by_id = {}
                    if os.path.exists(chat_log_path):
                        try:
                            with open(chat_log_path, 'r', encoding='utf-8') as f:
                                chat_log_data = json.load(f)
                                self.verbose_msg(f"Chat log structure: {type(chat_log_data)}")
                                
                                # Handle the actual structure: {"conversationId": "...", "messages": [{"id": "7", "userId": "...", "createdAt": "..."}]}
                                if isinstance(chat_log_data, dict) and "messages" in chat_log_data:
                                    messages = chat_log_data["messages"]
                                    self.verbose_msg(f"Found {len(messages)} messages in chat log")
                                    
                                    for message in messages:
                                        if isinstance(message, dict) and "id" in message:
                                            message_id = message["id"]
                                            chat_log_by_id[message_id] = message
                                            chat_log.append(message)
                                            self.verbose_msg(f"Added message ID {message_id}: {message.get('createdAt', 'no timestamp')}")
                                
                                elif isinstance(chat_log_data, list):
                                    # Fallback: Array of entries
                                    chat_log = chat_log_data
                                    for entry in chat_log:
                                        if isinstance(entry, dict) and "id" in entry:
                                            chat_log_by_id[entry["id"]] = entry
                                
                                self.verbose_msg(f"Loaded {len(chat_log_by_id)} chat log entries")
                                if chat_log_by_id:
                                    sample_key = list(chat_log_by_id.keys())[0]
                                    self.verbose_msg(f"Sample entry: ID {sample_key} (type: {type(sample_key)}) -> {chat_log_by_id[sample_key]}")
                                    self.verbose_msg(f"All chat log IDs: {list(chat_log_by_id.keys())}")  # Show all IDs
                                    
                        except Exception as e:
                            self.verbose_msg(f"Could not read chat log: {e}")
                            import traceback
                            self.verbose_msg(f"Full error: {traceback.format_exc()}")

                    # Group images by their ID prefix (matches chat_log.json id field)
                    image_groups = {}
                    for image_file in image_files:
                        filename = os.path.basename(image_file)
                        try:
                            # Extract ID from filename like "7-gchAVq_kc0wAbj_tMMC3D.webp" -> "7"
                            file_id = filename.split('-')[0]
                            if file_id not in image_groups:
                                image_groups[file_id] = []
                            image_groups[file_id].append(image_file)
                            self.verbose_msg(f"Found image with ID {file_id}: {filename}")
                        except (ValueError, IndexError):
                            # Handle files without ID prefix
                            if 'misc' not in image_groups:
                                image_groups['misc'] = []
                            image_groups['misc'].append(image_file)
                            self.verbose_msg(f"Image without ID prefix: {filename}")
                    
                    # Sort files within each group to ensure consistent ordering
                    for file_id in image_groups:
                        image_groups[file_id].sort()
                    
                    # Debug: Show all groups found
                    self.verbose_msg(f"Found {len(image_groups)} image groups:")
                    for file_id, files in image_groups.items():
                        self.verbose_msg(f"  Group {file_id}: {len(files)} files - {[os.path.basename(f) for f in files]}")

                    # Process each group
                    for file_id, group_files in image_groups.items():
                        # Try to extract timestamp and user info from chat log using the file ID
                        img_dt = None
                        user_id = None
                        
                        try:
                            self.verbose_msg(f"Looking for ID '{file_id}' (type: {type(file_id)}) in chat log...")
                            self.verbose_msg(f"Available IDs in chat log: {list(chat_log_by_id.keys()) if len(chat_log_by_id) < 20 else list(chat_log_by_id.keys())[:20]}")
                            
                            # Try different ID formats (string vs int)
                            found_entry = None
                            if file_id in chat_log_by_id:
                                found_entry = chat_log_by_id[file_id]
                            elif str(file_id) in chat_log_by_id:
                                found_entry = chat_log_by_id[str(file_id)]
                            elif int(file_id) in chat_log_by_id:
                                found_entry = chat_log_by_id[int(file_id)]
                            
                            if found_entry:
                                img_dt = self.get_datetime_from_str(found_entry.get('createdAt', ''))
                                user_id = found_entry.get('userId', 'unknown')
                                self.verbose_msg(f"✓ Found chat log entry for ID {file_id}: {found_entry.get('createdAt')} by user {user_id[:8]}...")
                            else:
                                # Use modification time of first file in group
                                img_dt = dt.fromtimestamp(os.path.getmtime(group_files[0]))
                                self.verbose_msg(f"✗ No chat log entry for ID {file_id}, using file modification time")
                                self.verbose_msg(f"✗ Tried looking for: '{file_id}', '{str(file_id)}', {int(file_id) if file_id.isdigit() else 'N/A'}")
                        except (ValueError, KeyError) as e:
                            img_dt = dt.fromtimestamp(os.path.getmtime(group_files[0]))
                            self.verbose_msg(f"✗ Error parsing chat log for ID {file_id}: {e}, using file modification time")

                        # Check if within time span
                        if not (self.time_span[0] <= img_dt <= self.time_span[1]):
                            continue

                        # Convert to local time for filename (to match EXIF metadata)
                        local_dt = self.convert_to_local_time(img_dt, None)
                        
                        # Export individual images with user info
                        exported_files = []
                        for i, image_file in enumerate(group_files):
                            filename = os.path.basename(image_file)
                            # Include user ID in filename if available
                            user_suffix = f"_user_{user_id[:8]}" if user_id and user_id != 'unknown' else ""
                            base_name = os.path.splitext(filename)[0]
                            output_filename = f"{local_dt.strftime('%Y-%m-%d_%H-%M-%S')}_id{file_id}_{i+1}{user_suffix}_{base_name}.webp"
                            output_path = os.path.join(out_conversation_folder, output_filename)
                            
                            self.export_img(image_file, output_path, img_dt, None)
                            if os.path.exists(output_path):
                                exported_files.append(output_path)

                        # Create composite if we have exactly 2 images
                        if len(exported_files) == 2:
                            user_suffix = f"_user_{user_id[:8]}" if user_id and user_id != 'unknown' else ""
                            composite_filename = f"{local_dt.strftime('%Y-%m-%d_%H-%M-%S')}_id{file_id}{user_suffix}_composited.webp"
                            composite_path = os.path.join(out_conversation_folder, composite_filename)
                            
                            # Choose detection method based on interactive mode
                            if self.web_ui and self.interactive_conversations:
                                # Update interactive progress
                                if interactive_pbar:
                                    interactive_pbar.set_description(f"Web UI: {conversation_id} msg {file_id}")
                                
                                # Create progress info
                                progress_info = f"Interactive pair {interactive_count + 1} of {total_interactive_pairs}" if interactive_pbar else None
                                
                                primary_img, overlay_img = self.web_ui_choose_primary_overlay(
                                    exported_files, conversation_id, file_id, progress_info
                                )
                                
                                # Update progress after selection
                                if interactive_pbar:
                                    interactive_pbar.update(1)
                                    interactive_pbar.set_description("Interactive selections")
                                    
                            elif self.interactive_conversations:
                                # Update interactive progress
                                if interactive_pbar:
                                    interactive_pbar.set_description(f"CLI: {conversation_id} msg {file_id}")
                                
                                # Create progress info
                                progress_info = f"Interactive pair {interactive_count + 1} of {total_interactive_pairs}" if interactive_pbar else None
                                
                                primary_img, overlay_img = self.interactive_choose_primary_overlay(
                                    group_files, exported_files, conversation_id, file_id, progress_info
                                )
                                
                                # Update progress after selection
                                if interactive_pbar:
                                    interactive_pbar.update(1)
                                    interactive_pbar.set_description("Interactive selections")
                                    
                            else:
                                primary_img, overlay_img = self.detect_primary_overlay_conversation(group_files, exported_files)
                            
                            # Create composite if user didn't skip
                            if primary_img and overlay_img:
                                self.create_composite_image(primary_img, overlay_img, composite_path, img_dt, None)
                                self.verbose_msg(f"Created composite for conversation ID {file_id} by user {user_id[:8] if user_id else 'unknown'}")
                            else:
                                self.verbose_msg(f"Skipped composite for conversation ID {file_id}")

                    main_pbar.set_postfix_str(f"Latest: {conversation_id}")
                    self.verbose_msg(f"Exported conversation: {conversation_id}")
            
            # Close interactive progress bar
            if interactive_pbar:
                interactive_pbar.close()


if __name__ == "__main__":
    args = init_parser()
    
    try:
        exporter = BeRealExporter(args)
        print(f"Found BeReal export at: {exporter.bereal_path}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        exit(1)

    if args.memories:
        try:
            memories_path = os.path.join(exporter.bereal_path, "memories.json")
            if os.path.exists(memories_path):
                with open(memories_path, encoding="utf-8") as f:
                    memories = json.load(f)
                    exporter.export_memories(memories)
            else:
                print("memories.json file not found, skipping memories export.")
        except json.JSONDecodeError:
            print("Error decoding memories.json file.")

    if args.posts:
        try:
            posts_path = os.path.join(exporter.bereal_path, "posts.json")
            if os.path.exists(posts_path):
                with open(posts_path, encoding="utf-8") as f:
                    posts = json.load(f)
                    exporter.export_posts(posts)
            else:
                print("posts.json file not found, skipping posts export.")
        except json.JSONDecodeError:
            print("Error decoding posts.json file.")

    if args.realmojis:
        try:
            realmojis_path = os.path.join(exporter.bereal_path, "realmojis.json")
            if os.path.exists(realmojis_path):
                with open(realmojis_path, encoding="utf-8") as f:
                    realmojis = json.load(f)
                    exporter.export_realmojis(realmojis)
            else:
                print("realmojis.json file not found, skipping realmojis export.")
        except json.JSONDecodeError:
            print("Error decoding realmojis.json file.")

    if args.conversations:
        exporter.export_conversations()
