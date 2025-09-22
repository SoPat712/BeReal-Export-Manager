# BeReal Exporter

This python script doesn't export photos and realmojis from the social media platform BeReal directly - for that, you have to make a request to BeReal. See [this Reddit post](https://www.reddit.com/r/bereal_app/comments/19dl0yk/experiencetutorial_for_exporting_all_bereal/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button) for more information.

It processes the data from the BeReal export and exports the images with added metadata, such as the original date and location. Now supports posts, memories, realmojis, and conversation images with parallel processing for speed. Also has interactive modes for when you want to manually choose which camera is which for conversation images.

I'm gonna be upfront and say it's BeReal's fault the dates are wonky on the output files, idk why they chose to save the time like this:

        "takenTime": "2024-12-24T01:27:16.726Z",
        "berealMoment": "2024-12-23T22:39:05.327Z",

instead of the way everyone else always does it with UNIX Epoch time, but it makes it pretty hard to find out what time the picture was taken, and to properly tag the photos with the correct time. The script now handles timezone conversion automatically using GPS coordinates when available, falling back to America/New_York timezone.

## Installation

1. Clone the repository:
    ```sh
    git@github.com:SoPat712/BeReal-Export-Manager.git 
    cd BeReal-Export-Manager
    ```

2. Install the required Python packages:
    ```sh
    pip install -r requirements.txt
    ```

3. Ensure you have `exiftool` installed on your system and set it up as a `PATH` variable. You can download it [here](https://exiftool.org/).

4. Put your BeReal export folder in the `input` directory. The script will automatically find it.

## Usage

Put your BeReal export in the `input` folder and run:
```sh
python bereal_exporter.py [OPTIONS]
```

The script automatically finds your export folder and processes everything in parallel for speed.

## Options

- `-v, --verbose`: Explain what is being done.
- `-t, --timespan`: Exports the given timespan. 
  - Valid format: `DD.MM.YYYY-DD.MM.YYYY`.
  - Wildcards can be used: `DD.MM.YYYY-*`.
- `-y, --year`: Exports the given year.
- `-p, --out-path`: Set a custom output path (default is `./output`).
- `--input-path`: Set the input folder path containing BeReal export (default `./input`).
- `--exiftool-path`: Set the path to the ExifTool executable (needed if it isn't on the $PATH).
- `--max-workers`: Maximum number of parallel workers (default 4).
- `--no-memories`: Don't export the memories.
- `--no-realmojis`: Don't export the realmojis.
- `--no-posts`: Don't export the posts.
- `--no-conversations`: Don't export the conversations.
- `--conversations-only`: Export only conversations (for debugging).
- `--interactive-conversations`: Manually choose front/back camera for conversation images.
- `--web-ui`: Use web UI for interactive conversation selection (requires `--interactive-conversations`).

The script automatically handles timezone conversion using GPS coordinates when available, falling back to America/New_York. It creates composite images with the back camera as the main image and front camera overlaid in the corner with rounded edges and a black border, just like BeReal shows them.

## Examples

1. Export everything (default behavior):
    ```sh
    python bereal_exporter.py
    ```

2. Export data for the year 2022:
    ```sh
    python bereal_exporter.py --year 2022
    ```

3. Export data for a specific timespan:
    ```sh
    python bereal_exporter.py --timespan '04.01.2022-31.12.2022'
    ```

4. Export to a custom output path:
    ```sh
    python bereal_exporter.py --out-path /path/to/output
    ```

5. Use a different input folder:
    ```sh
    python bereal_exporter.py --input-path /path/to/bereal/export
    ```

6. Use portable exiftool:
    ```sh
    python bereal_exporter.py --exiftool-path /path/to/exiftool.exe
    ```

7. Export only memories and posts (skip realmojis and conversations):
    ```sh
    python bereal_exporter.py --no-realmojis --no-conversations
    ```

8. Debug conversations only:
    ```sh
    python bereal_exporter.py --conversations-only
    ```

9. Use more workers for faster processing:
    ```sh
    python bereal_exporter.py --max-workers 8
    ```

10. Interactive conversation selection (command line):
    ```sh
    python bereal_exporter.py --conversations-only --interactive-conversations
    ```

11. Interactive conversation selection (web UI):
    ```sh
    python bereal_exporter.py --conversations-only --interactive-conversations --web-ui
    ```

## Interactive Conversation Processing

For conversation images, the script tries to automatically detect which image should be the main view vs selfie view, but sometimes it gets it wrong. That's where the interactive modes come in handy.

**Automatic Detection**: The script looks at filenames, image dimensions, and patterns to guess which camera is which. Works most of the time but not always.

**Interactive Mode**: You can manually choose which image should be the selfie view (front camera overlay):
- **Command Line** (`--interactive-conversations`): Opens images in your system viewer, you choose via keyboard
- **Web UI** (`--interactive-conversations --web-ui`): Opens a web page where you just click on the selfie image

The web UI is pretty nice - shows both images side by side, you click the one that should be the selfie view, and it automatically continues processing. Much easier than the command line version.

**File Naming**: All images get descriptive names so you know what's what:
- `2022-09-10_16-35-30_main-view.webp` (back camera)
- `2022-09-10_16-35-30_selfie-view.webp` (front camera) 
- `2022-09-10_16-35-30_composited.webp` (combined image with selfie overlaid)

## What Gets Exported

The script exports different types of content to organized folders:

- **Posts**: Your daily BeReal posts (main-view/selfie-view images + composited versions)
- **Memories**: Same as posts but with richer metadata (location, multiple timestamps)
- **Realmojis**: Your reaction images
- **Conversations**: Images from private conversations

All images get proper EXIF metadata with:
- Original timestamps (converted to local timezone using GPS when available)
- GPS coordinates (when available)
- Composited images with front camera overlaid on back camera (BeReal style with rounded corners and black border)

The script automatically detects duplicate content between posts and memories to avoid saving the same image twice.

## Performance

Uses parallel processing with configurable worker threads (default 4) for faster exports. Progress bars show real-time status. On a decent machine, expect to process hundreds of images per minute. If you have a fast SSD and good CPU, try bumping up `--max-workers` to 8 or more.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.
