#!/bin/bash

# ============================================================
# SQLite3 3.45.0 Upgrade for CentOS (Production)
# Run this as ROOT on your CentOS production server
# ============================================================

echo "=========================================="
echo "SQLite3 Upgrade for CentOS"
echo "=========================================="

# Check current version
echo ""
echo "Current SQLite3 version:"
sqlite3 --version

# Install dependencies
echo ""
echo "Installing build dependencies..."
yum install -y gcc readline-devel zlib-devel wget make tcl-devel

# Download latest SQLite3
echo ""
echo "Downloading SQLite3 3.45.0..."
cd /tmp
wget https://www.sqlite.org/2024/sqlite-autoconf-3450300.tar.gz

# Extract and compile
echo ""
echo "Extracting and compiling SQLite3..."
tar xzf sqlite-autoconf-3450300.tar.gz
cd sqlite-autoconf-3450300

./configure --prefix=/usr/local \
    --enable-shared \
    --enable-static \
    --disable-tcl

make -j$(nproc)
make install

# Update library path
echo ""
echo "Updating library configuration..."
echo '/usr/local/lib' > /etc/ld.so.conf.d/sqlite3.conf
ldconfig

# Verify installation
echo ""
echo "New SQLite3 version:"
/usr/local/bin/sqlite3 --version

# Create symlink if needed
echo ""
echo "Creating symlink..."
ln -sf /usr/local/bin/sqlite3 /usr/bin/sqlite3
ln -sf /usr/local/lib/libsqlite3.so.0 /usr/lib64/libsqlite3.so.0 2>/dev/null || true

echo ""
echo "✅ SQLite3 upgrade complete!"
echo ""
echo "Next steps:"
echo "1. Export library path in your startup script or systemd service:"
echo "   export LD_LIBRARY_PATH=/usr/local/lib:\$LD_LIBRARY_PATH"
echo "2. Restart your application"
echo "=========================================="
