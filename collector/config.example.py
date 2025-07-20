#!/usr/bin/env python3
"""
Meshtastic Bridge Collector - Configuration Template
Copy this file to config.py and update with your settings
"""

# Database Configuration
DATABASE_CONFIG = {
    'host': 'localhost',           # SSH tunnel endpoint (usually localhost if using tunnel)
    'port': 5432,                 # SSH tunnel port (usually 5432)
    'database': 'meshtastic',     # Your TimescaleDB database name
    'user': 'postgres',           # Your database username
    'password': 'YOUR_DATABASE_PASSWORD_HERE'  # ⚠️  UPDATE THIS
}

# Meshtastic Device Configuration
DEVICE_CONFIG = {
    'path': '/dev/ttyACM0',       # USB device path - update if different
    'baud_rate': None,            # None = auto-detect, or specify (e.g., 921600)
}

# SSH Tunnel Configuration (if using remote database)
SSH_TUNNEL_CONFIG = {
    'enabled': True,              # Set to False if database is local
    'remote_host': 'your-database-server.com',  # ⚠️  UPDATE THIS
    'remote_user': 'your-username',             # ⚠️  UPDATE THIS
    'ssh_key_path': '/root/.ssh/meshtastic_tunnel',  # SSH private key path
    'local_port': 5432,           # Local tunnel port
    'remote_port': 5432,          # Remote database port
}

# Logging Configuration
LOGGING_CONFIG = {
    'level': 'INFO',              # DEBUG, INFO, WARNING, ERROR
    'file_path': '/var/log/meshtastic-collector.log',
    'max_file_size': '10MB',      # Log rotation size
    'backup_count': 5,            # Number of backup log files
}

# Bridge Node Configuration
BRIDGE_CONFIG = {
    'node_name': 'YOUR-BRIDGE-NAME',    # ⚠️  UPDATE: Your bridge node name
    'location': 'YOUR-LOCATION',           # ⚠️  UPDATE: Your location
    'operator': 'Your-Callsign',         # ⚠️  UPDATE: Your amateur radio callsign
}

# Performance Settings
PERFORMANCE_CONFIG = {
    'bulk_check_interval': 60,    # Seconds between bulk node checks
    'stats_interval': 60,         # Seconds between stats logging
    'max_bulk_checks': 20,        # Max nodes to check per bulk cycle
    'connection_retry_delay': 15, # Seconds to wait before reconnection
}

# Feature Toggles
FEATURES = {
    'direct_nodeinfo_processing': True,   # Enable direct NODEINFO parsing
    'bulk_node_checking': True,           # Enable periodic bulk node checks
    'position_tracking': True,            # Track and store GPS positions
    'telemetry_processing': True,         # Process telemetry packets
}

# Advanced Configuration
ADVANCED_CONFIG = {
    'debug_payload_parsing': False,       # Enable detailed payload debug logs
    'packet_size_limit': 1024,           # Max packet size to process (bytes)
    'node_cleanup_enabled': False,       # Enable automatic cleanup of old temp nodes
    'node_cleanup_days': 30,             # Days after which to clean temp nodes
}
