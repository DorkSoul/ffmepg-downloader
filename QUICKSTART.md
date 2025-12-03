# Quick Start Guide

Get your video downloader running in 5 minutes!

## For Portainer Users (Easiest)

### 1. Upload to your NAS
- Download/clone this repository to your NAS
- Or use Git: `git clone <your-repo-url>`

### 2. Open Portainer
- Navigate to **Stacks** → **Add Stack**

### 3. Deploy
- Name: `video-downloader`
- Build method: **Upload** → select `docker-compose.yml`
- Click **Deploy the stack**

### 4. Done!
- Access at: `http://your-nas-ip:5000`
- VNC at: `http://your-nas-ip:6080`

## For Command Line Users

```bash
# 1. Navigate to project directory
cd /path/to/video-downloader

# 2. Create required directories
mkdir -p downloads chrome-data

# 3. Deploy
docker-compose up -d

# 4. Check status
docker-compose logs -f
```

## First Use

### Direct Download Mode
1. Select **Direct Download**
2. Paste your video URL (e.g., `.m3u8` link)
3. Choose quality
4. Click **Download Video**

### Browser Mode (For Sites Requiring Login)
1. Select **Find Link**
2. Paste the webpage URL
3. Chrome opens in the browser window
4. Log in if needed (cookies saved automatically!)
5. Play the video
6. App detects stream and starts downloading
7. See thumbnail confirmation
8. Chrome closes after 15 seconds

## What You'll See

**Direct Download:**
- Status updates as download progresses
- Completion notification
- Files saved to `./downloads/`

**Browser Mode:**
- Chrome window embedded in page (via noVNC)
- Login if needed (first time only)
- Popup with video thumbnail when download starts
- "Closing in 15 seconds" countdown
- Options to close now or keep open

## Configuration

Edit `docker-compose.yml` to customize:

```yaml
environment:
  - CHROME_TIMEOUT=15    # Seconds before auto-close
  - DEFAULT_QUALITY=1080 # Preferred quality
  - DOWNLOAD_PATH=/downloads
```

## Troubleshooting

**Ports already in use?**
- Change `5000:5000` to `5001:5000` (use port 5001)
- Change `6080:6080` to `6081:6080` (use port 6081)

**Container won't start?**
```bash
docker-compose logs video-downloader
```

**Need to restart?**
```bash
docker-compose restart
```

**Need to stop?**
```bash
docker-compose down
```

## Where Are My Videos?

Downloaded videos are saved to: `./downloads/`

## Tips

- **First-time logins**: The browser mode saves cookies, so you only need to log in once per site
- **Stream detection**: Works best with standard video players (HTML5, JWPlayer, etc.)
- **Quality**: The app tries to download the closest match to your preference
- **DRM content**: Cannot download DRM-protected videos (Netflix, Disney+, etc.)

## Next Steps

- Read [INSTALL.md](INSTALL.md) for detailed setup
- Read [README.md](README.md) for full documentation
- Check [CHANGELOG.md](CHANGELOG.md) for version history

## Need Help?

Run the test script first:
```bash
./test-setup.sh
```

This checks your setup and identifies any issues.

---

**Enjoy your new video downloader!** 🎬
