import psycopg2
from psycopg2 import pool
import time
import logging
import os

class RobustDBConnection:
    def __init__(self, host=None, port=None, database=None, user=None, password=None, max_retries=5):
        # Use environment variables as defaults
        self.connection_params = {
            'host': host or os.getenv('DB_HOST', 'localhost'),
            'port': port or int(os.getenv('DB_PORT', 5432)),
            'database': database or os.getenv('DB_NAME', 'meshtastic'),
            'user': user or os.getenv('DB_USER', 'postgres'),
            'password': password or os.getenv('DB_PASSWORD', 'p4ZwvXvkBBhlFcb1pOWRkDxbx')
        }
        self.max_retries = max_retries
        self.connection_pool = None
        self.create_pool()
    
    def create_pool(self):
        """Create connection pool with automatic reconnection"""
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                1, 20,  # min=1, max=20 connections
                **self.connection_params,
                # Important: These settings handle disconnections
                keepalives_idle=30,      # Send keepalive every 30 seconds
                keepalives_interval=5,   # Retry keepalive every 5 seconds
                keepalives_count=5,      # Give up after 5 failed keepalives
                connect_timeout=10       # Timeout connection attempts
            )
            logging.info("Database connection pool created successfully")
        except Exception as e:
            logging.error(f"Failed to create connection pool: {e}")
            raise

    def get_connection(self):
        """Get connection with retry logic"""
        for attempt in range(self.max_retries):
            try:
                if self.connection_pool:
                    conn = self.connection_pool.getconn()
                    # Test the connection
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                    return conn
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logging.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    self.recreate_pool()
                else:
                    raise
        return None

    def recreate_pool(self):
        """Recreate the connection pool"""
        try:
            if self.connection_pool:
                self.connection_pool.closeall()
        except:
            pass
        self.create_pool()

    def execute_with_retry(self, query, params=None):
        """Execute query with automatic retry on connection failure"""
        for attempt in range(self.max_retries):
            conn = None
            try:
                conn = self.get_connection()
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if query.strip().upper().startswith('SELECT'):
                        return cur.fetchall()
                    conn.commit()
                    return True
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logging.error(f"Database operation failed (attempt {attempt + 1}): {e}")
                if conn:
                    try:
                        self.connection_pool.putconn(conn, close=True)
                    except:
                        pass
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
            except Exception as e:
                if conn:
                    self.connection_pool.putconn(conn)
                raise
            finally:
                if conn:
                    try:
                        self.connection_pool.putconn(conn)
                    except:
                        pass

    def check_connection_health(self):
        """Periodically check connection health"""
        try:
            result = self.execute_with_retry("SELECT NOW()")
            logging.debug("Database connection healthy")
            return True
        except Exception as e:
            logging.error(f"Database connection unhealthy: {e}")
            return False

    def close_all_connections(self):
        """Close all connections in the pool"""
        try:
            if self.connection_pool:
                self.connection_pool.closeall()
                logging.info("All database connections closed")
        except Exception as e:
            logging.error(f"Error closing connections: {e}")
