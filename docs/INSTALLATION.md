# Installation Guide

## Prerequisites

### Hardware Requirements
- Meshtastic device connected via USB
- Linux system (Debian/Ubuntu recommended)
- Minimum 512MB RAM, 1GB storage

### Software Requirements
- Python 3.8+
- PostgreSQL or TimescaleDB database
- SSH access (if using remote database)

## Step 1: System Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3 python3-pip python3-venv git curl autossh postgresql-client

# Add user to dialout group (for USB device access)
sudo usermod -a -G dialout $USER
# Log out and back in for group changes to take effect
```

## Step 2: Clone Repository

```bash
# Clone the repository
cd /opt
sudo git clone https://github.com/yourusername/meshtastic-bridge-collector.git
sudo chown -R $USER:$USER meshtastic-bridge-collector
cd meshtastic-bridge-collector
```

## Step 3: Python Environment Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

## Step 4: Database Setup

### Option A: Local PostgreSQL

```bash
# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql << EOF
CREATE DATABASE meshtastic;
CREATE USER meshtastic_collector WITH PASSWORD 'your_password_here';
GRANT ALL PRIVILEGES ON DATABASE meshtastic TO meshtastic_collector;
\q
EOF

# Import schema
psql -h localhost -U meshtastic_collector -d meshtastic -f sql/schema.sql
```

### Option B: Remote TimescaleDB

```bash
# Import schema to remote database
psql -h your-remote-host -U your-user -d meshtastic -f sql/schema.sql
```

## Step 5: SSH Tunnel Setup (Remote Database Only)

```bash
# Generate SSH key pair
ssh-keygen -t rsa -b 4096 -f ~/.ssh/meshtastic_tunnel -N ""

# Copy public key to remote server
ssh-copy-id -i ~/.ssh/meshtastic_tunnel.pub your-user@your-remote-host

# Test SSH connection
ssh -i ~/.ssh/meshtastic_tunnel your-user@your-remote-host

# Copy keys to root (for systemd service)
sudo cp ~/.ssh/meshtastic_tunnel* /root/.ssh/
sudo chown root:root /root/.ssh/meshtastic_tunnel*
sudo chmod 600 /root/.ssh/meshtastic_tunnel
```

## Step 6: Configuration

```bash
# Copy and edit configuration
cp collector/config.example.py collector/config.py
nano collector/config.py
```

### Required Configuration Changes

Edit `collector/config.py` and update:

```python
# Database settings
DATABASE_CONFIG = {
    'host': 'localhost',                    # or remote host IP
    'port': 5432,
    'database': 'meshtastic',
    'user': 'meshtastic_collector',
    'password': 'your_actual_password'      # ⚠️ UPDATE THIS
}

# Device settings
DEVICE_CONFIG = {
    'path': '/dev/ttyACM0',                 # ⚠️ UPDATE if different
}

# SSH tunnel (if using remote database)
SSH_TUNNEL_CONFIG = {
    'enabled': True,                        # Set False for local DB
    'remote_host': 'your-database-host.com', # ⚠️ UPDATE THIS
    'remote_user': 'your-username',         # ⚠️ UPDATE THIS
}

# Bridge identification
BRIDGE_CONFIG = {
    'node_name': 'Bridge-Node-YourLocation', # ⚠️ UPDATE THIS
    'location': 'Your City, State',         # ⚠️ UPDATE THIS
    'operator': 'Your-Callsign',            # ⚠️ UPDATE THIS
}
```

## Step 7: Device Detection

```bash
# Find your Meshtastic device
ls -la /dev/ttyACM* /dev/ttyUSB*

# Check device permissions
ls -la /dev/ttyACM0

# Test device connection
python3 -c "
import meshtastic.serial_interface
try:
    interface = meshtastic.serial_interface.SerialInterface('/dev/ttyACM0')
    info = interface.getMyNodeInfo()
    print(f'Device found: {info}')
    interface.close()
except Exception as e:
    print(f'Device test failed: {e}')
"
```

## Step 8: Test Installation

```bash
# Activate virtual environment
source venv/bin/activate

# Test collector manually
python3 collector/meshtastic-collector.py
```

Look for:
- ✅ "Database connected"
- ✅ "Meshtastic connected"
- ✅ "Collection started"
- ✅ Packet reception logs

Press `Ctrl+C` to stop the test.

## Step 9: Production Deployment

### Install Systemd Services

```bash
# Copy service files
sudo cp systemd/meshtastic-tunnel.service /etc/systemd/system/
sudo cp systemd/meshtastic-collector.service /etc/systemd/system/

# Edit service files with correct paths
sudo nano /etc/systemd/system/meshtastic-tunnel.service
# Update: YOUR_DATABASE_USER@YOUR_DATABASE_HOST

sudo nano /etc/systemd/system/meshtastic-collector.service  
# Update: WorkingDirectory and ExecStart paths

# Reload systemd
sudo systemctl daemon-reload

# Enable and start services
sudo systemctl enable meshtastic-tunnel meshtastic-collector
sudo systemctl start meshtastic-tunnel
sudo systemctl start meshtastic-collector
```

### Verify Services

```bash
# Check service status
sudo systemctl status meshtastic-tunnel
sudo systemctl status meshtastic-collector

# Monitor logs
sudo journalctl -u meshtastic-collector -f

# Check for successful packet collection
sudo journalctl -u meshtastic-collector | grep "Stored packet"
```

## Step 10: Monitoring

### Log Files
- Service logs: `sudo journalctl -u meshtastic-collector`
- Application logs: `/var/log/meshtastic-collector.log`

### Database Queries
```sql
-- Check recent activity
SELECT COUNT(*) FROM mesh_packet_metrics 
WHERE time > NOW() - INTERVAL '1 hour';

-- View node statistics
SELECT * FROM node_statistics LIMIT 10;

-- Check mesh health
SELECT * FROM mesh_health;
```

### Performance Monitoring
```bash
# Watch real-time stats
sudo journalctl -u meshtastic-collector -f | grep "Stats -"

# Monitor NODEINFO updates
sudo journalctl -u meshtastic-collector -f | grep "🎉"
```

## Troubleshooting

### Common Issues

1. **Device not found**: Check USB connection and permissions
2. **Database connection failed**: Verify credentials and network
3. **Permission denied**: Ensure user is in dialout group
4. **SSH tunnel fails**: Check SSH key setup and remote access

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed solutions.

## Next Steps

- Set up Grafana dashboards for visualization
- Configure alerting for system health
- Consider deploying multiple bridge nodes for coverage
- Join the Meshtastic community!

## Support

- GitHub Issues: Report bugs and feature requests
- Community: Join the NSW Meshtastic network
- Documentation: Read additional guides in `/docs`
