-- Meshtastic Bridge Collector Database Schema
-- Compatible with TimescaleDB and PostgreSQL

-- Enable TimescaleDB extension (if using TimescaleDB)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Node details table
-- Stores information about mesh nodes
CREATE TABLE IF NOT EXISTS node_details (
    node_id VARCHAR PRIMARY KEY,                 -- Unique node identifier
    short_name VARCHAR,                          -- Short display name (e.g., "PLT7")
    long_name VARCHAR,                           -- Full display name (e.g., "PLT777")
    hardware_model VARCHAR,                      -- Device hardware model
    role VARCHAR,                                -- Node role (CLIENT, ROUTER, etc.)
    mqtt_status VARCHAR,                         -- MQTT connection status
    longitude INTEGER,                           -- GPS longitude (scaled)
    latitude INTEGER,                            -- GPS latitude (scaled)
    altitude INTEGER,                            -- GPS altitude (meters)
    precision INTEGER,                           -- GPS precision indicator
    created_at TIMESTAMP NOT NULL,              -- Record creation time
    updated_at TIMESTAMP NOT NULL               -- Last update time
);

-- Packet metrics table (TimescaleDB hypertable)
-- Stores time-series packet data
CREATE TABLE IF NOT EXISTS mesh_packet_metrics (
    time TIMESTAMPTZ NOT NULL,                  -- Packet timestamp (primary time dimension)
    source_id VARCHAR NOT NULL,                 -- Source node ID
    destination_id VARCHAR,                     -- Destination node ID (NULL for broadcast)
    portnum VARCHAR,                            -- Meshtastic portnum (TELEMETRY_APP, NODEINFO_APP, etc.)
    packet_id BIGINT,                           -- Unique packet identifier
    channel INTEGER,                            -- Radio channel number
    rx_time BIGINT,                             -- Raw receive timestamp
    rx_snr FLOAT,                               -- Signal-to-noise ratio
    rx_rssi INTEGER,                            -- Received signal strength indicator
    hop_limit INTEGER,                          -- Remaining hop count
    hop_start INTEGER,                          -- Initial hop count
    want_ack BOOLEAN,                           -- Acknowledgment requested
    via_mqtt BOOLEAN,                           -- Received via MQTT
    message_size_bytes INTEGER,                 -- Payload size in bytes
    
    -- Foreign key constraint
    CONSTRAINT fk_source_node 
        FOREIGN KEY (source_id) 
        REFERENCES node_details(node_id) 
        ON DELETE CASCADE
);

-- Create TimescaleDB hypertable (if using TimescaleDB)
-- This enables time-series optimizations
-- SELECT create_hypertable('mesh_packet_metrics', 'time', if_not_exists => TRUE);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mesh_packet_metrics_time 
    ON mesh_packet_metrics (time DESC);

CREATE INDEX IF NOT EXISTS idx_mesh_packet_metrics_source 
    ON mesh_packet_metrics (source_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_mesh_packet_metrics_portnum 
    ON mesh_packet_metrics (portnum, time DESC);

CREATE INDEX IF NOT EXISTS idx_mesh_packet_metrics_snr_rssi 
    ON mesh_packet_metrics (rx_snr, rx_rssi) 
    WHERE rx_snr IS NOT NULL AND rx_rssi IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_node_details_names 
    ON node_details (long_name, short_name);

CREATE INDEX IF NOT EXISTS idx_node_details_updated 
    ON node_details (updated_at DESC);

-- Views for common queries
CREATE OR REPLACE VIEW recent_packets AS
SELECT 
    p.time,
    n.long_name as source_name,
    n.short_name as source_short,
    p.destination_id,
    p.portnum,
    p.rx_snr,
    p.rx_rssi,
    p.hop_limit,
    p.hop_start,
    p.message_size_bytes
FROM mesh_packet_metrics p
LEFT JOIN node_details n ON p.source_id = n.node_id
WHERE p.time > NOW() - INTERVAL '1 hour'
ORDER BY p.time DESC;

CREATE OR REPLACE VIEW node_statistics AS
SELECT 
    n.node_id,
    n.long_name,
    n.short_name,
    n.hardware_model,
    COUNT(p.packet_id) as total_packets,
    AVG(p.rx_snr) as avg_snr,
    AVG(p.rx_rssi) as avg_rssi,
    MAX(p.time) as last_seen,
    MIN(p.time) as first_seen
FROM node_details n
LEFT JOIN mesh_packet_metrics p ON n.node_id = p.source_id
WHERE p.time > NOW() - INTERVAL '24 hours'
GROUP BY n.node_id, n.long_name, n.short_name, n.hardware_model
ORDER BY total_packets DESC;

CREATE OR REPLACE VIEW mesh_health AS
SELECT 
    COUNT(DISTINCT p.source_id) as active_nodes_24h,
    COUNT(p.packet_id) as total_packets_24h,
    AVG(p.rx_snr) as avg_snr_24h,
    AVG(p.rx_rssi) as avg_rssi_24h,
    COUNT(DISTINCT CASE WHEN p.time > NOW() - INTERVAL '1 hour' THEN p.source_id END) as active_nodes_1h,
    COUNT(CASE WHEN p.time > NOW() - INTERVAL '1 hour' THEN p.packet_id END) as total_packets_1h
FROM mesh_packet_metrics p
WHERE p.time > NOW() - INTERVAL '24 hours';

-- Data retention policy (TimescaleDB only)
-- Automatically drop data older than specified period
-- SELECT add_retention_policy('mesh_packet_metrics', INTERVAL '90 days', if_not_exists => TRUE);

-- Continuous aggregates for performance (TimescaleDB only)
-- Pre-compute hourly statistics
-- CREATE MATERIALIZED VIEW IF NOT EXISTS mesh_metrics_hourly
-- WITH (timescaledb.continuous) AS
-- SELECT 
--     time_bucket('1 hour', time) AS time_hour,
--     source_id,
--     portnum,
--     COUNT(*) as packet_count,
--     AVG(rx_snr) as avg_snr,
--     AVG(rx_rssi) as avg_rssi,
--     AVG(message_size_bytes) as avg_size
-- FROM mesh_packet_metrics
-- GROUP BY time_hour, source_id, portnum;

-- SELECT add_continuous_aggregate_policy('mesh_metrics_hourly',
--     start_offset => INTERVAL '1 day',
--     end_offset => INTERVAL '1 hour',
--     schedule_interval => INTERVAL '1 hour',
--     if_not_exists => TRUE);

-- Grant permissions for collector user
-- GRANT SELECT, INSERT, UPDATE ON node_details TO meshtastic_collector;
-- GRANT SELECT, INSERT ON mesh_packet_metrics TO meshtastic_collector;
-- GRANT SELECT ON recent_packets, node_statistics, mesh_health TO meshtastic_collector;
