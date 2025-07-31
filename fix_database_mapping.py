import psycopg2

# Connect to database
conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='meshtastic',
    user='postgres',
    password='p4ZwvXvkBBhlFcb1pOWRkDxbx'
)
cur = conn.cursor()

print("=== Correcting wrongly mapped hardware models ===")

# Fix the main incorrect mappings based on official protobuf
corrections = [
    ("ESP32_S3_PICO", "HELTEC_V3", "43"),  # 43 should be HELTEC_V3, not ESP32_S3_PICO
    ("M5STACK_CORE_FIRE", "M5STACK", "42"),  # 42 should be M5STACK, not M5STACK_CORE_FIRE  
    ("M5STACK_CORE_BASIC", "M5STACK_CORES3", "80"),  # 68 was wrong, 80 is M5STACK_CORES3
    ("SEEDSTUDIO_XIAO_S3", "TRACKER_T1000_E", "71"),  # 71 should be TRACKER_T1000_E
]

total_fixed = 0
for wrong_name, correct_name, hw_id in corrections:
    cur.execute("UPDATE node_details SET hardware_model = %s WHERE hardware_model = %s", (correct_name, wrong_name))
    if cur.rowcount > 0:
        print(f"✅ Fixed {cur.rowcount} nodes: {wrong_name} → {correct_name} (ID {hw_id})")
        total_fixed += cur.rowcount

# Also fix any that might still be numeric
numeric_fixes = [
    ("42", "M5STACK"),
    ("43", "HELTEC_V3"), 
    ("55", "ESP32_S3_PICO"),
    ("68", "HELTEC_VISION_MASTER_E290"),
    ("69", "HELTEC_MESH_NODE_T114"),
    ("71", "TRACKER_T1000_E"),
    ("80", "M5STACK_CORES3"),
    ("81", "SEEED_XIAO_S3"),
]

for hw_id, correct_name in numeric_fixes:
    cur.execute("UPDATE node_details SET hardware_model = %s WHERE hardware_model = %s", (correct_name, hw_id))
    if cur.rowcount > 0:
        print(f"✅ Fixed {cur.rowcount} remaining numeric: {hw_id} → {correct_name}")
        total_fixed += cur.rowcount

conn.commit()
conn.close()
print(f"\n🎉 Total corrections applied: {total_fixed}")
print("Hardware mapping database corrections complete!")
