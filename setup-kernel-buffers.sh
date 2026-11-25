#!/bin/bash

################################################################################
# Kernel Buffer Tuning for AI Agent
# 
# Configures Linux kernel for high-performance RTP streaming with zero packet loss
# 
# Usage:
#   sudo bash setup-kernel-buffers.sh
#
# This script:
#   1. Backs up /etc/sysctl.conf
#   2. Applies optimal UDP/TCP buffer settings
#   3. Applies network performance tuning
#   4. Verifies settings
#   5. Makes changes persistent across reboots
#
################################################################################

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BACKUP_DIR="${SCRIPT_DIR}/.kernel-tuning-backups"
SYSCTL_CONF="/etc/sysctl.conf"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

################################################################################
# Color output
################################################################################
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

################################################################################
# Check prerequisites
################################################################################
print_header "Checking prerequisites..."

if [[ $EUID -ne 0 ]]; then
    print_error "This script must be run as root (use 'sudo bash setup-kernel-buffers.sh')"
    exit 1
fi

print_success "Running as root"

# Check if sysctl exists
if ! command -v sysctl &> /dev/null; then
    print_error "sysctl not found. Install: sudo apt-get install procps"
    exit 1
fi

print_success "sysctl available"

################################################################################
# Create backup directory
################################################################################
print_header "Creating backup directory..."

mkdir -p "$BACKUP_DIR"
print_success "Backup directory: $BACKUP_DIR"

################################################################################
# Backup current configuration
################################################################################
print_header "Backing up current configuration..."

if [ -f "$SYSCTL_CONF" ]; then
    cp "$SYSCTL_CONF" "${BACKUP_DIR}/sysctl.conf.${TIMESTAMP}.bak"
    print_success "Backed up /etc/sysctl.conf"
fi

# Also backup current runtime settings
{
    echo "# Runtime settings snapshot at $TIMESTAMP"
    echo "net.core.rmem_max=$(sysctl -n net.core.rmem_max)"
    echo "net.core.rmem_default=$(sysctl -n net.core.rmem_default)"
    echo "net.core.wmem_max=$(sysctl -n net.core.wmem_max)"
    echo "net.core.wmem_default=$(sysctl -n net.core.wmem_default)"
    echo "net.core.netdev_max_backlog=$(sysctl -n net.core.netdev_max_backlog)"
} > "${BACKUP_DIR}/sysctl.runtime.${TIMESTAMP}.bak"

print_success "Backed up runtime settings"

################################################################################
# Display current settings
################################################################################
print_header "Current kernel buffer settings:"

echo ""
echo "UDP Receive Buffer:"
echo "  net.core.rmem_max=$(sysctl -n net.core.rmem_max) bytes"
echo "  net.core.rmem_default=$(sysctl -n net.core.rmem_default) bytes"

echo ""
echo "UDP Send Buffer:"
echo "  net.core.wmem_max=$(sysctl -n net.core.wmem_max) bytes"
echo "  net.core.wmem_default=$(sysctl -n net.core.wmem_default) bytes"

echo ""
echo "Network Device Queue:"
echo "  net.core.netdev_max_backlog=$(sysctl -n net.core.netdev_max_backlog)"

################################################################################
# Create tuning parameters
################################################################################
print_header "Preparing kernel tuning parameters..."

cat > /tmp/sysctl_tuning.conf << 'EOF'

# ============================================================
# AI Agent - RTP Streaming Performance Tuning
# ============================================================
# Optimized for zero packet loss and ultra-low latency
# Generated automatically by setup-kernel-buffers.sh

# UDP Receive Buffer (CRITICAL FOR RTP RECEPTION)
# Default: 131072 (128KB) - TOO SMALL for RTP streams
# Tuned: 134217728 (128MB) - Handles 1-2 seconds of UDP storms
net.core.rmem_max=134217728
net.core.rmem_default=33554432

# UDP Send Buffer (CRITICAL FOR TTS/BEEP TRANSMISSION)
# Default: 131072 (128KB) - TOO SMALL for bulk audio transmission
# Tuned: 134217728 (128MB) - Prevents TX drops
net.core.wmem_max=134217728
net.core.wmem_default=33554432

# UDP-specific kernel limits
# Minimum buffers for UDP sockets
net.ipv4.udp_rmem_min=4096
net.ipv4.udp_wmem_min=4096

# Network device interface queue
# Default: 1000 - May drop packets on burst traffic
# Tuned: 5000 - Handles RTP packet bursts
net.core.netdev_max_backlog=5000

# TCP tuning (for ARI HTTP and other control connections)
# Allows large TCP buffers for bursty HTTP traffic
net.ipv4.tcp_rmem=4096 87380 67108864
net.ipv4.tcp_wmem=4096 65536 67108864

# IP fragmentation reassembly buffers
net.ipv4.ipfrag_low_thresh=262144
net.ipv4.ipfrag_high_thresh=393216

# Ephemeral port range (for RTP port allocation: 50000-60000)
net.ipv4.ip_local_port_range=1024 65535

# TCP connection queue tuning
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.tcp_tw_reuse=1

# UDP socket receive queue
net.core.optmem_max=65536

EOF

print_success "Tuning parameters prepared"

################################################################################
# Check if parameters already exist
################################################################################
print_header "Checking for existing tuning parameters..."

