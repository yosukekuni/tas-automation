#!/usr/bin/env python3
"""
Featured Image Rotation Script
Adds photo variations to WordPress featured images for tokaiair.com
Each category group gets 3-5 images rotated across posts.
"""

import requests
import json
import time
import os
import sys
from PIL import Image
from io import BytesIO
from collections import defaultdict

# Config
CONFIG_PATH = '/mnt/c/Users/USER/Documents/_data/automation_config.json'
TEMP_DIR = '/tmp/featured_images'
TARGET_WIDTH = 1200
TARGET_HEIGHT = 630
JPEG_QUALITY = 85
SLEEP_BETWEEN_REQUESTS = 0.5

# Photos to upload per category group (keyed by current featured_media ID)
# Each entry: (source_path, wp_upload_filename, alt_text)
PHOTOS_TO_UPLOAD = {
    # Drone Survey (currently Media 6682, 29 posts) - add 3 new = 4 total
    6682: [
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-06-21_愛知アリーナ/DJI_0093.JPG',
            'drone-survey-aichi-arena.jpg',
            'ドローン測量 愛知アリーナ建設現場'
        ),
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2022-10-05_豊橋PA/DJI_0396.JPG',
            'drone-survey-toyohashi-pa.jpg',
            'ドローン測量 豊橋パーキングエリア俯瞰'
        ),
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2024-11-07豊橋公園/100_0050/100_0050_0010.JPG',
            'drone-survey-toyohashi-park.jpg',
            'ドローン測量 豊橋公園陸上競技場'
        ),
    ],
    # Earthwork/Volume Calculation (currently Media 6681, 21 posts) - add 3 new = 4 total
    6681: [
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-09-07_ラ・サール岩塚Ⅱ土量計測/100_0001_0005.JPG',
            'earthwork-lasalle-iwatsuka.jpg',
            '土量計測 ラ・サール岩塚現場'
        ),
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-06-05_東海市分譲地/DJI_0030.JPG',
            'earthwork-tokai-bunjouchi.jpg',
            '土量計測 東海市分譲地開発エリア'
        ),
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-09-07_ラ・サール岩塚Ⅱ土量計測/100_0001_0010.JPG',
            'earthwork-lasalle-iwatsuka-2.jpg',
            '土量計測 ラ・サール岩塚 工場跡地'
        ),
    ],
    # Factory/Plant (currently Media 6675, 9 posts) - add 1 new = 2 total
    6675: [
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/20251121折兼豊橋_UAVおよび内部スキャン/100_0008/100_0008_0003.JPG',
            'factory-orikane-toyohashi.jpg',
            '工場・プラント 折兼豊橋倉庫俯瞰'
        ),
    ],
    # Inventory Measurement (currently Media 6676, 8 posts) - add 2 new = 3 total
    6676: [
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-11-28_名古屋埠頭/DJI_0134.JPG',
            'inventory-nagoya-wharf-wide.jpg',
            '在庫計測 名古屋埠頭 石炭ヤード全景'
        ),
        (
            '/mnt/nas4/1_Projects/UAV_survey_data/2023-11-28_名古屋埠頭/DJI_0137.JPG',
            'inventory-nagoya-wharf-ship.jpg',
            '在庫計測 名古屋埠頭 貨物船と石炭ヤード'
        ),
    ],
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def center_crop_resize(img_path, target_w, target_h):
    """Center-crop and resize image to target dimensions."""
    img = Image.open(img_path)

    # Handle EXIF rotation
    try:
        from PIL import ExifTags
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        exif = img._getexif()
        if exif:
            orient = exif.get(orientation)
            if orient == 3:
                img = img.rotate(180, expand=True)
            elif orient == 6:
                img = img.rotate(270, expand=True)
            elif orient == 8:
                img = img.rotate(90, expand=True)
    except (AttributeError, KeyError, IndexError):
        pass

    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider - crop sides
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, src_h))
    else:
        # Source is taller - crop top/bottom
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        img = img.crop((0, offset, src_w, offset + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)
    return img


def upload_to_wordpress(img_path, filename, alt_text, auth, base_url):
    """Upload image to WordPress Media Library."""
    buf = BytesIO()
    img = center_crop_resize(img_path, TARGET_WIDTH, TARGET_HEIGHT)
    img.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    buf.seek(0)

    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': 'image/jpeg',
    }

    r = requests.post(
        f'{base_url}/media',
        headers=headers,
        data=buf.read(),
        auth=auth,
        timeout=60
    )

    if r.status_code not in (200, 201):
        print(f'  ERROR uploading {filename}: {r.status_code} {r.text[:200]}')
        return None

    media = r.json()
    media_id = media['id']

    # Update alt text
    requests.post(
        f'{base_url}/media/{media_id}',
        json={'alt_text': alt_text},
        auth=auth,
        timeout=30
    )

    print(f'  Uploaded {filename} -> Media ID {media_id}')
    return media_id


