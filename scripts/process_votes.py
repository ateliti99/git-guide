#!/usr/bin/env python3
"""
Git Guide - Vote Processing Script

This script processes GitHub Issues with the 'mod-approved' label,
validates locations using geopy, and creates/updates Markdown files
in the countries/ directory structure.

Architecture:
    User opens Issue → Community votes → Mod approves → This script runs →
    Validates city → Creates place file → Updates indexes → Closes issue
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, Tuple

from github import Github, GithubException
from github.Issue import Issue
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# Configuration
VOTE_THRESHOLD = 100  # Minimum net votes (👍 - 👎) to accept
REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
COUNTRIES_DIR = Path("countries")

# Labels
LABEL_MOD_APPROVED = "mod-approved"
LABEL_PENDING = "pending-votes"
LABEL_ACCEPTED = "accepted"
LABEL_REJECTED = "rejected"
LABEL_VALIDATION_FAILED = "validation-failed"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """
    Convert a place name to a safe filename.
    
    Args:
        name: The original place name
        
    Returns:
        Sanitized filename (lowercase, underscores, .md extension)
        
    Example:
        "Trattoria da Mario!" → "trattoria_da_mario.md"
    """
    # Remove special characters, keep alphanumeric and spaces
    clean = re.sub(r"[^\w\s-]", "", name.strip())
    # Replace spaces/hyphens with underscores, lowercase
    clean = re.sub(r"[\s-]+", "_", clean).lower()
    # Remove leading/trailing underscores
    clean = clean.strip("_")
    return f"{clean}.md" if clean else "unnamed.md"


def sanitize_dirname(name: str) -> str:
    """
    Convert a city/country name to a safe directory name.
    
    Args:
        name: The original name
        
    Returns:
        Sanitized directory name (Title Case, spaces replaced)
        
    Example:
        "new york" → "New_York"
    """
    clean = re.sub(r"[^\w\s-]", "", name.strip())
    clean = re.sub(r"[\s-]+", "_", clean)
    # Title case each word
    return "_".join(word.capitalize() for word in clean.split("_"))


def validate_city(city_name: str) -> Optional[Tuple[str, str]]:
    """
    Validate and normalize a city name using OpenStreetMap via geopy.
    
    Args:
        city_name: User-provided city name
        
    Returns:
        Tuple of (normalized_city, country) or None if not found
        
    Example:
        "roma" → ("Rome", "Italy")
    """
    try:
        geolocator = Nominatim(user_agent="git-guide-bot/1.0")
        location = geolocator.geocode(
            city_name,
            exactly_one=True,
            language="en",
            addressdetails=True
        )
        
        if not location or not location.raw.get("address"):
            logger.warning(f"City not found: {city_name}")
            return None
        
        address = location.raw["address"]
        
        # Extract city name (try multiple fields)
        normalized_city = (
            address.get("city") or
            address.get("town") or
            address.get("village") or
            address.get("municipality") or
            city_name.title()
        )
        
        # Extract country
        country = address.get("country", "Unknown")
        
        logger.info(f"Validated: {city_name} → {normalized_city}, {country}")
        return (normalized_city, country)
        
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Geocoder error for {city_name}: {e}")
        return None


def parse_issue_body(body: str) -> dict:
    """
    Parse the Issue body (YAML form response) into a dictionary.
    
    GitHub Issue forms create a structured body with headers like:
    ### Place Name
    Trattoria da Mario
    
    Args:
        body: The raw issue body text
        
    Returns:
        Dictionary with extracted fields
    """
    data = {}
    current_field = None
    current_value = []
    
    # Field mapping from form labels to keys
    field_map = {
        "place name": "place_name",
        "city": "city",
        "category": "category",
        "description": "description",
        "address (optional)": "address",
        "address": "address",
        "website (optional)": "website",
        "website": "website",
    }
    
    for line in body.split("\n"):
        line = line.strip()
        
        # Check for header (### Field Name)
        if line.startswith("### "):
            # Save previous field
            if current_field:
                data[current_field] = "\n".join(current_value).strip()
            
            # Start new field
            header = line[4:].strip().lower()
            current_field = field_map.get(header)
            current_value = []
        elif current_field and line and not line.startswith("_No response_"):
            current_value.append(line)
    
    # Save last field
    if current_field:
        data[current_field] = "\n".join(current_value).strip()
    
    return data


def calculate_votes(issue: Issue) -> int:
    """
    Calculate net votes from issue reactions.
    
    Args:
        issue: GitHub Issue object
        
    Returns:
        Net votes (thumbs_up - thumbs_down)
    """
    reactions = issue.get_reactions()
    thumbs_up = 0
    thumbs_down = 0
    
    for reaction in reactions:
        if reaction.content == "+1":
            thumbs_up += 1
        elif reaction.content == "-1":
            thumbs_down += 1
    
    return thumbs_up - thumbs_down


def create_place_file(
    country: str,
    city: str,
    category: str,
    place_name: str,
    description: str,
    address: str = "",
    website: str = "",
    issue_number: int = 0
) -> Path:
    """
    Create the Markdown file for a place.
    
    Args:
        country: Country name
        city: City name
        category: "Eat" or "See"
        place_name: Name of the place
        description: Description text
        address: Optional address
        website: Optional website URL
        issue_number: Source issue number
        
    Returns:
        Path to the created file
    """
    # Build directory path
    dir_path = COUNTRIES_DIR / sanitize_dirname(country) / sanitize_dirname(city) / category
    dir_path.mkdir(parents=True, exist_ok=True)
    
    # Build file path
    file_path = dir_path / sanitize_filename(place_name)
    
    # Build content
    content = f"""# {place_name}

