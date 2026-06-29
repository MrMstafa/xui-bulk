#!/bin/bash
# X-UI Bulk Manager

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}[*] Checking privileges...${NC}"
if [ "$EUID" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

echo -e "${YELLOW}[*] Installing dependencies (Python, venv, curl)...${NC}"
$SUDO apt-get update -y -qq
$SUDO apt-get install -y python3 python3-pip python3-venv curl wget -qq

VENV_DIR="/opt/xui-bulk-env"
SCRIPT_PATH="/opt/xui-bulk-env/xui_bulk.py"
WRAPPER_PATH="/usr/local/bin/xui-bulk"
GITHUB_RAW_URL="https://raw.githubusercontent.com/MrMstafa/xui-bulk/main/xui_bulk.py"

echo -e "${YELLOW}[*] Setting up isolated Python environment...${NC}"
if [ ! -d "$VENV_DIR" ]; then
    $SUDO python3 -m venv "$VENV_DIR"
fi

echo -e "${YELLOW}[*] Installing CLI UI (Rich)...${NC}"
$SUDO $VENV_DIR/bin/pip install rich --quiet

echo -e "${YELLOW}[*] Downloading application logic...${NC}"

TMP_FILE=$(mktemp)
$SUDO curl -sL "$GITHUB_RAW_URL" -o "$TMP_FILE"

if [ $? -eq 0 ] && grep -q "import sqlite3" "$TMP_FILE"; then
    $SUDO mv "$TMP_FILE" "$SCRIPT_PATH"
    $SUDO chmod +x "$SCRIPT_PATH"

    echo "#!/bin/bash" | $SUDO tee $WRAPPER_PATH > /dev/null
    echo "$VENV_DIR/bin/python3 $SCRIPT_PATH \"\$@\"" | $SUDO tee -a $WRAPPER_PATH > /dev/null
    $SUDO chmod +x $WRAPPER_PATH

    echo -e "${GREEN}[+] Installation successful!${NC}"
    echo -e "${GREEN}[+] You can now run the tool anytime by typing: ${YELLOW}xui-bulk${NC}"
    sleep 2
    xui-bulk
else
    echo -e "${RED}[!] Download failed or file is corrupted.${NC}"
    rm -f "$TMP_FILE"
    exit 1
fi
