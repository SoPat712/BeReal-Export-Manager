# BeReal Exporter

This python script doesn't export photos and realmojis from the social media platform BeReal directly for that, you have to make a request to the BeReal see [this Reddit post](https://www.reddit.com/r/bereal_app/comments/19dl0yk/experiencetutorial_for_exporting_all_bereal/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button) for more information.

It simple processes the data from the BeReal export and exports the images(as well BTS-videos) with added metadata, such as the original date and location.

## Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/Lukullul/bereal-exporter.git
    cd bereal-exporter
    ```

2. Install the required Python packages:
    ```sh
    pip install -r requirements.txt
    ```

3. Ensure you have `exiftool` installed on your system and set it up as a `PATH` variable. You can download it [here](https://exiftool.org/).

## Usage

To run the script, use the following command:
```sh
python bereal_exporter.py [OPTIONS]
```

## Options

- `-v, --verbose`: Explain what is being done.
- `-t, --timespan`: Exports the given timespan. 
  - Valid format: `DD.MM.YYYY-DD.MM.YYYY`.
  - Wildcards can be used: `DD.MM.YYYY-*`.
- `--exiftool-path`: Set the path to the ExifTool executable (needed if it isn't on the $PATH)
- `-y, --year`: Exports the given year.
- `-p, --out-path`: Set a custom output path (default is `./out`).
- `--bereal-path`: Set a custom BeReal path (default `./`)
- `--no-memories`: Don't export the memories.
- `--no-realmojis`: Don't export the realmojis.

## Examples

1. Export data for the year 2022:
    ```sh
    python bereal_exporter.py --year 2022
    ```

2. Export data for a specific timespan:
    ```sh
    python bereal_exporter.py --timespan '04.01.2022-31.12.2022'
    ```

3. Export data to a custom output path:
    ```sh
    python bereal_exporter.py --path /path/to/output
    ```

4. Use portable installed exiftool application:
    ```sh
    python bereal_exporter.py --exiftool-path /path/to/exiftool.exe
    ```

5. Export memories only:
    ```sh
    python bereal_exporter.py --no-realmojis
    ```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.