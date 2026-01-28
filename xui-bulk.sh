#!/bin/bash
# X-UI Bulk Installer

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

echo -e "${YELLOW}>>> نصب پیش‌نیازها ...${NC}"
$SUDO apt-get update -y -qq
$SUDO apt-get install -y python3 python3-pip curl wget -qq

# نصب Rich هوشمند
if ! python3 -c "import rich" &>/dev/null; then
    $SUDO pip3 install rich &>/dev/null
    if ! python3 -c "import rich" &>/dev/null; then
        $SUDO pip3 install rich --break-system-packages &>/dev/null
    fi
fi

# دانلود
# ⚠️ لینک خود را جایگزین کنید
GITHUB_RAW_URL="https://raw.githubusercontent.com/MrMstafa/xui-bulk/main/xui_bulk.py"
INSTALL_PATH="/usr/local/bin/xui-bulk"

echo -e "${YELLOW}>>> دانلود برنامه ...${NC}"
$SUDO curl -sL "$GITHUB_RAW_URL" -o "$INSTALL_PATH"

if [ $? -eq 0 ]; then
    $SUDO chmod +x "$INSTALL_PATH"
    echo -e "${GREEN}✅ تکمیل شد درحال اجرا ...${NC}"
    sleep 1
    $SUDO python3 "$INSTALL_PATH"
else
    echo -e "${RED}❌ دانلود ناموفق${NC}"
fi
