# Meshtastic Bridge Collector v1.3.2 - NODEINFO Bytes & Hex Parsing Hotfix
#!/usr/bin/env python3
"""
Meshtastic Data Collector - Version 3.6 - Database Resilience Update
Sydney Bridge Node Implementation for NSW Mesh Network

NEW IN v3.6:
- Robust database connection with automatic reconnection ✅
- Connection pooling for improved reliability ✅
- Exponential backoff retry logic ✅
- Better error handling for connection drops ✅

FIXED IN v3.5 Final:
- Direct NODEINFO payload parsing (fixes temp node issue) ✅
- Fixed bulk check node ID conversion (hex to int) ✅
- Multiple payload format support ✅
- Immediate database updates from NODEINFO packets ✅
- Better debug logging for payload inspection ✅

Features:
- Real-time packet capture via LoRa interface
- Official Meshtastic portnum compliance
- Intelligent node discovery and updates
- Complete database schema compatibility
- UTC timestamp handling
- Production-ready error handling and logging
- Self-healing connections with auto-restart
- Database connection resilience with automatic retry

Database: TimescaleDB via SSH tunnel
Device: /dev/ttyACM0 (Meshtastic device)
"""

import meshtastic.serial_interface
import psycopg2
from datetime import datetime, timezone
import time
import logging
import signal
import sys
from pubsub import pub
import os
import sys

