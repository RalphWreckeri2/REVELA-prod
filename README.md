# REVELA — Production Deployment Guide
### A Geospatial Business Intelligence System for Compliance Monitoring and Non-Registered Business Detection
**Municipality of Mataasnakahoy, Batangas — BPLO Deployment**

> ⚠️ This is the **production README**. For local development setup, see the [Development README](./README.md).

---

## Production Architecture Overview

```
Internet
    │
    ▼
[ Nginx Reverse Proxy ]          ← handles HTTPS, rate limiting, static files
    │
    ├──▶ [ Flask (Gunicorn) ]    ← REST API + Analytics Engine   :8000
    │         │
    │         ▼
    │    [ MySQL 8.x ]           ← Central business registry database
    │
    └──▶ [ React.js Build ]      ← Admin Web Dashboard (static files served by Nginx)

[ Flutter APK ]                  ← Field Inspection Tool (sideloaded on Android devices)
    │
    └──▶ calls Flask API via HTTPS
```

---

## Server Requirements

### Minimum Recommended Specs (VPS or On-Premise)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| CPU | 2 vCPU | 4 vCPU |
| RAM | 2 GB | 4 GB |
| Storage | 20 GB SSD | 40 GB SSD |
| Network | Stable broadband | Stable broadband with static IP |

### Client Devices

| Device | Requirement |
|--------|-------------|
| BPLO Admin (Web) | Any modern browser (Chrome 100+, Edge 100+) |
| Field Inspector (Mobile) | Android 10.0+ smartphone, GPS + Camera enabled |

---

## Prerequisites on the Server

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.13
sudo apt install python3.13 python3.13-venv python3-pip -y

# Install MySQL 8
sudo apt install mysql-server -y
sudo mysql_secure_installation

# Install Nginx
sudo apt install nginx -y

# Install Node.js 20 LTS (for building the React frontend)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs -y

# Install Gunicorn
pip install gunicorn
```

---

## Backend Deployment (Flask + Gunicorn)

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/revela-backend.git
cd revela-backend
```

### 2. Set up virtual environment and install dependencies

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure production environment variables

```bash
cp .env.example .env
nano .env
```

Set the following — **use strong, unique values for production**:

```env
FLASK_APP=app.py
FLASK_ENV=production
FLASK_DEBUG=0

DB_HOST=localhost
DB_PORT=3306
DB_NAME=revela_db
DB_USER=revela_user
DB_PASSWORD=STRONG_PASSWORD_HERE

JWT_SECRET_KEY=LONG_RANDOM_STRING_64_CHARS_MINIMUM

GOOGLE_MAPS_API_KEY=your_production_api_key_here

SMS_GATEWAY_API_KEY=your_gateway_key_here
SMS_GATEWAY_SENDER=REVELA
```

> ⚠️ In production, set `FLASK_DEBUG=0`. Debug mode exposes internal error details to the public.

**Generate a strong JWT secret:**
```bash
python3 -c "import secrets; print(secrets.token_hex(64))"
```

### 4. Set up the MySQL production database

```bash
sudo mysql -u root -p
```