{description}

"""
    
    if address:
        content += f"**📍 Address:** {address}\n\n"
    
    if website:
        content += f"**🔗 Website:** [{website}]({website})\n\n"
    
    content += f"""---

> Added via [Issue #{issue_number}](../../../../../../issues/{issue_number})
"""
    
    # Write file (idempotent - overwrites if exists)
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Created/updated: {file_path}")
    
    return file_path


def update_city_index(country: str, city: str) -> None:
    """
    Update the city's README.md with all places.
    
    Args:
        country: Country name
        city: City name
    """
    city_path = COUNTRIES_DIR / sanitize_dirname(country) / sanitize_dirname(city)
    readme_path = city_path / "README.md"
    
    # Collect places
    eat_places = []
    see_places = []
    
    eat_dir = city_path / "Eat"
    see_dir = city_path / "See"
    
    if eat_dir.exists():
        for f in sorted(eat_dir.glob("*.md")):
            name = f.stem.replace("_", " ").title()
            eat_places.append(f"- [{name}](Eat/{f.name})")
    
    if see_dir.exists():
        for f in sorted(see_dir.glob("*.md")):
            name = f.stem.replace("_", " ").title()
            see_places.append(f"- [{name}](See/{f.name})")
    
    # Build README
    content = f"""# {city}

Your community guide to {city}!

"""
    
    if eat_places:
        content += "## 🍽️ Eat\n\n" + "\n".join(eat_places) + "\n\n"
    
    if see_places:
        content += "## 👀 See\n\n" + "\n".join(see_places) + "\n\n"
    
    if not eat_places and not see_places:
        content += "*No places added yet.*\n"
    
    content += """---

> [← Back to Country](../README.md) | [← Back to All Countries](../../README.md)
"""
    
    readme_path.write_text(content, encoding="utf-8")
    logger.info(f"Updated city index: {readme_path}")


def update_country_index(country: str) -> None:
    """
    Update the country's README.md with all cities.
    
    Args:
        country: Country name
    """
    country_path = COUNTRIES_DIR / sanitize_dirname(country)
    readme_path = country_path / "README.md"
    
    # Collect cities (directories with README.md)
    cities = []
    for d in sorted(country_path.iterdir()):
        if d.is_dir() and (d / "README.md").exists():
            city_name = d.name.replace("_", " ")
            cities.append(f"- [{city_name}]({d.name}/README.md)")
    
    # Build README
    content = f"""# {country}

Explore cities in {country}!

## 🏙️ Cities

"""
    
    if cities:
        content += "\n".join(cities) + "\n"
    else:
        content += "*No cities added yet.*\n"
    
    content += """
---

> [← Back to All Countries](../README.md)
"""
    
    readme_path.write_text(content, encoding="utf-8")
    logger.info(f"Updated country index: {readme_path}")


def update_root_index() -> None:
    """
    Update the root countries/README.md with all countries.
    """
    readme_path = COUNTRIES_DIR / "README.md"
    
    # Collect countries
    countries = []
    for d in sorted(COUNTRIES_DIR.iterdir()):
        if d.is_dir() and (d / "README.md").exists():
            country_name = d.name.replace("_", " ")
            countries.append(f"- 🌍 [{country_name}]({d.name}/README.md)")
    
    # Build README
    content = """# 🌍 Countries Index

Welcome to the Git Guide! Browse places by country below.

## Available Countries

"""
    
    if countries:
        content += "\n".join(countries) + "\n"
    else:
        content += "*No countries yet. Be the first to [propose a place](../../issues/new/choose)!*\n"
    
    content += """
---

> This index is automatically updated when new places are approved.
"""
    
    readme_path.write_text(content, encoding="utf-8")
    logger.info(f"Updated root index: {readme_path}")


def process_issue(gh: Github, issue: Issue) -> bool:
    """
    Process a single approved issue.
    
    Args:
        gh: GitHub client
        issue: The issue to process
        
    Returns:
        True if successfully processed, False otherwise
    """
    logger.info(f"Processing Issue #{issue.number}: {issue.title}")
    
    # Parse issue body
    data = parse_issue_body(issue.body or "")
    
    # Validate required fields
    required = ["place_name", "city", "category", "description"]
    missing = [f for f in required if not data.get(f)]
    
    if missing:
        msg = f"❌ Missing required fields: {', '.join(missing)}"
        issue.create_comment(msg)
        logger.error(msg)
        return False
    
    # Calculate votes
    net_votes = calculate_votes(issue)
    logger.info(f"Net votes: {net_votes} (threshold: {VOTE_THRESHOLD})")
    
    if net_votes < VOTE_THRESHOLD:
        msg = f"⏳ Not enough votes yet. Current: {net_votes}, Required: {VOTE_THRESHOLD}"
        issue.create_comment(msg)
        logger.info(msg)
        return False
    
    # Validate city
    location = validate_city(data["city"])
    
    if not location:
        msg = (
            f"❌ **Validation Failed**\n\n"
            f"Could not verify the city: **{data['city']}**\n\n"
            f"Please check the spelling and try again. "
            f"The `{LABEL_MOD_APPROVED}` label has been removed."
        )
        issue.create_comment(msg)
        
        # Remove mod-approved label
        try:
            issue.remove_from_labels(LABEL_MOD_APPROVED)
            issue.add_to_labels(LABEL_VALIDATION_FAILED)
        except GithubException:
            pass
        
        logger.warning(f"Validation failed for city: {data['city']}")
        return False
    
    normalized_city, country = location
    category = data["category"]
    
    # Create the place file
    create_place_file(
        country=country,
        city=normalized_city,
        category=category,
        place_name=data["place_name"],
        description=data["description"],
        address=data.get("address", ""),
        website=data.get("website", ""),
        issue_number=issue.number
    )
    
    # Update indexes
    update_city_index(country, normalized_city)
    update_country_index(country)
    update_root_index()
    
    # Comment success and close
    msg = (
        f"✅ **Success!**\n\n"
        f"**{data['place_name']}** has been added to the guide!\n\n"
        f"📍 Location: {normalized_city}, {country}\n"
        f"📁 Category: {category}\n"
        f"👍 Votes: {net_votes}\n\n"
        f"Thank you for your contribution! 🎉"
    )
    issue.create_comment(msg)
    
    # Update labels and close
    try:
        issue.remove_from_labels(LABEL_PENDING)
    except GithubException:
        pass
    
    try:
        issue.remove_from_labels(LABEL_MOD_APPROVED)
    except GithubException:
        pass
    
    issue.add_to_labels(LABEL_ACCEPTED)
    issue.edit(state="closed")
    
    logger.info(f"Successfully processed Issue #{issue.number}")
    return True


def main():
    """Main entry point."""
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN environment variable not set")
        return
    
    if not REPO_NAME:
        logger.error("GITHUB_REPOSITORY environment variable not set")
        return
    
    logger.info(f"Starting vote processing for {REPO_NAME}")
    
    # Initialize GitHub client
    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(REPO_NAME)
    
    # Ensure countries directory exists
    COUNTRIES_DIR.mkdir(exist_ok=True)
    
    # Find all open issues with mod-approved label
    issues = repo.get_issues(
        state="open",
        labels=[LABEL_MOD_APPROVED]
    )
    
    processed = 0
    failed = 0
    
    for issue in issues:
        try:
            if process_issue(gh, issue):
                processed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Error processing Issue #{issue.number}: {e}")
            issue.create_comment(f"❌ An error occurred while processing: {e}")
            failed += 1
    
    logger.info(f"Done! Processed: {processed}, Failed/Skipped: {failed}")


if __name__ == "__main__":
    main()
