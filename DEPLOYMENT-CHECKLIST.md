# Deployment Checklist

Use this checklist when deploying to your NAS for the first time.

## Pre-Deployment

### 1. GitHub Repository Setup

- [ ] Create new GitHub repository
- [ ] Add repository description: "Self-hosted video downloader for NAS with browser-based authentication"
- [ ] Set repository to Public (or Private if preferred)
- [ ] Initialize with README (optional, will be overwritten)

### 2. Local Repository Setup

```bash
# Initialize git
cd ffmepg-downloader
git init

# Add all files
git add .

# Initial commit
git commit -m "Initial commit - NAS video downloader"

# Link to GitHub
git remote add origin https://github.com/YOUR_USERNAME/nas-video-downloader.git
git branch -M main
git push -u origin main
```

- [ ] Repository pushed to GitHub
- [ ] Verify all files visible on GitHub

### 3. NAS Prerequisites

Check your UGREEN NAS setup:

- [ ] Docker installed and running
- [ ] Portainer installed and accessible
- [ ] SSH access available (optional but recommended)
- [ ] Sufficient storage space:
  - [ ] At least 50GB free on /volume1 (HDD)
  - [ ] At least 5GB free on /volume2 (SSD)

### 4. Volume Preparation

Via SSH or File Manager:

- [ ] Create `/volume1/media/downloads` directory
- [ ] Create `/volume2/Dockerssd/video-downloader` directory
- [ ] Verify write permissions on both directories
- [ ] Test write access: `touch /volume1/media/downloads/test.txt`

### 5. Port Availability

Check ports are not in use:

```bash
# Check port 5000
netstat -tuln | grep :5000

# Check port 6080
netstat -tuln | grep :6080
```

- [ ] Port 5000 available
- [ ] Port 6080 available
- [ ] If ports in use, plan to modify docker-compose.yml

## Deployment via Portainer

### 6. Stack Creation

- [ ] Open Portainer web interface
- [ ] Navigate to **Stacks**
- [ ] Click **Add Stack**
- [ ] Enter stack name: `video-downloader`

### 7. Repository Configuration

- [ ] Select **Repository** build method
- [ ] Enter repository URL: `https://github.com/YOUR_USERNAME/nas-video-downloader`
- [ ] Repository reference: `refs/heads/main`
- [ ] Compose path: `docker-compose.yml`
- [ ] Authentication: None (if public repo)

### 8. Environment Variables (Optional)

Add custom variables if needed:

- [ ] `AUTO_CLOSE_DELAY=15` (or custom value)
- [ ] Other environment variables as needed

### 9. Deploy

- [ ] Click **Deploy the stack**
- [ ] Wait for deployment to complete
- [ ] Check for any error messages

## Post-Deployment Verification

### 10. Container Health

- [ ] Stack shows status: "running" in Portainer
- [ ] Check container logs for errors:
  ```bash
  docker logs nas-video-downloader
  ```
- [ ] No critical errors in logs

### 11. Service Accessibility

- [ ] Web interface loads: `http://YOUR_NAS_IP:5000`
- [ ] noVNC loads: `http://YOUR_NAS_IP:6080/vnc.html`
- [ ] Both services respond without errors

### 12. Functional Testing

#### Direct Download Test

- [ ] Open web interface
- [ ] Find a test .m3u8 URL (search online for "sample m3u8 stream")
- [ ] Paste in Direct Download section
- [ ] Click "Download Now"
- [ ] Check download starts without errors
- [ ] Verify file appears in `/volume1/media/downloads/`
- [ ] Check file is not corrupted (can be played)

#### Browser Mode Test

- [ ] Open web interface
- [ ] Paste any video website URL
- [ ] Click "Open Browser & Detect"
- [ ] Embedded Chrome browser appears
- [ ] Can interact with the browser
- [ ] Try playing a video
- [ ] Check if stream is detected

### 13. Volume Verification

- [ ] Downloads appear in `/volume1/media/downloads/`
- [ ] Chrome data created in `/volume2/Dockerssd/video-downloader/chrome-data/`
- [ ] Logs created in `/volume2/Dockerssd/video-downloader/logs/`
- [ ] File permissions correct (can read/write)

### 14. Cookie Persistence Test

- [ ] Visit a site requiring login
- [ ] Log in manually via browser mode
- [ ] Complete a download
- [ ] Close browser
- [ ] Start new browser session to same site
- [ ] Verify already logged in (cookies persisted)

## Troubleshooting

### Container Won't Start

- [ ] Check Docker daemon status
- [ ] Verify volume paths exist
- [ ] Check port conflicts
- [ ] Review container logs
- [ ] Try: `docker-compose down && docker-compose up -d --build`

### Web Interface Not Loading

- [ ] Ping NAS IP from your device
- [ ] Check firewall rules on NAS
- [ ] Verify port 5000 not blocked
- [ ] Check Flask logs: `docker logs nas-video-downloader | grep flask`

### Browser Not Appearing

- [ ] Check port 6080 accessible
- [ ] Verify Xvfb running: `docker exec nas-video-downloader ps aux | grep Xvfb`
- [ ] Check x11vnc logs: `docker exec nas-video-downloader cat /app/logs/x11vnc.log`
- [ ] Try accessing noVNC directly: `http://YOUR_NAS_IP:6080/vnc.html`

### Downloads Not Saving

- [ ] Check volume mount: `docker inspect nas-video-downloader | grep Mounts -A 20`
- [ ] Verify directory exists: `ls -la /volume1/media/downloads`
- [ ] Check permissions: `docker exec nas-video-downloader ls -la /app/downloads`
- [ ] Check disk space: `df -h`

### Stream Not Detected

- [ ] Ensure video is playing in browser
- [ ] Check browser console for errors
- [ ] Some sites use DRM (can't be downloaded)
- [ ] Try direct download mode instead
- [ ] Check Flask logs for detection attempts

## Security Hardening (Optional)

- [ ] Change default ports in docker-compose.yml
- [ ] Add authentication to Flask (custom implementation needed)
- [ ] Set up reverse proxy with SSL (nginx/Caddy)
- [ ] Restrict access to local network only
- [ ] Regular backups of chrome-data (for cookies)

## Maintenance Tasks

Set up regular maintenance:

- [ ] Weekly: Check disk space
- [ ] Weekly: Review logs for errors
- [ ] Monthly: Update container: `docker-compose pull && docker-compose up -d`
- [ ] Monthly: Clean old downloads
- [ ] Quarterly: Backup chrome-data directory

## Documentation

- [ ] Bookmark web interface URL
- [ ] Save NAS access credentials securely
- [ ] Document any custom configurations made
- [ ] Share access instructions with household members

## Completion

- [ ] All checklist items completed
- [ ] System running smoothly for 24 hours
- [ ] At least one successful download completed
- [ ] No errors in logs
- [ ] Cookie persistence verified

## Rollback Plan

If something goes wrong:

```bash
# Stop and remove container
docker-compose down

# Remove volumes (careful!)
rm -rf /volume2/Dockerssd/video-downloader

# Redeploy from scratch
# Follow checklist from step 6
```

---

**Deployment Date**: _______________

**Deployed By**: _______________

**NAS IP**: _______________

**Notes**:
_______________________________________________
_______________________________________________
_______________________________________________