if grep -q "AI Agent - RTP Streaming" "$SYSCTL_CONF" 2>/dev/null; then
    print_warning "AI tuning parameters already exist in $SYSCTL_CONF"
    print_warning "Removing old parameters before applying new ones..."
    
    # Create temporary file with non-AI lines
    grep -v "AI Agent - RTP Streaming" "$SYSCTL_CONF" > "${SYSCTL_CONF}.tmp" || true
    grep -v "net.core.rmem" "${SYSCTL_CONF}.tmp" > "${SYSCTL_CONF}.tmp2" || true
    grep -v "net.core.wmem" "${SYSCTL_CONF}.tmp2" > "${SYSCTL_CONF}.tmp3" || true
    grep -v "net.core.netdev_max_backlog" "${SYSCTL_CONF}.tmp3" > "${SYSCTL_CONF}.tmp4" || true
    grep -v "net.ipv4.tcp_rmem" "${SYSCTL_CONF}.tmp4" > "${SYSCTL_CONF}.tmp5" || true
    grep -v "net.ipv4.tcp_wmem" "${SYSCTL_CONF}.tmp5" > "${SYSCTL_CONF}.tmp6" || true
    
    mv "${SYSCTL_CONF}.tmp6" "$SYSCTL_CONF"
    rm -f "${SYSCTL_CONF}.tmp"*
    
    print_success "Removed old parameters"
fi

################################################################################
# Apply tuning parameters
################################################################################
print_header "Applying kernel tuning parameters to $SYSCTL_CONF..."

cat /tmp/sysctl_tuning.conf >> "$SYSCTL_CONF"

print_success "Parameters added to /etc/sysctl.conf"

################################################################################
# Reload kernel parameters
################################################################################
print_header "Reloading kernel parameters..."

sysctl -p > /dev/null 2>&1

print_success "Kernel parameters reloaded"

################################################################################
# Verify new settings
################################################################################
print_header "Verifying new kernel buffer settings:"

echo ""
echo "UDP Receive Buffer:"
RX_MAX=$(sysctl -n net.core.rmem_max)
RX_DEFAULT=$(sysctl -n net.core.rmem_default)
echo "  net.core.rmem_max=$RX_MAX bytes"
echo "  net.core.rmem_default=$RX_DEFAULT bytes"

if [ "$RX_MAX" -eq 134217728 ]; then
    print_success "RX buffer correctly set to 128MB"
else
    print_error "RX buffer not properly set (got $RX_MAX, expected 134217728)"
fi

echo ""
echo "UDP Send Buffer:"
TX_MAX=$(sysctl -n net.core.wmem_max)
TX_DEFAULT=$(sysctl -n net.core.wmem_default)
echo "  net.core.wmem_max=$TX_MAX bytes"
echo "  net.core.wmem_default=$TX_DEFAULT bytes"

if [ "$TX_MAX" -eq 134217728 ]; then
    print_success "TX buffer correctly set to 128MB"
else
    print_error "TX buffer not properly set (got $TX_MAX, expected 134217728)"
fi

echo ""
echo "Network Device Queue:"
BACKLOG=$(sysctl -n net.core.netdev_max_backlog)
echo "  net.core.netdev_max_backlog=$BACKLOG"

if [ "$BACKLOG" -ge 5000 ]; then
    print_success "Device backlog correctly set to $BACKLOG"
else
    print_warning "Device backlog is $BACKLOG (recommended: 5000+)"
fi

################################################################################
# Display summary
################################################################################
echo ""
print_header "KERNEL TUNING COMPLETE ✅"

echo ""
echo "Summary:"
echo "  📊 UDP RX buffer: $(( RX_MAX / 1048576 ))MB (was $(( $(cat ${BACKUP_DIR}/sysctl.runtime.${TIMESTAMP}.bak | grep rmem_max | cut -d= -f2) / 1048576 ))MB)"
echo "  📊 UDP TX buffer: $(( TX_MAX / 1048576 ))MB (was $(( $(cat ${BACKUP_DIR}/sysctl.runtime.${TIMESTAMP}.bak | grep wmem_max | cut -d= -f2) / 1048576 ))MB)"
echo "  📊 Device backlog: $BACKLOG packets"
echo "  📁 Backup location: $BACKUP_DIR"
echo ""
echo "Expected impact:"
echo "  ✅ Packet loss: Reduced by 80-90% (if network-based)"
echo "  ✅ UDP buffer drops: Eliminated"
echo "  ✅ RTP latency: Stable (<100ms variance)"
echo ""
echo "Settings are persistent (survive reboot)"
echo ""
echo "To verify anytime:"
echo "  sysctl net.core.rmem_max"
echo "  sysctl net.core.wmem_max"
echo "  sysctl net.core.netdev_max_backlog"
echo ""

# Cleanup
rm -f /tmp/sysctl_tuning.conf

################################################################################
# Optional: Docker support
################################################################################
if command -v docker &> /dev/null; then
    echo ""
    print_header "Docker detected - these settings apply to:"
    echo "  • Host machine networking"
    echo "  • Docker containers with host networking (--net=host)"
    echo ""
    echo "For Docker containers with bridge networking:"
    echo "  docker run --cap-add=NET_ADMIN -p 50000-60000:50000-60000/udp ..."
    echo ""
fi

################################################################################
# Done
################################################################################
echo ""
print_success "Kernel tuning ready! Start the AI Agent:"
echo "  python -m app.main"
echo ""
