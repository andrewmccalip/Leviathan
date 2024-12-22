import json
from atproto_client.models import get_or_create
from atproto import CAR, models
from atproto_firehose import FirehoseSubscribeReposClient, parse_subscribe_repos_message
from termcolor import colored
import random
from multiformats import CID

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
    
    print(colored(f"Debug - Full commit: {commit}", 'blue'))  # Debug print
    
    car = CAR.from_bytes(commit.blocks)
    for op in commit.ops:
        if op.action in ["create"] and op.cid:
            raw = car.blocks.get(op.cid)
            print(colored(f"Debug - Raw block data: {raw}", 'yellow'))  # Debug print
            
            # Only process posts
            if raw.get("$type") != "app.bsky.feed.post":
                continue
                
            # Check for images in different possible embed types
            if "embed" in raw:
                embed = raw["embed"]
                print(colored(f"Debug - Embed data: {embed}", 'cyan'))  # Debug print
                
                # Handle direct image embeds
                if embed.get("$type") == "app.bsky.embed.images":
                    for image in embed.get("images", []):
                        print(colored(f"Debug - Image data: {image}", 'magenta'))  # Debug print
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
                                print(colored(f"Found image: {full_url} (Alt: {alt_text})", 'green'))
                                
                                with open("bluesky_images.txt", "a", encoding="utf-8") as f:
                                    f.write(f"{full_url}\t{alt_text}\n")

if __name__ == "__main__":
    print(colored("Starting Bluesky image recorder...", 'green'))
    client = FirehoseSubscribeReposClient()
    client.start(image_recorder)