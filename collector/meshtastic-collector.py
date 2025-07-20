#!/usr/bin/env python3
"""
Meshtastic Data Collector - Version 3.5 Final - Complete Fixed Version
Sydney Bridge Node Implementation for NSW Mesh Network

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
        self.db_conn = None
        self.pending_nodes = {}
        self.last_node_check = {}  # Track when we last checked each node
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
        
        # Database configuration - UPDATE THESE VALUES
        self.db_config = {
            'host': 'localhost',        # SSH tunnel endpoint
            'port': 5432,              # SSH tunnel port  
            'database': 'meshtastic',  # UPDATE: Your database name
            'user': 'postgres',        # UPDATE: Your database user
            'password': 'p4ZwvXvkBBhlFcb1pOWRkDxbx'  # UPDATE: Your password
        }
        
        # Device configuration
        self.device_path = '/dev/ttyACM0'  # UPDATE: Your device path if different
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        pub.subscribe(self.on_receive, "meshtastic.receive")
        pub.subscribe(self.on_connection, "meshtastic.connection")
        
    def _signal_handler(self, signum, frame):
        logger.info("Shutdown signal received")
        self.running = False
        
    def on_receive(self, packet, interface):
        try:
            self.stats['packets_received'] += 1
            logger.info(f"Received packet from {packet.get('fromId', 'unknown')} "
                       f"to {packet.get('toId', 'unknown')} "
                       f"(SNR: {packet.get('rxSnr', 'N/A')}, RSSI: {packet.get('rxRssi', 'N/A')})")
            
            # For NODEINFO packets, parse payload directly (NEW IN v3.5)
            decoded = packet.get('decoded', {})
            if decoded.get('portnum') == 'NODEINFO_APP':
                from_id = packet.get('from')
                if from_id:
                    self.stats['nodeinfo_triggers'] += 1
                    # Parse NODEINFO payload directly instead of waiting for library
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
        """NEW IN v3.5: Process NODEINFO payload directly from packet"""
        try:
            # Check if there's a payload in the decoded data
            payload = decoded.get('payload')
            if not payload:
                logger.debug(f"NODEINFO packet from {node_id} has no payload")
                return False
            
            # Debug logging to understand payload format
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
                    hw_model = get_hardware_model_name(payload.hw_model)
                logger.debug(f"Method 1 (protobuf attrs): {long_name} / {short_name}")
                
            elif isinstance(payload, dict):
                # Dictionary format
                long_name = payload.get('long_name') or payload.get('longName')
                short_name = payload.get('short_name') or payload.get('shortName') 
                hw_model = get_hardware_model_name(payload.get('hw_model') or payload.get('hwModel', 0))
                logger.debug(f"Method 2 (dict): {long_name} / {short_name}")
                
            else:
                # Try to decode as User protobuf message
                try:
                    from meshtastic import mesh_pb2
                    if isinstance(payload, bytes):
                        user_info = mesh_pb2.User()
                        user_info.ParseFromString(payload)
                        long_name = user_info.long_name
                        short_name = user_info.short_name
                        hw_model = get_hardware_model_name(user_info.hw_model) if user_info.hw_model else 'UNKNOWN'
                        logger.debug(f"Method 3 (protobuf bytes): {long_name} / {short_name}")
                    else:
                        # Try string representation parsing as last resort
                        payload_str = str(payload)
                        logger.debug(f"Method 4 attempt - payload string: {payload_str}")
                        
                        # Look for patterns in string representation
                        if 'long_name:' in payload_str and 'short_name:' in payload_str:
                            import re
                            long_match = re.search(r'long_name:\s*"([^"]+)"', payload_str)
                            short_match = re.search(r'short_name:\s*"([^"]+)"', payload_str)
                            if long_match and short_match:
                                long_name = long_match.group(1)
                                short_name = short_match.group(1)
                                logger.debug(f"Method 4 (regex): {long_name} / {short_name}")
                        
                        if not long_name:
                            logger.debug(f"Unknown payload format for NODEINFO from {node_id}: {type(payload)}")
                            logger.debug(f"Payload content: {payload}")
                            return False
                            
                except Exception as e:
                    logger.debug(f"Failed to parse NODEINFO payload from {node_id}: {e}")
                    return False
            
            # Validate we got real names
            if not long_name or not short_name:
                logger.debug(f"NODEINFO from {node_id} missing names: long='{long_name}' short='{short_name}'")
                return False
            
            # Don't update if we just got temporary names
            if long_name.startswith('Node-') or short_name.startswith('N'):
                logger.debug(f"NODEINFO from {node_id} has temporary names, skipping")
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
                str(node_id),
                short_name,
                long_name,
                hw_model,
                'CLIENT',  # Default role
                'unknown',
                None, None, None, None,  # Position fields
                datetime.now(timezone.utc),
                datetime.now(timezone.utc)
            ))
            
            logger.info(f"🎉 DIRECT NODEINFO UPDATE: {node_id} -> {long_name} ({short_name}) [{hw_model}]")
            self.stats['nodes_updated'] += 1
            self.stats['nodeinfo_direct_updates'] += 1
            
            # Remove from pending nodes
            if node_id in self.pending_nodes:
                del self.pending_nodes[node_id]
                
            return True
                
        except Exception as e:
            logger.error(f"Error processing NODEINFO payload for {node_id}: {e}")
            logger.error(f"Payload type: {type(decoded.get('payload'))}")
            logger.error(f"Decoded keys: {decoded.keys()}")
            return False
            
    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        logger.info(f"Connection event: {topic}")
        
    def connect(self):
        try:
            self.db_conn = psycopg2.connect(**self.db_config)
            self.db_conn.autocommit = True
            logger.info("Database connected")
            
            self.interface = meshtastic.serial_interface.SerialInterface(self.device_path)
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
            if not hasattr(self.interface, 'nodes'):
                return
                
            # Check if we have this node in the interface
            if node_id in self.interface.nodes:
                node_info = self.interface.nodes[node_id]
                user = node_info.get('user', {})
                long_name = user.get('longName')
                short_name = user.get('shortName')
                
                if long_name and not long_name.startswith('Node-'):
                    # We have a real name! Update the database
                    cursor = self.db_conn.cursor()
                    cursor.execute("""
                        UPDATE node_details 
                        SET long_name = %s, short_name = %s, updated_at = %s
                        WHERE node_id = %s AND long_name LIKE 'Node-%'
                    """, (
                        long_name,
                        short_name or f'N{str(node_id)[-4:]}',
                        datetime.now(timezone.utc),
                        str(node_id)
                    ))
                    
                    if cursor.rowcount > 0:
                        logger.info(f"🔄 Updated node name via fallback: {node_id} -> {long_name}")
                        self.stats['nodes_updated'] += 1
                        
                        # Remove from pending list
                        if node_id in self.pending_nodes:
                            del self.pending_nodes[node_id]
                        return True
                    else:
                        logger.debug(f"Node {node_id} already has proper name")
                else:
                    logger.debug(f"Node {node_id} in interface but no proper name: {long_name}")
            else:
                logger.debug(f"Node {node_id} not found in interface nodes")
                
        except Exception as e:
            logger.error(f"Error checking node {node_id}: {e}")
            
        return False
            
    def ensure_node_exists(self, node_id):
        """Modified in v3.5: Less aggressive with temporary names"""
        if not node_id:
            return
            
        try:
            cursor = self.db_conn.cursor()
            node_id_str = str(node_id)
            
            # Check if node already exists
            cursor.execute("SELECT long_name FROM node_details WHERE node_id = %s", (node_id_str,))
            existing = cursor.fetchone()
            
            if existing:
                # Node exists, don't overwrite with temporary name
                logger.debug(f"Node {node_id_str} already exists: {existing[0]}")
                return
            
            # First check if we can get real info from interface
            node_info = {}
            if hasattr(self.interface, 'nodes') and node_id in self.interface.nodes:
                node_info = self.interface.nodes[node_id]
            
            user = node_info.get('user', {})
            position = node_info.get('position', {})
            long_name = user.get('longName')
            short_name = user.get('shortName')
            
            # Only create with temporary name if we don't have real info
            if not long_name or long_name.startswith('Node-'):
                long_name = f'Node-{node_id_str}'
                self.pending_nodes[node_id] = time.time()
                
            if not short_name or short_name.startswith('N'):
                short_name = f'N{node_id_str[-4:]}'
            
            # Create new node
            cursor.execute("""
                INSERT INTO node_details (
                    node_id, short_name, long_name, hardware_model, role,
                    mqtt_status, longitude, latitude, altitude, precision,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                node_id_str,
                short_name,
                long_name,
                get_hardware_model_name(user.get('hwModel', 0)),
                user.get('role', 'CLIENT'),
                'unknown',
                position.get('longitude'),
                position.get('latitude'),
                position.get('altitude'),
                None,
                datetime.now(timezone.utc),
                datetime.now(timezone.utc)
            ))
            
            if long_name.startswith('Node-'):
                logger.info(f"Created temporary node: {node_id_str} (awaiting NODEINFO)")
                self.stats['nodes_created'] += 1
            else:
                logger.info(f"Created node with real name: {node_id_str} ({long_name})")
                self.stats['nodes_updated'] += 1
                
        except psycopg2.IntegrityError:
            # Node already exists, ignore
            pass
        except Exception as e:
            logger.error(f"Error creating/updating node: {e}")
            
    def bulk_check_nodes(self):
        """FIXED: Periodically check all nodes in interface for updates"""
        if not hasattr(self.interface, 'nodes'):
            return
            
        updated_count = 0
        checked_count = 0
        
        # Check a subset of interface nodes each time
        for node_id_key, node_info in self.interface.nodes.items():
            checked_count += 1
            if checked_count > 20:  # Limit to 20 checks per cycle
                break
                
            try:
                # Convert hex node ID to integer for database lookup
                if isinstance(node_id_key, str) and node_id_key.startswith('!'):
                    # Remove ! prefix and convert hex to int
                    node_id = int(node_id_key[1:], 16)
                elif isinstance(node_id_key, int):
                    node_id = node_id_key
                else:
                    logger.debug(f"Skipping bulk check for unknown node ID format: {node_id_key}")
                    continue
                
                user = node_info.get('user', {})
                long_name = user.get('longName')
                
                if long_name and not long_name.startswith('Node-'):
                    # Check if this node is still temporary in database
                    cursor = self.db_conn.cursor()
                    cursor.execute("""
                        UPDATE node_details 
                        SET long_name = %s, short_name = %s, updated_at = %s
                        WHERE node_id = %s AND long_name LIKE 'Node-%'
                    """, (
                        long_name,
                        user.get('shortName') or f'N{str(node_id)[-4:]}',
                        datetime.now(timezone.utc),
                        str(node_id)
                    ))
                    
                    if cursor.rowcount > 0:
                        logger.info(f"🔄 Updated node from bulk check: {node_id} ({node_id_key}) -> {long_name}")
                        self.stats['nodes_updated'] += 1
                        updated_count += 1
                        
                        if node_id in self.pending_nodes:
                            del self.pending_nodes[node_id]
                            
            except Exception as e:
                logger.debug(f"Error in bulk update for {node_id_key}: {e}")
        
        if updated_count > 0:
            logger.info(f"Bulk check updated {updated_count} nodes from {checked_count} checked")
                    
    def process_packet(self, packet):
        try:
            from_id = packet.get('from')
            to_id = packet.get('to')
            
            if not from_id:
                return
                
            self.ensure_node_exists(from_id)
            if to_id and to_id != 4294967295:
                self.ensure_node_exists(to_id)
                
            decoded = packet.get('decoded', {})
            rx_time = packet.get('rxTime', int(time.time()))
            rx_snr = packet.get('rxSnr', 0.0)
            rx_rssi = packet.get('rxRssi', 0)
            hop_limit = packet.get('hopLimit', 0)
            hop_start = packet.get('hopStart', 0)
            want_ack = packet.get('wantAck', False)
            via_mqtt = packet.get('viaMqtt', False)
            packet_id = packet.get('id', 0)
            
            payload_size = 0
            if 'payload' in decoded:
                payload = decoded['payload']
                if isinstance(payload, bytes):
                    payload_size = len(payload)
                elif isinstance(payload, str):
                    payload_size = len(payload.encode('utf-8'))
            
            # Handle portnum according to official Meshtastic specification
            # See: https://meshtastic.org/docs/development/firmware/portnum/
            portnum = decoded.get('portnum', 0)
            if portnum == 0:
                portnum = 'UNKNOWN_APP'  # Official portnum 0 - unrecognized packets
            elif isinstance(portnum, int) and portnum >= 256:
                portnum = 'PRIVATE_APP'  # Custom applications (256-511 range)
            # else: keep string values as-is (TELEMETRY_APP, NODEINFO_APP, etc.)
            
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
                datetime.fromtimestamp(rx_time, timezone.utc),
                str(from_id),
                str(to_id) if to_id else None,
                portnum,
                packet_id,
                packet.get('channel', 0),
                rx_time,
                rx_snr,
                rx_rssi,
                hop_limit,
                hop_start,
                want_ack,
                via_mqtt,
                payload_size
            ))
            
            self.stats['packets_stored'] += 1
            
            display_name = f"Node-{from_id}"
            if hasattr(self.interface, 'nodes') and from_id in self.interface.nodes:
                user = self.interface.nodes[from_id].get('user', {})
                if user.get('longName'):
                    display_name = user.get('longName')
            
            logger.info(f"Stored packet: {display_name} ({str(from_id)}) -> {str(to_id)}, "
                       f"Type: {portnum}, Size: {payload_size}")
            
        except Exception as e:
            self.stats['packets_errors'] += 1
            logger.error(f"Error processing packet: {e}")
            
    def print_stats(self):
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
        logger.info("Starting Meshtastic data collection...")
        logger.info("Version: 3.5 Final - Complete Fixed Version")
        logger.info("Bridge Node: Sydney (BNS1) - NSW Mesh Network")
        
        if not self.connect():
            return False
            
        self.running = True
        logger.info("Collection started - waiting for packets...")
        
        last_stats_time = time.time()
        last_bulk_check = time.time()
        
        try:
            while self.running:
                time.sleep(1)
                
                # Do bulk node checks every 60 seconds
                if time.time() - last_bulk_check > 60:
                    self.bulk_check_nodes()
                    last_bulk_check = time.time()
                
                if time.time() - last_stats_time > 60:
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

