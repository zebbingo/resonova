#!/usr/bin/env python3
"""执行角色-音频关联中间表迁移"""

import pymysql
from pathlib import Path

# 读取迁移脚本
migration_file = Path(__file__).parent / "db" / "migrations" / "20260520_add_figurine_audio_middle_table.sql"

if not migration_file.exists():
    print(f"❌ 迁移脚本不存在: {migration_file}")
    exit(1)

sql_content = migration_file.read_text(encoding='utf-8')

# 数据库配置（WSL MySQL）
DB_CONFIG = {
    'host': '192.168.52.134',  # WSL IP
    'user': 'chatbot',
    'password': 'chatbot123',
    'database': 'ZebbieDb',
    'charset': 'utf8mb4'
}

print("📋 开始执行角色-音频关联中间表迁移...")
print(f"   迁移文件: {migration_file.name}")
print()

try:
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 执行迁移脚本
    cursor.execute(sql_content)
    conn.commit()
    
    print("✅ 迁移执行成功！")
    print()
    
    # 验证表是否创建
    cursor.execute("SHOW TABLES LIKE 'ZebFigurineAudioRef'")
    result = cursor.fetchone()
    
    if result:
        print("✅ ZebFigurineAudioRef 表已创建")
        print()
        
        # 显示表结构
        cursor.execute("DESCRIBE ZebFigurineAudioRef")
        columns = cursor.fetchall()
        print("   表结构:")
        for col in columns:
            print(f"      - {col[0]}: {col[1]}")
    else:
        print("❌ ZebFigurineAudioRef 表未创建")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"\n❌ 迁移失败: {e}")
    exit(1)