```sql
CREATE DATABASE revela_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'revela_user'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD_HERE';
GRANT ALL PRIVILEGES ON revela_db.* TO 'revela_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

Run migration scripts in foreign key dependency order:

```bash
mysql -u revela_user -p revela_db < migrations/01_barangays.sql
mysql -u revela_user -p revela_db < migrations/02_users.sql
mysql -u revela_user -p revela_db < migrations/03_user_password_resets.sql
mysql -u revela_user -p revela_db < migrations/04_official_registry.sql
mysql -u revela_user -p revela_db < migrations/05_geospatial_logs.sql
mysql -u revela_user -p revela_db < migrations/06_inspection_reports.sql
```

Seed the 16 barangays of Mataasnakahoy:

```bash
mysql -u revela_user -p revela_db < data/seed_barangays.sql
```

### 5. Run Flask with Gunicorn

```bash
gunicorn --workers 3 --bind 0.0.0.0:8000 app:app
```

> **Worker count formula:** `(2 × CPU cores) + 1`. For a 2-core server use 5 workers.

### 6. Set up Gunicorn as a systemd service (runs on startup)

```bash
sudo nano /etc/systemd/system/revela.service
```

Paste the following:

```ini
[Unit]
Description=REVELA Flask Backend
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/revela-backend
Environment="PATH=/home/ubuntu/revela-backend/venv/bin"
ExecStart=/home/ubuntu/revela-backend/venv/bin/gunicorn --workers 3 --bind unix:revela.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl start revela
sudo systemctl enable revela
sudo systemctl status revela
```

---

## Frontend Deployment (React.js)

### 1. Build the production bundle

```bash
cd revela-web
npm install
npm run build
```

This produces a `/build` folder of optimized static files.

### 2. Copy build to Nginx web root

```bash
sudo cp -r build/* /var/www/revela/
```

---

## Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/revela
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    # Serve React frontend
    root /var/www/revela;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to Flask/Gunicorn
    location /api/ {
        proxy_pass http://unix:/home/ubuntu/revela-backend/revela.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/revela /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Enable HTTPS with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

Certbot auto-renews. Confirm with:
```bash
sudo certbot renew --dry-run
```

---

## Mobile App Deployment (Flutter APK)

The REVELA mobile app is distributed as an internal APK — it is **not published to the Google Play Store**.

### Build the release APK

```bash
cd revela-mobile

# Update the API base URL to your production server before building
# In lib/config/constants.dart:
# const String BASE_URL = 'https://your-domain.com/api';

flutter build apk --release
```

Output: `build/app/outputs/flutter-apk/app-release.apk`

### Distribute to field inspectors

1. Share the APK file directly to the inspector's Android device via USB, Google Drive, or messaging app
2. On the Android device, enable **Install from Unknown Sources**: Settings → Security → Unknown Sources → Enable
3. Open the APK file on the device and install
4. Grant permissions on first launch: **Location (Always)**, **Camera**, **Storage**

> ⚠️ The APK must be rebuilt and redistributed manually whenever the API URL or core logic changes. Maintain an internal version log.

---

## Google Maps API — Production Restrictions

Before going live, restrict your Google Maps API key to prevent unauthorized use and unexpected billing:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Click your API key → Edit
3. Under **Application restrictions**:
   - Web Dashboard key: restrict to **HTTP referrers** → add `https://your-domain.com/*`
   - Android key: restrict to **Android apps** → add your app's SHA-1 certificate fingerprint
4. Under **API restrictions**: restrict to only the APIs REVELA uses:
   - Maps JavaScript API
   - Places API
   - Geocoding API
   - Maps SDK for Android
5. Set a **daily quota limit** in Google Cloud to cap usage costs

---

## Database Backup

Set up automated nightly backups:

```bash
# Create backup script
sudo nano /home/ubuntu/backup-revela.sh
```

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
mysqldump -u revela_user -p'STRONG_PASSWORD_HERE' revela_db > /home/ubuntu/backups/revela_$DATE.sql
# Keep only last 30 days
find /home/ubuntu/backups/ -name "*.sql" -mtime +30 -delete
```

```bash
chmod +x /home/ubuntu/backup-revela.sh
mkdir /home/ubuntu/backups

# Schedule nightly at 2:00 AM
crontab -e
# Add: 0 2 * * * /home/ubuntu/backup-revela.sh
```

---

## Production Security Checklist

```
☐ FLASK_DEBUG=0 in .env
☐ Strong, unique DB_PASSWORD (16+ characters, mixed case, symbols)
☐ JWT_SECRET_KEY is 64+ character random hex string
☐ .env file permissions set to 600: chmod 600 .env
☐ Google Maps API key restricted to REVELA domains and apps only
☐ Daily quota cap set on Google Maps API
☐ HTTPS enabled via Let's Encrypt
☐ MySQL root account has a strong password
☐ revela_user has no SUPER or GLOBAL privileges
☐ Automated nightly database backup configured
☐ Nginx rate limiting configured for /api/ routes
☐ Firewall configured — only ports 80, 443, and 22 open
```

---

## Monitoring

Check service health at any time:

```bash
# Flask/Gunicorn status
sudo systemctl status revela

# Nginx status
sudo systemctl status nginx

# MySQL status
sudo systemctl status mysql

# View Flask application logs
sudo journalctl -u revela -f

# View Nginx access logs
sudo tail -f /var/log/nginx/access.log
```

---

## Updating the Production System

```bash
# Pull latest code
cd revela-backend
git pull origin main

# Install any new dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart Flask
sudo systemctl restart revela

# If frontend changed — rebuild and redeploy
cd revela-web
npm install
npm run build
sudo cp -r build/* /var/www/revela/
sudo systemctl restart nginx
```

---

## Support

For technical issues during the evaluation phase, contact the development team:

| Name | Role | Contact |
|------|------|---------|
| Anoya, R. F. | Frontend / API Integration | — |
| Levita, R. A. | Database / Mobile | — |
| Samonte, R. M. A. | Backend / Analytics Engine | — |

**Institution:** Batangas State University — The National Engineering University, Lipa Campus
**Deployed for:** Municipality of Mataasnakahoy BPLO, Batangas
