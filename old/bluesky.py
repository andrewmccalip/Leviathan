import json
from atproto_client.models import get_or_create
from atproto import CAR, models
from atproto_firehose import FirehoseSubscribeReposClient, parse_subscribe_repos_message
from termcolor import colored
import random
from multiformats import CID
import os
import requests

def text_recorder(message):
    """Records only text content from Bluesky posts"""
    commit = parse_subscribe_repos_message(message)
    if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
        return
    car = CAR.from_bytes(commit.blocks)
    for op in commit.ops:
        if op.action in ["create"] and op.cid:
            raw = car.blocks.get(op.cid)
            if raw.get("$type") == "app.bsky.feed.post":
                text_content = raw.get("text", "")
                colors = ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
                color = random.choice(colors)
                print(colored(text_content, color))
                with open("bluesky.txt", "a", encoding="utf-8") as f:
                    f.write(text_content + "\n")

def image_recorder(message):
    """Records only image URLs from Bluesky posts"""
    commit = parse_subscribe_repos_message(message)
    if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
        return
    
    car = CAR.from_bytes(commit.blocks)
    for op in commit.ops:
        if op.action in ["create"] and op.cid:
            raw = car.blocks.get(op.cid)
            
            # Only process posts
            if raw.get("$type") != "app.bsky.feed.post":
                continue
                
            # Check for images in different possible embed types
            if "embed" in raw:
                embed = raw["embed"]
                
                # Handle direct image embeds
                if embed.get("$type") == "app.bsky.embed.images":
                    for image in embed.get("images", []):
                        if isinstance(image, dict) and "image" in image:
                            # Get the image blob
                            blob = image["image"]
                            if isinstance(blob, dict) and "ref" in blob:
                                # Get the DID from the commit
                                did = commit.repo
                                
                                # Get the CID from the blob reference
                                ref = blob["ref"]
                                if isinstance(ref, bytes):
                                    # Convert raw bytes to IPFS CID
                                    cid = str(CID.decode(ref))
                                else:
                                    cid = str(ref)
                                
                                # Construct CDN URL
                                full_url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{cid}@png"
                                
                                alt_text = image.get("alt", "No description provided")
                                # Truncate the display URL at "png"
                                display_url = full_url[:full_url.find("@png") + 4]
                                
                                # Create images/bluesky directory if it doesn't exist
                                os.makedirs("images/bluesky", exist_ok=True)
                                
                                # Download and save the image
                                try:
                                    response = requests.get(full_url)
                                    if response.status_code == 200:
                                        # Use CID as filename to ensure uniqueness
                                        filename = f"images/bluesky/{cid}.png"
                                        with open(filename, "wb") as f:
                                            f.write(response.content)
                                        print(colored(f"Found image: {display_url}", 'green'))
                                        
                                        # Still log to the text file
                                        with open("bluesky_images.txt", "a", encoding="utf-8") as f:
                                            f.write(f"{full_url}\t{alt_text}\n")
                                    else:
                                        print(colored(f"Failed to download image: {display_url}", 'red'))
                                except Exception as e:
                                    print(colored(f"Error downloading image: {e}", 'red'))

if __name__ == "__main__":
    print(colored("Starting Bluesky image recorder...", 'green'))
    client = FirehoseSubscribeReposClient()
    client.start(image_recorder)