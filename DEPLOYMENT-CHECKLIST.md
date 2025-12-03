# Deployment Checklist

Use this checklist to ensure a smooth deployment of your video downloader.

## Pre-Deployment

### System Requirements
- [ ] Docker installed and running
- [ ] Docker Compose installed (if using command line)
- [ ] At least 2GB RAM available
- [ ] At least 10GB free disk space
- [ ] Ports 5000 and 6080 are free

### File Verification
- [ ] All project files extracted/uploaded to NAS
- [ ] docker-compose.yml is present
- [ ] Dockerfile is present
- [ ] app/ directory with app.py exists
- [ ] requirements.txt is present
- [ ] supervisord.conf is present

### Directory Setup
- [ ] Created `downloads/` directory
- [ ] Created `chrome-data/` directory
- [ ] Set correct permissions (755 or rwxr-xr-x)

## Deployment Steps

### Option A: Portainer (Recommended)

- [ ] Logged into Portainer web interface
- [ ] Navigated to Stacks → Add Stack
- [ ] Named stack "video-downloader"
- [ ] Uploaded docker-compose.yml OR pasted contents
- [ ] Clicked "Deploy the stack"
- [ ] Stack shows as "Running" in Portainer

### Option B: Command Line

- [ ] Opened terminal/SSH to NAS
- [ ] Changed to project directory
- [ ] Ran: `docker-compose up -d`
- [ ] Checked status: `docker-compose ps`
- [ ] All containers show "Up"

## Post-Deployment Verification

### Container Health
- [ ] Container is running: `docker ps | grep video-downloader`
- [ ] No error logs: `docker-compose logs --tail=50`
- [ ] All services started (check logs for Xvfb, VNC, noVNC, Flask)

### Network Access
- [ ] Web interface accessible: `http://YOUR-NAS-IP:5000`
- [ ] noVNC accessible: `http://YOUR-NAS-IP:6080`
- [ ] Both ports respond (not connection refused/timeout)

### Functionality Tests

#### Test 1: Web Interface
- [ ] Web page loads correctly
- [ ] Can switch between Direct Download and Find Link modes
- [ ] Forms are visible and interactive

#### Test 2: Direct Download (Optional)
- [ ] Paste a test .m3u8 URL
- [ ] Click "Download Video"
- [ ] Status shows "Starting download..."
- [ ] Check if file appears in ./downloads/

#### Test 3: Browser Mode
- [ ] Paste any webpage URL
- [ ] Click "Open Browser & Detect"
- [ ] noVNC window appears showing Chrome
- [ ] Can see and interact with the webpage

## Configuration (Optional)

### Change Ports
If ports 5000 or 6080 are in use:

- [ ] Edit docker-compose.yml
- [ ] Change port mappings:
  ```yaml
  ports:
    - "5001:5000"  # Use 5001 instead of 5000
    - "6081:6080"  # Use 6081 instead of 6080
  ```
- [ ] Redeploy: `docker-compose up -d`

### Adjust Settings
- [ ] Edit CHROME_TIMEOUT if needed (default: 15 seconds)
- [ ] Edit DEFAULT_QUALITY if needed (default: 1080)
- [ ] Change DOWNLOAD_PATH if needed (default: /downloads)

### Volume Paths
- [ ] Verify downloads location is accessible
- [ ] Ensure chrome-data persists between restarts

## Troubleshooting

### Container Won't Start
- [ ] Check logs: `docker-compose logs`
- [ ] Verify all required files are present
- [ ] Check port conflicts: `netstat -tulpn | grep -E '5000|6080'`
- [ ] Verify Docker has sufficient resources

### Can't Access Web Interface
- [ ] Ping NAS IP from your computer
- [ ] Check firewall rules on NAS
- [ ] Verify container is running: `docker ps`
- [ ] Try accessing from NAS itself: `curl http://localhost:5000`

### Chrome Won't Open
- [ ] Check Xvfb is running in logs
- [ ] Verify x11vnc is running in logs
- [ ] Check shared memory: `docker exec video-downloader df -h /dev/shm`
- [ ] Increase shm_size in docker-compose.yml if needed

### Downloads Fail
- [ ] Check FFmpeg logs in web interface
- [ ] Verify stream URL is accessible
- [ ] Test manually: `docker exec video-downloader ffmpeg -i "URL" test.mp4`
- [ ] Check disk space: `df -h`

### Cookies Not Saving
- [ ] Verify chrome-data volume is mounted
- [ ] Check directory permissions: `ls -la chrome-data/`
- [ ] Ensure container has write access

## Maintenance

### Regular Tasks
- [ ] Monitor disk space in ./downloads/
- [ ] Periodically clean old downloads
- [ ] Check container logs for errors
- [ ] Update Docker images when available

### Updating the Application
- [ ] Stop container: `docker-compose down`
- [ ] Pull latest code (if using Git)
- [ ] Rebuild: `docker-compose build`
- [ ] Start: `docker-compose up -d`

### Backup
- [ ] Backup docker-compose.yml
- [ ] Backup chrome-data/ (if cookies are important)
- [ ] Backup any customized configuration

## Security Checklist

- [ ] Not exposed to internet (local network only)
- [ ] Consider VPN if remote access needed
- [ ] Review cookies stored in chrome-data/
- [ ] Keep Docker and host system updated
- [ ] Monitor access logs periodically

## Performance Optimization

- [ ] Monitor RAM usage: `docker stats video-downloader`
- [ ] Check CPU usage during downloads
- [ ] Verify disk I/O is acceptable
- [ ] Consider SSD for better performance
- [ ] Adjust shm_size if Chrome crashes frequently

## Final Verification

- [ ] Can access web interface from any device on network
- [ ] Direct download mode works
- [ ] Browser mode opens Chrome successfully
- [ ] Can log into test site and cookies persist
- [ ] Downloads complete successfully
- [ ] Thumbnails appear in browser mode
- [ ] Countdown timer works
- [ ] Downloaded files are accessible in ./downloads/

## Support Resources

If issues persist:

1. Review logs: `docker-compose logs -f`
2. Check TROUBLESHOOTING section in README.md
3. Run test script: `./test-setup.sh`
4. Review TECHNICAL.md for architecture details
5. Check GitHub issues (if repository is public)

## Success Criteria

✅ Container running without errors
✅ Web interface accessible
✅ Can download direct URLs
✅ Browser mode opens Chrome
✅ Cookies persist between sessions
✅ Downloads complete successfully

## Deployment Complete! 🎉

Once all items are checked, your video downloader is ready for production use!

---

**Date Deployed:** _______________
**Deployed By:** _______________
**NAS IP Address:** _______________
**Notes:** 
_______________________________________________
_______________________________________________
_______________________________________________
