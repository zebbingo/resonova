#!/bin/bash
# Grant remote access to chatbot user
mysql -u root <<EOF
GRANT ALL PRIVILEGES ON ZebbieDb.* TO 'chatbot'@'%';
FLUSH PRIVILEGES;
EOF
echo "Remote access granted for chatbot user"
