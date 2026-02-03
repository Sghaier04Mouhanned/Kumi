import json
from pathlib import Path

from dotenv import load_dotenv
from landingai_ade import LandingAIADE
from landingai_ade.types import ParseResponse, ExtractResponse

from .schema import schema_json


# Supported image extensions (upper- and lower-case)
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".JPG",
    ".JPEG",
    ".PNG",
}


def parse_and_extract_image(
    client: LandingAIADE,
    image_path: Path,
    model_parse: str = "dpt-2-latest",
    model_extract: str = "extract-latest",
) -> dict:
    """
    Run Parse() then Extract() on a single image and return the extraction JSON.
    """
    print(f"⚡ Parsing {image_path.name}...")
    parse_result: ParseResponse = client.parse(
        document=image_path,
        model=model_parse,
    )

    print(f"   Parsing done: {len(parse_result.chunks)} chunks")

    print(f"⚡ Extracting from {image_path.name}...")
    extraction_result: ExtractResponse = client.extract(
        schema=schema_json,
        markdown=parse_result.markdown,
        model=model_extract,
    )
    print("   Extraction done.")

    # This is the structured JSON you inspected in the notebook
    return extraction_result.extraction


def process_folder(
    input_dir: Path,
    output_dir: Path,
    model_parse: str = "dpt-2-latest",
    model_extract: str = "extract-latest",
) -> None:
    """
    Process all images in input_dir and write one JSON file per image to output_dir.
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize ADE client
    client = LandingAIADE()
    print("Authenticated client initialized")

    # Iterate over all images in the folder
    for image_path in sorted(input_dir.iterdir()):
        if not (image_path.is_file() and image_path.suffix in IMAGE_EXTENSIONS):
            continue

        try:
            extraction_json = parse_and_extract_image(
                client=client,
                image_path=image_path,
                model_parse=model_parse,
                model_extract=model_extract,
            )

            # Save to JSON, using the same base name as the image
            output_path = output_dir / f"{image_path.stem}.json"
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(extraction_json, f, ensure_ascii=False, indent=2)

            print(f"✅ Saved: {output_path}")
        except Exception as exc:
            print(f"❌ Failed for {image_path.name}: {exc}")


def main() -> None:
    """
    Entry point for CLI usage.

    - Loads environment variables from .env
    - Processes all images in 'time tables' directory
    - Writes JSON outputs into 'output' directory
    """
    # Load environment variables (VISION_AGENT_API_KEY, etc.)
    load_dotenv(override=True)

    project_root = Path(__file__).resolve().parent.parent

    input_dir = project_root / "time tables"
    output_dir = project_root / "output"

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")

    process_folder(
        input_dir=input_dir,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()

