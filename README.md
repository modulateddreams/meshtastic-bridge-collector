# Meshtastic Bridge Collector

> Production-ready LoRa bridge collector for Meshtastic mesh networks with direct NODEINFO processing and TimescaleDB integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Meshtastic](https://img.shields.io/badge/Meshtastic-Compatible-green.svg)](https://meshtastic.org/)

## 🌐 Overview

A production-ready Python collector that captures local Meshtastic mesh traffic via LoRa and stores comprehensive metrics in TimescaleDB. Designed to complement MQTT-based collection systems for complete mesh network monitoring.

**Part of the NSW Meshtastic monitoring ecosystem: [dash.nswmesh.au](https://dash.nswmesh.au)**

## 🎯 Key Features

- **Real-time LoRa packet capture** with direct NODEINFO processing
- **Intelligent node discovery** across multi-hop mesh networks  
- **Official Meshtastic portnum compliance** and complete schema support
- **TimescaleDB integration** via SSH tunnel for time-series analysis
- **Production-grade error handling**, logging, and auto-restart capabilities
- **Grafana-ready data structure** for mesh network visualization

## 📊 What It Captures

- **Node identification** and hardware details
- **Packet metrics** (SNR, RSSI, hop counts, routing info)
- **Telemetry data** (battery, GPS, device stats)
- **Message routing** and store-forward operations

## 🚀 Why Use This?

Traditional MQTT-based Meshtastic monitoring misses local mesh traffic that doesn't reach the internet. This bridge collector captures **everything** your local LoRa device can hear, providing comprehensive mesh network visibility.

### Before vs After
- **Before**: ~38% node discovery rate (MQTT-only)
- **After**: 70-90%+ discovery rate (direct NODEINFO processing)

## 📋 Prerequisites

- **Hardware**: Meshtastic device connected via USB
- **OS**: Debian/Ubuntu Linux (tested on Debian 12)
- **Database**: TimescaleDB (local or remote)
- **Python**: 3.8+

## ⚡ Quick Start

1. **Clone and setup**:
   ```bash
   git clone https://github.com/yourusername/meshtastic-bridge-collector.git
   cd meshtastic-bridge-collector
   
   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure database**:
   ```bash
   # Import database schema
   psql -h your-db-host -U postgres -d meshtastic -f sql/schema.sql
   ```

3. **Configure collector**:
   ```bash
   cp collector/config.example.py collector/config.py
   # Edit config.py with your database credentials
   ```

4. **Run collector**:
   ```bash
   python3 collector/meshtastic-collector.py
   ```

For detailed setup instructions, see [INSTALLATION.md](docs/INSTALLATION.md).

## 📊 Database Schema

The collector creates two main tables:

- **`node_details`**: Node information (names, hardware, location)
- **`mesh_packet_metrics`**: Time-series packet data (TimescaleDB hypertable)

## 🔧 Production Deployment

The collector includes systemd service files for production deployment:

- **SSH tunnel service** for secure database connections
- **Collector service** with auto-restart and logging
- **Comprehensive monitoring** and statistics

## 📈 Monitoring & Visualization

Works seamlessly with:
- **Grafana** dashboards
- **TimescaleDB** time-series queries
- **Custom monitoring** scripts

## 🤝 Contributing

Contributions welcome! Please read our contributing guidelines and submit pull requests.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Meshtastic Project** for the excellent mesh networking platform
- **NSW Meshtastic Community** for testing and feedback
- **TimescaleDB** for powerful time-series data storage

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/meshtastic-bridge-collector/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/meshtastic-bridge-collector/discussions)
- **NSW Mesh**: [nswmesh.au](https://nswmesh.au)

---

**Made with ❤️ for the Meshtastic community**

## 🎯 Hardware Model Mapping Enhancement

### New Features
- **Readable Hardware Names**: Converts numeric hardware IDs to human-readable device names
- **Complete Device Support**: Supports 85+ Meshtastic hardware models
- **Improved Dashboard**: Shows "RAK4631", "ESP32_S3_PICO", "HELTEC_V3" instead of numbers

### Performance Improvement
- **Before**: ~38% nodes with readable hardware names
- **After**: 98.7% nodes with readable hardware names
- **Production Tested**: Mesh infrastructure with 239+ nodes

### Supported Hardware Models
- **RAK Devices**: RAK4631, RAK11200, RAK11310, RAK4631_WISBLOCK
- **Heltec Devices**: HELTEC_V3, HELTEC_V2_0, HELTEC_WIRELESS_TRACKER, HELTEC_MESH_NODE_T114
- **ESP32 Variants**: ESP32_S3_PICO, T_DECK, T_ECHO, TBEAM variants
- **M5Stack Family**: CORE2, CORES3, CARDPUTER, and more
- **Others**: SEEDSTUDIO_XIAO_S3, TRACKER_T1000_E, PORTDUINO, and 70+ more

### Database Enhancement
The hardware_model field now stores readable names instead of numeric enum values

### Implementation
The enhancement uses a comprehensive hardware model mapping function that converts Meshtastic protobuf enum values to human-readable device names across all NODEINFO processing paths.
