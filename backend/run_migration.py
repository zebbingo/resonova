#!/usr/bin/env python3
"""执行数据库迁移脚本 - 创建对话音频追踪中间表"""

import pymysql
import sys
from pathlib import Path

# 读取迁移脚本
migration_file = Path(__file__).parent / "db" / "migrations" / "20260518_add_conversation_audio_tracking.sql"

if not migration_file.exists():
    print(f"❌ 迁移脚本不存在: {migration_file}")
    sys.exit(1)

sql_content = migration_file.read_text(encoding='utf-8')

# 数据库配置（从 chatbot 项目）
import os
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'chatbot'),
    'password': os.getenv('MYSQL_PASSWORD', 'chatbot123'),
    'database': os.getenv('MYSQL_DATABASE', 'ZebbieDb'),
    'charset': 'utf8mb4'
}

print("📋 开始执行数据库迁移...")
print(f"   迁移文件: {migration_file.name}")
print(f"   数据库: {DB_CONFIG['database']}")
print(f"   主机: {DB_CONFIG['host']}")
print(f"   用户: {DB_CONFIG['user']}")
print()

try:
    # 连接数据库
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print(f"📝 执行迁移脚本...")
    print()
    
    # 直接执行整个 SQL 文件（pymysql 支持多条语句）
    try:
        cursor.execute(sql_content)
        print("   ✅ 迁移脚本执行成功")
    except Exception as e:
        # 如果失败，尝试逐条执行
        print(f"   ⚠️  整体执行失败，尝试逐条执行: {str(e)[:100]}")
        
        # 分割 SQL 语句
        statements = sql_content.split(';')
        for i, statement in enumerate(statements, 1):
            statement = statement.strip()
            if not statement or statement.startswith('--'):
                continue
            
            print(f"   [{i}] 执行...")
            try:
                cursor.execute(statement)
                print(f"       ✅ 成功")
            except Exception as e2:
                print(f"       ⚠️  跳过: {str(e2)[:80]}")
    
    # 提交事务
    conn.commit()
    print()
    print("✅ 数据库迁移完成！")
    print()
    print("📊 验证表结构:")
    
    # 验证表是否创建成功
    cursor.execute("SHOW TABLES LIKE 'ZebConversationAudioRef'")
    result = cursor.fetchone()
    
    if result:
        print("   ✅ ZebConversationAudioRef 表已创建")
        
        # 显示表结构
        cursor.execute("DESCRIBE ZebConversationAudioRef")
        columns = cursor.fetchall()
        print()
        print("   表结构:")
        for col in columns:
            print(f"      - {col[0]}: {col[1]}")
    else:
        print("   ❌ ZebConversationAudioRef 表未创建")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"\n❌ 迁移失败: {e}")
    sys.exit(1)
