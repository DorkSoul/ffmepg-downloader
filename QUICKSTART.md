# Quick Start Guide

Get up and running in 5 minutes!

## 1. Deploy to Your NAS

### Using Portainer (Easiest)

1. Push this code to your GitHub repository
2. In Portainer: **Stacks** → **Add Stack** → **Repository**
3. Enter your repo URL and compose path: `docker-compose.yml`
4. Click **Deploy**

### Using SSH

```bash
git clone <your-repo>
cd nas-video-downloader
docker-compose up -d
```

## 2. Access the Interface

Open in your browser: **http://your-nas-ip:5000**

## 3. Try Your First Download

### Option A: Direct Download (Simple Test)

1. Find a test .m3u8 URL (search "sample m3u8 url" online)
2. Paste it in the **Direct Download** box
3. Click **Download Now**
4. Check `/volume1/media/downloads` for your video!

### Option B: Browser Mode (The Cool Feature)

1. Go to any video website (YouTube, Vimeo, etc.)
2. Copy the video page URL
3. Paste it in **Find Link** mode
4. Click **Open Browser & Detect**
5. An embedded Chrome browser appears
6. Play the video
7. Magic! Download starts automatically
8. See the thumbnail confirmation
9. Browser closes after 15 seconds

## 4. Log In Once, Stay Logged In

The next time you visit the same website:

1. Paste any video URL from that site
2. You're already logged in (cookies saved!)
3. Download starts immediately
4. No login required again!

## Common Use Cases

### Download from a Site Requiring Login

```
1. Paste: https://premium-site.com/watch/video123
2. Click "Open Browser & Detect"
3. Log in manually when Chrome opens
4. Navigate to video and play
5. Download starts → Done!

Next video from same site:
1. Paste: https://premium-site.com/watch/video456
2. Click "Open Browser & Detect"
3. Already logged in → Auto-downloads!
```

### Download Multiple Videos

Just repeat the process - each download runs independently!

### Keep Browser Open Longer

When the countdown popup appears, click **Keep Open** instead of letting it auto-close.

## Tips

- **Downloads save to**: `/volume1/media/downloads`
- **Cookies save to**: `/volume2/Dockerssd/video-downloader/chrome-data`
- **Auto-close delay**: 15 seconds (configurable in docker-compose.yml)
- **View logs**: `docker-compose logs -f`

## Troubleshooting

**Browser doesn't appear?**
- Check http://your-nas-ip:6080 directly
- Ensure port 6080 is not blocked

**Stream not detected?**
- Make sure video is playing
- Some protected streams can't be detected
- Try direct download mode instead

**Downloads not appearing?**
- Check volume exists: `/volume1/media/downloads`
- View logs: `docker-compose logs -f`

## Next Steps

- Read [README.md](README.md) for detailed features
- Check [INSTALL.md](INSTALL.md) for advanced setup
- Customize `docker-compose.yml` environment variables

Enjoy your video downloader! 🎬
