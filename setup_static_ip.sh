#!/bin/bash
# Smart Indoor Garden - give the Raspberry Pi a FIXED (static) IP address.
#
# Run on the Pi, in a Terminal, inside the SMART-GARDEN folder:
#   sudo bash setup_static_ip.sh                -> keep the IP the Pi has right now
#   sudo bash setup_static_ip.sh 192.168.1.50   -> use this IP instead
#   sudo bash setup_static_ip.sh --undo         -> back to automatic (DHCP)
#
# It also writes the IP into PI_IP in config.py, which laptop_server.py uses.
# The fixed IP applies to the Wi-Fi the Pi is connected to now.

set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo:  sudo bash setup_static_ip.sh"
  exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/config.py"

IFACE=$(ip route show default | awk '/^default/ {print $5; exit}')
GATEWAY=$(ip route show default | awk '/^default/ {print $3; exit}')
if [ -z "$IFACE" ] || [ -z "$GATEWAY" ]; then
  echo "The Pi is not connected to a network. Connect it to the Wi-Fi first, then run this again."
  exit 1
fi
CIDR=$(ip -o -4 addr show dev "$IFACE" | awk '{print $4; exit}')   # e.g. 192.168.1.23/24
CURRENT_IP="${CIDR%/*}"
PREFIX="${CIDR#*/}"

use_nm() { command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; }

update_config() {
  if [ -f "$CONFIG" ]; then
    sed -i "s/^PI_IP = .*/PI_IP = \"$1\"/" "$CONFIG"
    # sudo would otherwise leave config.py owned by root (Thonny couldn't save it)
    if [ -n "$SUDO_USER" ]; then chown "$SUDO_USER":"$SUDO_USER" "$CONFIG"; fi
    echo "config.py updated: PI_IP = \"$1\""
  fi
}

# ---------------------------------------------------------------- undo ------
if [ "$1" = "--undo" ]; then
  if use_nm; then
    CON=$(nmcli -g GENERAL.CONNECTION device show "$IFACE")
    nmcli con mod "$CON" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
    nmcli con up "$CON" >/dev/null
  else
    sed -i '/# smart-garden static ip/,/# end smart-garden/d' /etc/dhcpcd.conf
    systemctl restart dhcpcd
  fi
  echo "Back to automatic IP (DHCP). Reconnect may take a few seconds."
  exit 0
fi

# ---------------------------------------------------------------- set -------
WANT="${1:-$CURRENT_IP}"

# Validate: a real IPv4 address, on the same network as the router
if ! python3 - "$WANT" "$GATEWAY" "$PREFIX" <<'EOF'
import ipaddress, sys
want, gw, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    ip = ipaddress.ip_address(want)
except ValueError:
    print("'%s' is not a valid IP address (example: 192.168.1.50)." % want); sys.exit(1)
net = ipaddress.ip_network("%s/%s" % (gw, prefix), strict=False)
if ip not in net:
    print("%s is not on this Wi-Fi's network (%s). Pick one like %s." % (want, net, str(gw).rsplit(".", 1)[0] + ".50")); sys.exit(1)
if ip in (net.network_address, net.broadcast_address) or str(ip) == gw:
    print("%s can't be used (it's the router or a reserved address)." % want); sys.exit(1)
EOF
then
  exit 1
fi

# Don't steal an address another device is already using
if [ "$WANT" != "$CURRENT_IP" ] && ping -c 2 -W 1 "$WANT" >/dev/null 2>&1; then
  echo "$WANT is already used by another device. Choose a different number."
  exit 1
fi

echo "Network:  $IFACE   router: $GATEWAY   current IP: $CURRENT_IP"
echo "Setting fixed IP: $WANT/$PREFIX"

if use_nm; then
  CON=$(nmcli -g GENERAL.CONNECTION device show "$IFACE")
  if [ -z "$CON" ]; then
    echo "Could not find the active connection for $IFACE."
    exit 1
  fi
  nmcli con mod "$CON" ipv4.method manual ipv4.addresses "$WANT/$PREFIX" \
        ipv4.gateway "$GATEWAY" ipv4.dns "$GATEWAY 8.8.8.8"
  nmcli con up "$CON" >/dev/null
  echo "Saved in connection \"$CON\" (NetworkManager)."
else
  # Older Raspberry Pi OS (Bullseye and earlier) uses dhcpcd
  sed -i '/# smart-garden static ip/,/# end smart-garden/d' /etc/dhcpcd.conf
  cat >> /etc/dhcpcd.conf <<EOF
# smart-garden static ip
interface $IFACE
static ip_address=$WANT/$PREFIX
static routers=$GATEWAY
static domain_name_servers=$GATEWAY 8.8.8.8
# end smart-garden
EOF
  systemctl restart dhcpcd
  echo "Saved in /etc/dhcpcd.conf."
fi

update_config "$WANT"

echo ""
echo "Done. The Pi's fixed address is:  http://$WANT:5000"
echo "On the LAPTOP, set the same in config.py:   PI_IP = \"$WANT\""
echo "(or run:  python laptop_server.py $WANT)"