# Add the parent directory to the path to import our robust DB connection
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import RobustDBConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/meshtastic-collector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MeshtasticCollector:
    def __init__(self):
        self.running = False
        self.interface = None
        self.db = None  # Changed from db_conn to db (RobustDBConnection instance)
        
        # Database configuration - now handled by RobustDBConnection
        self.db_config = {
            'host': 'localhost',       # SSH tunnel endpoint
            'port': 5432,              # SSH tunnel port
            'database': 'meshtastic',  # UPDATE: Your database name
            'user': 'postgres',        # UPDATE: Your database user
            'password': 'p4ZwvXvkBBhlFcb1pOWRkDxbx'  # UPDATE: Your password
        }
        
        # Statistics tracking
        self.stats = {
            'received': 0,
            'stored': 0,
            'errors': 0,
            'nodes_created': 0,
            'nodes_updated': 0,
            'nodeinfo_triggers': 0,
            'direct_updates': 0,
            'pending': 0
        }
        
        # Setup Meshtastic event handlers
        pub.subscribe(self.on_receive, "meshtastic.receive")
        pub.subscribe(self.on_connection, "meshtastic.connection")
        
        self.start_time = datetime.now()

    def create_or_update_node_from_nodeinfo(self, node_id, decoded_payload):
        """Create or update node from NODEINFO payload with robust database connection"""
        try:
            # Extract node information from payload
            # FIX v1.3.2: Handle bytes payload
            if isinstance(decoded_payload, bytes):
                logger.info(f"NODEINFO payload for {node_id} is bytes - creating minimal entry")
                # Create minimal node entry
                query = '''
                INSERT INTO node_details (node_id, long_name, short_name, hardware_model, role, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (node_id) DO UPDATE SET updated_at = NOW()
                '''
                success = self.db.execute_with_retry(query, (node_id, f"Node {node_id}", f"N{str(node_id)[-4:]}", "UNKNOWN", "CLIENT"))
                if success:
                    self.stats['nodes_updated'] += 1
                    logger.info(f"Created minimal entry for node {node_id}")
                return success
            
            long_name = decoded_payload.get('longName', 'Unknown')
            short_name = decoded_payload.get('shortName', 'Unknown')
            hardware_model = decoded_payload.get('hw', 'Unknown')
            role_value = decoded_payload.get('role', 0)  # Default to CLIENT (0)
            
            # Convert role number to name using our mapping function
            if isinstance(role_value, int):
                role = self.get_role_name(role_value)
            else:
                role = str(role_value) if role_value else 'CLIENT'
            
            # Convert hardware model number to name if needed
            if isinstance(hardware_model, int):
                hardware_model = self.get_hardware_name(hardware_model)
            
            logger.info(f"Processing NODEINFO for {node_id}: {long_name} ({short_name}) - {hardware_model}")
            
            # Use robust database connection with retry logic
            query = """
            INSERT INTO node_details (node_id, long_name, short_name, hardware_model, role, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (node_id) DO UPDATE SET
                long_name = EXCLUDED.long_name,
                short_name = EXCLUDED.short_name,
                hardware_model = EXCLUDED.hardware_model,
                role = EXCLUDED.role,
                last_seen = NOW()
            """
            
            success = self.db.execute_with_retry(query, (node_id, long_name, short_name, hardware_model, role))
            
            if success:
                self.stats['nodes_updated'] += 1
                self.stats['direct_updates'] += 1
                logger.info(f"Successfully updated node {node_id} with name: {long_name}")
                return True
            else:
                logger.error(f"Failed to update node {node_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating node {node_id}: {e}")
            self.stats['errors'] += 1
            return False

    def store_packet_metrics(self, packet_data):
        """Store packet metrics with robust database connection"""
        try:
            query = """
            INSERT INTO mesh_packet_metrics (
                time, source_id, destination_id, portnum, packet_id, channel,
                rx_time, rx_snr, rx_rssi, hop_limit, hop_start, want_ack, via_mqtt, message_size_bytes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
            
            success = self.db.execute_with_retry(query, packet_data)
            
            if success:
                self.stats['stored'] += 1
                return True
            else:
                self.stats['errors'] += 1
                return False
                
        except Exception as e:
            logger.error(f"Error storing packet metrics: {e}")
            self.stats['errors'] += 1
            return False

    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        """Handle Meshtastic connection events"""
        logger.info(f"Connection event: {topic}")

    def connect(self):
        """Connect to database using robust connection"""
        try:
            # Initialize robust database connection
            self.db = RobustDBConnection(**self.db_config)
            logger.info("Robust database connection established")
            
            # Connect to Meshtastic device
            self.interface = meshtastic.serial_interface.SerialInterface('/dev/ttyACM0')
            my_info = self.interface.getMyNodeInfo()
            logger.info(f"Meshtastic connected: {my_info.get('user', {}).get('longName', 'Unknown')}")
            
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def on_receive(self, packet, interface):
        """Handle received Meshtastic packets with improved error handling"""
        try:
            self.stats['received'] += 1
            
            from_node = packet.get('fromId')
            to_node = packet.get('toId') 
            decoded = packet.get('decoded', {})
            portnum = decoded.get('portnum', 'UNKNOWN_APP')
            
            # Log basic packet info
            logger.info(f"Received packet from {from_node} to {to_node} (SNR: {packet.get('rxSnr', 'N/A')}, RSSI: {packet.get('rxRssi', 'N/A')})")
            
            # Convert node IDs to integers for database storage
            source_id = int(from_node.lstrip('!'), 16) if isinstance(from_node, str) and from_node.startswith('!') else None
            # Handle broadcast and hex node IDs
            if to_node == '^all':
                dest_id = '4294967295'  # Broadcast address
            elif isinstance(to_node, str) and to_node.startswith('!'):
                dest_id = str(int(to_node.lstrip('!'), 16))
            else:
                dest_id = None
            
            if source_id is None:
                logger.warning(f"Could not parse source node ID: {from_node}")
                return
            
            # Handle NODEINFO packets for immediate node updates
            if portnum == 'NODEINFO_APP':
                self.stats['nodeinfo_triggers'] += 1
                payload = decoded.get('payload')
                if payload:
                    logger.info(f"Processing NODEINFO payload for node {source_id}")
                    self.create_or_update_node_from_nodeinfo(source_id, payload)
            
            # Store packet metrics
            packet_data = (
                datetime.now(timezone.utc),  # time
                source_id,                   # source_id
                dest_id,                     # destination_id  
                portnum,                     # portnum
                packet.get('id', 0),         # packet_id
                packet.get('channel', 0),    # channel
                packet.get('rxTime', 0),     # rx_time
                packet.get('rxSnr'),         # rx_snr
                packet.get('rxRssi'),        # rx_rssi
                decoded.get('hopLimit'),     # hop_limit
                decoded.get('hopStart'),     # hop_start
                decoded.get('wantAck', False), # want_ack
                False,                       # via_mqtt (this is bridge data)
                len(str(packet))             # message_size_bytes
            )
            
            self.store_packet_metrics(packet_data)
            
        except Exception as e:
            logger.error(f"Error processing packet: {e}")
            self.stats['errors'] += 1

    def get_hardware_name(self, hw_model):
        """Convert hardware model number to readable name"""
        # Hardware model mapping - add more as needed
        hardware_map = {
            0: "UNSET",
            1: "TLORA_V2", 
            2: "TLORA_V1",
            3: "TLORA_V2_1_1P6",
            4: "TBEAM",
            5: "HELTEC_V2_0",
            6: "TBEAM_V0P7",
            7: "T_ECHO",
            8: "TLORA_V1_1P3",
            9: "RAK4631",
            10: "HELTEC_V2_1",
            # Add more mappings as discovered
        }
        return hardware_map.get(hw_model, f"UNKNOWN_HW_{hw_model}")

    def get_role_name(self, role_value):
        """Convert device role enum value to human-readable name"""
        role_mapping = {
            0: "CLIENT", 1: "CLIENT_MUTE", 2: "ROUTER", 3: "ROUTER_CLIENT",
            4: "REPEATER", 5: "TRACKER", 6: "SENSOR", 7: "TAK",
            8: "CLIENT_HIDDEN", 9: "LOST_AND_FOUND", 10: "TAK_TRACKER", 11: "ROUTER_LATE"
        }
        if role_value is None:
            return "CLIENT"
        try:
            role_int = int(role_value)
        except (ValueError, TypeError):
            if isinstance(role_value, str):
                return role_value
            return "CLIENT"
        return role_mapping.get(role_int, f"UNKNOWN_ROLE_{role_int}")

    def print_stats(self):
        """Print statistics with robust connection health check"""
        runtime = datetime.now() - self.start_time
        
        # Check database health
        db_healthy = self.db.check_connection_health() if self.db else False
        health_status = "✅" if db_healthy else "❌"
        
        logger.info(f"Stats - Runtime: {runtime}, Received: {self.stats['received']}, "
                   f"Stored: {self.stats['stored']}, Errors: {self.stats['errors']}, "
                   f"Nodes Created: {self.stats['nodes_created']}, Nodes Updated: {self.stats['nodes_updated']}, "
                   f"NODEINFO Triggers: {self.stats['nodeinfo_triggers']}, "
                   f"Direct Updates: {self.stats['direct_updates']}, Pending: {self.stats['pending']}, "
                   f"DB Health: {health_status}")

    def run(self):
        """Main run loop with improved error handling"""
        logger.info("Starting Meshtastic Collector v1.3.2...")
        
        if not self.connect():
            logger.error("Failed to connect. Exiting.")
            return False
            
        self.running = True
        last_stats_time = time.time()
        
        try:
            while self.running:
                time.sleep(1)
                
                # Print stats every minute
                if time.time() - last_stats_time >= 60:
                    self.print_stats()
                    last_stats_time = time.time()
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.cleanup()
            
        return True

    def cleanup(self):
        """Clean shutdown"""
        self.running = False
        if self.interface:
            self.interface.close()
        if self.db:
            self.db.close_all_connections()
        logger.info("Cleanup completed")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self.running = False

def main():
    # Setup signal handlers
    collector = MeshtasticCollector()
    signal.signal(signal.SIGINT, collector.signal_handler)
    signal.signal(signal.SIGTERM, collector.signal_handler)
    
    try:
        collector.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