# Hardware model mapping dictionary
HARDWARE_MODELS = {
    0: "UNSET", 1: "TLORA_V2", 2: "TLORA_V1", 3: "TLORA_V2_1_1P6",
    4: "TBEAM", 5: "HELTEC_UNSUPPORTED", 6: "TBEAM_V0P7", 7: "T_ECHO",
    8: "TLORA_V1_1P3", 9: "RAK4631", 10: "HELTEC_V2_0", 11: "HELTEC_V2_1",
    12: "HELTEC_V1", 13: "LILYGO_TBEAM_S3_CORE", 14: "RAK11200", 15: "NANO_G1",
    16: "TLORA_V2_1_1P8", 17: "TLORA_T3_S3", 18: "NANO_G1_EXPLORER", 19: "NANO_G2_ULTRA",
    20: "LORA_RELAY_V1", 21: "STATION_G1", 22: "RAK11310", 23: "SENSELORA_RP2040",
    24: "SENSELORA_S3", 25: "CANARYONE", 26: "RP2040_LORA", 27: "STATION_G2",
    28: "LORA_RELAY_V2", 29: "ENCODER", 30: "5GHOUL", 31: "HELTEC_V3",
    32: "HELTEC_WSL_V3", 33: "BETAFPV_2400_TX", 34: "BETAFPV_900_NANO_TX", 35: "RPI_PICO",
    36: "HELTEC_WIRELESS_TRACKER", 37: "HELTEC_WIRELESS_PAPER", 38: "T_DECK", 39: "T_WATCH_S3",
    40: "PICOMPUTER_S3", 41: "HELTEC_HT62", 42: "EBYTE_ESP32_S3", 43: "ESP32_S3_PICO",
    44: "CHATTER_2", 45: "HELTEC_WIRELESS_PAPER_V1_0", 46: "HELTEC_WIRELESS_TRACKER_V1_0", 47: "UNPHONE",
    48: "TD_LORAC", 49: "CDEBYTE_EORA_S3", 50: "TWC_MESH_V4", 51: "NRF52_UNKNOWN",
    52: "PORTDUINO", 53: "ANDROID_SIM", 54: "DIY_V1", 55: "NRF52840_PCA10059",
    56: "DR_DEV", 57: "M5STACK", 58: "M5STACK_CORE2", 59: "M5STACK_M5STICKC",
    60: "M5STACK_M5STICKC_PLUS", 61: "M5STACK_M5STICKC_PLUS2", 62: "M5STACK_M5ATOM", 63: "M5STACK_M5NANO",
    64: "M5STACK_STAMP_S3", 65: "M5STACK_CORE_INK", 66: "M5STACK_PAPER", 67: "M5STACK_CORES3",
    68: "M5STACK_CORE_BASIC", 69: "M5STACK_CORE_FIRE", 70: "M5STACK_CARDPUTER", 71: "SEEDSTUDIO_XIAO_S3",
    72: "RADIOMASTER_900_BANDIT_NANO", 73: "HELTEC_CAPSULE_SENSOR_V3", 74: "HELTEC_VISION_MASTER_T190", 75: "HELTEC_VISION_MASTER_E213",
    76: "HELTEC_VISION_MASTER_E290", 77: "HELTEC_MESH_NODE_T114", 78: "SENSECAP_INDICATOR", 79: "TRACKER_T1000_E",
    80: "RAK3172", 81: "RAK11310_WISBLOCK", 82: "PRIVATE_HW", 83: "RAK4631_WISBLOCK", 255: "RESERVED"
}

def get_hardware_model_name(hardware_value):
    """Convert hardware enum value to readable name"""
    if isinstance(hardware_value, str):
        try:
            hardware_value = int(hardware_value)
        except ValueError:
            return hardware_value  # Already a string name
    return HARDWARE_MODELS.get(hardware_value, f"UNKNOWN_HW_{hardware_value}")
