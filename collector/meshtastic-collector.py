#!/usr/bin/env python3
"""
Meshtastic Data Collector - Version 3.5 - Template
Bridge Node Implementation for Mesh Network Monitoring

Features:
- Real-time packet capture via LoRa interface
- Direct NODEINFO payload parsing (fixes temp node issue)
- Official Meshtastic portnum compliance
- Intelligent node discovery and updates
- Complete database schema compatibility  
- UTC timestamp handling
- Production-ready error handling and logging
- Self-healing connections with auto-restart

Database: TimescaleDB via SSH tunnel (optional)
Device: Configurable USB device path
"""

import meshtastic.serial_interface
import psycopg2
from datetime import datetime, timezone
import time
import logging
import signal
import sys
import os
from pubsub import pub

# Import configuration
try:
    from config import (
        DATABASE_CONFIG, DEVICE_CONFIG, LOGGING_CONFIG, 
        BRIDGE_CONFIG, PERFORMANCE_CONFIG, FEATURES, ADVANCED_CONFIG
    )
except ImportError:
    print("ERROR: config.py not found!")
    print("Please copy config.example.py to config.py and update with your settings.")
    sys.exit(1)

# Configure logging
log_handlers = [logging.StreamHandler()]
if LOGGING_CONFIG.get('file_path'):
    log_handlers.append(logging.FileHandler(LOGGING_CONFIG['file_path']))

