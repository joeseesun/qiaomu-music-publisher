---
name: qiaomu-music-publisher
description: |
  Publish Suno songs to a Qiaomu Music Player Web instance. Use when asked to upload, publish, or sync Suno song URLs/IDs, MP3, LRC lyrics, and cover art to 乔木音乐, music.qiaomu.ai, or a qiaomu-music-player-web site.
---

# Qiaomu Music Publisher

把 Suno 歌曲资产发布到 Qiaomu Music Player Web。这个 skill 是
`qiaomu-suno-master` 的发布适配器：Suno 生成和下载仍由 Suno Master 负责，
乔木音乐的登录、封面/歌词/音频打包和上传由本 skill 负责。

## Boundary

- This skill is optional and site-specific. It must not be folded into
  `qiaomu-suno-master` core logic.
- Do not hardcode private credentials, cookies, VPS paths, or production-only
  domains.
- Read deployment settings from environment variables:
  - `QIAOMU_MUSIC_BASE_URL`, default `http://127.0.0.1:3068`
  - `QIAOMU_MUSIC_ADMIN_PASSWORD`, fallback `ADMIN_PASSWORD`
- Upload through the modern admin API `POST /api/admin/tracks`, not the legacy
  `PUT /api/upload`, because the legacy path cannot publish cover art or LRC.

## When To Use

Use this skill when the user asks to:

- 上传到乔木音乐
- 发布到 music.qiaomu.ai
- 把 Suno 歌曲 ID/URL 下载后发布
- 将 MP3、LRC、封面同步到 qiaomu-music-player-web

Do not use it for pure Suno lyric writing or music generation. Use
`qiaomu-suno-master` first for new song creation.

## Inputs

- `suno_ids_or_urls`: one or more Suno clip IDs, `https://suno.com/song/<id>`
  URLs, or `https://suno.com/s/<share>` short links
- `output_dir`: local asset directory; default `~/Documents/Suno/QiaomuMusicPublisher`
- `base_url`: from `QIAOMU_MUSIC_BASE_URL` unless user gives another instance
- `admin_password`: from `QIAOMU_MUSIC_ADMIN_PASSWORD` or `ADMIN_PASSWORD`
- `artist`: default `Qiaomu`
- `album`: default `Qiaomu Radio`
- `source`: default `Suno`
- `published`: default true

## Workflow

1. Normalize Suno URLs to clip IDs. Follow `https://suno.com/s/<share>` short
   links to their final `https://suno.com/song/<id>?sh=...` destination before
   extracting the ID.
2. If MP3/LRC are not already present, call Suno Master's downloader:

```bash
bash ~/.agents/skills/qiaomu-suno-master/scripts/download_clips.sh \
  --ids "$IDS" --output-dir "$OUTPUT_DIR" \
  --lyrics --lyrics-format lrc --require-lrc
```

3. Generate a Qiaomu album cover by default before publishing:
   - Use `qiaomu-image-generator` with template `album_cover`, style
     `album-mondo-cover`, aspect ratio `1:1`.
   - Build the visual description from the track title plus the timestamped LRC:
     extract lyric imagery, compress it into one strong visual symbol, prefer
     negative space / single focus / limited palette, and explicitly request no
     text, letters, numbers, logos, or song title in the image.
   - Save `*-cover.visual.json`, `*-cover.result.json`, and
     `*-qiaomu-cover.png` in the output directory.
   - Only use the Suno source cover as a last-resort fallback when generated
     cover creation fails, times out, or the caller passes `--no-generated-cover`.
   - If the caller passes `--cover`, use that explicit cover.
4. Validate that each track has:
   - one MP3 file
   - one timestamped `.lrc`
   - one cover image, preferably `*-qiaomu-cover.png`
5. Login to Qiaomu Music with `POST /api/login`.
6. Upload each track with `POST /api/admin/tracks` multipart fields:
   - `title`
   - `artist`
   - `album`
   - `source`
   - `published`
   - `lyrics` as LRC text
   - `audio` file
   - `cover` file
7. Report uploaded track IDs, titles, and public paths.

## Primary Command

```bash
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "ID1 ID2" \
  --output-dir "$OUTPUT_DIR"
```

Generated covers are enabled by default. Useful cover controls:

```bash
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "ID1" \
  --output-dir "$OUTPUT_DIR" \
  --cover-provider jimeng \
  --cover-timeout 240

# Last-resort mode only: skip Qiaomu cover generation and use Suno cover.
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "ID1" \
  --output-dir "$OUTPUT_DIR" \
  --no-generated-cover
```

For an explicit site:

```bash
QIAOMU_MUSIC_BASE_URL="https://your-music-site.example" \
QIAOMU_MUSIC_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
python3 scripts/publish_suno_to_qiaomu_music.py \
  --ids "https://suno.com/song/ID1" \
  --output-dir "$OUTPUT_DIR"
```

## Handoff From qiaomu-suno-master

When `qiaomu-suno-master` sees a request that includes "上传到乔木音乐",
"发布到乔木音乐", `music.qiaomu.ai`, or `qiaomu-music-player-web`, it should:

1. Generate/download MP3 and LRC with Suno Master.
2. Then invoke this skill for the publishing step.
3. Not implement Qiaomu Music upload internally.

## Output

Return a concise summary:

- uploaded track title and ID
- MP3/LRC/cover local paths
- whether the cover is a generated Qiaomu cover or a Suno fallback
- Qiaomu Music base URL
- whether the track is published
- any failed ID with the exact error