def get_all_posts(auth, base_url):
    """Fetch all posts with their featured_media."""
    all_posts = []
    page = 1
    while True:
        r = requests.get(
            f'{base_url}/posts',
            params={'per_page': 100, 'page': page, '_fields': 'id,title,categories,featured_media'},
            auth=auth,
            timeout=30
        )
        if r.status_code != 200:
            break
        posts = r.json()
        if not posts:
            break
        all_posts.extend(posts)
        page += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    return all_posts


def main():
    config = load_config()
    wp = config['wordpress']
    auth = (wp['user'], wp['app_password'])
    base_url = wp['base_url']

    os.makedirs(TEMP_DIR, exist_ok=True)

    # Step 1: Get all posts
    print('=== Step 1: Fetching all posts ===')
    all_posts = get_all_posts(auth, base_url)
    print(f'Found {len(all_posts)} posts')

    # Group posts by featured_media
    media_groups = defaultdict(list)
    for p in all_posts:
        media_groups[p['featured_media']].append(p)

    for mid in sorted(media_groups.keys()):
        print(f'  Media {mid}: {len(media_groups[mid])} posts')

    # Step 2: Upload new photos
    print('\n=== Step 2: Uploading new photos ===')
    new_media_ids = {}  # {original_media_id: [new_media_id1, new_media_id2, ...]}

    for original_mid, photos in PHOTOS_TO_UPLOAD.items():
        print(f'\nCategory group (current Media {original_mid}, {len(media_groups.get(original_mid, []))} posts):')
        new_ids = []
        for src_path, filename, alt_text in photos:
            if not os.path.exists(src_path):
                print(f'  SKIP: File not found: {src_path}')
                continue

            media_id = upload_to_wordpress(src_path, filename, alt_text, auth, base_url)
            if media_id:
                new_ids.append(media_id)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        new_media_ids[original_mid] = new_ids
        print(f'  Uploaded {len(new_ids)} new images')

    # Step 3: Assign images in rotation
    print('\n=== Step 3: Assigning featured images in rotation ===')

    changes_made = 0
    changes_log = []

    for original_mid, new_ids in new_media_ids.items():
        if not new_ids:
            print(f'\nSkipping Media {original_mid}: no new images uploaded')
            continue

        posts = media_groups.get(original_mid, [])
        if not posts:
            continue

        # Build rotation list: original + new images
        rotation = [original_mid] + new_ids
        total_images = len(rotation)

        print(f'\nMedia {original_mid} -> Rotation of {total_images} images across {len(posts)} posts')
        print(f'  Images: {rotation}')

        # Sort posts by ID for consistent ordering
        posts.sort(key=lambda p: p['id'])

        for i, post in enumerate(posts):
            target_media = rotation[i % total_images]

            if target_media == post['featured_media']:
                # No change needed (keeps original)
                continue

            # Update featured image
            r = requests.post(
                f'{base_url}/posts/{post["id"]}',
                json={'featured_media': target_media},
                auth=auth,
                timeout=30
            )

            if r.status_code == 200:
                title = post['title']['rendered'][:40]
                print(f'  Post {post["id"]} ({title}): {post["featured_media"]} -> {target_media}')
                changes_log.append({
                    'post_id': post['id'],
                    'title': post['title']['rendered'],
                    'old_media': post['featured_media'],
                    'new_media': target_media,
                })
                changes_made += 1
            else:
                print(f'  ERROR Post {post["id"]}: {r.status_code}')

            time.sleep(SLEEP_BETWEEN_REQUESTS)

    # Step 4: Summary
    print(f'\n=== Summary ===')
    print(f'Total posts: {len(all_posts)}')
    print(f'New images uploaded: {sum(len(ids) for ids in new_media_ids.values())}')
    print(f'Posts updated: {changes_made}')

    # Save changelog
    log_path = os.path.join(TEMP_DIR, 'featured_image_changes.json')
    with open(log_path, 'w') as f:
        json.dump({
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'new_media_ids': {str(k): v for k, v in new_media_ids.items()},
            'changes': changes_log,
        }, f, ensure_ascii=False, indent=2)
    print(f'Changelog saved to: {log_path}')


if __name__ == '__main__':
    main()