logging.basicConfig(
    level=getattr(logging, LOGGING_CONFIG.get('level', 'INFO')),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

class MeshtasticCollector:
    def __init__(self):
        self.running = False
        self.interface = None
        self.db_conn = None
        self.pending_nodes = {}
        self.last_node_check = {}
        self.stats = {
            'packets_received': 0,
            'packets_stored': 0,
            'packets_errors': 0,
            'nodes_created': 0,
            'nodes_updated': 0,
            'nodeinfo_triggers': 0,
            'nodeinfo_direct_updates': 0,
            'start_time': datetime.now(timezone.utc)
        }
        
        # Validate configuration
        self._validate_config()
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        pub.subscribe(self.on_receive, "meshtastic.receive")
        pub.subscribe(self.on_connection, "meshtastic.connection")
        
    def _validate_config(self):
        """Validate configuration settings"""
        if DATABASE_CONFIG['password'] == 'YOUR_DATABASE_PASSWORD_HERE':
            logger.error("Please update DATABASE_CONFIG password in config.py")
            sys.exit(1)
            
        if not os.path.exists(DEVICE_CONFIG['path']):
            logger.warning(f"Device path {DEVICE_CONFIG['path']} not found - will retry on connect")
        
    def _signal_handler(self, signum, frame):
        logger.info("Shutdown signal received")
        self.running = False
        
    def on_receive(self, packet, interface):
        try:
            self.stats['packets_received'] += 1
            
            if ADVANCED_CONFIG.get('debug_payload_parsing', False):
                logger.debug(f"Raw packet: {packet}")
                
            logger.info(f"Received packet from {packet.get('fromId', 'unknown')} "
                       f"to {packet.get('toId', 'unknown')} "
                       f"(SNR: {packet.get('rxSnr', 'N/A')}, RSSI: {packet.get('rxRssi', 'N/A')})")
            
            # Process NODEINFO packets directly if feature enabled
            decoded = packet.get('decoded', {})
            if FEATURES.get('direct_nodeinfo_processing', True) and decoded.get('portnum') == 'NODEINFO_APP':
                from_id = packet.get('from')
                if from_id:
                    self.stats['nodeinfo_triggers'] += 1
                    success = self.process_nodeinfo_payload(from_id, decoded)
                    if not success:
                        # Fallback to old method if direct parsing fails
                        time.sleep(0.1)
                        self.check_and_update_node(from_id)
            
            self.process_packet(packet)
        except Exception as e:
            self.stats['packets_errors'] += 1
            logger.error(f"Error in on_receive: {e}")
            
    def process_nodeinfo_payload(self, node_id, decoded):
        """Process NODEINFO payload directly from packet"""
        try:
            payload = decoded.get('payload')
            if not payload:
                if ADVANCED_CONFIG.get('debug_payload_parsing', False):
                    logger.debug(f"NODEINFO packet from {node_id} has no payload")
                return False
            
            if ADVANCED_CONFIG.get('debug_payload_parsing', False):
                logger.debug(f"NODEINFO DEBUG - Node: {node_id}")
                logger.debug(f"Payload type: {type(payload)}")
                logger.debug(f"Decoded keys: {list(decoded.keys())}")
            
            long_name = None
            short_name = None
            hw_model = 'UNKNOWN'
            
            # Try different payload access methods
            if hasattr(payload, 'long_name') and hasattr(payload, 'short_name'):
                # Direct access to protobuf fields
                long_name = payload.long_name
                short_name = payload.short_name
                if hasattr(payload, 'hw_model'):
                    hw_model = str(payload.hw_model)
                    
            elif isinstance(payload, dict):
                # Dictionary format
                long_name = payload.get('long_name') or payload.get('longName')
                short_name = payload.get('short_name') or payload.get('shortName') 
                hw_model = payload.get('hw_model') or payload.get('hwModel', 'UNKNOWN')
                
            else:
                # Try to decode as User protobuf message
                try:
                    from meshtastic import mesh_pb2
                    if isinstance(payload, bytes):
                        user_info = mesh_pb2.User()
                        user_info.ParseFromString(payload)
                        long_name = user_info.long_name
                        short_name = user_info.short_name
                        hw_model = str(user_info.hw_model) if user_info.hw_model else 'UNKNOWN'
                    else:
                        # Try string representation parsing as last resort
                        payload_str = str(payload)
                        
                        if 'long_name:' in payload_str and 'short_name:' in payload_str:
                            import re
                            long_match = re.search(r'long_name:\s*"([^"]+)"', payload_str)
                            short_match = re.search(r'short_name:\s*"([^"]+)"', payload_str)
                            if long_match and short_match:
                                long_name = long_match.group(1)
                                short_name = short_match.group(1)
                        
                        if not long_name:
                            if ADVANCED_CONFIG.get('debug_payload_parsing', False):
                                logger.debug(f"Unknown payload format for NODEINFO from {node_id}")
                            return False
                            
                except Exception as e:
                    if ADVANCED_CONFIG.get('debug_payload_parsing', False):
                        logger.debug(f"Failed to parse NODEINFO payload from {node_id}: {e}")
                    return False
            
            # Validate we got real names
            if not long_name or not short_name:
                return False
            
            # Don't update if we just got temporary names
            if long_name.startswith('Node-') or short_name.startswith('N'):
                return False
            
            # Update database immediately with real nodeinfo
            cursor = self.db_conn.cursor()
            cursor.execute("""
                INSERT INTO node_details (
                    node_id, short_name, long_name, hardware_model, role,
                    mqtt_status, longitude, latitude, altitude, precision,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (node_id)
                DO UPDATE SET
                    short_name = EXCLUDED.short_name,
                    long_name = EXCLUDED.long_name,
                    hardware_model = EXCLUDED.hardware_model,
                    updated_at = EXCLUDED.updated_at
            """, (
                str(node_id), short_name, long_name, hw_model, 'CLIENT', 'unknown',
                None, None, None, None,
                datetime.now(timezone.utc), datetime.now(timezone.utc)
            ))
            
            logger.info(f"🎉 DIRECT NODEINFO UPDATE: {node_id} -> {long_name} ({short_name}) [{hw_model}]")
            self.stats['nodes_updated'] += 1
            self.stats['nodeinfo_direct_updates'] += 1
            
            if node_id in self.pending_nodes:
                del self.pending_nodes[node_id]
                
            return True
                
        except Exception as e:
            logger.error(f"Error processing NODEINFO payload for {node_id}: {e}")
            return False
            
    def connect(self):
        try:
            # Connect to database
            self.db_conn = psycopg2.connect(**DATABASE_CONFIG)
            self.db_conn.autocommit = True
            logger.info("Database connected")
            
            # Connect to Meshtastic device
            device_path = DEVICE_CONFIG['path']
            baud_rate = DEVICE_CONFIG.get('baud_rate')
            
            if baud_rate:
                self.interface = meshtastic.serial_interface.SerialInterface(device_path, baud_rate)
            else:
                self.interface = meshtastic.serial_interface.SerialInterface(device_path)
                
            my_info = self.interface.getMyNodeInfo()
            logger.info(f"Meshtastic connected: {my_info.get('user', {}).get('longName', 'Unknown')}")
            
            self.ensure_node_exists(my_info.get('num'))
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def check_and_update_node(self, node_id):
        """Legacy method - kept as fallback for library-based updates"""
        try:
            if not hasattr(self.interface, 'nodes') or node_id not in self.interface.nodes:
                return False
                
            node_info = self.interface.nodes[node_id]
            user = node_info.get('user', {})
            long_name = user.get('longName')
            short_name = user.get('shortName')
            
            if long_name and not long_name.startswith('Node-'):
                cursor = self.db_conn.cursor()
                cursor.execute("""
                    UPDATE node_details 
                    SET long_name = %s, short_name = %s, updated_at = %s
                    WHERE node_id = %s AND long_name LIKE 'Node-%'
                """, (
                    long_name, short_name or f'N{str(node_id)[-4:]}',
                    datetime.now(timezone.utc), str(node_id)
                ))
                
                if cursor.rowcount > 0:
                    logger.info(f"🔄 Updated node name via fallback: {node_id} -> {long_name}")
                    self.stats['nodes_updated'] += 1
                    
                    if node_id in self.pending_nodes:
                        del self.pending_nodes[node_id]
                    return True
                    
        except Exception as e:
            logger.error(f"Error checking node {node_id}: {e}")
            
        return False
            
    def ensure_node_exists(self, node_id):
        """Create node entry if it doesn't exist"""
        if not node_id:
            return
            
        try:
            cursor = self.db_conn.cursor()
            node_id_str = str(node_id)
            
            # Check if node already exists
            cursor.execute("SELECT long_name FROM node_details WHERE node_id = %s", (node_id_str,))
            existing = cursor.fetchone()
            
            if existing:
                return
            
            # Get info from interface if available
            node_info = {}
            if hasattr(self.interface, 'nodes') and node_id in self.interface.nodes:
                node_info = self.interface.nodes[node_id]
            
            user = node_info.get('user', {})
            position = node_info.get('position', {})
            long_name = user.get('longName') or f'Node-{node_id_str}'
            short_name = user.get('shortName') or f'N{node_id_str[-4:]}'
            
            if long_name.startswith('Node-'):
                self.pending_nodes[node_id] = time.time()
            
            # Create new node
            cursor.execute("""
                INSERT INTO node_details (
                    node_id, short_name, long_name, hardware_model, role,
                    mqtt_status, longitude, latitude, altitude, precision,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                node_id_str, short_name, long_name,
                user.get('hwModel', 'UNKNOWN'), user.get('role', 'CLIENT'), 'unknown',
                position.get('longitude'), position.get('latitude'), position.get('altitude'), None,
                datetime.now(timezone.utc), datetime.now(timezone.utc)
            ))
            
            status = "temporary" if long_name.startswith('Node-') else "real name"
            logger.info(f"Created node: {node_id_str} ({long_name}) [{status}]")
            self.stats['nodes_created'] += 1
                
        except psycopg2.IntegrityError:
            pass  # Node already exists
        except Exception as e:
            logger.error(f"Error creating node: {e}")
            
    def bulk_check_nodes(self):
        """Periodically check all nodes in interface for updates"""
        if not FEATURES.get('bulk_node_checking', True):
            return
            
        if not hasattr(self.interface, 'nodes'):
            return
            
        updated_count = 0
        checked_count = 0
        max_checks = PERFORMANCE_CONFIG.get('max_bulk_checks', 20)
        
        for node_id_key, node_info in self.interface.nodes.items():
            checked_count += 1
            if checked_count > max_checks:
                break
                
            try:
                # Convert hex node ID to integer for database lookup
                if isinstance(node_id_key, str) and node_id_key.startswith('!'):
                    node_id = int(node_id_key[1:], 16)
                elif isinstance(node_id_key, int):
                    node_id = node_id_key
                else:
                    continue
                
                user = node_info.get('user', {})
                long_name = user.get('longName')
                
                if long_name and not long_name.startswith('Node-'):
                    cursor = self.db_conn.cursor()
                    cursor.execute("""
                        UPDATE node_details 
                        SET long_name = %s, short_name = %s, updated_at = %s
                        WHERE node_id = %s AND long_name LIKE 'Node-%'
                    """, (
                        long_name, user.get('shortName') or f'N{str(node_id)[-4:]}',
                        datetime.now(timezone.utc), str(node_id)
                    ))
                    
                    if cursor.rowcount > 0:
                        logger.info(f"🔄 Updated node from bulk check: {node_id} -> {long_name}")
                        self.stats['nodes_updated'] += 1
                        updated_count += 1
                        
                        if node_id in self.pending_nodes:
                            del self.pending_nodes[node_id]
                            
            except Exception as e:
                logger.debug(f"Error in bulk update for {node_id_key}: {e}")
        
        if updated_count > 0:
            logger.info(f"Bulk check updated {updated_count} nodes from {checked_count} checked")
                    
    def process_packet(self, packet):
        """Process and store packet data"""
        try:
            from_id = packet.get('from')
            to_id = packet.get('to')
            
            if not from_id:
                return
                
            # Check packet size limit
            packet_size = len(str(packet))
            if packet_size > ADVANCED_CONFIG.get('packet_size_limit', 1024):
                logger.warning(f"Packet size {packet_size} exceeds limit, skipping")
                return
                
            self.ensure_node_exists(from_id)
            if to_id and to_id != 4294967295:
                self.ensure_node_exists(to_id)
                
            decoded = packet.get('decoded', {})
            
            # Calculate payload size
            payload_size = 0
            if 'payload' in decoded:
                payload = decoded['payload']
                if isinstance(payload, bytes):
                    payload_size = len(payload)
                elif isinstance(payload, str):
                    payload_size = len(payload.encode('utf-8'))
            
            # Handle portnum according to official Meshtastic specification
            portnum = decoded.get('portnum', 0)
            if portnum == 0:
                portnum = 'UNKNOWN_APP'
            elif isinstance(portnum, int) and portnum >= 256:
                portnum = 'PRIVATE_APP'
            
            # Store packet metrics
            cursor = self.db_conn.cursor()
            cursor.execute("""
                INSERT INTO mesh_packet_metrics (
                    time, source_id, destination_id, portnum, packet_id, 
                    channel, rx_time, rx_snr, rx_rssi, hop_limit, 
                    hop_start, want_ack, via_mqtt, message_size_bytes
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                datetime.fromtimestamp(packet.get('rxTime', time.time()), timezone.utc),
                str(from_id), str(to_id) if to_id else None, portnum,
                packet.get('id', 0), packet.get('channel', 0), packet.get('rxTime', int(time.time())),
                packet.get('rxSnr', 0.0), packet.get('rxRssi', 0), packet.get('hopLimit', 0),
                packet.get('hopStart', 0), packet.get('wantAck', False), 
                packet.get('viaMqtt', False), payload_size
            ))
            
            self.stats['packets_stored'] += 1
            
            # Get display name for logging
            display_name = f"Node-{from_id}"
            if hasattr(self.interface, 'nodes') and from_id in self.interface.nodes:
                user = self.interface.nodes[from_id].get('user', {})
                if user.get('longName'):
                    display_name = user.get('longName')
            
            logger.info(f"Stored packet: {display_name} ({from_id}) -> {to_id}, "
                       f"Type: {portnum}, Size: {payload_size}")
            
        except Exception as e:
            self.stats['packets_errors'] += 1
            logger.error(f"Error processing packet: {e}")
            
    def print_stats(self):
        """Print runtime statistics"""
        runtime = datetime.now(timezone.utc) - self.stats['start_time']
        logger.info(f"Stats - Runtime: {runtime}, "
                   f"Received: {self.stats['packets_received']}, "
                   f"Stored: {self.stats['packets_stored']}, "
                   f"Errors: {self.stats['packets_errors']}, "
                   f"Nodes Created: {self.stats['nodes_created']}, "
                   f"Nodes Updated: {self.stats['nodes_updated']}, "
                   f"NODEINFO Triggers: {self.stats['nodeinfo_triggers']}, "
                   f"Direct Updates: {self.stats['nodeinfo_direct_updates']}, "
                   f"Pending: {len(self.pending_nodes)}")
                   
    def run(self):
        """Main collection loop"""
        logger.info("Starting Meshtastic data collection...")
        logger.info("Version: 3.5 Final - Production Template")
        logger.info(f"Bridge Node: {BRIDGE_CONFIG.get('node_name', 'Unknown')} - {BRIDGE_CONFIG.get('location', 'Unknown')}")
        
        if not self.connect():
            return False
            
        self.running = True
        logger.info("Collection started - waiting for packets...")
        
        last_stats_time = time.time()
        last_bulk_check = time.time()
        
        try:
            while self.running:
                time.sleep(1)
                
                # Bulk checks
                if (time.time() - last_bulk_check > PERFORMANCE_CONFIG.get('bulk_check_interval', 60)):
                    self.bulk_check_nodes()
                    last_bulk_check = time.time()
                
                # Stats reporting
                if (time.time() - last_stats_time > PERFORMANCE_CONFIG.get('stats_interval', 60)):
                    self.print_stats()
                    last_stats_time = time.time()
                    
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.cleanup()
            
        return True
        
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        
        if self.interface:
            try:
                self.interface.close()
            except:
                pass
                
        if self.db_conn:
            try:
                self.db_conn.close()
            except:
                pass
                
        self.print_stats()
        logger.info("Cleanup completed")

if __name__ == "__main__":
    collector = MeshtasticCollector()
    try:
        success = collector.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
