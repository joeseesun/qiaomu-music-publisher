# Qiaomu Music Publisher

Optional publisher skill for sending Suno assets to a Qiaomu Music Player Web
instance.

This package intentionally keeps deployment secrets outside the repository.

## Environment

```bash
export QIAOMU_MUSIC_BASE_URL="https://your-music-site.example"
export QIAOMU_MUSIC_ADMIN_PASSWORD="..."
```

`QIAOMU_MUSIC_BASE_URL` defaults to `http://127.0.0.1:3068`.
`QIAOMU_MUSIC_ADMIN_PASSWORD` falls back to `ADMIN_PASSWORD`.

## Publish From Suno IDs

```bash
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "50a353a3-9c0c-4515-b87b-344b71b65ebf" \
  --output-dir ~/Documents/Suno/QiaomuMusicPublisher
```

The script will:

1. normalize Suno URLs/IDs
2. call `qiaomu-suno-master/scripts/download_clips.sh`
3. require timestamped `.lrc`
4. download Suno cover art from `suno info`
5. login with `POST /api/login`
6. upload through `POST /api/admin/tracks`

## Use Existing Local Assets

```bash
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "50a353a3-9c0c-4515-b87b-344b71b65ebf" \
  --output-dir ./song-assets \
  --no-download \
  --cover ./cover.png
```

`--no-download` expects the output directory to already contain an MP3 and LRC
whose filename includes the Suno ID or first 8 ID characters.

## Draft Upload

```bash
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "https://suno.com/song/50a353a3-9c0c-4515-b87b-344b71b65ebf" \
  --draft
```

## Boundary

This skill is a Qiaomu Music adapter. Keep Suno generation in
`qiaomu-suno-master`; keep publishing credentials and deployment-specific values
in environment variables.
